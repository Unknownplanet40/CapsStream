"""Tests for non-blocking external API health snapshots."""
import threading
import unittest
from unittest.mock import patch

from backend.utils import api_health


class TestApiHealth(unittest.TestCase):
    def setUp(self):
        with api_health._API_HEALTH_LOCK:
            api_health._API_HEALTH_CACHE.update({"key_fingerprint": None, "checked_at": 0.0, "data": None})
            api_health._API_HEALTH_REFRESHING.clear()
            api_health._API_HEALTH_ACTIVE_KEY = None

    @patch("backend.utils.api_health.threading.Thread")
    def test_initial_request_returns_checking_without_blocking(self, mock_thread):
        mock_thread.return_value.start = lambda: None
        result = api_health.get_api_health_snapshot({"tmdb_api_key": "key-one"}, "/tmp/capsstream")
        self.assertEqual(result["tmdb"]["status"], "checking")
        self.assertEqual(result["aniskip"]["status"], "checking")
        mock_thread.assert_called_once()

    @patch("backend.utils.api_health.threading.Thread")
    def test_concurrent_stale_reads_schedule_single_refresh(self, mock_thread):
        mock_thread.return_value.start = lambda: None
        config = {"tmdb_api_key": "key-one"}
        api_health.get_api_health_snapshot(config, "/tmp/capsstream")
        api_health.get_api_health_snapshot(config, "/tmp/capsstream")
        self.assertEqual(mock_thread.call_count, 1)

    @patch("backend.utils.api_health.threading.Thread")
    def test_fresh_snapshot_is_reused_until_ttl_expires(self, mock_thread):
        mock_thread.return_value.start = lambda: None
        config = {"tmdb_api_key": "key-one"}
        api_health.get_api_health_snapshot(config, "/tmp/capsstream")
        fingerprint = api_health.hashlib.sha256(b"key-one").hexdigest()
        with api_health._API_HEALTH_LOCK:
            api_health._API_HEALTH_CACHE.update({
                "key_fingerprint": fingerprint,
                "checked_at": api_health.time.time(),
                "data": {"tmdb": {"status": "ok", "latency_ms": 3}},
            })
        self.assertEqual(api_health.get_api_health_snapshot(config, "/tmp/capsstream")["tmdb"]["status"], "ok")
        self.assertEqual(mock_thread.call_count, 1)
        with api_health._API_HEALTH_LOCK:
            api_health._API_HEALTH_REFRESHING.clear()
            api_health._API_HEALTH_CACHE["checked_at"] -= api_health.CACHE_TTL_SECONDS + 1
        api_health.get_api_health_snapshot(config, "/tmp/capsstream")
        self.assertEqual(mock_thread.call_count, 2)

    @patch("backend.utils.api_health.threading.Thread")
    def test_key_change_does_not_reuse_previous_health(self, mock_thread):
        mock_thread.return_value.start = lambda: None
        with api_health._API_HEALTH_LOCK:
            api_health._API_HEALTH_CACHE.update({
                "key_fingerprint": "old-fingerprint",
                "checked_at": api_health.time.time(),
                "data": {"tmdb": {"status": "ok", "latency_ms": 1}},
            })
        result = api_health.get_api_health_snapshot({"tmdb_api_key": "new-key"}, "/tmp/capsstream")
        self.assertEqual(result["tmdb"]["status"], "checking")

    def test_refresh_updates_cached_snapshot_for_active_key(self):
        key = "test-key"
        fingerprint = api_health.hashlib.sha256(key.encode("utf-8")).hexdigest()
        with patch.object(api_health, "_probe_url", return_value=(True, 12)):
            api_health.get_api_health_snapshot({"tmdb_api_key": key}, "/tmp/capsstream")
            api_health._refresh_health(key, fingerprint, "/tmp/capsstream/data/metadata")
        result = api_health.get_api_health_snapshot({"tmdb_api_key": key}, "/tmp/capsstream")
        self.assertEqual(result["tmdb"]["status"], "ok")
        self.assertEqual(result["aniskip"]["status"], "ok")
        self.assertEqual(result["tmdb"]["latency_ms"], 12)
        self.assertEqual(result["poster_cache"]["status"], "ok")

    def test_stale_refresh_for_old_key_cannot_overwrite_new_key(self):
        key = "old-key"
        old_fingerprint = api_health.hashlib.sha256(key.encode("utf-8")).hexdigest()
        new_fingerprint = api_health.hashlib.sha256(b"new-key").hexdigest()
        with api_health._API_HEALTH_LOCK:
            api_health._API_HEALTH_ACTIVE_KEY = new_fingerprint
            api_health._API_HEALTH_REFRESHING.add(old_fingerprint)
        with patch.object(api_health, "_probe_url", return_value=(True, 12)):
            api_health._refresh_health(key, old_fingerprint, "/tmp/capsstream/data/metadata")
        self.assertNotEqual(api_health._API_HEALTH_CACHE["key_fingerprint"], old_fingerprint)


if __name__ == "__main__":
    unittest.main()
