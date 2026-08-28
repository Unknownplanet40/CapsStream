# -*- coding: utf-8 -*-
"""
Tests for Backend Utility Modules (backend/utils/*)
Covers paths, probe cache, response envelopes, formatting, scheduler persistence, and version detection.
"""
import os
import sys
import json
import unittest
import tempfile
import shutil

from backend.utils import paths
from backend.utils import probe_cache
from backend.utils import responses
from backend.utils import formatting
from backend.utils import scheduler
from backend.utils import version


class TestUtils(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_utils_test_")
        probe_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        probe_cache.clear()

    # ─── paths.py ────────────────────────────────────────────────────────────
    def test_paths_constants(self):
        """Verify BASE_DIR, FFMPEG_BIN, and FFPROBE_BIN are defined strings."""
        self.assertTrue(isinstance(paths.BASE_DIR, str))
        self.assertTrue(isinstance(paths.FFMPEG_BIN, str))
        self.assertTrue(isinstance(paths.FFPROBE_BIN, str))
        self.assertTrue(isinstance(paths.has_ffmpeg(), bool))
        self.assertTrue(isinstance(paths.has_ffprobe(), bool))

    # ─── probe_cache.py ──────────────────────────────────────────────────────
    def test_probe_cache_lifecycle(self):
        """Verify probe_cache put, get, clear, and capacity eviction."""
        key = ("test_key", 123)
        self.assertIsNone(probe_cache.get(key))

        probe_cache.put(key, {"data": "sample"})
        self.assertEqual(probe_cache.get(key), {"data": "sample"})

        probe_cache.clear()
        self.assertIsNone(probe_cache.get(key))

    def test_probe_cache_max_eviction(self):
        """Verify probe_cache clears on overflow when _MAX entries is exceeded."""
        orig_max = probe_cache._MAX
        try:
            probe_cache._MAX = 5
            for i in range(10):
                probe_cache.put(f"key_{i}", i)
            # Should have reset and kept the latest
            self.assertIsNotNone(probe_cache.get("key_9"))
        finally:
            probe_cache._MAX = orig_max

    # ─── formatting.py ───────────────────────────────────────────────────────
    def test_format_bytes(self):
        """Verify format_bytes formats sizes into KB / MB / GB / TB cleanly."""
        self.assertEqual(formatting.format_bytes(0), "0 GB")
        self.assertEqual(formatting.format_bytes(500 * 1024), "500 KB")
        self.assertEqual(formatting.format_bytes(1024 * 1024 * 5), "5.0 MB")
        self.assertEqual(formatting.format_bytes(int(1024 * 1024 * 1024 * 2.5)), "2.50 GB")
        self.assertEqual(formatting.format_bytes(int(1024 * 1024 * 1024 * 1024 * 1.5)), "1.50 TB")
        self.assertEqual(formatting.format_bytes(-10), "0 GB")
        self.assertEqual(formatting.format_bytes(None), "0 GB")

    # ─── responses.py ────────────────────────────────────────────────────────
    def test_api_responses(self):
        """Verify api_ok and api_error return valid Flask JSON response tuples."""
        from flask import Flask
        app = Flask(__name__)

        with app.test_request_context():
            resp = responses.api_ok(items=[1, 2, 3])
            data = resp.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["items"], [1, 2, 3])

            resp_err, status_err = responses.api_error("Item not found", status=404)
            self.assertEqual(status_err, 404)
            data_err = resp_err.get_json()
            self.assertEqual(data_err["error"], "Item not found")

    # ─── scheduler.py ────────────────────────────────────────────────────────
    def test_scheduler_read_write(self):
        """Verify saving and loading scheduled scan timestamps."""
        orig_file = scheduler._SCAN_SCHEDULE_FILE
        tmp_sched_file = os.path.join(self.test_dir, "scan_schedule.json")
        try:
            scheduler._SCAN_SCHEDULE_FILE = tmp_sched_file
            self.assertEqual(scheduler.read_last_scheduled_scan(), 0.0)

            scheduler.write_last_scheduled_scan(1700000000.0)
            self.assertEqual(scheduler.read_last_scheduled_scan(), 1700000000.0)
        finally:
            scheduler._SCAN_SCHEDULE_FILE = orig_file

    # ─── version.py ──────────────────────────────────────────────────────────
    def test_version_detection(self):
        """Verify get_app_version and is_dev_mode return sensible values."""
        ver = version.get_app_version()
        self.assertTrue(isinstance(ver, str))
        self.assertTrue(len(ver) > 0)
        self.assertTrue(isinstance(version.is_dev_mode(), bool))


if __name__ == "__main__":
    unittest.main()
