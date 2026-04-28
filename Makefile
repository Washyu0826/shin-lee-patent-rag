.PHONY: up down pull install dev eval stats reset help

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up:  ## Start Qdrant + Ollama + PostgreSQL
	docker compose up -d

down:  ## Stop all
	docker compose down

pull:  ## Download LLM model
	docker exec -it $$(docker ps -qf "ancestor=ollama/ollama") ollama pull qwen2.5:3b-instruct

install:  ## Install Python deps
	pip install -r apps/api/requirements.txt

dev:  ## Start API dev server
	cd apps/api && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

eval:  ## Run evaluation
	python scripts/run_eval.py

stats:  ## Show stats
	@curl -s http://localhost:8000/api/stats | python3 -m json.tool

reset:  ## Reset vector DB
	@curl -X DELETE http://localhost:8000/api/reset

start: up  ## Full start
	@sleep 8
	@echo "=== Patent RAG v3 ==="
	@echo "make dev → http://localhost:8000"
