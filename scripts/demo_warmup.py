"""Pre-demo warm-up — run 60 seconds before the demo starts.

Sequence:
  1. Health check Qdrant + Ollama + API (fail fast if a service is down)
  2. Confirm sample patents indexed; reseed if 0
  3. Send 1 dummy chat to warm: embedder cache, reranker, Ollama 7B model VRAM, KV cache
  4. Print a pre-flight checklist for the presenter

Run:  .venv/Scripts/python.exe scripts/demo_warmup.py
"""
from __future__ import annotations
import sys, time, json, os, requests
from urllib.parse import urlencode

API = os.environ.get("API_URL", "http://127.0.0.1:8000")
QDRANT = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def step(name):
    print(f"\n[{name}]", flush=True)


def must(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        print(f"\nAborted at: {msg}\n")
        sys.exit(1)


def main():
    t_all = time.time()

    step("1. Service health")
    try:
        q = requests.get(f"{QDRANT}/", timeout=3).json()
        must(q.get("status") == "ok" or "title" in q, f"Qdrant: {q.get('version','?')}")
    except Exception as e:
        must(False, f"Qdrant unreachable: {e}")

    try:
        o = requests.get(f"{OLLAMA}/api/tags", timeout=3).json()
        names = [m["name"] for m in o.get("models", [])]
        must(any(n.startswith("qwen2.5") for n in names), f"Ollama models: {len(names)} pulled")
    except Exception as e:
        must(False, f"Ollama unreachable: {e}")

    try:
        s = requests.get(f"{API}/api/stats", timeout=5).json()
        must(s.get("rerank_enabled"), f"API reachable, rerank_enabled={s.get('rerank_enabled')}, llm={s.get('llm_model')}")
        n_chunks = s.get("total_chunks", 0)
    except Exception as e:
        must(False, f"API unreachable: {e}")
        return

    step("2. Index state")
    print(f"  total_chunks: {n_chunks}", flush=True)
    if n_chunks < 30:
        print("  Reseeding 3 sample XMLs...", flush=True)
        r = requests.post(f"{API}/api/ingest/scan", params={"dir_path": "D:/patent-rag-v3/data/patents", "tag": "demo"})
        print(f"  result: {r.json()}", flush=True)
    pp = requests.get(f"{API}/api/patents").json()
    print(f"  indexed patents: {pp['total']}")
    for p in pp["patents"]:
        print(f"   - {p['doc_number']} | {p['title'][:40]}")

    step("3. Warm-up chat (forces Ollama to keep 7B in VRAM)")
    t0 = time.time()
    body = {"query": "List the key claims of TW202401234A", "top_k": 3, "stream": True, "doc_number_filter": "TW202401234A"}
    r = requests.post(f"{API}/api/chat", json=body, stream=True, timeout=180)
    first = None; tokens = 0
    for line in r.iter_lines():
        if not line: continue
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "token":
            if first is None:
                first = time.time() - t0
                print(f"  TTFT = {first:.1f}s", flush=True)
            tokens += 1
        elif d.get("type") == "done":
            total = time.time() - t0
            gen = total - (first or total)
            print(f"  total = {total:.1f}s | gen = {gen:.1f}s | {tokens} tokens", flush=True)
            break

    step("4. Demo pre-flight")
    print("""  [ ] Browser: open http://localhost:8000/ — auto-login should land you in the Chat page
  [ ] Sidebar shows >= 5 files (3 XML + 2 demo PDFs)
  [ ] Patents table shows 3 rows with Chinese titles (clean, no mojibake)
  [ ] First quick question button: TW202401234A claims — answer streams in
  [ ] Compare tab: pick A=TW202401234A B=TW202405678B → 3-row table
  [ ] Drag the SCAN PDF onto the upload zone → ocr_engine: paddleocr line appears""")

    print(f"\nWarm-up complete in {time.time()-t_all:.1f}s. You're ready.")


if __name__ == "__main__":
    main()
