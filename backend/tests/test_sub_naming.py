# -*- coding: utf-8 -*-
"""
Tests for Subtitle Naming & Parsing Module (backend/sub_naming.py)
Covers language normalization, flag extraction, duplicate suffix handling,
filename formatting, and player display labels.
"""

import unittest
from backend.sub_naming import (
    normalize_lang,
    parse_filename,
    format_filename_tag,
    display_label,
    LANG_MAP,
    LANG_NAMES,
)


class TestSubNaming(unittest.TestCase):
    def test_normalize_lang(self):
        """Test ISO 639-1 / 639-2 and localized language aliases."""
        self.assertEqual(normalize_lang("en"), "en")
        self.assertEqual(normalize_lang("eng"), "en")
        self.assertEqual(normalize_lang("English"), "en")
        self.assertEqual(normalize_lang("tl"), "tl")
        self.assertEqual(normalize_lang("tag"), "tl")
        self.assertEqual(normalize_lang("tgl"), "tl")
        self.assertEqual(normalize_lang("Tagalog"), "tl")
        self.assertEqual(normalize_lang("Filipino"), "tl")
        self.assertEqual(normalize_lang("spa"), "es")
        self.assertEqual(normalize_lang("Spanish"), "es")
        self.assertEqual(normalize_lang("jpn"), "ja")
        self.assertEqual(normalize_lang("Japanese"), "ja")
        self.assertEqual(normalize_lang("fra"), "fr")
        self.assertEqual(normalize_lang("ger"), "de")
        self.assertIsNone(normalize_lang("unknown_lang_token"))
        self.assertIsNone(normalize_lang(""))

    def test_parse_filename_flags(self):
        """Test detection of Forced, HI, SDH, CC flags."""
        p_forced = parse_filename("Avatar.2009.en.forced.srt")
        self.assertEqual(p_forced.lang, "en")
        self.assertTrue(p_forced.is_forced)
        self.assertFalse(p_forced.is_hi)

        p_hi = parse_filename("Avatar.2009.en.hi.srt")
        self.assertEqual(p_hi.lang, "en")
        self.assertTrue(p_hi.is_hi)
        self.assertFalse(p_hi.is_forced)

        p_sdh = parse_filename("Movie.2020.en.sdh.vtt")
        self.assertEqual(p_sdh.lang, "en")
        self.assertTrue(p_sdh.is_hi)

        p_cc = parse_filename("Show.S01E01.English.CC.srt")
        self.assertEqual(p_cc.lang, "en")
        self.assertTrue(p_cc.is_hi)

    def test_parse_filename_no_english_bias(self):
        """Ensure HI tag alone does not falsely classify unknown language as English."""
        p_sdh_only = parse_filename("UnknownMedia.SDH.srt")
        self.assertEqual(p_sdh_only.lang, "und")
        self.assertTrue(p_sdh_only.is_hi)
        self.assertFalse(p_sdh_only.is_recognized)

    def test_parse_filename_suffixes(self):
        """Test duplicate numeric suffix index parsing."""
        p_dup = parse_filename("Inception.en.2.srt")
        self.assertEqual(p_dup.lang, "en")
        self.assertEqual(p_dup.suffix_index, 2)

        p_forced_dup = parse_filename("Inception.en.forced.3.srt")
        self.assertEqual(p_forced_dup.lang, "en")
        self.assertTrue(p_forced_dup.is_forced)
        self.assertEqual(p_forced_dup.suffix_index, 3)

    def test_format_filename_tag(self):
        """Test formatting of standard destination subtitle tag."""
        p_en = parse_filename("Movie.en.srt")
        self.assertEqual(format_filename_tag(p_en), ".en")

        p_hi = parse_filename("Movie.en.hi.srt")
        self.assertEqual(format_filename_tag(p_hi), ".en.hi")

        p_forced = parse_filename("Movie.en.forced.srt")
        self.assertEqual(format_filename_tag(p_forced), ".en.forced")

        p_dup = parse_filename("Movie.en.2.srt")
        self.assertEqual(format_filename_tag(p_dup), ".en.2")

        p_forced_dup = parse_filename("Movie.en.forced.3.srt")
        self.assertEqual(format_filename_tag(p_forced_dup), ".en.forced.3")

        p_und = parse_filename("random_sub.srt")
        self.assertEqual(format_filename_tag(p_und), "")

    def test_display_label(self):
        """Test clean user-facing subtitle label generation."""
        self.assertEqual(display_label(parse_filename("Movie.en.srt")), "English")
        self.assertEqual(display_label(parse_filename("Movie.en.forced.srt")), "English (Forced)")
        self.assertEqual(display_label(parse_filename("Movie.en.hi.srt")), "English (HI)")
        self.assertEqual(display_label(parse_filename("Movie.en.2.srt")), "English (2)")
        self.assertEqual(display_label(parse_filename("Movie.en.forced.3.srt")), "English (Forced) (3)")
        self.assertEqual(display_label(parse_filename("Anime.tl.srt")), "Tagalog")

        # Unknown language gracefully falls back to clean stem without crashing
        raw_label = display_label(parse_filename("Director.Commentary.Track.srt"))
        self.assertEqual(raw_label, "Director Commentary Track")


if __name__ == "__main__":
    unittest.main()
