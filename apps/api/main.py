"""Patent RAG Chatbot v3 — Full-featured FastAPI backend"""
import os, shutil, time, uuid, json
from contextlib import asynccontextmanager
from pathlib import Path
from collections import defaultdict
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

load_dotenv()

from ocr_service import ocr_pdf, chunk_patent
from xml_parser import parse_patent_xml, chunk_patent_xml, scan_xml_directory
import rag_service
import retrieval_v2  # bge-m3 + dense/sparse RRF + reranker (SOTA path)
from auth_service import authenticate, create_token, require_admin, require_user
from webhook import alert_ocr_failure, alert_high_latency

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "patents"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_ROOT = DATA_DIR.parent.resolve()
PROJECT_ROOT = DATA_ROOT.parent.resolve()
UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"

# Rate limit state (simple in-memory)
_rate_counts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
PATENT_LIST_LIMIT = int(os.getenv("PATENT_LIST_LIMIT", "1000"))


def _split_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_uploaded_name(filename: str, allowed_suffixes: set[str]) -> str:
    safe_name = Path((filename or "").strip()).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(400, "Invalid filename")
    if Path(safe_name).suffix.lower() not in allowed_suffixes:
        raise HTTPException(400, f"Only {', '.join(sorted(allowed_suffixes))} files are supported")
    return safe_name


def _stored_file_path(filename: str, allowed_suffixes: set[str] | None = None) -> Path:
    raw_name = (filename or "").strip()
    if raw_name != Path(raw_name).name:
        raise HTTPException(400, "Invalid filename")
    path = (DATA_DIR / raw_name).resolve()
    if path.parent != DATA_DIR.resolve():
        raise HTTPException(400, "Invalid filename")
    if allowed_suffixes and path.suffix.lower() not in allowed_suffixes:
        raise HTTPException(400, "Unsupported file type")
    return path


def _safe_scan_dir(dir_path: str) -> Path:
    candidate = Path(dir_path)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(DATA_ROOT)
    except ValueError as exc:
        raise HTTPException(400, "Scan path must stay within ./data") from exc
    return candidate


@asynccontextmanager
async def lifespan(app: FastAPI):
    rag_service.init()
    yield


_cors_origins = _split_csv_env("CORS_ALLOW_ORIGINS")
_allow_all_origins = _cors_origins == ["*"]

app = FastAPI(title="Patent RAG Chatbot v3", description="台灣專利 OCR/RAG 問答 — GDG on Campus × 昕力資訊", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all_origins else _cors_origins,
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Rate Limit Middleware ───
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host
        now = time.time()
        _rate_counts[ip] = [t for t in _rate_counts[ip] if now - t < 60]
        if len(_rate_counts[ip]) >= RATE_LIMIT:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        _rate_counts[ip].append(now)
    return await call_next(request)


# ─── Models ───
class LoginReq(BaseModel):
    username: str
    password: str

class ChatReq(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    filename_filter: Optional[str] = None
    tag_filter: Optional[str] = None
    doc_number_filter: Optional[str] = None
    history: Optional[list[dict]] = None  # [{query, answer}, ...]
    stream: bool = False
    engine: str = "baseline"  # "baseline" | "m3" | "auto" (classifier picks)
    use_hyde: bool = False    # Hypothetical Document Embeddings query expansion
    auto_route: bool = False  # if true, ignore engine/use_hyde and let _classify_query decide

class FeedbackReq(BaseModel):
    query_log_id: int = Field(gt=0)
    rating: int = Field(ge=-1, le=1)  # -1=down, 1=up
    comment: str = ""

    @field_validator("rating")
    @classmethod
    def _validate_rating(cls, value: int) -> int:
        if value not in (-1, 1):
            raise ValueError("rating must be -1 or 1")
        return value

class CompareReq(BaseModel):
    doc_a: str
    doc_b: str


# ─── Auth ───
@app.post("/api/auth/login")
async def login(req: LoginReq):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(user), "user": user}


# ─── Shared PDF ingest pipeline ───
async def _ingest_pdf(file: UploadFile, ocr_engine: str, reprocess: bool, tag: str) -> dict:
    safe_name = _normalize_uploaded_name(file.filename, {".pdf"})
    t0 = time.time()
    save_path = DATA_DIR / safe_name

    if reprocess and save_path.exists():
        try:
            rag_service.get_qdrant().delete(
                collection_name=rag_service.COLLECTION,
                points_selector={"filter": {"must": [{"key": "filename", "match": {"value": safe_name}}]}},
            )
        except Exception:
            pass

    with open(save_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    await file.close()

    ocr_result = ocr_pdf(str(save_path), engine=ocr_engine)
    if not ocr_result.get("pages"):
        alert_ocr_failure(safe_name, "No pages extracted")
        raise HTTPException(422, "OCR failed")

    chunks = chunk_patent(ocr_result)
    if not chunks:
        raise HTTPException(422, "No chunks generated")

    count = rag_service.upsert_chunks(chunks, tag=tag)
    doc_info = {
        "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdf::{safe_name}")), "filename": safe_name,
        "total_pages": ocr_result["total_pages"], "chunks_created": count,
        "ocr_applied": ocr_result.get("ocr_applied", False),
        "ocr_engine": ocr_result.get("ocr_engine", ""),
        "file_size_kb": ocr_result.get("file_size_kb", 0),
        "source_type": "pdf",
    }
    rag_service.log_document(doc_info)
    return {**doc_info, "latency_ms": round((time.time() - t0) * 1000, 1), "tag": tag}


