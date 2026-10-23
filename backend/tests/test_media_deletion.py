# -*- coding: utf-8 -*-
"""
Tests for Media Deletion & Recycle Bin Integration
(backend/trash.py & endpoints in backend/routes/media.py)
"""
import os
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask

from backend.routes.media import media_bp, bust_home_cache
from backend.trash import send_to_trash


class TestMediaDeletion(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_deletion_secret"
        self.app.register_blueprint(media_bp)
        self.client = self.app.test_client()
        bust_home_cache()

    def test_send_to_trash_file_and_dir(self):
        """Verify send_to_trash correctly moves or removes temporary files and dirs."""
        fd, tmp_file = tempfile.mkstemp(prefix="cs_test_del_")
        os.close(fd)
        with open(tmp_file, "w") as f:
            f.write("test content")
        self.assertTrue(os.path.exists(tmp_file))

        res = send_to_trash(tmp_file)
        self.assertTrue(res)
        self.assertFalse(os.path.exists(tmp_file))

        # Test on missing path
        self.assertFalse(send_to_trash("Z:/nonexistent_capsstream_path_123.mkv"))

    @patch("backend.routes.media.get_media_by_id")
    @patch("backend.routes.media.get_admin_profiles")
    @patch("backend.routes.media.is_admin", return_value=False)
    def test_preview_media_delete_single_movie(self, mock_is_admin, mock_admins, mock_get_media):
        """Previewing single movie shows affected file count and companion files."""
        temp_dir = tempfile.mkdtemp(prefix="cs_preview_test_")
        vid_path = os.path.join(temp_dir, "Inception.2010.mkv")
        sub_path = os.path.join(temp_dir, "Inception.2010.en.srt")
        with open(vid_path, "w") as f:
            f.write("mock video")
        with open(sub_path, "w") as f:
            f.write("mock sub")

        mock_admins.return_value = [{"id": 1, "name": "Admin", "has_pin": True}]
        mock_get_media.return_value = {
            "id": 101,
            "title": "Inception",
            "type": "movie",
            "path": vid_path,
        }

        resp = self.client.post("/api/media/delete/preview", json={"media_id": 101})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["title"], "Inception")
        self.assertEqual(data["file_count"], 2)
        self.assertTrue(data["requires_pin"])
        self.assertIn("Inception.2010.mkv", data["files"])
        self.assertIn("Inception.2010.en.srt", data["files"])

        # Clean up
        try:
            if os.path.exists(vid_path): os.remove(vid_path)
            if os.path.exists(sub_path): os.remove(sub_path)
            if os.path.exists(temp_dir): os.rmdir(temp_dir)
        except Exception:
            pass

    @patch("backend.routes.media.get_media_by_id")
    @patch("backend.routes.media.delete_media_by_id")
    @patch("backend.routes.media.verify_admin_pin")
    @patch("backend.routes.media.send_to_trash")
    def test_api_media_delete_with_pin(self, mock_trash, mock_verify_pin, mock_delete_id, mock_get_media):
        """Deleting an episode with correct admin PIN succeeds."""
        mock_verify_pin.return_value = (True, "", 200)
        mock_delete_id.return_value = 1
        mock_trash.return_value = True

        temp_dir = tempfile.mkdtemp(prefix="cs_ep_test_")
        ep_path = os.path.join(temp_dir, "Breaking.Bad.S01E01.mkv")
        with open(ep_path, "w") as f:
            f.write("mock episode")

        mock_get_media.return_value = {
            "id": 55,
            "title": "Breaking Bad",
            "season": 1,
            "episode": 1,
            "ep_title": "Pilot",
            "type": "series",
            "path": ep_path,
        }

        resp = self.client.post("/api/media/delete", json={
            "media_id": 55,
            "admin_pin": "1234",
            "delete_files": True,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["deleted_rows"], 1)
        self.assertEqual(data["trashed_files_count"], 1)
        mock_trash.assert_called_with(ep_path)
        mock_delete_id.assert_called_with(55)

        try:
            if os.path.exists(ep_path): os.remove(ep_path)
            if os.path.exists(temp_dir): os.rmdir(temp_dir)
        except Exception:
            pass

    @patch("backend.routes.media.verify_admin_pin")
    @patch("backend.routes.media.is_admin", return_value=False)
    @patch("backend.routes.media.get_admin_profiles")
    def test_api_media_delete_unauthorized(self, mock_admins, mock_is_admin, mock_verify_pin):
        """Unauthorized delete requests without valid PIN are rejected."""
        mock_admins.return_value = [{"id": 1, "has_pin": True}]
        mock_verify_pin.return_value = (False, "Incorrect Admin PIN", 401)

        resp = self.client.post("/api/media/delete", json={
            "media_id": 999,
            "admin_pin": "0000",
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
