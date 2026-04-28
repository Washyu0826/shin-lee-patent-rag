"""
RAG Service v3 — Streaming + Multi-turn + Hybrid Search + Reranker + Patent Compare
"""
import os, uuid, json, time, re
from typing import Any, Optional, Generator

import requests
import psycopg2
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchText, MatchValue, PayloadSchemaType

# ─── Config ───
QDRANT_URL   = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
COLLECTION   = os.getenv("QDRANT_COLLECTION", "patent_chunks")
EMBED_MODEL  = os.getenv("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
LLM_MODEL    = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
ENABLE_RERANK = os.getenv("ENABLE_RERANK", "true").lower() == "true"
DB_URL       = os.getenv("DATABASE_URL", "postgresql://patent:patent2026@localhost:5432/patent_rag")
MIN_RERANK_SCORE = float(os.getenv("MIN_RERANK_SCORE", "0.05"))  # below this, skip LLM and tell user "no good source"
MMR_LAMBDA   = float(os.getenv("MMR_LAMBDA", "0.7"))             # 1.0=pure relevance, 0.0=pure diversity

_embedder: Optional[Any] = None
_reranker: Optional[Any] = None
_qdrant: Optional[QdrantClient] = None
_db = None
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{1,}")
_DOCNO_RE = re.compile(r"\b(?:TW\d{6,}[A-Z]?|[IM]\d{6,})\b", re.IGNORECASE)
_STOP_TERMS = {
    "the", "and", "for", "with", "that", "this", "from", "what", "which",
    "about", "into", "than", "then", "does", "show", "list", "find", "tell",
    "patent", "patents",
}


def init():
    global _embedder, _reranker, _qdrant, _db
    from sentence_transformers import SentenceTransformer, CrossEncoder

    print(f"[RAG] Loading embedding: {EMBED_MODEL}")
    _embedder = SentenceTransformer(EMBED_MODEL)
    dim = _embedder.get_sentence_embedding_dimension()

    if ENABLE_RERANK:
        print(f"[RAG] Loading reranker: {RERANK_MODEL}")
        _reranker = CrossEncoder(RERANK_MODEL, max_length=512)

    _qdrant = QdrantClient(url=QDRANT_URL, timeout=30)
    existing = [c.name for c in _qdrant.get_collections().collections]
    if COLLECTION not in existing:
        _qdrant.create_collection(collection_name=COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        _qdrant.create_payload_index(COLLECTION, "text", PayloadSchemaType.TEXT)
        _qdrant.create_payload_index(COLLECTION, "filename", PayloadSchemaType.KEYWORD)
        _qdrant.create_payload_index(COLLECTION, "doc_number", PayloadSchemaType.KEYWORD)
        _qdrant.create_payload_index(COLLECTION, "section", PayloadSchemaType.KEYWORD)
        _qdrant.create_payload_index(COLLECTION, "tag", PayloadSchemaType.KEYWORD)

    try:
        _db = psycopg2.connect(DB_URL); _db.autocommit = True
    except Exception as e:
        print(f"[RAG] DB connection failed: {e}"); _db = None
    print("[RAG] Init done")


def get_embedder():
    if not _embedder: init()
    return _embedder

def get_qdrant():
    if not _qdrant: init()
    return _qdrant


def scroll_points(collection_name: str = COLLECTION, scroll_filter: Filter | dict | None = None, limit: int | None = None, batch_size: int = 128, with_payload: bool = True, with_vectors: bool = False):
    points = []
    offset = None
    remaining = limit
    while True:
        batch_limit = batch_size if remaining is None else min(batch_size, remaining)
        if batch_limit <= 0:
            break
        batch, offset = get_qdrant().scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            with_payload=with_payload,
            with_vectors=with_vectors,
            limit=batch_limit,
            offset=offset,
        )
        if not batch:
            break
        points.extend(batch)
        if remaining is not None:
            remaining -= len(batch)
            if remaining <= 0:
                break
        if offset is None:
            break
    return points


# ─── Ingest ───
_CHUNK_NAMESPACE = uuid.UUID("6c1f8c2e-7e4a-4b3a-9f8d-3e0c1a4b5d6f")  # stable namespace for deterministic chunk IDs


def _chunk_id(meta: dict, text: str) -> str:
    """Deterministic chunk ID = uuid5(namespace, filename::section::page::texthash).
    Re-running ingest on the same input produces the same UUID → idempotent upsert."""
    import hashlib
    fn = meta.get("filename", "")
    sec = meta.get("section", "")
    page = meta.get("page", 0)
    th = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]
    return str(uuid.uuid5(_CHUNK_NAMESPACE, f"{fn}::{sec}::{page}::{th}"))


