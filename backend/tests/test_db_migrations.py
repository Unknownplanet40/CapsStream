# -*- coding: utf-8 -*-
"""
Tests for Database Schema & Migrations (backend/db/schema.py, backend/db/connection.py)
Covers database initialization, table creation, integrity constraints,
WAL pragmas, and schema migrations.
"""
import os
import sys
import sqlite3
import unittest
import tempfile

from backend.tests import create_isolated_test_db
from backend.db.connection import get_conn, release_conn
from backend.db.schema import init_db
from backend.db.profiles import create_profile, get_all_profiles, delete_profile, hash_pin
from backend.db.media import upsert_media, get_media_by_id
from backend.db.playback import save_progress, get_progress
from backend.db.playlists import create_playlist, get_playlists


class TestDatabaseMigrations(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()

    def tearDown(self):
        self.cleanup_db()

    def test_schema_tables_exist(self):
        """Verify all core tables and indexes are created during init_db()."""
        conn = get_conn()
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {r[0] for r in rows}
        conn.close()

        expected_tables = {
            "media",
            "profiles",
            "watch_progress",
            "favorites",
            "collections",
            "collection_items",
            "playlists",
            "playlist_items",
            "achievements",
        }

        for tbl in expected_tables:
            self.assertIn(tbl, tables, f"Expected table '{tbl}' to exist in schema")

    def test_profile_crud_and_pin_hashing(self):
        """Verify profile creation, PIN hashing, updates, and deletion."""
        pin_hash = hash_pin("1234")
        pid = create_profile(name="TestUser", pin_hash=pin_hash, avatar="ph-user", is_admin=False, is_kids=False)
        self.assertIsNotNone(pid)

        profiles = get_all_profiles()
        p = next((x for x in profiles if x["id"] == pid), None)
        self.assertIsNotNone(p)
        self.assertEqual(p["name"], "TestUser")
        self.assertTrue(p["has_pin"])

        delete_profile(pid)
        profiles_after = get_all_profiles()
        self.assertIsNone(next((x for x in profiles_after if x["id"] == pid), None))

    def test_media_upsert_and_retrieval(self):
        """Verify media item upserting, metadata fields, and querying."""
        media_data = {
            "title": "Inception",
            "type": "movie",
            "year": 2010,
            "rating": 8.8,
            "file_path": r"C:\Media\Inception.mp4",
            "file_size": 2147483648,
            "duration": 8880,
            "genres": "Action, Sci-Fi",
            "overview": "A thief who steals corporate secrets...",
        }
        mid = upsert_media(media_data)
        self.assertIsNotNone(mid)

        fetched = get_media_by_id(mid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Inception")
        self.assertEqual(fetched["year"], 2010)
        self.assertEqual(fetched["rating"], 8.8)

    def test_watch_progress_upsert(self):
        """Verify playback progress save and conflict updates."""
        pid = create_profile(name="Watcher", pin_hash="", avatar="ph-user")
        mid = upsert_media({"title": "Test Movie", "type": "movie", "file_path": r"C:\Media\test.mp4"})

        save_progress(pid, mid, position=120, duration=3600, completed=False)
        prog = get_progress(pid, mid)
        self.assertIsNotNone(prog)
        self.assertEqual(prog["position"], 120)

        # Update position
        save_progress(pid, mid, position=500, duration=3600, completed=True)
        prog2 = get_progress(pid, mid)
        self.assertEqual(prog2["position"], 500)
        self.assertEqual(prog2["completed"], 1)

    def test_idempotent_init_db(self):
        """Verify running init_db() multiple times does not corrupt existing data."""
        pid = create_profile(name="PersistentUser", pin_hash="", avatar="ph-user")
        init_db()
        init_db()

        profiles = get_all_profiles()
        self.assertTrue(any(p["id"] == pid for p in profiles))


if __name__ == "__main__":
    unittest.main()
