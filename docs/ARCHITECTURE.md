# Architecture

> 系統視角：Taiwan patent OCR/RAG chatbot — 從 PDF/XML 進到引用標註的答案，全程在單機可跑、ops-friendly。

---

## 1. System overview

Patent RAG v3 是一個**單體 FastAPI 應用 + 三個外部服務**的架構。所有的檢索、重排、生成都在同一個 Python process 裡，外部依賴只有：

- **Qdrant**（向量庫，雙 collection：MiniLM baseline + bge-m3 SOTA）
- **Ollama**（本地 LLM，預設 `qwen2.5:7b` Q4_K_M）
- **PostgreSQL**（審計、查詢 log、feedback；連不到時 `_db = None`、相關紀錄靜默略過，chat 仍可用）

設計原則：**沒有 model server，沒有 message queue，沒有 worker pool**。所有跨檔案呼叫都是 in-process。換來的代價：
- 冷啟動 ~15 秒（載入 embedder + reranker）
- 單一 uvicorn worker 的 throughput 上限

換來的好處：**部署一條指令、debug 不用看跨機器 log、一台 RTX 4060 8GB 筆電就能跑完整 demo**。

---

## 2. Component topology

```
                                  ┌──────────────────────────────────────────┐
                                  │                Browser                   │
                                  │            ui/index.html (SPA)           │
                                  │  · vanilla JS (no framework)             │
                                  │  · streams NDJSON over fetch()           │
                                  │  · JWT in localStorage                   │
                                  └─────────────────┬────────────────────────┘
                                                    │ HTTP / SSE
                                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       FastAPI (uvicorn, single process)                      │
│                              apps/api/main.py                                │
│                                                                              │
│  Endpoints                       Pipeline (per /api/chat call)               │
│  ─────────                       ─────────────────────────────               │
│  POST  /api/auth/login           1. _classify_query()  → engine + use_hyde   │
│  POST  /api/upload               2. _expand_with_hyde()                      │
│  POST  /api/ingest/xml           3. _search_dispatcher() → search/retrieval  │
│  POST  /api/chat (stream NDJSON) 4. CrossEncoder.predict() → rerank          │
│  GET   /api/retrieve_debug       5. _mmr_select() → diversify across docs   │
│  GET   /api/stats                6. confidence threshold gate                │
│  GET   /api/health               7. rag_service.generate_stream()            │
│  GET   /metrics                  8. log_query() + alert_high_latency()       │
│  POST  /api/feedback                                                         │
│                                                                              │
│  In-process models (loaded on first request, cached as singletons):          │
│  · SentenceTransformer       paraphrase-multilingual-MiniLM-L12-v2 (384d)    │
│  · BGEM3FlagModel            bge-m3 dense(1024d) + sparse + (colbert off)    │
│  · CrossEncoder              bge-reranker-v2-m3                              │
└──────┬───────────────────────────────────┬─────────────────────────┬─────────┘
       │ HTTP gRPC                         │ HTTP                    │ psycopg2
       ▼                                   ▼                         ▼
┌────────────────────┐            ┌─────────────────────┐    ┌─────────────────┐
│      Qdrant        │            │       Ollama        │    │   PostgreSQL    │
│      :6333         │            │      :11434         │    │      :5432      │
│                    │            │                     │    │                 │
│  patent_chunks     │            │  qwen2.5:7b Q4_K_M  │    │  documents      │
│   (baseline,       │            │  (LLM, streaming)   │    │  query_logs     │
│    MiniLM 384d)    │            │                     │    │  feedback       │
│  patent_chunks_m3  │            │                     │    │  eval_runs      │
│   (m3, dense+      │            │                     │    │                 │
│    sparse,         │            │                     │    │                 │
│    RRF-fused)      │            │                     │    │  if PG down →   │
│                    │            │                     │    │  silently skip  │
└────────────────────┘            └─────────────────────┘    └─────────────────┘
```

---

## 3. Module map (`apps/api/`)

