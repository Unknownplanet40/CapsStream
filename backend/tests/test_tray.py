# -*- coding: utf-8 -*-
"""
backend/tests/test_tray.py — Tests for native Windows System Tray companion.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

from backend.tray import CapsStreamTray, copy_to_clipboard, get_lan_url, open_folder


class TestTrayUtils(unittest.TestCase):
    def test_get_lan_url_format(self):
        url = get_lan_url(8000, ssl=False)
        self.assertTrue(url.startswith("http://"))
        self.assertTrue(url.endswith(":8000"))

        ssl_url = get_lan_url(8443, ssl=True)
        self.assertTrue(ssl_url.startswith("https://"))
        self.assertTrue(ssl_url.endswith(":8443"))

    def test_tray_initialization(self):
        tray = CapsStreamTray(
            local_url="http://127.0.0.1:8000",
            lan_url="http://192.168.1.100:8000",
            media_paths={"movies": "D:\\Movies"},
            log_dir="logs",
            data_dir="data",
        )
        self.assertEqual(tray.local_url, "http://127.0.0.1:8000")
        self.assertEqual(tray.lan_url, "http://192.168.1.100:8000")
        self.assertFalse(tray.is_exit_requested())

    @patch("backend.tray.open_folder")
    def test_handle_command_open_folders(self, mock_open_folder):
        tray = CapsStreamTray(
            local_url="http://127.0.0.1:8000",
            lan_url="http://192.168.1.100:8000",
            log_dir="C:\\test\\logs",
            data_dir="C:\\test\\data",
        )
        tray._handle_command(CapsStreamTray.CMD_OPEN_LOGS)
        mock_open_folder.assert_called_with("C:\\test\\logs")

        tray._handle_command(CapsStreamTray.CMD_OPEN_DATA)
        mock_open_folder.assert_called_with("C:\\test\\data")

    def test_handle_command_exit(self):
        exit_called = [False]

        def on_exit():
            exit_called[0] = True

        tray = CapsStreamTray(
            local_url="http://127.0.0.1:8000",
            lan_url="http://192.168.1.100:8000",
            on_exit=on_exit,
        )
        tray._handle_command(CapsStreamTray.CMD_EXIT)
        self.assertTrue(tray.is_exit_requested())


if __name__ == "__main__":
    unittest.main()
