# -*- coding: utf-8 -*-
"""
Tests for Updater Module (backend/updater.py)
Covers semver tuple parsing, update progress serialization, and security path whitelists.
"""
import os
import json
import unittest
import tempfile
import shutil

from backend import updater


class TestUpdater(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_updater_test_")
        self.orig_progress_file = updater.PROGRESS_FILE
        updater.PROGRESS_FILE = os.path.join(self.test_dir, "progress.json")

    def tearDown(self):
        updater.PROGRESS_FILE = self.orig_progress_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_version_tuple_parsing(self):
        """Verify _version_tuple converts standard version strings into 4-element integer tuples."""
        self.assertEqual(updater._version_tuple("2.24.1.0"), (2, 24, 1, 0))
        self.assertEqual(updater._version_tuple("v2.30.0"), (2, 30, 0, 0))
        self.assertEqual(updater._version_tuple("3.0"), (3, 0, 0, 0))
        self.assertEqual(updater._version_tuple("invalid"), (0, 0, 0, 0))

        # Semantic comparisons
        self.assertGreater(updater._version_tuple("2.25.0.0"), updater._version_tuple("2.24.9.9"))
        self.assertEqual(updater._version_tuple("2.24"), updater._version_tuple("2.24.0.0"))

    def test_update_progress_lifecycle(self):
        """Verify _write_progress persists state and get_update_progress reads it safely."""
        initial = updater.get_update_progress()
        self.assertEqual(initial.get("stage"), "idle")

        updater._write_progress(stage="downloading", bytes_done=5000, total=10000, message="Downloading 50%")
        progress = updater.get_update_progress()
        self.assertEqual(progress["stage"], "downloading")
        self.assertEqual(progress["bytes_done"], 5000)
        self.assertEqual(progress["total"], 10000)

    def test_security_allow_and_deny_lists(self):
        """Verify critical system files are in DENY list and not in ALLOWED_FILES."""
        for denied in ("config.json", ".env", "data", "media", "winpython", "ffmpeg"):
            self.assertIn(denied, updater.DENY)
            self.assertNotIn(denied, updater.ALLOWED_FILES)


if __name__ == "__main__":
    unittest.main()