| File | Responsibility |
|---|---|
| `main.py` | FastAPI routes, auth wiring, pipeline orchestration (`_run_chat_pipeline`), classifier (`_classify_query`), health & metrics |
| `rag_service.py` | Qdrant collection lifecycle, MiniLM embedding, baseline `search()` (RRF over dense + lexical), reranker call, MMR (`_mmr_select`), prompt template, Ollama streaming, deterministic chunk IDs, query logging |
| `retrieval_v2.py` | bge-m3 hybrid path: dense + sparse encoding, separate Qdrant collection (`patent_chunks_m3`), RRF fusion, retrieval debug (`get_stage_breakdown`) for the funnel UI |
| `ocr_service.py` | PDF text extraction (PyMuPDF first, OCR fallback), Paddle / Tesseract dispatcher, claim-aware chunker |
| `xml_parser.py` | TIPO-style patent XML → section-aware chunks (`bibliographic`, `abstract`, `claim_N`, `description_N`) |
| `auth_service.py` | JWT issue/verify (jose), single-user store from env vars (POC) |
| `webhook.py` | Slack/Discord-compatible alert sender for high-latency queries |

---

## 4. Request flows

### 4.1 Ingest — PDF

```
Client                  FastAPI                       Disk            Qdrant       PG
  │ multipart/form-data    │                             │               │           │
  │ ──────────────────────>│                             │               │           │
  │                        │ stream chunks (1 MiB)       │               │           │
  │                        │ ─────────────────────────── │               │           │
  │                        │                             │               │           │
  │                        │ ocr_pdf(): PyMuPDF text                     │           │
  │                        │   if chars/page < 80 →                      │           │
  │                        │   ocrmypdf (Paddle | Tesseract)             │           │
  │                        │                                             │           │
  │                        │ chunk_patent(): claim-split, max 800 chars  │           │
  │                        │                                             │           │
  │                        │ MiniLM.encode(N×384)                        │           │
  │                        │ ───────────────────────────────────────────>│           │
  │                        │   upsert with deterministic UUID5 ID        │           │
  │                        │                                             │           │
  │                        │ log_document() ────────────────────────────────────────>│
  │ <────────────────────  │ {"chunks": N}                               │           │
```

### 4.2 Ingest — XML（TIPO format）

```
Client → /api/ingest/xml → xml_parser.parse_patent_xml() (lxml XPath)
         → chunk_patent_xml() → 一個 chunk 對應一個 section
         → 同一條 embedding/upsert 路徑（baseline 用 MiniLM，m3 用 bge-m3）
```

XML 路徑保留 `doc_number`、`section`、`claim_n` metadata，允許 `[Source claim_3]` 級別的引用。

### 4.3 Chat — 完整 SSE pipeline

`POST /api/chat` 永遠串流 NDJSON 給前端，**即使 `stream=false` 也用同一份 generator**，只是 server-side collapse 成單一 response。