def upsert_chunks(chunks: list[dict], tag: str = "") -> int:
    emb = get_embedder()
    texts = [c["text"] for c in chunks]
    vecs = emb.encode(texts, show_progress_bar=True, batch_size=32).tolist()
    points = []
    for c, v in zip(chunks, vecs):
        meta = {**c["metadata"]}
        if tag: meta["tag"] = tag
        points.append(PointStruct(id=_chunk_id(meta, c["text"]), vector=v, payload={"text": c["text"], **meta}))
    batch = 64
    for i in range(0, len(points), batch):
        get_qdrant().upsert(collection_name=COLLECTION, points=points[i:i+batch])
    return len(points)


# ─── Hybrid Search (Vector + Keyword + Metadata Filter) ───
def _build_metadata_filter(filename_filter: str = None, tag_filter: str = None, doc_number_filter: str = None) -> Filter | None:
    must_conditions = []
    if filename_filter:
        must_conditions.append(FieldCondition(key="filename", match=MatchValue(value=filename_filter)))
    if tag_filter:
        must_conditions.append(FieldCondition(key="tag", match=MatchValue(value=tag_filter)))
    if doc_number_filter:
        must_conditions.append(FieldCondition(key="doc_number", match=MatchValue(value=doc_number_filter)))
    return Filter(must=must_conditions) if must_conditions else None


def _query_terms(query: str, max_terms: int = 8) -> list[str]:
    terms = []
    seen = set()
    for token in _TOKEN_RE.findall(query):
        norm = token.lower()
        if norm in seen or norm in _STOP_TERMS:
            continue
        if len(norm) < 2 and not any(ch.isdigit() for ch in norm):
            continue
        seen.add(norm)
        terms.append(token)
        if len(terms) >= max_terms:
            break
    return terms


def _point_to_candidate(point, score: float | None = None, **extra) -> dict:
    payload = point.payload or {}
    candidate = {
        "_point_id": str(getattr(point, "id", payload.get("chunk_id", ""))),
        "text": payload.get("text", ""),
        "source": payload.get("source", ""),
        "score": round(float(score or 0.0), 4),
        "filename": payload.get("filename", ""),
        "page": payload.get("page", 0),
        "section": payload.get("section", ""),
        "doc_number": payload.get("doc_number", ""),
        "tag": payload.get("tag", ""),
    }
    candidate.update(extra)
    return candidate


def _dense_candidates(query: str, fetch_k: int, q_filter: Filter | None) -> list[dict]:
    vec = get_embedder().encode(query).tolist()
    results = get_qdrant().search(collection_name=COLLECTION, query_vector=vec, limit=fetch_k, query_filter=q_filter)
    return [_point_to_candidate(result, score=result.score) for result in results]


def _build_lexical_filter(query: str, query_terms: list[str], metadata_filter: Filter | None) -> Filter | None:
    should_conditions = []
    phrase = query.strip()
    if phrase and len(phrase) <= 120:
        should_conditions.append(FieldCondition(key="text", match=MatchText(text=phrase)))
    for term in query_terms:
        should_conditions.append(FieldCondition(key="text", match=MatchText(text=term)))
    for doc_number in {match.upper() for match in _DOCNO_RE.findall(query)}:
        should_conditions.append(FieldCondition(key="doc_number", match=MatchValue(value=doc_number)))
        should_conditions.append(FieldCondition(key="filename", match=MatchValue(value=f"{doc_number}.xml")))
        should_conditions.append(FieldCondition(key="filename", match=MatchValue(value=f"{doc_number}.pdf")))
    if not should_conditions:
        return metadata_filter
    must_conditions = list(metadata_filter.must) if metadata_filter and metadata_filter.must else []
    return Filter(must=must_conditions, should=should_conditions)


