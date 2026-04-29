# Security Policy

## ⚠️ POC defaults — read this first

This project ships with intentionally weak defaults so that a fresh
`make dev` works out of the box for demos:

| Setting | Default value | Action required for any non-local use |
|---|---|---|
| `AUTH_USERNAME` | `admin` | Override via env |
| `AUTH_PASSWORD` | `patent2026` | **Override via env (mandatory)** |
| `JWT_SECRET` | `change-me-in-production-v3` | **Override with a random ≥32-byte secret (mandatory)** |
| `RATE_LIMIT_PER_MINUTE` | `30` | Tune for your traffic |

If you deploy this to a publicly-reachable address without overriding
those values, **anyone can log in as admin and reset your vector DB**
via `DELETE /api/reset`. Don't do that.

## Reporting a vulnerability

For security issues that should not be discussed in public:

1. Open a [GitHub Security Advisory](https://github.com/Washyu0826/shin-lee-patent-rag/security/advisories/new)
   on the repository. This creates a private channel between you and
   the maintainers.
2. Please include:
   - A clear description of the issue
   - Reproduction steps (exact request / payload / config)
   - Impact assessment in your view (read-only data leak / RCE / DoS / auth bypass)
   - Suggested fix if you have one

Do **not** open a public issue for vulnerabilities — public disclosure
before a patch puts every running deployment at risk.

For non-security issues, the regular issue tracker is the right place.

## Response timeline (best-effort, this is a research POC)

| Severity | First reply | Triaged | Patch in main | Public disclosure |
|---|---|---|---|---|
| Critical (RCE, auth bypass) | 48 h | 1 week | 2 weeks | After patch + downstream notification |
| High (data leak, privilege escalation) | 1 week | 2 weeks | 4 weeks | After patch |
| Medium / Low | Best effort | Best effort | Next release | With release notes |

The maintainer is a single student, not a team — the timeline above is
a target, not a contract.

## Scope

In scope:
- Python code under `apps/`
- JavaScript code under `ui/`
- Helper scripts under `scripts/`
- Container images built from `Dockerfile`
- The default config in `.env.example`

Out of scope:
- Bugs in upstream dependencies (Qdrant, Ollama, FastAPI, BAAI models,
  etc.) — please report those to their respective projects
- Issues that only manifest after intentionally weakening the security
  posture (e.g., setting `JWT_SECRET=""`, exposing `:6333` without a
  firewall)
- Attacks that require physical access to the host

## Known weaknesses (already documented)

These are accepted limitations of the current release — they are not
secrets, but it would be misleading to claim they're fixed:

- **Single hard-coded user** — `AUTH_USERNAME` / `AUTH_PASSWORD` is
  one global account; no user table, no session revocation, no MFA.
  See `apps/api/auth_service.py`.
- **No CSRF protection** — the chat endpoint accepts JSON POST with
  bearer token; if you embed this UI inside a portal that holds the
  token in localStorage, a malicious page on the same origin can
  drive `/api/chat`. POC scope, not addressed.
- **In-memory rate limit** — survives one process; no shared state
  across replicas.
- **No mTLS** between API → Qdrant / Ollama / Postgres — they're
  expected to be on a private network.
- **No PII redaction** in `query_logs` — anything a user types lands
  in the audit table verbatim.

These will be addressed if the project graduates from POC.