```
                                                  ┌──────────────────┐
                                                  │   _run_chat_     │
                                                  │   pipeline()     │
                                                  └────────┬─────────┘
                                                           │
                       ┌───────────────────────────────────┴──────────────────────────────────┐
                       │                                                                      │
                       ▼                                                                      │
   ┌────────────────────────────────┐    emit:                                                │
   │  1. _classify_query()          │ ──> {"type":"stage","stage":"route","status":"done",    │
   │     (rule-based)               │      "engine":"m3","use_hyde":true,"reason":"…"}        │
   │                                │                                                          │
   │  Rules (順序判斷):             │                                                          │
   │   · IPC code regex             │                                                          │
   │     /\b[A-H]\d{2}[A-Z]…\b/     │                                                          │
   │   · doc number regex           │                                                          │
   │     TWxxxxxxxA / Ixxxxxx       │                                                          │
   │   · ≤4 words → short-lookup    │                                                          │
   │   · else → natural-language    │                                                          │
   │                                │                                                          │
   │  literal/short → m3 (no HyDE) │                                                          │
   │  natural-lang  → m3 + HyDE     │                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼ if use_hyde                                                              │
   ┌────────────────────────────────┐    emit start + done                                     │
   │  2. _expand_with_hyde()        │ ──> {"stage":"hyde","status":"start"}                    │
   │     small Ollama call to       │     {"stage":"hyde","status":"done",                     │
   │     synthesize a hypothetical  │      "expanded_chars": 505}                              │
   │     answer; that text is the   │                                                          │
   │     actual search query        │                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐    emit start + done                                     │
   │  3. _search_dispatcher()       │ ──> {"stage":"search","status":"done","results":N}       │
   │                                │                                                          │
   │  baseline (engine=baseline)    │   m3 (engine=m3)                                         │
   │  ─────────────────────────     │   ──────────────────                                     │
   │  · MiniLM dense (384d)         │   · bge-m3 dense (1024d)                                 │
   │  · MatchText (Qdrant lexical)  │   · bge-m3 sparse (learned)                              │
   │  · RRF fuse (k=60)             │   · RRF fuse (k=60)                                      │
   │                                │                                                          │
   │  → fetch_k=30 candidates                                                                  │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐                                                          │
   │  4. CrossEncoder rerank        │                                                          │
   │     bge-reranker-v2-m3         │                                                          │
   │     (query, passage) pairs     │                                                          │
   │     → rerank_score             │                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐                                                          │
   │  5. _mmr_select(λ=0.7)         │                                                          │
   │                                │                                                          │
   │  iterate: pick whichever       │                                                          │
   │  remaining candidate maximizes │                                                          │
   │   λ·rel − (1−λ)·max_sim_picked │                                                          │
   │                                │                                                          │
   │  similarity proxy = same       │                                                          │
   │  doc_number indicator (1 or 0) │                                                          │
   │  → forces cross-doc diversity  │                                                          │
   │  → top_k=5                     │                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐    emit:                                                 │
   │  6. Confidence threshold gate  │ ──> {"stage":"threshold","status":"done",                │
   │                                │      "top_score":0.889,"min_required":0.05}              │
   │  if max(rerank_score) <        │                                                          │
   │     MIN_RERANK_SCORE (0.05):   │                                                          │
   │   → return refusal message,    │                                                          │
   │     skip LLM,                  │                                                          │
   │     mark low_confidence=true   │                                                          │
   │                                │                                                          │
   │  Why: indirect-semantic        │                                                          │
   │  questions on the baseline     │                                                          │
   │  retriever score ~0.001;       │                                                          │
   │  feeding that to the LLM       │                                                          │
   │  produces confident hallucination                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐    emit during generation:                               │
   │  7. generate_stream()          │ ──> {"type":"token","content":"…"} (per token)           │
   │                                │     {"type":"sources","sources":[{…},…]}                 │
   │  · prompt = RAG_PROMPT +       │     {"type":"done","answer":"…","query_log_id":N}        │
   │    history(10 turns) +         │     {"type":"summary","engine":"…","top_rerank":0.889}   │
   │    [Source N] tagged contexts  │                                                          │
   │  · Ollama /api/generate stream │                                                          │
   │  · LLM ends with               │                                                          │
   │    "Confidence: HIGH/MED/LOW"  │                                                          │
   │  · 6×4060 8GB → ~30s TTFT      │                                                          │
   └────────────────┬───────────────┘                                                          │
                    │                                                                          │
                    ▼                                                                          │
   ┌────────────────────────────────┐                                                          │
   │  8. log_query() → PG           │                                                          │
   │     alert_high_latency() →     │                                                          │
   │     webhook if elapsed > 60s   │                                                          │
   └────────────────────────────────┘                                                          │
```

前端 `renderStageBar()` 直接吃這串 stage events，把每段耗時畫成五色 progress bar，不再用假的 `setTimeout` 動畫。

---

## 5. Data stores

### 5.1 Qdrant — 雙 collection

