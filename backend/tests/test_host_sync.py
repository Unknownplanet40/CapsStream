# -*- coding: utf-8 -*-
"""
Tests for Host PC Documents User Data Synchronization (backend/host_sync.py)
Verifies that:
1. is_host_sync_allowed() correctly isolates development mode and checks enabled config.
2. Tag resolution follows: Dev_Test in dev mode -> custom tag -> config -> volume label -> drive letter.
3. export_user_data_to_host() exports profiles, watch history, playlists, achievements, avatars, and summary text.
4. import_user_data_from_host() performs intelligent merges into newly swapped drives.
5. Missing media is preserved in persistent watch history and stats while omitted from active playback queues.
6. Tag isolation ensures different drives (e.g. Drive_D vs Drive_T) write to distinct subfolders.
"""
import os
import shutil
import tempfile
import unittest
import sqlite3
from unittest.mock import patch

from backend.tests import create_isolated_test_db
from backend.host_sync import (
    get_drive_tag,
    get_host_sync_dir,
    is_host_sync_allowed,
    get_host_sync_status,
    export_user_data_to_host,
    import_user_data_from_host,
    open_host_sync_folder,
    sanitize_tag,
)
from backend.db.playback import save_progress, get_progress
from backend.db.media import upsert_media
from backend.db.connection import get_conn


