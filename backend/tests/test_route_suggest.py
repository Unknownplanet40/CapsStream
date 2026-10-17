# -*- coding: utf-8 -*-
"""
Tests for Media Suggestion & Random Pick Route Endpoints (backend/routes/media.py)
Validates /api/media/suggest and /api/media/random filtering by mood, type, unwatched status,
active kids profile, and ID exclusion for rerolls.
"""
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.media import media_bp


class TestRouteSuggest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_suggest_secret"
        self.app.register_blueprint(media_bp)
        self.client = self.app.test_client()

    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_basic(self, mock_get_shows):
        """Verify GET /api/media/suggest returns randomized items."""
        mock_get_shows.return_value = [
            {"id": 1, "title": "Inception", "type": "movie", "genres": "Action, Sci-Fi", "rating": 8.8},
            {"id": 2, "title": "The Office", "type": "series", "genres": "Comedy", "rating": 8.9},
        ]

        resp = self.client.get("/api/media/suggest?limit=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 2)
        titles = {item["title"] for item in data}
        self.assertEqual(titles, {"Inception", "The Office"})

    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_alias_random(self, mock_get_shows):
        """Verify /api/media/random works as an alias to /api/media/suggest."""
        mock_get_shows.return_value = [
            {"id": 1, "title": "Interstellar", "type": "movie", "genres": "Sci-Fi", "rating": 8.7}
        ]

        resp = self.client.get("/api/media/random")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Interstellar")

    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_mood_filter(self, mock_get_shows):
        """Verify filtering by mood matches appropriate genres."""
        mock_get_shows.return_value = [
            {"id": 1, "title": "Superbad", "type": "movie", "genres": "Comedy", "rating": 7.6},
            {"id": 2, "title": "The Conjuring", "type": "movie", "genres": "Horror, Mystery", "rating": 7.5},
            {"id": 3, "title": "Die Hard", "type": "movie", "genres": "Action, Thriller", "rating": 8.2},
        ]

        # mood=laugh -> comedy, animation
        resp = self.client.get("/api/media/suggest?mood=laugh")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Superbad")

        # mood=thrill -> thriller, mystery, crime, horror
        resp2 = self.client.get("/api/media/suggest?mood=thrill")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        titles2 = {item["title"] for item in data2}
        self.assertEqual(titles2, {"The Conjuring", "Die Hard"})

    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_type_filter(self, mock_get_shows):
        """Verify type parameter is forwarded to get_unique_shows."""
        mock_get_shows.return_value = [
            {"id": 10, "title": "Breaking Bad", "type": "series", "genres": "Crime, Drama"}
        ]

        resp = self.client.get("/api/media/suggest?type=series")
        self.assertEqual(resp.status_code, 200)
        mock_get_shows.assert_called_with("series")
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Breaking Bad")

    @patch("backend.routes.media.current_profile", return_value=1)
    @patch("backend.routes.media.get_progress_for_media_items")
    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_unwatched_filter(self, mock_get_shows, mock_get_progress, mock_cur_profile):
        """Verify unwatched=1 filters out titles that have >= 90% progress or completed=1."""
        items = [
            {"id": 1, "title": "Watched Movie", "type": "movie"},
            {"id": 2, "title": "Partially Watched Movie", "type": "movie"},
            {"id": 3, "title": "Fresh Movie", "type": "movie"},
        ]
        mock_get_shows.return_value = items
        mock_get_progress.return_value = {
            1: {"completed": 1, "position": 7200, "duration": 7200},
            2: {"completed": 0, "position": 1000, "duration": 7200},  # ~14% watched -> kept
            3: None,  # never watched -> kept
        }

        resp = self.client.get("/api/media/suggest?unwatched=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        titles = {item["title"] for item in data}
        self.assertIn("Partially Watched Movie", titles)
        self.assertIn("Fresh Movie", titles)
        self.assertNotIn("Watched Movie", titles)

    @patch("backend.routes.media.filter_for_profile")
    @patch("backend.routes.media.active_is_kids", return_value=True)
    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_kids_mode(self, mock_get_shows, mock_is_kids, mock_filter):
        """Verify Kids mode filtering is enforced."""
        mock_get_shows.return_value = [
            {"id": 1, "title": "Deadpool", "certification": "R"},
            {"id": 2, "title": "Toy Story", "certification": "G"},
        ]
        mock_filter.return_value = [{"id": 2, "title": "Toy Story", "certification": "G"}]

        resp = self.client.get("/api/media/suggest")
        self.assertEqual(resp.status_code, 200)
        mock_filter.assert_called_once()
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Toy Story")

    @patch("backend.routes.media.get_unique_shows")
    def test_api_suggest_exclude_id(self, mock_get_shows):
        """Verify exclude_id excludes previously rolled items when alternatives exist."""
        mock_get_shows.return_value = [
            {"id": 1, "tmdb_id": 100, "title": "First Movie"},
            {"id": 2, "tmdb_id": 200, "title": "Second Movie"},
        ]

        resp = self.client.get("/api/media/suggest?exclude_id=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Second Movie")


if __name__ == "__main__":
    unittest.main()
