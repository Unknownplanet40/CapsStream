# -*- coding: utf-8 -*-
"""
Tests for Profiles Route Endpoints (backend/routes/profiles.py)
Covers profile listing, creation, session heartbeat, and PIN authentication.
"""
import unittest
from unittest.mock import patch
from flask import Flask

from backend.tests import create_isolated_test_db
from backend.routes.profiles import profiles_bp
from backend.db.connection import release_conn
from backend.db.profiles import create_profile, get_profile


class TestRouteProfiles(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cleanup_db = create_isolated_test_db()
        self.app = Flask(__name__)
        self.app.secret_key = "test_profiles_secret"
        self.app.register_blueprint(profiles_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()

    def tearDown(self):
        self.cleanup_db()

    @patch("backend.routes.profiles.get_all_profiles")
    def test_api_get_profiles(self, mock_get_profs):
        """Verify GET /api/profiles returns list of profiles with in_use status flags."""
        mock_get_profs.return_value = [
            {"id": 1, "name": "Main User", "is_admin": 1, "has_pin": True, "has_completed_tour": 1},
            {"id": 2, "name": "Kids Profile", "is_kids": 1, "has_pin": False, "has_completed_tour": 0}
        ]

        resp = self.client.get("/api/profiles")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Main User")
        self.assertIn("in_use", data[0])

    @patch("backend.routes.profiles.require_admin")
    @patch("backend.routes.profiles.create_profile")
    @patch("backend.routes.profiles.get_all_profiles")
    def test_api_create_profile(self, mock_get_profs, mock_create, mock_admin):
        """Verify POST /api/profiles creates profile when admin authorized."""
        mock_get_profs.return_value = []
        mock_create.return_value = 3

        payload = {
            "name": "Guest",
            "pin": "1234",
            "is_kids": False,
            "theme": "indigo",
            "has_completed_tour": 0,
        }
        resp = self.client.post("/api/profiles", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["id"], 3)
        self.assertEqual(data["name"], "Guest")

    @patch("backend.routes.profiles.require_admin")
    def test_api_create_profile_invalid_pin_length(self, mock_admin):
        """Verify POST /api/profiles rejects PINs that are not exactly 4 digits."""
        payload = {"name": "Test", "pin": "12"}
        resp = self.client.post("/api/profiles", json=payload)
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("4 digits", data["error"])

    @patch("backend.routes.profiles.is_admin")
    @patch("backend.routes.profiles.current_profile")
    def test_api_update_profile_tour_completion(self, mock_curr, mock_admin):
        """Verify PUT /api/profiles/<id> persists has_completed_tour flag."""
        mock_admin.return_value = True
        mock_curr.return_value = 1

        pid = create_profile(name="Admin", pin_hash=None, is_admin=True, has_completed_tour=0)
        prof_before = get_profile(pid)
        self.assertEqual(prof_before.get("has_completed_tour"), 0)

        resp = self.client.put(f"/api/profiles/{pid}", json={
            "name": "Admin",
            "has_completed_tour": 1,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("has_completed_tour"))

        prof_after = get_profile(pid)
        self.assertEqual(prof_after.get("has_completed_tour"), 1)


if __name__ == "__main__":
    unittest.main()
