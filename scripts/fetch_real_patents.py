"""Pull real Taiwan patents from TIPO open data and split into 1案1XML files.

Source: https://cloud.tipo.gov.tw/S220/opdata/api/gazettes/P13
  - One issue's gazette = single XML, ~20 MB, ~1900 patents
  - Schema: <tw-patent-grants><tw-patent-grant>... where claims are
    <claim num="N"><p>text</p></claim> (no inline numbering)

What this script does:
  1. Download the issue gazette if not cached
  2. For each <tw-patent-grant>, transform into a flat 1-case XML matching
     the XPaths xml_parser.py expects (doc-number, chinese-title, claims, ...)
  3. Render <claims> as numbered plaintext "1. ...\n2. ..." so the
     existing chunk_patent_xml regex can split on claim boundaries
  4. Pick a diverse sample of N patents (covering different IPC sections)
"""
from __future__ import annotations
import os, sys
from pathlib import Path
from collections import defaultdict
import requests
from lxml import etree

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "patents_real"
OUT_DIR = REPO / "data" / "patents_real_split"
GAZETTE_URL = "https://cloud.tipo.gov.tw/S220/opdata/api/gazettes/P13"
GAZETTE_FILE = RAW_DIR / "P13_vol53_iss9.xml"

# Default: 20 patents, balanced across IPC sections
DEFAULT_N = 20


def download_gazette() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if GAZETTE_FILE.exists() and GAZETTE_FILE.stat().st_size > 1_000_000:
        print(f"[cache] {GAZETTE_FILE.name} ({GAZETTE_FILE.stat().st_size//(1024*1024)} MB)")
        return GAZETTE_FILE
    print(f"[download] {GAZETTE_URL}")
    r = requests.get(GAZETTE_URL, timeout=180, stream=True)
    r.raise_for_status()
    with open(GAZETTE_FILE, "wb") as f:
        for chunk in r.iter_content(1024 * 256):
            f.write(chunk)
    print(f"[saved] {GAZETTE_FILE.stat().st_size//(1024*1024)} MB")
    return GAZETTE_FILE


def first_text(parent, tag_local: str) -> str:
    """Find first descendant whose tag ends with tag_local; return stripped text."""
    for el in parent.iter():
        if el.tag.endswith(tag_local):
            t = (el.text or "").strip()
            if t:
                return t
    return ""


def collect_text(parent, tag_local: str) -> str:
    """Concatenate text from descendants matching tag_local."""
    out = []
    for el in parent.iter():
        if el.tag.endswith(tag_local):
            t = "".join(el.itertext()).strip()
            if t:
                out.append(t)
    return "\n".join(out)


def render_claims_as_numbered_text(grant) -> str:
    """Serialize <claims><claim num='N'><p>...</p></claim>...</claims>
    as: "1. ...\n2. ...\n" so the regex split in chunk_patent_xml works."""
    claims = grant.find("claims")
    if claims is None:
        return ""
    parts = []
    for c in claims.findall("claim"):
        num = c.get("num") or ""
        body = "".join(c.itertext()).strip()
        if num and body:
            parts.append(f"{num}. {body}")
    return "\n\n".join(parts)


def transform_grant(grant) -> dict:
    """Pull bibliographic + claims fields from a <tw-patent-grant> element."""
    bib = grant.find("tw-bibliographic-data-grant")
    if bib is None:
        return {}

    doc_number = first_text(bib.find("publication-reference") or bib, "doc-number") or grant.get("certificate-number", "")
    title_zh = first_text(bib, "chinese-title")
    title_en = first_text(bib, "english-title")
    ipc_main = first_text(bib, "main-classification")
    ipc_further = ""
    for el in bib.iter():
        if el.tag.endswith("further-classification") and el.text:
            ipc_further += el.text.strip() + " "
    ipc_further = ipc_further.strip()

    # Applicant: prefer <chinese-name><last-name>; fallback to english-name
    applicant_zh, applicant_en = "", ""
    for app in bib.iter():
        if app.tag.endswith("applicant"):
            for ab in app.iter():
                if ab.tag.endswith("chinese-name"):
                    nm = first_text(ab, "last-name")
                    if nm:
                        applicant_zh = nm
                        break
                if ab.tag.endswith("english-name") and not applicant_en:
                    nm = first_text(ab, "last-name")
                    if nm:
                        applicant_en = nm
            if applicant_zh:
                break

    inventor = ""
    for inv in bib.iter():
        if inv.tag.endswith("inventor"):
            for ab in inv.iter():
                if ab.tag.endswith("chinese-name"):
                    inventor = first_text(ab, "last-name")
                    if inventor:
                        break
            if inventor:
                break

    pub_date = ""
    for el in bib.iter():
        if el.tag.endswith("date") and el.text:
            t = el.text.strip()
            if len(t) >= 6 and t.isdigit():
                pub_date = t
                break

    claims_text = render_claims_as_numbered_text(grant)

    return {
        "doc_number": doc_number,
        "title_zh": title_zh,
        "title_en": title_en,
        "abstract": "",  # not available in gazette format
        "claims": claims_text,
        "description": "",  # not in gazette
        "ipc_main": ipc_main,
        "ipc_further": ipc_further,
        "applicant": applicant_zh or applicant_en,
        "inventor": inventor,
        "pub_date": pub_date,
        "country": "TW",
    }