# ─── Upload (single + reprocess) ───
@app.post("/api/upload")
async def upload(file: UploadFile = File(...), ocr_engine: str = Query("auto"), reprocess: bool = Query(False), tag: str = Query(""), user: dict = Depends(require_user)):
    return await _ingest_pdf(file, ocr_engine, reprocess, tag)


# ─── Batch Upload ───
@app.post("/api/upload/batch")
async def batch_upload(files: list[UploadFile] = File(...), ocr_engine: str = Query("auto"), tag: str = Query(""), user: dict = Depends(require_user)):
    results = []
    for file in files:
        try:
            r = await _ingest_pdf(file, ocr_engine, False, tag)
            results.append({"filename": file.filename, "status": "ok", **r})
        except HTTPException as e:
            results.append({"filename": file.filename, "status": "error", "error": e.detail})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
    return {"results": results, "total": len(results), "success": sum(1 for r in results if r["status"] == "ok")}


# ─── XML Ingest ───
@app.post("/api/ingest/xml")
async def ingest_xml(file: UploadFile = File(...), tag: str = Query(""), user: dict = Depends(require_user)):
    safe_name = _normalize_uploaded_name(file.filename, {".xml"})
    save_path = DATA_DIR / safe_name
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    patent = parse_patent_xml(str(save_path))
    if not patent:
        raise HTTPException(422, "Failed to parse XML")

    chunks = chunk_patent_xml(patent)
    count = rag_service.upsert_chunks(chunks, tag=tag)
    rag_service.log_document({
        "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"xml::{patent['doc_number'] or safe_name}")),
        "filename": safe_name,
        "total_pages": 0,
        "chunks_created": count,
        "ocr_applied": False,
        "ocr_engine": "xml",
        "file_size_kb": round(save_path.stat().st_size / 1024, 1),
        "source_type": "xml",
    })
    return {"filename": safe_name, "doc_number": patent["doc_number"], "title": patent["title_zh"] or patent["title_en"], "chunks": count}


# ─── Scan XML Directory ───
@app.post("/api/ingest/scan")
async def scan_directory(dir_path: str = Query("./data/patents"), tag: str = Query(""), user: dict = Depends(require_admin)):
    safe_dir = _safe_scan_dir(dir_path)
    patents = scan_xml_directory(str(safe_dir))
    total_chunks = 0
    for p in patents:
        chunks = chunk_patent_xml(p)
        total_chunks += rag_service.upsert_chunks(chunks, tag=tag)
    return {"patents_found": len(patents), "total_chunks": total_chunks}


