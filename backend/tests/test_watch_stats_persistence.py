# -*- coding: utf-8 -*-
"""
Tests for Watch Stats Persistence & Resilient Watch History
Verifies that:
1. save_progress dual-writes to watch_progress and watch_history.
2. Removing media / disconnecting drives does not delete watch_history.
3. Profile watch stats & wrapped analytics survive media row deletion.
4. Re-scanning media automatically restores watch_progress from watch_history.
5. clear_cache() preserves database records and watch statistics.
"""
import os
import unittest
import sqlite3
import tempfile
import shutil
from unittest.mock import patch

from backend.tests import create_isolated_test_db
from backend.db.playback import save_progress, get_progress, restore_progress_for_media
from backend.db.stats import get_profile_watch_stats, get_profile_wrapped_analytics
from backend.db.media import upsert_media
from backend.settings import clear_cache


class TestWatchStatsPersistence(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()

        # Create a test profile
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO profiles (id, name, avatar, is_admin) VALUES (1, 'TestUser', 'avatar.png', 1)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.cleanup_db()

    def test_save_progress_dual_writes_to_watch_history(self):
        """Verify save_progress records to both active watch_progress and persistent watch_history."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Insert a media item
        media_id = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, season, episode, ep_title, duration, genres, file_path)
            VALUES ('series', 1399, 'Game of Thrones', 2011, 1, 1, 'Winter Is Coming', 3600, 'Drama, Fantasy', 'D:\\TV\\GoT_S01E01.mkv')
        """).lastrowid
        conn.commit()
        conn.close()

        # Save progress
        save_progress(profile_id=1, media_id=media_id, position=1800, duration=3600)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Verify watch_progress
        wp = conn.execute("SELECT * FROM watch_progress WHERE profile_id=1 AND media_id=?", (media_id,)).fetchone()
        self.assertIsNotNone(wp)
        self.assertEqual(wp["position"], 1800)
        self.assertEqual(wp["duration"], 3600)

        # Verify watch_history
        wh = conn.execute("SELECT * FROM watch_history WHERE profile_id=1 AND tmdb_id=1399 AND season=1 AND episode=1").fetchone()
        self.assertIsNotNone(wh)
        self.assertEqual(wh["title"], "Game of Thrones")
        self.assertEqual(wh["ep_title"], "Winter Is Coming")
        self.assertEqual(wh["genres"], "Drama, Fantasy")
        self.assertEqual(wh["position"], 1800)
        self.assertEqual(wh["duration"], 3600)
        conn.close()

    def test_stats_persist_after_media_and_drive_removed(self):
        """Verify that when a drive is removed and media rows are deleted, watch stats remain accurate."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Insert media
        m1 = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, duration, genres, file_path)
            VALUES ('movie', 27205, 'Inception', 2010, 8880, 'Action, Sci-Fi', 'E:\\Movies\\Inception.mkv')
        """).lastrowid
        m2 = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, season, episode, ep_title, duration, genres, file_path)
            VALUES ('anime', 30984, 'Bleach', 2004, 1, 1, 'The Day I Became a Shinigami', 1440, 'Animation, Action', 'E:\\Anime\\Bleach_01.mkv')
        """).lastrowid
        conn.commit()
        conn.close()

        # Save progress (one completed, one partial)
        save_progress(profile_id=1, media_id=m1, position=8880, duration=8880, completed=True)
        save_progress(profile_id=1, media_id=m2, position=720, duration=1440, completed=False)

        # Simulate drive removal (deleting media records which cascades to watch_progress)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM media WHERE id IN (?, ?)", (m1, m2))
        conn.commit()

        # Ensure active watch_progress was removed by cascade
        wp_rows = conn.execute("SELECT COUNT(*) as count FROM watch_progress WHERE profile_id=1").fetchone()
        self.assertEqual(wp_rows[0], 0)

        # Ensure watch_history persisted
        wh_rows = conn.execute("SELECT COUNT(*) as count FROM watch_history WHERE profile_id=1").fetchone()
        self.assertEqual(wh_rows[0], 2)
        conn.close()

        # Check that get_profile_watch_stats returns non-zero stats
        stats = get_profile_watch_stats(1)
        self.assertEqual(stats["total_items"], 2)
        self.assertEqual(stats["completed_items"], 1)
        self.assertEqual(stats["total_seconds"], 8880 + 720)
        self.assertGreater(stats["total_seconds"] / 3600.0, 2.0)
        genre_names = [g["genre"] for g in stats["top_genres"]]
        self.assertIn("Action", genre_names)

        # Check Wrapped Analytics
        wrapped = get_profile_wrapped_analytics(1, period="all")
        self.assertEqual(wrapped["overview"]["total_seconds"], 8880 + 720)
        self.assertEqual(wrapped["overview"]["completed_items"], 1)

    def test_auto_restore_progress_on_rescan(self):
        """Verify that when a media file is re-added, restore_progress_for_media restores watch_progress."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Insert initially
        media_id = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, year, season, episode, ep_title, duration, genres, file_path)
            VALUES ('series', 60059, 'Better Call Saul', 2015, 1, 1, 'Uno', 3180, 'Crime, Drama', 'F:\\TV\\BCS_S01E01.mkv')
        """).lastrowid
        conn.commit()
        conn.close()

        # User watched half the episode
        save_progress(profile_id=1, media_id=media_id, position=1500, duration=3180)

        # Simulate drive disconnection & media wipe
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM media WHERE id=?", (media_id,))
        conn.commit()
        conn.close()

        # Re-connect drive and re-scan: upsert_media
        new_item = {
            "type": "series",
            "tmdb_id": 60059,
            "title": "Better Call Saul",
            "year": 2015,
            "season": 1,
            "episode": 1,
            "ep_title": "Uno",
            "duration": 3180,
            "genres": "Crime, Drama",
            "file_path": "F:\\TV\\BCS_S01E01.mkv",
            "file_size": 1048576,
        }
        new_id = upsert_media(new_item)

        # Verify active watch_progress is restored
        restored_wp = get_progress(profile_id=1, media_id=new_id)
        self.assertIsNotNone(restored_wp)
        self.assertEqual(restored_wp["position"], 1500)
        self.assertEqual(restored_wp["duration"], 3180)

    def test_clear_cache_does_not_delete_media_or_watch_data(self):
        """Verify clear_cache only deletes disk metadata files and leaves media, progress, and history untouched."""
        conn = sqlite3.connect(self.db_path)
        m_id = conn.execute("""
            INSERT INTO media (type, tmdb_id, title, file_path)
            VALUES ('movie', 9999, 'Cache Test Movie', 'C:\\dummy.mkv')
        """).lastrowid
        conn.commit()
        conn.close()

        save_progress(profile_id=1, media_id=m_id, position=500, duration=1000)

        # Call clear_cache()
        temp_root = tempfile.mkdtemp()
        os.makedirs(os.path.join(temp_root, "data", "metadata"), exist_ok=True)
        try:
            with patch("backend.settings.ROOT_DIR", temp_root):
                res = clear_cache()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        conn = sqlite3.connect(self.db_path)
        # Media must still exist
        media_cnt = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        self.assertEqual(media_cnt, 1)

        # watch_progress must still exist
        wp_cnt = conn.execute("SELECT COUNT(*) FROM watch_progress").fetchone()[0]
        self.assertEqual(wp_cnt, 1)

        # watch_history must still exist
        wh_cnt = conn.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0]
        self.assertEqual(wh_cnt, 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
