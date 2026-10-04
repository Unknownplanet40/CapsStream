# -*- coding: utf-8 -*-
"""
Tests for Settings & Configuration Module (backend/settings.py)
Covers config loading, caching, deep dictionary merging, validation, and serialization.
"""
import os
import json
import unittest
import tempfile
import shutil

from backend import settings


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_settings_test_")
        self.orig_config_path = settings.CONFIG_PATH
        settings.CONFIG_PATH = os.path.join(self.test_dir, "config.json")
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}

    def tearDown(self):
        settings.CONFIG_PATH = self.orig_config_path
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_default_config_when_missing(self):
        """Verify load_config returns DEFAULT_CONFIG when config.json does not exist."""
        cfg = settings.load_config()
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["port"], 8000)
        self.assertIn("playback", cfg)
        self.assertIn("media_paths", cfg)

    def test_save_and_load_config(self):
        """Verify save_config writes to disk and load_config reads modified values."""
        custom_cfg = settings.load_config()
        custom_cfg["port"] = 8080
        custom_cfg["playback"]["seek_step"] = 15

        ok, result = settings.save_config(custom_cfg)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(settings.CONFIG_PATH))

        # Invalidate in-memory cache to force disk read
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        reloaded = settings.load_config()
        self.assertEqual(reloaded["port"], 8080)
        self.assertEqual(reloaded["playback"]["seek_step"], 15)

    def test_deep_merge_preserves_new_defaults(self):
        """Verify existing user configs inherit missing default keys automatically."""
        partial_user_config = {
            "port": 9000,
            "playback": {"default_speed": 1.25}
        }
        with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(partial_user_config, f)

        cfg = settings.load_config()
        self.assertEqual(cfg["port"], 9000)
        self.assertEqual(cfg["playback"]["default_speed"], 1.25)
        # Should have inherited auto_play_next from DEFAULT_CONFIG
        self.assertTrue(cfg["playback"]["auto_play_next"])

    def test_clear_cache_deletes_only_disk_files_preserves_db(self):
        """Verify clear_cache deletes cached files on disk but preserves all media and watch records in SQLite."""
        fake_meta_dir = os.path.join(self.test_dir, "data", "metadata")
        os.makedirs(os.path.join(fake_meta_dir, "images"), exist_ok=True)
        dummy_file = os.path.join(fake_meta_dir, "movie_123.json")
        dummy_img = os.path.join(fake_meta_dir, "images", "poster.jpg")
        with open(dummy_file, "w") as f:
            f.write("{}")
        with open(dummy_img, "w") as f:
            f.write("img")

        import sqlite3
        from unittest.mock import patch, MagicMock

        test_db_path = os.path.join(self.test_dir, "test.db")
        setup_conn = sqlite3.connect(test_db_path)
        setup_conn.execute("""
            CREATE TABLE media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                tmdb_id INTEGER,
                title TEXT,
                file_path TEXT
            )
        """)
        setup_conn.execute("""
            CREATE TABLE watch_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                media_id INTEGER
            )
        """)
        setup_conn.execute("CREATE TABLE collection_items (collection_id INTEGER, media_id INTEGER)")
        setup_conn.execute("CREATE TABLE favorites (profile_id INTEGER, media_id INTEGER)")
        setup_conn.execute("CREATE TABLE playlist_items (id INTEGER PRIMARY KEY, playlist_id INTEGER, media_id INTEGER)")

        setup_conn.execute("INSERT INTO media (type, tmdb_id, title, file_path) VALUES ('movie', 101, 'Test Movie', 'C:/test.mkv')")
        setup_conn.execute("INSERT INTO watch_progress (profile_id, media_id) VALUES (1, 1)")
        setup_conn.commit()
        setup_conn.close()

        orig_root = settings.ROOT_DIR
        settings.ROOT_DIR = self.test_dir
        try:
            with patch("backend.db.get_conn", side_effect=lambda: sqlite3.connect(test_db_path)):
                cleared = settings.clear_cache()

            # Disk cache files should be removed
            self.assertEqual(cleared, 2)
            self.assertFalse(os.path.exists(dummy_file))
            self.assertFalse(os.path.exists(dummy_img))
            # The metadata directory structure should be recreated
            self.assertTrue(os.path.exists(os.path.join(fake_meta_dir, "images")))

            # Verify database rows are PRESERVED (not deleted)
            verify_conn = sqlite3.connect(test_db_path)
            count = verify_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            self.assertEqual(count, 1)  # media row must survive
            prog_count = verify_conn.execute("SELECT COUNT(*) FROM watch_progress").fetchone()[0]
            self.assertEqual(prog_count, 1)  # watch_progress must survive
            verify_conn.close()
        finally:
            settings.ROOT_DIR = orig_root

    def test_auto_convert_hevc_normalization(self):
        """Verify legacy boolean values for auto_convert_hevc are normalized to 'ask' and 'never'."""
        # 1. Default value is "ask"
        cfg = settings.load_config()
        self.assertEqual(cfg["playback"]["auto_convert_hevc"], "ask")

        # 2. Legacy True -> "ask"
        with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"playback": {"auto_convert_hevc": True}}, f)
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        cfg_true = settings.load_config()
        self.assertEqual(cfg_true["playback"]["auto_convert_hevc"], "ask")

        # 3. Legacy False -> "never"
        with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"playback": {"auto_convert_hevc": False}}, f)
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        cfg_false = settings.load_config()
        self.assertEqual(cfg_false["playback"]["auto_convert_hevc"], "never")

        # 4. Explicit "auto" is preserved
        with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"playback": {"auto_convert_hevc": "auto"}}, f)
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        cfg_auto = settings.load_config()
        self.assertEqual(cfg_auto["playback"]["auto_convert_hevc"], "auto")

    def test_movie_source_config_default_and_merge(self):
        """Verify movie_source config defaults and merges correctly."""
        cfg = settings.load_config()
        self.assertIn("movie_source", cfg)
        self.assertEqual(cfg["movie_source"]["site_url"], "https://siteformovies.com")
        self.assertEqual(cfg["movie_source"]["api_url"], "https://movies-api.accel.li/api/v2")

        # Custom site_url override preserves default api_url
        with open(settings.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"movie_source": {"site_url": "https://custommovies.org"}}, f)
        settings._CONFIG_CACHE = {"data": None, "ts": 0.0}
        merged_cfg = settings.load_config()
        self.assertEqual(merged_cfg["movie_source"]["site_url"], "https://custommovies.org")
        self.assertEqual(merged_cfg["movie_source"]["api_url"], "https://movies-api.accel.li/api/v2")

    def test_test_api_key_movie_source(self):
        """Verify test_api_key tests the movie_source API endpoint correctly."""
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "ok"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok, msg = settings.test_api_key("movie_source", url="https://movies-api.accel.li/api/v2")
            self.assertTrue(ok)
    def test_browse_folder_dialog_cancel_does_not_trigger_powershell(self):
        """Verify cancelling the Tkinter folder dialog returns None and does NOT launch PowerShell."""
        from unittest.mock import patch, MagicMock
        mock_tk = MagicMock()
        mock_tk.filedialog.askdirectory.return_value = ""

        with patch.dict("sys.modules", {"tkinter": mock_tk, "tkinter.filedialog": mock_tk.filedialog}):
            with patch("subprocess.run") as mock_subproc:
                res = settings.browse_folder_dialog()
                self.assertIsNone(res)
                mock_subproc.assert_not_called()

    def test_browse_folder_dialog_selects_folder(self):
        """Verify picking a folder in Tkinter returns the normalized path."""
        from unittest.mock import patch, MagicMock
        mock_tk = MagicMock()
        mock_tk.filedialog.askdirectory.return_value = "D:\\Entertainment\\Movies"

        with patch.dict("sys.modules", {"tkinter": mock_tk, "tkinter.filedialog": mock_tk.filedialog}):
            with patch("subprocess.run") as mock_subproc:
                res = settings.browse_folder_dialog()
                self.assertEqual(res, "D:/Entertainment/Movies")
                mock_subproc.assert_not_called()

    def test_browse_folder_dialog_tkinter_crash_falls_back_to_powershell(self):
        """Verify that when Tkinter raises an exception, PowerShell fallback is used."""
        from unittest.mock import patch, MagicMock
        mock_subproc = MagicMock()
        mock_subproc.stdout = "D:\\Entertainment\\Series\n"

        with patch.dict("sys.modules", {"tkinter": None}):
            with patch("subprocess.run", return_value=mock_subproc) as mock_run:
                with patch("os.name", "nt"):
                    res = settings.browse_folder_dialog()
                    self.assertEqual(res, "D:/Entertainment/Series")
                    mock_run.assert_called_once()

    def test_browse_folder_dialog_concurrent_lock(self):
        """Verify that if a dialog is already active, subsequent calls return None immediately."""
        with settings._folder_dialog_lock:
            res = settings.browse_folder_dialog()
            self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()

