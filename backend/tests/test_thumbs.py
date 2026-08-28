# -*- coding: utf-8 -*-
"""
Tests for Thumbnail Sprite Sheet Module (backend/thumbs.py)
Covers sidecar and sheet path helpers, readiness checks, info retrieval, and sheet generation.
"""
import os
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend import thumbs


class TestThumbs(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_thumbs_test_")
        self.orig_thumb_dir = thumbs.THUMB_DIR
        thumbs.THUMB_DIR = self.test_dir

        self.dummy_video = os.path.join(self.test_dir, "sample.mp4")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy video data for thumbnail testing")

    def tearDown(self):
        thumbs.THUMB_DIR = self.orig_thumb_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_ready_and_get_info(self):
        """Verify is_ready and get_info accurately inspect disk artifacts."""
        media_id = 999
        self.assertFalse(thumbs.is_ready(media_id))
        self.assertIsNone(thumbs.get_info(media_id))

        # Create sheet and sidecar
        sheet_path = thumbs._sheet(media_id)
        sidecar_path = thumbs._sidecar(media_id)

        with open(sheet_path, "wb") as f:
            f.write(b"fake jpeg data")

        sidecar_data = {
            "url": f"/api/media/{media_id}/thumbnails/sheet",
            "interval": 10,
            "cols": 10,
            "count": 20,
            "cell_width": 160,
            "cell_height": 90,
            "duration": 200,
        }
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar_data, f)

        self.assertTrue(thumbs.is_ready(media_id))
        info = thumbs.get_info(media_id)
        self.assertEqual(info["cols"], 10)
        self.assertEqual(info["duration"], 200)

    @patch("backend.thumbs.os.path.exists")
    @patch("backend.thumbs.subprocess.run")
    def test_generate_sheet_success(self, mock_subproc, mock_exists):
        """Verify generate_sheet creates cells, tiles sheet, and saves sidecar metadata."""
        mock_exists.return_value = True

        media_id = 123
        cells_dir = os.path.join(thumbs.THUMB_DIR, f"{media_id}_cells")
        sheet_file = thumbs._sheet(media_id)

        # Mock subprocess to write sample files when called
        def fake_run(cmd, *args, **kwargs):
            # If scaling individual cell
            if "-frames:v" in cmd and "cell_" in cmd[-1]:
                target_cell = cmd[-1]
                os.makedirs(os.path.dirname(target_cell), exist_ok=True)
                with open(target_cell, "wb") as f:
                    f.write(b"x" * 1024)
            # If tiling into final sheet
            elif "tile=" in str(cmd):
                with open(sheet_file, "wb") as f:
                    f.write(b"x" * 4096)
            # If ffprobe probing sheet height
            elif "ffprobe.exe" in cmd[0]:
                return MagicMock(returncode=0, stdout=json.dumps({"streams": [{"height": 900}]}))
            return MagicMock(returncode=0)

        mock_subproc.side_effect = fake_run

        info = thumbs.generate_sheet(media_id, self.dummy_video, duration=300)
        self.assertIsNotNone(info)
        self.assertEqual(info["duration"], 300)
        self.assertTrue(os.path.isfile(thumbs._sidecar(media_id)))

    def test_generate_sheet_short_duration_returns_none(self):
        """Verify videos under 30s are skipped for thumbnail sheet generation."""
        res = thumbs.generate_sheet(101, self.dummy_video, duration=15)
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
