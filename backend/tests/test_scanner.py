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

    def test_drive_mount_detection(self):
        """Verify drive mount check handles existing paths and missing virtual paths."""
        self.assertTrue(is_drive_mounted(self.test_dir))
        fake_path = r"Z:\NonExistentDrive\Media\movie.mp4"
        self.assertFalse(is_drive_mounted(fake_path))


if __name__ == "__main__":
    unittest.main()
