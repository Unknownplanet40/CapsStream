# -*- coding: utf-8 -*-
"""
Tests for Intro Detection Module (backend/intro_detect.py)
Covers FFmpeg silencedetect output parsing, threshold evaluation, and missing file handling.
"""
import os
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend.intro_detect import detect_intro


class TestIntroDetect(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_intro_detect_test_")
        self.dummy_video = os.path.join(self.test_dir, "sample_episode.mkv")
        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy episode data")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_file_returns_none(self):
        """Verify missing video file returns None safely."""
        res = detect_intro(os.path.join(self.test_dir, "nonexistent.mkv"))
        self.assertIsNone(res)

    @patch("backend.intro_detect.os.path.exists")
    @patch("backend.intro_detect.subprocess.run")
    def test_detect_intro_success(self, mock_subproc, mock_exists):
        """Verify successful intro detection when silencedetect intervals indicate intro theme."""
        mock_exists.return_value = True

        fake_stderr = """
        [silencedetect @ 000001] silence_start: 18.5
        [silencedetect @ 000001] silence_end: 22.0 | silence_duration: 3.5
        [silencedetect @ 000001] silence_start: 112.0
        [silencedetect @ 000001] silence_end: 114.5 | silence_duration: 2.5
        """
        mock_subproc.return_value = MagicMock(returncode=0, stderr=fake_stderr)

        result = detect_intro(self.dummy_video)
        self.assertIsNotNone(result)
        self.assertEqual(result["start"], 22.0)
        self.assertEqual(result["end"], 112.0)

    @patch("backend.intro_detect.os.path.exists")
    @patch("backend.intro_detect.subprocess.run")
    def test_detect_intro_no_silence_found(self, mock_subproc, mock_exists):
        """Verify detect_intro returns None when no silence intervals are found."""
        mock_exists.return_value = True
        mock_subproc.return_value = MagicMock(returncode=0, stderr="No silence detected in audio stream.")

        result = detect_intro(self.dummy_video)
        self.assertIsNone(result)

    @patch("backend.intro_detect.os.path.exists")
    @patch("backend.intro_detect.subprocess.run")
    def test_detect_intro_duration_out_of_bounds(self, mock_subproc, mock_exists):
        """Verify detect_intro rejects intro segment that is shorter than MIN_INTRO or longer than MAX_INTRO."""
        mock_exists.return_value = True

        # Duration is only 3s (too short)
        fake_stderr_short = """
        [silencedetect @ 000001] silence_start: 19.0
        [silencedetect @ 000001] silence_end: 22.0
        [silencedetect @ 000001] silence_start: 24.0
        [silencedetect @ 000001] silence_end: 26.0
        """
        mock_subproc.return_value = MagicMock(returncode=0, stderr=fake_stderr_short)
        result = detect_intro(self.dummy_video)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