# ─── Chat (non-streaming + streaming) ───
def _expand_with_hyde(query: str) -> str:
    """HyDE: ask the LLM to draft a hypothetical patent claim that would answer
    the question, then embed THAT (concatenated with the query) instead of the
    raw query. Empirically lifts recall on indirect questions where the user's
    vocabulary differs from the document vocabulary."""
    try:
        prompt = (
            "Write a single concise paragraph (max 120 words) that would plausibly "
            "appear in a Taiwan patent claim or abstract directly answering this question. "
            "Use precise patent-style language. Do not preface or apologize.\n\n"
            f"Question: {query}\n\nPassage:"
        )
        import requests as _r
        resp = _r.post(
            f"{os.getenv('OLLAMA_URL','http://localhost:11434')}/api/generate",
            json={"model": os.getenv("LLM_MODEL", "qwen2.5:7b"), "prompt": prompt,
                  "stream": False, "options": {"temperature": 0.1, "num_predict": 220}},
            timeout=60,
        )
        hyp = (resp.json().get("response", "") or "").strip()
        if hyp:
            return f"{query}\n\n{hyp}"
    except Exception:
        pass
    return query


def _search_dispatcher(query: str, top_k: int, engine: str, **filters) -> list[dict]:
    if engine == "m3":
        # Use the same reranker instance the baseline already loaded — saves VRAM
        return retrieval_v2.search_with_rerank(query, top_k=top_k, fetch_k=top_k * 6, reranker=rag_service._reranker, **filters)
    return rag_service.search(query, top_k, **filters)


import re as _re
_IPC_RE = _re.compile(r"\b[A-H]\d{2}[A-Z](?:\s?\d+)(?:/\d+)?\b")     # e.g., F02D 41/00, H10D80/00
_DOCNO_RE = _re.compile(r"\b(?:TW\d{6,}[A-Z]?|[IM]\d{6,})\b")        # e.g., TW202401234A, I918591, M681222


def _classify_query(q: str) -> dict:
    """Cheap rule-based router: decides engine + use_hyde without an extra LLM call.
    Returns {engine, use_hyde, reason} so the UI can show why it chose."""
    q_norm = q.strip()
    # Hard literal hooks → no HyDE (the user already typed the exact identifier)
    if _IPC_RE.search(q_norm) or _DOCNO_RE.search(q_norm):
        return {"engine": "m3", "use_hyde": False, "reason": "literal-id"}
    # Very short fact lookup → no HyDE
    if len(q_norm.split()) <= 4 and not q_norm.endswith("?"):
        return {"engine": "m3", "use_hyde": False, "reason": "short-lookup"}
    # Default for question-shaped natural-language queries → m3 + HyDE
    return {"engine": "m3", "use_hyde": True, "reason": "natural-language"}


def _stage_event(stage: str, status: str, t0: float, **extra) -> str:
    payload = {"type": "stage", "stage": stage, "status": status, "elapsed_ms": round((time.time() - t0) * 1000)}
    payload.update(extra)
    return json.dumps(payload) + "\n"


