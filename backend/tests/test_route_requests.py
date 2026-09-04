# -*- coding: utf-8 -*-
"""
Tests for Media Requests Routes (backend/routes/requests.py)
Covers listing, creating, status updating, deleting, DEV mode gating, and Kids guard.
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.requests import requests_bp


class TestRouteRequests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = os.path.join(self.temp_dir.name, "requests.json")

        self.app = Flask(__name__)
        self.app.secret_key = "test_requests_secret"
        self.app.register_blueprint(requests_bp)
        self.client = self.app.test_client()

        # Patch REQUESTS_FILE in backend.routes.requests
        self.file_patcher = patch("backend.routes.requests.REQUESTS_FILE", self.test_file)
        self.file_patcher.start()

    def tearDown(self):
        self.file_patcher.stop()
        self.temp_dir.cleanup()

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    def test_get_empty_requests(self, mock_dev):
        """GET /api/requests returns empty list and dev_mode flag."""
        resp = self.client.get("/api/requests")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["requests"], [])
        self.assertTrue(data["dev_mode"])

    @patch("backend.routes.requests.get_profile", return_value={"name": "Uncle Bob", "avatar": "ph-user", "is_kids": 0, "color": "#e50914"})
    @patch("backend.routes.requests.current_profile", return_value=1)
    def test_create_request_success(self, mock_pid, mock_prof):
        """POST /api/requests creates a new pending request."""
        payload = {
            "title": "Interstellar",
            "type": "Movie",
            "year": "2014",
            "notes": "4K if possible"
        }
        resp = self.client.post("/api/requests", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        req = data["request"]
        self.assertEqual(req["title"], "Interstellar")
        self.assertEqual(req["type"], "Movie")
        self.assertEqual(req["year"], "2014")
        self.assertEqual(req["notes"], "4K if possible")
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["requested_by"], "Uncle Bob")

        # Verify persisted file
        with open(self.test_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["title"], "Interstellar")

    def test_create_request_requires_title(self):
        """POST /api/requests fails if title is empty."""
        resp = self.client.post("/api/requests", json={"title": "  "})
        self.assertEqual(resp.status_code, 400)

    @patch("backend.routes.requests.get_profile", return_value={"name": "Kiddo", "is_kids": 1})
    @patch("backend.routes.requests.current_profile", return_value=2)
    def test_kids_profile_blocked(self, mock_pid, mock_prof):
        """Kids profiles are blocked with 403."""
        resp = self.client.get("/api/requests")
        self.assertEqual(resp.status_code, 403)

        resp = self.client.post("/api/requests", json={"title": "Frozen"})
        self.assertEqual(resp.status_code, 403)

    @patch("backend.routes.requests.is_dev_mode", return_value=False)
    @patch("backend.routes.requests.current_profile", return_value=1)
    def test_status_update_blocked_without_dev_mode(self, mock_pid, mock_dev):
        """Non-DEV mode cannot change fulfillment status."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{"id": "req_1", "title": "Dune", "status": "pending", "profile_id": 1}], f)

        resp = self.client.patch("/api/requests/req_1", json={"status": "completed"})
        self.assertEqual(resp.status_code, 403)

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    def test_status_update_allowed_with_dev_mode(self, mock_dev):
        """DEV mode can update status to completed."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{"id": "req_1", "title": "Dune", "status": "pending", "profile_id": 1}], f)

        resp = self.client.patch("/api/requests/req_1", json={"status": "completed"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["request"]["status"], "completed")

    @patch("backend.routes.requests.is_dev_mode", return_value=False)
    def test_delete_request_uncle_mode(self, mock_dev):
        """Uncle mode can delete pending requests but not completed ones."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "req_p", "title": "Pending Movie", "status": "pending"},
                {"id": "req_c", "title": "Completed Movie", "status": "completed"}
            ], f)

        # Pending delete succeeds
        resp = self.client.delete("/api/requests/req_p")
        self.assertEqual(resp.status_code, 200)

        # Completed delete fails in uncle mode
        resp = self.client.delete("/api/requests/req_c")
        self.assertEqual(resp.status_code, 403)

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    def test_clear_completed_dev_mode(self, mock_dev):
        """DEV mode can batch clear completed requests."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "req_1", "title": "M1", "status": "completed"},
                {"id": "req_2", "title": "M2", "status": "pending"},
                {"id": "req_3", "title": "M3", "status": "completed"}
            ], f)

        resp = self.client.post("/api/requests/clear-completed")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["removed_count"], 2)

        with open(self.test_file, "r", encoding="utf-8") as f:
            remaining = json.load(f)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["id"], "req_2")

    @patch("backend.routes.requests.get_profile", return_value={"name": "Uncle Bob", "avatar": "ph-user", "is_kids": 0})
    @patch("backend.routes.requests.current_profile", return_value=1)
    def test_create_request_with_tmdb_metadata(self, mock_pid, mock_prof):
        """POST /api/requests saves TMDb fields accurately."""
        payload = {
            "title": "Inception",
            "type": "Movie",
            "year": "2010",
            "tmdb_id": 27205,
            "poster_path": "https://image.tmdb.org/t/p/w500/edv5CZvWj09upOsy2Y6IwDhK8bt.jpg",
            "backdrop_path": "https://image.tmdb.org/t/p/original/8ZTVqvKDQ8emSGUEMjsS4yHAwrp.jpg",
            "overview": "A thief who steals corporate secrets through the use of dream-sharing technology...",
            "vote_average": 8.4,
            "notes": "Must watch in high bitrate"
        }
        resp = self.client.post("/api/requests", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["request"]
        self.assertEqual(data["tmdb_id"], 27205)
        self.assertEqual(data["poster_path"], "https://image.tmdb.org/t/p/w500/edv5CZvWj09upOsy2Y6IwDhK8bt.jpg")
        self.assertEqual(data["overview"], "A thief who steals corporate secrets through the use of dream-sharing technology...")
        self.assertEqual(data["vote_average"], 8.4)

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    def test_update_request_tmdb_metadata(self, mock_dev):
        """PATCH /api/requests/<id> can link or update TMDb metadata in DEV mode."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{"id": "req_manual", "title": "Manual Show", "type": "TV Show", "status": "pending"}], f)

        patch_payload = {
            "tmdb_id": 1396,
            "title": "Breaking Bad",
            "poster_path": "https://image.tmdb.org/t/p/w500/ggFHVNu6YYI5L9pCfO0jeijilVv.jpg",
            "overview": "A chemistry teacher diagnosed with inoperable lung cancer...",
            "vote_average": 8.9
        }
        resp = self.client.patch("/api/requests/req_manual", json=patch_payload)
        self.assertEqual(resp.status_code, 200)
        updated = resp.get_json()["request"]
        self.assertEqual(updated["title"], "Breaking Bad")
        self.assertEqual(updated["tmdb_id"], 1396)
        self.assertEqual(updated["poster_path"], "https://image.tmdb.org/t/p/w500/ggFHVNu6YYI5L9pCfO0jeijilVv.jpg")
        self.assertEqual(updated["vote_average"], 8.9)

    @patch("backend.routes.requests.detect_media_in_library")
    def test_auto_detect_library_media_on_sync(self, mock_detect):
        """POST /api/requests/sync-library auto-detects and completes pending requests."""
        mock_detect.return_value = {
            "id": 42,
            "type": "movie",
            "title": "72 HOURS",
            "year": 2026,
            "tmdb_id": 949838
        }
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{
                "id": "req_auto",
                "title": "72 HOURS",
                "type": "Movie",
                "status": "pending",
                "tmdb_id": 949838
            }], f)

        resp = self.client.post("/api/requests/sync-library")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["detected_count"], 1)
        req = data["requests"][0]
        self.assertEqual(req["status"], "completed")
        self.assertTrue(req["auto_detected"])
        self.assertEqual(req["detected_media_id"], 42)
        self.assertEqual(req["detected_media_type"], "movie")

    @patch("backend.routes.requests.detect_media_in_library")
    @patch("backend.routes.requests.get_profile", return_value={"name": "Uncle", "is_kids": 0})
    @patch("backend.routes.requests.current_profile", return_value=1)
    def test_auto_detect_on_request_creation(self, mock_pid, mock_prof, mock_detect):
        """POST /api/requests auto-completes if title already in library."""
        mock_detect.return_value = {
            "id": 99,
            "type": "series",
            "title": "Golden Scenery of Tomorrow",
            "year": 2025,
            "tmdb_id": 303257
        }
        payload = {
            "title": "Golden Scenery of Tomorrow",
            "type": "TV Show",
            "year": "2025",
            "tmdb_id": 303257
        }
        resp = self.client.post("/api/requests", json=payload)
        self.assertEqual(resp.status_code, 201)
        req = resp.get_json()["request"]
        self.assertEqual(req["status"], "completed")
        self.assertTrue(req["auto_detected"])
        self.assertEqual(req["detected_media_id"], 99)
        self.assertEqual(req["detected_media_type"], "series")


if __name__ == "__main__":
    unittest.main()

