"""Generate demo PDFs for OCR showcase from sample XMLs.

Produces, for one chosen patent:
  - <doc>_digital.pdf : born-digital (text layer, no OCR triggered)
  - <doc>_scan.pdf    : rasterized image-only (forces OCR fallback)
"""
import sys
from pathlib import Path

import fitz  # pymupdf
from lxml import etree

REPO = Path(__file__).resolve().parent.parent
XML_DIR = REPO / "data" / "patents"


def parse_min(xml_path: Path) -> dict:
    t = etree.parse(str(xml_path)).getroot()
    def x(p):
        e = t.find(p)
        return ("".join(e.itertext()).strip() if e is not None else "")
    return {
        "doc_number": x(".//doc-number") or xml_path.stem,
        "title_zh": x(".//chinese-title"),
        "title_en": x(".//english-title"),
        "abstract": x(".//abstract"),
        "claims": x(".//claims"),
        "applicant": x(".//applicant//orgname") or x(".//applicant//last-name"),
        "ipc": x(".//main-classification"),
        "date": x(".//date"),
    }


EN_ABSTRACT = (
    "The present invention relates to a patent document question answering system "
    "based on vector retrieval and reranking. The system comprises an optical character "
    "recognition (OCR) module for extracting text from patent PDFs, a chunking module "
    "that segments text by claim numbers and section boundaries, a vector database "
    "storing chunk embeddings, a reranking module based on a cross encoder, and a "
    "large language model generation module. By combining hybrid retrieval (vector "
    "similarity plus keyword filtering) and reranking, the system delivers accurate "
    "and citable patent question answering with grounded source attribution."
)
EN_CLAIMS = (
    "1. A patent document question answering system characterized by comprising: "
    "an OCR module configured to extract text from a patent PDF; a chunking module "
    "configured to divide the extracted text into document fragments according to "
    "claim numbers or section boundaries; a vector database storing embeddings of "
    "each fragment; a hybrid retrieval module configured to fetch candidate fragments "
    "by combining vector similarity and metadata filtering; a reranking module based "
    "on a cross encoder for refining the ranking of retrieved fragments; and a large "
    "language model module configured to generate answers grounded in the top ranked "
    "fragments together with explicit source citations.\n"
    "2. The system of claim 1 wherein the OCR module supports a user selectable engine "
    "between PaddleOCR and Tesseract OCR with automatic born-digital detection.\n"
    "3. The system of claim 1 wherein the chunking module produces one chunk per "
    "numbered claim and one chunk per abstract block to preserve citation granularity.\n"
    "4. The system of claim 1 wherein the reranking module uses bge-reranker-v2-m3 "
    "to score query document pairs and reorder the top K candidates.\n"
    "5. The system of claim 1 wherein the large language model module emits answers "
    "in a streaming fashion and includes a confidence level chosen from HIGH MEDIUM LOW."
)


def make_digital_pdf(p: dict, out: Path):
    doc = fitz.open()
    # English-only content so the rasterized SCAN PDF can be OCR'd reliably
    # (built-in helv font can't render CJK glyphs).
    title = p["title_en"] or p["doc_number"]
    body_blocks = [
        ("Patent No.", p["doc_number"]),
        ("IPC", p["ipc"]),
        ("Applicant", "Hsinli Information Co., Ltd."),
        ("Publication Date", p["date"]),
        ("Title", p["title_en"]),
        ("Abstract", EN_ABSTRACT),
        ("Claims", EN_CLAIMS),
    ]

    # Page 1: cover
    page = doc.new_page()
    y = 60
    page.insert_text((50, y), title[:80], fontname="helv", fontsize=14)
    y += 40
    for label, value in body_blocks[:4]:
        page.insert_text((50, y), f"{label}: {value}", fontname="helv", fontsize=10)
        y += 18

    # Page 2+: abstract & claims (long fields wrap manually)
    def wrap(text, width=95):
        out = []
        for line in text.splitlines():
            while len(line) > width:
                out.append(line[:width])
                line = line[width:]
            out.append(line)
        return out

    for label, value in body_blocks[4:]:
        if not value:
            continue
        page = doc.new_page()
        page.insert_text((50, 50), label, fontname="helv", fontsize=12)
        y = 80
        for ln in wrap(value):
            if y > 780:
                page = doc.new_page()
                y = 50
            page.insert_text((50, y), ln, fontname="helv", fontsize=9)
            y += 12

    doc.save(out)
    doc.close()
    print(f"  digital → {out.name} ({out.stat().st_size//1024} KB)")


def rasterize_to_scan(src: Path, out: Path, dpi: int = 150):
    """Convert a born-digital PDF to image-only by re-rendering each page."""
    src_doc = fitz.open(src)
    new_doc = fitz.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi)
        new_page = new_doc.new_page(width=pix.width * 72 / dpi, height=pix.height * 72 / dpi)
        # Slight noise simulation via lower DPI; here we just embed the rasterized image.
        new_page.insert_image(new_page.rect, stream=pix.tobytes("png"))
    new_doc.save(out)
    new_doc.close()
    src_doc.close()
    print(f"  scan    → {out.name} ({out.stat().st_size//1024} KB)")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "TW202401234A.xml"
    src = XML_DIR / target
    if not src.exists():
        print(f"XML not found: {src}")
        sys.exit(1)
    p = parse_min(src)
    digital = XML_DIR / f"{src.stem}_digital.pdf"
    scan = XML_DIR / f"{src.stem}_scan.pdf"
    make_digital_pdf(p, digital)
    rasterize_to_scan(digital, scan)
    print("\nReady for demo:")
    print(f"  - {digital}  (will be detected as born-digital, no OCR)")
    print(f"  - {scan}     (image-only, forces OCR engine)")


if __name__ == "__main__":
    main()
