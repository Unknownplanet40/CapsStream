# -*- coding: utf-8 -*-
"""
backend/discovery.py — Lightweight UDP LAN Discovery Service for CapsStream.
Allows mobile apps, Android TV clients, and companion devices on the local Wi-Fi
to discover the CapsStream server instantly without manual IP configuration.
"""
import socket
import threading
import json
import logging
from typing import Optional

logger = logging.getLogger("capsstream.discovery")

DISCOVERY_PORT = 8001
DISCOVERY_MAGIC = "CAPSSTREAM_DISCOVER"

_discovery_service: Optional["DiscoveryService"] = None


class DiscoveryService:
    def __init__(self, http_port: int, ssl: bool = False):
        self.http_port = http_port
        self.ssl = ssl
        self._running = False
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True, name="capsstream-discovery")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def _listen(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("", DISCOVERY_PORT))
            self._sock.settimeout(2.0)
            logger.info(f"UDP LAN discovery responder active on port {DISCOVERY_PORT}")
        except Exception as e:
            logger.warning(f"Could not bind UDP discovery socket on port {DISCOVERY_PORT}: {e}")
            self._running = False
            return

        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                msg = data.decode("utf-8", errors="ignore").strip()
                if DISCOVERY_MAGIC in msg:
                    from backend.utils.network import get_device_ip
                    dev_ip = get_device_ip()
                    proto = "https" if self.ssl else "http"
                    response = json.dumps({
                        "service": "capsstream",
                        "ip": dev_ip,
                        "port": self.http_port,
                        "ssl": self.ssl,
                        "url": f"{proto}://{dev_ip}:{self.http_port}"
                    }).encode("utf-8")
                    self._sock.sendto(response, addr)
                    logger.debug(f"Replied to discovery beacon from {addr}")
            except socket.timeout:
                continue
            except Exception:
                if not self._running:
                    break


def start_discovery_service(http_port: int, ssl: bool = False):
    """Start global background UDP discovery responder."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DiscoveryService(http_port=http_port, ssl=ssl)
        _discovery_service.start()
    return _discovery_service


def stop_discovery_service():
    """Stop global UDP discovery responder."""
    global _discovery_service
    if _discovery_service is not None:
        _discovery_service.stop()
        _discovery_service = None
