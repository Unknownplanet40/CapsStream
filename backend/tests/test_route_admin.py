# -*- coding: utf-8 -*-
"""
Tests for Admin Route Endpoints (backend/routes/admin.py)
Covers settings retrieval, test-api endpoint, system cache stats, and health checks.
"""
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.admin import admin_bp
from backend.routes.middleware import has_active_profile_session


class TestRouteAdmin(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_admin_secret"
        self.app.config["BASE_DIR"] = "/dummy/base"
        self.app.register_blueprint(admin_bp)
        self.client = self.app.test_client()

    def test_api_health(self):
        """Verify GET /api/health returns 200 OK with status ok."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})

    @patch("backend.settings.load_config")
    def test_api_get_settings(self, mock_load):
        """Verify GET /api/settings returns loaded config."""
        mock_load.return_value = {"port": 8000, "browser": "edge"}

        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["port"], 8000)

    @patch("backend.routes.admin.require_admin")
    @patch("backend.settings.test_api_key")
    def test_api_test_api_key(self, mock_test_key, mock_admin):
        """Verify POST /api/settings/test-api verifies API credentials."""
        mock_test_key.return_value = (True, "API Key is valid!")

        resp = self.client.post("/api/settings/test-api", json={"provider": "tmdb", "key": "valid_key"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("valid", data["message"])

    @patch("backend.settings.get_cache_info")
    def test_api_cache_info(self, mock_cache_info):
        """Verify GET /api/system/cache returns disk cache metrics."""
        mock_cache_info.return_value = {"total_size_bytes": 1048576, "items": 42}

        resp = self.client.get("/api/system/cache")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["items"], 42)

    @patch("backend.routes.admin.current_profile", return_value=None)
    @patch("backend.routes.admin.is_admin", return_value=False)
    def test_api_scan_unauthorized_without_profile(self, mock_admin, mock_prof):
        """Verify POST /api/scan returns 401 when no profile is selected and not admin."""
        resp = self.client.post("/api/scan", json={})
        self.assertEqual(resp.status_code, 401)

    @patch("backend.routes.admin.current_profile", return_value=1)
    @patch("backend.routes.admin.has_active_profile_session", return_value=True)
    @patch("backend.scanner.get_scan_status", return_value={"running": True, "phase": "scanning"})
    def test_api_scan_authorized_with_profile(self, mock_status, mock_has_active, mock_prof):
        """Verify POST /api/scan succeeds when a live profile session is active."""
        resp = self.client.post("/api/scan", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])

    @patch("backend.routes.middleware.ACTIVE_PROFILE_SESSIONS", {1: {"last_seen": 9999999999, "evicted": False}})
    def test_has_active_profile_session_detects_live_session(self):
        """Scheduled scans should only run when an authenticated profile session is still active."""
        with patch("time.time", return_value=10000000000):
            self.assertTrue(has_active_profile_session(1))


if __name__ == "__main__":
    unittest.main()
