# -*- coding: utf-8 -*-
"""
routes/streaming.py — Video streaming, subtitles, thumbnails, skip-times, audio tracks.
All streaming endpoints are unlimited (no rate limiting).
"""
import os
import threading

from flask import Blueprint, jsonify, request, send_file, abort, current_app, Response

from .middleware import kids_guard_media, current_profile
from backend.db import get_best_media_source, get_media_by_id, get_media_quality_options
from backend.streamer import stream_file

streaming_bp = Blueprint("streaming", __name__)


def _media_duration_seconds(file_path):
    """Best-effort stream duration via ffprobe (0 if unavailable)."""
    import subprocess, json as _json
    from backend.utils.paths import FFPROBE_BIN
    if not file_path or not os.path.isfile(FFPROBE_BIN):
        return 0.0
    try:
        from backend.proc_utils import CREATE_NO_WINDOW
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        info = _json.loads(out.stdout)
        return round(float(info.get("format", {}).get("duration") or 0), 3)
    except Exception:
        return 0.0


@streaming_bp.route("/api/skip-times/<int:media_id>")
def api_skip_times(media_id):
    from backend.skip_times import fetch_skip_times, SKIP_CACHE_DIR
    if request.args.get("refresh") in ("1", "true"):
        cache_path = os.path.join(SKIP_CACHE_DIR, f"{media_id}.json")
        try:
            if os.path.isfile(cache_path):
                os.remove(cache_path)
        except Exception:
            pass
    skip_data = fetch_skip_times(media_id)
    return jsonify(skip_data)


@streaming_bp.route("/api/quality-options/<int:media_id>")
def api_quality_options(media_id):
    options = get_media_quality_options(media_id)
    return jsonify(options)


@streaming_bp.route("/api/audio-tracks/<int:media_id>")
def api_audio_tracks(media_id):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)
    from backend.audio_probe import probe_audio_tracks
    tracks = probe_audio_tracks(media["file_path"])
    return jsonify(tracks)


@streaming_bp.route("/api/stream/<int:media_id>")
def api_stream(media_id):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)

    guard = kids_guard_media(media, deep=True)
    if guard:
        return guard

    if request.args.get("audio_only") in ("1", "true"):
        audio_track = request.args.get("audio_track", "")
        at = request.args.get("at", type=float, default=0.0)
        if not audio_track.isdigit():
            abort(400, description="audio_track required for audio-only mode")
        from backend.streamer import stream_audio_only
        return stream_audio_only(media["file_path"], int(audio_track), start_time=at)

    if request.args.get("transcode") in ("1", "true"):
        audio_track = request.args.get("audio_track", "")
        track_idx = int(audio_track) if audio_track.isdigit() else 0
        start_time = request.args.get("start", type=float, default=0.0)
        max_height = request.args.get("max_height", type=int, default=1080)
        from backend.streamer import stream_video_convert
        return stream_video_convert(
            media["file_path"], audio_track_index=track_idx,
            start_time=start_time, max_height=max_height,
        )

    audio_track = request.args.get("audio_track")
    start_time = request.args.get("start", type=float, default=0.0)

    if audio_track is not None and audio_track != "" and str(audio_track).isdigit():
        track_idx = int(audio_track)
        from backend.streamer import stream_transcoded
        return stream_transcoded(media["file_path"], audio_track_index=track_idx, start_time=start_time)

    return stream_file(media["file_path"])


@streaming_bp.route("/api/system/health-status")
def api_system_health_status():
    """
    Lightweight health check for host RAM pressure and server responsiveness.
    """
    ram_load = 0
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong)
            ]
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                ram_load = int(ms.dwMemoryLoad)
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "ram_load_pct": ram_load,
        "is_low_memory": ram_load >= 88,
    })



# ─── On-Demand Adaptive HLS Streaming ────────────────────────────────────────

@streaming_bp.route("/api/hls/<int:media_id>/master.m3u8")
def api_hls_master(media_id):
    media = get_best_media_source(media_id)
    if not media or not media.get("file_path"):
        abort(404)
    guard = kids_guard_media(media, deep=True)
    if guard:
        return guard
    audio_track = request.args.get("audio_track", 0, type=int)
    from backend.hls_transcoder import generate_master_playlist
    playlist = generate_master_playlist(media_id, media["file_path"], audio_track_index=audio_track)
    return Response(playlist, mimetype="application/vnd.apple.mpegurl", headers={
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    })


@streaming_bp.route("/api/hls/<int:media_id>/stream_<quality>.m3u8")
def api_hls_variant(media_id, quality):
    media = get_best_media_source(media_id)
    if not media or not media.get("file_path"):
        abort(404)
    guard = kids_guard_media(media, deep=True)
    if guard:
        return guard
    audio_track = request.args.get("audio_track", 0, type=int)
    duration = float(media.get("duration") or 0)
    if duration <= 0:
        duration = _media_duration_seconds(media["file_path"])
    from backend.hls_transcoder import generate_variant_playlist
    playlist = generate_variant_playlist(media_id, media["file_path"], quality, duration, audio_track_index=audio_track)
    return Response(playlist, mimetype="application/vnd.apple.mpegurl", headers={
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    })


