# -*- coding: utf-8 -*-
"""
Tests for Admin Route Endpoints (backend/routes/admin.py)
Covers settings retrieval, test-api endpoint, system cache stats, and health checks.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

if "backend.scanner" not in sys.modules:
    sys.modules["backend.scanner"] = MagicMock()
if "app" not in sys.modules:
    mock_app_module = MagicMock()
    mock_app_module._get_api_health.return_value = {}
    mock_app_module._get_github_profile.return_value = {}
    sys.modules["app"] = mock_app_module

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
    @patch("backend.scanner.get_scan_status", create=True, return_value={"running": True, "phase": "scanning"})
    def test_api_scan_authorized_with_profile(self, mock_status, mock_has_active, mock_prof):
        """Verify POST /api/scan succeeds when a live profile session is active."""
        resp = self.client.post("/api/scan", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])

    @patch("backend.routes.admin.require_admin")
    @patch("backend.settings.reset_application")
    def test_api_system_reset(self, mock_reset, mock_admin):
        """Verify POST /api/system/reset executes reset_application and clears session."""
        mock_reset.return_value = True
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1
        resp = self.client.post("/api/system/reset", json={"clear_media_files": False})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        mock_reset.assert_called_once_with(clear_media_files=False)

    @patch("backend.updater.get_release_changelog")
    def test_api_system_changelog(self, mock_get_changelog):
        """Verify GET /api/system/changelog returns version changelog data."""
        mock_get_changelog.return_value = {
            "version": "2.25.0.0",
            "title": "CapsStream v2.25.0.0",
            "body": "## Added\n- Feature X",
            "published_at": None,
            "html_url": "https://github.com/repo"
        }
        resp = self.client.get("/api/system/changelog?version=2.25.0.0")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["version"], "2.25.0.0")
        self.assertIn("Feature X", data["body"])

    def test_system_backup_status(self):
        res = self.client.get("/api/system/backup/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("has_autobackup", data)
        self.assertIn("count", data)
        self.assertIn("backups", data)

    @patch("backend.utils.network.get_device_ip", return_value="192.168.1.55")
    @patch("backend.utils.network.get_all_device_ips", return_value=["192.168.1.55"])
    def test_system_info_device_ip(self, mock_all_ips, mock_ip):
        """Verify GET /api/system/info returns device_ip, all_device_ips, and device_url."""
        res = self.client.get("/api/system/info")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("device_ip"), "192.168.1.55")
        self.assertEqual(data.get("all_device_ips"), ["192.168.1.55"])
        self.assertIn("192.168.1.55", data.get("device_url", ""))


    @patch("backend.routes.admin.is_dev_mode", return_value=True)
    def test_check_update_dev_mode(self, mock_dev):
        """Verify GET /api/system/check-update is disabled in development mode."""
        res = self.client.get("/api/system/check-update")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "disabled")
        self.assertTrue(data.get("disabled"))
        self.assertIn("development mode", data.get("message", "").lower())

    @patch("backend.routes.admin.require_admin")
    @patch("backend.routes.admin.is_dev_mode", return_value=True)
    def test_apply_update_dev_mode(self, mock_dev, mock_admin):
        """Verify POST /api/system/apply-update returns 403 in development mode."""
        res = self.client.post("/api/system/apply-update", json={"download_url": "https://example.com/test.zip"})
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("development mode", data.get("message", "").lower())

    @patch("backend.routes.admin.is_dev_mode", return_value=False)
    @patch("backend.updater.check_for_update")
    def test_check_update_non_dev(self, mock_check, mock_dev):
        """Verify GET /api/system/check-update runs updater when not in dev mode."""
        mock_check.return_value = {"status": "available", "latest": "2.99.0.0"}
        res = self.client.get("/api/system/check-update")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "available")
        self.assertEqual(data.get("latest"), "2.99.0.0")


if __name__ == "__main__":
    unittest.main()


