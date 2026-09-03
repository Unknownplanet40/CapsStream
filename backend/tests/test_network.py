# -*- coding: utf-8 -*-
"""
backend/tests/test_network.py — Tests for network inspection and device IP utilities.
"""
import unittest
from unittest.mock import patch, MagicMock
import socket

from backend.utils.network import get_device_ip, get_all_device_ips


class TestNetworkUtils(unittest.TestCase):
    def test_get_device_ip_returns_valid_string(self):
        ip = get_device_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) >= 7)
        self.assertNotEqual(ip, "0.0.0.0")
        parts = ip.split(".")
        self.assertEqual(len(parts), 4)

    def test_get_all_device_ips_returns_list(self):
        ips = get_all_device_ips()
        self.assertIsInstance(ips, list)
        self.assertGreaterEqual(len(ips), 1)
        for ip in ips:
            parts = ip.split(".")
            self.assertEqual(len(parts), 4)

    @patch("socket.socket")
    @patch("socket.gethostbyname_ex")
    def test_get_device_ip_fallback(self, mock_gethost, mock_sock_cls):
        # Force socket UDP connect to fail
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("Network unreachable")
        mock_sock_cls.return_value = mock_sock

        # Mock gethostbyname_ex returning LAN IP
        mock_gethost.return_value = ("testhost", [], ["192.168.10.50"])

        ip = get_device_ip()
        self.assertEqual(ip, "192.168.10.50")

    @patch("socket.socket")
    @patch("socket.gethostbyname_ex")
    @patch("socket.gethostbyname")
    def test_get_device_ip_total_fallback(self, mock_gethostbyname, mock_gethost, mock_sock_cls):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("Network unreachable")
        mock_sock_cls.return_value = mock_sock

        mock_gethost.side_effect = Exception("Hostname lookup error")
        mock_gethostbyname.side_effect = Exception("Lookup failed")

        ip = get_device_ip()
        self.assertEqual(ip, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
