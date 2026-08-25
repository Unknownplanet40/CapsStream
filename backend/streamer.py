"""
streamer.py — HTTP range-request video streaming for CapsStream.

Implements RFC 7233 byte-range requests so browsers can:
- Seek to arbitrary positions in large video files
- Start playback without downloading the full file
"""

import os
import re
import json
import subprocess
import threading
from flask import Response, request, abort

from backend.proc_utils import CREATE_NO_WINDOW

# Active ffmpeg transcodes keyed by absolute file path — switching audio
# tracks rapidly used to stack multiple ffmpeg processes per file.
_TRANSCODE_LOCK = threading.Lock()
_ACTIVE_TRANSCODES = {}

# Keyframe lookup cache: (path, size, mtime, requested_t) -> keyframe_time
_KEYFRAME_CACHE = {}
_KEYFRAME_CACHE_MAX = 2048

BASE_DIR_STREAM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FFPROBE_BIN = os.path.join(BASE_DIR_STREAM, "ffmpeg", "bin", "ffprobe.exe")


def find_keyframe_before(file_path, t):
    """
    Find the timestamp of the last video keyframe at or before time `t`.

    Input seeking with '-c:v copy' always lands on the previous keyframe —
    if we pass the raw target, video starts up to a full GOP earlier than
    the audio, producing seconds of silence that users perceive as an A/V
    sync bug. Seeking to the exact keyframe instead makes video and audio
    start together, perfectly synchronized.
    """
    t = float(t or 0)
    if t <= 0:
        return 0.0

    try:
        st = os.stat(file_path)
        cache_key = (os.path.abspath(file_path), st.st_size, st.st_mtime, round(t))
    except OSError:
        return t

    cached = _KEYFRAME_CACHE.get(cache_key)
    if cached is not None:
        return cached

    result = t
    if os.path.exists(_FFPROBE_BIN):
        try:
            window_start = max(0.0, t - 60)
            cmd = [
                _FFPROBE_BIN, "-v", "quiet",
                "-select_streams", "v:0",
                "-show_packets",
                "-print_format", "json",
                "-read_intervals", f"{window_start:.3f}%{t + 0.5:.3f}",
                file_path,
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15,
                                          creationflags=CREATE_NO_WINDOW)
            data = json.loads(out.decode("utf-8", errors="ignore"))
            best = None
            for pkt in data.get("packets", []):
                flags = pkt.get("flags", "")
                if "K" not in flags:
                    continue
                try:
                    pts = float(pkt.get("pts_time") or -1)
                except (TypeError, ValueError):
                    continue
                if 0 <= pts <= t and (best is None or pts > best):
                    best = pts
            if best is not None:
                result = best
        except Exception as e:
            print(f"[Streamer] Keyframe lookup failed for {file_path}@{t}: {e}")
            result = t

    if len(_KEYFRAME_CACHE) >= _KEYFRAME_CACHE_MAX:
        _KEYFRAME_CACHE.clear()
    _KEYFRAME_CACHE[cache_key] = result
    return result


