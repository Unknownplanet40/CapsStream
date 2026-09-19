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

        # Patch load_config in backend.settings to enable requests by default
        self.config_patcher = patch("backend.settings.load_config", return_value={"features": {"requests": True}})
        self.config_patcher.start()

        # Isolate route unit tests from external Supabase network calls
        self.supabase_patcher = patch("backend.routes.requests.is_supabase_configured", return_value=False)
        self.supabase_patcher.start()

    def tearDown(self):
        self.supabase_patcher.stop()
        self.file_patcher.stop()
        self.config_patcher.stop()
        self.temp_dir.cleanup()

    def test_feature_disabled_returns_403(self):
        """When features.requests is False, /api/requests endpoints return 403."""
        with patch("backend.settings.load_config", return_value={"features": {"requests": False}}):
            resp = self.client.get("/api/requests")
            self.assertEqual(resp.status_code, 403)
            data = resp.get_json()
            self.assertIn("disabled", data.get("error", "").lower())

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
    @patch("backend.routes.requests.get_profile", return_value={"name": "Uncle", "is_kids": 0})
    @patch("backend.routes.requests.current_profile", return_value=1)
    def test_create_request_with_season_and_episode(self, mock_pid, mock_prof):
        """POST /api/requests saves season and episode numbers."""
        payload = {
            "title": "Arcane",
            "type": "TV Show",
            "season": 2,
            "episode": 3,
            "tmdb_id": 94605
        }
        resp = self.client.post("/api/requests", json=payload)
        self.assertEqual(resp.status_code, 201)
        req = resp.get_json()["request"]
        self.assertEqual(req["season"], 2)
        self.assertEqual(req["episode"], 3)

    @patch("backend.routes.requests.get_series_library_inventory")
    def test_series_inventory_endpoint(self, mock_inv):
        """GET /api/requests/series-inventory returns breakdown of existing seasons."""
        mock_inv.return_value = {
            "in_library": True,
            "total_episodes": 18,
            "seasons": {1: 9, 2: 9},
            "seasons_display": "Season 1 (9 eps), Season 2 (9 eps)"
        }
        resp = self.client.get("/api/requests/series-inventory?tmdb_id=94605&title=Arcane")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["inventory"]["in_library"])
        self.assertEqual(data["inventory"]["seasons"]["1"], 9)

    @patch("backend.routes.requests.ensure_request_artwork")
    def test_get_request_artwork_placeholder(self, mock_ensure):
        """GET /api/requests/artwork/<id>/poster returns fallback SVG if no image."""
        payload = {"title": "Test Artwork Movie", "type": "Movie"}
        res = self.client.post("/api/requests", json=payload)
        req_id = res.get_json()["request"]["id"]
        art_res = self.client.get(f"/api/requests/artwork/{req_id}/poster")
        self.assertEqual(art_res.status_code, 200)
        self.assertIn("image/svg+xml", art_res.content_type)

    @patch("backend.matcher._tmdb_get", return_value={"poster_path": "/test.jpg", "backdrop_path": "/bg.jpg", "overview": "TMDb overview"})
    @patch("backend.matcher._download_image", return_value="images/test.jpg")
    def test_refresh_request_artwork(self, mock_dl, mock_tmdb):
        """POST /api/requests/<id>/refresh-artwork repairs missing artwork from TMDb."""
        payload = {"title": "Test Refresh", "type": "Movie", "tmdb_id": 99999}
        res = self.client.post("/api/requests", json=payload)
        req_id = res.get_json()["request"]["id"]
        ref_res = self.client.post(f"/api/requests/{req_id}/refresh-artwork")
        self.assertEqual(ref_res.status_code, 200)
        updated = ref_res.get_json()["request"]
        self.assertIn("test.jpg", updated["poster_path"])
        self.assertIn("bg.jpg", updated["backdrop_path"])

    def test_duplicate_request_merges_different_profile(self):
        """When a different profile requests an active title, it merges requesters."""
        # Alice requests Inception
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice", "color": "#ff0000"}):
            resp1 = self.client.post("/api/requests", json={"title": "Inception", "type": "Movie", "tmdb_id": 27205})
            self.assertEqual(resp1.status_code, 201)
            req1 = resp1.get_json()["request"]
            self.assertEqual(len(req1["requesters"]), 1)
            self.assertEqual(req1["requested_by"], "Alice")

        # Bob requests the same Inception
        with patch("backend.routes.requests.current_profile", return_value=2), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Bob", "color": "#00ff00"}):
            resp2 = self.client.post("/api/requests", json={"title": "Inception", "type": "Movie", "tmdb_id": 27205})
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.get_json()
            self.assertTrue(data2.get("merged"))
            req2 = data2["request"]
            self.assertEqual(len(req2["requesters"]), 2)
            self.assertEqual(req2["requesters"][0]["requested_by"], "Alice")
            self.assertEqual(req2["requesters"][1]["requested_by"], "Bob")
            self.assertEqual(req2["requested_by"], "Alice, Bob")

        # Verify persisted file has only 1 item with 2 requesters
        with open(self.test_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
            self.assertEqual(len(persisted), 1)
            self.assertEqual(len(persisted[0]["requesters"]), 2)

    def test_duplicate_request_blocked_same_profile(self):
        """When the same profile requests an active title again, return 409 already requested."""
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice", "color": "#ff0000"}):
            resp1 = self.client.post("/api/requests", json={"title": "Inception", "type": "Movie", "tmdb_id": 27205})
            self.assertEqual(resp1.status_code, 201)

            resp2 = self.client.post("/api/requests", json={"title": "Inception", "type": "Movie", "tmdb_id": 27205})
            self.assertEqual(resp2.status_code, 409)
            data2 = resp2.get_json()
            self.assertTrue(data2.get("already_requested"))
            self.assertIn("already requested", data2.get("error", "").lower())

        with open(self.test_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
            self.assertEqual(len(persisted), 1)
            self.assertEqual(len(persisted[0]["requesters"]), 1)

    def test_toggle_me_too_join_and_leave(self):
        """Co-requesters can join with toggle-me-too and subsequently unjoin."""
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice", "color": "#ff0000"}):
            resp1 = self.client.post("/api/requests", json={"title": "Gladiator", "type": "Movie"})
            req_id = resp1.get_json()["request"]["id"]

        # Bob joins as +1
        with patch("backend.routes.requests.current_profile", return_value=2), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Bob", "color": "#00ff00"}):
            resp2 = self.client.post(f"/api/requests/{req_id}/toggle-me-too")
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.get_json()
            self.assertTrue(data2["ok"])
            self.assertTrue(data2["joined"])
            self.assertEqual(len(data2["request"]["requesters"]), 2)
            self.assertEqual(data2["request"]["requested_by"], "Alice, Bob")

            # Bob toggles again to leave
            resp3 = self.client.post(f"/api/requests/{req_id}/toggle-me-too")
            self.assertEqual(resp3.status_code, 200)
            data3 = resp3.get_json()
            self.assertTrue(data3["ok"])
            self.assertFalse(data3["joined"])
            self.assertEqual(len(data3["request"]["requesters"]), 1)
            self.assertEqual(data3["request"]["requested_by"], "Alice")

    def test_toggle_me_too_sole_requester_cannot_leave(self):
        """Primary/sole requester cannot leave their own request via toggle."""
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice", "color": "#ff0000"}):
            resp1 = self.client.post("/api/requests", json={"title": "Gladiator", "type": "Movie"})
            req_id = resp1.get_json()["request"]["id"]

            resp2 = self.client.post(f"/api/requests/{req_id}/toggle-me-too")
            self.assertEqual(resp2.status_code, 400)
            self.assertIn("original requester", resp2.get_json().get("error", "").lower())

    def test_toggle_me_too_not_found_or_inactive(self):
        """Toggle returns 404 for unknown request and 400 for completed/rejected."""
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice"}):
            resp_404 = self.client.post("/api/requests/non-existent-id/toggle-me-too")
            self.assertEqual(resp_404.status_code, 404)

            # Create request then patch it to completed
            res = self.client.post("/api/requests", json={"title": "Completed Movie", "type": "Movie"})
            req_id = res.get_json()["request"]["id"]
            with patch("backend.routes.requests.is_dev_mode", return_value=True):
                self.client.patch(f"/api/requests/{req_id}", json={"status": "completed"})

            resp_inactive = self.client.post(f"/api/requests/{req_id}/toggle-me-too")
            self.assertEqual(resp_inactive.status_code, 400)

    def test_requests_enrich_local_library_presence(self):
        """Requests returned by API should include in_local_library, local_media_id, local_media_type, local_tmdb_id."""
        with patch("backend.routes.requests.current_profile", return_value=1), \
             patch("backend.routes.requests.get_profile", return_value={"name": "Alice"}):
            resp = self.client.post("/api/requests", json={"title": "Local Playable Movie", "type": "Movie"})
            self.assertEqual(resp.status_code, 201)
            req_id = resp.get_json()["request"]["id"]

        # When detect_media_in_library finds nothing (remote/unmatched client)
        with patch("backend.routes.requests.detect_media_in_library", return_value=None):
            get_resp = self.client.get("/api/requests")
            self.assertEqual(get_resp.status_code, 200)
            items = get_resp.get_json()["requests"]
            item = next(i for i in items if i["id"] == req_id)
            self.assertFalse(item["in_local_library"])
            self.assertIsNone(item["local_media_id"])

        # When detect_media_in_library finds media on this local machine
        with patch("backend.routes.requests.detect_media_in_library", return_value={"id": 99, "type": "movie", "tmdb_id": 12345}):
            get_resp = self.client.get("/api/requests")
            self.assertEqual(get_resp.status_code, 200)
            items = get_resp.get_json()["requests"]
            item = next(i for i in items if i["id"] == req_id)
            self.assertTrue(item["in_local_library"])
            self.assertEqual(item["local_media_id"], 99)
            self.assertEqual(item["local_media_type"], "movie")
            self.assertEqual(item["local_tmdb_id"], 12345)


if __name__ == "__main__":
    unittest.main()


