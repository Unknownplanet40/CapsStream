# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from backend.external_player import (
    find_vlc_binary,
    get_free_port,
    build_playlist_content,
    create_temp_playlist_file,
    VLCProgressTracker,
    launch_external_player,
)


class TestExternalPlayer(unittest.TestCase):
    def test_find_vlc_binary(self):
        """Verify VLC detection finds executable or returns None gracefully."""
        res = find_vlc_binary()
        if res is not None:
            self.assertTrue(os.path.isfile(res))
            self.assertTrue(res.lower().endswith("vlc.exe") or "vlc" in res.lower())

    def test_get_free_port(self):
        """Verify ephemeral port allocation."""
        port = get_free_port(8089)
        self.assertIsInstance(port, int)
        self.assertGreater(port, 1024)

    def test_build_playlist_content_local(self):
        """Verify local client playlist uses absolute filesystem paths."""
        items = [
            {
                "id": 101,
                "title": "Frieren",
                "ep_title": "The Journey Begins",
                "season": 1,
                "episode": 1,
                "duration": 1440,
                "file_path": os.path.abspath(__file__),  # existing file
            },
            {
                "id": 102,
                "title": "Frieren",
                "ep_title": "It Didn't Have to Be Magic",
                "season": 1,
                "episode": 2,
                "duration": 1420,
                "file_path": os.path.abspath(__file__),
            },
        ]
        content = build_playlist_content(items, is_local_client=True, host_url="http://localhost:5000")
        self.assertTrue(content.startswith("#EXTM3U"))
        self.assertIn("#EXTINF:1440,Frieren - S01E01 - The Journey Begins", content)
        self.assertIn("#EXTINF:1420,Frieren - S01E02 - It Didn't Have to Be Magic", content)
        # Should contain local file path, not HTTP URL
        self.assertIn(os.path.normpath(os.path.abspath(__file__)), content)
        self.assertNotIn("http://localhost:5000", content)

    def test_build_playlist_content_remote(self):
        """Verify remote client playlist uses HTTP stream URLs."""
        items = [
            {
                "id": 201,
                "title": "Inception",
                "duration": 8880,
                "file_path": "/fake/path/movie.mkv",
            }
        ]
        content = build_playlist_content(items, is_local_client=False, host_url="http://192.168.1.50:5000")
        self.assertTrue(content.startswith("#EXTM3U"))
        self.assertIn("#EXTINF:8880,Inception", content)
        self.assertIn("http://192.168.1.50:5000/api/stream/201", content)

    def test_create_temp_playlist_file(self):
        """Verify temp playlist file is created with utf-8 encoding."""
        content = "#EXTM3U\n#EXTINF:100,Test\n/dummy/file.mp4\n"
        path = create_temp_playlist_file(content, title_hint="test_show")
        try:
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(path.endswith(".m3u8"))
            with open(path, "r", encoding="utf-8") as f:
                read_back = f.read()
            self.assertEqual(content, read_back)
        finally:
            if os.path.isfile(path):
                os.remove(path)

    def test_vlc_tracker_resolve_media_id(self):
        """Verify metadata resolution in VLC tracker."""
        dummy_file = os.path.abspath(__file__)
        items = [
            {
                "id": 501,
                "title": "Solo Leveling",
                "ep_title": "Episode 1",
                "season": 1,
                "episode": 1,
                "file_path": dummy_file,
            },
            {
                "id": 502,
                "title": "Solo Leveling",
                "ep_title": "Episode 2",
                "season": 1,
                "episode": 2,
                "file_path": "C:\\Media\\Solo_Leveling_S01E02.mkv",
            }
        ]
        proc = MagicMock()
        tracker = VLCProgressTracker(
            process=proc,
            port=9999,
            password="test",
            items=items,
            profile_id=1
        )

        # 1. Resolve via file URI
        norm_uri = "file:///" + dummy_file.replace("\\", "/")
        mid1 = tracker.resolve_media_id({"uri": norm_uri})
        self.assertEqual(mid1, 501)

        # 2. Resolve via filename
        mid2 = tracker.resolve_media_id({"filename": "Solo_Leveling_S01E02.mkv"})
        self.assertEqual(mid2, 502)

        # 3. Resolve via stream URL
        mid3 = tracker.resolve_media_id({"uri": "http://127.0.0.1:5000/api/stream/501?token=xyz"})
        self.assertEqual(mid3, 501)

        # 4. Resolve via URL-encoded filename
        mid4 = tracker.resolve_media_id({"filename": "Solo_Leveling_S01E02%2Emkv"})
        self.assertEqual(mid4, 502)

        # 5. Resolve via SxxExx regex in title
        mid5 = tracker.resolve_media_id({"title": "S01E02 - Episode 2", "artist": "Solo Leveling"})
        self.assertEqual(mid5, 502)

    @patch("backend.external_player.find_vlc_binary", return_value="/usr/bin/vlc")
    @patch("subprocess.Popen")
    def test_launch_external_player_vlc(self, mock_popen, mock_find_vlc):
        """Verify VLC launch when binary is found."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        items = [
            {"id": 1, "title": "Test Movie", "duration": 6000, "file_path": os.path.abspath(__file__)}
        ]
        res = launch_external_player(
            items=items,
            profile_id=1,
            is_local_client=True,
            host_url="http://localhost:5000"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["method"], "vlc")
        self.assertTrue(res["tracked"])
        self.assertEqual(res["player"], "VLC Media Player")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "/usr/bin/vlc")
        self.assertIn("--extraintf", cmd)
        self.assertIn("http", cmd)

    @patch("backend.external_player.find_vlc_binary", return_value=None)
    @patch("os.startfile", create=True)
    def test_launch_external_player_fallback(self, mock_startfile, mock_find_vlc):
        """Verify fallback to system default when VLC is missing."""
        items = [
            {"id": 2, "title": "Fallback Movie", "duration": 4000, "file_path": os.path.abspath(__file__)}
        ]
        with patch("sys.platform", "win32"):
            res = launch_external_player(
                items=items,
                profile_id=1,
                is_local_client=True,
                host_url="http://localhost:5000"
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["method"], "system")
            self.assertFalse(res["tracked"])
            mock_startfile.assert_called_once()

    def test_vlc_tracker_run_method_attached(self):
        """Verify VLCProgressTracker properly defines run() instead of inheriting empty Thread.run."""
        import threading
        from backend.external_player import get_vlc_tracker_status
        self.assertNotEqual(VLCProgressTracker.run, threading.Thread.run)
        status = get_vlc_tracker_status()
        self.assertIsInstance(status, dict)
        self.assertIn("active", status)

    def test_prune_temp_playlists(self):
        """Verify prune_temp_playlists deletes stale files while keeping fresh files."""
        import tempfile
        import time
        from backend.external_player import prune_temp_playlists
        temp_dir = os.path.join(tempfile.gettempdir(), "capsstream_playlists")
        os.makedirs(temp_dir, exist_ok=True)
        old_file = os.path.join(temp_dir, "test_stale_old.m3u8")
        fresh_file = os.path.join(temp_dir, "test_fresh.m3u8")

        with open(old_file, "w") as f:
            f.write("#EXTM3U")
        with open(fresh_file, "w") as f:
            f.write("#EXTM3U")

        # Set old_file mtime to 2 hours ago
        stale_time = time.time() - 7200
        os.utime(old_file, (stale_time, stale_time))

        try:
            prune_temp_playlists(max_age_seconds=3600)
            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(fresh_file))
        finally:
            if os.path.exists(old_file):
                os.remove(old_file)
            if os.path.exists(fresh_file):
                os.remove(fresh_file)


if __name__ == "__main__":
    unittest.main()