def _lexical_score(query: str, query_terms: list[str], payload: dict) -> float:
    text = " ".join(
        str(payload.get(key, ""))
        for key in ("text", "source", "filename", "doc_number", "section", "tag")
    ).lower()
    if not text:
        return 0.0
    normalized_terms = [term.lower() for term in query_terms]
    hit_count = sum(1 for term in normalized_terms if term in text)
    score = hit_count / max(1, len(normalized_terms))
    for doc_number in {match.lower() for match in _DOCNO_RE.findall(query)}:
        if payload.get("doc_number", "").lower() == doc_number:
            score += 1.0
    filename = payload.get("filename", "").lower()
    if filename and filename in query.lower():
        score += 0.5
    return round(score, 4)


def _lexical_candidates(query: str, fetch_k: int, q_filter: Filter | None) -> list[dict]:
    query_terms = _query_terms(query)
    lexical_filter = _build_lexical_filter(query, query_terms, q_filter)
    if lexical_filter is None:
        return []
    records = scroll_points(scroll_filter=lexical_filter, limit=max(fetch_k * 4, 20))
    candidates = []
    for record in records:
        payload = record.payload or {}
        lexical_score = _lexical_score(query, query_terms, payload)
        if lexical_score <= 0:
            continue
        candidates.append(_point_to_candidate(record, score=lexical_score, lexical_score=lexical_score))
    candidates.sort(key=lambda item: item.get("lexical_score", 0.0), reverse=True)
    return candidates[:fetch_k]


