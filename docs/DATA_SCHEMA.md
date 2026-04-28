# Data schema

## Taiwan patent XML (expected by `xml_parser.py`)

`xml_parser.parse_patent_xml()` uses `lxml`'s `findall`/`find` with `.//` (descendant) XPath, so the exact tree shape is flexible as long as these nodes exist somewhere under the root:

| Field | Primary XPath | Fallback XPath |
|---|---|---|
| `doc_number` | `.//doc-number` | `.//publication-reference//doc-number` |
| `title_zh` | `.//chinese-title` | `.//invention-title[@lang='zh']` |
| `title_en` | `.//english-title` | `.//invention-title[@lang='en']` |
| `abstract` | `.//abstract` (all descendant text) | `.//tw-abstract` |
| `claims` | `.//claims` | `.//tw-claims` |
| `description` | `.//description` (truncated to 5000 chars) | `.//tw-description` |
| `ipc_main` | `.//main-classification` | `.//classification-ipc//main-classification` |
| `ipc_further` | `.//further-classification` | — |
| `applicant` | `.//applicant//last-name` | `.//applicant//orgname` |
| `inventor` | `.//inventor//last-name` | — |
| `pub_date` | `.//date` | `.//publication-reference//date` |
| `country` | `.//country` | defaults to `TW` |

A document is considered valid if either `doc_number` or `title_zh` is non-empty.

## Chunk layout

After `chunk_patent_xml()`:

- **`abstract`** — one chunk, prefixed `[Patent {doc_number}] Abstract:`
- **`claim_N`** — one chunk per numbered claim (split on `^\s*\d+\s*[.、．]\s*`); falls back to a single `claims` chunk if no numbering is detected
- **`description_N`** — paragraphs packed up to `CHUNK_MAX_CHARS` (default 800)
- **`bibliographic`** — always-on chunk containing title/IPC/applicant/inventor/date/country

Every chunk carries this metadata in Qdrant payload:

```python
{
  "filename": "...",
  "doc_number": "...",
  "title": "...",
  "ipc": "...",
  "applicant": "...",
  "source_type": "xml",
  "section": "abstract" | "claim_1" | "description_0" | "bibliographic",
  "source": "{doc_number} {Section}",
  "page": 0,
  "chunk_id": int,
  "tag": "..."  # if provided at upload time
}
```

## Sample files

Three synthetic TW patents ship under `data/patents/`:

| File | Topic | Claims | IPC |
|---|---|---|---|
| `TW202401234A.xml` | Patent RAG system | 8 | G06F 16/31 |
| `TW202405678B.xml` | OCR preprocessing for zh-TW scans | 6 | G06V 30/413 |
| `TW202409012A.xml` | Multi-turn QA with streaming | 7 | G06F 40/30 |

Load them end-to-end with:

```bash
curl -X POST "http://localhost:8000/api/ingest/scan?dir_path=./data/patents&tag=demo"
```

Expected result: `{"patents_found": 3, "total_chunks": 30}` (actual chunk count varies slightly depending on `CHUNK_MAX_CHARS`).

## PDF ingest

PDFs go through a different path — `ocr_service.chunk_patent()` — and carry different metadata:

```python
{
  "filename": "...pdf",
  "page": int,
  "chunk_id": int,
  "section": "" | "Claim N",
  "source": "{filename} Page {n} [Claim N]",
  "ocr_engine": "none (born-digital)" | "paddleocr" | "tesseract"
}
```

PDF chunks don't have `doc_number` / `title` / `ipc` / `applicant`, so `tag_filter` and `filename_filter` are the practical way to scope them. Prefer XML ingest when possible.
