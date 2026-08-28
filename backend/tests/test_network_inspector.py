# -*- coding: utf-8 -*-
"""
Tests for Network Inspector Module (backend/network_inspector.py)
Covers service detection, ring buffer recording, filtering, summary statistics, and clear operations.
"""
import unittest

from backend import network_inspector


class TestNetworkInspector(unittest.TestCase):
    def setUp(self):
        network_inspector.clear_recorded_requests()

    def tearDown(self):
        network_inspector.clear_recorded_requests()

    def test_detect_service(self):
        """Verify _detect_service classifies outbound API domains correctly."""
        self.assertEqual(network_inspector._detect_service("https://api.themoviedb.org/3/movie/550"), "TMDb API")
        self.assertEqual(network_inspector._detect_service("https://image.tmdb.org/t/p/w500/poster.jpg"), "TMDb CDN")
        self.assertEqual(network_inspector._detect_service("https://api.opensubtitles.com/api/v1/subtitles"), "OpenSubtitles")
        self.assertEqual(network_inspector._detect_service("https://api.aniskip.com/v2/skip-times/1/1"), "AniSkip")
        self.assertEqual(network_inspector._detect_service("https://api.jikan.moe/v4/anime"), "Jikan / MAL")
        self.assertEqual(network_inspector._detect_service("https://api.github.com/repos/CapsStream"), "GitHub")
        self.assertEqual(network_inspector._detect_service(""), "Unknown")

    def test_record_and_get_requests(self):
        """Verify recording requests stores entries with correct status, latency, and summary metrics."""
        network_inspector.record_request("GET", "https://api.themoviedb.org/3/movie/1", 200, duration_ms=45.2, size_bytes=1024)
        network_inspector.record_request("POST", "https://api.opensubtitles.com/api/v1/download", 500, duration_ms=120.0, error="Server Error")

        data = network_inspector.get_recorded_requests()
        requests = data["requests"]
        summary = data["summary"]

        self.assertEqual(len(requests), 2)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["success_rate"], 50.0)

        # First in list should be the most recent (LIFO ring buffer)
        self.assertEqual(requests[0]["method"], "POST")
        self.assertEqual(requests[0]["service"], "OpenSubtitles")
        self.assertFalse(requests[0]["ok"])

        self.assertEqual(requests[1]["method"], "GET")
        self.assertEqual(requests[1]["service"], "TMDb API")
        self.assertTrue(requests[1]["ok"])

    def test_filter_by_service_and_status(self):
        """Verify filtering requests by service name and status (success/error)."""
        network_inspector.record_request("GET", "https://api.themoviedb.org/3/movie/1", 200, duration_ms=50.0)
        network_inspector.record_request("GET", "https://api.aniskip.com/v2/skip-times/1/1", 200, duration_ms=30.0)
        network_inspector.record_request("GET", "https://api.aniskip.com/v2/skip-times/1/2", 404, duration_ms=25.0, error="Not Found")

        tmdb_only = network_inspector.get_recorded_requests(service_filter="TMDb API")
        self.assertEqual(len(tmdb_only["requests"]), 1)

        aniskip_errors = network_inspector.get_recorded_requests(service_filter="AniSkip", status_filter="error")
        self.assertEqual(len(aniskip_errors["requests"]), 1)
        self.assertEqual(aniskip_errors["requests"][0]["status_code"], 404)

    def test_clear_requests(self):
        """Verify clear_recorded_requests flushes the ring buffer."""
        network_inspector.record_request("GET", "https://api.themoviedb.org/3/movie/1", 200, duration_ms=50.0)
        self.assertEqual(len(network_inspector.get_recorded_requests()["requests"]), 1)

        network_inspector.clear_recorded_requests()
        self.assertEqual(len(network_inspector.get_recorded_requests()["requests"]), 0)


if __name__ == "__main__":
    unittest.main()
