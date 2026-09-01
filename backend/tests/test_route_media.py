# -*- coding: utf-8 -*-
"""
Tests for Media Route Endpoints (backend/routes/media.py)
Covers media item detail, genres listing, search endpoints, home cache busting, and episode merging.
"""
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.media import media_bp, bust_home_cache, _merge_season_episodes


class TestRouteMedia(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_media_secret"
        self.app.register_blueprint(media_bp)
        self.client = self.app.test_client()
        bust_home_cache()

    def test_home_cache_busting(self):
        """Verify bust_home_cache clears cache state."""
        from backend.routes import media
        media._HOME_CACHE["data"] = {"featured": []}
        media._HOME_CACHE["ts"] = 12345.0

        bust_home_cache()
        self.assertIsNone(media._HOME_CACHE["data"])
        self.assertEqual(media._HOME_CACHE["ts"], 0.0)

    @patch("backend.routes.media.get_all_genres")
    def test_api_genres(self, mock_get_genres):
        """Verify GET /api/genres returns list of unique genres."""
        mock_get_genres.return_value = ["Action", "Comedy", "Drama"]

        resp = self.client.get("/api/genres")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 3)
        self.assertIn("Action", data)

    @patch("backend.routes.media.db_search_media")
    def test_api_search_media(self, mock_search):
        """Verify GET /api/search returns matched media query results."""
        mock_search.return_value = [{"id": 1, "title": "Inception"}]

        resp = self.client.get("/api/search?q=Inception")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Inception")

    @patch("backend.db.media.get_conn")
    @patch("backend.db.media.enrich_mounted_list", side_effect=lambda items: items)
    def test_search_media_resolution_filter(self, mock_enrich, mock_conn):
        """Verify resolution queries only surface actual 4K/HD matches instead of unrelated titles."""
        from backend.db.media import search_media

        rows = [
            {"id": 1, "title": "Movie A", "original_title": "Movie A", "genres": "Action", "cast_json": "[]", "overview": "", "file_path": "D:/Media/Movie.A.2160p.mkv", "file_size": 6 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 101},
            {"id": 2, "title": "Movie B", "original_title": "Movie B", "genres": "Action", "cast_json": "[]", "overview": "", "file_path": "D:/Media/Movie.B.1080p.mkv", "file_size": 1.5 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 102},
        ]
        mock_conn.return_value.execute.return_value.fetchall.return_value = rows

        results = search_media(query="4K")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], 1)
        self.assertEqual(results[0]["file_path"], "D:/Media/Movie.A.2160p.mkv")

    @patch("backend.db.media.get_conn")
    @patch("backend.db.media.enrich_mounted_list", side_effect=lambda items: items)
    def test_search_media_resolution_filter_includes_series(self, mock_enrich, mock_conn):
        """Verify resolution queries include series even when the file name does not explicitly contain the resolution tag."""
        from backend.db.media import search_media

        rows = [
            {"id": 1, "title": "Series A", "original_title": "Series A", "genres": "Action", "cast_json": "[]", "overview": "", "file_path": "D:/Media/Series.A.S01E01.mkv", "file_size": 0.9 * 1024 * 1024 * 1024, "type": "series", "tmdb_id": 300, "season": 1, "episode": 1},
            {"id": 2, "title": "Series A", "original_title": "Series A", "genres": "Action", "cast_json": "[]", "overview": "", "file_path": "D:/Media/Series.A.S01E02.mkv", "file_size": 2.2 * 1024 * 1024 * 1024, "type": "series", "tmdb_id": 300, "season": 1, "episode": 2},
            {"id": 3, "title": "Movie A", "original_title": "Movie A", "genres": "Action", "cast_json": "[]", "overview": "", "file_path": "D:/Media/Movie.A.2160p.mkv", "file_size": 5.5 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 100},
        ]
        mock_conn.return_value.execute.return_value.fetchall.return_value = rows

        results = search_media(query="1080p")
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any(r["tmdb_id"] == 300 for r in results))
        self.assertTrue(any(r["file_size"] >= 350 * 1024 * 1024 for r in results))

    @patch("backend.db.media.get_conn")
    @patch("backend.db.media.enrich_mounted_list", side_effect=lambda items: items)
    def test_search_media_groups_multiple_movie_qualities(self, mock_enrich, mock_conn):
        """Verify search_media groups multiple quality copies of the same movie into a single best result."""
        from backend.db.media import search_media

        rows = [
            {"id": 10, "title": "Toy Story", "original_title": "Toy Story", "genres": "Animation", "cast_json": "[]", "overview": "", "file_path": "D:/Toy Story (1995) 720p.mkv", "file_size": 1 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 862, "year": 1995, "poster_path": "/poster.jpg"},
            {"id": 11, "title": "Toy Story", "original_title": "Toy Story", "genres": "Animation", "cast_json": "[]", "overview": "", "file_path": "D:/Toy Story (1995) 1080p.mkv", "file_size": 4 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 862, "year": 1995, "poster_path": "/poster.jpg"},
            {"id": 12, "title": "Toy Story", "original_title": "Toy Story", "genres": "Animation", "cast_json": "[]", "overview": "", "file_path": "D:/Toy Story (1995) 4K.mkv", "file_size": 15 * 1024 * 1024 * 1024, "type": "movie", "tmdb_id": 862, "year": 1995, "poster_path": "/poster.jpg"},
        ]
        mock_conn.return_value.execute.return_value.fetchall.return_value = rows

        results = search_media(query="Toy Story")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], 12)
        self.assertEqual(results[0]["title"], "Toy Story")
        self.assertEqual(results[0]["file_path"], "D:/Toy Story (1995) 4K.mkv")

    @patch("backend.matcher.fetch_season_episodes")
    def test_merge_season_episodes(self, mock_fetch_tmdb):
        """Verify _merge_season_episodes integrates local files with TMDb episode metadata."""
        mock_fetch_tmdb.return_value = [
            {"episode_number": 1, "name": "Pilot", "overview": "The story begins.", "runtime": 45},
            {"episode_number": 2, "name": "Chapter 2", "overview": "Continuing story.", "runtime": 45}
        ]
        local_map = {
            (1, 1): {"id": 10, "season": 1, "episode": 1, "title": "My Show", "file_path": "/path/s01e01.mp4"}
        }

        merged = _merge_season_episodes(
            tmdb_id=500,
            s_num=1,
            local_map=local_map,
            pid=None,
            show_title="My Show"
        )
        self.assertEqual(len(merged), 2)
        # Episode 1 should be marked local
        self.assertTrue(merged[0]["is_local"])
        self.assertEqual(merged[0]["id"], 10)
        self.assertEqual(merged[0]["ep_title"], "Pilot")

        # Episode 2 is missing locally
        self.assertFalse(merged[1]["is_local"])
        self.assertIsNone(merged[1]["id"])
        self.assertEqual(merged[1]["ep_title"], "Chapter 2")

    @patch("backend.db.media.get_conn")
    def test_series_quality_options_deduplication(self, mock_conn):
        """Verify get_all_sources_for_media does NOT group distinct episodes/extras as quality options."""
        from backend.db.media import get_all_sources_for_media

        # Simulate SQLite returning 3 rows: Main Ep5, Extra NCOP 2, and OAD 5
        rows = [
            {"id": 1, "tmdb_id": 82684, "type": "anime", "season": 1, "episode": 5, "title": "Slime",
             "file_path": r"K:\Slime\Season 01\Slime - S01E05.mkv", "file_size": 200000000},
            {"id": 2, "tmdb_id": 82684, "type": "anime", "season": 1, "episode": 5, "title": "Slime",
             "file_path": r"K:\Slime\Season 01\Extras\Slime - NCOP 02.mkv", "file_size": 40000000},
            {"id": 3, "tmdb_id": 82684, "type": "anime", "season": 1, "episode": 5, "title": "Slime",
             "file_path": r"K:\Slime\Season 01\OADs\Slime - OAD 05.mkv", "file_size": 190000000},
        ]
        mock_cursor = mock_conn.return_value.execute.return_value
        mock_cursor.fetchall.return_value = rows

        target_ep5 = rows[0]
        sources = get_all_sources_for_media(target_ep5)

        # Only the main episode should remain
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["id"], 1)

    @patch("backend.db.media.get_conn")
    @patch("backend.db.media.enrich_mounted_list", side_effect=lambda items: items)
    def test_get_hero_featured_deduplication_and_backdrop_filter(self, mock_enrich, mock_conn):
        """Verify get_hero_featured only selects items with backdrops and deduplicates by show/title."""
        from backend.db.media import get_hero_featured

        rows = [
            {"id": 1, "title": "Series A", "type": "series", "tmdb_id": 100, "backdrop_path": "/backdropA.jpg", "file_path": "D:/a1.mkv"},
            {"id": 2, "title": "Series A", "type": "series", "tmdb_id": 100, "backdrop_path": "/backdropA.jpg", "file_path": "D:/a2.mkv"},
            {"id": 3, "title": "Movie B", "type": "movie", "tmdb_id": 200, "backdrop_path": "/backdropB.jpg", "file_path": "D:/b.mkv"},
        ]
        mock_conn.return_value.execute.return_value.fetchall.return_value = rows

        items = get_hero_featured(limit=10)
        self.assertEqual(len(items), 2)
        tmdb_ids = {i["tmdb_id"] for i in items}
        self.assertEqual(tmdb_ids, {100, 200})

    @patch("backend.routes.media.get_hero_featured")
    @patch("backend.routes.media.get_unique_shows")
    @patch("backend.routes.media.get_recently_added")
    @patch("backend.routes.media.get_all_genres")
    def test_api_home_includes_hero_featured_row(self, mock_genres, mock_recent, mock_shows, mock_hero):
        """Verify /api/home includes a dynamic 'Featured' hero row."""
        mock_hero.return_value = [{"id": 10, "title": "Random Movie", "backdrop_path": "/backdrop10.jpg"}]
        mock_shows.return_value = []
        mock_recent.return_value = [{"id": 1, "title": "Recent 1"}]
        mock_genres.return_value = []

        resp = self.client.get("/api/home")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]["type"], "hero")
        self.assertEqual(data[0]["title"], "Featured")
        self.assertEqual(len(data[0]["items"]), 1)
        self.assertEqual(data[0]["items"][0]["title"], "Random Movie")


    @patch("backend.matcher.fetch_season_episodes")
    @patch("backend.db.playback.get_conn")
    def test_get_continue_watching_enriches_episode_still_path(self, mock_conn, mock_fetch_eps):
        """Verify get_continue_watching enriches series/anime items with TMDB episode still_path."""
        from backend.db.playback import get_continue_watching

        mock_rows = [
            {
                "id": 101, "tmdb_id": 999, "type": "series", "title": "Breaking Code",
                "season": 1, "episode": 2, "ep_title": "Breaking Code",
                "position": 500, "duration": 3000, "completed": 0, "file_path": "C:/test/s01e02.mkv"
            }
        ]
        mock_cursor = mock_conn.return_value.execute.return_value
        mock_cursor.fetchall.return_value = mock_rows

        mock_fetch_eps.return_value = [
            {"episode_number": 1, "name": "Pilot", "still_path": "/still1.jpg"},
            {"episode_number": 2, "name": "Cat's in the Bag", "still_path": "/still2.jpg"}
        ]

        results = get_continue_watching(profile_id=1, limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["still_path"], "/still2.jpg")
        self.assertEqual(results[0]["ep_title"], "Cat's in the Bag")


if __name__ == "__main__":
    unittest.main()


