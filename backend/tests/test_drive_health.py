# -*- coding: utf-8 -*-
"""
Tests for Drive Health and Offline Media Detection
Covers:
- get_drive_identifier and enrich_mounted
- GET /api/system/drives-status endpoint
- GET /api/stream/<media_id> returns 503 drive_offline when drive is unmounted
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

from backend.db.media import get_drive_identifier, enrich_mounted, is_drive_mounted
from backend.routes.admin import admin_bp
from backend.routes.streaming import streaming_bp


class TestDriveHealth(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_drive_health_secret"
        self.app.config["BASE_DIR"] = "/dummy/base"
        self.app.register_blueprint(admin_bp)
        self.app.register_blueprint(streaming_bp)
        self.client = self.app.test_client()

    def test_get_drive_identifier(self):
        """Verify drive identifier extraction on Windows and POSIX paths."""
        self.assertEqual(get_drive_identifier("D:\\Movies\\Film.mp4"), "D:")
        self.assertEqual(get_drive_identifier("e:/anime/show.mkv"), "E:")
        self.assertEqual(get_drive_identifier("/mnt/storage/movies/film.mp4"), "/mnt/storage")
        self.assertEqual(get_drive_identifier(""), "")

    def test_enrich_mounted_populates_drive_letter(self):
        """Verify enrich_mounted attaches both is_mounted and drive_letter."""
        item = {"file_path": "X:\\Movies\\Alien.mkv"}
        with patch("backend.db.media.is_drive_mounted", return_value=False):
            enriched = enrich_mounted(item)
            self.assertFalse(enriched["is_mounted"])
            self.assertEqual(enriched["drive_letter"], "X:")

    @patch("backend.settings.load_config")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.get_conn")
    @patch("shutil.disk_usage")
    def test_api_system_drives_status(self, mock_usage, mock_get_conn, mock_is_mounted, mock_cfg):
        """Verify GET /api/system/drives-status returns drive status list and offline flag."""
        mock_cfg.return_value = {
            "media_paths": {
                "movies": ["D:\\Movies"],
                "series": ["E:\\Series"],
                "anime": []
            },
            "disabled_paths": {}
        }
        # D: is mounted, E: is unmounted
        mock_is_mounted.side_effect = lambda p: "D:" in str(p)
        mock_usage.return_value = MagicMock(total=1000 * 1024**3, used=600 * 1024**3, free=400 * 1024**3)
        mock_conn = MagicMock()
        mock_conn.execute.return_value = iter([
            {"file_path": "D:\\Movies\\Film1.mp4", "type": "movie"},
            {"file_path": "E:\\Series\\Ep1.mkv", "type": "series"},
            {"file_path": "X:\\Unconfigured\\Old.mp4", "type": "movie"},
        ])
        mock_get_conn.return_value = mock_conn

        resp = self.client.get("/api/system/drives-status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("drives", data)
        self.assertTrue(data["has_offline_drives"])
        self.assertIn("E:", data["offline_drive_letters"])
        self.assertIn("hide_unmounted_items", data)

        # Only drives configured via media_paths (D: and E:) should appear, not X:
        drive_letters = [d["drive_letter"] for d in data["drives"]]
        self.assertIn("D:", drive_letters)
        self.assertIn("E:", drive_letters)
        self.assertNotIn("X:", drive_letters)

        d_entry = next((d for d in data["drives"] if d["drive_letter"] == "D:"), None)
        self.assertIsNotNone(d_entry)
        self.assertTrue(d_entry["is_mounted"])
        self.assertEqual(d_entry["used_pct"], 60)
        self.assertEqual(d_entry["used_percent"], 60)
        self.assertEqual(d_entry["media_count"], 1)

        e_entry = next((d for d in data["drives"] if d["drive_letter"] == "E:"), None)
        self.assertIsNotNone(e_entry)
        self.assertFalse(e_entry["is_mounted"])
        self.assertEqual(e_entry["media_count"], 1)

    @patch("backend.settings.load_config")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.get_conn")
    @patch("shutil.disk_usage")
    def test_drives_status_uses_nested_and_overlapping_roots(self, mock_usage, mock_get_conn, mock_is_mounted, mock_cfg):
        mock_cfg.return_value = {
            "media_paths": {"movies": ["D:\\Media", "D:\\Media\\Movies"], "series": ["D:\\Media"], "anime": []},
            "disabled_paths": {},
        }
        mock_is_mounted.return_value = True
        mock_usage.return_value = MagicMock(total=1000 * 1024**3, used=500 * 1024**3, free=500 * 1024**3)
        mock_conn = MagicMock()
        mock_conn.execute.return_value = iter([
            {"file_path": "D:\\Media\\Movies\\Film.mkv", "type": "movie"},
            {"file_path": "D:\\Media\\Series\\Episode.mkv", "type": "series"},
            {"file_path": "D:\\Media2\\Neighbor.mkv", "type": "movie"},
        ])
        mock_get_conn.return_value = mock_conn

        response = self.client.get("/api/system/drives-status")
        self.assertEqual(response.status_code, 200)
        drive = response.get_json()["drives"][0]
        # The `D:\\Media` root is configured in two categories but only occurs once in paths.
        # The nested Movies root overlaps and deliberately counts its item a second time.
        self.assertEqual(drive["media_count"], 3)
        self.assertEqual(drive["category"], "movie, movies, series")

    @patch("backend.settings.load_config")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.get_conn")
    @patch("shutil.disk_usage")
    def test_drives_status_falls_back_to_drive_count_when_roots_empty(self, mock_usage, mock_get_conn, mock_is_mounted, mock_cfg):
        mock_cfg.return_value = {
            "media_paths": {"movies": ["D:\\Empty"], "series": [], "anime": []},
            "disabled_paths": {},
        }
        mock_is_mounted.return_value = True
        mock_usage.return_value = MagicMock(total=1000 * 1024**3, used=500 * 1024**3, free=500 * 1024**3)
        mock_conn = MagicMock()
        mock_conn.execute.return_value = iter([
            {"file_path": "D:\\Elsewhere\\one.mkv", "type": "movie"},
            {"file_path": "D:\\Elsewhere\\two.mkv", "type": "movie"},
        ])
        mock_get_conn.return_value = mock_conn

        response = self.client.get("/api/system/drives-status")
        self.assertEqual(response.status_code, 200)
        drive = response.get_json()["drives"][0]
        self.assertEqual(drive["media_count"], 2)

    @patch("backend.settings.load_config")
    @patch("backend.db.media.is_drive_mounted")
    @patch("backend.db.get_conn")
    @patch("shutil.disk_usage")
    def test_drives_status_keeps_duplicate_root_paths_distinct(self, mock_usage, mock_get_conn, mock_is_mounted, mock_cfg):
        mock_cfg.return_value = {
            "media_paths": {"movies": ["D:\\Library"], "series": ["d:\\library"], "anime": []},
            "disabled_paths": {},
        }
        mock_is_mounted.return_value = True
        mock_usage.return_value = MagicMock(total=1000 * 1024**3, used=500 * 1024**3, free=500 * 1024**3)
        mock_conn = MagicMock()
        mock_conn.execute.return_value = iter([
            {"file_path": "D:\\Library\\Film.mkv", "type": "movie"},
        ])
        mock_get_conn.return_value = mock_conn

        response = self.client.get("/api/system/drives-status")
        self.assertEqual(response.status_code, 200)
        drive = response.get_json()["drives"][0]
        # Existing path de-duplication is exact/case-sensitive; both configured roots match the media.
        self.assertEqual(drive["paths"], ["D:\\Library", "d:\\library"])
        self.assertEqual(drive["media_count"], 2)

    @patch("backend.routes.streaming.get_best_media_source")
    @patch("backend.routes.streaming.is_item_mounted")
    def test_api_stream_offline_drive_returns_503(self, mock_is_mounted, mock_get_best):
        """Verify GET /api/stream/<id> returns 503 drive_offline when drive is unmounted."""
        mock_get_best.return_value = {
            "id": 999,
            "title": "Offline Movie",
            "file_path": "Z:\\Movies\\Matrix.mkv",
            "drive_letter": "Z:",
            "is_mounted": False
        }
        mock_is_mounted.return_value = False

        resp = self.client.get("/api/stream/999")
        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertEqual(data.get("error"), "drive_offline")
        self.assertEqual(data.get("drive_letter"), "Z:")


if __name__ == "__main__":
    unittest.main()
