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

    def test_tray_dark_mode(self):
        from backend.tray import enable_windows_dark_mode
        tray = CapsStreamTray(
            local_url="http://127.0.0.1:8000",
            lan_url="http://192.168.1.100:8000",
            dark_mode=True,
        )
        self.assertTrue(tray.dark_mode)
        # Verify enable_windows_dark_mode runs without raising exceptions
        enable_windows_dark_mode(None, force=True)
        enable_windows_dark_mode(None, force=False)

    def test_window_detection_filtering(self):
        """Verify is_capsstream_title ignores GitHub, searches, and matches actual app."""
        from silent_launcher import is_capsstream_title

        # Negative test cases (should NOT match)
        self.assertFalse(is_capsstream_title("Release · Unknownplanet40/CapsStream · GitHub - Google Chrome", "chrome.exe"))
        self.assertFalse(is_capsstream_title("Unknownplanet40/CapsStream: Portable media server - Google Chrome", "chrome.exe"))
        self.assertFalse(is_capsstream_title("capsstream - Google Search - Microsoft Edge", "msedge.exe"))
        self.assertFalse(is_capsstream_title("capsstream reddit - Google Search - Brave", "brave.exe"))
        self.assertFalse(is_capsstream_title("CapsStream", "notepad.exe"))
        self.assertFalse(is_capsstream_title("CapsStream", "cmd.exe"))
        self.assertFalse(is_capsstream_title("", "msedge.exe"))

        # Positive test cases (MUST match)
        self.assertTrue(is_capsstream_title("CapsStream", "msedge.exe"))
        self.assertTrue(is_capsstream_title("CapsStream", "chrome.exe"))
        self.assertTrue(is_capsstream_title("CapsStream - Microsoft Edge", "msedge.exe"))
        self.assertTrue(is_capsstream_title("CapsStream - Personal - Microsoft Edge", "msedge.exe"))
        self.assertTrue(is_capsstream_title("CapsStream - Google Chrome", "chrome.exe"))
        self.assertTrue(is_capsstream_title("CapsStream — Mozilla Firefox", "firefox.exe"))
        self.assertTrue(is_capsstream_title("http://127.0.0.1:8000 - Brave", "brave.exe"))
        self.assertTrue(is_capsstream_title("localhost:8000 - Opera", "opera.exe"))

    @patch("subprocess.Popen")
    @patch("os.name", "nt")
    def test_send_toast_action_buttons_and_silent_execution(self, mock_popen):
        """Verify silent_launcher.send_toast generates action buttons and executes 100% silently."""
        from silent_launcher import send_toast
        import base64
        import subprocess

        actions = [
            {"content": "Open CapsStream", "arguments": "http://127.0.0.1:8000", "activationType": "protocol"},
            {"content": "Open LAN Stream", "arguments": "http://192.168.1.50:8000", "activationType": "protocol"},
            {"content": "Dismiss", "arguments": "dismiss", "activationType": "system"},
        ]
        send_toast(
            "CapsStream is running",
            "Serving on LAN: http://192.168.1.50:8000",
            actions=actions,
            launch_url="http://127.0.0.1:8000",
        )

        self.assertTrue(mock_popen.called)
        args, kwargs = mock_popen.call_args
        cmd = args[0]

        # Verify command contains hidden and non-interactive switches
        self.assertIn("powershell.exe", cmd[0])
        self.assertIn("-WindowStyle", cmd)
        self.assertIn("Hidden", cmd)
        self.assertIn("-NonInteractive", cmd)
        self.assertIn("-NoProfile", cmd)
        self.assertIn("-EncodedCommand", cmd)

        # Verify creationflags has CREATE_NO_WINDOW (0x08000000)
        self.assertEqual(kwargs.get("creationflags"), 0x08000000)

        # Verify startupinfo is configured with SW_HIDE
        si = kwargs.get("startupinfo")
        self.assertIsNotNone(si)
        self.assertEqual(si.dwFlags & subprocess.STARTF_USESHOWWINDOW, subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(si.wShowWindow, 0)

        # Decode base64 powershell script
        enc_idx = cmd.index("-EncodedCommand") + 1
        decoded_ps = base64.b64decode(cmd[enc_idx]).decode("utf-16le")

        # Verify toast XML elements
        self.assertIn("Open CapsStream", decoded_ps)
        self.assertIn("Open LAN Stream", decoded_ps)
        self.assertIn("Dismiss", decoded_ps)
        self.assertIn("activationType=\"protocol\"", decoded_ps)
        self.assertIn("activationType=\"system\"", decoded_ps)
        self.assertIn("launch=\"http://127.0.0.1:8000\"", decoded_ps)
        self.assertIn("$ProgressPreference = 'SilentlyContinue'", decoded_ps)


if __name__ == "__main__":
    unittest.main()

