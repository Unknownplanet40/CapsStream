# -*- coding: utf-8 -*-
import json
import unittest
from flask import Flask

from backend.tests import create_isolated_test_db
from backend.db.connection import get_conn, release_conn
from backend.db.playback import (
    get_similar_media,
    get_profile_recommendations,
    save_progress,
)
from backend.franchises import get_media_franchise
from backend.routes.media import media_bp, bust_home_cache


class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        conn = get_conn()

        # Insert profiles (Profile 1: Adult admin, Profile 2: Kids)
        conn.execute("INSERT INTO profiles (id, name, avatar, is_admin, is_kids) VALUES (1, 'Adult User', 'avatar1', 1, 0)")
        conn.execute("INSERT INTO profiles (id, name, avatar, is_admin, is_kids) VALUES (2, 'Kids User', 'avatar2', 0, 1)")

        # Insert test media items
        media_records = [
            (
                1, "The Dark Knight", "movie", "C:/movies/tdk.mp4",
                "Action, Crime, Drama",
                json.dumps([{"name": "Christian Bale"}, {"name": "Heath Ledger"}]),
                2008, 9.0, 152 * 60, "PG-13", 155
            ),
            (
                2, "Batman Begins", "movie", "C:/movies/bb.mp4",
                "Action, Crime, Drama",
                json.dumps([{"name": "Christian Bale"}, {"name": "Michael Caine"}]),
                2005, 8.2, 140 * 60, "PG-13", 272
            ),
            (
                3, "The Prestige", "movie", "C:/movies/prestige.mp4",
                "Drama, Mystery, Sci-Fi",
                json.dumps([{"name": "Christian Bale"}, {"name": "Hugh Jackman"}]),
                2006, 8.5, 130 * 60, "PG-13", 1124
            ),
            (
                4, "Inception", "movie", "C:/movies/inception.mp4",
                "Action, Adventure, Sci-Fi",
                json.dumps([{"name": "Leonardo DiCaprio"}, {"name": "Joseph Gordon-Levitt"}]),
                2010, 8.8, 148 * 60, "PG-13", 27205
            ),
            (
                5, "Toy Story", "movie", "C:/movies/toystory.mp4",
                "Animation, Adventure, Comedy",
                json.dumps([{"name": "Tom Hanks"}, {"name": "Tim Allen"}]),
                1995, 8.3, 81 * 60, "G", 862
            ),
        ]

        for m in media_records:
            conn.execute(
                """
                INSERT INTO media (id, title, type, file_path, genres, cast_json, year, rating, duration, certification, tmdb_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                m
            )
        conn.commit()
        conn.close()

        self.app = Flask(__name__)
        self.app.secret_key = "test_recs_secret"
        self.app.register_blueprint(media_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()
        bust_home_cache()

    def tearDown(self):
        self.cleanup_db()

    def test_get_similar_media(self):
        similar = get_similar_media(1, limit=5)
        self.assertTrue(len(similar) > 0)
        # Media 1 itself should never be in similar
        self.assertNotIn(1, [item["id"] for item in similar])

        # Media 2 (Batman Begins) shares Nolan + Christian Bale + Action/Crime/Drama
        # Media 3 (The Prestige) shares Nolan + Christian Bale + Drama
        top_ids = [item["id"] for item in similar[:2]]
        self.assertIn(2, top_ids)
        self.assertIn(3, top_ids)

    def test_get_profile_recommendations_high_engagement(self):
        # 1. Low progress (10%) should NOT generate recommendations
        save_progress(profile_id=1, media_id=1, position=900, duration=9000) # 10%
        recs_low = get_profile_recommendations(profile_id=1, limit=3)
        self.assertEqual(len(recs_low), 0)

        # 2. High progress (75%) should generate recommendations
        save_progress(profile_id=1, media_id=1, position=6750, duration=9000) # 75%
        recs_high = get_profile_recommendations(profile_id=1, limit=3)
        self.assertEqual(len(recs_high), 1)
        self.assertEqual(recs_high[0]["type"], "recommendation")
        self.assertIn("The Dark Knight", recs_high[0]["title"])
        shelf_ids = [it["id"] for it in recs_high[0]["items"]]
        self.assertIn(2, shelf_ids)
        self.assertNotIn(1, shelf_ids)

    def test_get_profile_recommendations_favorites_fallback(self):
        # When no watch progress exists, favorites should serve as seeds
        conn = get_conn()
        conn.execute("INSERT INTO favorites (profile_id, media_id) VALUES (1, 4)") # Inception
        conn.commit()
        conn.close()

        recs = get_profile_recommendations(profile_id=1, limit=2)
        self.assertEqual(len(recs), 1)
        self.assertIn("Inception", recs[0]["title"])
        shelf_ids = [it["id"] for it in recs[0]["items"]]
        self.assertNotIn(4, shelf_ids)

    def test_get_media_franchise_sequence_and_current(self):
        conn = get_conn()
        from backend.db.media import get_all_media
        all_media = get_all_media()
        conn.close()

        # The Dark Knight and Batman Begins match Batman/Dark Knight patterns
        tdk = next(m for m in all_media if m["id"] == 1)
        franchise = get_media_franchise(tdk, all_media)

        if franchise:
            items = franchise.get("items", [])
            self.assertTrue(len(items) >= 2)
            # Find current item
            current_item = next((it for it in items if it["id"] == 1), None)
            self.assertIsNotNone(current_item)
            self.assertTrue(current_item.get("is_current"))
            # Sibling should not be marked current
            sibling = next((it for it in items if it["id"] == 2), None)
            self.assertIsNotNone(sibling)
            self.assertFalse(sibling.get("is_current"))
            # Sequence numbers should be positive integers
            self.assertTrue(current_item.get("sequence_number") > 0)
            self.assertTrue(sibling.get("sequence_number") > 0)

    from unittest.mock import patch

    @patch("backend.audio_probe.probe_audio_tracks", return_value=[])
    @patch("backend.matcher.ensure_media_logo")
    @patch("backend.matcher.fetch_imdb_id", return_value="tt0468569")
    @patch("backend.matcher.fetch_media_backdrops", return_value=[])
    def test_api_media_similar_and_detail(self, mock_backdrops, mock_imdb, mock_logo, mock_audio):
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        # Test GET /api/media/<id>/similar
        resp = self.client.get("/api/media/1/similar")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        self.assertNotIn(1, [it["id"] for it in data])

        # Test GET /api/media/<id> detail includes similar_items
        detail_resp = self.client.get("/api/media/1")
        self.assertEqual(detail_resp.status_code, 200)
        detail_data = detail_resp.get_json()
        self.assertIn("similar_items", detail_data)
        self.assertIsInstance(detail_data["similar_items"], list)
