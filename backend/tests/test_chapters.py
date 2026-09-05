# -*- coding: utf-8 -*-
"""
Tests for Chapters Extraction & API Module (backend/skip_times.py & backend/routes/streaming.py)
"""
import os
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend import skip_times


class TestChapters(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_chapter_test_")
        self.orig_cache_dir = skip_times.CHAPTERS_CACHE_DIR
        skip_times.CHAPTERS_CACHE_DIR = os.path.join(self.test_dir, "chapters")
        os.makedirs(skip_times.CHAPTERS_CACHE_DIR, exist_ok=True)

        self.dummy_video = os.path.join(self.test_dir, "movie.mkv")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy movie data")

    def tearDown(self):
        skip_times.CHAPTERS_CACHE_DIR = self.orig_cache_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("backend.skip_times.subprocess.run")
    def test_probe_chapters_full(self, mock_subproc):
        fake_chapters_json = {
            "chapters": [
                {
                    "id": 0,
                    "start_time": "0.000000",
                    "end_time": "120.500000",
                    "tags": {"title": "Prologue"}
                },
                {
                    "id": 1,
                    "start_time": "120.500000",
                    "end_time": "720.000000",
                    "tags": {"title": "The Awakening"}
                },
                {
                    "id": 2,
                    "start_time": "720.000000",
                    "end_time": "1500.000000"
                }
            ]
        }
        mock_subproc.return_value = MagicMock(returncode=0, stdout=json.dumps(fake_chapters_json))
        chapters = skip_times.probe_chapters_full(self.dummy_video)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0]["title"], "Prologue")
        self.assertEqual(chapters[0]["start"], 0.0)
        self.assertEqual(chapters[0]["end"], 120.5)
        self.assertEqual(chapters[1]["title"], "The Awakening")
        self.assertEqual(chapters[2]["title"], "Chapter 3")

    @patch("backend.skip_times.get_media_by_id")
    @patch("backend.skip_times.probe_chapters_full")
    def test_fetch_chapters_caching(self, mock_probe, mock_get_media):
        mock_get_media.return_value = {"id": 42, "file_path": self.dummy_video}
        mock_probe.return_value = [{"id": 0, "start": 0.0, "end": 100.0, "title": "Intro"}]

        # 1. First fetch: calls probe and writes cache
        res1 = skip_times.fetch_chapters(42)
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["title"], "Intro")
        self.assertEqual(mock_probe.call_count, 1)

        # 2. Second fetch: should read from cache file, not re-probe
        res2 = skip_times.fetch_chapters(42)
        self.assertEqual(len(res2), 1)
        self.assertEqual(mock_probe.call_count, 1)


if __name__ == "__main__":
    unittest.main()
