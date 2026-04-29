"""OCR Service v3 — User-selectable engine + born-digital detection + comparison"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

import fitz

_paddle_ocr = None

def _get_paddle():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(use_angle_cls=True, lang="chinese_cht", show_log=False, use_gpu=False)
        except ImportError:
            _paddle_ocr = "unavailable"
    return _paddle_ocr if _paddle_ocr != "unavailable" else None


def ocr_pdf(pdf_path: str, engine: str = "auto") -> dict:
    pdf_path = Path(pdf_path)
    result = _extract_pymupdf(str(pdf_path))
    avg_chars = sum(p["char_count"] for p in result["pages"]) / max(len(result["pages"]), 1)

    if avg_chars >= 80:
        result["ocr_applied"] = False
        result["ocr_engine"] = "none (born-digital)"
    elif engine in ("auto", "paddle") and _get_paddle():
        result = _ocr_paddle(str(pdf_path))
        result["ocr_applied"] = True
        result["ocr_engine"] = "paddleocr"
    elif engine in ("auto", "tesseract"):
        tmp = _ocr_tesseract(str(pdf_path))
        if tmp:
            result = _extract_pymupdf(tmp)
            result["ocr_applied"] = True
            result["ocr_engine"] = "tesseract"
            try: os.unlink(tmp)
            except: pass
        else:
            result["ocr_applied"] = False
            result["ocr_engine"] = "failed"
    else:
        result["ocr_applied"] = False
        result["ocr_engine"] = "skipped"

    result["filename"] = pdf_path.name
    result["file_size_kb"] = round(pdf_path.stat().st_size / 1024, 1)
    return result


def _extract_pymupdf(pdf_path: str) -> dict:
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        pages.append({"page_no": i + 1, "text": text, "char_count": len(text)})
    doc.close()
    full = "\n\n".join(f"[Page {p['page_no']}]\n{p['text']}" for p in pages if p["text"])
    return {"pages": pages, "full_text": full, "total_pages": len(pages)}


def _ocr_paddle(pdf_path: str) -> dict:
    ocr = _get_paddle()
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(pix.tobytes("png")); tmp_path = tmp.name
        try:
            result = ocr.ocr(tmp_path, cls=True)
            lines = []
            if result and result[0]:
                for box in sorted(result[0], key=lambda x: (x[0][0][1], x[0][0][0])):
                    if box[1][1] > 0.5: lines.append(box[1][0])
            text = "\n".join(lines)
        except: text = ""
        finally: os.unlink(tmp_path)
        pages.append({"page_no": i + 1, "text": text, "char_count": len(text)})
    doc.close()
    full = "\n\n".join(f"[Page {p['page_no']}]\n{p['text']}" for p in pages if p["text"])
    return {"pages": pages, "full_text": full, "total_pages": len(pages)}


def _ocr_tesseract(pdf_path: str) -> str | None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(["ocrmypdf", "--language", os.getenv("OCR_LANGUAGE", "chi_tra+eng"),
                        "--skip-text", "--output-type", "pdf", str(pdf_path), tmp_path],
                       capture_output=True, timeout=180, check=True)
        return tmp_path
    except:
        if os.path.exists(tmp_path): os.unlink(tmp_path)
        return None


def chunk_patent(ocr_result: dict, max_chars: int = None) -> list[dict]:
    max_chars = max_chars or int(os.getenv("CHUNK_MAX_CHARS", "800"))
    chunks = []
    cid = 0
    for page in ocr_result["pages"]:
        text = page["text"]
        if not text or len(text) < 30: continue
        # Try claim-number splitting
        parts = re.split(r'(?:^|\n)\s*(\d+)\s*[.、．]\s*', text)
        if len(parts) > 3:
            cur, num = "", 0
            for p in parts:
                p = p.strip()
                if not p: continue
                if p.isdigit():
                    if cur:
                        chunks.append(_mk(cur, ocr_result, page, cid, f"Claim {num}"))
                        cid += 1
                    num = int(p); cur = f"{num}. "
                else: cur += p
            if cur.strip():
                chunks.append(_mk(cur, ocr_result, page, cid, f"Claim {num}"))
                cid += 1
        else:
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            cur = ""
            for para in paras:
                if len(cur) + len(para) > max_chars and cur:
                    chunks.append(_mk(cur, ocr_result, page, cid))
                    cid += 1; cur = para
                else: cur = f"{cur}\n\n{para}" if cur else para
            if cur.strip():
                chunks.append(_mk(cur, ocr_result, page, cid))
                cid += 1
    return chunks


def _mk(text, ocr_result, page, cid, section=""):
    fn = ocr_result.get("filename", "unknown")
    return {"text": text.strip(), "metadata": {
        "filename": fn, "page": page["page_no"], "chunk_id": cid, "section": section,
        "source": f"{fn} Page {page['page_no']}" + (f" {section}" if section else ""),
        "ocr_engine": ocr_result.get("ocr_engine", ""),
    }}
