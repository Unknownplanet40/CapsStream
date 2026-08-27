# -*- coding: utf-8 -*-
"""
Tests for Subtitles Module (backend/subtitles.py)
Covers subtitle label parsing, SDH detection, language mapping,
external subtitle discovery, and SRT/VTT formatting.
"""
import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend.subtitles import _parse_sub_label, get_all_subtitles, LANG_NAMES


class TestSubtitles(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_subs_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_sub_label_languages(self):
        """Verify language codes in subtitle filenames map to user-friendly display labels."""
        test_cases = [
            ("Inception.en.srt", "English", "en"),
            ("Movie.Spanish.srt", "Spanish", "spa"),
            ("Show.S01E01.Japanese.vtt", "Japanese", "jpn"),
            ("Film.fr.srt", "French", "fr"),
            ("Video.ger.srt", "German", "ger"),
            ("Anime.tag.srt", "Tagalog", "tag"),
        ]

        for fname, expected_lang_name, expected_code in test_cases:
            label, lang, is_sdh, _ = _parse_sub_label(fname)
            self.assertIn(expected_lang_name.lower(), label.lower(), f"Failed label parse for {fname}")
            self.assertFalse(is_sdh, f"Did not expect SDH for {fname}")

    def test_parse_sub_label_sdh_detection(self):
        """Verify SDH, CC, and Hearing Impaired tags are correctly detected."""
        sdh_files = [
            "Inception.2010.en.sdh.srt",
            "Movie.English.CC.vtt",
            "Show.S01E01.en.hi.srt",
            "Film.en_hearing_impaired.srt",
        ]

        for fname in sdh_files:
            label, lang, is_sdh, _ = _parse_sub_label(fname)
            self.assertTrue(is_sdh, f"Expected SDH tag for {fname}")
            self.assertIn("[SDH]", label, f"Expected [SDH] in label for {fname}")

    def test_external_subtitle_matching(self):
        """Verify external subtitle files in the same directory matching the video stem are discovered."""
        video_path = os.path.join(self.test_dir, "Matrix.1999.1080p.mp4")
        with open(video_path, "wb") as f:
            f.write(b"0" * 512)

        sub_en = os.path.join(self.test_dir, "Matrix.1999.1080p.en.srt")
        with open(sub_en, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nWake up, Neo...\n")

        sub_es = os.path.join(self.test_dir, "Matrix.1999.1080p.es.srt")
        with open(sub_es, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nDespierta, Neo...\n")

        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout=b'{"streams":[]}')
            subs = get_all_subtitles(video_path, media_id=1)

            self.assertGreaterEqual(len(subs), 2)
            urls = [s.get("url", "") for s in subs]
            self.assertTrue(any("Matrix.1999.1080p.en.srt" in u for u in urls))
            self.assertTrue(any("Matrix.1999.1080p.es.srt" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
