# -*- coding: utf-8 -*-
"""
Tests for safe_logo_path security validation and media logo handling.
"""
import os
import unittest
import tempfile
import shutil
from backend.matcher import safe_logo_path
import backend.matcher as matcher_module


class TestSafeLogoPath(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="capsstream_logo_test_")
        self.orig_images_dir = matcher_module.IMAGES_DIR
        matcher_module.IMAGES_DIR = self.test_dir

        # Create valid test files
        self.valid_png = "w500_valid_logo.png"
        self.valid_svg = "w500_valid_logo.svg"
        self.valid_webp = "w500_valid_logo.webp"

        for fname in (self.valid_png, self.valid_svg, self.valid_webp):
            with open(os.path.join(self.test_dir, fname), "wb") as f:
                f.write(b"dummy image content")

    def tearDown(self):
        matcher_module.IMAGES_DIR = self.orig_images_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_valid_logo_paths(self):
        self.assertEqual(safe_logo_path(f"images/{self.valid_png}"), f"images/{self.valid_png}")
        self.assertEqual(safe_logo_path(f"images/{self.valid_svg}"), f"images/{self.valid_svg}")
        self.assertEqual(safe_logo_path(f"images/{self.valid_webp}"), f"images/{self.valid_webp}")

    def test_nonexistent_file_rejected(self):
        self.assertIsNone(safe_logo_path("images/nonexistent_logo.png"))

    def test_missing_or_invalid_prefix_rejected(self):
        self.assertIsNone(safe_logo_path(self.valid_png))
        self.assertIsNone(safe_logo_path(f"/images/{self.valid_png}"))
        self.assertIsNone(safe_logo_path(f"metadata/images/{self.valid_png}"))
        self.assertIsNone(safe_logo_path(f"http://example.com/images/{self.valid_png}"))

    def test_path_traversal_rejected(self):
        self.assertIsNone(safe_logo_path(f"images/../{self.valid_png}"))
        self.assertIsNone(safe_logo_path("images/../../etc/passwd"))
        self.assertIsNone(safe_logo_path(f"images/subdir/../../{self.valid_png}"))

    def test_suspicious_characters_and_nested_paths_rejected(self):
        self.assertIsNone(safe_logo_path(f"images\\{self.valid_png}"))
        self.assertIsNone(safe_logo_path(f"images/nested/{self.valid_png}"))
        self.assertIsNone(safe_logo_path("images/C:test.png"))

    def test_unsupported_extensions_rejected(self):
        jpg_name = "test_logo.jpg"
        with open(os.path.join(self.test_dir, jpg_name), "wb") as f:
            f.write(b"jpg data")
        self.assertIsNone(safe_logo_path(f"images/{jpg_name}"))
        self.assertIsNone(safe_logo_path("images/test_logo.exe"))
        self.assertIsNone(safe_logo_path("images/test_logo.gif"))

    def test_empty_and_non_string_types(self):
        self.assertIsNone(safe_logo_path(None))
        self.assertIsNone(safe_logo_path(""))
        self.assertIsNone(safe_logo_path(12345))
        self.assertIsNone(safe_logo_path({}))
