# -*- coding: utf-8 -*-
"""
Tests for Audio Probing Module (backend/audio_probe.py)
Covers track extraction, language code mapping, channel labels, caching, and error handling.
"""
import os
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch

from backend.audio_probe import probe_audio_tracks, LANG_NAMES
from backend.utils import probe_cache


class TestAudioProbe(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_audio_probe_test_")
        self.dummy_video = os.path.join(self.test_dir, "sample.mkv")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy video content")
        probe_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        probe_cache.clear()

    def test_nonexistent_file_returns_empty_list(self):
        """Verify probing a missing file returns an empty list immediately without crashing."""
        result = probe_audio_tracks(os.path.join(self.test_dir, "nonexistent.mkv"))
        self.assertEqual(result, [])

    @patch("backend.audio_probe.os.path.exists")
    @patch("backend.audio_probe.subprocess.check_output")
    def test_probe_multiple_audio_tracks(self, mock_subprocess, mock_exists):
        """Verify parsing multi-track audio metadata including languages, dispositions, and channel formats."""
        mock_exists.return_value = True

        fake_ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "index": 0
                },
                {
                    "codec_type": "audio",
                    "index": 1,
                    "codec_name": "aac",
                    "channels": 6,
                    "disposition": {"default": 1},
                    "tags": {
                        "language": "eng",
                        "title": "Surround 5.1"
                    }
                },
                {
                    "codec_type": "audio",
                    "index": 2,
                    "codec_name": "opus",
                    "channels": 2,
                    "disposition": {"default": 0},
                    "tags": {
                        "language": "jpn"
                    }
                }
            ]
        }
        mock_subprocess.return_value = json.dumps(fake_ffprobe_output).encode("utf-8")

        tracks = probe_audio_tracks(self.dummy_video)
        self.assertEqual(len(tracks), 2)

        # Track 1
        t1 = tracks[0]
        self.assertEqual(t1["index"], 0)
        self.assertEqual(t1["stream_index"], 1)
        self.assertEqual(t1["language"], "eng")
        self.assertEqual(t1["codec"], "AAC")
        self.assertEqual(t1["channels"], 6)
        self.assertTrue(t1["default"])
        self.assertIn("English", t1["title"])
        self.assertIn("Surround 5.1", t1["title"])

        # Track 2
        t2 = tracks[1]
        self.assertEqual(t2["index"], 1)
        self.assertEqual(t2["stream_index"], 2)
        self.assertEqual(t2["language"], "jpn")
        self.assertEqual(t2["codec"], "OPUS")
        self.assertEqual(t2["channels"], 2)
        self.assertFalse(t2["default"])
        self.assertIn("Japanese", t2["title"])
        self.assertIn("Stereo", t2["title"])

    @patch("backend.audio_probe.os.path.exists")
    @patch("backend.audio_probe.subprocess.check_output")
    def test_probe_cache_hit(self, mock_subprocess, mock_exists):
        """Verify subsequent calls return cached audio track metadata without re-executing ffprobe."""
        mock_exists.return_value = True
        fake_ffprobe_output = {
            "streams": [
                {
                    "codec_type": "audio",
                    "index": 1,
                    "codec_name": "ac3",
                    "channels": 2,
                    "tags": {"language": "spa"}
                }
            ]
        }
        mock_subprocess.return_value = json.dumps(fake_ffprobe_output).encode("utf-8")

        # First call: cache miss
        tracks1 = probe_audio_tracks(self.dummy_video)
        self.assertEqual(len(tracks1), 1)
        self.assertEqual(mock_subprocess.call_count, 1)

        # Second call: cache hit
        tracks2 = probe_audio_tracks(self.dummy_video)
        self.assertEqual(tracks1, tracks2)
        self.assertEqual(mock_subprocess.call_count, 1)

    @patch("backend.audio_probe.os.path.exists")
    @patch("backend.audio_probe.subprocess.check_output")
    def test_probe_error_handling(self, mock_subprocess, mock_exists):
        """Verify subprocess errors or JSON decoding failures return an empty list gracefully."""
        mock_exists.return_value = True
        mock_subprocess.side_effect = Exception("FFprobe execution timeout")

        tracks = probe_audio_tracks(self.dummy_video)
        self.assertEqual(tracks, [])


if __name__ == "__main__":
    unittest.main()
