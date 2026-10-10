# -*- coding: utf-8 -*-
"""
Tests for Subtitles Module (backend/subtitles.py)
Covers subtitle label parsing, SDH detection, language mapping,
external subtitle discovery, and SRT/VTT formatting.
"""
import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from backend.subtitles import _parse_sub_label, get_all_subtitles, LANG_NAMES, promote_subs_to_media_folder


class TestSubtitles(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_subs_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_sub_label_languages(self):
        """Verify language codes in subtitle filenames map to user-friendly display labels."""
        test_cases = [
            ("Inception.en.srt", "English", "en"),
            ("Movie.Spanish.srt", "Spanish", "spa"),
            ("Show.S01E01.Japanese.vtt", "Japanese", "jpn"),
            ("Film.fr.srt", "French", "fr"),
            ("Video.ger.srt", "German", "ger"),
            ("Anime.tag.srt", "Filipino", "tag"),
        ]

        for fname, expected_lang_name, expected_code in test_cases:
            label, lang, is_sdh, _ = _parse_sub_label(fname)
            self.assertIn(expected_lang_name.lower(), label.lower(), f"Failed label parse for {fname}")
            self.assertFalse(is_sdh, f"Did not expect SDH for {fname}")

    def test_parse_sub_label_sdh_detection(self):
        """Verify SDH, CC, and Hearing Impaired tags are correctly detected."""
        sdh_files = [
            "Inception.2010.en.sdh.srt",
            "Movie.English.CC.vtt",
            "Show.S01E01.en.hi.srt",
            "Film.en_hearing_impaired.srt",
        ]

        for fname in sdh_files:
            label, lang, is_sdh, _ = _parse_sub_label(fname)
            self.assertTrue(is_sdh, f"Expected SDH tag for {fname}")
            self.assertIn("(HI)", label, f"Expected (HI) in label for {fname}")

    def test_parse_sub_label_forced_and_duplicates(self):
        """Verify forced tags and duplicate index suffixes in external subtitle labels."""
        label, lang, is_sdh, _ = _parse_sub_label("Movie.en.forced.srt")
        self.assertEqual(label, "English (Forced)")
        self.assertEqual(lang, "en")
        self.assertFalse(is_sdh)

        label_dup, _, _, _ = _parse_sub_label("Movie.en.2.srt")
        self.assertEqual(label_dup, "English (2)")

        label_forced_dup, _, _, _ = _parse_sub_label("Movie.en.forced.3.srt")
        self.assertEqual(label_forced_dup, "English (Forced) (3)")

    def test_external_subtitle_matching(self):
        """Verify external subtitle files in the same directory matching the video stem are discovered."""
        video_path = os.path.join(self.test_dir, "Matrix.1999.1080p.mp4")
        with open(video_path, "wb") as f:
            f.write(b"0" * 512)

        sub_en = os.path.join(self.test_dir, "Matrix.1999.1080p.en.srt")
        with open(sub_en, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nWake up, Neo...\n")

        sub_es = os.path.join(self.test_dir, "Matrix.1999.1080p.es.srt")
        with open(sub_es, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nDespierta, Neo...\n")

        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout=b'{"streams":[]}')
            subs = get_all_subtitles(video_path, media_id=1)

            self.assertGreaterEqual(len(subs), 2)
            urls = [s.get("url", "") for s in subs]
            self.assertTrue(any("Matrix.1999.1080p.en.srt" in u for u in urls))
            self.assertTrue(any("Matrix.1999.1080p.es.srt" in u for u in urls))


    def test_online_subtitles_search_requires_api_key(self):
        """Verify GET /api/subtitles/online/search returns 400 when opensubtitles_api_key is empty."""
        from flask import Flask
        from backend.routes.streaming import streaming_bp
        app = Flask(__name__)
        app.register_blueprint(streaming_bp)
        client = app.test_client()

        with patch("backend.settings.load_config", return_value={"subtitles": {"opensubtitles_api_key": ""}}):
            resp = client.get("/api/subtitles/online/search?media_id=1")
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertIn("No OpenSubtitles API key configured", data.get("error", ""))

    def test_online_subtitles_download_requires_api_key(self):
        """Verify POST /api/subtitles/online/download returns 400 when opensubtitles_api_key is empty."""
        from flask import Flask
        from backend.routes.streaming import streaming_bp
        app = Flask(__name__)
        app.register_blueprint(streaming_bp)
        client = app.test_client()

        with patch("backend.settings.load_config", return_value={"subtitles": {"opensubtitles_api_key": ""}}):
            resp = client.post("/api/subtitles/online/download", json={"media_id": 1, "slug": "test-slug"})
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertIn("No OpenSubtitles API key configured", data.get("error", ""))

    def test_promote_subs_from_subs_folder_when_none_beside_media(self):
        """Verify that when a movie folder has a Subs/ folder and no subtitles beside media, subs are promoted."""
        movie_folder = os.path.join(self.test_dir, "Inception (2010)")
        os.makedirs(movie_folder, exist_ok=True)
        video_path = os.path.join(movie_folder, "Inception (2010).mkv")
        with open(video_path, "wb") as f:
            f.write(b"0" * 1024)

        subs_dir = os.path.join(movie_folder, "Subs")
        os.makedirs(subs_dir, exist_ok=True)

        with open(os.path.join(subs_dir, "2_English.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHello")
        with open(os.path.join(subs_dir, "3_English_SDH.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\n[Music playing]")
        with open(os.path.join(subs_dir, "5_Spanish.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHola")

        # Call promotion
        promoted = promote_subs_to_media_folder(video_path)
        self.assertGreaterEqual(len(promoted), 2)

        # Expected files beside media in movie folder
        dst_en = os.path.join(movie_folder, "Inception (2010).en.srt")
        dst_hi = os.path.join(movie_folder, "Inception (2010).en.hi.srt")
        dst_es = os.path.join(movie_folder, "Inception (2010).es.srt")

        self.assertTrue(os.path.exists(dst_en), "Expected English sub directly beside video")
        self.assertTrue(os.path.exists(dst_hi), "Expected HI English sub directly beside video")
        self.assertTrue(os.path.exists(dst_es), "Expected Spanish sub directly beside video")

        # Verify get_all_subtitles returns them as external subtitles
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = MagicMock(returncode=0, stdout=b'{"streams":[]}')
            subs = get_all_subtitles(video_path, media_id=99)
            urls = [s.get("url", "") for s in subs]
            self.assertTrue(any("Inception (2010).en.srt" in u for u in urls))

    def test_no_promote_when_subtitle_already_beside_media(self):
        """Verify that when a subtitle file already exists beside media, nothing is promoted from Subs/."""
        movie_folder = os.path.join(self.test_dir, "Gladiator (2000)")
        os.makedirs(movie_folder, exist_ok=True)
        video_path = os.path.join(movie_folder, "Gladiator (2000).mp4")
        with open(video_path, "wb") as f:
            f.write(b"0" * 1024)

        # Existing sub already beside media
        existing_sub = os.path.join(movie_folder, "Gladiator (2000).en.srt")
        with open(existing_sub, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nAre you not entertained?")

        subs_dir = os.path.join(movie_folder, "Subs")
        os.makedirs(subs_dir, exist_ok=True)
        with open(os.path.join(subs_dir, "2_English.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nAlternative")
        with open(os.path.join(subs_dir, "4_Spanish.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nEspanol")

        promoted = promote_subs_to_media_folder(video_path)
        self.assertEqual(len(promoted), 0, "Should not promote when subtitle is already beside media")

    def test_download_online_subtitle_ssrf_and_traversal_blocked(self):
        """Verify internal/loopback URLs are blocked (SSRF) and slug path traversal is sanitized."""
        from backend.subtitles import _is_safe_subtitle_download_url, download_online_subtitle

        # SSRF checks
        self.assertFalse(_is_safe_subtitle_download_url("http://127.0.0.1:8000/secret"))
        self.assertFalse(_is_safe_subtitle_download_url("http://localhost:5000/admin"))
        self.assertFalse(_is_safe_subtitle_download_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(_is_safe_subtitle_download_url("file:///etc/passwd"))
        self.assertFalse(_is_safe_subtitle_download_url("gopher://127.0.0.1:6379"))

        # Public HTTPS checks
        self.assertTrue(_is_safe_subtitle_download_url("https://www.google.com"))

        # Empty or malicious slug should be rejected gracefully
        self.assertIsNone(download_online_subtitle("../../..//", 1))

    def test_api_subtitles_serves_cached_online_vtt(self):
        """Verify /api/subtitles/<media_id>/<filename> correctly serves online VTT from cache."""
        import tempfile
        from flask import Flask
        from backend.routes.streaming import streaming_bp
        from backend.subtitles import SUB_CACHE_DIR

        app = Flask(__name__)
        app.register_blueprint(streaming_bp)
        client = app.test_client()

        os.makedirs(SUB_CACHE_DIR, exist_ok=True)
        test_vtt = os.path.join(SUB_CACHE_DIR, "online_9999_testsub.vtt")
        with open(test_vtt, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello Online Subtitle\n")

        resp = None
        try:
            resp = client.get("/api/subtitles/9999/online_9999_testsub.vtt")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "text/vtt")
            self.assertIn("Hello Online Subtitle", resp.get_data(as_text=True))
        finally:
            if resp is not None:
                resp.close()
            if os.path.isfile(test_vtt):
                try:
                    os.remove(test_vtt)
                except OSError:
                    pass

    def test_api_media_subtitles_endpoint(self):
        """Verify GET /api/media/<id>/subtitles returns status, subtitle count, and track list."""
        from flask import Flask
        from backend.routes.media import media_bp

        app = Flask(__name__)
        app.register_blueprint(media_bp)
        client = app.test_client()

        with patch("backend.routes.media.get_media_by_id") as mock_get_media, \
             patch("backend.subtitles.get_all_subtitles") as mock_get_subs:
            mock_get_media.return_value = {
                "id": 42,
                "title": "Interstellar",
                "file_path": "C:/Media/Interstellar.2014.mkv"
            }
            mock_get_subs.return_value = [
                {
                    "type": "external",
                    "label": "English (SDH)",
                    "language": "en",
                    "is_sdh": True,
                    "filename": "Interstellar.en.sdh.srt",
                    "url": "/api/subtitles/42/Interstellar.en.sdh.srt"
                }
            ]

            resp = client.get("/api/media/42/subtitles")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("has_subtitles"))
            self.assertEqual(data.get("count"), 1)
            self.assertEqual(len(data.get("subtitles")), 1)
            self.assertEqual(data["subtitles"][0]["label"], "English (SDH)")


if __name__ == "__main__":
    unittest.main()