def _rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    fused = {}
    for ranking in rankings:
        for rank, point_id in enumerate(ranking):
            fused[point_id] = fused.get(point_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _fuse_candidates(dense_candidates: list[dict], lexical_candidates: list[dict], limit: int) -> list[dict]:
    by_id = {}
    for candidate in dense_candidates + lexical_candidates:
        point_id = candidate["_point_id"]
        if point_id not in by_id:
            by_id[point_id] = dict(candidate)
            continue
        merged = by_id[point_id]
        for key, value in candidate.items():
            if key in {"score", "lexical_score"}:
                merged[key] = max(merged.get(key, 0.0), value)
            elif value not in ("", None):
                merged[key] = value

    rankings = []
    if dense_candidates:
        rankings.append([candidate["_point_id"] for candidate in dense_candidates])
    if lexical_candidates:
        rankings.append([candidate["_point_id"] for candidate in lexical_candidates])
    if not rankings:
        return []

    fused_scores = _rrf_fuse(rankings)
    fused_ranked = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    fused = []
    for point_id, fused_score in fused_ranked:
        candidate = dict(by_id[point_id])
        candidate["rrf_score"] = round(fused_score, 6)
        fused.append(candidate)
    return fused


def search(query: str, top_k: int = 5, filename_filter: str = None, tag_filter: str = None, doc_number_filter: str = None) -> list[dict]:
    fetch_k = top_k * 4 if ENABLE_RERANK and _reranker else max(top_k * 2, 10)
    q_filter = _build_metadata_filter(filename_filter, tag_filter, doc_number_filter)
    dense_candidates = _dense_candidates(query, fetch_k, q_filter)
    lexical_candidates = _lexical_candidates(query, fetch_k, q_filter)
    candidates = _fuse_candidates(dense_candidates, lexical_candidates, fetch_k) or dense_candidates or lexical_candidates

    if ENABLE_RERANK and _reranker and candidates:
        pairs = [(query, c["text"]) for c in candidates]
        scores = _reranker.predict(pairs)
        for c, s in zip(candidates, scores): c["rerank_score"] = round(float(s), 4)
        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

    return _mmr_select(candidates, top_k)


def _mmr_select(candidates: list[dict], top_k: int) -> list[dict]:
    """Maximal Marginal Relevance: keep the top-1 then iteratively pick whichever
    remaining candidate maximizes (lambda * relevance) - ((1-lambda) * max_sim_to_picked).
    Similarity here is "same patent" indicator (cheap proxy for content overlap),
    which is what we actually want to diversify on for patent search."""
    if not candidates:
        return []
    score_key = "rerank_score" if "rerank_score" in candidates[0] else "score"
    pool = list(candidates)
    picked = [pool.pop(0)]
    while pool and len(picked) < top_k:
        best_i, best_score = 0, -1e9
        for i, c in enumerate(pool):
            rel = c.get(score_key, 0.0)
            redundancy = max(
                (1.0 if (p.get("doc_number") and p["doc_number"] == c.get("doc_number")) else 0.0)
                for p in picked
            )
            mmr = MMR_LAMBDA * rel - (1 - MMR_LAMBDA) * redundancy
            if mmr > best_score:
                best_score, best_i = mmr, i
        picked.append(pool.pop(best_i))
    return picked


# ─── Prompt ───
RAG_PROMPT = """You are a Taiwan patent document AI assistant. Answer questions based ONLY on the provided patent document excerpts.

## Rules
1. Answer ONLY from the provided sources. Do NOT fabricate information.
2. Cite every claim with [Source N] format.
3. If sources are insufficient, say "Based on available data, I cannot fully answer this question" and explain what's missing.
4. Answer in **English**.
5. For claims/patent scope questions, list each claim and quote the original text.
6. For comparison questions, use a table format.
7. End with confidence level: HIGH (multiple sources) / MEDIUM (partial) / LOW (inference-based).

## Patent Document Excerpts
{context}

## Conversation History
{history}

## Current Question
{query}

## Answer (with citations + confidence level)"""


# ─── Generate (non-streaming) ───
def generate_answer(query: str, contexts: list[dict], history: list[dict] = None) -> dict:
    ctx_parts = []
    for i, c in enumerate(contexts):
        sc = f"vector:{c['score']}"
        if "rerank_score" in c: sc += f", rerank:{c['rerank_score']}"
        ctx_parts.append(f"[Source {i+1}] ({c['source']}, {sc})\n{c['text']}")

    hist_str = ""
    if history:
        for h in history[-10:]:  # Max 10 turns
            hist_str += f"User: {h.get('query','')}\nAssistant: {h.get('answer','')[:300]}\n\n"

    prompt = RAG_PROMPT.format(context="\n\n".join(ctx_parts), query=query, history=hist_str or "None")

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": LLM_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1500}
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        answer, tokens = data.get("response", "").strip(), data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
    except Exception as e:
        answer, tokens = f"LLM error: {e}", 0

    return {"answer": answer, "sources": _fmt_sources(contexts), "model": LLM_MODEL, "total_tokens": tokens, "rerank_enabled": ENABLE_RERANK and _reranker is not None}


# ─── Streaming Generate ───
def generate_stream(query: str, contexts: list[dict], history: list[dict] = None) -> Generator[str, None, None]:
    ctx_parts = []
    for i, c in enumerate(contexts):
        sc = f"vector:{c['score']}"
        if "rerank_score" in c: sc += f", rerank:{c['rerank_score']}"
        ctx_parts.append(f"[Source {i+1}] ({c['source']}, {sc})\n{c['text']}")

    hist_str = ""
    if history:
        for h in history[-10:]:
            hist_str += f"User: {h.get('query','')}\nAssistant: {h.get('answer','')[:300]}\n\n"

    prompt = RAG_PROMPT.format(context="\n\n".join(ctx_parts), query=query, history=hist_str or "None")

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": LLM_MODEL, "prompt": prompt, "stream": True,
            "options": {"temperature": 0.3, "num_predict": 1500}
        }, timeout=120, stream=True)
        resp.raise_for_status()

        full_answer = ""
        total_tokens = 0
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("response", "")
                full_answer += token
                yield json.dumps({"type": "token", "content": token}) + "\n"
                if data.get("done"):
                    total_tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
                    break

        yield json.dumps({"type": "sources", "sources": _fmt_sources(contexts)}) + "\n"
        yield json.dumps({"type": "done", "model": LLM_MODEL, "answer": full_answer, "total_tokens": total_tokens}) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "message": str(e)}) + "\n"


