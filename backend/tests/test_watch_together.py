"""
backend/tests/test_watch_together.py -- Unit tests for Watch Together room logic.
"""

import unittest
from backend.watch_together import _gen_code, _rooms, _sid_room


class TestWatchTogether(unittest.TestCase):
    def setUp(self):
        _rooms.clear()
        _sid_room.clear()

    def tearDown(self):
        _rooms.clear()
        _sid_room.clear()

    def test_gen_code_format(self):
        """Room codes should be 6-character alphanumeric uppercase strings."""
        code = _gen_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isalnum())
        self.assertEqual(code, code.upper())

    def test_gen_code_uniqueness(self):
        """Generated codes should avoid collision with existing active rooms."""
        generated = set()
        for _ in range(50):
            c = _gen_code()
            _rooms[c] = {"code": c}
            generated.add(c)
        self.assertEqual(len(generated), 50)

    def test_room_dictionary_tracking(self):
        """Test manually storing and clearing rooms."""
        code = _gen_code()
        _rooms[code] = {
            "code": code,
            "media_id": 123,
            "media_type": "movie",
            "position": 42.0,
            "is_playing": True,
            "leader_sid": "sid-1",
            "members": [{"sid": "sid-1", "name": "Host", "color": "#8b5cf6"}],
            "chat": [],
        }
        _sid_room["sid-1"] = code

        self.assertIn(code, _rooms)
        self.assertEqual(_sid_room.get("sid-1"), code)
        self.assertEqual(_rooms[code]["position"], 42.0)

    def test_room_profile_metadata(self):
        """Test storing member profile information (name, avatar, theme)."""
        code = _gen_code()
        _rooms[code] = {
            "code": code,
            "media_id": 999,
            "members": [
                {"sid": "sid-alice", "name": "Alice", "color": "#10b981", "avatar": "👩"}
            ],
            "leader_sid": "sid-alice",
            "position": 10.5,
            "is_playing": True,
        }
        member = _rooms[code]["members"][0]
        self.assertEqual(member["name"], "Alice")
        self.assertEqual(member["color"], "#10b981")
        self.assertEqual(member["avatar"], "👩")


if __name__ == "__main__":
    unittest.main()
