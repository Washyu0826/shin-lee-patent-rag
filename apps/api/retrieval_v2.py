"""SOTA retrieval pipeline: bge-m3 (dense + sparse) + RRF fusion + reranker.

Why this beats the baseline:
  * bge-m3 is BAAI's 2024 multilingual SOTA — supports 100+ languages, 8192 token
    context (vs MiniLM's 256), and produces dense + lexical (sparse) + colbert
    embeddings in a single forward pass.
  * Dense + sparse fusion via Reciprocal Rank Fusion (RRF) closes the
    "vocabulary gap": dense catches semantic similarity, sparse catches exact
    term matches (esp. acronyms, IPC codes, proper nouns) — the patent domain
    needs both.
  * The same CrossEncoder reranker (bge-reranker-v2-m3) sits on top, giving a
    fine-grained ranking over ~30 fused candidates.

Architecture lives in a SEPARATE Qdrant collection (patent_chunks_m3) so the
baseline pipeline stays untouched and we can A/B compare.
"""
from __future__ import annotations

import os
import time

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    NamedSparseVector,
    NamedVector,
    PayloadSchemaType,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
M3_COLLECTION = "patent_chunks_m3"
DENSE_NAME = "dense"
SPARSE_NAME = "sparse"
DENSE_DIM = 1024  # bge-m3 fixed dim

_m3_model = None
_qdrant: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL, timeout=60)
    return _qdrant


def get_m3():
    """Lazy-load bge-m3 — first call downloads ~2.27 GB to HF cache."""
    global _m3_model
    if _m3_model is None:
        print("[v2] Loading BAAI/bge-m3 (this is slow on first call)…", flush=True)
        from FlagEmbedding import BGEM3FlagModel
        t0 = time.time()
        _m3_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, devices="cpu")
        print(f"[v2] bge-m3 loaded in {time.time()-t0:.1f}s", flush=True)
    return _m3_model


def ensure_collection():
    """Create the m3 collection with both dense and sparse vector configs."""
    qd = get_qdrant()
    existing = {c.name for c in qd.get_collections().collections}
    if M3_COLLECTION in existing:
        return
    qd.create_collection(
        collection_name=M3_COLLECTION,
        vectors_config={DENSE_NAME: VectorParams(size=DENSE_DIM, distance=Distance.COSINE)},
        sparse_vectors_config={SPARSE_NAME: SparseVectorParams(index=SparseIndexParams())},
    )
    for k in ("filename", "doc_number", "section", "tag"):
        qd.create_payload_index(M3_COLLECTION, k, PayloadSchemaType.KEYWORD)
    print(f"[v2] created collection {M3_COLLECTION} (dense={DENSE_DIM} + sparse)", flush=True)


def encode_passages(texts: list[str], batch_size: int = 4) -> list[dict]:
    """Encode docs: produce dense vec + sparse {token_id: weight}.
    batch_size lowered to 4 for 8GB-VRAM/16GB-RAM laptops — bge-m3 on CPU at
    batch=8 occasionally OOMs mid-reindex on long claim chunks."""
    m = get_m3()
    out = m.encode(texts, return_dense=True, return_sparse=True, return_colbert_vecs=False, batch_size=batch_size, max_length=512)
    dense = out["dense_vecs"]
    sparse = out["lexical_weights"]
    return [{"dense": dense[i].tolist(), "sparse": sparse[i]} for i in range(len(texts))]


def encode_query(text: str) -> dict:
    m = get_m3()
    out = m.encode([text], return_dense=True, return_sparse=True, return_colbert_vecs=False, max_length=512)
    return {"dense": out["dense_vecs"][0].tolist(), "sparse": out["lexical_weights"][0]}


def _sparse_to_qdrant(sparse_dict: dict) -> SparseVector:
    """Convert {token_id_str: weight_float32} → Qdrant SparseVector."""
    if not sparse_dict:
        return SparseVector(indices=[], values=[])
    indices = [int(k) for k in sparse_dict]
    values = [float(v) for v in sparse_dict.values()]
    return SparseVector(indices=indices, values=values)


def upsert_chunks_m3(chunks: list[dict], tag: str = "") -> int:
    """Index chunks into the m3 collection with dense + sparse vectors."""
    ensure_collection()
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    embs = encode_passages(texts)

    # Use the same deterministic chunk ID scheme as the baseline collection so
    # reindex / cron-sync stays idempotent.
    from rag_service import _chunk_id

    points = []
    for c, e in zip(chunks, embs):
        meta = {**c["metadata"]}
        if tag:
            meta["tag"] = tag
        points.append(
            PointStruct(
                id=_chunk_id(meta, c["text"]),
                vector={
                    DENSE_NAME: e["dense"],
                    SPARSE_NAME: _sparse_to_qdrant(e["sparse"]),
                },
                payload={"text": c["text"], **meta},
            )
        )
    batch = 32
    qd = get_qdrant()
    for i in range(0, len(points), batch):
        qd.upsert(collection_name=M3_COLLECTION, points=points[i:i + batch])
    return len(points)


def reindex_from_baseline(baseline_collection: str = "patent_chunks", limit: int = 5000, skip: int = 0) -> int:
    """Stream chunks out of the baseline collection, re-encode with bge-m3,
    and upsert into the m3 collection. Skips re-running ingest pipeline.
    `skip` allows resume after a crash by skipping the first N points."""
    import gc
    ensure_collection()
    qd = get_qdrant()
    next_offset = None
    total = 0
    seen = 0
    while True:
        pts, next_offset = qd.scroll(
            collection_name=baseline_collection,
            scroll_filter=None,
            with_payload=True,
            with_vectors=False,
            limit=32,
            offset=next_offset,
        )
        if not pts:
            break
        if seen + len(pts) <= skip:
            seen += len(pts)
            if next_offset is None:
                break
            continue
        keep = pts[max(0, skip - seen):] if seen < skip else pts
        seen += len(pts)
        batch_chunks = []
        for p in keep:
            payload = p.payload or {}
            text = payload.get("text", "")
            if not text:
                continue
            meta = {k: v for k, v in payload.items() if k != "text"}
            batch_chunks.append({"text": text, "metadata": meta})
        n = upsert_chunks_m3(batch_chunks)
        total += n
        gc.collect()
        print(f"[v2] reindexed {total} so far (cumulative seen={seen})…", flush=True)
        if next_offset is None or total >= limit:
            break
    return total


