# Deployment

Three supported paths: local dev, Docker Compose (all-in-one), Kubernetes.

## Local development

```bash
cp .env.example .env
make up           # qdrant + ollama + postgres (Docker)
make pull         # pull qwen2.5:3b-instruct into Ollama
make install      # pip install apps/api/requirements.txt
make dev          # uvicorn main:app --reload
```

Requires: Python 3.10+, Docker, NVIDIA GPU (optional, for Ollama), `tesseract-ocr` + `tesseract-ocr-chi-tra` if you want the Tesseract OCR engine.

## Docker Compose

The included `docker-compose.yml` builds the API image and wires it to Qdrant, Ollama, and Postgres:

```bash
docker compose build api
docker compose up -d
# inside ollama: docker compose exec ollama ollama pull qwen2.5:3b-instruct
```

Env vars are read from `.env`. The API service depends on Qdrant's healthcheck passing before it starts.
For anything beyond local demo, set at least:
- `AUTH_PASSWORD`
- `JWT_SECRET`
- `POSTGRES_PASSWORD`
- `CORS_ALLOW_ORIGINS`

Volumes:
- `./volumes/qdrant` — vector data
- `./volumes/postgres` — audit/feedback/eval tables
- `./volumes/ollama` — model weights
- `./volumes/models` — HF model cache (embedder + reranker)
- `./data` — uploaded PDFs and sample XMLs

## Kubernetes

`k8s/` has a minimal manifest set: namespace, Qdrant Deployment + Service + PVC, and a `patent-api` Deployment/Service expecting a `patent-env` Secret.

Build and push the image before applying:

```bash
docker build -f apps/api/Dockerfile -t <registry>/patent-rag-api:latest .
docker push <registry>/patent-rag-api:latest

kubectl apply -f k8s/namespace.yaml
kubectl create secret generic patent-env -n patent-rag --from-env-file=.env
kubectl apply -f k8s/deployments.yaml
```

Gaps to close before production:
- No Ollama Deployment or Postgres StatefulSet yet — add these or point env vars at managed services.
- No Ingress — the API Service is `LoadBalancer`; swap to `ClusterIP` + Ingress for HTTPS termination.
- PVC is 5 Gi — size up for real corpora.
- Liveness/readiness probes aren't wired in `k8s/`; the Docker image now checks `/api/health/strict`, and the same path should be mirrored in readiness/liveness probes.

## Production notes

The README mentions a production layout: **digiRunner** (OIDC + API Key gateway) in front, **Dify** for RAG orchestration. Neither is wired in this repo — they are reference integrations for a downstream deployment.

Default credentials are still environment-backed (`AUTH_USERNAME`, `AUTH_PASSWORD`) and intended only for POC use. Replace them with a real user store or external identity provider before any non-demo deployment.

The JWT secret defaults to `change-me-in-production-v3` — override `JWT_SECRET` in `.env` or the Kubernetes Secret.

## CI

The repo includes a small GitHub Actions workflow that:
- installs a lightweight test dependency set
- runs `python -m unittest discover -s tests -v`

This is meant as a regression gate for helper logic, auth checks, and retrieval plumbing, not as a full end-to-end evaluation.
