# -*- coding: utf-8 -*-
"""
Tests for Social & Stats Routes (backend/routes/social.py)
Covers profile watch stats, achievement unlocking, and network request inspector endpoints.
"""
import unittest
from unittest.mock import patch
from flask import Flask, session

from backend.routes.social import social_bp


class TestRouteSocial(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_social_secret"
        self.app.register_blueprint(social_bp)
        self.client = self.app.test_client()

    @patch("backend.db.get_profile_watch_stats")
    def test_api_get_profile_stats(self, mock_get_stats):
        """Verify GET /api/stats returns profile statistics."""
        mock_get_stats.return_value = {"total_watch_time": 3600, "items_completed": 5}

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        resp = self.client.get("/api/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["items_completed"], 5)

    @patch("backend.db.unlock_achievement")
    def test_api_unlock_achievement(self, mock_unlock):
        """Verify POST /api/achievements/unlock triggers achievement unlock logic."""
        mock_unlock.return_value = {"id": "binge_watcher", "title": "Binge Watcher"}

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        resp = self.client.post("/api/achievements/unlock", json={"achievement_id": "binge_watcher"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["unlocked"]["id"], "binge_watcher")

    @patch("backend.network_inspector.get_recorded_requests")
    def test_api_get_network_requests(self, mock_get_net):
        """Verify GET /api/system/network-requests returns recorded requests and metrics."""
        mock_get_net.return_value = {"requests": [], "summary": {"total": 0}}

        resp = self.client.get("/api/system/network-requests")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("summary", data)

    @patch("backend.network_inspector.clear_recorded_requests")
    def test_api_clear_network_requests(self, mock_clear_net):
        """Verify POST /api/system/network-requests/clear flushes buffer."""
        resp = self.client.post("/api/system/network-requests/clear")
        self.assertEqual(resp.status_code, 200)
        mock_clear_net.assert_called_once()


if __name__ == "__main__":
    unittest.main()
