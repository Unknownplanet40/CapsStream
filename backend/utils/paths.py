"""
backend/utils/paths.py — Single source of truth for project-root and FFmpeg binary paths.

All backend modules that need ffprobe/ffmpeg import from here instead of
computing BASE_DIR and binary paths themselves.

Previously each of these 10 files computed its own copy:
  audio_probe.py, video_probe.py, streamer.py, subtitles.py, thumbs.py,
  skip_times.py, intro_detect.py, scanner.py, routes/streaming.py, routes/admin.py
"""
import os

# Project root — two levels up from backend/utils/
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FFMPEG_BIN  = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")
FFPROBE_BIN = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffprobe.exe")


def has_ffmpeg() -> bool:
    """True if the bundled ffmpeg.exe exists and is a file."""
    return os.path.isfile(FFMPEG_BIN)


def has_ffprobe() -> bool:
    """True if the bundled ffprobe.exe exists and is a file."""
    return os.path.isfile(FFPROBE_BIN)