def _run_chat_pipeline(req: "ChatReq"):
    """Unified generator that yields SSE-like JSON lines covering every stage.
    Emits stage events for: route → hyde → search → rerank → threshold → gen.
    Used by both stream and non-stream endpoints — non-stream collapses events
    into a single response payload."""
    t0 = time.time()
    _METRICS["queries_total"] += 1
    filters = {}
    if req.filename_filter: filters["filename_filter"] = req.filename_filter
    if req.tag_filter: filters["tag_filter"] = req.tag_filter
    if req.doc_number_filter: filters["doc_number_filter"] = req.doc_number_filter

    # Route
    engine, use_hyde, route_reason = req.engine, req.use_hyde, "user-selected"
    if req.auto_route or req.engine == "auto":
        c = _classify_query(req.query)
        engine, use_hyde, route_reason = c["engine"], c["use_hyde"], c["reason"]
    yield _stage_event("route", "done", t0, engine=engine, use_hyde=use_hyde, reason=route_reason)

    # HyDE
    search_query = req.query
    if use_hyde:
        yield _stage_event("hyde", "start", t0)
        search_query = _expand_with_hyde(req.query)
        yield _stage_event("hyde", "done", t0, expanded_chars=len(search_query))

    # Search + rerank (one combined dispatcher call — both stages happen inside)
    yield _stage_event("search", "start", t0, engine=engine)
    contexts = _search_dispatcher(search_query, req.top_k, engine, **filters)
    yield _stage_event("search", "done", t0, results=len(contexts))

    if not contexts:
        answer = "No relevant data found. Please upload patent documents first."
        elapsed = round((time.time() - t0) * 1000)
        _METRICS["latency_ms_sum"] += elapsed
        query_log_id = rag_service.log_query(
            query=req.query,
            answer=answer,
            sources=[],
            top_k=req.top_k,
            model=rag_service.LLM_MODEL,
            total_tokens=0,
            latency_ms=elapsed,
        )
        yield json.dumps({"type": "token", "content": answer}) + "\n"
        yield json.dumps({"type": "sources", "sources": []}) + "\n"
        yield json.dumps({
            "type": "done",
            "answer": answer,
            "engine": engine,
            "use_hyde": use_hyde,
            "route_reason": route_reason,
            "query_log_id": query_log_id,
            "elapsed_ms": elapsed,
            "total_tokens": 0,
        }) + "\n"
        return

    # A1 Reranker confidence threshold — refuse to hallucinate on weak grounding
    top_score = max(((c.get("rerank_score") or c.get("score") or 0.0) for c in contexts), default=0.0)
    yield _stage_event("threshold", "done", t0, top_score=round(float(top_score), 4), min_required=rag_service.MIN_RERANK_SCORE)
    if top_score < rag_service.MIN_RERANK_SCORE:
        _METRICS["queries_low_confidence"] += 1
        msg = (f"⚠️ I found {len(contexts)} candidate passages, but my best match scored only "
               f"{top_score:.3f} (below the {rag_service.MIN_RERANK_SCORE} confidence floor). "
               "I won't answer this from low-confidence context — please rephrase, narrow the scope, "
               "or try a different engine. Confidence: LOW")
        sources = rag_service._fmt_sources(contexts)
        elapsed = round((time.time() - t0) * 1000)
        _METRICS["latency_ms_sum"] += elapsed
        query_log_id = rag_service.log_query(
            query=req.query,
            answer=msg,
            sources=sources,
            top_k=req.top_k,
            model=rag_service.LLM_MODEL,
            total_tokens=0,
            latency_ms=elapsed,
        )
        yield json.dumps({"type": "token", "content": msg}) + "\n"
        yield json.dumps({"type": "sources", "sources": sources}) + "\n"
        yield json.dumps({"type": "done", "answer": msg, "engine": engine, "use_hyde": use_hyde,
                          "route_reason": route_reason, "low_confidence": True,
                          "query_log_id": query_log_id,
                          "top_rerank": round(float(top_score), 4),
                          "elapsed_ms": elapsed,
                          "total_tokens": 0}) + "\n"
        return

    # Generation
    yield _stage_event("gen", "start", t0)
    full_answer = ""
    total_tokens = 0
    generation_error = None
    for line in rag_service.generate_stream(req.query, contexts, req.history):
        # rag_service yields its own JSON lines; pass through but capture the answer
        try:
            d = json.loads(line)
            if d.get("type") == "token":
                full_answer += d.get("content", "")
            elif d.get("type") == "done":
                full_answer = d.get("answer") or full_answer
                total_tokens = d.get("total_tokens", 0)
                continue
            elif d.get("type") == "error":
                generation_error = d.get("message", "Generation failed")
                _METRICS["errors_total"] += 1
        except Exception:
            pass
        yield line if line.endswith("\n") else line + "\n"
    yield _stage_event("gen", "done", t0, chars=len(full_answer))

    elapsed = round((time.time()-t0)*1000)
    _METRICS["latency_ms_sum"] += elapsed
    _METRICS["tokens_total"] += total_tokens
    final_answer = full_answer or generation_error or ""
    final_sources = rag_service._fmt_sources(contexts)
    query_log_id = rag_service.log_query(
        query=req.query,
        answer=final_answer,
        sources=final_sources,
        top_k=req.top_k,
        model=rag_service.LLM_MODEL,
        total_tokens=total_tokens,
        latency_ms=elapsed,
    )
    yield json.dumps({
        "type": "done",
        "model": rag_service.LLM_MODEL,
        "answer": final_answer,
        "query_log_id": query_log_id,
        "total_tokens": total_tokens,
    }) + "\n"
    yield json.dumps({"type": "summary", "engine": engine, "use_hyde": use_hyde,
                      "route_reason": route_reason, "top_rerank": round(float(top_score), 4),
                      "query_log_id": query_log_id, "elapsed_ms": elapsed}) + "\n"
    alert_high_latency(req.query, elapsed)


