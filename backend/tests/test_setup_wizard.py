# -*- coding: utf-8 -*-
"""
Tests for First-Run Setup Wizard Endpoints (backend/routes/admin.py)
Covers /api/setup/status, /api/setup/system-check, and /api/setup/complete.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

if "app" not in sys.modules:
    mock_app_module = MagicMock()
    mock_app_module._get_api_health.return_value = {}
    mock_app_module._get_github_profile.return_value = {}
    sys.modules["app"] = mock_app_module

from backend.routes.admin import admin_bp


class TestSetupWizardEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_setup_secret"
        self.app.config["BASE_DIR"] = "/dummy/base"
        self.app.register_blueprint(admin_bp)
        self.client = self.app.test_client()

    @patch("backend.db.profiles.get_all_profiles")
    @patch("backend.settings.load_config")
    def test_setup_status_unconfigured(self, mock_load_config, mock_profiles):
        mock_load_config.return_value = {"setup_completed": False}
        mock_profiles.return_value = []

        resp = self.client.get("/api/setup/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("setup_completed"))
        self.assertFalse(data.get("has_profiles"))

    @patch("backend.db.profiles.get_all_profiles")
    @patch("backend.settings.load_config")
    def test_setup_status_configured(self, mock_load_config, mock_profiles):
        mock_load_config.return_value = {"setup_completed": True}
        mock_profiles.return_value = [{"id": 1, "name": "Admin"}]

        resp = self.client.get("/api/setup/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("setup_completed"))
        self.assertTrue(data.get("has_profiles"))

    @patch("backend.utils.diagnostics.get_system_diagnostics")
    @patch("backend.streamer.describe_hw_encoder")
    @patch("backend.utils.paths.has_ffmpeg")
    @patch("backend.utils.paths.has_ffprobe")
    @patch("shutil.disk_usage")
    def test_setup_system_check(self, mock_disk, mock_ffprobe, mock_ffmpeg, mock_hw, mock_diag):
        mock_diag.return_value = {"ram_total_gb": 16.0, "ram_used_gb": 6.0}
        mock_hw.return_value = {"available": True, "encoder": "h264_nvenc", "hardware": True}
        mock_ffmpeg.return_value = True
        mock_ffprobe.return_value = True
        mock_disk.return_value = MagicMock(free=50 * (1024 ** 3), total=250 * (1024 ** 3))

        resp = self.client.get("/api/setup/system-check")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(data.get("cpu_cores", 0), 1)
        self.assertEqual(data.get("ram_total_gb"), 16.0)
        self.assertEqual(data.get("ram_avail_gb"), 10.0)
        self.assertEqual(data.get("disk_free_gb"), 50.0)
        self.assertTrue(data.get("ffmpeg_available"))
        self.assertTrue(data.get("ffprobe_available"))
        self.assertEqual(data.get("hw_accel", {}).get("encoder"), "h264_nvenc")

    @patch("backend.settings.save_config")
    @patch("backend.settings.load_config")
    def test_setup_complete(self, mock_load_config, mock_save_config):
        mock_load_config.return_value = {"setup_completed": False}
        mock_save_config.return_value = (True, {"setup_completed": True})

        resp = self.client.post("/api/setup/complete")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("setup_completed"))
        mock_save_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