def stream_file(file_path):
    """
    Stream a file with HTTP range-request support.
    Returns a Flask Response with proper 200/206 status and headers.
    """
    if not os.path.isfile(file_path):
        abort(404, description=f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range", None)

    # Determine MIME type
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".mp4":  "video/mp4",
        ".webm": "video/webm",
        ".mkv":  "video/x-matroska",
        ".avi":  "video/x-msvideo",
        ".mov":  "video/quicktime",
        ".m4v":  "video/mp4",
        ".ts":   "video/mp2t",
        ".wmv":  "video/x-ms-wmv",
        ".flv":  "video/x-flv",
        ".m2ts": "video/mp2t",
    }
    mime_type = mime_map.get(ext, "video/mp4")

    # Default headers
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type":  mime_type,
        "Cache-Control": "no-cache",
    }

    # No Range header → serve the whole file
    if not range_header:
        def generate_full():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1 MB chunks
                    if not chunk:
                        break
                    yield chunk

        headers["Content-Length"] = str(file_size)
        return Response(generate_full(), status=200, headers=headers)

    # Parse the Range header (e.g., "bytes=0-1023")
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        abort(416, description="Invalid Range header")

    start_str, end_str = m.group(1), m.group(2)

    if start_str == "" and end_str == "":
        abort(416)

    if start_str == "":
        # Suffix range: last N bytes
        end   = file_size - 1
        start = max(0, file_size - int(end_str))
    elif end_str == "":
        start = int(start_str)
        end   = file_size - 1
    else:
        start = int(start_str)
        end   = int(end_str)

    # Clamp to valid range
    start = max(0, start)
    end   = min(end, file_size - 1)

    if start > end or start >= file_size:
        abort(416, description="Range Not Satisfiable")

    length = end - start + 1
    chunk_size = 1024 * 1024  # 1 MB

    def generate_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                data = f.read(to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update({
        "Content-Length": str(length),
        "Content-Range":  f"bytes {start}-{end}/{file_size}",
    })

    return Response(generate_range(), status=206, headers=headers)


# Active audio-only streams keyed separately from video remuxes.
_ACTIVE_AUDIO_STREAMS = {}

# ─── Hardware-Accelerated Transcoding ────────────────────────────────────────
# One-time probe of the best available H.264 encoder, preferring dedicated
# hardware blocks (Intel QuickSync, NVIDIA NVENC, Windows Media Foundation)
# over software x264. Result cached for the process lifetime.
_HW_ENCODER_CACHE = None
_HW_ENCODER_LOCK = threading.Lock()

_HW_CANDIDATES = [
    # (encoder name, extra output opts, is_hardware)
    ("h264_qsv",   ["-preset", "medium", "-global_quality", "23"], True),
    ("h264_nvenc", ["-preset", "p4", "-rc", "vbr", "-cq", "24", "-b:v", "0"], True),
    ("h264_mf",    [], True),
]


def _ffmpeg_bin():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "ffmpeg", "bin", "ffmpeg.exe")


def _encoder_selftest(encoder, extra_opts):
    """Quick null-render encode to confirm the encoder actually works
    (a listed encoder may still lack a usable GPU/driver)."""
    ff = _ffmpeg_bin()
    if not os.path.exists(ff):
        return False
    try:
        cmd = [
            ff, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2",
            "-c:v", encoder, *extra_opts,
            "-f", "null", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=15,
                             creationflags=CREATE_NO_WINDOW)
        return res.returncode == 0
    except Exception:
        return False


