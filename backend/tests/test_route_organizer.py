# -*- coding: utf-8 -*-
"""
backend/tests/test_route_organizer.py — Unit tests for Media Organizer routes & webhooks.
"""
import os
import tempfile
import shutil
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.organizer import organizer_bp


class TestRouteOrganizer(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_secret_key"
        self.app.register_blueprint(organizer_bp)
        self.client = self.app.test_client()

        self.temp_dir = tempfile.mkdtemp()
        self.incoming_dir = os.path.join(self.temp_dir, "incoming")
        self.movies_dir = os.path.join(self.temp_dir, "movies")
        self.tv_dir = os.path.join(self.temp_dir, "tv")
        os.makedirs(self.incoming_dir, exist_ok=True)
        os.makedirs(self.movies_dir, exist_ok=True)
        os.makedirs(self.tv_dir, exist_ok=True)

        self.test_cfg = {
            "media_paths": {
                "movies": [self.movies_dir],
                "series": [self.tv_dir]
            },
            "organizer": {
                "incoming_dir": self.incoming_dir,
                "mode": "move",
                "auto_watch": False,
                "watch_interval_seconds": 60
            }
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("backend.routes.organizer.save_config", return_value=(True, None))
    @patch("backend.routes.organizer.require_admin")
    def test_get_and_post_config(self, mock_require_admin, mock_save_cfg):
        with patch("backend.routes.organizer.load_config", return_value=dict(self.test_cfg)):
            # GET config
            resp = self.client.get("/api/admin/organizer/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("incoming_dir", data)
            self.assertIn("mode", data)
            self.assertIn("available_paths", data)
            self.assertIn("target_movies_path", data)
            self.assertIn("target_series_path", data)
            self.assertIn("target_anime_path", data)

            # POST config
            post_resp = self.client.post("/api/admin/organizer/config", json={
                "incoming_dir": self.incoming_dir,
                "mode": "move",
                "auto_watch": True,
                "watch_interval_seconds": 30,
                "target_anime_path": "D:/Anime"
            })
            self.assertEqual(post_resp.status_code, 200)
            post_data = post_resp.get_json()
            self.assertTrue(post_data.get("success"))

    @patch("backend.routes.organizer.trigger_post_processing")
    @patch("backend.routes.organizer.require_admin")
    def test_preview_and_execute(self, mock_require_admin, mock_trigger):
        with patch("backend.routes.organizer.load_config", return_value=dict(self.test_cfg)):
            # Create a sample movie file in incoming
            movie_file = os.path.join(self.incoming_dir, "Gladiator.II.2024.1080p.mkv")
            with open(movie_file, "wb") as f:
                f.write(b"movie video data content")

            # Preview
            preview_resp = self.client.post("/api/admin/organizer/preview", json={
                "incoming_dir": self.incoming_dir
            })
            self.assertEqual(preview_resp.status_code, 200)
            prev_data = preview_resp.get_json()
            self.assertEqual(prev_data["count"], 1)
            item = prev_data["items"][0]
            self.assertEqual(item["canonical_title"], "Gladiator II")
            self.assertEqual(item["year"], 2024)

            # Execute
            exec_resp = self.client.post("/api/admin/organizer/execute", json={
                "items": [item],
                "mode": "move"
            })
            self.assertEqual(exec_resp.status_code, 200)
            exec_data = exec_resp.get_json()
            self.assertEqual(exec_data["success_count"], 1)

    @patch("backend.routes.organizer.trigger_post_processing")
    def test_webhook_downloaded(self, mock_trigger):
        with patch("backend.routes.organizer.load_config", return_value=dict(self.test_cfg)):
            movie_file = os.path.join(self.incoming_dir, "Oppenheimer.2023.mkv")
            with open(movie_file, "wb") as f:
                f.write(b"oppenheimer payload")

            hook_resp = self.client.post("/api/hooks/downloaded", json={
                "path": movie_file,
                "mode": "move"
            })
            self.assertEqual(hook_resp.status_code, 200)
            hook_data = hook_resp.get_json()
            self.assertTrue(hook_data.get("success"))
            self.assertEqual(hook_data.get("organized_count"), 1)

    def test_webhook_downloaded_blocks_outside_paths(self):
        with patch("backend.routes.organizer.load_config", return_value=dict(self.test_cfg)):
            outside_file = os.path.join(self.temp_dir, "outside_sensitive.txt")
            with open(outside_file, "w") as f:
                f.write("sensitive content")

            hook_resp = self.client.post("/api/hooks/downloaded", json={
                "path": outside_file,
                "mode": "move"
            })
            self.assertEqual(hook_resp.status_code, 403)
            self.assertIn("outside allowed", hook_resp.get_json()["error"])

    def test_webhook_downloaded_blocks_remote_non_admin(self):
        with patch("backend.routes.organizer.load_config", return_value=dict(self.test_cfg)):
            movie_file = os.path.join(self.incoming_dir, "Sample.2024.mkv")
            with open(movie_file, "wb") as f:
                f.write(b"sample")

            with patch("backend.routes.organizer.is_admin", return_value=False):
                hook_resp = self.client.post(
                    "/api/hooks/downloaded",
                    json={"path": movie_file, "mode": "move"},
                    environ_base={"REMOTE_ADDR": "192.168.1.100"}
                )
                self.assertEqual(hook_resp.status_code, 403)
                self.assertIn("Administrator privileges or localhost access required", hook_resp.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