def write_individual_xml(rec: dict, out_path: Path):
    """Build a flat 1-case XML matching the 1案1XML schema xml_parser.py expects."""
    root = etree.Element("patent-document", attrib={"country": "TW", "doc-number": rec["doc_number"], "kind": "B"})
    # Bibliographic
    bib = etree.SubElement(root, "bibliographic-data")
    pub = etree.SubElement(bib, "publication-reference")
    docid = etree.SubElement(pub, "document-id")
    etree.SubElement(docid, "country").text = rec["country"]
    etree.SubElement(docid, "doc-number").text = rec["doc_number"]
    etree.SubElement(docid, "date").text = rec["pub_date"]
    cls = etree.SubElement(bib, "classification-ipc")
    etree.SubElement(cls, "main-classification").text = rec["ipc_main"]
    if rec["ipc_further"]:
        etree.SubElement(cls, "further-classification").text = rec["ipc_further"]
    etree.SubElement(bib, "chinese-title").text = rec["title_zh"]
    etree.SubElement(bib, "english-title").text = rec["title_en"]
    if rec["applicant"]:
        app = etree.SubElement(bib, "applicant")
        etree.SubElement(app, "orgname").text = rec["applicant"]
        etree.SubElement(app, "last-name").text = rec["applicant"]
    if rec["inventor"]:
        inv = etree.SubElement(bib, "inventor")
        etree.SubElement(inv, "last-name").text = rec["inventor"]
    # Body
    if rec["claims"]:
        etree.SubElement(root, "claims").text = rec["claims"]
    if rec["abstract"]:
        etree.SubElement(root, "abstract").text = rec["abstract"]
    if rec["description"]:
        etree.SubElement(root, "description").text = rec["description"]

    out_path.write_bytes(etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8"))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    gz = download_gazette()
    tree = etree.parse(str(gz))
    grants = tree.getroot().findall("tw-patent-grant")
    print(f"[parse] total grants in issue: {len(grants)}")

    # Bucket by IPC main-section letter (A, B, C, F, G, H, ...) for diversity
    by_section = defaultdict(list)
    for g in grants:
        rec = transform_grant(g)
        if not rec or not rec["doc_number"] or not rec["title_zh"] or not rec["claims"]:
            continue
        sec = (rec["ipc_main"] or "")[:1].upper() or "X"
        by_section[sec].append(rec)

    print(f"[buckets] " + ", ".join(f"{k}={len(v)}" for k, v in sorted(by_section.items())))

    # Round-robin pick from each section until we hit n
    picked = []
    queues = {k: list(v) for k, v in by_section.items() if v}
    while queues and len(picked) < n:
        for k in list(sorted(queues.keys())):
            if not queues[k]:
                queues.pop(k); continue
            picked.append(queues[k].pop(0))
            if len(picked) >= n:
                break

    print(f"[select] {len(picked)} patents:")
    for rec in picked:
        out = OUT_DIR / f"{rec['doc_number']}.xml"
        write_individual_xml(rec, out)
        print(f"  {rec['doc_number']:>10} | IPC={rec['ipc_main']:<10} | claims={len(rec['claims'])//1000}k chars | {rec['title_zh'][:40]}")

    print(f"\n[done] wrote {len(picked)} files to {OUT_DIR}")
    print(f"\nNext: curl -X POST 'http://localhost:8000/api/ingest/scan?dir_path={OUT_DIR.as_posix()}&tag=real'")


if __name__ == "__main__":
    main()
