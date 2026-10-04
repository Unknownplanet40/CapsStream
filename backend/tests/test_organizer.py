# -*- coding: utf-8 -*-
"""
backend/tests/test_organizer.py — Unit tests for Media Renamer & File Organizer.
"""
import os
import shutil
import tempfile
import unittest
from backend.organizer import (
    is_incomplete_file,
    is_clutter,
    is_media_file,
    classify_media_file,
    build_destination_path,
    execute_file_operation,
    find_companion_subtitles,
    execute_organization_plan,
    undo_batch,
    resolve_with_requests,
    sanitize_filename,
    clean_empty_subfolders,
    parse_subtitle_details,
)


class TestOrganizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.incoming_dir = os.path.join(self.temp_dir, "incoming")
        self.movies_dir = os.path.join(self.temp_dir, "movies")
        self.tv_dir = os.path.join(self.temp_dir, "tv")
        self.anime_dir = os.path.join(self.temp_dir, "anime")
        os.makedirs(self.incoming_dir, exist_ok=True)
        os.makedirs(self.movies_dir, exist_ok=True)
        os.makedirs(self.tv_dir, exist_ok=True)
        os.makedirs(self.anime_dir, exist_ok=True)
        self.lib_roots = {"movies": self.movies_dir, "tv": self.tv_dir, "anime": self.anime_dir}

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_incomplete_and_clutter_filters(self):
        self.assertTrue(is_incomplete_file("movie.mp4.part"))
        self.assertTrue(is_incomplete_file("show.s01e01.mkv.!ut"))
        self.assertTrue(is_incomplete_file("temp_download.crdownload"))
        self.assertFalse(is_incomplete_file("movie.2024.1080p.mkv"))

        self.assertTrue(is_clutter("RARBG.txt"))
        self.assertTrue(is_clutter("sample.mkv"))
        self.assertTrue(is_clutter("info.nfo"))
        self.assertFalse(is_clutter("Inception.2010.mkv"))

    def test_classify_movie(self):
        movie_path = os.path.join(self.incoming_dir, "Inception.2010.1080p.BluRay.x264.mkv")
        with open(movie_path, "wb") as f:
            f.write(b"fake movie video data")

        res = classify_media_file(movie_path)
        self.assertEqual(res["media_type"], "movie")
        self.assertEqual(res["title"], "Inception")
        self.assertEqual(res["year"], 2010)

        dst = build_destination_path(res | {"canonical_title": "Inception"}, self.lib_roots)
        expected = os.path.join(self.movies_dir, "Inception (2010)", "Inception (2010).mkv")
        self.assertEqual(os.path.normpath(dst), os.path.normpath(expected))

    def test_classify_tv_series(self):
        tv_path = os.path.join(self.incoming_dir, "Severance.S02E01.1080p.WEB-DL.mkv")
        with open(tv_path, "wb") as f:
            f.write(b"fake tv video data")

        res = classify_media_file(tv_path)
        self.assertEqual(res["media_type"], "tv")
        self.assertEqual(res["title"], "Severance")
        self.assertEqual(res["season"], 2)
        self.assertEqual(res["episode"], 1)

        dst = build_destination_path(res | {"canonical_title": "Severance"}, self.lib_roots)
        expected = os.path.join(self.tv_dir, "Severance", "Season 02", "Severance - S02E01.mkv")
        self.assertEqual(os.path.normpath(dst), os.path.normpath(expected))

    def test_classify_anime(self):
        anime_path = os.path.join(self.incoming_dir, "[SubsPlease] Sousou no Frieren - 28 (1080p) [ABCD1234].mkv")
        with open(anime_path, "wb") as f:
            f.write(b"fake anime video data")

        res = classify_media_file(anime_path)
        self.assertEqual(res["media_type"], "anime")
        self.assertEqual(res["title"], "Sousou no Frieren")
        self.assertEqual(res["season"], 1)
        self.assertEqual(res["episode"], 28)

        dst = build_destination_path(res | {"canonical_title": "Sousou no Frieren"}, self.lib_roots)
        expected = os.path.join(self.anime_dir, "Sousou no Frieren", "Season 01", "Sousou no Frieren - S01E28.mkv")
        self.assertEqual(os.path.normpath(dst), os.path.normpath(expected))

    def test_confidence_scoring(self):
        good_movie = os.path.join(self.incoming_dir, "Inception.2010.1080p.mkv")
        with open(good_movie, "wb") as f:
            f.write(b"data")
        self.assertEqual(classify_media_file(good_movie)["confidence"], "high")

        unrecognized = os.path.join(self.incoming_dir, "unknown.mkv")
        with open(unrecognized, "wb") as f:
            f.write(b"data")
        self.assertEqual(classify_media_file(unrecognized)["confidence"], "low")

    def test_execute_smart_link_and_subtitles(self):
        # Create media file and matching subtitle
        src_media = os.path.join(self.incoming_dir, "Dune.Part.Two.2024.1080p.mkv")
        src_sub = os.path.join(self.incoming_dir, "Dune.Part.Two.2024.1080p.en.srt")
        with open(src_media, "wb") as f:
            f.write(b"movie payload")
        with open(src_sub, "wb") as f:
            f.write(b"1\n00:00:01,000 --> 00:00:03,000\nHello")

        companions = find_companion_subtitles(src_media)
        self.assertEqual(len(companions), 1)

        dst_media = os.path.join(self.movies_dir, "Dune Part Two (2024)", "Dune Part Two (2024).mkv")
        plan = [{
            "source_path": src_media,
            "destination_path": dst_media,
            "media_type": "movie",
            "subtitles": companions
        }]

        history_file = os.path.join(self.temp_dir, "history.json")
        res = execute_organization_plan(plan, mode="smart")
        self.assertEqual(res["success_count"], 1)
        self.assertTrue(os.path.exists(dst_media))

        # Check subtitle moved/linked
        dst_sub = os.path.join(self.movies_dir, "Dune Part Two (2024)", "Dune Part Two (2024).en.srt")
        self.assertTrue(os.path.exists(dst_sub))

    def test_undo_batch(self):
        src = os.path.join(self.incoming_dir, "Test.Movie.2023.mkv")
        with open(src, "wb") as f:
            f.write(b"undo test")

        dst = os.path.join(self.movies_dir, "Test Movie (2023)", "Test Movie (2023).mkv")
        plan = [{
            "source_path": src,
            "destination_path": dst,
            "media_type": "movie",
            "subtitles": []
        }]

        history_file = os.path.join(self.temp_dir, "history.json")
        from backend import organizer
        orig_hist = organizer.ORGANIZER_HISTORY_FILE
        organizer.ORGANIZER_HISTORY_FILE = history_file
        try:
            res = execute_organization_plan(plan, mode="move")
            self.assertEqual(res["success_count"], 1)
            self.assertFalse(os.path.exists(src))
            self.assertTrue(os.path.exists(dst))

            # Now rollback
            undo_res = undo_batch(res["batch_id"], history_file=history_file)
            self.assertTrue(undo_res["success"])
            self.assertTrue(os.path.exists(src))
            self.assertFalse(os.path.exists(dst))
        finally:
            organizer.ORGANIZER_HISTORY_FILE = orig_hist

    def test_sanitize_filename(self):
        bad = 'What If...?: The Movie <2024> [Director/Cut]*'
        san = sanitize_filename(bad)
        self.assertNotIn(":", san)
        self.assertNotIn("<", san)
        self.assertNotIn(">", san)
        self.assertNotIn("/", san)
        self.assertNotIn("*", san)

    def test_watcher_lifecycle(self):
        from backend.organizer import start_organizer_watcher, stop_organizer_watcher, _WATCHER_STOP_EVENT
        start_organizer_watcher()
        self.assertFalse(_WATCHER_STOP_EVENT.is_set())
        stop_organizer_watcher()
        self.assertTrue(_WATCHER_STOP_EVENT.is_set())


    def test_movie_sequels_prequels_and_numbered_titles_not_classified_as_series(self):
        """Verify movie sequels, parts, chapters, Roman numerals, and numbered titles are classified as movies."""
        from backend.organizer import resolve_canonical_item
        cases = [
            ("Deadpool 2 (2018).mkv", "Deadpool 2", 2018),
            ("Gladiator II (2024).mkv", "Gladiator II", 2024),
            ("Dune Part Two (2024).mkv", "Dune Part Two", 2024),
            ("Dune Part 2 (2024).mkv", "Dune Part 2", 2024),
            ("Spider-Man 2.mkv", "Spider Man 2", None),
            ("John Wick Chapter 4 (2023).mkv", "John Wick Chapter 4", 2023),
            ("Star Wars Episode II Attack of the Clones (2002).mkv", "Star Wars Episode II Attack of the Clones", 2002),
            ("Ocean's 11 (2001).mkv", "Ocean s 11", 2001),
            ("300 (2006).mkv", "300", 2006),
            ("District 9 (2009).mkv", "District 9", 2009),
        ]
        for filename, expected_title_part, expected_year in cases:
            fpath = os.path.join(self.incoming_dir, filename)
            res = classify_media_file(fpath)
            self.assertEqual(res["media_type"], "movie", f"Failed for {filename}: got {res['media_type']}")
            self.assertIsNone(res["season"], f"Season should be None for movie {filename}")
            self.assertIsNone(res["episode"], f"Episode should be None for movie {filename}")
            if expected_year:
                self.assertEqual(res["year"], expected_year)

            # Destination path must lead to Movies/ directory
            resolved = resolve_canonical_item(res)
            dst = build_destination_path(resolved, self.lib_roots)
            self.assertTrue(dst.startswith(self.movies_dir), f"Destination {dst} should be in movies dir")

    def test_tv_and_anime_classification_accuracy(self):
        """Verify legitimate TV shows and anime releases are accurately detected."""
        # Standard SxxExx
        res_tv = classify_media_file(os.path.join(self.incoming_dir, "Severance.S02E01.1080p.mkv"))
        self.assertEqual(res_tv["media_type"], "tv")
        self.assertEqual(res_tv["season"], 2)
        self.assertEqual(res_tv["episode"], 1)

        # Standard 1x02
        res_tv2 = classify_media_file(os.path.join(self.incoming_dir, "Breaking.Bad.1x02.720p.mkv"))
        self.assertEqual(res_tv2["media_type"], "tv")
        self.assertEqual(res_tv2["season"], 1)
        self.assertEqual(res_tv2["episode"], 2)

        # Folder based season
        season_folder = os.path.join(self.incoming_dir, "The Office", "Season 02")
        os.makedirs(season_folder, exist_ok=True)
        res_folder = classify_media_file(os.path.join(season_folder, "03 - Office Olympics.mkv"))
        self.assertEqual(res_folder["media_type"], "tv")
        self.assertEqual(res_folder["season"], 2)
        self.assertEqual(res_folder["episode"], 3)

        # Anime with release group
        res_anime = classify_media_file(os.path.join(self.incoming_dir, "[SubsPlease] Sousou no Frieren - 28 (1080p).mkv"))
        self.assertEqual(res_anime["media_type"], "anime")
        self.assertEqual(res_anime["episode"], 28)

    def test_tmdb_multi_search_disambiguation(self):
        """Verify resolve_canonical_item uses TMDb search/multi to accurately resolve titles and types."""
        from unittest.mock import patch, MagicMock
        from backend.organizer import resolve_canonical_item

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": 383498,
                    "media_type": "movie",
                    "title": "Deadpool 2",
                    "release_date": "2018-05-15",
                }
            ]
        }

        item = {
            "file_path": "D:/Incoming/Deadpool 2 (2018).mkv",
            "filename": "Deadpool 2 (2018).mkv",
            "media_type": "movie",
            "title": "Deadpool 2",
            "year": 2018,
            "season": None,
            "episode": None,
            "extension": ".mkv",
            "file_size": 1000,
        }

        with patch("requests.get", return_value=mock_resp) as mock_get:
            res = resolve_canonical_item(item, tmdb_api_key="fake_key")
            self.assertEqual(res["canonical_title"], "Deadpool 2")
            self.assertEqual(res["media_type"], "movie")
            self.assertEqual(res["year"], 2018)
            self.assertEqual(res["match_source"], "tmdb")
            mock_get.assert_called_once()
            # Ensure search/multi was called
            self.assertIn("search/multi", mock_get.call_args[0][0])

    def test_clean_empty_subfolders(self):
        """Verify empty subfolders and clutter-only directories in Incoming are cleaned up."""
        empty_a = os.path.join(self.incoming_dir, "EmptyFolderA")
        os.makedirs(empty_a, exist_ok=True)

        parent_b = os.path.join(self.incoming_dir, "Parent")
        child_b = os.path.join(parent_b, "ChildEmpty")
        os.makedirs(child_b, exist_ok=True)

        clutter_dir = os.path.join(self.incoming_dir, "ClutterOnly")
        os.makedirs(clutter_dir, exist_ok=True)
        with open(os.path.join(clutter_dir, "movie.nfo"), "w") as f:
            f.write("scene info")
        with open(os.path.join(clutter_dir, "cover.jpg"), "w") as f:
            f.write("fake image")

        active_dir = os.path.join(self.incoming_dir, "ActiveDownload")
        os.makedirs(active_dir, exist_ok=True)
        with open(os.path.join(active_dir, "torrent.mkv.part"), "w") as f:
            f.write("downloading...")

        media_dir = os.path.join(self.incoming_dir, "RealMedia")
        os.makedirs(media_dir, exist_ok=True)
        with open(os.path.join(media_dir, "video.mkv"), "w") as f:
            f.write("video content")

        cleaned = clean_empty_subfolders(self.incoming_dir)

        # Incoming root must NEVER be deleted
        self.assertTrue(os.path.exists(self.incoming_dir))

        # Empty folders and clutter-only folders must be removed
        self.assertFalse(os.path.exists(empty_a))
        self.assertFalse(os.path.exists(child_b))
        self.assertFalse(os.path.exists(parent_b))
        self.assertFalse(os.path.exists(clutter_dir))

        # Folders with active downloads or media files must be preserved
        self.assertTrue(os.path.exists(active_dir))
        self.assertTrue(os.path.exists(media_dir))

    def test_execute_plan_cleans_empty_subfolders(self):
        """Verify execute_organization_plan prunes empty source folders after move."""
        movie_src_dir = os.path.join(self.incoming_dir, "Movie.Release.2024")
        os.makedirs(movie_src_dir, exist_ok=True)
        src_file = os.path.join(movie_src_dir, "movie.mkv")
        with open(src_file, "w") as f:
            f.write("data")
        with open(os.path.join(movie_src_dir, "movie.nfo"), "w") as f:
            f.write("nfo")

        dst_file = os.path.join(self.movies_dir, "Movie (2024)", "Movie (2024).mkv")
        plan = [{
            "source_path": src_file,
            "destination_path": dst_file,
            "media_type": "movie",
            "subtitles": []
        }]

        history_file = os.path.join(self.temp_dir, "hist_clean.json")
        res = execute_organization_plan(plan, mode="move", incoming_dir=self.incoming_dir, history_file=history_file)

        self.assertEqual(res["success_count"], 1)
        self.assertTrue(os.path.exists(dst_file))
        # Movie.Release.2024 should be completely pruned
        self.assertFalse(os.path.exists(movie_src_dir))
        # Incoming itself must remain
        self.assertTrue(os.path.exists(self.incoming_dir))
        self.assertTrue(any("Movie.Release.2024" in f for f in res.get("cleaned_folders", [])))

    def test_subtitle_prioritization_and_destination(self):
        """Verify English and HI English subtitles are prioritized and properly named."""
        # 1. Test parse_subtitle_details ranking
        eng_std = parse_subtitle_details("Subs/2_English.srt")
        self.assertEqual(eng_std["lang"], "en")
        self.assertFalse(eng_std["is_hi"])
        self.assertEqual(eng_std["priority"], 0)

        eng_hi = parse_subtitle_details("Subs/3_English_SDH.srt")
        self.assertEqual(eng_hi["lang"], "en")
        self.assertTrue(eng_hi["is_hi"])
        self.assertEqual(eng_hi["priority"], 1)

        eng_cc = parse_subtitle_details("Movie.Title.2024.en.cc.srt")
        self.assertEqual(eng_cc["lang"], "en")
        self.assertTrue(eng_cc["is_hi"])
        self.assertEqual(eng_cc["priority"], 1)

        spanish = parse_subtitle_details("Subs/5_Spanish.srt")
        self.assertEqual(spanish["lang"], "es")
        self.assertEqual(spanish["priority"], 4)

        # 2. Test directory companion search and priority sorting
        movie_dir = os.path.join(self.incoming_dir, "Dune.2024")
        subs_dir = os.path.join(movie_dir, "Subs")
        os.makedirs(subs_dir, exist_ok=True)

        movie_path = os.path.join(movie_dir, "Dune.2024.1080p.mkv")
        with open(movie_path, "w") as f:
            f.write("movie")

        # Create subtitles in random/scrambled order
        sub_spa = os.path.join(subs_dir, "5_Spanish.srt")
        sub_hi = os.path.join(subs_dir, "3_English_SDH.srt")
        sub_en = os.path.join(subs_dir, "2_English.srt")
        sub_fre = os.path.join(subs_dir, "6_French.srt")

        for s in [sub_spa, sub_hi, sub_en, sub_fre]:
            with open(s, "w") as f:
                f.write("1\n00:00:01,000 --> 00:00:02,000\nSub")

        companions = find_companion_subtitles(movie_path)
        self.assertEqual(len(companions), 4)

        # English (priority 0) must be first
        self.assertEqual(os.path.basename(companions[0]), "2_English.srt")
        # HI English / SDH (priority 1) must be second
        self.assertEqual(os.path.basename(companions[1]), "3_English_SDH.srt")

        # 3. Test execution naming
        dst_movie = os.path.join(self.movies_dir, "Dune (2024)", "Dune (2024).mkv")
        plan = [{
            "source_path": movie_path,
            "destination_path": dst_movie,
            "media_type": "movie",
            "subtitles": companions
        }]

        history_file = os.path.join(self.temp_dir, "sub_hist.json")
        res = execute_organization_plan(plan, mode="copy", history_file=history_file)
        self.assertEqual(res["success_count"], 1)

        # Verify all destinations were created cleanly with proper priority naming
        dst_en = os.path.join(self.movies_dir, "Dune (2024)", "Dune (2024).en.srt")
        dst_hi = os.path.join(self.movies_dir, "Dune (2024)", "Dune (2024).en.hi.srt")
        dst_es = os.path.join(self.movies_dir, "Dune (2024)", "Dune (2024).es.srt")
        dst_fr = os.path.join(self.movies_dir, "Dune (2024)", "Dune (2024).fr.srt")

        self.assertTrue(os.path.exists(dst_en))
        self.assertTrue(os.path.exists(dst_hi))
        self.assertTrue(os.path.exists(dst_es))
        self.assertTrue(os.path.exists(dst_fr))

    def test_undo_batch_default_history_file(self):
        """Verify undo_batch works and writes back when history_file=None (default ORGANIZER_HISTORY_FILE)."""
        import json
        from unittest.mock import patch
        import backend.organizer as org_mod

        fake_default_hist = os.path.join(self.temp_dir, "default_history.json")
        src_file = os.path.join(self.incoming_dir, "test_file.mkv")
        dst_file = os.path.join(self.movies_dir, "test_file.mkv")
        with open(dst_file, "w") as f:
            f.write("content")

        batch = {
            "batch_id": "test_batch_123",
            "timestamp": "2026-10-03T00:00:00",
            "operations": [
                {
                    "action": "move",
                    "source": src_file,
                    "destination": dst_file,
                }
            ]
        }
        with open(fake_default_hist, "w", encoding="utf-8") as f:
            json.dump([batch], f)

        with patch.object(org_mod, "ORGANIZER_HISTORY_FILE", fake_default_hist):
            res = undo_batch("test_batch_123")  # history_file=None default
            self.assertTrue(res["success"])
            self.assertEqual(res["reverted_count"], 1)
            self.assertTrue(os.path.exists(src_file))
            self.assertFalse(os.path.exists(dst_file))
            # Verify the default history file was successfully written and batch removed
            with open(fake_default_hist, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved), 0)


if __name__ == "__main__":
    unittest.main()


