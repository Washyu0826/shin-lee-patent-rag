# Contributing to Patent RAG Chatbot

Thanks for your interest. This is a research-oriented POC, but pull
requests, bug reports, and suggestions are welcome.

## Quick start for development

```bash
git clone https://github.com/Washyu0826/shin-lee-patent-rag.git
cd shin-lee-patent-rag
cp .env.example .env

python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # Linux/macOS

pip install -r apps/api/requirements.txt
pip install -r requirements-test.txt

# External services (Docker recommended)
docker run -d -p 6333:6333 qdrant/qdrant
ollama pull qwen2.5:7b               # via ollama.com
docker run -d -p 5432:5432 postgres   # optional, audit log only

# Run the API
cd apps/api
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ — UI auto-logs in with `admin` / `patent2026`.

## Running tests

```bash
python -m unittest discover -s tests -v
```

CI runs the same command on `ubuntu-latest` (Python 3.11). All 22
existing tests must stay green for a PR to be accepted.

## Code style

- Python: follow PEP 8 with 4-space indent. We're adopting `ruff`
  (configured in `pyproject.toml`); please run `ruff check .` before
  submitting. Type hints encouraged where they help readability —
  not religiously enforced.
- JavaScript: vanilla JS, no frameworks. Match the existing style in
  `ui/assets/app.js` (mostly `const` / arrow functions, minimal
  abstractions, comments only for non-obvious logic).
- Commit messages: imperative mood ("Add X", not "Added X").
  Body explains *why*, not just *what*. Look at `git log` for the
  established style.

## What kinds of contributions are welcome?

### Eagerly wanted
- **More chunkers** — the current `xml_parser.py` only knows TIPO P13
  format. Adding USPTO XML, EPO XML, generic regulatory PDFs, etc.
  would expand the demo's reach.
- **Better evals** — `data/eval/sample_questions.jsonl` is tiny.
  Larger benchmark sets (with expected source citations) are
  high-value.
- **Performance work** — reranker is the bottleneck. ONNX export,
  CPU SIMD, batching strategies are all on the roadmap.
- **Bug reports with reproductions** — exact query, engine setting,
  and the source PDF (or a description if you can't share it).

### Discuss before sending a PR
- **New retrieval engines** — the codebase already has `baseline` and
  `m3`; adding a third (e.g., Cohere rerank, ColBERT) is welcome but
  please open an issue first to align on the interface.
- **Major UI rewrites** — the SPA is intentionally framework-free.
  PRs that introduce React/Vue/etc. will be rejected without prior
  discussion.

### Probably not accepted
- **Adding heavy dependencies** — current install footprint is
  intentional. New top-level dependencies need a strong case.
- **Removing the threshold gate / refusal mechanism** — that's a
  core design property, not a tunable.

## Reporting a bug

Open an issue using the bug template. Please include:

1. What you ran (exact command / API call / UI clicks)
2. What you expected
3. What actually happened (paste the full stage events from
   `/api/chat` if it's a retrieval issue)
4. Your environment: Python version, OS, GPU, `ollama list` output

## Reporting a security issue

See `SECURITY.md` — please **do not** open a public issue for security
problems.

## Licence

By contributing, you agree your contribution will be licensed under the
same MIT licence as the project.