def _fmt_sources(contexts):
    return [{
        "source": c["source"], "score": c["score"],
        "rerank_score": c.get("rerank_score"), "page": c["page"],
        "filename": c["filename"], "section": c.get("section", ""),
        "doc_number": c.get("doc_number", ""),
        "snippet": c["text"][:300] + ("..." if len(c["text"]) > 300 else ""),
    } for c in contexts]


# ─── Unified Ask ───
def ask(query: str, top_k: int = 5, history: list = None, **filters) -> dict:
    t0 = time.time()
    contexts = search(query, top_k, **filters)
    if not contexts:
        return {"answer": "No relevant data found. Please upload patent documents first.", "sources": [], "model": LLM_MODEL, "total_tokens": 0, "latency_ms": 0}
    result = generate_answer(query, contexts, history)
    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
    result["query_log_id"] = log_query(
        query=query,
        answer=result.get("answer", ""),
        sources=result.get("sources", []),
        top_k=top_k,
        model=result.get("model"),
        total_tokens=result.get("total_tokens", 0),
        latency_ms=result.get("latency_ms", 0),
    )
    return result


# ─── Patent Comparison ───
def compare_patents(doc_a: str, doc_b: str) -> dict:
    """Basic table comparison of two patents by doc_number"""
    compare_limit = int(os.getenv("COMPARE_SCROLL_LIMIT", "300"))
    chunks_a = scroll_points(
        scroll_filter=Filter(must=[FieldCondition(key="doc_number", match=MatchValue(value=doc_a))]),
        limit=compare_limit,
    )
    chunks_b = scroll_points(
        scroll_filter=Filter(must=[FieldCondition(key="doc_number", match=MatchValue(value=doc_b))]),
        limit=compare_limit,
    )

    def extract_field(chunks, section_prefix):
        for c in chunks:
            if c.payload.get("section", "").startswith(section_prefix):
                return c.payload.get("text", "")[:500]
        return "N/A"

    return {
        "patent_a": doc_a, "patent_b": doc_b,
        "comparison": {
            "abstract": {"a": extract_field(chunks_a, "abstract"), "b": extract_field(chunks_b, "abstract")},
            "claim_1": {"a": extract_field(chunks_a, "claim_1"), "b": extract_field(chunks_b, "claim_1")},
            "bibliographic": {"a": extract_field(chunks_a, "bibliographic"), "b": extract_field(chunks_b, "bibliographic")},
        },
    }


def get_patent_records(limit: int = 1000) -> list[dict]:
    records = scroll_points(
        scroll_filter=Filter(must=[FieldCondition(key="section", match=MatchValue(value="bibliographic"))]),
        limit=limit,
    )
    patents = []
    seen = set()
    for record in records:
        payload = record.payload or {}
        doc_number = payload.get("doc_number", payload.get("filename", ""))
        if not doc_number or doc_number in seen:
            continue
        seen.add(doc_number)
        patents.append({
            "doc_number": doc_number,
            "title": payload.get("title", ""),
            "ipc": payload.get("ipc", ""),
            "applicant": payload.get("applicant", ""),
            "filename": payload.get("filename", ""),
            "tag": payload.get("tag", ""),
        })
    return patents