class TestHostSync(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        self.test_root = tempfile.mkdtemp(prefix="caps_test_root_")
        self.test_docs_base = os.path.join(self.test_root, "Documents")
        os.makedirs(self.test_docs_base, exist_ok=True)
        self.env_patcher = patch.dict(os.environ, {"USERPROFILE": self.test_root})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.cleanup_db()
        if os.path.exists(self.test_root):
            try:
                shutil.rmtree(self.test_root)
            except Exception:
                pass

    def test_tag_sanitization_and_resolution(self):
        """Verify tag sanitization and 3-tier resolution."""
        self.assertEqual(sanitize_tag("Province Drive!"), "Province_Drive")
        self.assertEqual(sanitize_tag("USB-DRIVE_1"), "USB-DRIVE_1")
        self.assertEqual(sanitize_tag(""), "")

        # Custom tag parameter override
        self.assertEqual(get_drive_tag(custom_tag="External_T"), "External_T")

        # In dev mode, defaults to Dev_Test
        with patch("backend.host_sync.is_dev_mode", return_value=True):
            self.assertEqual(get_drive_tag(), "Dev_Test")

        # In non-dev mode, checks config.json
        with patch("backend.host_sync.is_dev_mode", return_value=False):
            with patch("backend.host_sync.load_config", return_value={"host_sync": {"drive_tag": "Custom_Tag"}}):
                self.assertEqual(get_drive_tag(), "Custom_Tag")

        # In non-dev mode without config, checks volume label or drive letter
        with patch("backend.host_sync.is_dev_mode", return_value=False):
            with patch("backend.host_sync.load_config", return_value={"host_sync": {"drive_tag": ""}}):
                with patch("backend.host_sync.get_windows_volume_label", return_value="CAPS_STICK"):
                    self.assertEqual(get_drive_tag(), "CAPS_STICK")

    @patch("backend.host_sync.is_dev_mode", return_value=True)
    def test_dev_mode_isolation_and_safety(self, mock_dev):
        """Verify dev mode allows safe Dev_Test operations but blocks non-test tags without force_dev."""
        # By default in config, host_sync is disabled
        self.assertFalse(is_host_sync_allowed())
        # Even with force_dev, requires enabled=True in config
        with patch("backend.host_sync.load_config", return_value={"host_sync": {"enabled": True}}):
            self.assertFalse(is_host_sync_allowed())
            self.assertTrue(is_host_sync_allowed(force_dev=True))

        # Dev mode allows testing in Dev_Test
        dev_exp = export_user_data_to_host()
        self.assertTrue(dev_exp["ok"], dev_exp.get("error"))
        self.assertEqual(dev_exp["drive_tag"], "Dev_Test")
        self.assertTrue(os.path.isfile(os.path.join(self.test_docs_base, "CapsStream", "Dev_Test", "user_data.db")))

        # Dev mode blocks targeting a production tag like Drive_D without force_dev
        prod_exp = export_user_data_to_host(custom_tag="Drive_D")
        self.assertFalse(prod_exp["ok"])
        self.assertTrue(prod_exp.get("is_dev"))

        # But allows it if force_dev is True
        prod_exp_forced = export_user_data_to_host(force_dev=True, custom_tag="Drive_D")
        self.assertTrue(prod_exp_forced["ok"])
        self.assertEqual(prod_exp_forced["drive_tag"], "Drive_D")

    @patch("backend.host_sync.is_dev_mode", return_value=False)
    def test_export_and_import_cycle(self, mock_dev):
        """Verify complete export to Documents folder and intelligent restore."""
        conn = get_conn()
        # Seed test profile
        conn.execute("INSERT INTO profiles (id, name, avatar, color, is_admin) VALUES (1, 'Ryan', 'ph-user', '#e50914', 1)")
        # Seed media
        m_id = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, duration, genres, file_path)
            VALUES ('movie', 550, 'Fight Club', 1999, 8340, 'Drama', 'E:\\Movies\\FightClub.mkv')
        """).lastrowid
        # Seed achievements
        conn.execute("INSERT INTO achievements (profile_id, achievement_id) VALUES (1, 'first_watch')")
        conn.commit()
        conn.close()

        # Record progress
        save_progress(profile_id=1, media_id=m_id, position=4200, duration=8340, completed=False)

        # Export to host Documents under tag Province_Drive
        res = export_user_data_to_host(custom_tag="Province_Drive")
        self.assertTrue(res["ok"], res.get("error"))
        sync_folder = os.path.join(self.test_docs_base, "CapsStream", "Province_Drive")
        self.assertTrue(os.path.isfile(os.path.join(sync_folder, "user_data.db")))
        self.assertTrue(os.path.isfile(os.path.join(sync_folder, "export_summary.txt")))
        self.assertTrue(os.path.isfile(os.path.join(sync_folder, "sync_manifest.json")))

        # Check export_summary.txt content
        with open(os.path.join(sync_folder, "export_summary.txt"), "r", encoding="utf-8") as f:
            summary = f.read()
            self.assertIn("Ryan", summary)
            self.assertIn("Province_Drive", summary)
            self.assertIn("Total Watch History Entries", summary)

        # Now simulate a NEW USB drive with a fresh database and new movie, but same Fight Club
        new_db_path, cleanup_new = create_isolated_test_db()
        try:
            n_conn = sqlite3.connect(new_db_path)
            # Fresh drive has default profile
            n_conn.execute("INSERT INTO profiles (id, name, avatar, is_admin) VALUES (1, 'Default', 'ph-film-strip', 1)")
            # Fresh drive has Fight Club with new media ID
            new_m_id = n_conn.execute("""
                INSERT INTO media (type, tmdb_id, title, year, duration, genres, file_path)
                VALUES ('movie', 550, 'Fight Club', 1999, 8340, 'Drama', 'F:\\NewDrive\\FightClub.mkv')
            """).lastrowid
            n_conn.commit()
            n_conn.close()

            # Import host user data into new drive database using same tag
            imp_res = import_user_data_from_host(conn=sqlite3.connect(new_db_path), custom_tag="Province_Drive")
            self.assertTrue(imp_res["ok"], imp_res.get("error"))
            self.assertGreaterEqual(imp_res.get("restored_profiles", 0), 1)

            # Verify that watch progress was automatically re-linked for Fight Club on the new drive!
            chk_conn = sqlite3.connect(new_db_path)
            chk_conn.row_factory = sqlite3.Row
            wp = chk_conn.execute("SELECT * FROM watch_progress WHERE media_id=?", (new_m_id,)).fetchone()
            self.assertIsNotNone(wp)
            self.assertEqual(wp["position"], 4200)

            # Verify achievements restored
            ach = chk_conn.execute("SELECT * FROM achievements WHERE achievement_id='first_watch'").fetchone()
            self.assertIsNotNone(ach)
            chk_conn.close()
        finally:
            cleanup_new()

    @patch("backend.host_sync.is_dev_mode", return_value=False)
    def test_multi_drive_subfolder_isolation(self, mock_dev):
        """Verify D: and T: instances do not overwrite each other."""
        conn = get_conn()
        conn.execute("INSERT INTO profiles (id, name, is_admin) VALUES (1, 'Stationary_D', 1)")
        conn.commit()
        conn.close()

        # Export D
        res_d = export_user_data_to_host(custom_tag="Drive_D")
        self.assertTrue(res_d["ok"])

        # Change profile to Portable_T and export T
        conn = get_conn()
        conn.execute("UPDATE profiles SET name='Portable_T' WHERE id=1")
        conn.commit()
        conn.close()

        res_t = export_user_data_to_host(custom_tag="Drive_T")
        self.assertTrue(res_t["ok"])

        # Check that both subfolders exist independently
        dir_d = os.path.join(self.test_docs_base, "CapsStream", "Drive_D", "export_summary.txt")
        dir_t = os.path.join(self.test_docs_base, "CapsStream", "Drive_T", "export_summary.txt")
        self.assertTrue(os.path.isfile(dir_d))
        self.assertTrue(os.path.isfile(dir_t))

        with open(dir_d, "r", encoding="utf-8") as f:
            self.assertIn("Stationary_D", f.read())
        with open(dir_t, "r", encoding="utf-8") as f:
            self.assertIn("Portable_T", f.read())

    @patch("backend.host_sync.is_dev_mode", return_value=False)
    def test_missing_media_resilience(self, mock_dev):
        """Verify media missing on the new drive stays safely in watch_history without creating broken progress."""
        conn = get_conn()
        conn.execute("INSERT INTO profiles (id, name, is_admin) VALUES (1, 'Alice', 1)")
        m_id = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, duration, genres, file_path)
            VALUES ('movie', 9999, 'Old Deleted Movie', 2000, 7200, 'Comedy', 'E:\\Old\\Movie.mkv')
        """).lastrowid
        conn.commit()
        conn.close()

        # Save progress for old movie
        save_progress(profile_id=1, media_id=m_id, position=7200, duration=7200, completed=True)

        # Export to host
        export_user_data_to_host(custom_tag="Drive_Test")

        # Create new drive that does NOT have 'Old Deleted Movie'
        new_db_path, cleanup_new = create_isolated_test_db()
        try:
            n_conn = sqlite3.connect(new_db_path)
            n_conn.execute("INSERT INTO profiles (id, name, is_admin) VALUES (1, 'Alice', 1)")
            # Only has a different movie
            n_conn.execute("""
                INSERT INTO media (type, tmdb_id, title, year, duration, genres, file_path)
                VALUES ('movie', 1111, 'Brand New Movie', 2026, 6000, 'Action', 'F:\\New\\NewMovie.mkv')
            """)
            n_conn.commit()
            n_conn.close()

            # Import host user data
            imp_res = import_user_data_from_host(conn=sqlite3.connect(new_db_path), custom_tag="Drive_Test")
            self.assertTrue(imp_res["ok"])

            chk_conn = sqlite3.connect(new_db_path)
            chk_conn.row_factory = sqlite3.Row

            # 1. Old movie is present in persistent watch_history (stats & achievements intact)
            wh = chk_conn.execute("SELECT * FROM watch_history WHERE title='Old Deleted Movie'").fetchone()
            self.assertIsNotNone(wh)
            self.assertEqual(wh["completed"], 1)

            # 2. No broken watch_progress row was created for the missing movie
            wp_rows = chk_conn.execute("SELECT * FROM watch_progress").fetchall()
            self.assertEqual(len(wp_rows), 0)
            chk_conn.close()
        finally:
            cleanup_new()

    def test_get_host_sync_status(self):
        """Verify status reporting accurately detects sync files."""
        stat = get_host_sync_status(custom_tag="Test_Status")
        self.assertTrue(stat["ok"])
        self.assertFalse(stat["has_host_data"])
        self.assertEqual(stat["drive_tag"], "Test_Status")

        status_dir = os.path.join(self.test_docs_base, "CapsStream", "Test_Status")
        os.makedirs(status_dir, exist_ok=True)
        # Create dummy user_data.db
        with open(os.path.join(status_dir, "user_data.db"), "w") as f:
            f.write("test")

        stat2 = get_host_sync_status(custom_tag="Test_Status")
        self.assertTrue(stat2["has_host_data"])
        self.assertGreater(stat2["db_size"], 0)


if __name__ == "__main__":
    unittest.main()
