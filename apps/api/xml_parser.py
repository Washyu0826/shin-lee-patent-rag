"""Taiwan patent XML parser — extracts structured fields from data.gov.tw 1案1XML"""
import os
import re
from pathlib import Path
from typing import Optional
from lxml import etree


def parse_patent_xml(xml_path: str) -> dict | None:
    """Parse a single patent XML file, return structured data."""
    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"[XML] Parse error {xml_path}: {e}")
        return None

    def txt(xpath: str) -> str:
        el = root.find(xpath)
        return (el.text or "").strip() if el is not None else ""

    def txt_all(xpath: str) -> str:
        """Get all text content under an element (including children)"""
        el = root.find(xpath)
        if el is None:
            return ""
        return "".join(el.itertext()).strip()

    # Extract fields (adapt XPath to actual schema)
    doc_number = txt(".//doc-number") or txt(".//publication-reference//doc-number")
    title_zh = txt(".//chinese-title") or txt(".//invention-title[@lang='zh']")
    title_en = txt(".//english-title") or txt(".//invention-title[@lang='en']")
    abstract_text = txt_all(".//abstract") or txt_all(".//tw-abstract")
    claims_text = txt_all(".//claims") or txt_all(".//tw-claims")
    description_text = txt_all(".//description") or txt_all(".//tw-description")
    ipc_main = txt(".//main-classification") or txt(".//classification-ipc//main-classification")
    ipc_further = txt(".//further-classification")
    applicant = txt(".//applicant//last-name") or txt(".//applicant//orgname")
    inventor = txt(".//inventor//last-name")
    pub_date = txt(".//date") or txt(".//publication-reference//date")
    country = txt(".//country")

    if not doc_number and not title_zh:
        return None

    return {
        "doc_number": doc_number,
        "title_zh": title_zh,
        "title_en": title_en,
        "abstract": abstract_text,
        "claims": claims_text,
        "description": description_text[:5000],  # Limit for chunking
        "ipc_main": ipc_main,
        "ipc_further": ipc_further,
        "applicant": applicant,
        "inventor": inventor,
        "pub_date": pub_date,
        "country": country or "TW",
        "source_file": Path(xml_path).name,
    }


def chunk_patent_xml(patent: dict) -> list[dict]:
    """
    XML 結構化切塊：claims 和 abstract 分開成獨立 chunk。
    每個 chunk 帶完整 metadata。
    """
    chunks = []
    base_meta = {
        "filename": patent["source_file"],
        "doc_number": patent["doc_number"],
        "title": patent["title_zh"] or patent["title_en"],
        "ipc": patent["ipc_main"],
        "applicant": patent["applicant"],
        "source_type": "xml",
    }

    # Abstract chunk
    if patent["abstract"] and len(patent["abstract"]) > 20:
        chunks.append({
            "text": f"[Patent {patent['doc_number']}] Abstract:\n{patent['abstract']}",
            "metadata": {
                **base_meta,
                "section": "abstract",
                "source": f"{patent['doc_number']} Abstract",
                "page": 0,
            },
        })

    # Claims chunks — split by claim number
    if patent["claims"]:
        claim_parts = re.split(r'(?:^|\n)\s*(\d+)\s*[.、．]\s*', patent["claims"])
        current_claim = ""
        claim_num = 0

        for part in claim_parts:
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                if current_claim:
                    chunks.append({
                        "text": f"[Patent {patent['doc_number']}] Claim {claim_num}:\n{current_claim}",
                        "metadata": {
                            **base_meta,
                            "section": f"claim_{claim_num}",
                            "source": f"{patent['doc_number']} Claim {claim_num}",
                            "page": 0,
                        },
                    })
                claim_num = int(part)
                current_claim = ""
            else:
                current_claim += part

        if current_claim:
            chunks.append({
                "text": f"[Patent {patent['doc_number']}] Claim {claim_num}:\n{current_claim}",
                "metadata": {
                    **base_meta,
                    "section": f"claim_{claim_num}",
                    "source": f"{patent['doc_number']} Claim {claim_num}",
                    "page": 0,
                },
            })

        # If no numbered claims found, treat whole claims as one chunk
        if not any("claim_" in c["metadata"]["section"] for c in chunks):
            chunks.append({
                "text": f"[Patent {patent['doc_number']}] Claims:\n{patent['claims'][:1500]}",
                "metadata": {
                    **base_meta,
                    "section": "claims",
                    "source": f"{patent['doc_number']} Claims",
                    "page": 0,
                },
            })

    # Description chunks — split by paragraph
    if patent["description"]:
        desc = patent["description"]
        max_chars = int(os.getenv("CHUNK_MAX_CHARS", "800"))
        paragraphs = [p.strip() for p in desc.split("\n\n") if p.strip()]
        current = ""
        desc_idx = 0

        for para in paragraphs:
            if len(current) + len(para) > max_chars and current:
                chunks.append({
                    "text": f"[Patent {patent['doc_number']}] Description:\n{current}",
                    "metadata": {
                        **base_meta,
                        "section": f"description_{desc_idx}",
                        "source": f"{patent['doc_number']} Description",
                        "page": 0,
                    },
                })
                desc_idx += 1
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current.strip():
            chunks.append({
                "text": f"[Patent {patent['doc_number']}] Description:\n{current}",
                "metadata": {
                    **base_meta,
                    "section": f"description_{desc_idx}",
                    "source": f"{patent['doc_number']} Description",
                    "page": 0,
                },
            })

    # Bibliographic chunk (always include)
    bib = f"""[Patent {patent['doc_number']}] Bibliographic Data:
Title (ZH): {patent['title_zh']}
Title (EN): {patent['title_en']}
IPC: {patent['ipc_main']} {patent['ipc_further']}
Applicant: {patent['applicant']}
Inventor: {patent['inventor']}
Date: {patent['pub_date']}
Country: {patent['country']}"""

    chunks.append({
        "text": bib,
        "metadata": {
            **base_meta,
            "section": "bibliographic",
            "source": f"{patent['doc_number']} Bibliographic",
            "page": 0,
        },
    })

    # Assign chunk_ids
    for i, c in enumerate(chunks):
        c["metadata"]["chunk_id"] = i

    return chunks


def scan_xml_directory(dir_path: str) -> list[dict]:
    """Scan a directory for patent XML files, parse all."""
    results = []
    xml_dir = Path(dir_path)
    if not xml_dir.exists():
        return results

    for f in sorted(xml_dir.glob("*.xml")):
        patent = parse_patent_xml(str(f))
        if patent:
            results.append(patent)

    print(f"[XML] Parsed {len(results)} patents from {dir_path}")
    return results