# ─── Suggested Questions ───
def get_suggested_questions() -> list[str]:
    """Generate dynamic suggestions based on indexed documents"""
    try:
        results = get_qdrant().scroll(collection_name=COLLECTION, limit=10)[0]
        if not results:
            return ["Upload patent documents to get started."]

        filenames = list(set(r.payload.get("filename", "") for r in results))[:3]
        doc_numbers = list(set(r.payload.get("doc_number", "") for r in results if r.payload.get("doc_number")))[:3]

        suggestions = []
        if doc_numbers:
            suggestions.append(f"What are the key claims of patent {doc_numbers[0]}?")
            if len(doc_numbers) > 1:
                suggestions.append(f"Compare patents {doc_numbers[0]} and {doc_numbers[1]}")
        if filenames:
            suggestions.append(f"Summarize the technical features in {filenames[0]}")
        suggestions.append("What IPC classifications are covered in the uploaded patents?")
        suggestions.append("List all applicants and their patents")
        return suggestions[:5]
    except Exception:
        return ["What is the main technical feature of this patent?"]


# ─── Stats ───
def get_stats() -> dict:
    info = get_qdrant().get_collection(COLLECTION)
    stats = {
        "collection": COLLECTION, "total_chunks": info.points_count,
        "rerank_enabled": ENABLE_RERANK and _reranker is not None,
        "llm_model": LLM_MODEL, "embed_model": EMBED_MODEL,
    }
    if _db:
        try:
            with _db.cursor() as cur:
                cur.execute("SELECT COUNT(*), COALESCE(AVG(latency_ms),0), COUNT(DISTINCT query) FROM query_logs")
                r = cur.fetchone()
                stats.update({"total_queries": r[0], "avg_latency_ms": round(r[1], 1), "unique_queries": r[2]})
                cur.execute("SELECT COUNT(*) FROM documents")
                stats["total_documents"] = cur.fetchone()[0]
                # Hot topics
                cur.execute("SELECT query, COUNT(*) as cnt FROM query_logs GROUP BY query ORDER BY cnt DESC LIMIT 5")
                stats["hot_topics"] = [{"query": r[0][:80], "count": r[1]} for r in cur.fetchall()]
        except Exception: pass
    return stats


# ─── DB Logging ───
def log_document(doc_info: dict):
    if not _db: return
    try:
        with _db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (doc_id,filename,source_type,total_pages,total_chunks,ocr_applied,ocr_engine,file_size_kb)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(doc_id) DO UPDATE SET
                    filename = EXCLUDED.filename,
                    source_type = EXCLUDED.source_type,
                    total_pages = EXCLUDED.total_pages,
                    total_chunks = EXCLUDED.total_chunks,
                    ocr_applied = EXCLUDED.ocr_applied,
                    ocr_engine = EXCLUDED.ocr_engine,
                    file_size_kb = EXCLUDED.file_size_kb,
                    ingested_at = NOW()
                """,
                (
                    doc_info.get("doc_id", str(uuid.uuid4())),
                    doc_info["filename"],
                    doc_info.get("source_type", "patent"),
                    doc_info.get("total_pages"),
                    doc_info.get("chunks_created"),
                    doc_info.get("ocr_applied"),
                    doc_info.get("ocr_engine"),
                    doc_info.get("file_size_kb"),
                ),
            )
    except Exception as e: print(f"[DB] log_document: {e}")


def log_query(query: str, answer: str, sources: list[dict], top_k: int = 5, model: str | None = None, total_tokens: int = 0, latency_ms: float = 0) -> int | None:
    if not _db: return
    try:
        with _db.cursor() as cur:
            cur.execute(
                "INSERT INTO query_logs (query,answer,top_k,sources,model,total_tokens,latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING qid",
                (
                    query,
                    answer[:2000],
                    top_k,
                    json.dumps(sources, ensure_ascii=False)[:5000],
                    model,
                    total_tokens,
                    latency_ms,
                ),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        print(f"[DB] log_query: {e}")
        return None


def log_feedback(qid: int, rating: int, comment: str = "") -> bool:
    if not _db:
        return False
    try:
        with _db.cursor() as cur:
            cur.execute("SELECT 1 FROM query_logs WHERE qid = %s", (qid,))
            if cur.fetchone() is None:
                return False
            cur.execute("INSERT INTO feedback (query_log_id, rating, comment) VALUES (%s,%s,%s)", (qid, rating, comment))
            return True
    except Exception:
        return False