@streaming_bp.route("/api/hls/<int:media_id>/seg_<quality>_<seg_name>.ts")
def api_hls_segment(media_id, quality, seg_name):
    media = get_best_media_source(media_id)
    if not media or not media.get("file_path"):
        abort(404)
    guard = kids_guard_media(media, deep=True)
    if guard:
        return guard
    audio_track = request.args.get("audio_track", 0, type=int)
    try:
        # seg_name might be "00000" or "0"
        seg_index = int(seg_name)
    except ValueError:
        abort(400)
    duration = float(media.get("duration") or 0)
    from backend.hls_transcoder import get_or_generate_segment
    seg_path = get_or_generate_segment(media_id, media["file_path"], quality, seg_index, audio_track_index=audio_track, duration=duration)
    if not seg_path or not os.path.isfile(seg_path):
        abort(404)
    return send_file(seg_path, mimetype="video/MP2T")


@streaming_bp.route("/api/hls/<int:media_id>/cleanup", methods=["GET", "POST"])
def api_hls_cleanup(media_id):
    from backend.hls_transcoder import cleanup_hls_session
    cleanup_hls_session(media_id)
    return jsonify({"ok": True})


@streaming_bp.route("/api/transcode-caps", methods=["GET"])
def api_transcode_caps():
    from backend.streamer import describe_hw_encoder
    return jsonify(describe_hw_encoder())


@streaming_bp.route("/api/stream-start/<int:media_id>")
def api_stream_start(media_id):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)
    guard = kids_guard_media(media, deep=True)
    if guard:
        return guard
    start_time = request.args.get("start", type=float, default=0.0)
    from backend.streamer import find_keyframe_before
    aligned = find_keyframe_before(media["file_path"], start_time)
    return jsonify({"requested": start_time, "start": aligned})


@streaming_bp.route("/api/subtitles/<int:media_id>/embedded/<int:stream_index>.vtt")
def api_embedded_subtitles(media_id, stream_index):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)
    from backend.subtitles import extract_embedded_vtt
    vtt_path = extract_embedded_vtt(media["file_path"], stream_index, media_id)
    if not vtt_path or not os.path.exists(vtt_path):
        abort(404)
    return send_file(vtt_path, mimetype="text/vtt")


@streaming_bp.route("/api/media/<int:media_id>/download-subtitles", methods=["POST"])
def api_download_subtitles(media_id):
    media = get_best_media_source(media_id)
    if not media or not media.get("file_path"):
        return jsonify({"added": 0, "message": "Media not found"}), 404

    from backend.settings import load_config
    cfg = load_config()
    sub_cfg = cfg.get("subtitles") or {}
    api_key = (sub_cfg.get("opensubtitles_api_key") or "").strip()
    if not api_key:
        return jsonify({
            "added": 0,
            "message": "No OpenSubtitles API key configured — add one in Settings → Player & Subtitle Defaults.",
        }), 400

    pref = (sub_cfg.get("preferred_language") or "en").lower()
    lang_map = {"auto": "en", "english": "en", "spanish": "es", "french": "fr", "japanese": "ja", "german": "de"}
    languages = lang_map.get(pref, pref if len(pref) <= 3 else "en")

    from backend.opensubs import download_subtitles_for_file
    try:
        saved = download_subtitles_for_file(media["file_path"], api_key, languages)
    except Exception as e:
        return jsonify({"added": 0, "message": f"OpenSubtitles request failed: {e}"}), 502

    if not saved:
        return jsonify({"added": 0, "message": "No subtitles found for this file (or already downloaded)."})
    return jsonify({
        "added": len(saved),
        "message": f"Downloaded {len(saved)} subtitle file(s)",
        "files": [os.path.basename(p) for p in saved],
    })


@streaming_bp.route("/api/subtitles/<int:media_id>/<path:filename>")
def api_subtitles(media_id, filename):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)
    video_dir = os.path.dirname(media["file_path"])
    sub_path = os.path.normpath(os.path.join(video_dir, filename))
    video_dir_norm = os.path.normpath(video_dir).lower()
    parent_dir_norm = os.path.normpath(os.path.dirname(video_dir)).lower()
    sub_path_norm = os.path.normpath(sub_path).lower()
    if not sub_path_norm.startswith(video_dir_norm) and not sub_path_norm.startswith(parent_dir_norm):
        abort(403)
    from backend.subtitles import get_vtt_path
    vtt_path = get_vtt_path(sub_path)
    if not vtt_path:
        abort(404)
    return send_file(vtt_path, mimetype="text/vtt")