| Collection | Vector | Sparse | Used by | Index/payload |
|---|---|---|---|---|
| `patent_chunks` | MiniLM 384d cosine | – | baseline path | `text` (full-text), `filename` `doc_number` `section` `tag` (keyword) |
| `patent_chunks_m3` | bge-m3 1024d cosine | bge-m3 learned sparse | m3 path | same payload schema; sparse stored under `sparse` named-vector |

兩個 collection 共用相同的 `payload` schema → 前端 source rendering 與引用標註不需要分支。

**Chunk ID 是 deterministic UUID5**（namespace = `6c1f8c2e-…`）：

```python
id = uuid5(NAMESPACE, f"{filename}::{section}::{page}::{sha1(text)[:16]}")
```

→ 重跑 ingest 自動冪等，不會產生重複 chunk。

### 5.2 PostgreSQL — 審計層

Schema 來源：[`scripts/init_db.sql`](../scripts/init_db.sql)。

```
documents      (doc_id PK, filename, source_type, total_pages, total_chunks,
                ocr_applied, ocr_engine, file_size_kb, tags, ingested_at)
query_logs     (qid SERIAL PK, query, answer, top_k, sources JSONB,
                model, total_tokens, latency_ms, created_at)
feedback       (id SERIAL PK, query_log_id → query_logs(qid),
                rating CHECK IN (-1,1), comment, created_at)
eval_results   (eval_id SERIAL PK, eval_set, question, expected, actual,
                recall_at_5, faithfulness, latency_ms, passed, created_at)
```

當 PG 連不到時，`rag_service._db` 會設為 `None`，所有 `log_query` / `log_feedback` / `log_document` 呼叫都靜默略過（用 `if _db:` 守門）— 沒有 SQLite fallback。chat 仍可運作，但**沒有審計記錄**、`/api/admin/stats` 與 feedback 串接都會空轉。單機 demo 想完整體驗 admin 介面就需要起 PG。

### 5.3 Filesystem

```
data/
├── patents/                  原始上傳的 PDF/XML（gitignored）
├── patents_real/             正式評測用真實專利 XML（gitignored）
├── patents_real_split/       拆分後 100 個專利（gitignored）
├── processed/                OCR 中間產物（gitignored）
└── eval/
    ├── ab_bench_100patents.md   demo 評測結果（會推 git）
    ├── sample_questions.jsonl   eval 題庫（會推 git）
    └── report.html              最近一次 run 報告（gitignored）
```

---

## 6. Security model

| 層級 | 機制 | 限制 |
|---|---|---|
| 認證 | JWT (HS256, 24h expire), `Authorization: Bearer …` | 單一 user 寫死在 env vars（POC）|
| 授權 | `role: admin/user` claim | 目前只看是不是有 token，沒做細粒度 RBAC |
| Rate limit | per-IP per-minute（in-memory dict）| `RATE_LIMIT_PER_MINUTE=30` 預設 |
| Secret 管理 | `.env`（gitignored），預設值寫在 code 但有 `change-me-in-production-v3` 警告字串 |
| Upload 限制 | FastAPI 預設 + chunked read（避免 OOM）| 沒做 file-type 嚴格驗證 |

⚠ **POC 模式預設 admin/patent2026 + JWT secret 寫死。Production 必改。**

---

## 7. Observability

### 7.1 Health probe

```
GET /api/health         → 200 with subsystem status (即使 PG down 也回 200)
GET /api/health/strict  → 503 if any subsystem down (k8s liveness 用)
```

回應範例：

```json
{
  "status": "ok",
  "subsystems": {"qdrant": true, "ollama": true, "postgres": false},
  "uptime_s": 685.4,
  "models": {
    "llm": "qwen2.5:7b",
    "embed": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "rerank": "BAAI/bge-reranker-v2-m3"
  }
}
```

### 7.2 Prometheus metrics

`GET /metrics` 出 6 個 counters/gauges：

```
patent_rag_queries_total
patent_rag_low_confidence_total
patent_rag_errors_total
patent_rag_tokens_total
patent_rag_latency_ms_avg
patent_rag_uptime_s
```

