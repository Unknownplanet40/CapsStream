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


    @patch("backend.routes.library.update_collection")
    def test_api_update_collection(self, mock_update):
        """Verify PATCH /api/collections/<id> updates cover_id and metadata."""
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
        resp = self.client.patch("/api/collections/5", json={"cover_id": 42, "name": "Favorites"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("cover_id"), 42)
        mock_update.assert_called_once_with(5, 1, name="Favorites", description=None, cover_id=42)

    @patch("backend.routes.library.update_collection")
    def test_api_reset_collection_cover(self, mock_update):
        """Verify PATCH /api/collections/<id> with cover_id=None resets cover."""
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
        resp = self.client.patch("/api/collections/5", json={"cover_id": None})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsNone(data.get("cover_id"))
        mock_update.assert_called_once_with(5, 1, name=None, description=None, cover_id=None)

    @patch("backend.db.get_all_media")
    def test_api_get_universes(self, mock_get_all):
        """Verify GET /api/universes returns discovered cinematic universes."""
        mock_get_all.return_value = [
            {"id": 1, "title": "Iron Man", "type": "movie", "year": 2008, "poster_path": "/im.jpg", "backdrop_path": "/im_bg.jpg"},
            {"id": 2, "title": "Thor", "type": "movie", "year": 2011, "poster_path": "/thor.jpg", "backdrop_path": "/thor_bg.jpg"},
        ]
        resp = self.client.get("/api/universes")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        mcu = next((u for u in data if u["id"] == "universe-mcu"), None)
        self.assertIsNotNone(mcu)
        self.assertEqual(mcu["item_count"], 2)

    @patch("backend.db.get_all_media")
    def test_api_get_universe_detail(self, mock_get_all):
        """Verify GET /api/universes/<id> returns timeline items and release order items."""
        mock_get_all.return_value = [
            {"id": 1, "title": "Captain America: The First Avenger", "type": "movie", "year": 2011},
            {"id": 2, "title": "Iron Man", "type": "movie", "year": 2008},
        ]
        resp = self.client.get("/api/universes/universe-mcu")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["id"], "universe-mcu")
        self.assertTrue(data.get("has_timeline"))
        self.assertEqual(len(data["timeline_items"]), 2)
        # Chronological timeline: Captain America is #1, Iron Man is #2
        self.assertIn("Captain America", data["timeline_items"][0]["title"])

    @patch("backend.db.get_all_media")
    def test_api_get_regional_countries(self, mock_get_all):
        """Verify GET /api/regional/countries returns country collections."""
        mock_get_all.return_value = [
            {"id": 1, "title": "Hello, Love, Goodbye", "type": "movie", "year": 2019, "original_language": "tl", "file_path": "C:\\Media\\Pinoy\\hlg.mkv"},
            {"id": 2, "title": "Parasite", "type": "movie", "year": 2019, "original_language": "ko", "file_path": "C:\\Media\\Kdrama\\parasite.mkv"},
        ]
        resp = self.client.get("/api/regional/countries")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        ph = next((c for c in data if c["country_code"] == "PH"), None)
        self.assertIsNotNone(ph)

    @patch("backend.db.get_all_media")
    def test_api_get_regional_country_detail(self, mock_get_all):
        """Verify GET /api/regional/countries/<code> returns items for that country."""
        mock_get_all.return_value = [
            {"id": 1, "title": "Train to Busan", "type": "movie", "year": 2016, "original_language": "ko", "file_path": "C:\\Media\\korean\\ttb.mkv"},
        ]
        resp = self.client.get("/api/regional/countries/KR")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["country_code"], "KR")
        self.assertEqual(len(data["items"]), 1)


if __name__ == "__main__":
    unittest.main()

