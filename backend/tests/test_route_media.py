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


if __name__ == "__main__":
    unittest.main()
