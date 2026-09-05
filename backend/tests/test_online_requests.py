# -*- coding: utf-8 -*-
"""
Tests for Online Media Request System & Supabase Integration.
Covers:
- Client ID persistence & isolation
- DEV mode vs Client mode query scoping
- Remote sync and auto-completion pushing
- Status transitions (pending, in_progress, completed, rejected)
- Admin response notes
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

from backend.routes.requests import requests_bp, sync_online_requests
from backend.utils.paths import get_client_id
import backend.utils.supabase_client as sb_client


class TestOnlineRequests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = os.path.join(self.temp_dir.name, "requests.json")
        self.client_id_file = os.path.join(self.temp_dir.name, "client_id")

        self.app = Flask(__name__)
        self.app.secret_key = "test_online_secret"
        self.app.register_blueprint(requests_bp)
        self.client = self.app.test_client()

        self.file_patcher = patch("backend.routes.requests.REQUESTS_FILE", self.test_file)
        self.file_patcher.start()

        self.cid_patcher = patch("backend.utils.paths.CLIENT_ID_FILE", self.client_id_file)
        self.cid_patcher.start()

        self.config_patcher = patch("backend.settings.load_config", return_value={"features": {"requests": True}})
        self.config_patcher.start()

    def tearDown(self):
        self.file_patcher.stop()
        self.cid_patcher.stop()
        self.config_patcher.stop()
        self.temp_dir.cleanup()

    def test_client_id_generation_and_persistence(self):
        """get_client_id generates a persistent UUID and saves it to disk."""
        cid1 = get_client_id()
        self.assertTrue(len(cid1) >= 32)
        self.assertTrue(os.path.isfile(self.client_id_file))

        # Second call returns identical client ID
        cid2 = get_client_id()
        self.assertEqual(cid1, cid2)

    @patch("backend.utils.supabase_client._make_request")
    def test_test_supabase_connection_success(self, mock_req):
        """test_supabase_connection returns True when table is accessible."""
        mock_req.return_value = (200, [{"id": "test_1"}])
        ok, msg = sb_client.test_supabase_connection("https://demo.supabase.co", "test-anon-key")
        self.assertTrue(ok)
        self.assertIn("successful", msg.lower())

    @patch("backend.utils.supabase_client._make_request")
    def test_test_supabase_connection_table_missing(self, mock_req):
        """test_supabase_connection returns helpful notice when media_requests table missing."""
        mock_req.return_value = (404, "Table not found")
        ok, msg = sb_client.test_supabase_connection("https://demo.supabase.co", "test-anon-key")
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    @patch("backend.routes.requests.is_supabase_configured", return_value=True)
    @patch("backend.routes.requests.fetch_online_requests")
    @patch("backend.routes.requests.is_dev_mode", return_value=False)
    def test_desktop2_client_sees_only_own_requests(self, mock_dev, mock_fetch, mock_sb_cfg):
        """Desktop 2 (Client mode) filters requests so it only receives its own."""
        my_cid = get_client_id()
        other_cid = "some-other-client-uuid-999"

        # Mock Supabase returning two requests from different clients
        mock_fetch.return_value = [
            {"id": "req_mine", "title": "My Movie", "client_id": my_cid, "status": "pending", "created_at": "2026-09-01"},
            {"id": "req_other", "title": "Other Person Movie", "client_id": other_cid, "status": "pending", "created_at": "2026-09-02"}
        ]

        resp = self.client.get("/api/requests")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        reqs = data["requests"]

        # Desktop 2 should ONLY see its own request
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["id"], "req_mine")
        self.assertEqual(reqs[0]["client_id"], my_cid)

    @patch("backend.routes.requests.is_supabase_configured", return_value=True)
    @patch("backend.routes.requests.fetch_online_requests")
    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    def test_desktop1_dev_sees_all_clients_requests(self, mock_dev, mock_fetch, mock_sb_cfg):
        """Desktop 1 (DEV mode) sees requests from all client devices."""
        mock_fetch.return_value = [
            {"id": "req_client_a", "title": "Movie A", "client_id": "client-a", "status": "pending", "created_at": "2026-09-01"},
            {"id": "req_client_b", "title": "Show B", "client_id": "client-b", "status": "in_progress", "created_at": "2026-09-02"}
        ]

        resp = self.client.get("/api/requests")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        reqs = data["requests"]

        # Desktop 1 sees all requests
        self.assertEqual(len(reqs), 2)
        self.assertTrue(data["dev_mode"])

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    @patch("backend.routes.requests.is_supabase_configured", return_value=True)
    @patch("backend.routes.requests.update_online_request")
    def test_dev_mode_status_lifecycle_and_admin_notes(self, mock_update_online, mock_sb_cfg, mock_dev):
        """Desktop 1 (DEV mode) can set in_progress, rejected, completed, and add admin notes."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{
                "id": "req_lifecycle",
                "title": "Oppenheimer",
                "status": "pending",
                "client_id": "client-xyz"
            }], f)

        # 1. Update status to in_progress with an admin note
        resp = self.client.patch("/api/requests/req_lifecycle", json={
            "status": "in_progress",
            "admin_note": "Currently downloading remux in 4K HDR."
        })
        self.assertEqual(resp.status_code, 200)
        req = resp.get_json()["request"]
        self.assertEqual(req["status"], "in_progress")
        self.assertEqual(req["admin_note"], "Currently downloading remux in 4K HDR.")

        # 2. Update status to rejected
        resp = self.client.patch("/api/requests/req_lifecycle", json={
            "status": "rejected",
            "admin_note": "Not released on digital yet until next year."
        })
        self.assertEqual(resp.status_code, 200)
        req = resp.get_json()["request"]
        self.assertEqual(req["status"], "rejected")
        self.assertEqual(req["admin_note"], "Not released on digital yet until next year.")

        # Verify update was pushed to Supabase
        self.assertTrue(mock_update_online.called)

    @patch("backend.routes.requests.is_dev_mode", return_value=False)
    def test_client_cannot_change_status_or_admin_note(self, mock_dev):
        """Desktop 2 (Client mode) cannot alter status or inject admin notes."""
        my_cid = get_client_id()
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump([{
                "id": "req_client_mod",
                "title": "Gladiator II",
                "status": "pending",
                "client_id": my_cid
            }], f)

        # Attempt to set status to completed
        resp = self.client.patch("/api/requests/req_client_mod", json={"status": "completed"})
        self.assertEqual(resp.status_code, 403)

        # Attempt to set admin_note
        resp = self.client.patch("/api/requests/req_client_mod", json={"admin_note": "Hacked note"})
        self.assertEqual(resp.status_code, 403)

    @patch("backend.routes.requests.is_dev_mode", return_value=True)
    @patch("backend.routes.requests.is_supabase_configured", return_value=True)
    @patch("backend.routes.requests.update_online_request")
    @patch("backend.routes.requests.detect_media_in_library")
    @patch("backend.routes.requests.fetch_online_requests")
    def test_desktop1_auto_detects_and_pushes_to_supabase(self, mock_fetch, mock_detect, mock_update_sb, mock_sb_cfg, mock_dev):
        """When Desktop 1 syncs, newly added library files auto-complete requests and push to Supabase."""
        mock_fetch.return_value = [{
            "id": "req_online_detect",
            "title": "Inception",
            "type": "Movie",
            "status": "pending",
            "client_id": "client-desktop2"
        }]

        mock_detect.return_value = {
            "id": 101,
            "type": "movie",
            "title": "Inception",
            "year": 2010,
            "tmdb_id": 27205
        }

        resp = self.client.post("/api/requests/sync-online")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["detected_count"], 1)

        req = data["requests"][0]
        self.assertEqual(req["status"], "completed")
        self.assertEqual(req["detected_media_id"], 101)
        self.assertTrue(mock_update_sb.called)


if __name__ == "__main__":
    unittest.main()
