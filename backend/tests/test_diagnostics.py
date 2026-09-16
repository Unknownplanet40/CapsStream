# -*- coding: utf-8 -*-
"""
Tests for System Diagnostics Collector (backend/utils/diagnostics.py)
"""
import unittest
from unittest.mock import patch, MagicMock

from backend.utils.diagnostics import get_system_diagnostics


class TestSystemDiagnostics(unittest.TestCase):
    @patch("backend.utils.diagnostics.os.path.exists")
    @patch("backend.utils.diagnostics.os.path.getsize")
    def test_diagnostics_returns_valid_structure(self, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 10485760  # 10 MB

        stats = get_system_diagnostics()
        self.assertTrue(stats["ok"])
        self.assertIn("cpu_pct", stats)
        self.assertIn("ram_used_gb", stats)
        self.assertIn("ram_total_gb", stats)
        self.assertIn("ram_pct", stats)
        self.assertIn("active_streams", stats)
        self.assertIn("db_size", stats)
        self.assertIn("db_size_bytes", stats)
        self.assertIsInstance(stats["cpu_pct"], (int, float))
        self.assertIsInstance(stats["active_streams"], int)
        self.assertEqual(stats["db_size_bytes"], 10485760)
        self.assertEqual(stats["db_size"], "10.0 MB")


if __name__ == "__main__":
    unittest.main()
