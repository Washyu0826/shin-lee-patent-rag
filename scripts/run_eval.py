#!/usr/bin/env python3
"""Eval: run test set -> metrics -> HTML report"""
import argparse,json,time
from pathlib import Path
import requests,pandas as pd
API="http://localhost:8000"
def run(evalset,output):
    qs=[json.loads(l) for l in open(evalset) if l.strip()]
    print(f"Running {len(qs)} questions...")
    results=[]
    for i,q in enumerate(qs):
        t0=time.time()
        try:
            r=requests.post(f"{API}/api/chat",json={"query":q["question"],"top_k":5},timeout=120).json()
            ans=r.get("answer","")
        except Exception as e: ans=f"ERROR: {e}"
        lat=round((time.time()-t0)*1000,1)
        cite="[Source" in ans
        kw=all(k in ans for k in q.get("expected_keywords",[])) if "expected_keywords" in q else True
        results.append({"question":q["question"],"category":q.get("category",""),"latency_ms":lat,"has_citation":cite,"keyword_match":kw,"passed":cite and kw})
        print(f"  [{i+1}/{len(qs)}] {'✅' if results[-1]['passed'] else '❌'} {lat:.0f}ms")
    df=pd.DataFrame(results);t,p=len(df),df['passed'].sum()
    html=f"""<!DOCTYPE html><html><head><meta charset=UTF-8><title>Eval</title><style>body{{font-family:sans-serif;max-width:900px;margin:0 auto;padding:20px}}.g{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:16px 0}}.c{{background:#f1f5f9;padding:12px;border-radius:8px;text-align:center}}.c .v{{font-size:24px;font-weight:700}}.c .l{{font-size:10px;color:#666}}table{{width:100%;border-collapse:collapse;font-size:12px}}th{{background:#1e293b;color:#fff;padding:6px}}td{{padding:4px 6px;border-bottom:1px solid #eee}}</style></head><body><h1>Eval Report</h1><p>{time.strftime('%Y-%m-%d %H:%M')}</p><div class=g><div class=c><div class=v>{p}/{t}</div><div class=l>Pass</div></div><div class=c><div class=v>{p/max(t,1)*100:.0f}%</div><div class=l>Rate</div></div><div class=c><div class=v>{df['has_citation'].mean()*100:.0f}%</div><div class=l>Citation</div></div><div class=c><div class=v>{df['latency_ms'].mean()/1000:.1f}s</div><div class=l>Latency</div></div></div><table><tr><th>#</th><th>Cat</th><th>Question</th><th>Pass</th><th>Cite</th><th>ms</th></tr>"""
    for i,r in enumerate(results):html+=f"<tr><td>{i+1}</td><td>{r['category']}</td><td>{r['question'][:60]}</td><td>{'✅' if r['passed'] else '❌'}</td><td>{'✅' if r['has_citation'] else '❌'}</td><td>{r['latency_ms']:.0f}</td></tr>"
    html+="</table></body></html>";Path(output).write_text(html, encoding="utf-8");print(f"\n[REPORT] {output} | {p/max(t,1)*100:.0f}%")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--evalset",default="data/eval/sample_questions.jsonl");p.add_argument("--output",default="data/eval/report.html");a=p.parse_args();run(a.evalset,a.output)
