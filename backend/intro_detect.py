"""
intro_detect.py — Local, FFmpeg-based intro detection for any show.

Heuristic: TV intros almost always sit between two quiet moments — the
recap/scene before the intro fades to silence, the theme song plays, then
silence again before dialogue resumes. Running ffmpeg's silencedetect over
the first few minutes and looking for that "silence → content → silence"
pattern finds the intro without any external API.

Results are conservative (15s–300s window) and stored in the skip-time
cache with source "audio" — users can always override them in the
Edit Skip Timestamps modal.
"""

import os
import re
import subprocess

from backend.proc_utils import CREATE_NO_WINDOW

# Run ffmpeg at below-normal priority so intro analysis never starves
# media streaming / library queries of disk I/O.
BELOW_NORMAL_PRIORITY = 0x00004000 if os.name == "nt" else 0

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG_BIN = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")

ANALYZE_SECONDS = 420   # only analyze the first 7 minutes
MIN_INTRO = 15          # shorter than this is noise
MAX_INTRO = 300         # longer than this isn't an intro


def detect_intro(file_path):
    """
    Returns {"start": float, "end": float} for the detected intro segment,
    or None when no confident pattern is found.
    """
    if not file_path or not os.path.isfile(file_path) or not os.path.exists(FFMPEG_BIN):
        return None

    cmd = [
        FFMPEG_BIN, "-hide_banner",
        "-t", str(ANALYZE_SECONDS),
        "-i", file_path,
        "-af", "silencedetect=noise=-30dB:d=0.8",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY,
        )
    except Exception:
        return None

    stderr = proc.stderr or ""
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", stderr)]
    if not starts or not ends:
        return None

    # Pair each silence_start with the first silence_end after it
    intervals = []
    for s in starts:
        e = next((x for x in ends if x > s), None)
        if e is not None:
            intervals.append((s, e))
    if not intervals:
        return None

    # The first silence ending past the 20s mark is the pre-intro boundary
    # (recap/cold-open ends). The intro runs until the next silence begins.
    first_boundary = next((e for (s, e) in intervals if e >= 20), None)
    if first_boundary is None:
        return None
    next_silence = next((s for (s, e) in intervals if s > first_boundary + 5), None)
    if next_silence is None:
        return None

    start, end = first_boundary, next_silence
    if MIN_INTRO <= (end - start) <= MAX_INTRO and end < ANALYZE_SECONDS:
        return {"start": round(start, 2), "end": round(end, 2)}

    return None