@app.post("/api/chat")
async def chat(req: ChatReq, user: dict = Depends(require_user)):
    if not req.query.strip():
        raise HTTPException(400, "Empty query")

    if req.stream:
        return StreamingResponse(_run_chat_pipeline(req), media_type="text/event-stream")

    # Non-stream: collapse the pipeline events into a single response
    answer = ""
    sources, stages, summary = [], [], {}
    for line in _run_chat_pipeline(req):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if t == "stage":
            stages.append(d)
        elif t == "token":
            answer += d.get("content", "")
        elif t == "sources":
            sources = d.get("sources", [])
        elif t == "done":
            answer = d.get("answer") or answer
            summary.update({k: d[k] for k in d if k not in ("type",)})
        elif t == "summary":
            summary.update({k: d[k] for k in d if k not in ("type",)})
        elif t == "error":
            return {"answer": d.get("message", ""), "sources": [], "model": rag_service.LLM_MODEL, "stages": stages}
    return {"answer": answer, "sources": sources, "model": rag_service.LLM_MODEL, "stages": stages, **summary}


@app.get("/api/retrieve_debug")
async def retrieve_debug(query: str = Query(...), engine: str = Query("m3"), tag_filter: Optional[str] = None, doc_number_filter: Optional[str] = None, fetch_k: int = Query(20, ge=5, le=50), user: dict = Depends(require_user)):
    """Diagnostic endpoint: show the retrieval funnel (dense / sparse / fused / reranked).
    Helpful for demonstrating WHY a hybrid pipeline picks different sources than
    a single-stage one."""
    filters = {}
    if tag_filter: filters["tag_filter"] = tag_filter
    if doc_number_filter: filters["doc_number_filter"] = doc_number_filter
    if engine != "m3":
        raise HTTPException(400, "retrieve_debug only supports engine=m3 currently")
    breakdown = retrieval_v2.get_stage_breakdown(query, fetch_k=fetch_k, **filters)
    # Add reranker output too
    fused = breakdown["fused_top"]
    if rag_service._reranker and fused:
        pairs = [(query, x["snippet"]) for x in fused]
        scores = rag_service._reranker.predict(pairs)
        for x, s in zip(fused, scores):
            x["rerank_score"] = round(float(s), 4)
        reranked = sorted(fused, key=lambda x: x["rerank_score"], reverse=True)
        breakdown["reranked_top"] = reranked[:10]
    return breakdown


@app.post("/api/m3/reindex")
async def m3_reindex(limit: int = Query(5000, ge=1, le=10000), skip: int = Query(0, ge=0), user: dict = Depends(require_admin)):
    """Re-encode chunks from the baseline collection and write into the m3
    collection. Idempotent (creates duplicates if run twice — wipe with
    /api/m3/reset first if you want a clean state). `skip` lets you resume
    after a crash by skipping the first N already-indexed points."""
    n = retrieval_v2.reindex_from_baseline(baseline_collection=rag_service.COLLECTION, limit=limit, skip=skip)
    return {"status": "ok", "indexed": n, "skipped": skip, "collection": retrieval_v2.M3_COLLECTION}


