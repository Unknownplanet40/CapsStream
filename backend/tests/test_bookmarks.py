# -*- coding: utf-8 -*-
"""
test_bookmarks.py — Unit and integration tests for CapsStream Moments (bookmarks).
Covers database CRUD, profile privacy & family sharing, updates, cascade deletion, and Flask route endpoints.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from backend.db.connection import _apply_pragmas
from backend.db.bookmarks import (
    create_bookmark,
    get_bookmark,
    get_bookmarks_for_media,
    get_bookmarks_for_profile,
    update_bookmark,
    delete_bookmark,
)
from backend.routes.media import media_bp


class TestBookmarksDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_capsstream.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        _apply_pragmas(self.conn)

        # Setup minimal schema
        self.conn.executescript("""
            CREATE TABLE profiles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                pin_hash   TEXT,
                avatar     TEXT DEFAULT 'ph-film-strip',
                color      TEXT DEFAULT '#e50914',
                is_admin   INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE media (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                type       TEXT NOT NULL,
                tmdb_id    INTEGER,
                title      TEXT NOT NULL,
                year       INTEGER,
                season     INTEGER,
                episode    INTEGER,
                ep_title   TEXT,
                file_path  TEXT NOT NULL UNIQUE,
                duration   INTEGER DEFAULT 3600,
                poster_path TEXT,
                backdrop_path TEXT
            );

            CREATE TABLE bookmarks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                media_id   INTEGER NOT NULL,
                position   INTEGER NOT NULL DEFAULT 0,
                note       TEXT DEFAULT '',
                category   TEXT DEFAULT 'general',
                color      TEXT DEFAULT '#e50914',
                is_shared  INTEGER NOT NULL DEFAULT 0,
                thumb_path TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
            );
        """)

        # Seed data
        self.conn.execute("INSERT INTO profiles (name, is_admin) VALUES ('AdminUser', 1)")
        self.conn.execute("INSERT INTO profiles (name, is_admin) VALUES ('FamilyUser', 0)")
        self.conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, file_path, duration)
            VALUES ('movie', 550, 'Fight Club', 1999, '/movies/fight_club.mkv', 8340)
        """)
        self.conn.commit()

        # Patch get_conn to use self.conn
        self.conn_patcher = patch("backend.db.bookmarks.get_conn", side_effect=self._get_test_conn)
        self.conn_patcher.start()

    def _get_test_conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        _apply_pragmas(c)
        return c

    def tearDown(self):
        self.conn_patcher.stop()
        self.conn.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_and_get_bookmark(self):
        """Verify creating a bookmark returns full details including media and profile."""
        bm = create_bookmark(
            profile_id=1,
            media_id=1,
            position=1240,
            note="Rule #1 of Fight Club",
            category="quote",
            color="#10b981",
            is_shared=False,
            thumb_path=""
        )
        self.assertIsNotNone(bm)
        self.assertEqual(bm["profile_id"], 1)
        self.assertEqual(bm["media_id"], 1)
        self.assertEqual(bm["position"], 1240)
        self.assertEqual(bm["note"], "Rule #1 of Fight Club")
        self.assertEqual(bm["category"], "quote")
        self.assertEqual(bm["color"], "#10b981")
        self.assertFalse(bm["is_shared"])
        self.assertEqual(bm["media_title"], "Fight Club")
        self.assertEqual(bm["profile_name"], "AdminUser")

    def test_media_bookmarks_visibility_and_family_sharing(self):
        """Verify private bookmarks are hidden from other profiles, while shared ones are visible."""
        # Profile 1 creates a private bookmark
        create_bookmark(1, 1, 100, note="Private P1", is_shared=False)
        # Profile 1 creates a shared bookmark
        create_bookmark(1, 1, 200, note="Shared P1", is_shared=True)
        # Profile 2 creates a private bookmark
        create_bookmark(2, 1, 300, note="Private P2", is_shared=False)

        # Profile 1 sees their private, their shared, and does not see Profile 2's private
        p1_list = get_bookmarks_for_media(1, profile_id=1)
        self.assertEqual(len(p1_list), 2)
        notes_p1 = [b["note"] for b in p1_list]
        self.assertIn("Private P1", notes_p1)
        self.assertIn("Shared P1", notes_p1)

        # Profile 2 sees Profile 1's shared bookmark and their own private bookmark
        p2_list = get_bookmarks_for_media(1, profile_id=2)
        self.assertEqual(len(p2_list), 2)
        notes_p2 = [b["note"] for b in p2_list]
        self.assertIn("Shared P1", notes_p2)
        self.assertIn("Private P2", notes_p2)

    def test_update_bookmark(self):
        """Verify updating note, category, color, and sharing status."""
        bm = create_bookmark(1, 1, 500, note="Initial note", category="general")
        bm_id = bm["id"]

        updated = update_bookmark(
            bookmark_id=bm_id,
            profile_id=1,
            note="Updated note",
            category="action",
            color="#e50914",
            is_shared=True
        )
        self.assertEqual(updated["note"], "Updated note")
        self.assertEqual(updated["category"], "action")
        self.assertTrue(updated["is_shared"])

        # Profile 2 (non-admin) cannot update Profile 1's bookmark
        denied = update_bookmark(bm_id, profile_id=2, note="Hacked")
        self.assertIsNone(denied)

    def test_delete_bookmark(self):
        """Verify deleting a bookmark removes it and unauthorized profiles cannot delete."""
        bm = create_bookmark(1, 1, 500, note="To be deleted")
        bm_id = bm["id"]

        # Profile 2 (non-admin) cannot delete
        self.assertFalse(delete_bookmark(bm_id, profile_id=2))
        self.assertIsNotNone(get_bookmark(bm_id))

        # Profile 1 can delete
        self.assertTrue(delete_bookmark(bm_id, profile_id=1))
        self.assertIsNone(get_bookmark(bm_id))

    def test_cascade_delete_on_media_removal(self):
        """Verify deleting media item cascades and removes all bookmarks."""
        create_bookmark(1, 1, 100, note="Cascade test")
        conn = self._get_test_conn()
        conn.execute("DELETE FROM media WHERE id = 1")
        conn.commit()
        conn.close()

        bms = get_bookmarks_for_media(1)
        self.assertEqual(len(bms), 0)


class TestBookmarksRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_bookmarks_secret"
        self.app.register_blueprint(media_bp)
        self.client = self.app.test_client()

    @patch("backend.routes.media.get_bookmarks_for_media")
    def test_api_get_media_bookmarks(self, mock_get):
        mock_get.return_value = [{"id": 1, "position": 120, "note": "Test moment"}]
        resp = self.client.get("/api/media/10/bookmarks?profile_id=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["bookmarks"][0]["note"], "Test moment")

    @patch("backend.routes.media.get_media_by_id")
    @patch("backend.routes.media.create_bookmark")
    def test_api_create_media_bookmark(self, mock_create, mock_get_media):
        mock_get_media.return_value = {"id": 10, "title": "Test Title"}
        mock_create.return_value = {"id": 1, "media_id": 10, "position": 250, "note": "Awesome fight"}

        resp = self.client.post("/api/media/10/bookmarks", json={
            "profile_id": 1,
            "position": 250,
            "note": "Awesome fight",
            "category": "action",
            "color": "#e50914"
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["bookmark"]["note"], "Awesome fight")

    @patch("backend.routes.media.update_bookmark")
    def test_api_update_bookmark(self, mock_update):
        mock_update.return_value = {"id": 1, "note": "New note"}
        resp = self.client.patch("/api/bookmarks/1", json={"note": "New note", "profile_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    @patch("backend.routes.media.delete_bookmark")
    def test_api_delete_bookmark(self, mock_delete):
        mock_delete.return_value = True
        resp = self.client.delete("/api/bookmarks/1?profile_id=1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    @patch("backend.routes.media.get_bookmarks_for_profile")
    def test_api_get_profile_bookmarks(self, mock_get_prof):
        mock_get_prof.return_value = [{"id": 1, "title": "Fight Club", "note": "Iconic"}]
        resp = self.client.get("/api/profile/1/bookmarks?category=all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
