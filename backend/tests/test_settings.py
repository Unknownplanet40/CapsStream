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


if __name__ == "__main__":
    unittest.main()
