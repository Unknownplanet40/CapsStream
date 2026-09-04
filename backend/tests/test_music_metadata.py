# -*- coding: utf-8 -*-
"""Unit tests for music metadata, Cover Art Archive, and LRCLIB integration."""

import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from backend.music_metadata import (
    fetch_synced_lyrics,
    save_lyrics_file,
    search_musicbrainz_album,
    fetch_cover_art_archive,
    fetch_artist_info,
)


class TestMusicMetadata(unittest.TestCase):

    def test_fetch_synced_lyrics_empty_input(self):
        res = fetch_synced_lyrics("", "")
        self.assertFalse(res["synced"])
        self.assertIsNone(res["lyrics"])

    @patch("backend.music_metadata._http_get_json")
    def test_fetch_synced_lyrics_success(self, mock_get):
        mock_get.return_value = {
            "syncedLyrics": "[00:12.34] Test lyric line 1\n[00:15.67] Test lyric line 2",
            "plainLyrics": "Test lyric line 1\nTest lyric line 2",
        }
        res = fetch_synced_lyrics("Angeleyes", "ABBA", album="Voulez-Vous")
        self.assertTrue(res["synced"])
        self.assertEqual(res["source"], "lrclib")
        self.assertIn("Test lyric line 1", res["lyrics"])

    @patch("backend.music_metadata._http_get_json")
    def test_fetch_synced_lyrics_fallback_plain(self, mock_get):
        mock_get.return_value = {
            "syncedLyrics": None,
            "plainLyrics": "Only plain lyrics available",
        }
        res = fetch_synced_lyrics("Loverboy", "A-Wall")
        self.assertFalse(res["synced"])
        self.assertEqual(res["source"], "lrclib")
        self.assertEqual(res["lyrics"], "Only plain lyrics available")

    @patch("backend.music_metadata._http_get_json")
    def test_fetch_synced_lyrics_not_found(self, mock_get):
        mock_get.return_value = None
        res = fetch_synced_lyrics("Nonexistent Track 12345", "Unknown Artist")
        self.assertFalse(res["synced"])
        self.assertIsNone(res["lyrics"])

    def test_save_lyrics_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.music_metadata.LYRICS_DIR", tmpdir):
                path = save_lyrics_file(999, "[00:01.00] Hello World")
                self.assertIsNotNone(path)
                self.assertTrue(os.path.isfile(path))
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertEqual(content, "[00:01.00] Hello World")

    @patch("backend.music_metadata._http_get_json")
    def test_search_musicbrainz_album(self, mock_get):
        mock_get.return_value = {
            "releases": [
                {
                    "id": "12345678-abcd-ef01-2345-6789abcdef01",
                    "title": "Voulez-Vous",
                    "date": "1979-04-23",
                    "country": "SE",
                }
            ]
        }
        res = search_musicbrainz_album("Voulez-Vous", "ABBA")
        self.assertIsNotNone(res)
        self.assertEqual(res["mbid"], "12345678-abcd-ef01-2345-6789abcdef01")
        self.assertEqual(res["year"], 1979)

    def test_search_musicbrainz_unknown_album_skipped(self):
        res = search_musicbrainz_album("Unknown Album", "ABBA")
        self.assertIsNone(res)

    @patch("backend.music_metadata._http_download_image")
    def test_fetch_cover_art_archive(self, mock_dl):
        mock_dl.return_value = True
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.music_metadata.COVERS_DIR", tmpdir):
                res = fetch_cover_art_archive("12345678-abcd-ef01-2345-6789abcdef01")
                self.assertIsNotNone(res)
                self.assertTrue(res.startswith("music_covers/caa_"))

    @patch("backend.music_metadata._http_get_json")
    def test_fetch_artist_info(self, mock_get):
        mock_get.return_value = {
            "artists": [
                {
                    "strArtist": "ABBA",
                    "strBiographyEN": "ABBA were a Swedish pop group formed in Stockholm in 1972.",
                    "strArtistThumb": "https://example.com/abba.jpg",
                }
            ]
        }
        res = fetch_artist_info("ABBA")
        self.assertIsNotNone(res)
        self.assertIn("Swedish pop group", res["biography"])


if __name__ == "__main__":
    unittest.main()
