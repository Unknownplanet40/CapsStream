# -*- coding: utf-8 -*-
"""
Tests for Blueprint Middleware & Auth Guards (backend/routes/middleware.py)
Covers PIN lockout, admin verification, kids mode guards, and profile resolution.
"""
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask, session
from werkzeug.exceptions import HTTPException

from backend.routes.middleware import (
    record_pin_failure,
    clear_pin_failures,
    pin_lockout_remaining,
    verify_admin_pin,
    is_admin,
    require_admin,
    current_profile,
    require_profile,
    active_is_kids
)


class TestMiddleware(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test_secret"
        clear_pin_failures(1)
        clear_pin_failures(2)

    def tearDown(self):
        clear_pin_failures(1)
        clear_pin_failures(2)

    def test_pin_brute_force_lockout(self):
        """Verify 5 failed attempts trigger a lockout window."""
        profile_id = 1
        self.assertEqual(pin_lockout_remaining(profile_id), 0)

        for _ in range(4):
            record_pin_failure(profile_id)
        self.assertEqual(pin_lockout_remaining(profile_id), 0)

        # 5th attempt locks out
        record_pin_failure(profile_id)
        self.assertGreater(pin_lockout_remaining(profile_id), 0)

        clear_pin_failures(profile_id)
        self.assertEqual(pin_lockout_remaining(profile_id), 0)

    @patch("backend.routes.middleware.get_admin_profiles")
    @patch("backend.db.verify_pin_raw")
    def test_verify_admin_pin(self, mock_verify_pin, mock_get_admins):
        """Verify verify_admin_pin validates pins against admin profiles."""
        mock_get_admins.return_value = [{"id": 1, "is_admin": 1, "has_pin": True}]
        mock_verify_pin.return_value = True

        ok, err, code = verify_admin_pin("1234")
        self.assertTrue(ok)
        self.assertEqual(code, 200)

        mock_verify_pin.return_value = False
        ok_fail, err_fail, code_fail = verify_admin_pin("0000")
        self.assertFalse(ok_fail)
        self.assertEqual(code_fail, 401)

    def test_require_profile_aborts_unauthenticated(self):
        """Verify require_profile raises 401 when no profile session is active."""
        with self.app.test_request_context():
            session.clear()
            with self.assertRaises(HTTPException) as ctx:
                require_profile()
            self.assertEqual(ctx.exception.code, 401)

    def test_require_profile_success(self):
        """Verify require_profile returns active profile_id."""
        with self.app.test_request_context():
            session["profile_id"] = 42
            self.assertEqual(require_profile(), 42)

    def test_require_admin_guard(self):
        """Verify require_admin aborts 403 when session is not an admin."""
        with self.app.test_request_context():
            session["profile_id"] = 5
            session["is_admin"] = False
            with self.assertRaises(HTTPException) as ctx:
                require_admin()
            self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
