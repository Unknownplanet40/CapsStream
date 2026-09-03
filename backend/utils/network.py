# -*- coding: utf-8 -*-
"""
backend/utils/network.py — Network inspection utilities for local server binding and device IP detection.
"""
import socket
import logging

logger = logging.getLogger("capsstream.network")


def get_device_ip() -> str:
    """
    Determine the primary local network IPv4 address of this machine.
    Uses UDP routing lookups without transmitting packets over the wire.
    Falls back to hostname-based resolution if unreachable.
    """
    # 1. Try UDP routing towards common subnets/targets to identify the active outbound interface
    targets = [
        ("8.8.8.8", 80),
        ("10.255.255.255", 1),
        ("192.168.255.255", 1),
        ("172.31.255.255", 1),
    ]
    for target in targets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        except Exception:
            pass

    # 2. Fallback: inspect addresses from gethostbyname_ex
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
    except Exception:
        pass

    # 3. Fallback: standard gethostbyname
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_all_device_ips() -> list[str]:
    """
    Return a list of all non-loopback IPv4 addresses detected on this machine,
    with the primary device IP ordered first.
    """
    primary = get_device_ip()
    ips = [primary] if (primary and primary != "127.0.0.1") else []

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip and not ip.startswith("127.") and ip != "0.0.0.0" and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips if ips else ["127.0.0.1"]
