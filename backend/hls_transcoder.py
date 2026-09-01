# -*- coding: utf-8 -*-
"""
backend/hls_transcoder.py — Dynamic on-demand HLS transcoding and segment packaging.

Provides:
- Master & variant M3U8 playlist generation for adaptive bitrate streaming
- Fast GPU-accelerated / Smart Remux segment generation on demand
- Cache management with LRU eviction and session cleanup
"""

import os
import math
import time
import shutil
import threading
import subprocess
from typing import Dict, Any, Optional

from backend.proc_utils import CREATE_NO_WINDOW, BELOW_NORMAL_PRIORITY
from backend.utils.paths import BASE_DIR, FFMPEG_BIN, FFPROBE_BIN
from backend.streamer import describe_hw_encoder, find_keyframe_before
from backend.video_probe import probe_video_resolution
from backend.audio_probe import probe_audio_tracks

HLS_CACHE_DIR = os.path.join(BASE_DIR, "data", "metadata", "hls_cache")
SEGMENT_DURATION = 4.0  # 4 seconds per segment for fast seeking & adaptive switching
MAX_CACHE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB max cache size

# Segment generation lock per (media_id, quality, seg_index)
_GEN_LOCK = threading.Lock()
_ACTIVE_GENS: Dict[str, threading.Event] = {}

QUALITY_PRESETS = {
    "1080p": {
        "label": "1080p Full HD",
        "height": 1080,
        "video_bitrate": "4500k",
        "maxrate": "5500k",
        "bufsize": "9000k",
        "audio_bitrate": "192k",
        "bandwidth": 5000000,
    },
    "720p": {
        "label": "720p HD",
        "height": 720,
        "video_bitrate": "2400k",
        "maxrate": "3000k",
        "bufsize": "5000k",
        "audio_bitrate": "128k",
        "bandwidth": 2600000,
    },
    "480p": {
        "label": "480p SD",
        "height": 480,
        "video_bitrate": "1200k",
        "maxrate": "1500k",
        "bufsize": "2500k",
        "audio_bitrate": "96k",
        "bandwidth": 1300000,
    },
    "360p": {
        "label": "360p Low",
        "height": 360,
        "video_bitrate": "700k",
        "maxrate": "900k",
        "bufsize": "1500k",
        "audio_bitrate": "64k",
        "bandwidth": 800000,
    },
}


