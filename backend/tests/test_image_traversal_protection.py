# -*- coding: utf-8 -*-
"""
backend/tests/test_image_traversal_protection.py — Verify path traversal protection
on /metadata/images and /metadata/avatars endpoints.
"""
import sys
import unittest
from unittest.mock import MagicMock

if "app" in sys.modules and isinstance(sys.modules["app"], MagicMock):
    del sys.modules["app"]
from app import app


class TestImageTraversalProtection(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_metadata_images_blocks_path_traversal(self):
        """Verify requesting ../../ traverses are rejected with 403 Forbidden."""
        res = self.client.get("/metadata/images/..%2f..%2fconfig.json")
        self.assertEqual(res.status_code, 403)

    def test_metadata_avatars_blocks_path_traversal(self):
        """Verify avatar requests with traversal are rejected with 403 Forbidden."""
        res = self.client.get("/metadata/avatars/..%2f..%2fapp.py")
        self.assertEqual(res.status_code, 403)

    def test_metadata_images_fallback_svg_on_missing(self):
        """Verify normal non-existent image request serves SVG loading placeholder without error."""
        res = self.client.get("/metadata/images/w500_missing12345.jpg")
        self.assertEqual(res.status_code, 200)
        self.assertIn("image/svg+xml", res.content_type)


if __name__ == "__main__":
    unittest.main()
