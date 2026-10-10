# -*- coding: utf-8 -*-
"""
backend/tests/test_theme_music.py — Unit and integration tests for theme audio previews.
"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from backend.theme_music import (
    find_local_theme_file,
    find_cached_theme_file,
    resolve_theme_music,
    fetch_animethemes_audio,
    THEME_MUSIC_DIR,
)


def test_find_local_theme_file_in_item_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        media_file = os.path.join(tmpdir, "Movie.2024.mkv")
        with open(media_file, "w") as f:
            f.write("mock video")

        theme_file = os.path.join(tmpdir, "theme.mp3")
        with open(theme_file, "w") as f:
            f.write("mock theme audio")

        found = find_local_theme_file(media_file, is_series=False)
        assert found == theme_file


def test_find_local_theme_file_companion_pattern():
    with tempfile.TemporaryDirectory() as tmpdir:
        media_file = os.path.join(tmpdir, "Inception (2010).mkv")
        with open(media_file, "w") as f:
            f.write("mock video")

        theme_file = os.path.join(tmpdir, "Inception (2010).theme_song.mp3")
        with open(theme_file, "w") as f:
            f.write("mock theme audio")

        found = find_local_theme_file(media_file, is_series=False)
        assert found == theme_file


def test_find_local_theme_file_in_show_parent_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        show_dir = os.path.join(tmpdir, "Breaking Bad")
        season_dir = os.path.join(show_dir, "Season 01")
        os.makedirs(season_dir, exist_ok=True)

        ep_file = os.path.join(season_dir, "S01E01.mkv")
        with open(ep_file, "w") as f:
            f.write("mock episode")

        theme_file = os.path.join(show_dir, "theme.ogg")
        with open(theme_file, "w") as f:
            f.write("mock show theme")

        found = find_local_theme_file(ep_file, is_series=True)
        assert found == theme_file


def test_resolve_theme_music_local_precedence():
    with tempfile.TemporaryDirectory() as tmpdir:
        media_file = os.path.join(tmpdir, "Interstellar.2014.mkv")
        with open(media_file, "w") as f:
            f.write("content")

        theme_file = os.path.join(tmpdir, "theme.wav")
        with open(theme_file, "w") as f:
            f.write("audio")

        media = {
            "title": "Interstellar",
            "type": "movie",
            "file_path": media_file,
            "tmdb_id": 157336,
        }

        res = resolve_theme_music(media)
        assert res["has_theme"] is True
        assert res["source"] == "local"
        assert res["file_path"] == theme_file


def test_fetch_animethemes_audio_mock():
    mock_payload = {
        "anime": [
            {
                "name": "Frieren: Beyond Journey's End",
                "animethemes": [
                    {
                        "type": "OP",
                        "animethemeentries": [
                            {
                                "videos": [
                                    {
                                        "audio": {
                                            "link": "https://a.animethemes.moe/SousouNoFrieren-OP1.ogg"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    mock_stream = MagicMock()
    mock_stream.status_code = 200
    mock_stream.iter_content.return_value = [b"OGG_HEADER_DATA_12345" * 100]
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.__exit__.return_value = False

    with patch("requests.get", side_effect=[mock_resp, mock_stream]):
        res = fetch_animethemes_audio("Frieren: Beyond Journey's End", tmdb_id=209867)
        assert res is not None
        assert os.path.isfile(res)
        assert os.path.getsize(res) > 1000
        # Cleanup
        try:
            os.remove(res)
        except Exception:
            pass


def test_streaming_theme_music_route(monkeypatch):
    from flask import Flask
    from backend.routes.streaming import streaming_bp
    from backend.routes.media import media_bp
    from backend.db import upsert_media
    import backend.theme_music as tm

    app = Flask(__name__)
    app.secret_key = "test_theme_secret"
    app.register_blueprint(streaming_bp)
    app.register_blueprint(media_bp)
    client = app.test_client()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tf.write(b"MOCK_MP3_STREAM_CONTENT")
        tf_path = tf.name

    try:
        def mock_resolve(media_dict):
            return {
                "has_theme": True,
                "file_path": tf_path,
                "source": "mock",
                "title": media_dict.get("title", "")
            }

        monkeypatch.setattr(tm, "resolve_theme_music", mock_resolve)

        # Create dummy media
        media_id = upsert_media({
            "title": "Theme Test Movie",
            "type": "movie",
            "year": 2024,
            "duration": 3600,
            "file_path": tf_path,
            "file_size": 10000,
        })

        resp = client.get(f"/api/media/{media_id}/theme-music")
        assert resp.status_code in (200, 206)
        assert b"MOCK_MP3_STREAM_CONTENT" in resp.data

        # Check detail endpoint metadata
        detail_resp = client.get(f"/api/media/{media_id}")
        assert detail_resp.status_code == 200
        detail_json = detail_resp.get_json()
        assert detail_json.get("has_theme_music") is True
        assert detail_json.get("theme_music_url") == f"/api/media/{media_id}/theme-music"

    finally:
        try:
            from backend.db import delete_media_by_id
            if 'media_id' in locals() and media_id:
                delete_media_by_id(media_id)
        except Exception:
            pass
        try:
            os.remove(tf_path)
        except Exception:
            pass
