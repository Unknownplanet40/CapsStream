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
    stop_active_stream,
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
    def test_stream_audio_only_generator(self, mock_audio, mock_popen):
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

    def test_stop_active_stream_matching_media_id(self):
        """Verify stop_active_stream terminates matching processes and leaves others intact."""
        from backend.streamer import _ACTIVE_STREAMS, _STREAM_LOCK
        proc1 = MagicMock()
        proc1.poll.return_value = None
        proc1._media_id = 101
        proc1._file_path = "/path/to/media1.mkv"

        proc2 = MagicMock()
        proc2.poll.return_value = None
        proc2._media_id = 102
        proc2._file_path = "/path/to/media2.mkv"

        with _STREAM_LOCK:
            _ACTIVE_STREAMS["stream_1"] = proc1
            _ACTIVE_STREAMS["stream_2"] = proc2

        try:
            killed = stop_active_stream(media_id=101)
            self.assertEqual(killed, 1)
            proc1.kill.assert_called_once()
            proc2.kill.assert_not_called()
            self.assertNotIn("stream_1", _ACTIVE_STREAMS)
            self.assertIn("stream_2", _ACTIVE_STREAMS)

            # Terminate all remaining
            killed_all = stop_active_stream()
            self.assertEqual(killed_all, 1)
            proc2.kill.assert_called_once()
            self.assertEqual(len(_ACTIVE_STREAMS), 0)
        finally:
            with _STREAM_LOCK:
                _ACTIVE_STREAMS.clear()


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
            max_height=720,
            media_id=2
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
            start_time=120.0,
            media_id=3
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
            media_id=4,
            force_sw=True
        )

    @patch("backend.streamer.stop_active_stream")
    def test_api_stop_stream_route(self, mock_stop):
        """Verify POST /api/stream/stop/<id> terminates the active conversion for that media ID."""
        mock_stop.return_value = 1
        resp = self.client.post("/api/stream/stop/42")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("stopped"))
        self.assertEqual(data.get("media_id"), 42)
        self.assertEqual(data.get("killed"), 1)
        mock_stop.assert_called_once_with(media_id=42)

    @patch("backend.streamer.stop_active_stream")
    def test_api_stop_all_streams_route(self, mock_stop):
        """Verify POST /api/stream/stop-all terminates all active transcode streams."""
        mock_stop.return_value = 2
        resp = self.client.post("/api/stream/stop-all")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("stopped"))
        self.assertEqual(data.get("killed"), 2)
        mock_stop.assert_called_once_with()

    @patch("backend.routes.streaming.get_media_quality_options")
    def test_api_quality_options_route(self, mock_get_opts):
        """Verify GET /api/quality-options/<id> returns options formatted by get_media_quality_options."""
        mock_get_opts.return_value = [
            {"media_id": 10, "quality_id": "10_direct", "type": "direct", "display_label": "4K UHD", "is_transcode": False},
            {"media_id": 10, "quality_id": "10_transcode_1080", "type": "transcode", "display_label": "Convert to 1080p (Full HD)", "is_transcode": True, "target_height": 1080},
            {"media_id": 10, "quality_id": "10_transcode_720", "type": "transcode", "display_label": "Convert to 720p (HD)", "is_transcode": True, "target_height": 720},
            {"media_id": 10, "quality_id": "10_transcode_480", "type": "transcode", "display_label": "Convert to 480p (SD)", "is_transcode": True, "target_height": 480},
        ]
        resp = self.client.get("/api/quality-options/10")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 4)
        self.assertTrue(any(o.get("is_transcode") and o.get("target_height") == 1080 for o in data))

    @patch("backend.db.media.get_all_sources_for_media")
    @patch("backend.db.media.get_media_by_id")
    @patch("backend.video_probe.probe_video_resolution")
    def test_get_media_quality_options_generates_transcode_presets_for_4k(self, mock_probe, mock_get_media, mock_get_sources):
        """Verify get_media_quality_options automatically generates downscaled conversion options for 4K media."""
        from backend.db.media import get_media_quality_options
        mock_media = {
            "id": 99,
            "file_path": "C:\\Media\\Movies\\Interstellar.2014.2160p.UHD.BluRay.x265.mkv",
            "file_size": 25000000000,
            "is_mounted": True,
        }
        mock_get_media.return_value = mock_media
        mock_get_sources.return_value = [mock_media]
        mock_probe.return_value = {
            "height": 2160,
            "width": 3840,
            "label": "4K UHD (2160p)",
            "base_label": "4K",
        }

        opts = get_media_quality_options(99)
        self.assertTrue(len(opts) >= 4)

        # Verify direct 4K option
        direct_opts = [o for o in opts if not o.get("is_transcode")]
        self.assertEqual(len(direct_opts), 1)
        self.assertEqual(direct_opts[0]["quality_id"], "99_direct")
        self.assertEqual(direct_opts[0]["target_height"], 2160)

        # Verify downscaled transcode presets
        transcode_opts = [o for o in opts if o.get("is_transcode")]
        target_heights = [o["target_height"] for o in transcode_opts]
        self.assertIn(1080, target_heights)
        self.assertIn(720, target_heights)
        self.assertIn(480, target_heights)

        opt_1080 = next(o for o in transcode_opts if o["target_height"] == 1080)
        self.assertEqual(opt_1080["quality_id"], "99_transcode_1080")
        self.assertEqual(opt_1080["display_label"], "Convert to 1080p (Full HD)")
        self.assertTrue(opt_1080["is_transcode"])

    @patch("backend.db.media.get_all_sources_for_media")
    @patch("backend.db.media.get_media_by_id")
    @patch("backend.video_probe.probe_video_resolution")
    def test_get_media_quality_options_no_transcode_for_standard_1080p_x264(self, mock_probe, mock_get_media, mock_get_sources):
        """Verify get_media_quality_options does NOT generate converted presets (e.g. 480p) for standard 1080p x264."""
        from backend.db.media import get_media_quality_options
        mock_media = {
            "id": 101,
            "file_path": "C:\\Media\\Movies\\Movie.2020.1080p.BluRay.x264.mp4",
            "file_size": 2500000000,
            "is_mounted": True,
        }
        mock_get_media.return_value = mock_media
        mock_get_sources.return_value = [mock_media]
        mock_probe.return_value = {
            "height": 1080,
            "width": 1920,
            "codec": "x264",
            "label": "1080p HD • x264",
            "base_label": "1080p HD",
        }

        opts = get_media_quality_options(101)
        # Only direct stream option should exist
        self.assertEqual(len(opts), 1)
        self.assertFalse(opts[0].get("is_transcode"))
        self.assertEqual(opts[0]["quality_id"], "101_direct")

    @patch("backend.db.media.get_all_sources_for_media")
    @patch("backend.db.media.get_media_by_id")
    @patch("backend.video_probe.probe_video_resolution")
    def test_get_media_quality_options_generates_transcode_presets_for_x265_1080p(self, mock_probe, mock_get_media, mock_get_sources):
        """Verify get_media_quality_options generates conversion options for x265/HEVC content."""
        from backend.db.media import get_media_quality_options
        mock_media = {
            "id": 102,
            "file_path": "C:\\Media\\Movies\\Movie.2020.1080p.x265.mkv",
            "file_size": 1500000000,
            "is_mounted": True,
        }
        mock_get_media.return_value = mock_media
        mock_get_sources.return_value = [mock_media]
        mock_probe.return_value = {
            "height": 1080,
            "width": 1920,
            "codec": "x265",
            "label": "1080p HD • x265",
            "base_label": "1080p HD",
        }

        opts = get_media_quality_options(102)
        transcode_opts = [o for o in opts if o.get("is_transcode")]
        self.assertTrue(len(transcode_opts) >= 1)
        target_heights = [o["target_height"] for o in transcode_opts]
        self.assertIn(480, target_heights)


if __name__ == "__main__":
    unittest.main()

