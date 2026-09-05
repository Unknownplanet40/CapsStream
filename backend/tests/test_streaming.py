# -*- coding: utf-8 -*-
"""
Tests for Video Streaming Module (backend/streamer.py & routes/streaming.py)
Covers HTTP Range requests, 206 Partial Content, Content-Range calculations,
MIME type headers, FFmpeg command builders, convert/remux/audio streaming generators,
and Flask blueprint integration endpoints.
"""
import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from flask import Flask
from werkzeug.exceptions import HTTPException

from backend.streamer import (
    stream_file,
    stream_video_convert,
    stream_audio_only,
    stream_transcoded,
    find_keyframe_before,
    describe_hw_encoder,
    _build_convert_cmd
)


class TestVideoStreaming(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_stream_test_")
        
        # Create a test video payload of exactly 10,000 bytes
        self.video_size = 10000
        self.video_path = os.path.join(self.test_dir, "sample_video.mp4")
        with open(self.video_path, "wb") as f:
            f.write(bytes([i % 256 for i in range(self.video_size)]))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ─── Range Request Tests ──────────────────────────────────────────────────
    def test_full_video_stream_without_range(self):
        """Verify requesting video without Range header returns 200 OK with full Content-Length."""
        with self.app.test_request_context():
            response = stream_file(self.video_path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Content-Length"), str(self.video_size))
            self.assertEqual(response.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(response.headers.get("Content-Type"), "video/mp4")

    def test_partial_range_start_to_end(self):
        """Verify 'bytes=0-1023' returns 206 Partial Content with 1024 bytes and correct Content-Range."""
        with self.app.test_request_context(headers={"Range": "bytes=0-1023"}):
            response = stream_file(self.video_path)
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.headers.get("Content-Length"), "1024")
            self.assertEqual(response.headers.get("Content-Range"), f"bytes 0-1023/{self.video_size}")

            data = b"".join(response.response)
            self.assertEqual(len(data), 1024)
            self.assertEqual(data[0], 0)
            self.assertEqual(data[1], 1)

    def test_partial_range_from_offset(self):
        """Verify 'bytes=5000-' streams from byte 5000 to the end of the file."""
        with self.app.test_request_context(headers={"Range": "bytes=5000-"}):
            response = stream_file(self.video_path)
            self.assertEqual(response.status_code, 206)
            expected_len = self.video_size - 5000
            self.assertEqual(response.headers.get("Content-Length"), str(expected_len))
            self.assertEqual(response.headers.get("Content-Range"), f"bytes 5000-{self.video_size - 1}/{self.video_size}")

            data = b"".join(response.response)
            self.assertEqual(len(data), expected_len)

    def test_suffix_range(self):
        """Verify 'bytes=-500' streams the last 500 bytes of the file."""
        with self.app.test_request_context(headers={"Range": "bytes=-500"}):
            response = stream_file(self.video_path)
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.headers.get("Content-Length"), "500")
            self.assertEqual(response.headers.get("Content-Range"), f"bytes 9500-9999/{self.video_size}")

    def test_invalid_range_aborts_416(self):
        """Verify out-of-bounds or malformed range requests raise 416 Range Not Satisfiable."""
        with self.app.test_request_context(headers={"Range": f"bytes={self.video_size + 1000}-"}):
            with self.assertRaises(HTTPException) as ctx:
                stream_file(self.video_path)
            self.assertEqual(ctx.exception.code, 416)

    # ─── Command Builder Tests ────────────────────────────────────────────────
    def test_convert_cmd_builder_with_audio_and_yuv420p(self):
        """Verify _build_convert_cmd ensures yuv420p pixel format, audio mapping, and subtitle exclusion."""
        cmd = _build_convert_cmd(
            file_path=self.video_path,
            audio_track_index=0,
            effective_start=12.5,
            max_height=1080,
            encoder_name="libx264",
            has_audio=True,
        )
        self.assertIn("-pix_fmt", cmd)
        self.assertIn("yuv420p", cmd)
        self.assertIn("-ss", cmd)
        self.assertIn("12.500", cmd)
        self.assertIn("-map", cmd)
        self.assertIn("0:V:0?", cmd)
        self.assertIn("0:a:0?", cmd)
        self.assertIn("-0:s?", cmd)
        self.assertIn("-flush_packets", cmd)
        self.assertIn("-c:a", cmd)
        self.assertIn("aac", cmd)

    def test_convert_cmd_builder_without_audio(self):
        """Verify _build_convert_cmd uses -an when media has no audio tracks."""
        cmd = _build_convert_cmd(
            file_path=self.video_path,
            audio_track_index=0,
            effective_start=0.0,
            max_height=0,
            encoder_name="libx264",
            has_audio=False,
        )
        self.assertIn("-an", cmd)
        self.assertNotIn("0:a:0?", cmd)
        self.assertIn("-pix_fmt", cmd)
        self.assertIn("yuv420p", cmd)

    # ─── Hardware Encoder & Keyframe Probing ──────────────────────────────────
    @patch("backend.streamer._encoder_selftest")
    @patch("subprocess.run")
    def test_describe_hw_encoder(self, mock_subproc, mock_selftest):
        """Verify describe_hw_encoder probes hardware encoders correctly."""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="h264_qsv h264_nvenc libx264")
        mock_selftest.side_effect = lambda enc, opts: enc == "libx264"

        caps = describe_hw_encoder(force=True)
        self.assertTrue(caps["available"])
        self.assertEqual(caps["encoder"], "libx264")
        self.assertFalse(caps["hardware"])

    @patch("subprocess.check_output")
    def test_find_keyframe_before(self, mock_check_output):
        """Verify find_keyframe_before finds matching packet pts timestamp."""
        fake_ffprobe_pkts = {
            "packets": [
                {"pts_time": "0.000", "flags": "K_"},
                {"pts_time": "2.500", "flags": "K_"},
                {"pts_time": "4.000", "flags": "_"},
                {"pts_time": "5.000", "flags": "K_"},
                {"pts_time": "7.500", "flags": "K_"},
            ]
        }
        mock_check_output.return_value = json.dumps(fake_ffprobe_pkts).encode("utf-8")

        # Seeking to 6.2 should land on keyframe at 5.0
        kf = find_keyframe_before(self.video_path, 6.2)
        self.assertEqual(kf, 5.0)

    # ─── Streaming Execution Generators ───────────────────────────────────────
    @patch("backend.streamer.subprocess.Popen")
    @patch("backend.video_probe.probe_video_details")
    @patch("backend.audio_probe.probe_audio_tracks")
    def test_stream_video_convert_generator(self, mock_audio, mock_video, mock_popen):
        """Verify stream_video_convert launches FFmpeg process and streams MP4 chunks."""
        mock_video.return_value = {"is_h264": False, "height": 1080}
        mock_audio.return_value = [{"index": 0, "codec": "AAC"}]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.read.side_effect = [b"chunk_1", b"chunk_2", b""]
        mock_popen.return_value = mock_proc

        with self.app.test_request_context():
            response = stream_video_convert(self.video_path, audio_track_index=0, start_time=0.0)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "video/mp4")
            self.assertIn("X-Content-Start", response.headers)

            data = b"".join(response.response)
            self.assertEqual(data, b"chunk_1chunk_2")

    @patch("backend.streamer.subprocess.Popen")
    @patch("backend.audio_probe.probe_audio_tracks")
    @patch("backend.streamer.os.path.exists", return_value=True)
    def test_stream_audio_only_generator(self, mock_exists, mock_audio, mock_popen):
        """Verify stream_audio_only produces ADTS AAC audio stream."""
        mock_audio.return_value = [{"index": 0, "codec": "AAC"}]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.read.side_effect = [b"adts_chunk_1", b""]
        mock_popen.return_value = mock_proc

        with self.app.test_request_context():
            response = stream_audio_only(self.video_path, track_index=0, start_time=5.0)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "audio/aac")

            data = b"".join(response.response)
            self.assertEqual(data, b"adts_chunk_1")