def _build_filter(filename_filter=None, tag_filter=None, doc_number_filter=None) -> Filter | None:
    must = []
    if filename_filter:
        must.append(FieldCondition(key="filename", match=MatchValue(value=filename_filter)))
    if tag_filter:
        must.append(FieldCondition(key="tag", match=MatchValue(value=tag_filter)))
    if doc_number_filter:
        must.append(FieldCondition(key="doc_number", match=MatchValue(value=doc_number_filter)))
    return Filter(must=must) if must else None


def _rrf(ranked_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion. Each input is a ranked list of doc IDs.
    Returns {id: fused_score}. k=60 is the canonical value from the original
    Cormack et al. 2009 paper."""
    score: dict[str, float] = {}
    for rl in ranked_lists:
        for rank, docid in enumerate(rl):
            score[docid] = score.get(docid, 0.0) + 1.0 / (k + rank + 1)
    return score


def search_m3(query: str, top_k: int = 5, fetch_k: int = 30, **filters) -> list[dict]:
    """Hybrid search: dense + sparse → RRF fusion → top-k.

    Returns the same shape as rag_service.search() so generate_answer/
    generate_stream can consume it unchanged.
    """
    qd = get_qdrant()
    qf = _build_filter(**filters)
    qe = encode_query(query)

    # 1) Dense search
    dense_hits = qd.search(
        collection_name=M3_COLLECTION,
        query_vector=NamedVector(name=DENSE_NAME, vector=qe["dense"]),
        query_filter=qf,
        limit=fetch_k,
        with_payload=True,
    )
    # 2) Sparse search
    sparse_hits = qd.search(
        collection_name=M3_COLLECTION,
        query_vector=NamedSparseVector(name=SPARSE_NAME, vector=_sparse_to_qdrant(qe["sparse"])),
        query_filter=qf,
        limit=fetch_k,
        with_payload=True,
    )

    # 3) RRF fusion
    by_id = {}
    for h in dense_hits + sparse_hits:
        by_id[str(h.id)] = h  # keep one ScoredPoint per id
    fused = _rrf([[str(h.id) for h in dense_hits], [str(h.id) for h in sparse_hits]])
    fused_ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:fetch_k]

    out = []
    for docid, fscore in fused_ranked:
        h = by_id.get(docid)
        if h is None:
            continue
        p = h.payload or {}
        out.append({
            "text": p.get("text", ""),
            "source": p.get("source", ""),
            "filename": p.get("filename", ""),
            "page": p.get("page", 0),
            "section": p.get("section", ""),
            "doc_number": p.get("doc_number", ""),
            "tag": p.get("tag", ""),
            "score": round(float(h.score), 4),
            "rrf_score": round(fscore, 6),
        })
    return out[:top_k]


def search_with_rerank(query: str, top_k: int = 5, fetch_k: int = 30, reranker=None, **filters) -> list[dict]:
    cands = search_m3(query, top_k=fetch_k, fetch_k=fetch_k, **filters)
    if reranker is None or not cands:
        return cands[:top_k]
    pairs = [(query, c["text"]) for c in cands]
    scores = reranker.predict(pairs)
    for c, s in zip(cands, scores):
        c["rerank_score"] = round(float(s), 4)
    cands.sort(key=lambda x: x["rerank_score"], reverse=True)
    # MMR diversity over the same patent — same selector as the baseline path
    from rag_service import _mmr_select
    return _mmr_select(cands, top_k)


def get_stage_breakdown(query: str, fetch_k: int = 30, **filters) -> dict:
    """Diagnostic endpoint: return dense-only / sparse-only / fused / reranked
    candidates for the same query, so the UI can visualize the funnel."""
    qd = get_qdrant()
    qf = _build_filter(**filters)
    qe = encode_query(query)

    def _summarize(hit):
        p = hit.payload or {}
        return {
            "id": str(hit.id),
            "source": p.get("source", ""),
            "doc_number": p.get("doc_number", ""),
            "section": p.get("section", ""),
            "score": round(float(hit.score), 4),
            "snippet": p.get("text", "")[:120],
        }

    dense_hits = qd.search(collection_name=M3_COLLECTION, query_vector=NamedVector(name=DENSE_NAME, vector=qe["dense"]), query_filter=qf, limit=fetch_k, with_payload=True)
    sparse_hits = qd.search(collection_name=M3_COLLECTION, query_vector=NamedSparseVector(name=SPARSE_NAME, vector=_sparse_to_qdrant(qe["sparse"])), query_filter=qf, limit=fetch_k, with_payload=True)

    by_id = {str(h.id): h for h in dense_hits + sparse_hits}
    fused = _rrf([[str(h.id) for h in dense_hits], [str(h.id) for h in sparse_hits]])
    fused_ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:fetch_k]

    return {
        "query": query,
        "dense_top": [_summarize(h) for h in dense_hits[:10]],
        "sparse_top": [_summarize(h) for h in sparse_hits[:10]],
        "fused_top": [{**_summarize(by_id[i]), "rrf_score": round(s, 6)} for i, s in fused_ranked[:10]],
    }
