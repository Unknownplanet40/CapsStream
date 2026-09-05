# -*- coding: utf-8 -*-
import unittest
from flask import Flask
from backend.tests import create_isolated_test_db
from backend.db.connection import get_conn, release_conn
from backend.routes.library import library_bp


class TestCollectionToPlaylist(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        conn = get_conn()
        conn.execute("INSERT INTO profiles (id, name, avatar, is_admin) VALUES (1, 'Test User', 'avatar1', 1)")
        conn.execute("INSERT INTO media (id, title, type, file_path) VALUES (10, 'Iron Man', 'movie', 'C:/movies/ironman.mp4')")
        conn.execute("INSERT INTO media (id, title, type, file_path) VALUES (11, 'Thor', 'movie', 'C:/movies/thor.mp4')")
        # Series episodes
        conn.execute("INSERT INTO media (id, title, type, file_path, tmdb_id, season, episode) VALUES (20, 'Loki', 'series', 'C:/shows/loki_s1e1.mp4', 100, 1, 1)")
        conn.execute("INSERT INTO media (id, title, type, file_path, tmdb_id, season, episode) VALUES (21, 'Loki', 'series', 'C:/shows/loki_s1e2.mp4', 100, 1, 2)")
        conn.commit()
        conn.close()

        self.app = Flask(__name__)
        self.app.secret_key = "test_collection_to_playlist_secret"
        self.app.register_blueprint(library_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()

    def tearDown(self):
        self.cleanup_db()

    def test_convert_movies_to_playlist(self):
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        payload = {
            "name": "Marvel Movie Marathon",
            "description": "MCU movies in order",
            "is_shared": True,
            "items": [
                {"id": 10, "type": "movie", "title": "Iron Man"},
                {"id": 11, "type": "movie", "title": "Thor"},
            ]
        }
        res = self.client.post("/api/collections/convert-to-playlist", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["name"], "Marvel Movie Marathon")
        self.assertEqual(data["description"], "MCU movies in order")
        self.assertTrue(data["is_shared"])
        self.assertEqual(len(data.get("items", [])), 2)
        item_mids = [i["id"] for i in data["items"]]
        self.assertEqual(item_mids, [10, 11])

    def test_convert_series_single_episode_per_show(self):
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        payload = {
            "name": "Shows Queue",
            "include_all_episodes": False,
            "items": [
                {"id": 20, "type": "series", "tmdb_id": 100, "title": "Loki"},
                {"id": 10, "type": "movie", "title": "Iron Man"}
            ]
        }
        res = self.client.post("/api/collections/convert-to-playlist", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(len(data.get("items", [])), 2)
        item_mids = [i["id"] for i in data["items"]]
        self.assertEqual(item_mids, [20, 10])

    def test_convert_series_expand_all_episodes(self):
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        payload = {
            "name": "Binge Loki and Movies",
            "include_all_episodes": True,
            "items": [
                {"id": 20, "type": "series", "tmdb_id": 100, "title": "Loki"},
                {"id": 10, "type": "movie", "title": "Iron Man"}
            ]
        }
        res = self.client.post("/api/collections/convert-to-playlist", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        # Should have Loki S1E1 (20), Loki S1E2 (21), and Iron Man (10)
        self.assertEqual(len(data.get("items", [])), 3)
        item_mids = [i["id"] for i in data["items"]]
        self.assertEqual(item_mids, [20, 21, 10])

    def test_convert_validation(self):
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        # Missing name
        res = self.client.post("/api/collections/convert-to-playlist", json={"items": [{"id": 10}]})
        self.assertEqual(res.status_code, 400)

        # Missing items
        res = self.client.post("/api/collections/convert-to-playlist", json={"name": "Empty"})
        self.assertEqual(res.status_code, 400)
