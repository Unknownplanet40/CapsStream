# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from backend.regional import detect_item_country, get_country_collections, COUNTRIES_MAP


class TestRegionalCollections(unittest.TestCase):

    def test_philippines_detection_from_language(self):
        item = {
            "id": 1,
            "title": "Hello, Love, Goodbye",
            "type": "movie",
            "original_language": "tl",
            "year": 2019,
            "file_path": "/movies/Hello.Love.Goodbye.2019.1080p.mkv"
        }
        res = detect_item_country(item)
        self.assertIsNotNone(res)
        self.assertEqual(res["code"], "PH")
        self.assertEqual(res["name"], "Philippines")
        self.assertEqual(res["flag"], "🇵🇭")

    def test_philippines_detection_from_path_keywords(self):
        item = {
            "id": 2,
            "title": "Unkabogable Praybeyt Benjamin",
            "type": "movie",
            "year": 2011,
            "file_path": "/media/Pinoy Movies/Praybeyt Benjamin (2011).mp4"
        }
        res = detect_item_country(item)
        self.assertIsNotNone(res)
        self.assertEqual(res["code"], "PH")
        self.assertEqual(res["name"], "Philippines")

    def test_philippines_series_detection(self):
        item = {
            "id": 3,
            "title": "Encantadia",
            "type": "series",
            "year": 2016,
            "file_path": "/series/Encantadia (2016) Teleserye/S01E01.mkv"
        }
        res = detect_item_country(item)
        self.assertIsNotNone(res)
        self.assertEqual(res["code"], "PH")

    def test_korea_detection_from_language(self):
        item = {
            "id": 4,
            "title": "Crash Landing on You",
            "type": "series",
            "original_language": "ko",
            "year": 2019,
            "file_path": "/series/Crash Landing on You/S01E01.mkv"
        }
        res = detect_item_country(item)
        self.assertIsNotNone(res)
        self.assertEqual(res["code"], "KR")
        self.assertEqual(res["name"], "South Korea")
        self.assertEqual(res["flag"], "🇰🇷")

    def test_get_country_collections_grouping(self):
        all_media = [
            {"id": 10, "title": "Rewind", "type": "movie", "original_language": "tl", "year": 2023},
            {"id": 11, "title": "Ang Probinsyano", "type": "series", "original_language": "tl", "year": 2015},
            {"id": 12, "title": "Four Sisters and a Wedding", "type": "movie", "original_language": "fil", "year": 2013},
            {"id": 13, "title": "Parasite", "type": "movie", "original_language": "ko", "year": 2019},
        ]
        # min_count=2: Philippines should be included (3 items), Korea should not (1 item)
        collections = get_country_collections(all_media, min_count=2)
        self.assertEqual(len(collections), 1)
        ph_col = collections[0]
        self.assertEqual(ph_col["id"], "country-ph")
        self.assertEqual(ph_col["country_code"], "PH")
        self.assertEqual(ph_col["movie_count"], 2)
        self.assertEqual(ph_col["series_count"], 1)
        self.assertEqual(len(ph_col["items"]), 3)
        self.assertTrue(ph_col["is_country_hub"])
        self.assertTrue(ph_col["smart"])


if __name__ == "__main__":
    unittest.main()
