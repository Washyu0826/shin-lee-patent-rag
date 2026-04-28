# API Reference

Base URL: `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs` (Swagger UI)
OpenAPI JSON: `http://localhost:8000/openapi.json`

Rate limit: `RATE_LIMIT_PER_MINUTE` (default 30) per client IP, applied to all `/api/*` paths.

## Auth

### `POST /api/auth/login`
```json
{ "username": "admin", "password": "patent2026" }
```
Returns `{ "token": "<JWT>", "user": { "sub": "admin", "role": "admin" } }`. Token TTL is 24 h (`EXPIRE_HOURS` in `auth_service.py`).

Most business endpoints require this JWT. Public exceptions are:
- `GET /api/health`
- `GET /api/health/strict`
- `GET /api/pdf/{filename}`
- `GET /api/pdf/{filename}/page/{page_no}`
- `GET /api/ocr-compare/{filename}/{page_no}`

Admin-only endpoints additionally require `"role": "admin"`.

## Ingest

### `POST /api/upload`
Multipart form with `file` (PDF). Query params:
- `ocr_engine`: `auto` | `paddle` | `tesseract` (default `auto`)
- `reprocess`: bool — delete existing chunks for the same filename first
- `tag`: string — free-form tag stored in payload, used by `tag_filter` later

### `POST /api/upload/batch`
Multiform `files[]`. Same query params minus `reprocess`. Each file passes through `_ingest_pdf`; failures return `{status: "error", error: ...}` per-file, never aborting the batch.

### `POST /api/ingest/xml`
Multipart form with `file` (XML, data.gov.tw 1案1XML format). Query: `tag`.

### `POST /api/ingest/scan`
Query:
- `dir_path` (default `./data/patents`)
- `tag`

Walks the directory for `*.xml`, parses each, and indexes.

## Chat

### `POST /api/chat`
```json
{
  "query": "What are the key claims?",
  "top_k": 5,
  "filename_filter": "TW202401234A.xml",
  "tag_filter": "demo",
  "doc_number_filter": "TW202401234A",
  "history": [{"query": "...", "answer": "..."}],
  "stream": false
}
```

Non-streaming response:
```json
{
  "answer": "...",
  "sources": [{"source": "...", "page": 0, "snippet": "...", "score": 0.78, "rerank_score": 4.23, "section": "claim_1", "doc_number": "TW202401234A"}],
  "model": "qwen2.5:3b-instruct",
  "query_log_id": 42,
  "top_rerank": 0.91,
  "total_tokens": 812,
  "elapsed_ms": 3240.5,
  "stages": [{"type": "stage", "stage": "search", "status": "done", "elapsed_ms": 185}]
}
```

Streaming (`"stream": true`) returns `text/event-stream` with NDJSON lines:
```
{"type":"stage","stage":"route","status":"done","engine":"m3","use_hyde":true}
{"type":"token","content":"The "}
{"type":"token","content":"system "}
...
{"type":"sources","sources":[...]}
{"type":"done","model":"qwen2.5:3b-instruct","answer":"...","query_log_id":42}
{"type":"summary","engine":"m3","top_rerank":0.91,"elapsed_ms":3240}
```

### `POST /api/compare`
```json
{ "doc_a": "TW202401234A", "doc_b": "TW202405678B" }
```
Returns a table-shaped comparison of abstract / claim_1 / bibliographic.

### `GET /api/suggestions`
Dynamic questions derived from indexed doc_numbers and filenames.

## Feedback + export

### `POST /api/feedback`
```json
{ "query_log_id": 42, "rating": 1, "comment": "helpful" }
```
`rating` ∈ {-1, 1}. `query_log_id` must refer to an existing `qid` from `/api/chat`, otherwise the API returns `404`.

### `POST /api/export`
Body: `messages` array. Returns `conversation_export.json` as a download.

## Viewer

### `GET /api/pdf/{filename}`
Streams the raw PDF.

### `GET /api/pdf/{filename}/page/{page_no}?dpi=150`
Returns a rasterized PNG of the page. Cached by browser (`Cache-Control: public, max-age=3600`).

### `GET /api/ocr-compare/{filename}/{page_no}`
Returns `{ocr_text, image_url}` for side-by-side review.

## Catalog + admin

| Endpoint | Returns |
|---|---|
| `GET /api/patents?limit=1000` | Distinct patents with bibliographic fields (fallback: filesystem listing) |
| `GET /api/files` | All files in `data/patents/` |
| `GET /api/stats` | Collection size, query counts, latency, hot topics |
| `GET /api/admin/stats` | Same payload as `/api/stats` |
| `GET /api/admin/feedback` | Last 50 feedback rows joined with their queries |
| `GET /api/health` | Soft health probe; returns `degraded` when a dependency is down |
| `GET /api/health/strict` | Hard probe; returns `503` when Qdrant/Ollama/Postgres is degraded |
| `DELETE /api/reset` | Drops + recreates the Qdrant collection |

## Error codes

| Status | Meaning |
|---|---|
| 400 | Non-PDF/XML upload, empty query, page out of range |
| 401 | Missing/invalid JWT |
| 403 | Authenticated but not admin |
| 404 | PDF not on disk |
| 422 | OCR produced no pages / no chunks |
| 429 | Rate limit exceeded (30 req/min/IP) |
