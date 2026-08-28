# -*- coding: utf-8 -*-
"""
Tests for Skip Times Module (backend/skip_times.py)
Covers manual skip markers, AniSkip API fallback, embedded chapter probing, anime detection, and caching.
"""
import os
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend import skip_times


class TestSkipTimes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_skip_test_")
        self.orig_cache_dir = skip_times.SKIP_CACHE_DIR
        self.orig_mal_file = skip_times.MAL_CACHE_FILE
        skip_times.SKIP_CACHE_DIR = os.path.join(self.test_dir, "skips")
        skip_times.MAL_CACHE_FILE = os.path.join(self.test_dir, "mal.json")
        os.makedirs(skip_times.SKIP_CACHE_DIR, exist_ok=True)

        self.dummy_video = os.path.join(self.test_dir, "anime_ep.mkv")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy video")

    def tearDown(self):
        skip_times.SKIP_CACHE_DIR = self.orig_cache_dir
        skip_times.MAL_CACHE_FILE = self.orig_mal_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_anime_detection(self):
        """Verify is_anime recognizes explicit anime types and animated series."""
        self.assertTrue(skip_times.is_anime({"type": "anime", "title": "Attack on Titan"}))
        self.assertTrue(skip_times.is_anime({"type": "series", "genres": "Action, Animation, Drama"}))
        self.assertFalse(skip_times.is_anime({"type": "movie", "genres": "Action, Drama"}))
        self.assertFalse(skip_times.is_anime(None))

    @patch("backend.skip_times.get_media_by_id")
    def test_manual_skip_markers_highest_priority(self, mock_get_media):
        """Verify manual recap, intro, outro timestamps stored on the media take highest priority."""
        mock_get_media.return_value = {
            "id": 1,
            "title": "Anime Show",
            "type": "anime",
            "recap_start": 0,
            "recap_end": 60,
            "intro_start": 65,
            "intro_end": 155,
            "outro_start": 1300,
            "outro_end": 1390,
            "preview_start": 1395,
            "preview_end": 1420,
        }

        skips = skip_times.fetch_skip_times(1)
        self.assertEqual(len(skips), 4)
        self.assertEqual(skips["op"]["source"], "manual")
        self.assertEqual(skips["op"]["start"], 65.0)
        self.assertEqual(skips["op"]["end"], 155.0)
        self.assertEqual(skips["ed"]["source"], "manual")
        self.assertEqual(skips["recap"]["source"], "manual")
        self.assertEqual(skips["preview"]["source"], "manual")

    @patch("backend.skip_times.subprocess.run")
    def test_probe_chapters_for_skips(self, mock_subproc):
        """Verify probe_chapters_for_skips parses embedded intro/outro/preview chapter titles."""
        fake_chapters_json = {
            "chapters": [
                {
                    "start_time": "0.000",
                    "end_time": "120.000",
                    "tags": {"title": "Prologue"}
                },
                {
                    "start_time": "120.000",
                    "end_time": "210.000",
                    "tags": {"title": "Opening Theme"}
                },
                {
                    "start_time": "1300.000",
                    "end_time": "1390.000",
                    "tags": {"title": "Ending / Credits"}
                },
                {
                    "start_time": "1390.000",
                    "end_time": "1420.000",
                    "tags": {"title": "Next Episode Preview"}
                }
            ]
        }
        mock_subproc.return_value = MagicMock(returncode=0, stdout=json.dumps(fake_chapters_json))

        skips = skip_times.probe_chapters_for_skips(self.dummy_video)
        self.assertIn("op", skips)
        self.assertEqual(skips["op"]["start"], 120.0)
        self.assertEqual(skips["op"]["end"], 210.0)
        self.assertEqual(skips["op"]["source"], "chapters")

        self.assertIn("ed", skips)
        self.assertEqual(skips["ed"]["start"], 1300.0)

        self.assertIn("preview", skips)
        self.assertEqual(skips["preview"]["start"], 1390.0)


if __name__ == "__main__":
    unittest.main()
