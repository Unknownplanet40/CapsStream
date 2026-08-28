# -*- coding: utf-8 -*-
"""
Tests for Video Probing Module (backend/video_probe.py)
Covers codec tag extraction, resolution labeling, full video stream details probing, and caching.
"""
import os
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch

from backend.video_probe import (
    extract_codec_tag,
    format_resolution_label,
    probe_video_resolution,
    probe_video_details
)
from backend.utils import probe_cache


class TestVideoProbe(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_video_probe_test_")
        self.dummy_video = os.path.join(self.test_dir, "sample_movie.mkv")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy video data for probe test")
        probe_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        probe_cache.clear()

    def test_extract_codec_tag(self):
        """Verify extract_codec_tag correctly prioritizes codec names and falls back to filenames."""
        # Standard mappings from codec_name
        self.assertEqual(extract_codec_tag("hevc"), "x265")
        self.assertEqual(extract_codec_tag("h265"), "x265")
        self.assertEqual(extract_codec_tag("h264"), "x264")
        self.assertEqual(extract_codec_tag("avc"), "x264")
        self.assertEqual(extract_codec_tag("av1"), "AV1")
        self.assertEqual(extract_codec_tag("vp9"), "VP9")

        # Fallback from filename
        self.assertEqual(extract_codec_tag("", "Movie.2023.1080p.HEVC.mkv"), "x265")
        self.assertEqual(extract_codec_tag("", "Movie.2023.1080p.x264.mkv"), "x264")
        self.assertEqual(extract_codec_tag("", "Movie.2023.AV1.mkv"), "AV1")
        self.assertEqual(extract_codec_tag("", "Movie.2023.VP9.mkv"), "VP9")

        # Other codecs
        self.assertEqual(extract_codec_tag("mpeg4"), "MPEG4")
        self.assertEqual(extract_codec_tag(""), "")

    def test_format_resolution_label(self):
        """Verify format_resolution_label calculates user-friendly resolution strings."""
        self.assertEqual(format_resolution_label(3840, 2160), "4K UHD")
        self.assertEqual(format_resolution_label(1920, 1080), "1080p HD")
        self.assertEqual(format_resolution_label(1280, 720), "720p HD")
        self.assertEqual(format_resolution_label(854, 480), "480p SD")
        self.assertEqual(format_resolution_label(640, 360), "360p")
        self.assertEqual(format_resolution_label(0, 0), "Standard Quality")

    @patch("backend.video_probe.os.path.exists")
    @patch("backend.video_probe.subprocess.check_output")
    def test_probe_video_resolution(self, mock_subprocess, mock_exists):
        """Verify probe_video_resolution extracts width, height, and labels accurately."""
        mock_exists.return_value = True
        fake_ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080
                }
            ]
        }
        mock_subprocess.return_value = json.dumps(fake_ffprobe_output).encode("utf-8")

        res = probe_video_resolution(self.dummy_video)
        self.assertEqual(res["width"], 1920)
        self.assertEqual(res["height"], 1080)
        self.assertEqual(res["codec"], "x265")
        self.assertEqual(res["base_label"], "1080p HD")
        self.assertEqual(res["label"], "1080p HD • x265")

    @patch("backend.video_probe.os.path.exists")
    @patch("backend.video_probe.subprocess.check_output")
    def test_probe_video_details_hevc_10bit(self, mock_subprocess, mock_exists):
        """Verify probe_video_details detects 10-bit HEVC correctly (is_h264 should be False)."""
        mock_exists.return_value = True
        fake_ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "pix_fmt": "yuv420p10le",
                    "width": 1920,
                    "height": 1080
                },
                {
                    "codec_type": "audio",
                    "codec_name": "opus",
                    "channels": 2,
                    "sample_rate": "48000"
                }
            ]
        }
        mock_subprocess.return_value = json.dumps(fake_ffprobe_output).encode("utf-8")

        details = probe_video_details(self.dummy_video)
        self.assertEqual(details["video_codec"], "hevc")
        self.assertEqual(details["pix_fmt"], "yuv420p10le")
        self.assertFalse(details["is_h264"])
        self.assertEqual(details["width"], 1920)
        self.assertEqual(details["height"], 1080)
        self.assertEqual(len(details["audio_tracks"]), 1)
        self.assertEqual(details["audio_tracks"][0]["codec"], "opus")

    @patch("backend.video_probe.os.path.exists")
    @patch("backend.video_probe.subprocess.check_output")
    def test_probe_video_details_h264_8bit(self, mock_subprocess, mock_exists):
        """Verify probe_video_details flags 8-bit H.264 as is_h264 = True for smart remuxing."""
        mock_exists.return_value = True
        fake_ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "width": 1920,
                    "height": 1080
                }
            ]
        }
        mock_subprocess.return_value = json.dumps(fake_ffprobe_output).encode("utf-8")

        details = probe_video_details(self.dummy_video)
        self.assertEqual(details["video_codec"], "h264")
        self.assertEqual(details["pix_fmt"], "yuv420p")
        self.assertTrue(details["is_h264"])

    def test_probe_missing_file(self):
        """Verify probing missing file returns safe defaults."""
        details = probe_video_details(os.path.join(self.test_dir, "missing.mp4"))
        self.assertEqual(details["width"], 0)
        self.assertFalse(details["is_h264"])
        self.assertEqual(details["audio_tracks"], [])


if __name__ == "__main__":
    unittest.main()
