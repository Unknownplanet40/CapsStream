"""
video_probe.py — Probes video dimensions, codec tags (x265, x264, AV1), and formats clean resolution labels.
"""

import os
import subprocess
import json

from backend.proc_utils import CREATE_NO_WINDOW

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFPROBE_BIN = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffprobe.exe")

# Probe results cached per file+size+mtime — avoids re-spawning ffprobe
# (slow over network storage) on every detail view / quality menu open.
_PROBE_CACHE = {}
_PROBE_CACHE_MAX = 4096


def extract_codec_tag(codec_name, file_path=""):
    codec = (codec_name or "").lower().strip()
    filename = os.path.basename(file_path or "").lower()

    # 1. Ground truth from ffprobe stream codec_name
    if codec in ("hevc", "h265"):
        return "x265"
    elif codec in ("h264", "avc"):
        return "x264"
    elif codec == "av1":
        return "AV1"
    elif codec == "vp9":
        return "VP9"

    # 2. Fallback: inspect filename only (never full path / parent folders)
    if "x265" in filename or "h265" in filename or "hevc" in filename or "h.265" in filename:
        return "x265"
    elif "x264" in filename or "h264" in filename or "avc" in filename or "h.264" in filename:
        return "x264"
    elif "av1" in filename:
        return "AV1"
    elif "vp9" in filename:
        return "VP9"

    if codec:
        return codec.upper()
    return ""


def probe_video_resolution(file_path):
    """
    Probes video file using ffprobe and returns dict with width, height, codec, and res_label.
    Results are cached by (path, size, mtime).
    """
    width, height = 0, 0
    codec_name = ""

    if os.path.isfile(file_path) and os.path.exists(FFPROBE_BIN):
        try:
            st = os.stat(file_path)
            cache_key = (os.path.abspath(file_path), st.st_size, st.st_mtime)
            cached = _PROBE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            cmd = [
                FFPROBE_BIN,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                file_path
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10,
                                          creationflags=CREATE_NO_WINDOW)
            data = json.loads(out.decode("utf-8", errors="ignore"))
            streams = data.get("streams", [])

            for s in streams:
                if s.get("codec_type") == "video":
                    width = int(s.get("width") or 0)
                    height = int(s.get("height") or 0)
                    codec_name = s.get("codec_name") or ""
                    if height > 0:
                        break
        except Exception as e:
            print(f"[VideoProbe] Error probing {file_path}: {e}")
            return _format_probe_result(width, height, codec_name, file_path)

        result = _format_probe_result(width, height, codec_name, file_path)
        if len(_PROBE_CACHE) >= _PROBE_CACHE_MAX:
            _PROBE_CACHE.clear()
        _PROBE_CACHE[cache_key] = result
        return result

    return _format_probe_result(width, height, codec_name, file_path)


def _format_probe_result(width, height, codec_name, file_path):
    codec_tag = extract_codec_tag(codec_name, file_path)
    res_base = format_resolution_label(width, height)

    if codec_tag:
        label = f"{res_base} • {codec_tag}"
    else:
        label = res_base

    return {
        "width": width,
        "height": height,
        "codec": codec_tag,
        "base_label": res_base,
        "label": label
    }


def format_resolution_label(width, height):
    if height >= 2160 or width >= 3840:
        return "4K UHD"
    elif height >= 1440 or width >= 2560:
        return "1440p QHD"
    elif height >= 1080 or width >= 1920:
        return "1080p HD"
    elif height >= 720 or width >= 1280:
        return "720p HD"
    elif height >= 480 or width >= 854:
        return "480p SD"
    elif height > 0:
        return f"{height}p"
    return "Standard Quality"


def probe_video_details(file_path):
    """
    Detailed probe of media streams including video codec, pixel format,
    H.264 compatibility, and audio track details.
    """
    if not file_path or not os.path.isfile(file_path) or not os.path.exists(FFPROBE_BIN):
        return {"video_codec": "", "pix_fmt": "", "is_h264": False, "width": 0, "height": 0, "audio_tracks": []}

    try:
        st = os.stat(file_path)
        cache_key = ("details", os.path.abspath(file_path), st.st_size, st.st_mtime)
        cached = _PROBE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        cmd = [
            FFPROBE_BIN,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            file_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10,
                                      creationflags=CREATE_NO_WINDOW)
        data = json.loads(out.decode("utf-8", errors="ignore"))
        streams = data.get("streams", [])

        v_codec = ""
        pix_fmt = ""
        width, height = 0, 0
        audio_tracks = []

        for s in streams:
            ctype = s.get("codec_type")
            if ctype == "video" and not v_codec:
                v_codec = (s.get("codec_name") or "").lower()
                pix_fmt = (s.get("pix_fmt") or "").lower()
                width = int(s.get("width") or 0)
                height = int(s.get("height") or 0)
            elif ctype == "audio":
                audio_tracks.append({
                    "codec": s.get("codec_name") or "",
                    "channels": int(s.get("channels") or 2),
                    "sample_rate": s.get("sample_rate") or "",
                })

        is_h264 = v_codec in ("h264", "avc", "avc1") and ("10" not in pix_fmt)

        res = {
            "video_codec": v_codec,
            "pix_fmt": pix_fmt,
            "is_h264": is_h264,
            "width": width,
            "height": height,
            "audio_tracks": audio_tracks,
        }

        if len(_PROBE_CACHE) >= _PROBE_CACHE_MAX:
            _PROBE_CACHE.clear()
        _PROBE_CACHE[cache_key] = res
        return res
    except Exception as e:
        print(f"[VideoProbe] Details probe error for {file_path}: {e}")
        return {"video_codec": "", "pix_fmt": "", "is_h264": False, "width": 0, "height": 0, "audio_tracks": []}

