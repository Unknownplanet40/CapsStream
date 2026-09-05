"""
Unit tests for TMDb digital release status detection and request persistence.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from backend.matcher import get_tmdb_digital_release_status


class TestDigitalReleaseDetection(unittest.TestCase):
    def test_movie_available_digitally(self):
        today = datetime.now(timezone.utc).date()
        past_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")

        mock_release_dates = {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 3, "release_date": f"{(today - timedelta(days=60)).strftime('%Y-%m-%d')}T00:00:00.000Z"},
                        {"type": 4, "release_date": f"{past_date}T00:00:00.000Z"},
                    ]
                }
            ]
        }
        mock_detail = {"status": "Released", "release_date": (today - timedelta(days=60)).strftime("%Y-%m-%d")}

        def fake_tmdb_get(endpoint, params=None):
            if "release_dates" in endpoint:
                return mock_release_dates
            return mock_detail

        with patch("backend.matcher._tmdb_get", side_effect=fake_tmdb_get):
            res = get_tmdb_digital_release_status(12345, media_type="movie")
            self.assertTrue(res["has_digital_release"])
            self.assertEqual(res["status_code"], "digital_available")
            self.assertEqual(res["digital_release_date"], past_date)

    def test_movie_upcoming_digital_release(self):
        today = datetime.now(timezone.utc).date()
        future_date = (today + timedelta(days=45)).strftime("%Y-%m-%d")

        mock_release_dates = {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 3, "release_date": f"{(today - timedelta(days=10)).strftime('%Y-%m-%d')}T00:00:00.000Z"},
                        {"type": 4, "release_date": f"{future_date}T00:00:00.000Z"},
                    ]
                }
            ]
        }
        mock_detail = {"status": "Released"}

        def fake_tmdb_get(endpoint, params=None):
            if "release_dates" in endpoint:
                return mock_release_dates
            return mock_detail

        with patch("backend.matcher._tmdb_get", side_effect=fake_tmdb_get):
            res = get_tmdb_digital_release_status(12345, media_type="movie")
            self.assertFalse(res["has_digital_release"])
            self.assertEqual(res["status_code"], "upcoming_digital")
            self.assertEqual(res["digital_release_date"], future_date)
            self.assertIn("Digital:", res["digital_status_label"])

    def test_movie_theatrical_only_recent(self):
        today = datetime.now(timezone.utc).date()
        recent_theatrical = (today - timedelta(days=20)).strftime("%Y-%m-%d")

        mock_release_dates = {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 3, "release_date": f"{recent_theatrical}T00:00:00.000Z"},
                    ]
                }
            ]
        }
        mock_detail = {"status": "Released"}

        def fake_tmdb_get(endpoint, params=None):
            if "release_dates" in endpoint:
                return mock_release_dates
            return mock_detail

        with patch("backend.matcher._tmdb_get", side_effect=fake_tmdb_get):
            res = get_tmdb_digital_release_status(12345, media_type="movie")
            self.assertFalse(res["has_digital_release"])
            self.assertEqual(res["status_code"], "theatrical_only")
            self.assertEqual(res["digital_status_label"], "Theatrical Only (No Digital Copy)")

    def test_movie_theatrical_older_catalog(self):
        today = datetime.now(timezone.utc).date()
        old_theatrical = (today - timedelta(days=365)).strftime("%Y-%m-%d")

        mock_release_dates = {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 3, "release_date": f"{old_theatrical}T00:00:00.000Z"},
                    ]
                }
            ]
        }
        mock_detail = {"status": "Released"}

        def fake_tmdb_get(endpoint, params=None):
            if "release_dates" in endpoint:
                return mock_release_dates
            return mock_detail

        with patch("backend.matcher._tmdb_get", side_effect=fake_tmdb_get):
            res = get_tmdb_digital_release_status(12345, media_type="movie")
            self.assertTrue(res["has_digital_release"])
            self.assertEqual(res["status_code"], "digital_available")
            self.assertIn("Likely Available", res["digital_status_label"])

    def test_movie_unreleased_in_production(self):
        mock_release_dates = {"results": []}
        mock_detail = {"status": "In Production", "release_date": ""}

        def fake_tmdb_get(endpoint, params=None):
            if "release_dates" in endpoint:
                return mock_release_dates
            return mock_detail

        with patch("backend.matcher._tmdb_get", side_effect=fake_tmdb_get):
            res = get_tmdb_digital_release_status(12345, media_type="movie")
            self.assertFalse(res["has_digital_release"])
            self.assertEqual(res["status_code"], "unaired")
            self.assertIn("Unreleased", res["digital_status_label"])

    def test_tv_show_unaired_future(self):
        today = datetime.now(timezone.utc).date()
        future_air = (today + timedelta(days=60)).strftime("%Y-%m-%d")

        mock_tv = {"first_air_date": future_air, "status": "Planned"}

        with patch("backend.matcher._tmdb_get", return_value=mock_tv):
            res = get_tmdb_digital_release_status(9999, media_type="tv")
            self.assertFalse(res["has_digital_release"])
            self.assertEqual(res["status_code"], "unaired")
            self.assertIn("Unaired", res["digital_status_label"])

    def test_tv_show_aired(self):
        today = datetime.now(timezone.utc).date()
        past_air = (today - timedelta(days=120)).strftime("%Y-%m-%d")

        mock_tv = {"first_air_date": past_air, "status": "Returning Series"}

        with patch("backend.matcher._tmdb_get", return_value=mock_tv):
            res = get_tmdb_digital_release_status(9999, media_type="tv")
            self.assertTrue(res["has_digital_release"])
            self.assertEqual(res["status_code"], "digital_available")
            self.assertEqual(res["digital_status_label"], "Aired / Streaming")


class TestDigitalReleaseRoutes(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        from flask import Flask
        from backend.routes.media import media_bp
        from backend.routes.requests import requests_bp

        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = os.path.join(self.temp_dir.name, "requests.json")

        self.app = Flask(__name__)
        self.app.secret_key = "test_secret"
        self.app.register_blueprint(media_bp)
        self.app.register_blueprint(requests_bp)
        self.client = self.app.test_client()

        self.file_patcher = patch("backend.routes.requests.REQUESTS_FILE", self.test_file)
        self.file_patcher.start()

        self.config_patcher = patch("backend.settings.load_config", return_value={"features": {"requests": True}})
        self.config_patcher.start()

    def tearDown(self):
        self.file_patcher.stop()
        self.config_patcher.stop()
        self.temp_dir.cleanup()

    def test_api_tmdb_digital_status_endpoint(self):
        mock_res = {
            "has_digital_release": False,
            "digital_status_label": "Theatrical Only (No Digital Copy)",
            "status_code": "theatrical_only",
            "digital_release_date": None,
            "theatrical_release_date": "2026-08-01",
            "raw_status": "Released"
        }
        with patch("backend.matcher.get_tmdb_digital_release_status", return_value=mock_res):
            resp = self.client.get("/api/tmdb/digital-status?id=12345&type=movie")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertFalse(data["has_digital_release"])
            self.assertEqual(data["status_code"], "theatrical_only")
            self.assertEqual(data["digital_status_label"], "Theatrical Only (No Digital Copy)")

    def test_create_request_persists_digital_release_fields(self):
        payload = {
            "title": "Upcoming Blockbuster",
            "type": "Movie",
            "year": "2026",
            "tmdb_id": 54321,
            "has_digital_release": False,
            "digital_release_date": "2026-11-20",
            "digital_status_label": "Digital: 2026-11-20"
        }
        resp = self.client.post("/api/requests", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        req_item = data.get("request")
        self.assertIsNotNone(req_item)
        self.assertFalse(req_item["has_digital_release"])
        self.assertEqual(req_item["digital_release_date"], "2026-11-20")
        self.assertEqual(req_item["digital_status_label"], "Digital: 2026-11-20")


if __name__ == "__main__":
    unittest.main()