def describe_hw_encoder(force=False):
    """
    Returns {"available": bool, "encoder": str|None, "hardware": bool}.
    Preference order: Intel QSV → NVIDIA NVENC → MediaFoundation → libx264.
    """
    global _HW_ENCODER_CACHE
    with _HW_ENCODER_LOCK:
        if _HW_ENCODER_CACHE is not None and not force:
            return _HW_ENCODER_CACHE

        ff = _ffmpeg_bin()
        result = {"available": False, "encoder": None, "hardware": False}

        if os.path.exists(ff):
            try:
                res = subprocess.run(
                    [ff, "-hide_banner", "-encoders"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
                encoders_text = res.stdout or ""
                for name, extra, is_hw in _HW_CANDIDATES:
                    if name not in encoders_text:
                        continue
                    if is_hw and not _encoder_selftest(name, extra):
                        continue
                    result = {"available": True, "encoder": name, "hardware": is_hw}
                    break
                else:
                    # Software fallback always available in full ffmpeg builds
                    if "libx264" in encoders_text:
                        result = {"available": True, "encoder": "libx264", "hardware": False}
            except Exception as e:
                print(f"[Streamer] Encoder probe failed: {e}")

        _HW_ENCODER_CACHE = result
        return result


def stream_video_convert(file_path, audio_track_index, start_time=0.0, max_height=0):
    """
    Full real-time conversion of the video to widely-supported H.264/AAC MP4,
    using hardware acceleration when available (QSV/NVENC/MF). Intended for
    codecs the browser struggles with (e.g. 4K 10-bit HEVC) so playback stays
    smooth without pegging the CPU.
    """
    if not os.path.isfile(file_path):
        abort(404, description=f"File not found: {file_path}")

    caps = describe_hw_encoder()
    if not caps.get("available"):
        abort(503, description="No usable video encoder found")

    from backend.audio_probe import probe_audio_tracks
    tracks = probe_audio_tracks(file_path)
    if audio_track_index < 0 or audio_track_index >= len(tracks):
        audio_track_index = 0

    ff = _ffmpeg_bin()

    # Keyframe-align the cut point so A/V start together (see find_keyframe_before)
    effective_start = find_keyframe_before(file_path, float(start_time or 0))

    cmd = [ff, "-hide_banner", "-loglevel", "error"]
    if effective_start > 0:
        cmd.extend(["-ss", f"{effective_start:.3f}"])
    # Cap input analysis on huge MKVs — big TTFB win on 4K files
    cmd.extend(["-probesize", "5M", "-analyzeduration", "5M"])
    cmd.extend(["-i", file_path])
    cmd.extend([
        "-map", "0:v:0",
        "-map", f"0:a:{audio_track_index}",
    ])

    encoder = caps["encoder"]
    extra = next((o for n, o, _ in _HW_CANDIDATES if n == encoder), [])
    cmd.extend(["-c:v", encoder, *extra])

    # Downscale only when actually needed (probed height is cached)
    if max_height and max_height > 0:
        try:
            from backend.video_probe import probe_video_resolution
            src_h = probe_video_resolution(file_path).get("height") or 0
        except Exception:
            src_h = 0
        if src_h > max_height:
            cmd.extend(["-vf", f"scale=-2:{int(max_height)}"])

    cmd.extend([
        "-c:a", "aac",
        "-ac", "2",
        "-b:a", "192k",
        "-af", "aresample=async=1",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    ])

    key = ("convert", os.path.abspath(file_path))
    with _TRANSCODE_LOCK:
        old = _ACTIVE_TRANSCODES.pop(key, None)
    if old is not None and old.poll() is None:
        try:
            old.kill()
        except Exception:
            pass

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

        def generate():
            try:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass

        return Response(generate(), mimetype="video/mp4", headers={
            "Cache-Control": "no-cache",
            "Accept-Ranges": "none",
            "X-Content-Start": f"{effective_start:.3f}",
        })
    except Exception:
        return stream_file(file_path)


def stream_audio_only(file_path, track_index, start_time=0.0):
    """
    Stream ONLY the selected audio track as AAC (ADTS) over HTTP.

    This powers the dual-element player design: the <video> element keeps
    playing the original file natively (muted), while the chosen audio track
    is served here and played by a hidden <audio> element kept in sync with
    the video. Video therefore never leaves its native path and can never
    drift, stall, or desync due to transcoding.
    """
    if not os.path.isfile(file_path):
        abort(404, description=f"File not found: {file_path}")

    from backend.audio_probe import probe_audio_tracks
    available = probe_audio_tracks(file_path)
    if track_index < 0 or track_index >= len(available):
        abort(404, description="Audio track out of range")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ffmpeg_bin = os.path.join(base_dir, "ffmpeg", "bin", "ffmpeg.exe")
    if not os.path.exists(ffmpeg_bin):
        abort(404, description="FFmpeg not available")

    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error"]
    if start_time and float(start_time) > 0:
        cmd.extend(["-ss", f"{float(start_time):.3f}"])
    cmd.extend([
        "-i", file_path,
        "-map", f"0:a:{track_index}",
        "-c:a", "aac",
        "-ac", "2",
        "-b:a", "192k",
        "-f", "adts",
        "pipe:1"
    ])

    key = ("audio", os.path.abspath(file_path))
    with _TRANSCODE_LOCK:
        old = _ACTIVE_AUDIO_STREAMS.pop(key, None)
    if old is not None and old.poll() is None:
        try:
            old.kill()
        except Exception:
            pass

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        with _TRANSCODE_LOCK:
            _ACTIVE_AUDIO_STREAMS[key] = proc

        def generate():
            try:
                while True:
                    chunk = proc.stdout.read(32768)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                with _TRANSCODE_LOCK:
                    if _ACTIVE_AUDIO_STREAMS.get(key) is proc:
                        _ACTIVE_AUDIO_STREAMS.pop(key, None)

        return Response(generate(), mimetype="audio/aac", headers={
            "Cache-Control": "no-cache",
            "Accept-Ranges": "none",
        })
    except Exception:
        abort(500, description="Failed to start audio stream")


def stream_transcoded(file_path, audio_track_index=0, start_time=0.0):
    """
    Remuxes/streams video via FFmpeg with specific audio track index.
    '-c:v copy' preserves original video frames without CPU load.
    '-map 0:a:{audio_track_index}' selects the target audio track.

    A/V sync notes:
      - Input '-ss' seeks the demuxer once, so ALL streams keep their original
        relative offsets (uniform timestamp shift) -> audio stays in sync.
      - '-copyts'/'-start_at_zero' were removed deliberately: they shift only
        ONE stream's first timestamp to zero while video (keyframe) and audio
        (frame boundary) land at different points, producing a permanent
        audio offset.
      - 'aresample=async=1' corrects slow clock drift over long transcodes
        without forcing stream start times.
    """
    if not os.path.isfile(file_path):
        abort(404, description=f"File not found: {file_path}")

    # Validate the requested audio track — an out-of-range index with the
    # optional '?'' map specifier would silently produce a VIDEO-ONLY stream.
    from backend.audio_probe import probe_audio_tracks
    available = probe_audio_tracks(file_path)
    if audio_track_index < 0 or audio_track_index >= len(available):
        return stream_file(file_path)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ffmpeg_bin = os.path.join(base_dir, "ffmpeg", "bin", "ffmpeg.exe")

    if not os.path.exists(ffmpeg_bin):
        return stream_file(file_path)

    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error"]

    # Align the seek to the actual video keyframe so audio and video start
    # at the same instant (see find_keyframe_before).
    effective_start = 0.0
    if start_time and float(start_time) > 0:
        effective_start = find_keyframe_before(file_path, float(start_time))
        cmd.extend(["-ss", f"{effective_start:.3f}"])

    cmd.extend([
        "-i", file_path,
        "-map", "0:v:0",
        "-map", f"0:a:{audio_track_index}",
        "-c:v", "copy",
        "-c:a", "aac",
        "-ac", "2",
        "-b:a", "192k",
        "-af", "aresample=async=1",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1"
    ])

    key = os.path.abspath(file_path)

    # A new transcode for this file replaces any previous one — the old
    # browser connection is dead anyway once the <video> src changes.
    with _TRANSCODE_LOCK:
        old = _ACTIVE_TRANSCODES.pop(key, None)
    if old is not None and old.poll() is None:
        try:
            old.kill()
        except Exception:
            pass

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        with _TRANSCODE_LOCK:
            _ACTIVE_TRANSCODES[key] = proc

        def generate():
            try:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                with _TRANSCODE_LOCK:
                    if _ACTIVE_TRANSCODES.get(key) is proc:
                        _ACTIVE_TRANSCODES.pop(key, None)

        return Response(generate(), mimetype="video/mp4", headers={
            "Cache-Control": "no-cache",
            "Accept-Ranges": "none",
            "X-Content-Start": f"{effective_start:.3f}",
        })
    except Exception as e:
        return stream_file(file_path)