### 7.3 Stage telemetry

每個 `/api/chat` 都會在 NDJSON stream 裡附帶 stage events，前端用來畫 progress bar，後端 grep `query_logs.engine` + `top_rerank` 也能事後分析。

### 7.4 Webhook alerts

`alert_high_latency()` 在 elapsed > 60 s 時 POST 一個 Slack/Discord-compatible payload 到 `WEBHOOK_URL`（如果有設）。

---

## 8. Design choices & trade-offs

| 選擇 | 為什麼 | 代價 |
|---|---|---|
| Single FastAPI process | 部署簡單、debug 不用看跨機器 log | 單 worker、scale 受 GIL 限制 |
| In-process embedder/reranker | 避免 model server 成本與冷啟動 | 啟動慢 ~15s |
| Two Qdrant collections（baseline + m3）| 允許 A/B 對比，不污染對方索引 | RAM 翻倍 |
| MiniLM baseline + bge-m3 SOTA 並存 | demo 賣點：可以同題對比，最戲劇性的指標是某道間接語意測試題 baseline 0.0014 → m3+HyDE 0.889（接近零的比值要謹慎解讀，見 README 註腳）| 維護兩條 ingest 路徑 |
| Rule-based router (`_classify_query`) | 0 LLM call、確定性、可解釋 | 無法處理 edge case，未來可換 small classifier model |
| Reranker confidence floor | 防止低分上下文進 LLM 產生 hallucination | 偶爾擋掉合理但低分的答案（floor=0.05 是保守值）|
| MMR with same-doc indicator | 強制跨專利多樣性，cross-doc 題型表現變好 | 同 patent 內多個相關段不會一起出現 |
| HyDE 只在自然語言題啟用 | IPC code/doc number 題型加 HyDE 反而干擾 | router 判斷錯就會浪費 30s |
| SSE NDJSON + 同一 generator 也餵 non-stream | 兩種 mode 一份程式碼路徑 | non-stream 還是要等整個 pipeline 完才回 |
| Deterministic chunk UUID5 | re-ingest 冪等，不需 reset DB | 修改 chunker 邏輯後舊 ID 不會自動清掉，要 manual purge |

---

## 9. Deployment topology

### 9.1 Dev / demo（單機）

```
host:
  ├── ollama serve              :11434  (native)
  ├── qdrant (docker)           :6333
  ├── postgres (docker)         :5432   (optional — chat works without it, but audit log is silently dropped)
  └── uvicorn apps.api.main:app :8000
```

`docker-compose.yml` 啟動 Qdrant + PG + API 三件套，Ollama 留在 host 因為要吃 GPU。

### 9.2 Production（k8s 草案）

`k8s/deployments.yaml` 定義：
- `patent-rag-api` Deployment (3 replicas, readiness=`/api/health/strict`)
- `qdrant` StatefulSet (PVC for vectors)
- `postgres` StatefulSet (managed DB recommended in real prod)
- Ollama 通常拉外部 endpoint（self-hosted GPU node 或 vLLM cluster）

⚠ k8s manifests 是 POC 草案，沒做 HPA / network policy / secret rotation。

---

## 10. 可擴充點 / 未來路線

- **A6 ColBERT late-interaction**：bge-m3 已經編碼好 colbert vectors，只要在 retrieval_v2 開 `return_colbert_vecs=True` + 加 late-interaction 重排（~150 行 + RAM 2×）
- **Query log → eval set**：`scripts/run_eval.py` 已經支援讀 `query_logs` 抽 sample，未來可做半自動回歸測試
- **Multi-tenant**：JWT 已有 `sub`，加 `tenant_id` 到 Qdrant payload 與 PG schema 即可水平切分
- **小型 LLM router**：rule-based 換成 quantized 100M-class classifier，能處理「混合語意」的 query
- **Edge inference**：reranker 是 bottleneck，可走 ONNX runtime + CPU SIMD 給輕量部署用
