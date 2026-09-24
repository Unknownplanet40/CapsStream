import importlib.util
import unittest
from unittest.mock import patch

from flask import Flask

from backend.db.connection import release_conn
from backend.db.profiles import activate_totp, create_profile, get_totp_state, update_profile, hash_pin
from backend.db.collections import create_collection, get_collections, validate_smart_collection_rule, match_smart_collection_items
from backend.routes.profiles import profiles_bp, _TOTP_CHALLENGES, _TOTP_ENROLLMENTS
from backend.routes.media import media_bp
from backend.utils.totp import recovery_hash
from backend.tests import create_isolated_test_db
from backend.utils.totp import code_at, matching_step


class TestTotpAndSmartCollections(unittest.TestCase):
    def setUp(self):
        from backend.routes import middleware
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS
        ACTIVE_PROFILE_SESSIONS.clear()
        middleware._PIN_FAILS.clear()
        self.pin_fails_patchers = [
            patch("backend.routes.middleware._load_pin_fails"),
            patch("backend.routes.middleware._save_pin_fails"),
        ]
        for patcher in self.pin_fails_patchers:
            patcher.start()
        _TOTP_CHALLENGES.clear()
        _TOTP_ENROLLMENTS.clear()
        self.db_path, self.cleanup_db = create_isolated_test_db()
        self.app = Flask(__name__)
        self.app.secret_key = "test_totp_secret"
        self.app.register_blueprint(profiles_bp)
        self.app.register_blueprint(media_bp)
        self.app.teardown_appcontext(release_conn)
        self.client = self.app.test_client()

    def tearDown(self):
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS
        ACTIVE_PROFILE_SESSIONS.clear()
        _TOTP_CHALLENGES.clear()
        _TOTP_ENROLLMENTS.clear()
        for patcher in self.pin_fails_patchers:
            patcher.stop()
        self.cleanup_db()

    def test_totp_known_vector_and_replay_step(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        code, step = code_at(secret, 59)
        self.assertEqual(code, "287082")
        self.assertEqual(matching_step(secret, code, timestamp=59), step)
        self.assertIsNone(matching_step(secret, code, last_step=step, timestamp=59))

    @patch("backend.routes.profiles._verify_totp_secret", return_value=("test-secret", 123))
    def test_admin_auth_requires_second_factor_before_session(self, _verify):
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS

        ACTIVE_PROFILE_SESSIONS.clear()
        profile_id = create_profile("Admin", None, is_admin=True)
        activate_totp(profile_id, "encrypted-test-secret", [])
        response = self.client.post("/api/profiles/auth", json={
            "profile_id": profile_id,
            "session_id": "client-session",
            "device_name": "Test Device",
        })
        self.assertEqual(response.status_code, 200)
        challenge = response.get_json()["challenge"]
        with self.client.session_transaction() as session:
            self.assertNotIn("profile_id", session)
            self.assertEqual(session["totp_challenge"], challenge)
        self.assertNotIn(profile_id, ACTIVE_PROFILE_SESSIONS)

        verified = self.client.post("/api/profiles/auth/2fa", json={"challenge": challenge, "code": "123456"})
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.get_json()["ok"])
        with self.client.session_transaction() as session:
            self.assertEqual(session["profile_id"], profile_id)
        self.assertNotIn("totp_secret", verified.get_json()["profile"])

    def test_totp_challenge_expires_without_authenticating_profile(self):
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS

        profile_id = create_profile("Admin", None, is_admin=True)
        activate_totp(profile_id, "encrypted-test-secret", [])
        started = self.client.post("/api/profiles/auth", json={"profile_id": profile_id})
        challenge = started.get_json()["challenge"]
        _TOTP_CHALLENGES[challenge]["created"] -= 301
        expired = self.client.post("/api/profiles/auth/2fa", json={"challenge": challenge, "code": "123456"})
        self.assertEqual(expired.status_code, 401)
        with self.client.session_transaction() as session:
            self.assertNotIn("profile_id", session)
        self.assertNotIn(profile_id, ACTIVE_PROFILE_SESSIONS)

    def test_totp_recovery_code_is_single_use(self):
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS

        ACTIVE_PROFILE_SESSIONS.clear()
        profile_id = create_profile("Admin", None, is_admin=True)
        from backend.routes.middleware import clear_pin_failures
        clear_pin_failures(profile_id)
        recovery = "ABCD-1234-RECOVERY"
        activate_totp(profile_id, "encrypted-test-secret", [recovery_hash(recovery)])
        with patch("backend.routes.profiles._verify_totp_secret", return_value=(None, None)):
            response = self.client.post("/api/profiles/auth", json={"profile_id": profile_id, "session_id": "recovery-test"})
            challenge = response.get_json()["challenge"]
            first = self.client.post("/api/profiles/auth/2fa", json={"challenge": challenge, "code": recovery})
            self.assertEqual(first.status_code, 200)
            with self.client.session_transaction() as session:
                session.clear()
            ACTIVE_PROFILE_SESSIONS.clear()
            retry = self.client.post("/api/profiles/auth", json={"profile_id": profile_id})
            challenge = retry.get_json()["challenge"]
            second = self.client.post("/api/profiles/auth/2fa", json={"challenge": challenge, "code": recovery})
        self.assertEqual(second.status_code, 401)
        with self.client.session_transaction() as session:
            self.assertNotIn("profile_id", session)
        self.assertNotIn(profile_id, ACTIVE_PROFILE_SESSIONS)

    def test_auth_challenge_does_not_reset_existing_pin_lockout(self):
        from backend.routes.middleware import ACTIVE_PROFILE_SESSIONS, record_pin_failure, pin_lockout_remaining, clear_pin_failures

        ACTIVE_PROFILE_SESSIONS.clear()
        profile_id = create_profile("Admin", None, is_admin=True)
        clear_pin_failures(profile_id)
        activate_totp(profile_id, "encrypted-test-secret", [])
        for _ in range(5):
            record_pin_failure(profile_id)
        response = self.client.post("/api/profiles/auth", json={"profile_id": profile_id})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(pin_lockout_remaining(profile_id), 0)

    def test_totp_is_cleared_when_profile_loses_admin_status_or_becomes_kids(self):
        profile_id = create_profile("Admin", None, is_admin=True)
        activate_totp(profile_id, "encrypted-test-secret", [recovery_hash("ABCD-1234")])
        update_profile(profile_id, "Admin", is_admin=False)
        self.assertIsNone(get_totp_state(profile_id)["totp_secret"])
        from backend.db.connection import get_conn
        conn = get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM totp_recovery_codes WHERE profile_id=?", (profile_id,)).fetchone()[0], 0)
        conn.close()

        update_profile(profile_id, "Admin", is_admin=True)
        activate_totp(profile_id, "encrypted-test-secret", [recovery_hash("ABCD-5678")])
        update_profile(profile_id, "Admin", is_kids=True)
        self.assertIsNone(get_totp_state(profile_id)["totp_secret"])

    def test_failed_totp_disable_keeps_valid_pin_failures(self):
        from backend.routes.middleware import clear_pin_failures, pin_lockout_remaining

        clear_pin_failures(1)
        profile_id = create_profile("Admin", hash_pin("1234"), is_admin=True)
        activate_totp(profile_id, "encrypted-test-secret", [])
        with self.client.session_transaction() as session:
            session["profile_id"] = profile_id
            session["is_admin"] = True
        clear_pin_failures(profile_id)
        with patch("backend.routes.profiles._verify_totp_secret", return_value=(None, None)):
            for _ in range(5):
                response = self.client.post(f"/api/profiles/{profile_id}/totp/disable", json={"pin": "1234", "code": "000000"})
                self.assertEqual(response.status_code, 401)
        self.assertGreater(pin_lockout_remaining(profile_id), 0)

    def test_profile_demotion_invalidates_cached_admin_session(self):
        from backend.routes.middleware import is_admin
        from flask import session

        profile_id = create_profile("Admin", None, is_admin=True)
        update_profile(profile_id, "Admin", is_admin=False)
        with self.app.test_request_context():
            session["profile_id"] = profile_id
            session["is_admin"] = True
            self.assertFalse(is_admin())
            self.assertFalse(session.get("is_admin"))

    @unittest.skipUnless(
        importlib.util.find_spec("cryptography") and importlib.util.find_spec("qrcode"),
        "cryptography and qrcode dependencies are required",
    )
    def test_totp_enrollment_exposes_qr_once_and_requires_valid_code(self):
        from base64 import b64decode
        from backend.utils.totp import code_at, decrypt_secret
        from backend.db.profiles import hash_pin

        profile_id = create_profile("Admin", hash_pin("1234"), is_admin=True)
        with self.client.session_transaction() as session:
            session["profile_id"] = profile_id
            session["is_admin"] = True
        started = self.client.post(f"/api/profiles/{profile_id}/totp/enroll", json={"pin": "1234"})
        self.assertEqual(started.status_code, 200)
        payload = started.get_json()
        self.assertTrue(payload["qr_code"].startswith("data:image/png;base64,"))
        self.assertTrue(b64decode(payload["qr_code"].split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotIn("totp_secret", payload)
        uri = payload["otpauth_uri"]
        self.assertIn(payload["secret"], uri)
        enrolled_secret = payload["secret"]
        code, _ = code_at(enrolled_secret)
        confirmed = self.client.post(f"/api/profiles/{profile_id}/totp/confirm", json={"enrollment": payload["enrollment"], "code": code})
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(len(confirmed.get_json()["recovery_codes"]), 10)
        self.assertEqual(decrypt_secret(get_totp_state(profile_id)["totp_secret"], self.app.secret_key), enrolled_secret)
        with self.assertRaises(Exception):
            decrypt_secret(get_totp_state(profile_id)["totp_secret"], "wrong-install-secret")
        self.assertNotIn("recovery_codes", self.client.get("/api/profiles").get_json()[0])

    @patch("backend.routes.media.require_admin")
    @patch("backend.video_probe.probe_video_resolution")
    @patch("backend.routes.media.get_all_sources_for_media")
    def test_duplicate_report_is_read_only_and_ranks_resolution(self, sources, probe, require_admin):
        from backend.routes.media import api_duplicate_report
        sources.return_value = [
            {"id": 1, "file_path": "D:/film-low.mkv", "file_size": 50, "is_mounted": True},
            {"id": 2, "file_path": "E:/film-high.mkv", "file_size": 20, "is_mounted": True},
        ]
        probe.side_effect = [
            {"width": 1280, "height": 720, "base_label": "720p HD"},
            {"width": 1920, "height": 1080, "base_label": "1080p HD"},
        ]
        from backend.db import upsert_media
        for path in ("D:/film-low.mkv", "E:/film-high.mkv"):
            upsert_media({"title": "Film", "type": "movie", "tmdb_id": 7, "file_path": path, "file_size": 50})
        with self.app.test_request_context("/api/admin/duplicate-report"):
            response = api_duplicate_report()
        self.assertEqual(response.status_code, 200)
        report = response.get_json()[0]
        self.assertEqual(report["suggested_best_id"], 2)
        self.assertEqual(report["estimated_reclaimable_bytes"], 50)
        self.assertEqual(sources.call_count, 1)
        self.assertEqual([call.args[0] for call in probe.call_args_list], ["D:/film-low.mkv", "E:/film-high.mkv"])

    def test_duplicate_report_requires_admin(self):
        from backend.routes.media import api_duplicate_report
        from flask import abort

        with self.app.test_request_context("/api/admin/duplicate-report"):
            with patch("backend.routes.media.require_admin", side_effect=lambda: abort(403)):
                with self.assertRaises(Exception) as caught:
                    api_duplicate_report()
        self.assertEqual(getattr(caught.exception, "code", None), 403)

    def test_smart_collection_resolution_rule_rejects_unknown_dimensions(self):
        rule = validate_smart_collection_rule({"resolution": 1080})
        items = [{"id": 1, "file_path": "unknown.mkv"}]
        self.assertEqual(match_smart_collection_items(items, rule, resolution_probe=lambda _path: {"height": 0}), [])

    def test_smart_collection_rule_validation_and_dynamic_matching(self):
        rule = validate_smart_collection_rule({"type": "movie", "year_from": "2000", "watched": False})
        items = [
            {"id": 1, "type": "movie", "year": 2001},
            {"id": 2, "type": "series", "year": 2001},
            {"id": 3, "type": "movie", "year": 1999},
        ]
        self.assertEqual([item["id"] for item in match_smart_collection_items(items, rule)], [1])
        with self.assertRaises(ValueError):
            validate_smart_collection_rule({"type": "movie", "sql": "1=1"})

        profile_id = create_profile("Owner", None)
        collection_id = create_collection(profile_id, "Recent Films", rule=rule)
        collections = get_collections(profile_id, media_items=items)
        saved = next(collection for collection in collections if collection["id"] == collection_id)
        self.assertEqual([item["id"] for item in saved["items"]], [1])
        other_profile = create_profile("Other", None)
        self.assertEqual(get_collections(other_profile, media_items=items), [])
        updated = validate_smart_collection_rule({"type": "movie", "year_from": 2002})
        from backend.db.collections import update_smart_collection_rule
        self.assertFalse(update_smart_collection_rule(collection_id, other_profile, updated))
        self.assertTrue(update_smart_collection_rule(collection_id, profile_id, updated))
        profiles = self.client.get("/api/profiles").get_json()
        self.assertNotIn("totp_secret", profiles[0])
        self.assertNotIn("totp_last_step", profiles[0])


if __name__ == "__main__":
    unittest.main()
