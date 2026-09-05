# -*- coding: utf-8 -*-
"""
backend/tests/test_discovery.py — Tests for UDP LAN Discovery service.
"""
import time
import json
import socket
import unittest
from backend.discovery import DiscoveryService, DISCOVERY_MAGIC


class TestDiscoveryService(unittest.TestCase):
    def test_udp_discovery_response(self):
        service = DiscoveryService(http_port=8999, ssl=False)
        service.start()
        time.sleep(0.1)

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client_sock.settimeout(1.5)

        try:
            # Send probe to localhost on DISCOVERY_PORT (8001)
            client_sock.sendto(DISCOVERY_MAGIC.encode("utf-8"), ("127.0.0.1", 8001))
            data, addr = client_sock.recvfrom(1024)
            payload = json.loads(data.decode("utf-8"))

            self.assertEqual(payload.get("service"), "capsstream")
            self.assertEqual(payload.get("port"), 8999)
            self.assertFalse(payload.get("ssl"))
            self.assertTrue("url" in payload)
            self.assertTrue("ip" in payload)
        finally:
            client_sock.close()
            service.stop()


if __name__ == "__main__":
    unittest.main()
