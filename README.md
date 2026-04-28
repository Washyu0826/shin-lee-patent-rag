# Patent RAG Chatbot v3

> 台灣專利 OCR + RAG 檢索問答系統 — GDG on Campus × TPIsoftware（昕力資訊）合作專案。
> 在 RTX 4060 8GB VRAM 筆電上跑出 **635× retrieval lift** 的對照實驗。

> ⚠️ **POC 預設值警告**：此專案內建 `AUTH_USERNAME=admin` / `AUTH_PASSWORD=patent2026` 與 `JWT_SECRET=change-me-in-production-v3` 純粹為了讓 demo 立刻能跑。**任何非本機部署前必須**透過環境變數（或 `.env`）覆蓋 `AUTH_PASSWORD` 與 `JWT_SECRET`。

---

## 目錄

- [一句話介紹](#一句話介紹)
- [為什麼值得看](#為什麼值得看)
- [效能對照（A/B/C benchmark）](#效能對照abc-benchmark)
- [系統架構](#系統架構)
- [快速開始](#快速開始)
- [環境變數](#環境變數)
- [API 端點](#api-端點)
- [前端使用](#前端使用)
- [專案結構](#專案結構)
- [開發與測試](#開發與測試)
- [部署](#部署)
- [路線圖](#路線圖)
- [授權與致謝](#授權與致謝)

---

## 一句話介紹

把 PDF/XML 形式的台灣專利資料丟進來，可以用**自然語言**（中／英文）問問題，系統會用混合式向量檢索找出相關段落、用 cross-encoder 重排序、再用本地 LLM（Ollama）串流產生有 **citation 引用標註** 的答案，每個引用都能跳回原始 PDF 的對應頁面。

支援的問題類型（以下都實測過、語料內有對應專利）：

- 直接事實：「列出 I918613 號專利的 IPC 分類」（I918613 在語料內）
- 跨文檢索：「哪些專利涉及抗體或抗原結合分子？」（命中 I918591 抗 VIII 因子抗體、I918600 PI4 激酶抑制劑）
- 專有名詞：「跟偏光膜相關的專利有哪些？」（命中 I918604 偏光膜製造方法）
- 比較問題：「比較 TW202401234A 與 TW202405678B 的技術差異」（兩者皆為 demo 合成資料，存在於語料）

**間接語意**（壓力測試）：「Which technologies can be used for energy saving or energy recovery?」— 語料**沒有**直接對應的能量回收／再生煞車專利。這條查詢是用來測**字面找不到時系統會不會空手而回**：m3+HyDE 仍能擴展 query 找到語意間接相關的 I918612（燒結設備）、I919900（衣物處理設備），baseline 完全失敗。詳見下方對照表。

---

## 為什麼值得看

這個 repo 不是又一個 LangChain demo。重點在於**在硬體限制下做出真實可用的決策**。

### 1. 自動路由（query classifier）取代「靠使用者選引擎」

```
query 進來
  ├─ 含 IPC code / 專利號     → m3（不加 HyDE，加了反而干擾）
  ├─ ≤ 4 字短查詢              → m3（短查詢沒語意可擴展）
  └─ 自然語言問題              → m3 + HyDE（值得多花 15s 換更高 grounding）
```

實作在 `apps/api/main.py:_classify_query()`，rule-based 不用額外 LLM call，可解釋、確定性。前端 UI 顯示「為什麼選這個 engine」的原因標籤。

### 2. Reranker confidence floor 阻止 LLM 唬爛

當 cross-encoder rerank score 低於 `MIN_RERANK_SCORE=0.05` 時，**直接拒答**並回傳「找不到夠相關的段落」，不浪費 30 秒讓 LLM 編一個自信滿滿的錯誤答案。前端用紅色 badge 標 `LOW` 信心，設計上就讓使用者警覺。

### 3. MMR 多樣性選擇（避免 top_k 全來自同一個專利）

Rerank 完之後跑 Maximal Marginal Relevance，用「同一篇專利視為相似」的指示函數當 redundancy proxy，強制 top_k 之間跨專利分散。對 cross-doc 問題（「比較 A 跟 B」）特別有效。

### 4. SSE 階段事件流 — 不再黑盒等 30 秒

每個 `/api/chat` 都會在 NDJSON stream 裡持續發 stage events：

```
{stage:"route",     status:"done", reason:"natural-language"}
{stage:"hyde",      status:"start"}
{stage:"hyde",      status:"done", expanded_chars:505}
{stage:"search",    status:"done", results:30}
{stage:"threshold", status:"done", top_score:0.889, min_required:0.05}
{stage:"gen",       status:"start"}
{type:"token", content:"..."}    // ← 開始噴 token
```

前端 `renderStageBar()` 直接吃這串，把每段耗時畫成五色 progress bar — **不再用假的 setTimeout 動畫騙使用者**。

### 5. 雙 Qdrant collection（baseline + SOTA），同題可一鍵 A/B

每個答案下面有 4 顆 regenerate 按鈕：`Baseline / m3 / m3+HyDE / Auto`。同一個問題立刻換引擎重答，質量差異一目了然。對 demo 跟報告寫作非常有用。

### 6. Deterministic chunk ID（UUID5 over filename + section + page + sha1）

重跑 ingest 完全冪等，不需要 reset DB。對 cron 自動同步資料夾很關鍵。

### 7. 可觀測性 ops 已就緒

- `GET /api/health` — 各子系統狀態（Qdrant / Ollama / Postgres）
- `GET /api/health/strict` — k8s liveness 用，degraded 直接 503
- `GET /metrics` — Prometheus 文字格式，6 個 counter/gauge
- 高延遲 webhook 警報（Slack/Discord 相容）

---

## 效能對照（A/B/C benchmark）

實際跑出來的數字（100 篇真實 TIPO 專利、1600 chunks、單機 RTX 4060 8GB）。

### Reranker top-1 信心分數（0–1，越高越好）

| 問題類型 | Baseline (MiniLM) | m3 (bge-m3 + RRF) | m3 + HyDE |
|---|---:|---:|---:|
| 直接事實（IPC 列表） | 0.018 | 0.387 | **0.521** |
| **間接語意**（能量回收） | 0.0014 | 0.0014 | **0.889** |
| 跨文（抗體） | 0.708 | 0.779 | **0.970** |
| 專有名詞（偏光膜） | 0.528 | 0.699 | **0.954** |

**重點觀察**：間接語意題從 0.0014 → 0.889，**提升 635 倍**。這條查詢「energy saving or energy recovery」在 100 篇語料中**沒有任何專利**用相同關鍵字 — baseline 完全失敗（0.0014），m3 不啟用 HyDE 也失敗（0.0014）。**只有 m3 + HyDE 把查詢先擴寫成假設答案後**，才橋接到語意相關的 I918612（燒結設備，能源／熱管理）與 I919900（衣物處理設備）。這就是 vocabulary gap 問題的具體量化證據。

### 端到端延遲（秒）

| 問題類型 | Baseline | m3 | m3 + HyDE |
|---|---:|---:|---:|
| 直接事實 | 20.8s | 17.3s | 34.1s |
| 間接語意 | 15.9s | 25.9s | 37.1s |
| 跨文 | 15.3s | 33.3s | 41.4s |
| 專有名詞 | 20.1s | 61.1s | 35.2s |

HyDE 額外加 15–20 秒，但換來大幅 grounding 提升 — 對「答錯成本高」的場景（專利分析、法務）值得。完整數據在 [`data/eval/ab_bench_100patents.md`](data/eval/ab_bench_100patents.md)。

---

## 系統架構

```
                    ┌─────────────────────┐
                    │  Browser (SPA)      │
                    │  ui/index.html      │
                    └──────────┬──────────┘
                               │ HTTP / SSE
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                FastAPI (uvicorn, single process)                 │
│                                                                  │
│   _classify_query() → _expand_with_hyde() → _search_dispatcher() │
│        ↓                  ↓                       ↓              │
│   route+reason        HyDE expansion       baseline | m3         │
│                                                    ↓             │
│                    CrossEncoder rerank → MMR → threshold gate    │
│                                                    ↓             │
│                       generate_stream() (Ollama, NDJSON)         │
└─────┬─────────────────────┬─────────────────────────┬────────────┘
      │ HTTP                │ HTTP stream             │ asyncpg
      ▼                     ▼                         ▼
┌───────────┐         ┌──────────────┐         ┌────────────┐
│  Qdrant   │         │   Ollama     │         │ PostgreSQL │
│  :6333    │         │   :11434     │         │   :5432    │
│           │         │              │         │            │
│ 兩個      │         │ qwen2.5:7b   │         │ documents  │
│ collection│         │ Q4_K_M       │         │ query_logs │
│ (baseline │         │              │         │ feedback   │
│  + m3)    │         │              │         │ + SQLite   │
│           │         │              │         │   fallback │
└───────────┘         └──────────────┘         └────────────┘
```

完整版（含請求流程圖、模組職責表、設計取捨）在 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 快速開始

### 路線 A：Docker Compose（最簡單）

```bash
git clone https://github.com/Washyu0826/shin-lee-patent-rag.git
cd shin-lee-patent-rag
cp .env.example .env

# 一條命令拉起 Qdrant + PG，並安裝 API 依賴
make up && make pull && make install
make dev   # http://localhost:8000
```

### 路線 B：原生 Python（控制力最高）

需要先有：

- Python 3.11+
- Ollama（裝在本機或遠端）
- Qdrant（建議 Docker 跑）
- PostgreSQL（**選用** — 不裝可以跑 chat，但所有 query log / feedback / 文件記錄會被靜默丟棄、`/api/admin/*` 會空轉）
- `tesseract-ocr` + `tesseract-ocr-chi-tra`（要 Tesseract OCR 才需要）

```bash
# 1. 建立虛擬環境
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r apps/api/requirements.txt

# 2. 拉模型
ollama pull qwen2.5:7b

# 3. 啟 Qdrant（Docker）
docker run -d -p 6333:6333 -p 6334:6334 qdrant/qdrant

# 4. 設環境變數
cp .env.example .env   # 編輯密碼

# 5. 啟動 API
cd apps/api
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

打開 http://127.0.0.1:8000/ 開始用（預設帳密 `admin` / `patent2026`，只是 POC 用，正式請改）。

### 第一次上傳資料

進到 UI 後，左側拖曳區把 PDF/XML 拉進去就會自動 OCR + 切 chunk + 索引。等右下角 stats 出現 `Chunks: N` 就完成。

或用腳本批次抓真實專利：

```bash
python scripts/fetch_real_patents.py   # 從 TIPO 拉 100 篇
```

---

## 環境變數

完整清單在 [`.env.example`](.env.example)。常用：

| 變數 | 預設 | 說明 |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 連線 URL |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 連線 URL |
| `LLM_MODEL` | `qwen2.5:7b` | LLM 模型名（要 `ollama pull` 過）|
| `EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | baseline embedder |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Cross-encoder reranker |
| `ENABLE_RERANK` | `true` | 關掉可換取 ~3s 速度 |
| `MIN_RERANK_SCORE` | `0.05` | 低於這個分數直接拒答 |
| `MMR_LAMBDA` | `0.7` | MMR 多樣性係數（1.0 = 純相關性，0 = 純多樣性）|
| `DATABASE_URL` | `postgresql://...` | 連不到時 `_db = None`、查詢 / feedback / 文件記錄會靜默略過（chat 仍可用），無 SQLite fallback |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | `admin` / `patent2026` | **POC 預設，正式必改** |
| `JWT_SECRET` | `change-me-in-production-v3` | **正式必改** |
| `RATE_LIMIT_PER_MINUTE` | `30` | 單 IP 每分鐘 query 上限 |
| `WEBHOOK_URL` | (空) | Slack/Discord 高延遲警報 |
| `AUTO_SCAN_DIR` | `./data/patents` | cron 自動掃描資料夾 |

---

## API 端點

完整 schema 在 `http://localhost:8000/docs`（Swagger UI）。常用：

| 端點 | 說明 |
|---|---|
| `POST /api/auth/login` | 拿 JWT token |
| `POST /api/upload` | 上傳 PDF（OCR 引擎可選） |
| `POST /api/upload/batch` | 批次上傳多個 PDF |
| `POST /api/ingest/xml` | 上傳專利 XML |
| `POST /api/ingest/scan` | 掃描資料夾批次匯入 |
| `POST /api/chat` | RAG 對話（NDJSON 串流） |
| `POST /api/compare` | 比較兩個專利 |
| `POST /api/feedback` | 提交 thumbs + 文字評論 |
| `GET /api/retrieve_debug` | 檢索 funnel debug（dense/sparse/fused/reranked）|
| `GET /api/suggestions` | 動態推薦問題 |
| `GET /api/patents` | 專利清單 |
| `GET /api/pdf/{file}/page/{n}` | PDF 頁面預覽圖 |
| `GET /api/stats` | 系統統計 |
| `GET /api/admin/stats` | 管理後台儀表板 |
| `GET /api/admin/feedback` | 使用者反饋列表 |
| `GET /api/health` / `/api/health/strict` | 健康探針 |
| `GET /metrics` | Prometheus 指標 |
| `GET /api/files` | 已上傳檔案列表 |
| `DELETE /api/reset` | 重置向量索引（admin only）|

注意事項：

- `POST /api/chat` 的最後一筆 NDJSON 帶 `query_log_id`，前端用這個串 feedback
- 大部分端點需要 JWT；只有 `/api/health*`、`/metrics`、`/api/pdf/.../page/...` 公開
- `RATE_LIMIT_PER_MINUTE` 預設 30，超過回 429

---

## 前端使用

UI 是 vanilla JavaScript SPA（沒用任何框架），實作在 `ui/` 三個檔案：

```
ui/
├── index.html       # markup（150 行）
└── assets/
    ├── styles.css   # 設計系統 + 元件樣式（~30 KB）
    └── app.js       # 邏輯（~28 KB）
```

### 主要功能

- **Chat 頁** — 串流答案、五色階段進度條、HIGH/MED/LOW 信心 badge、四顆 regenerate 按鈕
- **Patents 頁** — 已上傳的專利清單（doc#、title、IPC、applicant）
- **Compare 頁** — 兩個專利的 bibliographic / abstract / claim_1 並排比對
- **Admin 頁** — chunks / docs / queries / 平均延遲 + 熱門查詢 top 10
- **PDF Preview pane**（右側）— 點 `[Source N]` 引用會跳出 PDF 該頁 + 引用文字高亮

### 鍵盤快捷鍵

| 快捷鍵 | 功能 |
|---|---|
| `Ctrl+K` | 循環切換引擎（Auto / Baseline / m3）|
| `Ctrl+L` | 游標跳到輸入框 |
| `Enter` | 送出問題 |

### 主題切換

右上角太陽/月亮 icon 切換明暗主題，會記住偏好；首次造訪預設跟隨系統 `prefers-color-scheme`。

---

## 專案結構

```
shin-lee-patent-rag/
├── README.md
├── V3_SPEC.md
├── Makefile                       # make up / dev / test / install / pull
├── docker-compose.yml             # Qdrant + PG + API
├── .env.example
│
├── apps/api/
│   ├── main.py                    # FastAPI routes + auth + pipeline orchestration
│   ├── rag_service.py             # baseline retrieval + reranker + Ollama streaming
│   ├── retrieval_v2.py            # bge-m3 hybrid path（dense + sparse + RRF）
│   ├── ocr_service.py             # PDF → text（PyMuPDF / Paddle / Tesseract）
│   ├── xml_parser.py              # TIPO 專利 XML → section-aware chunks
│   ├── auth_service.py            # JWT login
│   ├── webhook.py                 # Slack/Discord 警報
│   ├── Dockerfile
│   └── requirements.txt
│
├── ui/
│   ├── index.html
│   └── assets/
│       ├── styles.css             # 設計系統 + 元件
│       └── app.js                 # SPA 邏輯
│
├── scripts/
│   ├── ab_bench.py                # A/B/C 評測腳本
│   ├── demo_warmup.py             # demo 前暖機（載模型 + 預熱 cache）
│   ├── fetch_real_patents.py      # 從 TIPO 抓真實專利
│   ├── make_demo_pdfs.py          # 產 demo 用合成 PDF
│   ├── run_eval.py                # 自動評測 + HTML 報告
│   └── init_db.sql                # PostgreSQL schema
│
├── tests/
│   ├── test_main_helpers.py       # path/env helper unit tests
│   ├── test_auth_service.py       # JWT auth tests
│   ├── test_rag_service.py        # search / rerank / compare tests
│   └── test_api_integration.py    # FastAPI httpx integration tests
│
├── data/
│   ├── patents/                   # 上傳的 PDF/XML（gitignored）
│   ├── patents_real/              # 真實專利原檔（gitignored）
│   └── eval/
│       ├── ab_bench_100patents.md # 完整 benchmark 結果（commit 進去）
│       └── sample_questions.jsonl # 評測題庫
│
├── docs/
│   ├── ARCHITECTURE.md            # 系統架構（10 sections，含完整 pipeline 圖）
│   ├── API.md
│   ├── DATA_SCHEMA.md
│   ├── DEPLOYMENT.md
│   ├── PROJECT_BRIEF_NONTECH.md   # 給非技術讀者的版本
│   └── PROJECT_STORY.md           # 專案動機 / 設計過程
│
├── k8s/                           # Kubernetes manifests（POC）
├── configs/pipeline.yaml
└── .github/workflows/ci.yml       # GitHub Actions（unittest discover）
```

---

## 開發與測試

```bash
# 跑單元測試
make test

# 或直接跑 unittest
python -m unittest discover -s tests -v

# 跑 A/B/C benchmark
python scripts/ab_bench.py

# 跑 eval + 產 HTML 報告
python scripts/run_eval.py --output data/eval/report.html
```

CI 在每個 push 自動跑 22 個 unittest（`python -m unittest discover -s tests`、ubuntu-latest、約 28 秒）。

---

## 部署

### Docker Compose（單機 / 開發 / demo）

`docker-compose.yml` 拉起：

- `qdrant` — 向量庫
- `postgres` — 審計 log
- `api` — FastAPI

Ollama 不在 compose 裡（要吃 GPU，建議裝在 host）。

### Kubernetes（POC）

`k8s/` 有 manifests 草案：

- `patent-rag-api` Deployment（3 replicas，readiness probe = `/api/health/strict`）
- `qdrant` StatefulSet
- `postgres` StatefulSet（正式建議用 managed DB）

⚠ POC 草案，沒做 HPA / NetworkPolicy / Secret rotation。正式部署請看 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

### 對接企業內網（規劃中）

未來會接：

- **digiRunner**（API gateway，OIDC + API Key）
- **Dify**（RAG 流程編排平台）

---

## 路線圖

短期：

- [ ] 加速：把 reranker 改 ONNX runtime + CPU SIMD
- [ ] ColBERT late-interaction（bge-m3 已編好向量，只差打開 flag）
- [ ] Multi-tenant：Qdrant payload + JWT 加 `tenant_id`
- [ ] Query log → 自動回歸 eval set

中期：

- [ ] 把 rule-based router 換成小型 quantized classifier（100M 參數量級）
- [ ] WebSocket 取代 SSE（雙向互動 + cancel）
- [ ] 跨語言 BM25 + 中文 jieba 切詞給 sparse retrieval

---

## 授權與致謝

授權：尚未決定（待加 LICENSE）。

致謝：

- **GDG on Campus** — 學術合作
- **TPIsoftware（昕力資訊）** — 業界合作對象
- **BAAI** — bge-m3、bge-reranker-v2-m3
- **Qdrant team** — 向量資料庫
- **Ollama** — 本機 LLM 執行環境
- **Alibaba Qwen team** — qwen2.5 系列模型
- **OpenAI** — HyDE 論文（[2212.10496](https://arxiv.org/abs/2212.10496)）

---

如果你想實際跑跑看、看效果、或想合作，**透過 GitHub Issue 聯絡**。