def _get_media_cache_dir(media_id: int) -> str:
    path = os.path.join(HLS_CACHE_DIR, str(media_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_available_qualities(file_path: str) -> list[str]:
    """Return available quality ladder options based on source video resolution."""
    res = probe_video_resolution(file_path)
    src_height = res.get("height") or 1080

    qualities = []
    for q_key, q_cfg in QUALITY_PRESETS.items():
        if src_height >= q_cfg["height"] - 40:  # Allow 1080p if source is ~1040p (aspect ratio crops)
            qualities.append(q_key)

    if not qualities:
        qualities.append("720p")
        qualities.append("480p")

    return qualities


def generate_master_playlist(media_id: int, file_path: str, audio_track_index: int = 0) -> str:
    """Generate HLS Master Playlist (m3u8) string linking variant quality playlists."""
    qualities = get_available_qualities(file_path)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
    ]

    for q in qualities:
        cfg = QUALITY_PRESETS.get(q)
        if not cfg:
            continue
        h = cfg["height"]
        w = int(round(h * 16 / 9))
        bw = cfg["bandwidth"]
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={w}x{h},NAME="{cfg["label"]}"')
        lines.append(f"/api/hls/{media_id}/stream_{q}.m3u8?audio_track={audio_track_index}")

    return "\n".join(lines) + "\n"


def generate_variant_playlist(media_id: int, file_path: str, quality: str, duration: float, audio_track_index: int = 0) -> str:
    """Generate HLS Variant Playlist (m3u8) containing list of segment files."""
    if duration <= 0:
        duration = 3600.0

    total_segments = int(math.ceil(duration / SEGMENT_DURATION))
    target_dur = int(math.ceil(SEGMENT_DURATION))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target_dur}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]

    for idx in range(total_segments):
        start_t = idx * SEGMENT_DURATION
        seg_len = min(SEGMENT_DURATION, duration - start_t)
        if seg_len <= 0:
            break
        lines.append(f"#EXTINF:{seg_len:.3f},")
        lines.append(f"/api/hls/{media_id}/seg_{quality}_{idx:05d}.ts?audio_track={audio_track_index}")

    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def get_or_generate_segment(
    media_id: int,
    file_path: str,
    quality: str,
    seg_index: int,
    audio_track_index: int = 0,
    duration: float = 0.0,
) -> Optional[str]:
    """
    Ensure the requested HLS segment (.ts) is rendered and cached.
    Returns the absolute path to the .ts file or None on failure.
    """
    if not os.path.isfile(file_path) or not os.path.exists(FFMPEG_BIN):
        return None

    media_dir = _get_media_cache_dir(media_id)
    quality_dir = os.path.join(media_dir, quality)
    os.makedirs(quality_dir, exist_ok=True)

    seg_file = os.path.join(quality_dir, f"seg_{seg_index:05d}.ts")

    # If already generated and valid, return it immediately
    if os.path.isfile(seg_file) and os.path.getsize(seg_file) > 1024:
        return seg_file

    gen_key = f"{media_id}_{quality}_{seg_index}_{audio_track_index}"
    with _GEN_LOCK:
        event = _ACTIVE_GENS.get(gen_key)
        if event is None:
            event = threading.Event()
            _ACTIVE_GENS[gen_key] = event
            is_creator = True
        else:
            is_creator = False

    if not is_creator:
        # Wait for creator thread to finish
        event.wait(timeout=30)
        if os.path.isfile(seg_file) and os.path.getsize(seg_file) > 1024:
            return seg_file
        return None

    try:
        cfg = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["720p"])
        start_t = seg_index * SEGMENT_DURATION

        # Hardware encoder detection
        caps = describe_hw_encoder()
        encoder = caps.get("encoder") or "libx264"

        # Check source specs
        res = probe_video_resolution(file_path)
        src_h = res.get("height") or 1080

        tracks = probe_audio_tracks(file_path)
        has_audio = len(tracks) > 0
        if has_audio and (audio_track_index < 0 or audio_track_index >= len(tracks)):
            audio_track_index = 0

        cmd = [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{start_t:.3f}",
            "-t", f"{SEGMENT_DURATION:.3f}",
            "-i", file_path,
            "-map", "0:V:0?",
        ]

        if has_audio:
            cmd.extend(["-map", f"0:a:{audio_track_index}?"])
        else:
            cmd.extend(["-an"])

        # Exclude subtitles from TS container
        cmd.extend(["-map", "-0:s?"])

        # Video filters
        vf_filters = []
        target_h = cfg["height"]
        if src_h > target_h:
            vf_filters.append(f"scale=-2:{target_h}:flags=fast_bilinear")

        pix_fmt = "nv12" if encoder == "h264_qsv" else "yuv420p"
        vf_filters.append(f"format={pix_fmt}")
        cmd.extend(["-vf", ",".join(vf_filters)])

        # Encoder options
        if encoder == "h264_nvenc":
            cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", cfg["video_bitrate"], "-maxrate", cfg["maxrate"], "-bufsize", cfg["bufsize"]])
        elif encoder == "h264_qsv":
            cmd.extend(["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", cfg["video_bitrate"], "-maxrate", cfg["maxrate"], "-bufsize", cfg["bufsize"]])
        elif encoder == "h264_mf":
            cmd.extend(["-c:v", "h264_mf", "-b:v", cfg["video_bitrate"]])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-b:v", cfg["video_bitrate"], "-maxrate", cfg["maxrate"], "-bufsize", cfg["bufsize"], "-tune", "zerolatency"])

        cmd.extend(["-pix_fmt", pix_fmt])

        if has_audio:
            cmd.extend([
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", cfg["audio_bitrate"],
                "-af", "aresample=async=1:first_pts=0",
            ])

        temp_file = f"{seg_file}.tmp_{int(time.time() * 1000)}"
        cmd.extend([
            "-f", "mpegts",
            "-muxdelay", "0",
            "-avoid_negative_ts", "make_zero",
            "-y",
            temp_file,
        ])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=40,
            creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY,
        )

        if os.path.isfile(temp_file) and os.path.getsize(temp_file) > 512:
            os.replace(temp_file, seg_file)
            return seg_file
        else:
            if os.path.isfile(temp_file):
                os.remove(temp_file)
            return None

    except Exception as e:
        print(f"[HLSTranscoder] Failed to generate segment {seg_index} ({quality}) for media {media_id}: {e}")
        return None
    finally:
        with _GEN_LOCK:
            _ACTIVE_GENS.pop(gen_key, None)
            event.set()


def cleanup_hls_session(media_id: int):
    """Clean up cached HLS segments for a specific media ID."""
    media_dir = os.path.join(HLS_CACHE_DIR, str(media_id))
    if os.path.isdir(media_dir):
        try:
            shutil.rmtree(media_dir, ignore_errors=True)
        except Exception as e:
            print(f"[HLSTranscoder] Cleanup error for media {media_id}: {e}")


def prune_hls_cache_if_needed():
    """Ensure total HLS cache directory size stays within MAX_CACHE_BYTES."""
    if not os.path.isdir(HLS_CACHE_DIR):
        return

    try:
        entries = []
        total_size = 0
        for root, dirs, files in os.walk(HLS_CACHE_DIR):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    sz = os.path.getsize(fp)
                    mtime = os.path.getmtime(fp)
                    total_size += sz
                    entries.append((mtime, sz, fp))
                except OSError:
                    pass

        if total_size > MAX_CACHE_BYTES:
            entries.sort(key=lambda x: x[0])  # Oldest first
            for _, sz, fp in entries:
                try:
                    os.remove(fp)
                    total_size -= sz
                except OSError:
                    pass
                if total_size < (MAX_CACHE_BYTES * 0.7):
                    break
    except Exception as e:
        print(f"[HLSTranscoder] Prune cache error: {e}")
