# -*- coding: utf-8 -*-
"""
Tests for OpenSubtitles Module (backend/opensubs.py)
Covers OpenSubtitles movie hash calculation and mock subtitle download handling.
"""
import os
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend import opensubs


class TestOpenSubs(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_opensubs_test_")
        self.dummy_video = os.path.join(self.test_dir, "sample_movie.mp4")
        # Create a file > 65536 bytes (e.g. 131,072 bytes) so compute_os_hash works
        with open(self.dummy_video, "wb") as f:
            f.write(bytes([i % 256 for i in range(131072)]))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_compute_os_hash(self):
        """Verify compute_os_hash returns deterministic 64-bit integer hash for files > 64KB."""
        h1 = opensubs.compute_os_hash(self.dummy_video)
        self.assertIsNotNone(h1)
        self.assertTrue(isinstance(h1, int))

        # Re-running on the exact same file yields identical hash
        h2 = opensubs.compute_os_hash(self.dummy_video)
        self.assertEqual(h1, h2)

    def test_compute_os_hash_small_file(self):
        """Verify files smaller than 64KB return None."""
        small_file = os.path.join(self.test_dir, "small.mp4")
        with open(small_file, "wb") as f:
            f.write(b"too small")
        self.assertIsNone(opensubs.compute_os_hash(small_file))

    @patch("backend.opensubs._api_get")
    @patch("backend.opensubs._api_post")
    @patch("backend.opensubs._download_link")
    def test_download_subtitles_for_file(self, mock_download, mock_post, mock_get):
        """Verify download_subtitles_for_file queries API, requests download link, and saves subtitle file."""
        mock_get.return_value = {
            "data": [
                {
                    "attributes": {
                        "language": "en",
                        "download_count": 500,
                        "files": [{"file_id": 12345}]
                    }
                }
            ]
        }
        mock_post.return_value = {
            "link": "https://api.opensubtitles.com/download/file.srt",
            "file_name": "sample_movie.en.srt"
        }
        mock_download.return_value = 1024

        saved = opensubs.download_subtitles_for_file(self.dummy_video, api_key="dummy_api_key", languages="en")
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].endswith(".en.srt"))


if __name__ == "__main__":
    unittest.main()
