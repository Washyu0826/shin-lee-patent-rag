import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import rag_service


class FakeQdrant:
    def __init__(self, points=None, search_results=None):
        self.points = list(points or [])
        self.search_results = list(search_results or [])

    def scroll(self, *, limit, offset=None, **kwargs):
        start = offset or 0
        batch = self.points[start:start + limit]
        next_offset = start + len(batch)
        if next_offset >= len(self.points):
            next_offset = None
        return batch, next_offset

    def search(self, **kwargs):
        return list(self.search_results)


class FakeVector(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    def encode(self, *args, **kwargs):
        return FakeVector([0.1, 0.2, 0.3])


class RagServiceTests(unittest.TestCase):
    def test_scroll_points_paginates_until_limit(self):
        fake = FakeQdrant([1, 2, 3, 4, 5])
        with patch.object(rag_service, "get_qdrant", return_value=fake):
            points = rag_service.scroll_points(limit=4, batch_size=2)
        self.assertEqual(points, [1, 2, 3, 4])

    def test_get_patent_records_deduplicates_doc_numbers(self):
        rows = [
            SimpleNamespace(payload={"doc_number": "TW1", "title": "A", "filename": "a.xml", "ipc": "A01", "applicant": "ACME"}),
            SimpleNamespace(payload={"doc_number": "TW1", "title": "A copy", "filename": "a2.xml", "ipc": "A01", "applicant": "ACME"}),
            SimpleNamespace(payload={"doc_number": "TW2", "title": "B", "filename": "b.xml", "ipc": "B02", "applicant": "Beta"}),
        ]
        with patch.object(rag_service, "scroll_points", return_value=rows):
            patents = rag_service.get_patent_records(limit=10)
        self.assertEqual([p["doc_number"] for p in patents], ["TW1", "TW2"])

    def test_compare_patents_reads_from_scroll_points(self):
        abstract = SimpleNamespace(payload={"section": "abstract", "text": "Abstract text"})
        claim = SimpleNamespace(payload={"section": "claim_1", "text": "Claim one"})
        bib = SimpleNamespace(payload={"section": "bibliographic", "text": "Bib data"})
        with patch.object(rag_service, "scroll_points", side_effect=[[abstract, claim, bib], [abstract, claim, bib]]):
            result = rag_service.compare_patents("TW1", "TW2")
        self.assertEqual(result["comparison"]["claim_1"]["a"], "Claim one")

    def test_search_returns_lexical_candidate_when_dense_misses(self):
        lexical = SimpleNamespace(
            id="lex-1",
            payload={
                "text": "Polarizer film with multilayer optical stack",
                "source": "TWX Abstract",
                "filename": "TWX.xml",
                "page": 0,
                "section": "abstract",
                "doc_number": "TWX",
                "tag": "demo",
            },
        )
        fake_qdrant = FakeQdrant(points=[lexical], search_results=[])
        with patch.object(rag_service, "get_qdrant", return_value=fake_qdrant), \
             patch.object(rag_service, "get_embedder", return_value=FakeEmbedder()), \
             patch.object(rag_service, "_reranker", None), \
             patch.object(rag_service, "ENABLE_RERANK", False):
            results = rag_service.search("polarizer film", top_k=1)
        self.assertEqual(results[0]["doc_number"], "TWX")
