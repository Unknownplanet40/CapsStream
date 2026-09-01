# -*- coding: utf-8 -*-
"""
backend/tests/test_hls.py — Unit tests for HLS transcoder and streaming routes.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from backend.hls_transcoder import (
    QUALITY_PRESETS,
    generate_master_playlist,
    generate_variant_playlist,
    get_available_qualities,
)


class TestHLSTranscoder(unittest.TestCase):

    def test_quality_presets(self):
        self.assertIn("1080p", QUALITY_PRESETS)
        self.assertIn("720p", QUALITY_PRESETS)
        self.assertIn("480p", QUALITY_PRESETS)
        self.assertIn("360p", QUALITY_PRESETS)

    @patch("backend.hls_transcoder.probe_video_resolution")
    def test_get_available_qualities(self, mock_probe):
        mock_probe.return_value = {"height": 1080, "width": 1920}
        quals = get_available_qualities("dummy.mp4")
        self.assertIn("1080p", quals)
        self.assertIn("720p", quals)
        self.assertIn("480p", quals)

    @patch("backend.hls_transcoder.probe_video_resolution")
    def test_generate_master_playlist(self, mock_probe):
        mock_probe.return_value = {"height": 1080, "width": 1920}
        playlist = generate_master_playlist(123, "dummy.mp4", audio_track_index=0)
        self.assertTrue(playlist.startswith("#EXTM3U"))
        self.assertIn("stream_1080p.m3u8", playlist)
        self.assertIn("stream_720p.m3u8", playlist)

    def test_generate_variant_playlist(self):
        playlist = generate_variant_playlist(123, "dummy.mp4", "720p", duration=20.0, audio_track_index=0)
        self.assertTrue(playlist.startswith("#EXTM3U"))
        self.assertIn("#EXT-X-TARGETDURATION:4", playlist)
        self.assertIn("seg_720p_00000.ts", playlist)
        self.assertIn("seg_720p_00004.ts", playlist)
        self.assertIn("#EXT-X-ENDLIST", playlist)


if __name__ == "__main__":
    unittest.main()
