# -*- coding: utf-8 -*-
"""
Tests for Local Music Feature:
- Schema and database operations (backend/db/music.py)
- API routes (backend/routes/music.py)
- Music scanner helper functions (backend/music_scanner.py)
"""

import os
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask

from backend.db import get_conn, init_db
from backend.db.connection import release_conn
from backend.db import music as mdb
from backend.routes.music import music_bp
from backend.music_scanner import _find_lrc, _safe_int, get_music_scan_status


class TestMusicFeature(unittest.TestCase):
    def setUp(self):
        init_db()
        self.app = Flask(__name__)
        self.app.secret_key = "test_music_secret"
        self.app.register_blueprint(music_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()

    def tearDown(self):
        release_conn()

    def test_music_db_crud(self):
        """Test upserting and retrieving artists, albums, and tracks."""
        # 1. Artist
        artist_id = mdb.upsert_artist("Daft Punk", sort_name="Daft Punk")
        self.assertIsNotNone(artist_id)
        artist = mdb.get_artist(artist_id)
        self.assertEqual(artist["name"], "Daft Punk")

        # Duplicate upsert returns same id
        same_id = mdb.upsert_artist("Daft Punk")
        self.assertEqual(artist_id, same_id)

        # 2. Album
        album_id = mdb.upsert_album("Discovery", artist_id=artist_id, year=2001, genre="Electronic")
        self.assertIsNotNone(album_id)
        album = mdb.get_album(album_id)
        self.assertEqual(album["title"], "Discovery")
        self.assertEqual(album["year"], 2001)

        # 3. Track
        dummy_path = f"C:/fake_music/track_{os.urandom(4).hex()}.flac"
        track_id = mdb.upsert_track(
            file_path=dummy_path,
            title="One More Time",
            artist_id=artist_id,
            album_id=album_id,
            track_number=1,
            duration=320,
            fmt="flac",
            bitrate=1050,
            sample_rate=44100,
        )
        self.assertIsNotNone(track_id)
        track = mdb.get_track(track_id)
        self.assertEqual(track["title"], "One More Time")
        self.assertEqual(track["format"], "flac")
        self.assertEqual(track["duration"], 320)

        # 4. Search
        search_res = mdb.search_music("One More")
        self.assertTrue(any(t["id"] == track_id for t in search_res))

        # 5. Play record / History
        mdb.record_play(profile_id=1, track_id=track_id, duration_played=300)
        history = mdb.get_recently_played(profile_id=1)
        self.assertTrue(any(h["id"] == track_id for h in history))

        # 6. Favorites
        is_fav = mdb.toggle_favorite_track(profile_id=1, track_id=track_id)
        self.assertTrue(is_fav)
        favs = mdb.get_favorite_tracks(profile_id=1)
        self.assertTrue(any(f["id"] == track_id for f in favs))

        # Toggle off
        is_fav = mdb.toggle_favorite_track(profile_id=1, track_id=track_id)
        self.assertFalse(is_fav)

        # 7. Playlists
        pl_id = mdb.create_playlist(profile_id=1, name="Synth Favorites", description="Best synth tracks")
        self.assertIsNotNone(pl_id)
        playlists = mdb.get_playlists(profile_id=1)
        self.assertTrue(any(p["id"] == pl_id for p in playlists))

        mdb.add_to_playlist(pl_id, track_id)
        pl_tracks = mdb.get_playlist_tracks(pl_id)
        self.assertEqual(len(pl_tracks), 1)
        self.assertEqual(pl_tracks[0]["id"], track_id)

        mdb.delete_playlist(pl_id, profile_id=1)
        playlists_after = mdb.get_playlists(profile_id=1)
        self.assertFalse(any(p["id"] == pl_id for p in playlists_after))

    def test_remove_missing_tracks(self):
        """Verify deleted audio files are removed from the database."""
        artist_id = mdb.upsert_artist("Test Cleanup Artist")
        album_id = mdb.upsert_album("Test Cleanup Album", artist_id=artist_id)
        path1 = f"C:/fake_music/exists_{os.urandom(4).hex()}.flac"
        path2 = f"C:/fake_music/deleted_{os.urandom(4).hex()}.flac"

        t1 = mdb.upsert_track(path1, "Track 1", artist_id, album_id)
        t2 = mdb.upsert_track(path2, "Track 2", artist_id, album_id)

        # Retain only path1
        removed = mdb.remove_missing_tracks({path1})
        self.assertGreaterEqual(removed, 1)

        self.assertIsNotNone(mdb.get_track(t1))
        self.assertIsNone(mdb.get_track(t2))

    def test_music_api_endpoints(self):
        """Verify music REST endpoints respond with valid JSON."""
        # 1. Artists
        resp = self.client.get("/api/music/artists")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

        # 2. Albums
        resp = self.client.get("/api/music/albums")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

        # 3. Tracks
        resp = self.client.get("/api/music/tracks")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

        # 4. Scan Status
        resp = self.client.get("/api/music/scan/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("running", data)
        self.assertIn("phase", data)

        # 5. Favorites toggle via API
        with self.client.session_transaction() as sess:
            sess["profile_id"] = 1

        artist_id = mdb.upsert_artist("Api Artist")
        album_id = mdb.upsert_album("Api Album", artist_id=artist_id)
        tid = mdb.upsert_track(f"C:/fake/track_api_{os.urandom(4).hex()}.flac", "Api Track", artist_id, album_id)

        fav_resp = self.client.post("/api/music/favorites", json={"track_id": tid})
        self.assertEqual(fav_resp.status_code, 200)
        fav_data = fav_resp.get_json()
        self.assertTrue(fav_data["ok"])

    def test_lrc_finder(self):
        """Verify _find_lrc finds accompanying .lrc file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "song.flac")
            lrc_path = os.path.join(tmpdir, "song.lrc")
            with open(audio_path, "wb") as f:
                f.write(b"fakeaudio")
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write("[00:10.00]Hello world\n[00:15.50]Next line\n")

            found = _find_lrc(audio_path)
            self.assertEqual(found, lrc_path)

            no_lrc = _find_lrc(os.path.join(tmpdir, "other.flac"))
            self.assertIsNone(no_lrc)

    def test_safe_int(self):
        """Verify track number string splitting and int parsing."""
        self.assertEqual(_safe_int("5"), 5)
        self.assertEqual(_safe_int("3/12"), 3)
        self.assertEqual(_safe_int(None, 1), 1)
        self.assertEqual(_safe_int(["7"]), 7)


if __name__ == "__main__":
    unittest.main()
