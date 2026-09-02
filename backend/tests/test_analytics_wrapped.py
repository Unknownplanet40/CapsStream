# -*- coding: utf-8 -*-
"""
Tests for Wrapped & Analytics (backend/db/stats.py & backend/routes/social.py)
"""
import unittest
import sqlite3
from unittest.mock import patch
from flask import Flask

from backend.routes.social import social_bp
from backend.db.stats import get_profile_wrapped_analytics


class TestAnalyticsWrapped(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_wrapped_secret"
        self.app.register_blueprint(social_bp)
        self.client = self.app.test_client()

    @patch("backend.db.get_profile_wrapped_analytics")
    def test_api_get_wrapped_analytics_route(self, mock_get_wrapped):
        """Verify GET /api/analytics/wrapped dispatches and returns JSON payload."""
        mock_get_wrapped.return_value = {
            "period": "year",
            "year": 2026,
            "overview": {"total_hours": 42.5, "completion_rate": 88.0},
            "archetype": {"title": "Midnight Binge Lord"}
        }

        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        resp = self.client.get("/api/analytics/wrapped?period=year&year=2026")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["period"], "year")
        self.assertEqual(data["overview"]["total_hours"], 42.5)
        self.assertEqual(data["archetype"]["title"], "Midnight Binge Lord")

    @patch("backend.db.stats.get_conn")
    def test_get_profile_wrapped_analytics_calculation(self, mock_get_conn):
        """Verify aggregation logic with mocked SQLite database queries."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Set up minimal schema
        c.execute("""
            CREATE TABLE media (
                id INTEGER PRIMARY KEY,
                type TEXT,
                tmdb_id INTEGER,
                title TEXT,
                original_title TEXT,
                year INTEGER,
                season INTEGER,
                episode INTEGER,
                ep_title TEXT,
                duration INTEGER,
                genres TEXT,
                rating REAL,
                poster_path TEXT,
                backdrop_path TEXT,
                file_path TEXT,
                file_size INTEGER,
                cast_json TEXT
            )
        """)
        c.execute("""
            CREATE TABLE watch_progress (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER,
                media_id INTEGER,
                position INTEGER,
                duration INTEGER,
                completed INTEGER,
                updated_at DATETIME
            )
        """)
        c.execute("""
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY,
                name TEXT,
                default_audio_lang TEXT,
                default_sub_lang TEXT
            )
        """)
        c.execute("INSERT INTO profiles (id, name, default_audio_lang, default_sub_lang) VALUES (1, 'Tester', 'ja', 'en')")

        # Insert sample media
        c.execute("""
            INSERT INTO media (id, type, tmdb_id, title, year, genres, rating, file_path, cast_json)
            VALUES (1, 'movie', 101, 'Interstellar', 2014, 'Sci-Fi, Adventure', 8.6, 'C:\\media\\interstellar.mkv',
                    '[{"name": "Matthew McConaughey", "character": "Cooper", "profile": "/mcconaughey.jpg"}]')
        """)
        c.execute("""
            INSERT INTO media (id, type, tmdb_id, title, year, season, episode, genres, rating, file_path, cast_json)
            VALUES (2, 'series', 202, 'Breaking Bad', 2008, 1, 1, 'Drama, Crime', 9.5, 'C:\\media\\bb_s01e01.mkv',
                    '[{"name": "Bryan Cranston", "character": "Walter White", "profile_path": "/cranston.jpg"}]')
        """)

        # Insert watch progress across multiple dates
        c.execute("""
            INSERT INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at)
            VALUES (1, 1, 7200, 7200, 1, '2026-03-15 22:30:00')
        """)
        c.execute("""
            INSERT INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at)
            VALUES (1, 2, 3600, 3600, 1, '2026-03-16 23:15:00')
        """)
        conn.commit()

        # Mock connection to return our in-memory connection
        mock_get_conn.return_value = conn

        res = get_profile_wrapped_analytics(1, period="year", year=2026)
        self.assertIsNotNone(res)
        self.assertEqual(res["overview"]["total_seconds"], 10800)
        self.assertEqual(res["overview"]["total_hours"], 3.0)
        self.assertEqual(res["overview"]["completed_items"], 2)
        self.assertEqual(res["overview"]["completion_rate"], 100.0)

        # Check Heatmap & Streaks
        self.assertGreaterEqual(len(res["heatmap"]["days"]), 365)
        self.assertEqual(len(res["heatmap"]["days"]) % 7, 0)
        self.assertIn("month_labels", res["heatmap"])
        self.assertIn("weeks_count", res["heatmap"])
        self.assertEqual(res["heatmap"]["days_active"], 2)
        self.assertEqual(res["heatmap"]["longest_streak"], 2)

        # Check Binge Records
        self.assertIsNotNone(res["binge_records"]["biggest_binge_day"])

        # Check Cast / Talent
        self.assertTrue(any(a["name"] == "Matthew McConaughey" and a["profile_path"] == "/mcconaughey.jpg" for a in res["talent"]["top_actors"]))
        self.assertTrue(any(a["name"] == "Bryan Cranston" and a["profile_path"] == "/cranston.jpg" for a in res["talent"]["top_actors"]))

        # Check Archetype was generated
        self.assertIn("title", res["archetype"])
        self.assertIn("tagline", res["archetype"])

        # Check Top Obsession
        self.assertIsNotNone(res["top_obsession"])
        self.assertEqual(res["top_obsession"]["title"], "Interstellar")
        self.assertEqual(res["top_obsession"]["hours"], 2.0)

        # Check Audio & Subtitle DNA
        self.assertIn("preferred_audio", res["audio_sub_dna"])
        self.assertIn("sub_style", res["audio_sub_dna"])

        # Check Speed Binge & Streaks
        self.assertEqual(res["speed_binge"]["longest_streak"], 2)

        # Check Tech Specs
        self.assertIn("total_gb_streamed", res["tech_specs"])
        self.assertIn("direct_play_pct", res["tech_specs"])

        # Check Quizzes
        self.assertIsNotNone(res["quizzes"]["genre"])
        self.assertEqual(res["quizzes"]["genre"]["correct_answer"], "Sci-Fi")
        self.assertGreaterEqual(len(res["quizzes"]["genre"]["options"]), 2)
        self.assertTrue(any(o["is_correct"] for o in res["quizzes"]["genre"]["options"]))

        self.assertIsNotNone(res["quizzes"]["talent"])
        self.assertGreaterEqual(len(res["quizzes"]["talent"]["options"]), 2)


if __name__ == "__main__":
    unittest.main()

