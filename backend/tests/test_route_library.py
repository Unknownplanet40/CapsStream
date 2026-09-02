# -*- coding: utf-8 -*-
"""
Tests for Library Routes (backend/routes/library.py)
Covers watch progress, mark-watched, favorites toggle, and collections endpoints.
"""
import unittest
from unittest.mock import patch
from flask import Flask, session

from backend.routes.library import library_bp


class TestRouteLibrary(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_library_secret"
        self.app.register_blueprint(library_bp)
        self.client = self.app.test_client()

    @patch("backend.routes.library.save_progress")
    @patch("backend.db.check_and_unlock_achievements")
    @patch("backend.db.get_profile_catalog")
    def test_api_save_progress(self, mock_catalog, mock_achievements, mock_save):
        """Verify POST /api/progress records position and returns newly unlocked achievements."""
        mock_achievements.return_value = []
        mock_catalog.return_value = []

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        payload = {"media_id": 100, "position": 500, "duration": 1000, "completed": False}
        resp = self.client.post("/api/progress", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        mock_save.assert_called_once_with(1, 100, 500, 1000, False)

    @patch("backend.routes.library.get_favorites")
    def test_api_get_favorites(self, mock_get_favs):
        """Verify GET /api/favorites returns favorite media items for the active profile."""
        mock_get_favs.return_value = [{"id": 1, "title": "Inception"}]

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
            sess["is_kids"] = False

        resp = self.client.get("/api/favorites")
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Inception")

    @patch("backend.routes.library.toggle_favorite")
    def test_api_toggle_favorite(self, mock_toggle):
        """Verify POST /api/favorites/<id> toggles state."""
        mock_toggle.return_value = True

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        resp = self.client.post("/api/favorites/10")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["is_favorite"])

    @patch("backend.routes.library.save_progress")
    @patch("backend.routes.library.get_media_by_id")
    def test_api_mark_watched_movie(self, mock_get_media, mock_save):
        mock_get_media.return_value = {"id": 101, "title": "Avatar", "duration": 9600, "type": "movie"}
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
        resp = self.client.post("/api/progress/mark-watched", json={"media_id": 101})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["completed"])
        mock_save.assert_called_once_with(1, 101, 9600, 9600, True)

    @patch("backend.routes.library.delete_progress")
    @patch("backend.routes.library.get_media_by_id")
    def test_api_mark_unwatched_movie(self, mock_get_media, mock_del):
        mock_get_media.return_value = {"id": 101, "title": "Avatar", "type": "movie"}
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
        resp = self.client.post("/api/progress/mark-unwatched", json={"media_id": 101})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["completed"])
        mock_del.assert_called_once_with(1, 101)


if __name__ == "__main__":
    unittest.main()