@app.delete("/api/m3/reset")
async def m3_reset(user: dict = Depends(require_admin)):
    qd = retrieval_v2.get_qdrant()
    try:
        qd.delete_collection(retrieval_v2.M3_COLLECTION)
    except Exception:
        pass
    retrieval_v2.ensure_collection()
    return {"status": "rebuilt", "collection": retrieval_v2.M3_COLLECTION}


# ─── Feedback ───
@app.post("/api/feedback")
async def feedback(req: FeedbackReq, user: dict = Depends(require_user)):
    if not rag_service._db:
        raise HTTPException(503, "Feedback storage unavailable")
    if not rag_service.log_feedback(req.query_log_id, req.rating, req.comment):
        raise HTTPException(404, "Unknown query log id")
    return {"status": "ok"}


# ─── Patent Comparison ───
@app.post("/api/compare")
async def compare(req: CompareReq, user: dict = Depends(require_user)):
    return rag_service.compare_patents(req.doc_a, req.doc_b)


# ─── Suggested Questions ───
@app.get("/api/suggestions")
async def suggestions(user: dict = Depends(require_user)):
    return {"suggestions": rag_service.get_suggested_questions()}


# ─── Export Conversation ───
@app.post("/api/export")
async def export_conversation(messages: list[dict], user: dict = Depends(require_user)):
    """Export conversation as JSON download"""
    export_data = {"exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "messages": messages}
    content = json.dumps(export_data, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content.encode()]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=conversation_export.json"}
    )


# ─── PDF Preview ───
@app.get("/api/pdf/{filename}")
async def get_pdf(filename: str):
    path = _stored_file_path(filename, {".pdf"})
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf")

