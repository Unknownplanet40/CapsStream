# -*- coding: utf-8 -*-
"""
Tests for Video Streaming Module (backend/streamer.py)
Covers HTTP Range requests, 206 Partial Content, Content-Range calculations,
MIME type headers, and buffer chunking.
"""
import os
import sys
import unittest
import tempfile
import shutil
from flask import Flask
from werkzeug.exceptions import HTTPException

from backend.streamer import stream_file


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


if __name__ == "__main__":
    unittest.main()
