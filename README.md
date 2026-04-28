# Patent RAG Chatbot v3

Taiwan patent OCR/RAG chatbot — GDG on Campus × TPIsoftware (昕力資訊)

> ⚠️ **POC defaults — change before any non-local deployment.** This repo ships with `AUTH_USERNAME=admin` / `AUTH_PASSWORD=patent2026` and `JWT_SECRET=change-me-in-production-v3` as placeholders so the demo runs out-of-the-box. **Override `AUTH_PASSWORD` and `JWT_SECRET` via environment variables (or `.env`) before exposing the API.**

## Features

**OCR & Ingestion**: PaddleOCR + Tesseract (user-selectable) | XML parsing (data.gov.tw) | Batch upload | Auto-scan folder | Reprocess button | OCR side-by-side comparison

**Search**: Hybrid baseline (dense + lexical + metadata filter) | Optional bge-m3 + RRF path | Reranker (bge-reranker-v2-m3) | Patent number / IPC / applicant filtering | Tag-based knowledge groups

**Chat**: Streaming responses | Multi-turn (10 rounds) | File scope switching | Dynamic suggested questions | English responses | Patent comparison table

**UI**: Light professional theme | PDF preview with zoom + highlight | Expandable citations (patent# + section + page + clickable) | Feedback (thumbs + text) | Chat export | localStorage history | i18n (EN/ZH) | Patent browser | Admin dashboard

**Security**: JWT login required for API usage | Admin-only reset/reindex endpoints | Rate limiting | Safer upload/path validation | Audit logging (PostgreSQL)

**Eval**: Auto-scoring test set | HTML report | Unit-test regression coverage

**Deploy**: Docker Compose | Kubernetes manifests | OpenAPI/Swagger (built-in)

## Quick Start

```bash
cp .env.example .env
make up && make pull && make install
make dev  # http://localhost:8000
# Set AUTH_PASSWORD / JWT_SECRET in .env before sharing the app
```

Prerequisites: Docker, Python 3.10+, NVIDIA GPU (optional), `apt install tesseract-ocr tesseract-ocr-chi-tra`

## Architecture

```
┌──────────┐     ┌───────────────┐     ┌────────┐     ┌────────┐
│  Chat UI │────>│   FastAPI      │────>│ Qdrant │     │ Ollama │
│  (HTML)  │<────│  API backend   │────>│(hybrid)│     │ (LLM)  │
└──────────┘     └───────┬───────┘     └────────┘     └────────┘
                         │             ┌────────────┐
                         └────────────>│ PostgreSQL │
                                       │ (audit log)│
                                       └────────────┘
```

Production: Add **digiRunner** (OIDC + API Key) + **Dify** (RAG orchestration)

## Project Structure

```
├── docker-compose.yml
├── apps/api/
│   ├── main.py            # FastAPI endpoints + auth + health + ingest
│   ├── ocr_service.py     # PaddleOCR + Tesseract + smart chunking
│   ├── rag_service.py     # Baseline hybrid retrieval + reranker + logging
│   ├── xml_parser.py      # Taiwan patent XML parser
│   ├── auth_service.py    # JWT auth
│   └── webhook.py         # Alert notifications
├── ui/index.html          # Full-featured SPA
├── k8s/                   # Kubernetes manifests
├── scripts/
│   ├── run_eval.py        # Auto evaluation + HTML report
│   └── init_db.sql        # PostgreSQL schema
├── tests/                 # Regression tests (unittest)
├── .github/workflows/     # CI
├── configs/pipeline.yaml
└── data/eval/sample_questions.jsonl
```

## API (key endpoints)

| Endpoint | Description |
|----------|-------------|
| POST /api/auth/login | JWT login |
| POST /api/upload | Upload PDF (OCR engine selectable, reprocess flag) |
| POST /api/upload/batch | Batch upload multiple PDFs |
| POST /api/ingest/xml | Ingest patent XML |
| POST /api/ingest/scan | Scan directory for XMLs |
| POST /api/chat | RAG chat (streaming supported) |
| POST /api/compare | Compare two patents |
| POST /api/feedback | Submit feedback (thumbs + text) |
| POST /api/export | Export conversation |
| GET /api/suggestions | Dynamic suggested questions |
| GET /api/patents | Patent browser |
| GET /api/pdf/{file}/page/{n} | PDF page image |
| GET /api/ocr-compare/{file}/{n} | OCR comparison |
| GET /api/stats | System stats |
| GET /api/admin/stats | Admin dashboard data |
| GET /api/admin/feedback | Feedback list |
| GET /api/health / /api/health/strict | Service health probes |
| GET /api/files | File list |
| DELETE /api/reset | Reset vector DB |

Notes:
- Core ingest/chat/catalog/admin endpoints require a JWT. Health probes and direct PDF/page viewer endpoints stay open so containers and browser previews can work without an auth header.
- `/api/chat` returns `query_log_id` in its final payload so feedback can be linked to a stored query.
- `GET /api/patents` accepts `limit` and now scans past the first scroll page.

## License

TBD