@streaming_bp.route("/api/subtitles/online/search", methods=["GET"])
def api_search_online_subtitles():
    media_id = request.args.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id is required"}), 400
    media = get_media_by_id(int(media_id))
    if not media:
        return jsonify({"error": "Media not found"}), 404
    from backend.subtitles import search_online_subtitles
    results = search_online_subtitles(
        title=media.get("title") or media.get("original_title") or "",
        imdb_id=media.get("imdb_id"),
        season=media.get("season"),
        episode=media.get("episode")
    )
    return jsonify(results)


@streaming_bp.route("/api/subtitles/online/download", methods=["POST"])
def api_download_online_subtitle():
    data = request.json or {}
    slug = data.get("slug") or data.get("id")
    media_id = data.get("media_id")
    if not slug or not media_id:
        return jsonify({"error": "slug and media_id are required"}), 400
    from backend.subtitles import download_online_subtitle
    sub_meta = download_online_subtitle(slug, int(media_id))
    if not sub_meta:
        return jsonify({"error": "Failed to download subtitle"}), 500
    return jsonify(sub_meta)


@streaming_bp.route("/api/media/<int:media_id>/thumbnails", methods=["GET"])
def api_media_thumbnails(media_id):
    media = get_best_media_source(media_id)
    if not media or not media.get("file_path"):
        return jsonify({"error": "Not found"}), 404
    from backend import thumbs
    if thumbs.is_ready(media_id):
        return jsonify({**thumbs.get_info(media_id), "ready": True})
    duration = media.get("duration") or 0
    file_path = media["file_path"]
    if not duration:
        duration = _media_duration_seconds(file_path)
    if not duration or not os.path.isfile(file_path):
        return jsonify({"ready": False})

    def _gen():
        try:
            thumbs.generate_sheet(media_id, file_path, duration)
        except Exception as e:
            print(f"[Thumbs] Generation failed for media {media_id}: {e}")

    threading.Thread(target=_gen, daemon=True).start()
    return jsonify({"ready": False})


@streaming_bp.route("/api/media/<int:media_id>/thumbnails/sheet", methods=["GET"])
def api_media_thumbnail_sheet(media_id):
    from backend import thumbs
    if not thumbs.is_ready(media_id):
        abort(404)
    return send_file(thumbs._sheet(media_id), mimetype="image/jpeg")


@streaming_bp.route("/api/media/<int:media_id>/skip-timestamps", methods=["POST"])
def api_update_skip_timestamps(media_id):
    data = request.json or {}
    media = get_media_by_id(media_id)
    if not media:
        return jsonify({"error": "Media not found"}), 404

    try:
        duration = float(media.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0 and media.get("file_path"):
        duration = _media_duration_seconds(media["file_path"])

    MAX_MIN = {"recap": 5, "intro": 5, "outro": 15, "preview": 15}
    cleaned = {}
    errors = []

    for seg, max_min in MAX_MIN.items():
        s = data.get(f"{seg}_start")
        e = data.get(f"{seg}_end")

        def _to_int(v):
            if v is None or v == "":
                return None
            try:
                return int(round(float(v)))
            except (TypeError, ValueError):
                return None

        s_i, e_i = _to_int(s), _to_int(e)
        if s_i is None and e_i is None:
            continue
        if s_i == 0 and e_i == 0:
            cleaned[f"{seg}_start"] = 0
            cleaned[f"{seg}_end"] = 0
            continue
        if s_i is None:
            errors.append(f"{seg}: start time is required")
            continue
        if s_i < 0:
            errors.append(f"{seg}: start cannot be negative")
            continue
        if seg == "outro" and (e_i is None or e_i == 0) and duration > 0:
            e_i = int(duration)
        if e_i is None:
            msg = f"{seg}: end time is required"
            if seg == "outro":
                msg += " (video duration could not be determined — is the file available?)"
            errors.append(msg)
            continue
        length = e_i - s_i
        if length <= 0:
            errors.append(f"{seg}: end must come after start")
            continue
        if length < 5:
            errors.append(f"{seg}: segments must be at least 5 seconds long")
            continue
        if length > max_min * 60:
            errors.append(f"{seg}: cannot exceed {max_min} minutes")
            continue
        if duration > 0 and abs(e_i - duration) <= 10:
            e_i = int(duration)
        if duration > 0 and e_i > duration + 1:
            errors.append(f"{seg}: end exceeds the video duration")
            continue
        cleaned[f"{seg}_start"] = s_i
        cleaned[f"{seg}_end"] = e_i

    if errors:
        return jsonify({"error": "; ".join(errors[:3])}), 400

    from backend.db import update_skip_timestamps
    ok = update_skip_timestamps(media_id, cleaned)
    if ok:
        return jsonify({"ok": True, "saved": cleaned})
    return jsonify({"error": "Failed to update skip timestamps"}), 400
