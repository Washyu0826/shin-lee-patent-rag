import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import main


class MainHelperTests(unittest.TestCase):
    def test_normalize_uploaded_name_keeps_basename(self):
        name = main._normalize_uploaded_name(r"nested\folder\patent.pdf", {".pdf"})
        self.assertEqual(name, "patent.pdf")

    def test_stored_file_path_rejects_path_traversal(self):
        with self.assertRaises(HTTPException) as ctx:
            main._stored_file_path("../secret.pdf", {".pdf"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_safe_scan_dir_rejects_outside_data_root(self):
        with self.assertRaises(HTTPException) as ctx:
            main._safe_scan_dir("../outside")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_split_csv_env_parses_values(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ORIGINS": "http://a.test, http://b.test "}, clear=False):
            origins = main._split_csv_env("CORS_ALLOW_ORIGINS")
        self.assertEqual(origins, ["http://a.test", "http://b.test"])
