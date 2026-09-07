# -*- coding: utf-8 -*-
"""
Tests for Media Matcher Module (backend/matcher.py)
Covers filename cleaning, release tag stripping, IMDb ID extraction,
and TMDb search query formatting.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from backend.matcher import _clean_name, search_tmdb


class TestMediaMatcher(unittest.TestCase):
    def test_clean_name_movie_patterns(self):
        """Verify movie titles, release years, and IMDb IDs are cleanly extracted from release strings."""
        test_cases = [
            ("Inception.2010.1080p.BluRay.x264-SPARKS.mp4", "Inception", 2010, None),
            ("The.Dark.Knight.2008.2160p.UHD.HDR.HEVC.mkv", "The Dark Knight", 2008, None),
            ("Interstellar (2014) [1080p] [AAC 5.1].mp4", "Interstellar", 2014, None),
            ("Spider-Man.No.Way.Home.2021.tt10872600.720p.mkv", "Spider Man No Way Home", 2021, "tt10872600"),
        ]

        for fname, expected_title, expected_year, expected_imdb in test_cases:
            title, year, imdb_id = _clean_name(fname)
            self.assertEqual(title.lower(), expected_title.lower(), f"Title mismatch for {fname}")
            self.assertEqual(year, expected_year, f"Year mismatch for {fname}")
            if expected_imdb:
                self.assertEqual(imdb_id, expected_imdb, f"IMDb ID mismatch for {fname}")

    def test_clean_name_strips_scene_tags(self):
        """Verify codecs, resolutions, audio formats, and release groups are stripped."""
        dirty_names = [
            "Avatar.The.Way.of.Water.2022.4K.HDR.Atmos.TrueHD",
            "The.Matrix.1999.Remastered.1080p.HEVC.x265",
            "Fight.Club.1999.Directors.Cut.720p.BrRip.AAC",
        ]

        for name in dirty_names:
            title, year, _ = _clean_name(name)
            self.assertNotIn("1080p", title.lower())
            self.assertNotIn("4k", title.lower())
            self.assertNotIn("hevc", title.lower())
            self.assertNotIn("bluray", title.lower())

    def test_search_tmdb_mocked(self):
        """Verify search_tmdb queries TMDb API and formats results."""
        with patch("backend.matcher._tmdb_get") as mock_get:
            mock_get.return_value = {
                "results": [
                    {
                        "id": 27205,
                        "title": "Inception",
                        "release_date": "2010-07-15",
                        "vote_average": 8.4,
                        "overview": "Cobb, a skilled thief...",
                        "poster_path": "/inception_poster.jpg",
                    }
                ]
            }

            results = search_tmdb(query="Inception", media_type="movie")
            self.assertIsNotNone(results)
            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0]["title"], "Inception")
            self.assertEqual(results[0]["tmdb_id"], 27205)

    def test_search_tmdb_series_and_anime(self):
        """Verify search_tmdb properly routes series and anime queries to search/tv without dropping candidates."""
        with patch("backend.matcher._tmdb_get") as mock_get:
            mock_get.return_value = {
                "results": [
                    {
                        "id": 1396,
                        "name": "Breaking Bad",
                        "first_air_date": "2008-01-20",
                        "vote_average": 8.9,
                        "overview": "A chemistry teacher diagnosed with lung cancer...",
                        "poster_path": "/breaking_bad.jpg",
                    }
                ]
            }

            # Series test
            results_series = search_tmdb(query="Breaking Bad", media_type="series")
            mock_get.assert_called_with("search/tv", {"query": "Breaking Bad", "language": "en-US"})
            self.assertEqual(len(results_series), 1)
            self.assertEqual(results_series[0]["title"], "Breaking Bad")
            self.assertEqual(results_series[0]["tmdb_id"], 1396)
            self.assertEqual(results_series[0]["media_type"], "series")

            # Anime test
            results_anime = search_tmdb(query="Solo Leveling", media_type="anime")
            self.assertEqual(len(results_anime), 1)
            self.assertEqual(results_anime[0]["media_type"], "anime")

    def test_search_tmdb_imdb_id(self):
        """Verify search_tmdb supports direct IMDb ID searches via find/ endpoint."""
        with patch("backend.matcher._tmdb_get") as mock_get:
            mock_get.return_value = {
                "tv_results": [
                    {
                        "id": 1396,
                        "name": "Breaking Bad",
                        "first_air_date": "2008-01-20",
                        "vote_average": 8.9,
                        "overview": "A high school chemistry teacher...",
                        "poster_path": "/bb.jpg"
                    }
                ],
                "movie_results": []
            }
            results = search_tmdb(query="tt0903747", media_type="series")
            mock_get.assert_called_with("find/tt0903747", {"external_source": "imdb_id"})
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["tmdb_id"], 1396)

    def test_search_tmdb_numeric_id(self):
        """Verify search_tmdb supports direct numeric TMDb ID lookup."""
        with patch("backend.matcher._tmdb_get") as mock_get:
            mock_get.return_value = {
                "id": 1396,
                "name": "Breaking Bad",
                "first_air_date": "2008-01-20",
                "vote_average": 8.9,
                "overview": "A high school chemistry teacher...",
                "poster_path": "/bb.jpg"
            }
            results = search_tmdb(query="1396", media_type="series")
            mock_get.assert_called_with("tv/1396", {"language": "en-US"})
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["tmdb_id"], 1396)


if __name__ == "__main__":
    unittest.main()
