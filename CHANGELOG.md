# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Query Coach** (`/api/coach`): corpus-aware suggestion panel that
  groups indexed patents by IPC main class and applicant, surfaces
  cross-document comparison candidates, and seeds a stress-test query
  to demo the refusal mechanism. Frontend shows it as a "What can I
  ask?" link in the input toolbar — no LLM call.
- **Dual-write upload pipeline**: `/api/upload`, `/api/ingest/xml`,
  and `/api/ingest/scan` now write to both the baseline (MiniLM) and
  m3 (bge-m3) Qdrant collections so cross-lingual queries (zh ↔ en)
  work for newly-uploaded files. m3 write is best-effort; baseline
  remains the source of truth.
- **Data sources triage** (`docs/DATA_SOURCES.md`): every external
  document source must be registered with its licence status before
  it can be ingested. ISO standards and Espacenet bulk are explicitly
  refused; TIPO open data is the only confirmed-permissive source.
- **Markdown rendering** in chat answers via an in-house allowlist
  parser; supports headings, bold/italic, fenced code, lists,
  blockquotes, links — runs after HTML escape so it stays XSS-safe.
- **Command palette** (Cmd/Ctrl+K) with searchable command groups for
  navigation, engine switching, theme toggle, language switch.
- **UI polish v2**: skeleton loaders for files / patents / admin
  sections, empty states with contextual icons, toast notifications
  for upload + feedback, Lucide-derived inline SVG icon set
  (replacing emoji).
- **Enterprise UI v1**: design tokens (4pt scale, 8-step type ramp,
  5-tier shadow elevation), dark mode via `[data-theme]` + system
  preference, gradient brand mark in header.
- **Detailed Traditional Chinese README** (later rewritten for
  non-technical readers) with concrete benchmark numbers, honest
  caveats, and pitch script.

### Changed
- **635× headline reframed**: every occurrence in README,
  ARCHITECTURE, PROJECT_BRIEF_NONTECH, PROJECT_STORY now states
  "single test query, confidence score (not accuracy), ratio sensitive
  to near-zero denominator". The 0.0014 → 0.889 numbers stay because
  they're real and traceable, but readers get the full picture.

### Fixed
- **Cross-platform path handling** (`_normalize_uploaded_name`):
  `Path("a\\b\\c.pdf").name` returns the whole string on Linux
  (backslash is not a separator there), causing the unit test to fail
  on ubuntu-latest while passing on Windows. Now normalises
  backslashes to forward slashes before extracting the basename. Also
  fixes a real bug where Windows browsers submitting filenames with
  backslashes wrote oddly-named files on Linux servers.

### Removed
- **Fabricated claims** scrubbed from README and ARCHITECTURE.md:
  - Qdrant collection name `patent_chunks_v2` → real name is
    `patent_chunks_m3`
  - "PostgreSQL fallback to SQLite" — no such fallback exists
  - Function names `_log_query` / `_save_feedback` / `_log_document`
    were invented; real names are `log_query`, `log_feedback`,
    `log_document`
  - Database schema in ARCHITECTURE was completely fabricated; now
    matches `scripts/init_db.sql` exactly
  - `pytest` → real CI uses `python -m unittest`

## [0.1.0] - 2026-04-28 — Initial public commit

Full RAG pipeline shipped with auto-routing, MMR diversity, reranker
confidence floor, SSE stage events, and dual-collection A/B
infrastructure. Backend in FastAPI, frontend in vanilla JS, deployable
via docker-compose. CI (GitHub Actions) runs 22 unit tests on
ubuntu-latest in ~28s.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full picture.
