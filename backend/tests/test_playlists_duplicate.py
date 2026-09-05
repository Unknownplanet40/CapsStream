# -*- coding: utf-8 -*-
import unittest
from flask import Flask
from backend.tests import create_isolated_test_db
from backend.db.connection import get_conn, release_conn
from backend.db.playlists import (
    create_playlist,
    add_to_playlist,
    is_media_in_playlist,
    get_playlists,
    get_playlist,
)
from backend.routes.library import library_bp


class TestPlaylistsDuplicate(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        conn = get_conn()
        conn.execute("INSERT INTO profiles (id, name, avatar, is_admin) VALUES (1, 'Test User', 'avatar1', 1)")
        conn.execute("INSERT INTO media (id, title, type, file_path) VALUES (10, 'Sample Movie', 'movie', 'C:/test.mp4')")
        conn.commit()
        conn.close()

        self.app = Flask(__name__)
        self.app.secret_key = "test_playlist_secret"
        self.app.register_blueprint(library_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()

    def tearDown(self):
        self.cleanup_db()

    def test_item_ids_and_duplicate_detection(self):
        pl_id = create_playlist(profile_id=1, name="My Test Playlist")

        # Initially media 10 is not in playlist
        self.assertFalse(is_media_in_playlist(pl_id, 10))

        # Add media 10 to playlist
        item_id = add_to_playlist(pl_id, 10, profile_id=1)
        self.assertIsNotNone(item_id)

        # Now media 10 is in playlist
        self.assertTrue(is_media_in_playlist(pl_id, 10))

        # get_playlists includes item_ids
        lists = get_playlists(profile_id=1)
        self.assertEqual(len(lists), 1)
        self.assertIn(10, lists[0]["item_ids"])

        # get_playlist includes item_ids
        single = get_playlist(pl_id, profile_id=1)
        self.assertIsNotNone(single)
        self.assertIn(10, single["item_ids"])

        # Add duplicate
        dup_id = add_to_playlist(pl_id, 10, profile_id=1)
        self.assertIsNotNone(dup_id)
        single_dup = get_playlist(pl_id, profile_id=1)
        self.assertEqual(len(single_dup["items"]), 2)

    def test_api_add_to_playlist_duplicate_flag(self):
        pl_id = create_playlist(profile_id=1, name="API Test Playlist")

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        # First add: already_in_playlist should be False
        res1 = self.client.post(f"/api/playlists/{pl_id}/items", json={"media_id": 10})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1.get("ok"))
        self.assertFalse(data1.get("already_in_playlist"))

        # Second add: already_in_playlist should be True
        res2 = self.client.post(f"/api/playlists/{pl_id}/items", json={"media_id": 10})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2.get("ok"))
        self.assertTrue(data2.get("already_in_playlist"))


if __name__ == "__main__":
    unittest.main()
