"""Minimal, read-only Supabase activity probe for Vercel Cron."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


TIMEOUT_SECONDS = 10


def _json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    """Vercel Python function at /api/keepalive."""

    def do_GET(self):
        cron_secret = os.environ.get("CRON_SECRET", "")
        authorization = self.headers.get("Authorization", "")
        expected = f"Bearer {cron_secret}" if cron_secret else ""
        if not cron_secret or not hmac.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
            _json_response(self, 401, {"ok": False, "error": "Unauthorized"})
            return

        supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        parsed_url = urlsplit(supabase_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password or not anon_key:
            _json_response(self, 500, {"ok": False, "error": "Supabase configuration is missing or invalid"})
            return

        query = urlencode({"select": "id", "limit": "1"})
        request = Request(
            f"{supabase_url}/rest/v1/media_requests?{query}",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
                "Accept": "application/json",
                "User-Agent": "CapsStream-Supabase-Keepalive/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    _json_response(self, 502, {"ok": False, "error": "Supabase returned an unexpected status"})
                    return
                _json_response(self, 200, {"ok": True, "message": "Supabase activity check succeeded"})
        except HTTPError:
            _json_response(self, 502, {"ok": False, "error": "Supabase request failed"})
        except (URLError, TimeoutError, OSError):
            _json_response(self, 502, {"ok": False, "error": "Supabase could not be reached"})

    def do_POST(self):
        _json_response(self, 405, {"ok": False, "error": "Method not allowed"})

    def log_message(self, format, *args):
        # Avoid logging request headers or values that could contain secrets.
        return