class TestStreamingRouteIntegration(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        from backend.routes.streaming import streaming_bp
        self.app.register_blueprint(streaming_bp)
        self.client = self.app.test_client()

    @patch("backend.routes.streaming.get_best_media_source")
    @patch("backend.routes.streaming.kids_guard_media")
    @patch("backend.routes.streaming.stream_file")
    def test_api_stream_direct_route(self, mock_stream_file, mock_guard, mock_get_media):
        """Verify GET /api/stream/<id> calls stream_file for standard playback."""
        mock_get_media.return_value = {"id": 1, "file_path": "/path/to/media.mp4"}
        mock_guard.return_value = None
        mock_stream_file.return_value = "stream_response"

        resp = self.client.get("/api/stream/1")
        mock_stream_file.assert_called_once_with("/path/to/media.mp4")

    @patch("backend.routes.streaming.get_best_media_source")
    @patch("backend.routes.streaming.kids_guard_media")
    @patch("backend.streamer.stream_video_convert")
    def test_api_stream_transcode_route(self, mock_convert, mock_guard, mock_get_media):
        """Verify GET /api/stream/<id>?transcode=1 dispatches to stream_video_convert."""
        mock_get_media.return_value = {"id": 2, "file_path": "/path/to/hevc.mkv"}
        mock_guard.return_value = None
        mock_convert.return_value = "transcode_response"

        self.client.get("/api/stream/2?transcode=1&max_height=720&audio_track=1&start=45.5")
        mock_convert.assert_called_once_with(
            "/path/to/hevc.mkv",
            audio_track_index=1,
            start_time=45.5,
            max_height=720
        )

    @patch("backend.routes.streaming.get_best_media_source")
    @patch("backend.routes.streaming.kids_guard_media")
    @patch("backend.streamer.stream_audio_only")
    def test_api_stream_audio_only_route(self, mock_audio, mock_guard, mock_get_media):
        """Verify GET /api/stream/<id>?audio_only=1 dispatches to stream_audio_only."""
        mock_get_media.return_value = {"id": 3, "file_path": "/path/to/anime.mkv"}
        mock_guard.return_value = None
        mock_audio.return_value = "audio_response"

        self.client.get("/api/stream/3?audio_only=1&audio_track=2&at=120.0")
        mock_audio.assert_called_once_with(
            "/path/to/anime.mkv",
            2,
            start_time=120.0
        )

    @patch("backend.routes.streaming.get_best_media_source")
    @patch("backend.routes.streaming.kids_guard_media")
    @patch("backend.streamer.stream_video_convert")
    def test_api_stream_force_sw_transcode_route(self, mock_convert, mock_guard, mock_get_media):
        """Verify GET /api/stream/<id>?transcode=1&sw=1 dispatches to stream_video_convert with force_sw=True."""
        mock_get_media.return_value = {"id": 4, "file_path": "/path/to/corrupt.mp4"}
        mock_guard.return_value = None
        mock_convert.return_value = "transcode_response"

        self.client.get("/api/stream/4?transcode=1&sw=1")
        mock_convert.assert_called_once_with(
            "/path/to/corrupt.mp4",
            audio_track_index=0,
            start_time=0.0,
            max_height=1080,
            force_sw=True
        )


if __name__ == "__main__":
    unittest.main()
