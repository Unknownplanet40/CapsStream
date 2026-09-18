# -*- coding: utf-8 -*-
"""
Tests for Media Scanner Module (backend/scanner.py)
Covers file extension filtering, directory walking, disabled path exclusions,
and mount detection caching.
"""
import os
import sys
import unittest
import tempfile
import shutil

from backend.tests import create_isolated_test_db
from backend.scanner import VIDEO_EXTS, _is_video, _scan_movies, _scan_shows
from backend.db.media import is_drive_mounted, is_file_path_disabled


class TestMediaScanner(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_scan_test_")

    def tearDown(self):
        self.cleanup_db()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_media_extensions_recognition(self):
        """Verify video file extensions are recognized and non-video extensions are ignored."""
        valid_files = ["movie.mp4", "episode.mkv", "film.avi", "clip.mov", "video.webm", "stream.m4v", "test.ts"]
        invalid_files = ["sub.srt", "info.nfo", "poster.jpg", "cover.png", "notes.txt", "script.py", "archive.zip"]

        for f in valid_files:
            self.assertTrue(_is_video(f), f"Expected {f} to be recognized as video")

        for f in invalid_files:
            self.assertFalse(_is_video(f), f"Expected {f} NOT to be recognized as video")

    def test_scanner_discovers_nested_movies(self):
        """Verify _scan_movies walks directory trees and indexes video files."""
        movies_dir = os.path.join(self.test_dir, "Movies", "Inception (2010)")
        os.makedirs(movies_dir, exist_ok=True)
        dummy_movie = os.path.join(movies_dir, "Inception.2010.1080p.mp4")
        with open(dummy_movie, "wb") as f:
            f.write(b"0" * 1024)

        results = _scan_movies(path_list=[self.test_dir], existing_paths=set())
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["file_path"], dummy_movie)
        self.assertEqual(results[0]["type"], "movie")

    def test_disabled_paths_exclusion(self):
        """Verify files within disabled path roots are properly identified as disabled."""
        disabled_folder = os.path.join(self.test_dir, "ExcludedFolder")
        os.makedirs(disabled_folder, exist_ok=True)
        dummy_file = os.path.join(disabled_folder, "HiddenMovie.mp4")

        disabled_roots = [disabled_folder.replace("/", "\\").lower().rstrip("\\")]

        self.assertTrue(is_file_path_disabled(dummy_file, disabled_roots))
        self.assertFalse(is_file_path_disabled(os.path.join(self.test_dir, "Allowed.mp4"), disabled_roots))

    def test_reset_scan_status(self):
        """Verify reset_scan_status restores clean idle state."""
        from backend.scanner import reset_scan_status, get_scan_status, _set_status
        _set_status(running=True, phase="scanning", progress="testing...")
        self.assertTrue(get_scan_status()["running"])
        reset_scan_status()
        status = get_scan_status()
        self.assertFalse(status["running"])
        self.assertEqual(status["phase"], "idle")
        self.assertEqual(status["progress"], "")

    def test_resolve_paths_ignores_empty_or_invalid(self):
        """Verify _resolve_paths never resolves empty strings or invalid types to BASE_DIR."""
        from backend.scanner import _resolve_paths
        from backend.utils.paths import BASE_DIR
        resolved = _resolve_paths(["", "  ", None, 123])
        self.assertEqual(resolved, [])
        self.assertNotIn(BASE_DIR, resolved)

    def test_should_skip_system_and_hidden_folders(self):
        """Verify _should_skip skips hidden, recycle bin, and repo folders."""
        from backend.scanner import _should_skip
        self.assertTrue(_should_skip(".CapsStream"))
        self.assertTrue(_should_skip(".git"))
        self.assertTrue(_should_skip("$RECYCLE.BIN"))
        self.assertTrue(_should_skip("System Volume Information"))
        self.assertTrue(_should_skip(".hidden_dir"))
        self.assertFalse(_should_skip("Avatar (2009)"))

    def test_scan_library_error_recovery(self):
        """Verify scan_library sets running=False even if an unhandled error happens."""
        from unittest.mock import patch
        from backend.scanner import scan_library, get_scan_status, reset_scan_status
        reset_scan_status()
        with patch("backend.scanner._scan_movies", side_effect=RuntimeError("Disk failure test")):
            with patch("backend.scanner._resolve_paths", return_value=[self.test_dir]):
                scan_library()
        status = get_scan_status()
        self.assertFalse(status["running"], "Scanner must never stay running on fatal exception")
        self.assertEqual(status["phase"], "complete")
        self.assertTrue(any("Disk failure test" in e for e in status["errors"]))


if __name__ == "__main__":
    unittest.main()
