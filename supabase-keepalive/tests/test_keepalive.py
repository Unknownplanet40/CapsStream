import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError


API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))
import keepalive  # noqa: E402


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class KeepaliveTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = keepalive.handler.__new__(keepalive.handler)
        self.endpoint.headers = {}
        self.endpoint.wfile = io.BytesIO()
        self.endpoint.send_response = unittest.mock.Mock()
        self.endpoint.send_header = unittest.mock.Mock()
        self.endpoint.end_headers = unittest.mock.Mock()
        self.env = patch.dict(os.environ, {
            "CRON_SECRET": "a-long-test-secret",
            "SUPABASE_URL": "https://demo.supabase.co/",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _response_json(self):
        return json.loads(self.endpoint.wfile.getvalue().decode("utf-8"))

    def test_rejects_missing_or_invalid_cron_secret_without_supabase_call(self):
        for authorization in (None, "Bearer wrong"):
            with self.subTest(authorization=authorization):
                self.endpoint.headers = {} if authorization is None else {"Authorization": authorization}
                with patch.object(keepalive, "urlopen") as urlopen:
                    self.endpoint.do_GET()
                self.endpoint.send_response.assert_called_with(401)
                urlopen.assert_not_called()
                self.endpoint.wfile = io.BytesIO()
                self.endpoint.send_response.reset_mock()

    def test_authorized_probe_uses_read_only_supabase_get(self):
        self.endpoint.headers = {"Authorization": "Bearer a-long-test-secret"}
        with patch.object(keepalive, "urlopen", return_value=_FakeResponse()) as urlopen:
            self.endpoint.do_GET()

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://demo.supabase.co/rest/v1/media_requests?select=id&limit=1")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Apikey"), "test-anon-key")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-anon-key")
        urlopen.assert_called_once_with(request, timeout=keepalive.TIMEOUT_SECONDS)
        self.endpoint.send_response.assert_called_with(200)
        self.assertTrue(self._response_json()["ok"])

    def test_missing_supabase_config_fails_without_request(self):
        self.endpoint.headers = {"Authorization": "Bearer a-long-test-secret"}
        os.environ.pop("SUPABASE_ANON_KEY")
        with patch.object(keepalive, "urlopen") as urlopen:
            self.endpoint.do_GET()
        urlopen.assert_not_called()
        self.endpoint.send_response.assert_called_with(500)

    def test_upstream_http_and_network_errors_are_sanitized(self):
        self.endpoint.headers = {"Authorization": "Bearer a-long-test-secret"}
        failures = (
            HTTPError("https://demo.supabase.co", 401, "denied", {}, None),
            URLError("network details"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.endpoint.wfile = io.BytesIO()
                self.endpoint.send_response.reset_mock()
                with patch.object(keepalive, "urlopen", side_effect=failure):
                    self.endpoint.do_GET()
                self.endpoint.send_response.assert_called_with(502)
                self.assertEqual(self._response_json(), {
                    "ok": False,
                    "error": "Supabase request failed" if isinstance(failure, HTTPError) else "Supabase could not be reached",
                })

    def test_post_is_not_allowed(self):
        self.endpoint.do_POST()
        self.endpoint.send_response.assert_called_with(405)


if __name__ == "__main__":
    unittest.main()
