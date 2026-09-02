# -*- coding: utf-8 -*-
"""
Tests for Franchise and Cinematic Universe Engine (backend/franchises.py)
Covers pattern matching, timeline ranking, universe collection grouping, and deduplication.
"""
import unittest

from backend.franchises import (
    UNIVERSES,
    _matches_patterns,
    _get_timeline_rank,
    get_universe_collections
)


class TestFranchises(unittest.TestCase):
    def test_matches_patterns(self):
        """Verify _matches_patterns checks regex word boundaries correctly."""
        patterns = [r"\biron man\b", r"\bspider-man\b"]
        self.assertTrue(_matches_patterns("Iron Man (2008)", patterns))
        self.assertTrue(_matches_patterns("Spider-Man: No Way Home", patterns))
        self.assertFalse(_matches_patterns("Batman Begins", patterns))
        self.assertFalse(_matches_patterns("", patterns))

    def test_get_timeline_rank(self):
        """Verify _get_timeline_rank assigns sequential chronological ordering."""
        timeline_patterns = [
            (1, r"captain america:? the first avenger"),
            (2, r"captain marvel"),
            (3, r"iron man\b"),
        ]
        self.assertEqual(_get_timeline_rank("Captain America: The First Avenger", timeline_patterns), 1)
        self.assertEqual(_get_timeline_rank("Captain Marvel (2019)", timeline_patterns), 2)
        self.assertEqual(_get_timeline_rank("Iron Man", timeline_patterns), 3)
        self.assertEqual(_get_timeline_rank("Unknown Movie", timeline_patterns), 9999)

    def test_get_universe_collections_mcu(self):
        """Verify get_universe_collections groups items when threshold (min_count) is met."""
        items = [
            {"id": 1, "tmdb_id": 101, "title": "Iron Man", "year": 2008},
            {"id": 2, "tmdb_id": 102, "title": "Captain America: The First Avenger", "year": 2011},
            {"id": 3, "tmdb_id": 103, "title": "Thor", "year": 2011},
            {"id": 4, "tmdb_id": 999, "title": "The Matrix", "year": 1999},
        ]

        collections = get_universe_collections(items, min_count=2)
        self.assertTrue(any(c["id"] == "universe-mcu" for c in collections))

        mcu = next(c for c in collections if c["id"] == "universe-mcu")
        self.assertEqual(len(mcu["items"]), 3)
        self.assertTrue(mcu["has_timeline"])

        # Timeline order should place Captain America (rank 1) before Iron Man (rank 3)
        timeline_titles = [x["title"] for x in mcu["timeline_items"]]
        self.assertEqual(timeline_titles[0], "Captain America: The First Avenger")

    def test_get_universe_collections_below_min_count(self):
        """Verify universes with fewer than min_count matched titles are excluded."""
        items = [
            {"id": 1, "tmdb_id": 101, "title": "Iron Man", "year": 2008}
        ]
        collections = get_universe_collections(items, min_count=2)
        self.assertEqual(len(collections), 0)

    def test_get_media_franchise(self):
        """Verify get_media_franchise locates the parent collection for a sibling item."""
        from backend.franchises import get_media_franchise
        items = [
            {"id": 1, "tmdb_id": 101, "title": "Iron Man", "year": 2008},
            {"id": 2, "tmdb_id": 102, "title": "Thor", "year": 2011},
        ]
        franchise = get_media_franchise(items[0], library_items=items)
        self.assertIsNotNone(franchise)
        self.assertEqual(franchise["name"], "Marvel Cinematic Universe")
        self.assertEqual(franchise["item_count"], 2)


if __name__ == "__main__":
    unittest.main()
