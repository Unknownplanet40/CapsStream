# -*- coding: utf-8 -*-
"""
Tests for Missing Artwork & Re-cache Manager
Covers:
- get_media_needing_recache() logic (missing poster/backdrop detection)
- Title-level grouping across multiple episodes
- Drive mounted/unmounted status reflection
- GET /api/media/needs-recache route endpoint
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

if "app" not in sys.modules:
    mock_app_module = MagicMock()
    mock_app_module._get_api_health.return_value = {}
    mock_app_module._get_github_profile.return_value = {}
    sys.modules["app"] = mock_app_module

from backend.db.media import get_media_needing_recache
from backend.routes.media import media_bp


class TestRecacheManager(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_recache_secret"
        self.app.register_blueprint(media_bp)
        self.client = self.app.test_client()

    @patch("backend.db.media.os.path.isfile")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.media.get_conn")
    def test_get_media_needing_recache_detects_missing_artwork(self, mock_conn, mock_mounted, mock_isfile):
        """Verify items with missing poster/backdrop files on disk are returned."""
        fake_rows = [
            {
                "id": 1,
                "tmdb_id": 100,
                "title": "Movie One",
                "original_title": "Movie One",
                "year": 2024,
                "type": "movie",
                "file_path": "D:\\Movies\\Movie1.mp4",
                "file_size": 1024,
                "poster_path": "images/w500_p1.jpg",
                "backdrop_path": "images/original_b1.jpg",
                "season": None,
                "episode": None,
            },
            {
                "id": 2,
                "tmdb_id": 200,
                "title": "Movie Two (Cached)",
                "original_title": "Movie Two",
                "year": 2023,
                "type": "movie",
                "file_path": "D:\\Movies\\Movie2.mp4",
                "file_size": 2048,
                "poster_path": "images/w500_p2.jpg",
                "backdrop_path": "images/original_b2.jpg",
                "season": None,
                "episode": None,
            }
        ]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_rows
        mock_conn.return_value.execute.return_value = mock_cursor

        # Movie 1 poster missing on disk; Movie 2 files both exist
        def fake_isfile(path):
            if "p1.jpg" in path:
                return False
            return True

        mock_isfile.side_effect = fake_isfile
        mock_mounted.return_value = True

        results = get_media_needing_recache()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tmdb_id"], 100)
        self.assertEqual(results[0]["title"], "Movie One")
        self.assertTrue(results[0]["missing_poster"])
        self.assertFalse(results[0]["missing_backdrop"])
        self.assertTrue(results[0]["is_mounted"])

    @patch("backend.db.media.os.path.isfile")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.media.get_conn")
    def test_get_media_needing_recache_groups_series_episodes(self, mock_conn, mock_mounted, mock_isfile):
        """Verify multiple episodes of a show are grouped into 1 entry with total file count."""
        fake_rows = [
            {
                "id": 10,
                "tmdb_id": 500,
                "title": "Awesome Show",
                "original_title": "Awesome Show",
                "year": 2022,
                "type": "series",
                "file_path": "E:\\Series\\Show\\S01E01.mkv",
                "file_size": 500,
                "poster_path": None,
                "backdrop_path": None,
                "season": 1,
                "episode": 1,
            },
            {
                "id": 11,
                "tmdb_id": 500,
                "title": "Awesome Show",
                "original_title": "Awesome Show",
                "year": 2022,
                "type": "series",
                "file_path": "E:\\Series\\Show\\S01E02.mkv",
                "file_size": 600,
                "poster_path": None,
                "backdrop_path": None,
                "season": 1,
                "episode": 2,
            }
        ]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_rows
        mock_conn.return_value.execute.return_value = mock_cursor
        mock_isfile.return_value = False
        mock_mounted.return_value = False  # Drive E: offline

        results = get_media_needing_recache()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tmdb_id"], 500)
        self.assertEqual(results[0]["file_count"], 2)
        self.assertEqual(results[0]["file_size"], 1100)
        self.assertFalse(results[0]["is_mounted"])
        self.assertTrue(results[0]["missing_poster"])
        self.assertTrue(results[0]["missing_backdrop"])

    @patch("backend.routes.media.require_admin")
    @patch("backend.routes.media.get_media_needing_recache")
    def test_api_media_needs_recache_endpoint(self, mock_get_recache, mock_admin):
        """Verify GET /api/media/needs-recache returns list of items needing re-cache."""
        mock_admin.return_value = None
        mock_get_recache.return_value = [
            {"id": 1, "tmdb_id": 123, "title": "Inception", "type": "movie", "is_mounted": True}
        ]

        resp = self.client.get("/api/media/needs-recache")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Inception")


if __name__ == "__main__":
    unittest.main()