@app.get("/api/pdf/{filename}/page/{page_no}")
async def get_page_image(filename: str, page_no: int, dpi: int = Query(150, ge=72, le=300)):
    import fitz
    path = _stored_file_path(filename, {".pdf"})
    if not path.exists(): raise HTTPException(404)
    doc = fitz.open(str(path))
    if page_no < 1 or page_no > len(doc): raise HTTPException(400, f"Page out of range (1-{len(doc)})")
    pix = doc[page_no - 1].get_pixmap(dpi=dpi)
    img = pix.tobytes("png")
    doc.close()
    return StreamingResponse(iter([img]), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ─── OCR Comparison (side-by-side) ───
@app.get("/api/ocr-compare/{filename}/{page_no}")
async def ocr_compare(filename: str, page_no: int):
    """Return OCR text + page image for side-by-side comparison"""
    import fitz
    path = _stored_file_path(filename, {".pdf"})
    if not path.exists(): raise HTTPException(404)
    doc = fitz.open(str(path))
    if page_no < 1 or page_no > len(doc): raise HTTPException(400)
    text = doc[page_no - 1].get_text("text").strip()
    doc.close()
    return {"filename": filename, "page": page_no, "ocr_text": text, "image_url": f"/api/pdf/{filename}/page/{page_no}"}


# ─── Patent Browser ───
@app.get("/api/patents")
async def list_patents(limit: int = Query(PATENT_LIST_LIMIT, ge=1, le=5000), user: dict = Depends(require_user)):
    """List all indexed patents with bibliographic data"""
    try:
        patents = rag_service.get_patent_records(limit=limit)
        return {"patents": patents, "total": len(patents)}
    except Exception:
        # Fallback: list files
        files = [{"filename": f.name, "doc_number": f.stem} for f in DATA_DIR.glob("*.pdf")]
        return {"patents": files, "total": len(files)}


# ─── Admin Stats ───
@app.get("/api/admin/stats")
async def admin_stats(user: dict = Depends(require_admin)):
    return rag_service.get_stats()

@app.get("/api/admin/feedback")
async def admin_feedback(user: dict = Depends(require_admin)):
    if not rag_service._db: return {"feedback": []}
    try:
        with rag_service._db.cursor() as cur:
            cur.execute("""SELECT f.id, f.rating, f.comment, q.query, q.created_at 
                          FROM feedback f JOIN query_logs q ON f.query_log_id = q.qid 
                          ORDER BY f.created_at DESC LIMIT 50""")
            rows = cur.fetchall()
            return {"feedback": [{"id": r[0], "rating": r[1], "comment": r[2], "query": r[3][:80], "date": str(r[4])} for r in rows]}
    except Exception: return {"feedback": []}


# ─── Health / Metrics ───
_METRICS = {"queries_total": 0, "queries_low_confidence": 0, "errors_total": 0, "tokens_total": 0,
            "latency_ms_sum": 0.0, "started_at": time.time()}


def _check(url: str, timeout: float = 2.0) -> bool:
    try:
        import requests as _r
        return _r.get(url, timeout=timeout).status_code < 500
    except Exception:
        return False


@app.get("/api/health")
async def health():
    """K8s-friendly health probe. Returns 200 if all soft deps are up; degraded marks
    individual subsystems but still returns 200 (use /api/health/strict for hard fail)."""
    qd_ok = _check(f"{rag_service.QDRANT_URL}/collections")
    ol_ok = _check(f"{rag_service.OLLAMA_URL}/api/tags")
    pg_ok = rag_service._db is not None
    status = "ok" if (qd_ok and ol_ok and pg_ok) else "degraded"
    return {
        "status": status,
        "subsystems": {"qdrant": qd_ok, "ollama": ol_ok, "postgres": pg_ok},
        "uptime_s": round(time.time() - _METRICS["started_at"], 1),
        "models": {"llm": rag_service.LLM_MODEL, "embed": rag_service.EMBED_MODEL,
                   "rerank": rag_service.RERANK_MODEL if rag_service.ENABLE_RERANK else None},
    }


@app.get("/api/health/strict")
async def health_strict():
    h = await health()
    if h["status"] != "ok":
        raise HTTPException(503, f"degraded: {h['subsystems']}")
    return h


@app.get("/metrics")
async def metrics():
    """Prometheus-style metrics (text/plain). Mount at /metrics so a scraper can hit it."""
    avg_latency = (_METRICS["latency_ms_sum"] / max(1, _METRICS["queries_total"]))
    body = (
        f"# HELP patent_rag_queries_total Total /api/chat invocations\n"
        f"# TYPE patent_rag_queries_total counter\n"
        f"patent_rag_queries_total {_METRICS['queries_total']}\n"
        f"# HELP patent_rag_low_confidence_total Queries that hit MIN_RERANK_SCORE floor\n"
        f"# TYPE patent_rag_low_confidence_total counter\n"
        f"patent_rag_low_confidence_total {_METRICS['queries_low_confidence']}\n"
        f"# HELP patent_rag_errors_total Pipeline errors\n"
        f"# TYPE patent_rag_errors_total counter\n"
        f"patent_rag_errors_total {_METRICS['errors_total']}\n"
        f"# HELP patent_rag_tokens_total Generated tokens summed\n"
        f"# TYPE patent_rag_tokens_total counter\n"
        f"patent_rag_tokens_total {_METRICS['tokens_total']}\n"
        f"# HELP patent_rag_latency_ms_avg Average end-to-end latency\n"
        f"# TYPE patent_rag_latency_ms_avg gauge\n"
        f"patent_rag_latency_ms_avg {avg_latency:.1f}\n"
        f"# HELP patent_rag_uptime_s Process uptime\n"
        f"# TYPE patent_rag_uptime_s gauge\n"
        f"patent_rag_uptime_s {round(time.time() - _METRICS['started_at'], 1)}\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# ─── Stats / Files / Reset ───
@app.get("/api/stats")
async def stats(user: dict = Depends(require_user)):
    return rag_service.get_stats()

@app.get("/api/files")
async def list_files(user: dict = Depends(require_user)):
    files = [{"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "ext": f.suffix} for f in sorted(DATA_DIR.iterdir()) if f.is_file()]
    return {"files": files, "count": len(files)}

@app.delete("/api/reset")
async def reset(user: dict = Depends(require_admin)):
    rag_service.get_qdrant().delete_collection(rag_service.COLLECTION)
    rag_service.init()
    return {"status": "rebuilt"}


# ─── Static UI ───
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
