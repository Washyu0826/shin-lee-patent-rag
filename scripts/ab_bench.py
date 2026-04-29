"""Tiny A/B/C benchmark: baseline vs bge-m3 vs bge-m3+HyDE."""
import time

import requests

QUERIES = [
    ("Direct fact", "List the IPC classifications of all uploaded patents"),
    ("Indirect semantic", "Which technologies can be used for energy saving or energy recovery?"),
    ("Cross-doc",  "Which patents involve antibody or antigen-binding molecules?"),
    ("Specific term", "Find patents about polarizing film or polarizer"),
]

print(f"{'Q':<22} {'engine':<14} {'wall':<8} {'top_rerank':<12} top_3_docs")
print("-" * 110)
for label, q in QUERIES:
    for engine, hyde in [("baseline", False), ("m3", False), ("m3", True)]:
        t0 = time.time()
        body = {"query": q, "top_k": 5, "engine": engine, "use_hyde": hyde, "tag_filter": "real"}
        try:
            r = requests.post("http://127.0.0.1:8000/api/chat", json=body, timeout=240)
            j = r.json()
            srcs = j.get("sources", [])
            top_score = srcs[0].get("rerank_score") if srcs else None
            doc_set = sorted({s.get("doc_number") or s.get("source","").split()[0] for s in srcs[:3]})
        except Exception as e:
            top_score = f"err:{e}"; doc_set = []
        eng_label = engine + ("+HyDE" if hyde else "")
        print(f"{label:<22} {eng_label:<14} {time.time()-t0:5.1f}s  {str(top_score):<12} {doc_set}")
    print()
