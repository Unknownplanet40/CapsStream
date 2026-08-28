# -*- coding: utf-8 -*-
"""
Tests for Kids Filter Module (backend/kids_filter.py)
Covers genre gating, blocked genres, certification ratings, mature keyword denylist, and parental overrides.
"""
import unittest

from backend.kids_filter import is_kid_safe, filter_kids


class TestKidsFilter(unittest.TestCase):
    def test_safe_animation_item_passes(self):
        """Verify standard animated family movie with safe certification passes."""
        item = {
            "title": "Toy Adventure",
            "genres": "Animation, Family, Comedy",
            "certification": "G",
            "overview": "A fun adventure with animated toys."
        }
        safe, reason = is_kid_safe(item)
        self.assertTrue(safe)
        self.assertEqual(reason, "")

    def test_hard_blocked_genre_fails(self):
        """Verify presence of Horror, Crime, or Thriller blocks the item even with Animation genre."""
        item = {
            "title": "Animated Zombie Apocalypse",
            "genres": "Animation, Horror",
            "certification": "PG",
        }
        safe, reason = is_kid_safe(item)
        self.assertFalse(safe)
        self.assertIn("blocked genre", reason)

    def test_soft_genre_without_core_safe_fails(self):
        """Verify Action/Drama without Animation/Family/Kids is blocked."""
        item = {
            "title": "Serious Action Hero",
            "genres": "Action, Drama",
            "certification": "PG",
        }
        safe, reason = is_kid_safe(item)
        self.assertFalse(safe)
        self.assertIn("without Animation/Family", reason)

    def test_mature_keyword_in_overview_fails(self):
        """Verify keyword denylist blocks item even with Family genre."""
        item = {
            "title": "Misclassified Series",
            "genres": "Animation, Family",
            "certification": "PG",
            "overview": "A documentary exploring adult sexuality and human reproduction."
        }
        safe, reason = is_kid_safe(item)
        self.assertFalse(safe)
        self.assertIn("keyword", reason)

    def test_parental_overrides(self):
        """Verify parental allow override allows blocked items, and block override blocks safe items."""
        blocked_item = {
            "tmdb_id": 101,
            "title": "Horror Movie",
            "genres": "Horror",
        }
        overrides = {"allow": {101}, "block": set()}
        safe, _ = is_kid_safe(blocked_item, overrides=overrides)
        self.assertTrue(safe)

        safe_item = {
            "tmdb_id": 202,
            "title": "Safe Cartoon",
            "genres": "Animation, Family",
            "certification": "G"
        }
        overrides_block = {"allow": set(), "block": {202}}
        safe_b, reason_b = is_kid_safe(safe_item, overrides=overrides_block)
        self.assertFalse(safe_b)
        self.assertIn("parental override: blocked", reason_b)

    def test_filter_kids_batch(self):
        """Verify filter_kids filters lists properly."""
        items = [
            {"id": 1, "genres": "Animation, Family", "certification": "G"},
            {"id": 2, "genres": "Horror", "certification": "R"},
            {"id": 3, "genres": "Family, Kids", "certification": "PG"},
        ]
        result = filter_kids(items)
        self.assertEqual(len(result), 2)
        self.assertEqual([x["id"] for x in result], [1, 3])


if __name__ == "__main__":
    unittest.main()
