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

    def test_clear_cache_deletes_metadata_files_and_db_records(self):
        """Verify clear_cache deletes cached files on disk and removes all media records from SQLite."""
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

            self.assertEqual(cleared, 2)
            self.assertFalse(os.path.exists(dummy_file))
            self.assertFalse(os.path.exists(dummy_img))
            self.assertTrue(os.path.exists(os.path.join(fake_meta_dir, "images")))

            # Verify database rows purged
            verify_conn = sqlite3.connect(test_db_path)
            count = verify_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            self.assertEqual(count, 0)
            prog_count = verify_conn.execute("SELECT COUNT(*) FROM watch_progress").fetchone()[0]
            self.assertEqual(prog_count, 0)
            verify_conn.close()
        finally:
            settings.ROOT_DIR = orig_root


if __name__ == "__main__":
    unittest.main()
