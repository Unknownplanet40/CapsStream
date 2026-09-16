# -*- coding: utf-8 -*-
"""
backend/utils/diagnostics.py — System health and resource diagnostics.

Collects CPU %, RAM used/total, active video streams, and database size
using built-in Windows APIs (ctypes) and SQLite queries with zero external dependencies.
"""
import os
import sys
import time
import ctypes

from backend.db import DB_PATH, get_conn
from backend.streamer import _ACTIVE_STREAMS, _STREAM_LOCK
from backend.utils.formatting import format_bytes


# Windows-specific API structures
if hasattr(ctypes, "windll"):
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    def _ft_to_int(ft):
        return (ft.dwHighDateTime << 32) + ft.dwLowDateTime
else:
    MEMORYSTATUSEX = None
    FILETIME = None
    def _ft_to_int(ft):
        return 0


# Cached last CPU times for delta calculation across polling intervals
_LAST_CPU_CHECK = {"idle": 0, "total": 0, "time": 0.0, "pct": 0.0}


def get_system_diagnostics():
    """
    Collect and return current system performance and resource metrics.
    Returns:
        dict: {
            ok: bool,
            cpu_pct: float,
            ram_used_gb: float,
            ram_total_gb: float,
            ram_pct: int,
            active_streams: int,
            db_size: str,
            db_size_bytes: int
        }
    """
    global _LAST_CPU_CHECK
    now = time.time()
    cpu_pct = 0.0
    ram_used_gb = 0.0
    ram_total_gb = 0.0
    ram_pct = 0

    # 1. RAM & CPU via Win32 ctypes
    if hasattr(ctypes, "windll") and MEMORYSTATUSEX and FILETIME:
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            ram_total_gb = round(stat.ullTotalPhys / (1024**3), 1)
            ram_used_gb = round((stat.ullTotalPhys - stat.ullAvailPhys) / (1024**3), 1)
            ram_pct = int(stat.dwMemoryLoad)
        except Exception:
            pass

        try:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            i_now, k_now, u_now = _ft_to_int(idle), _ft_to_int(kernel), _ft_to_int(user)
            t_now = k_now + u_now

            if _LAST_CPU_CHECK["time"] > 0 and (now - _LAST_CPU_CHECK["time"]) >= 0.2:
                idle_delta = i_now - _LAST_CPU_CHECK["idle"]
                total_delta = t_now - _LAST_CPU_CHECK["total"]
                if total_delta > 0:
                    cpu_pct = round(max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta)), 1)
                else:
                    cpu_pct = _LAST_CPU_CHECK["pct"]
            else:
                time.sleep(0.04)
                idle2, kernel2, user2 = FILETIME(), FILETIME(), FILETIME()
                ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2))
                i2, k2, u2 = _ft_to_int(idle2), _ft_to_int(kernel2), _ft_to_int(user2)
                t2 = k2 + u2
                total_delta = t2 - t_now
                idle_delta = i2 - i_now
                if total_delta > 0:
                    cpu_pct = round(max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta)), 1)
                i_now, t_now = i2, t2
                now = time.time()

            _LAST_CPU_CHECK = {"idle": i_now, "total": t_now, "time": now, "pct": cpu_pct}
        except Exception:
            pass

    # 2. Active stream count (active FFmpeg transcode processes + direct playback heartbeats)
    active_ffmpeg = 0
    try:
        with _STREAM_LOCK:
            for sid, proc in list(_ACTIVE_STREAMS.items()):
                try:
                    if proc.poll() is None:
                        active_ffmpeg += 1
                    else:
                        _ACTIVE_STREAMS.pop(sid, None)
                except Exception:
                    pass
    except Exception:
        pass

    active_heartbeats = 0
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT count(DISTINCT profile_id) FROM watch_progress WHERE updated_at >= datetime('now', '-30 seconds') AND completed = 0"
        ).fetchone()
        active_heartbeats = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    active_streams = max(active_ffmpeg, active_heartbeats)

    # 3. SQLite Database size
    db_size_str = "0 KB"
    db_size_bytes = 0
    try:
        if os.path.exists(DB_PATH):
            db_size_bytes = os.path.getsize(DB_PATH)
            db_size_str = format_bytes(db_size_bytes)
    except Exception:
        pass

    return {
        "ok": True,
        "cpu_pct": cpu_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "ram_pct": ram_pct,
        "active_streams": active_streams,
        "db_size": db_size_str,
        "db_size_bytes": db_size_bytes,
    }
