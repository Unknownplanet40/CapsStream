"""
app.py — CapsStream main Flask application.

Run with: python app.py
Or double-click start.bat
"""

import os
import re
import sys
import json
import shutil
import hashlib
import threading
import subprocess
from flask import (
    Flask, jsonify, request, send_file,
    send_from_directory, render_template, session, abort, Response
)

from backend.db import (
    init_db, get_all_media, get_media_by_id, get_media_by_tmdb, get_best_media_source, get_media_quality_options,
    search_media, get_unique_shows, get_recently_added, get_top_rated,
    get_by_genre, get_all_genres, get_random_pick,
    get_all_profiles, get_profile, create_profile, update_profile, delete_profile, verify_pin,
    get_progress, save_progress, delete_progress, get_continue_watching,
    get_favorites, toggle_favorite, is_favorite,
    get_collections, create_collection, delete_collection,
    add_to_collection, remove_from_collection,
    get_unmatched, upsert_media
)
from backend.streamer import stream_file
from backend.subtitles import find_subtitles, get_vtt_path
from backend.scanner import scan_library, get_scan_status
from backend.settings import load_config, save_config, test_api_key, apply_system_file_hiding
from backend.franchises import get_universe_collections
from backend.network_inspector import (
    init_network_inspector, get_recorded_requests, clear_recorded_requests
)
from backend.kids_filter import is_kid_safe, filter_kids

# Initialize outgoing HTTP interceptor
init_network_inspector()

# ─── App Setup ────────────────────────────────────────────────────────────────

import time
SERVER_START_TIME = time.time()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "capsstream_secret_key_fixed_v1"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB max upload (backup restore)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


def get_app_version():
    """Read the version from the VERSION file (fallback to 2.0.0.0)."""
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "2.0.0.0"
    except Exception:
        return "2.0.0.0"


def is_dev_mode():
    """Check if local DEV file exists with valid development flag."""
    try:
        dev_file = os.path.join(BASE_DIR, "DEV")
        if os.path.isfile(dev_file):
            with open(dev_file, "r", encoding="utf-8") as f:
                val = f.read().strip().lower()
                return val in ("development", "dev", "true", "1", "yes", "on")
    except Exception:
        pass
    return False


def load_config():
    # Delegate so .env / environment secrets are included
    from backend.settings import load_config as _load
    return _load()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def _current_profile():
    return session.get("profile_id")


def _require_profile():
    pid = _current_profile()
    if not pid:
        abort(401, description="No profile selected")
    return pid


def _active_is_kids():
    """True when the active session profile is a Kids profile."""
    pid = _current_profile()
    if not pid:
        return False
    try:
        prof = get_profile(pid)
        return bool(prof and prof.get("is_kids"))
    except Exception:
        return False


def _kids_guard_media(media, deep=True):
    """
    Hard gate for single-item endpoints (detail page / playback).
    Returns an error response when a Kids profile requests non-kid-safe
    media; None when the request may proceed.
    """
    if not _active_is_kids() or not media:
        return None
    safe, reason = is_kid_safe(media, deep=deep)
    if not safe:
        print(f"[KidsFilter] denied '{media.get('title')}' (tmdb {media.get('tmdb_id')}) — {reason}")
        return jsonify({"error": "Not available in Kids Mode", "reason": "kid_unsafe"}), 404
    return None


def _jsonify_rows(rows):
    return jsonify(rows)


_GITHUB_PROFILE_CACHE = {"data": None, "fetched_at": 0.0}

_API_HEALTH_CACHE = {"ts": 0.0, "data": None}
API_HEALTH_TTL_SEC = 120


def _probe_url(url, timeout=4):
    """Return (reachable, latency_ms). Any HTTP response counts as reachable."""
    import urllib.request
    import urllib.error
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CapsStream-Diagnostics"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)
        return True, int((time.monotonic() - start) * 1000)
    except urllib.error.HTTPError:
        # Server answered (4xx/5xx) — endpoint itself is reachable
        return True, int((time.monotonic() - start) * 1000)
    except Exception:
        return False, None


def _get_api_health(config):
    """
    Real reachability probes for external services, cached for 120s so the
    3s frontend poll never spams third-party APIs. Returns:
      { name: { status: ok|error|unconfigured|disabled, latency_ms } }
    """
    now = time.time()
    if _API_HEALTH_CACHE["data"] is not None and now - _API_HEALTH_CACHE["ts"] < API_HEALTH_TTL_SEC:
        return _API_HEALTH_CACHE["data"]

    health = {}

    tmdb_key = (config.get("tmdb_api_key") or "").strip()
    if tmdb_key:
        ok, ms = _probe_url(f"https://api.themoviedb.org/3/configuration?api_key={tmdb_key}")
        health["tmdb"] = {"status": "ok" if ok else "error", "latency_ms": ms}
    else:
        health["tmdb"] = {"status": "unconfigured", "latency_ms": None}

    ok, ms = _probe_url("https://api.aniskip.com/v2/skip-times/21/1?types=op&episodeLength=0")
    health["aniskip"] = {"status": "ok" if ok else "error", "latency_ms": ms}

    # Poster/metadata cache is fully local — healthy when its directory is usable
    try:
        os.makedirs(os.path.join(BASE_DIR, "data", "metadata"), exist_ok=True)
        health["poster_cache"] = {"status": "ok", "latency_ms": None}
    except Exception:
        health["poster_cache"] = {"status": "error", "latency_ms": None}

    _API_HEALTH_CACHE["data"] = health
    _API_HEALTH_CACHE["ts"] = now
    return health


def _get_github_profile():
    """Cached GitHub profile — refreshed at most once per hour, falls back to defaults offline."""
    import time as _time
    now = _time.time()
    if _GITHUB_PROFILE_CACHE["data"] and now - _GITHUB_PROFILE_CACHE["fetched_at"] < 3600:
        return _GITHUB_PROFILE_CACHE["data"]

    profile = {
        "login": "Unknownplanet40",
        "name": "<Caps />",
        "avatar_url": "https://avatars.githubusercontent.com/u/57881134?v=4",
        "html_url": "https://github.com/Unknownplanet40",
        "bio": "I debug life the same way I debug code with patience, caffeine, and a bit of panic.",
        "location": "Philippines",
        "public_repos": 20,
        "followers": 13,
        "following": 8,
        "created_year": "2019"
    }
    try:
        import urllib.request
        req = urllib.request.Request("https://api.github.com/users/Unknownplanet40", headers={"User-Agent": "CapsStream"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            gh_data = json.loads(resp.read().decode())
            if gh_data and "avatar_url" in gh_data:
                profile["name"] = gh_data.get("name") or gh_data.get("login") or "<Caps />"
                profile["login"] = gh_data.get("login") or "Unknownplanet40"
                profile["avatar_url"] = gh_data.get("avatar_url") or profile["avatar_url"]
                profile["html_url"] = gh_data.get("html_url") or profile["html_url"]
                profile["bio"] = gh_data.get("bio") or profile["bio"]
                profile["location"] = gh_data.get("location") or profile["location"]
                profile["public_repos"] = gh_data.get("public_repos", 20)
                profile["followers"] = gh_data.get("followers", 13)
                profile["following"] = gh_data.get("following", 8)
                created_raw = gh_data.get("created_at") or ""
                if len(created_raw) >= 4:
                    profile["created_year"] = created_raw[:4]
    except Exception:
        pass

    _GITHUB_PROFILE_CACHE["data"] = profile
    _GITHUB_PROFILE_CACHE["fetched_at"] = now
    return profile


# ─── Main Page ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", version=get_app_version(), t=int(time.time()))


@app.route("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_json():
    return jsonify({})


# ─── Static Media (images) ────────────────────────────────────────────────────

# Post-scan the UI can request hundreds of posters at once. Without limits,
# each miss held a Flask thread for up to 10s of TMDb download -> thread
# starvation froze every other API. Identical in-flight downloads are deduped,
# network fetches are capped, and total queued requests are capped.
_IMAGE_INFLIGHT_LOCK = threading.Lock()
_IMAGE_INFLIGHT = set()                               # filenames downloading now
_IMAGE_DOWNLOAD_SEM = threading.BoundedSemaphore(4)   # max parallel TMDb fetches
_IMAGE_WAITER_SEM = threading.BoundedSemaphore(16)    # max queued requests

@app.route("/metadata/images/<path:filename>")
def serve_metadata_image(filename):
    img_dir = os.path.join(BASE_DIR, "data", "metadata", "images")
    img_path = os.path.join(img_dir, filename)

    if not os.path.isfile(img_path):
        parts = filename.split("_", 1)
        if len(parts) == 2 and _IMAGE_WAITER_SEM.acquire(blocking=False):
            size, tmdb_file = parts[0], parts[1]
            is_owner = False
            try:
                # Collapse duplicate concurrent requests into one download
                while True:
                    with _IMAGE_INFLIGHT_LOCK:
                        if filename not in _IMAGE_INFLIGHT:
                            _IMAGE_INFLIGHT.add(filename)
                            is_owner = True
                            break
                    time.sleep(0.2)
                    if os.path.isfile(img_path):
                        break

                with _IMAGE_DOWNLOAD_SEM:
                    deadline = time.time() + 20
                    while not os.path.isfile(img_path) and time.time() < deadline:
                        if is_owner:
                            try:
                                url = f"https://image.tmdb.org/t/p/{size}/{tmdb_file}"
                                r = requests.get(url, timeout=10)
                                if r.status_code == 200:
                                    os.makedirs(img_dir, exist_ok=True)
                                    with open(img_path, "wb") as f:
                                        f.write(r.content)
                            except Exception as e:
                                print(f"[Image Server] On-demand download failed for {filename}: {e}")
                            break
                        time.sleep(0.25)
            finally:
                if is_owner:
                    with _IMAGE_INFLIGHT_LOCK:
                        _IMAGE_INFLIGHT.discard(filename)
                _IMAGE_WAITER_SEM.release()

        if os.path.isfile(img_path):
            resp = send_file(img_path, conditional=True)
            resp.headers["Cache-Control"] = "public, max-age=604800"
            return resp

        # Fallback inline SVG placeholder — no-store so a transient failure
        # (download queue full / TMDb down) is retried on the next view
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450">
          <rect width="300" height="450" fill="#181824"/>
          <text x="50%" y="48%" dominant-baseline="middle" text-anchor="middle" fill="#666" font-size="48">🎬</text>
          <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" fill="#888" font-family="sans-serif" font-size="14">No Poster Available</text>
        </svg>"""
        return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})

    resp = send_file(img_path, conditional=True)
    # Posters/backdrops rarely change — cache aggressively so large libraries
    # don't re-fetch thousands of images after a scan or page reload
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


# ─── Profiles API ─────────────────────────────────────────────────────────────

@app.route("/api/profiles", methods=["GET"])
def api_get_profiles():
    return jsonify(get_all_profiles())


@app.route("/api/profiles", methods=["POST"])
def api_create_profile():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    raw_pin = data.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""
    avatar = data.get("avatar", "🎬")
    color  = data.get("color", "#e50914")
    theme  = str(data.get("theme", "crimson") or "crimson").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if pin and len(pin) != 4:
        return jsonify({"error": "PIN must be exactly 4 digits"}), 400

    is_kids = bool(data.get("is_kids", False))
    daily_limit_minutes = int(data.get("daily_limit_minutes", 0) or 0)
    bedtime_curfew = str(data.get("bedtime_curfew", "") or "").strip()
    pin_hash = _hash_pin(pin) if pin else None
    pid = create_profile(name, pin_hash, avatar, color, is_kids=is_kids, daily_limit_minutes=daily_limit_minutes, bedtime_curfew=bedtime_curfew, theme=theme)
    if is_kids:
        active_pid = _current_profile()
        if active_pid:
            from backend.db import unlock_achievement
            unlock_achievement(active_pid, "kids_creator")
    return jsonify({
        "id": pid, "name": name, "avatar": avatar, "color": color, "theme": theme, "is_kids": is_kids,
        "daily_limit_minutes": daily_limit_minutes, "bedtime_curfew": bedtime_curfew
    }), 201


@app.route("/api/profiles/<int:profile_id>", methods=["PUT"])
def api_update_profile(profile_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    raw_pin = data.get("pin")
    is_kids = bool(data.get("is_kids", False))
    avatar = data.get("avatar", "🎬")
    color  = data.get("color", "#e50914")
    theme  = str(data.get("theme", "crimson") or "crimson").strip()
    update_pin = bool(data.get("update_pin", False))

    if not name:
        return jsonify({"error": "Name is required"}), 400

    if is_kids:
        pin_hash = None
        update_pin = True
    else:
        if update_pin:
            pin = str(raw_pin).strip() if raw_pin is not None else ""
            if pin and len(pin) != 4:
                return jsonify({"error": "PIN must be exactly 4 digits"}), 400
            pin_hash = _hash_pin(pin) if pin else None
        else:
            pin_hash = None

    daily_limit_minutes = int(data.get("daily_limit_minutes", 0) or 0)
    bedtime_curfew = str(data.get("bedtime_curfew", "") or "").strip()
    update_profile(profile_id, name, pin_hash, avatar, color, is_kids, update_pin=update_pin, daily_limit_minutes=daily_limit_minutes, bedtime_curfew=bedtime_curfew, theme=theme)

    return jsonify({
        "id": profile_id,
        "name": name,
        "avatar": avatar,
        "color": color,
        "theme": theme,
        "is_kids": is_kids,
        "has_pin": bool(pin_hash),
        "daily_limit_minutes": daily_limit_minutes,
        "bedtime_curfew": bedtime_curfew
    })


@app.route("/api/profiles/<int:profile_id>", methods=["DELETE", "POST"])
def api_delete_profile(profile_id):
    # 1. Kids profile lockout check
    active_pid = _current_profile()
    if active_pid:
        active_prof = get_profile(active_pid)
        if active_prof and active_prof.get("is_kids"):
            return jsonify({"error": "Kids profiles cannot delete profiles"}), 403

    # 2. Last profile guard
    all_profiles = get_all_profiles()
    if len(all_profiles) <= 1:
        return jsonify({"error": "Cannot delete the only profile"}), 400

    target = get_profile(profile_id)
    if not target:
        return jsonify({"error": "Profile not found"}), 404

    # 3. PIN verification for profiles with PIN
    data = request.json if (request.data and request.is_json) else {}
    raw_pin = data.get("pin") if data else request.args.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""
    pin_hash = _hash_pin(pin) if pin else None

    if target.get("pin_hash") and target.get("pin_hash") != "":
        if not verify_pin(profile_id, pin_hash):
            return jsonify({"error": "Incorrect PIN"}), 401

    delete_profile(profile_id)
    if session.get("profile_id") == profile_id:
        session.pop("profile_id", None)
    return jsonify({"ok": True})


@app.route("/api/profiles/auth", methods=["POST"])
def api_auth_profile():
    data = request.json or {}
    profile_id = data.get("profile_id")
    raw_pin = data.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""

    if not profile_id:
        return jsonify({"error": "profile_id required"}), 400

    profile = get_profile(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    pin_hash = _hash_pin(pin) if pin else ""
    if not verify_pin(profile_id, pin_hash if pin else None):
        return jsonify({"error": "Incorrect PIN"}), 401

    session["profile_id"] = profile_id
    return jsonify({"ok": True, "profile": {
        "id":      profile["id"],
        "name":    profile["name"],
        "avatar":  profile["avatar"],
        "color":   profile["color"],
        "is_kids": bool(profile.get("is_kids", 0)),
        "daily_limit_minutes": int(profile.get("daily_limit_minutes", 0) or 0),
        "bedtime_curfew": str(profile.get("bedtime_curfew", "") or ""),
    }})


@app.route("/api/profiles/me", methods=["GET"])
def api_me():
    pid = _current_profile()
    if not pid:
        return jsonify(None)
    profile = get_profile(pid)
    if not profile:
        session.pop("profile_id", None)
        return jsonify(None)
    return jsonify({
        "id":      profile["id"],
        "name":    profile["name"],
        "avatar":  profile["avatar"],
        "color":   profile["color"],
        "is_kids": bool(profile.get("is_kids", 0)),
        "daily_limit_minutes": int(profile.get("daily_limit_minutes", 0) or 0),
        "bedtime_curfew": str(profile.get("bedtime_curfew", "") or ""),
    })


@app.route("/api/profiles/logout", methods=["POST"])
def api_logout():
    session.pop("profile_id", None)
    return jsonify({"ok": True})


# ─── Settings API ─────────────────────────────────────────────────────────────

from backend.settings import load_config, save_config, test_api_key

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(load_config())


@app.route("/api/settings", methods=["POST"])
def api_post_settings():
    data = request.json or {}
    ok, result = save_config(data)
    if ok:
        # Changing the auto-scan interval restarts the countdown from now
        if "library" in data and "scan_interval_hours" in (data.get("library") or {}):
            _write_last_scheduled_scan(time.time())
        return jsonify({"ok": True, "config": result})
    return jsonify({"error": result}), 500


@app.route("/api/settings/test-api", methods=["POST"])
def api_test_api_key():
    data = request.json or {}
    provider = data.get("provider", "")
    key = data.get("key", "")
    ok, message = test_api_key(provider, key)
    return jsonify({"ok": ok, "message": message})


@app.route("/api/system/cache", methods=["GET"])
def api_cache_info():
    from backend.settings import get_cache_info
    return jsonify(get_cache_info())


@app.route("/api/system/cache", methods=["DELETE"])
def api_clear_cache():
    from backend.settings import clear_cache
    cleared = clear_cache()
    return jsonify({"ok": True, "cleared": cleared})


@app.route("/api/system/reset", methods=["POST"])
def api_system_reset():
    data = request.json or {}
    clear_media = data.get("clear_media_files", False)
    from backend.settings import reset_application
    reset_application(clear_media_files=clear_media)
    session.clear()
    return jsonify({"ok": True, "message": "Application reset complete"})


# ─── Library / Home API ───────────────────────────────────────────────────────

@app.route("/api/home", methods=["GET"])
def api_home():
    pid = _current_profile()
    kids = _active_is_kids()
    rows = []

    # Continue Watching (profile-specific)
    if pid:
        cw = get_continue_watching(pid, limit=15)
        if cw:
            rows.append({"title": "Continue Watching", "type": "continue", "items": cw})

    # Recently Added
    recent = get_recently_added(limit=20)
    if recent:
        rows.append({"title": "Recently Added", "type": "row", "items": recent})

    # Top Rated
    top = get_top_rated(limit=20)
    if top:
        rows.append({"title": "Top Rated", "type": "row", "items": top})

    # Movies
    movies = get_top_rated(limit=20, media_type="movie")
    if not movies:
        movies = get_unique_shows("movie")[:20]
    if movies:
        rows.append({"title": "Movies", "type": "row", "items": movies})

    # Series
    series = get_unique_shows("series")
    if series:
        rows.append({"title": "Series", "type": "row", "items": series[:20]})

    # Anime
    anime = get_unique_shows("anime")
    if anime:
        rows.append({"title": "Anime", "type": "row", "items": anime[:20]})

    # Random Pick
    random_picks = get_random_pick(limit=10)
    if random_picks:
        rows.append({"title": "Discover Something New", "type": "row", "items": random_picks})

    # Genre rows
    genres = get_all_genres()
    priority_genres = ["Action", "Comedy", "Drama", "Horror", "Sci-Fi", "Science Fiction",
                       "Romance", "Thriller", "Animation", "Documentary", "Fantasy"]
    shown_genres = [g for g in priority_genres if g in genres]
    if not shown_genres:
        shown_genres = genres[:5]

    for genre in shown_genres[:4]:  # Max 4 genre rows
        items = get_by_genre(genre, limit=15)
        if items:
            rows.append({"title": genre, "type": "row", "items": items})

    if kids:
        filtered_rows = []
        for row in rows:
            items = filter_kids(row.get("items"))
            if items:
                filtered_rows.append({**row, "items": items})
        rows = filtered_rows

    return jsonify(rows)


@app.route("/api/library", methods=["GET"])
def api_library():
    media_type = request.args.get("type")
    rows = get_unique_shows(media_type if media_type else None)
    if _active_is_kids():
        rows = filter_kids(rows)
    return _jsonify_rows(rows)


# ─── Anime Detection (Series → Anime reclassification) ────────────────────────

_ANIME_DETECT = {
    "running": False, "done": False, "total": 0,
    "processed": 0, "reclassified": 0, "error": None,
}


def _is_anime_detail(detail):
    """Strict anime test: Animation genre AND Japanese origin/language."""
    if not detail:
        return False
    genres = ", ".join(g.get("name", "") for g in detail.get("genres", []))
    origin = detail.get("origin_country") or []
    return "Animation" in genres and (
        detail.get("original_language") == "ja" or "JP" in origin
    )


def _detect_anime_job():
    """Re-type Japanese-animation shows from 'series' to 'anime'.

    Iterates distinct series tmdb_ids (never individual episode rows) and
    re-types each show atomically so season/episode queries never split.
    """
    from backend.db import get_conn
    from backend.matcher import _tmdb_get
    try:
        conn = get_conn()
        shows = conn.execute(
            "SELECT tmdb_id, MIN(title) AS title FROM media "
            "WHERE type='series' AND tmdb_id IS NOT NULL GROUP BY tmdb_id"
        ).fetchall()
        conn.close()
        _ANIME_DETECT["total"] = len(shows)
        reclassified = 0

        for idx, row in enumerate(shows):
            tmdb_id, title = row[0], row[1]
            try:
                detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US"})
                if detail and _is_anime_detail(detail):
                    conn = get_conn()
                    cur = conn.execute(
                        "UPDATE media SET type='anime' WHERE tmdb_id=? AND type='series'",
                        (tmdb_id,),
                    )
                    conn.commit()
                    conn.close()
                    if cur.rowcount:
                        reclassified += 1
                        print(f"[AnimeDetect] '{title}' → anime ({cur.rowcount} episode rows re-typed)")
            except Exception as e:
                print(f"[AnimeDetect] Error for tmdb_id {tmdb_id}: {e}")
            finally:
                _ANIME_DETECT["processed"] = idx + 1

        _ANIME_DETECT["reclassified"] = reclassified
        print(f"[AnimeDetect] Done — {reclassified} show(s) moved to Anime")
    except Exception as e:
        _ANIME_DETECT["error"] = str(e)
        print(f"[AnimeDetect] Job failed: {e}")
    finally:
        _ANIME_DETECT["running"] = False
        _ANIME_DETECT["done"] = True


@app.route("/api/library/detect-anime", methods=["POST"])
def api_detect_anime_start():
    if _ANIME_DETECT["running"]:
        return jsonify({"started": False, "message": "Detection is already running"})
    _ANIME_DETECT.update({
        "running": True, "done": False, "total": 0,
        "processed": 0, "reclassified": 0, "error": None,
    })
    threading.Thread(target=_detect_anime_job, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/library/detect-anime/status", methods=["GET"])
def api_detect_anime_status():
    return jsonify(dict(_ANIME_DETECT))


@app.route("/api/media/<int:media_id>", methods=["GET"])
def api_media_detail(media_id):
    media = get_best_media_source(media_id)
    if not media:
        return jsonify({"error": "Not found"}), 404

    guard = _kids_guard_media(media, deep=True)
    if guard:
        return guard

    if not media.get("logo_path"):
        from backend.matcher import ensure_media_logo
        ensure_media_logo(media)

    if media.get("tmdb_id") and not media.get("imdb_id"):
        from backend.matcher import fetch_imdb_id
        imdb_id = fetch_imdb_id(media["tmdb_id"], media.get("type", "movie"))
        if imdb_id:
            media["imdb_id"] = imdb_id
            try:
                from backend.db import get_conn
                conn = get_conn()
                conn.execute("UPDATE media SET imdb_id=? WHERE tmdb_id=?", (imdb_id, media["tmdb_id"]))
                conn.commit()
                conn.close()
            except Exception:
                pass

    if media.get("tmdb_id"):
        from backend.matcher import fetch_media_backdrops
        backdrops = fetch_media_backdrops(media["tmdb_id"], media.get("type", "movie"))
        if media.get("backdrop_path") and media["backdrop_path"] not in backdrops:
            backdrops = [media["backdrop_path"]] + backdrops
        media["backdrops"] = backdrops or ([media["backdrop_path"]] if media.get("backdrop_path") else [])
    else:
        media["backdrops"] = [media["backdrop_path"]] if media.get("backdrop_path") else []

    pid = _current_profile()
    if pid:
        progress = get_progress(pid, media_id)
        media["progress"] = dict(progress) if progress else None
        media["is_favorite"] = is_favorite(pid, media_id)
    else:
        media["progress"] = None
        media["is_favorite"] = False

    # For series/anime, also return all episodes grouped by season
    if media["type"] in ("series", "anime") and media.get("tmdb_id"):
        all_eps = get_media_by_tmdb(media["tmdb_id"], media["type"])
        from backend.matcher import fetch_season_episodes

        local_map = {}
        for ep_row in all_eps:
            ep = dict(ep_row)
            try:
                s_int = int(ep.get("season") or 1)
            except Exception:
                s_int = 1
            try:
                ep_int = int(ep.get("episode") or 1)
            except Exception:
                ep_int = 1
            local_map[(s_int, ep_int)] = ep

        from backend.matcher import fetch_season_episodes, get_show_seasons_list

        seasons = {}
        s_nums_set = set(k[0] for k in local_map.keys())
        tmdb_seasons = get_show_seasons_list(media["tmdb_id"], media["type"])
        if tmdb_seasons:
            for ts in tmdb_seasons:
                if ts > 0:
                    s_nums_set.add(ts)

        s_nums = sorted(list(s_nums_set))
        if not s_nums:
            s_nums = [1]

        for s_num in s_nums:
            tmdb_eps = fetch_season_episodes(media["tmdb_id"], s_num)
            merged_list = []
            if tmdb_eps:
                seen_ep_nums = set()
                for meta in tmdb_eps:
                    ep_num = meta["episode_number"]
                    seen_ep_nums.add(ep_num)
                    if (s_num, ep_num) in local_map:
                        ep = dict(local_map[(s_num, ep_num)])
                        ep["is_local"] = True
                        if not ep.get("ep_title") or ep.get("ep_title") == ep.get("title"):
                            ep["ep_title"] = meta.get("name")
                        ep["overview"] = meta.get("overview") or ep.get("overview")
                        ep["still_path"] = meta.get("still_path") or ep.get("backdrop_path")
                        if meta.get("runtime"):
                            ep["duration"] = meta.get("runtime") * 60
                        if pid and ep.get("id"):
                            ep_progress = get_progress(pid, ep["id"])
                            ep["progress"] = dict(ep_progress) if ep_progress else None
                        merged_list.append(ep)
                    else:
                        merged_list.append({
                            "id": None,
                            "is_local": False,
                            "season": s_num,
                            "episode": ep_num,
                            "ep_title": meta.get("name"),
                            "overview": meta.get("overview"),
                            "still_path": meta.get("still_path") or media.get("backdrop_path"),
                            "duration": (meta.get("runtime") * 60) if meta.get("runtime") else None,
                            "title": media.get("title"),
                            "progress": None
                        })
                for (ls, le), ep in local_map.items():
                    if ls == s_num and le not in seen_ep_nums:
                        ep_dict = dict(ep)
                        ep_dict["is_local"] = True
                        if pid and ep_dict.get("id"):
                            ep_progress = get_progress(pid, ep_dict["id"])
                            ep_dict["progress"] = dict(ep_progress) if ep_progress else None
                        merged_list.append(ep_dict)
            else:
                for (ls, le), ep in local_map.items():
                    if ls == s_num:
                        ep_dict = dict(ep)
                        ep_dict["is_local"] = True
                        if pid and ep_dict.get("id"):
                            ep_progress = get_progress(pid, ep_dict["id"])
                            ep_dict["progress"] = dict(ep_progress) if ep_progress else None
                        merged_list.append(ep_dict)

            seasons[str(s_num)] = sorted(merged_list, key=lambda e: e.get("episode") or 0)

        media["seasons"] = seasons

    # Parse cast_json
    if media.get("cast_json"):
        try:
            media["cast"] = json.loads(media["cast_json"])
        except Exception:
            media["cast"] = []
    else:
        media["cast"] = []

    # Find subtitles (external, Subs/ subfolders, and embedded)
    from backend.subtitles import get_all_subtitles
    media["subtitles"] = get_all_subtitles(media["file_path"], media_id)

    # Probe audio tracks for Multi-Audio indicator badge
    from backend.audio_probe import probe_audio_tracks
    media["audio_tracks"] = probe_audio_tracks(media["file_path"])
    media["has_multi_audio"] = len(media["audio_tracks"]) > 1

    return jsonify(media)


@app.route("/api/media/<int:media_id>/trailer", methods=["GET"])
def api_media_trailer(media_id):
    media = get_media_by_id(media_id)
    if not media:
        return jsonify({"error": "Media not found"}), 404

    from backend.matcher import get_media_trailer
    trailer = get_media_trailer(media.get("tmdb_id"), media.get("type", "movie"))
    if not trailer:
        return jsonify({"error": "Trailer not available for this title"}), 404

    return jsonify(trailer)


@app.route("/api/show/<int:tmdb_id>", methods=["GET"])
def api_show_detail(tmdb_id):
    """Get show detail by TMDb ID (or fallback to media ID)."""
    media_type = request.args.get("type", "series")
    episodes = get_media_by_tmdb(tmdb_id, media_type)
    if not episodes:
        # Fallback: check if tmdb_id is a media ID
        single = get_media_by_id(tmdb_id)
        if single:
            if single.get("tmdb_id"):
                episodes = get_media_by_tmdb(single["tmdb_id"], single.get("type", media_type))
            else:
                episodes = [single]

    if not episodes:
        return jsonify({"error": "Not found"}), 404

    # Use first episode's show-level metadata
    show = dict(episodes[0])
    show["is_mounted"] = any(ep.get("is_mounted", False) for ep in episodes)
    # Remove episode-specific fields for the show object
    for f in ["season", "episode", "ep_title", "file_path", "file_size", "duration"]:
        show.pop(f, None)

    if show.get("cast_json"):
        try:
            show["cast"] = json.loads(show["cast_json"])
        except Exception:
            show["cast"] = []

    pid = _current_profile()
    from backend.matcher import fetch_season_episodes

    local_map = {}
    for ep_row in episodes:
        ep = dict(ep_row)
        try:
            s_int = int(ep.get("season") or 1)
        except Exception:
            s_int = 1
        try:
            ep_int = int(ep.get("episode") or 1)
        except Exception:
            ep_int = 1
        local_map[(s_int, ep_int)] = ep

    seasons = {}
    tmdb_id = show.get("tmdb_id")
    s_nums = set(k[0] for k in local_map.keys())
    if not s_nums:
        s_nums = {1}

    for s_num in s_nums:
        tmdb_eps = fetch_season_episodes(tmdb_id, s_num) if tmdb_id else []
        merged_list = []
        if tmdb_eps:
            seen_ep_nums = set()
            for meta in tmdb_eps:
                ep_num = meta["episode_number"]
                seen_ep_nums.add(ep_num)
                if (s_num, ep_num) in local_map:
                    ep = dict(local_map[(s_num, ep_num)])
                    ep["is_local"] = True
                    if not ep.get("ep_title") or ep.get("ep_title") == ep.get("title"):
                        ep["ep_title"] = meta.get("name")
                    ep["overview"] = meta.get("overview") or ep.get("overview")
                    ep["still_path"] = meta.get("still_path") or ep.get("backdrop_path")
                    if meta.get("runtime"):
                        ep["duration"] = meta.get("runtime") * 60
                    if pid and ep.get("id"):
                        ep_progress = get_progress(pid, ep["id"])
                        ep["progress"] = dict(ep_progress) if ep_progress else None
                    merged_list.append(ep)
                else:
                    merged_list.append({
                        "id": None,
                        "is_local": False,
                        "season": s_num,
                        "episode": ep_num,
                        "ep_title": meta.get("name"),
                        "overview": meta.get("overview"),
                        "still_path": meta.get("still_path") or show.get("backdrop_path"),
                        "duration": (meta.get("runtime") * 60) if meta.get("runtime") else None,
                        "title": show.get("title"),
                        "progress": None
                    })
            # Add any extra local files not in TMDb list
            for (ls, le), ep in local_map.items():
                if ls == s_num and le not in seen_ep_nums:
                    ep_dict = dict(ep)
                    ep_dict["is_local"] = True
                    if pid and ep_dict.get("id"):
                        ep_progress = get_progress(pid, ep_dict["id"])
                        ep_dict["progress"] = dict(ep_progress) if ep_progress else None
                    merged_list.append(ep_dict)
        else:
            # Fallback to local files only
            for (ls, le), ep in local_map.items():
                if ls == s_num:
                    ep_dict = dict(ep)
                    ep_dict["is_local"] = True
                    if pid and ep_dict.get("id"):
                        ep_progress = get_progress(pid, ep_dict["id"])
                        ep_dict["progress"] = dict(ep_progress) if ep_progress else None
                    merged_list.append(ep_dict)

        seasons[str(s_num)] = sorted(merged_list, key=lambda e: e.get("episode") or 0)

    # ── Missing seasons (Jellyfin-style) ─────────────────────────
    # Seasons the library has no local episode rows for still need to
    # appear (grayed tab + "Not Downloaded" placeholder episodes).
    # Expected count comes from the matcher's cached TMDb show detail
    # (number_of_seasons), falling back to a live TMDb lookup.
    expected_seasons = 0
    if tmdb_id:
        from backend.matcher import _load_cache, _tmdb_get
        for cache_type in (media_type, "series", "anime"):
            cached_show = _load_cache(cache_type, tmdb_id)
            if cached_show and cached_show.get("seasons"):
                try:
                    expected_seasons = int(cached_show["seasons"])
                    break
                except (TypeError, ValueError):
                    continue
        if expected_seasons <= 0:
            detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US"})
            if detail:
                try:
                    expected_seasons = int(detail.get("number_of_seasons") or 0)
                except (TypeError, ValueError):
                    expected_seasons = 0

    for s_num in range(1, expected_seasons + 1):
        if s_num in s_nums:
            continue
        tmdb_eps = fetch_season_episodes(tmdb_id, s_num) if tmdb_id else []
        if not tmdb_eps:
            continue  # unaired / no metadata for this season
        placeholder_list = []
        for meta in tmdb_eps:
            placeholder_list.append({
                "id": None,
                "is_local": False,
                "season": s_num,
                "episode": meta.get("episode_number"),
                "ep_title": meta.get("name"),
                "overview": meta.get("overview"),
                "still_path": meta.get("still_path") or show.get("backdrop_path"),
                "duration": (meta.get("runtime") * 60) if meta.get("runtime") else None,
                "title": show.get("title"),
                "progress": None,
            })
        seasons[str(s_num)] = sorted(placeholder_list, key=lambda e: e.get("episode") or 0)

    show["seasons"] = seasons
    if pid and episodes:
        show["is_favorite"] = is_favorite(pid, episodes[0]["id"])
    else:
        show["is_favorite"] = False

    # Probe first local episode for Multi-Audio badge
    if episodes:
        first_local = next((ep for ep in episodes if ep.get("file_path")), None)
        if first_local:
            from backend.audio_probe import probe_audio_tracks
            show["audio_tracks"] = probe_audio_tracks(first_local["file_path"])
            show["has_multi_audio"] = len(show.get("audio_tracks", [])) > 1

    return jsonify(show)


@app.route("/api/search", methods=["GET"])
def api_search():
    q = request.args.get("q", "").strip()
    media_type = request.args.get("type", "all")
    genre = request.args.get("genre", "all")
    sort_by = request.args.get("sort", "relevance")

    from backend.db import search_media
    results = search_media(query=q, media_type=media_type, genre=genre, sort_by=sort_by)
    if _active_is_kids():
        results = filter_kids(results)
    return jsonify(results)


@app.route("/api/genres", methods=["GET"])
def api_genres():
    return jsonify(get_all_genres())


# ─── Streaming ────────────────────────────────────────────────────────────────

@app.route("/api/skip-times/<int:media_id>")
def api_skip_times(media_id):
    from backend.skip_times import fetch_skip_times, SKIP_CACHE_DIR
    # refresh=1 drops the resolved cache so AniSkip is re-queried and audio
    # detection re-runs (used by the Edit Skip Timestamps "Check Online" button)
    if request.args.get("refresh") in ("1", "true"):
        cache_path = os.path.join(SKIP_CACHE_DIR, f"{media_id}.json")
        try:
            if os.path.isfile(cache_path):
                os.remove(cache_path)
        except Exception:
            pass
    skip_data = fetch_skip_times(media_id)
    return jsonify(skip_data)

@app.route("/api/quality-options/<int:media_id>")
def api_quality_options(media_id):
    options = get_media_quality_options(media_id)
    return jsonify(options)


@app.route("/api/audio-tracks/<int:media_id>")
def api_audio_tracks(media_id):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)
    from backend.audio_probe import probe_audio_tracks
    tracks = probe_audio_tracks(media["file_path"])
    return jsonify(tracks)


@app.route("/api/stream/<int:media_id>")
def api_stream(media_id):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)

    guard = _kids_guard_media(media, deep=True)
    if guard:
        return guard

    # Audio-only mode: the player keeps video native (muted) and streams just
    # the chosen track to a synced <audio> element.
    if request.args.get("audio_only") in ("1", "true"):
        audio_track = request.args.get("audio_track", "")
        at = request.args.get("at", type=float, default=0.0)
        if not audio_track.isdigit():
            abort(400, description="audio_track required for audio-only mode")
        from backend.streamer import stream_audio_only
        return stream_audio_only(media["file_path"], int(audio_track), start_time=at)

    # Hardware-accelerated full conversion (compatibility playback)
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


@app.route("/api/system/check-update", methods=["GET"])
def api_check_update():
    """Compare local VERSION with the latest GitHub release."""
    from backend.updater import check_for_update
    try:
        result = check_for_update()
        result["version"] = get_app_version()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "version": get_app_version(),
        }), 500


@app.route("/api/system/apply-update", methods=["POST"])
def api_apply_update():
    """Download and install the latest update package (code files only)."""
    from backend.updater import apply_update
    data = request.json or {}
    try:
        result = apply_update(data.get("download_url"))
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "restart_required": False,
            "ui_only": False,
        }), 500


# ─── Live Server Logs ─────────────────────────────────────────────────────────

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_NAME_RE = re.compile(r"^capsstream_\d{8}\.log$")


def _safe_log_path(name):
    """Validate a log filename against the whitelist and return its full path, or None."""
    if not name or not LOG_NAME_RE.match(name.strip()):
        return None
    return os.path.join(LOG_DIR, name.strip())


@app.route("/api/system/logs", methods=["GET"])
def api_system_logs():
    """List available server log files, newest first."""
    os.makedirs(LOG_DIR, exist_ok=True)
    files = []
    try:
        for name in os.listdir(LOG_DIR):
            fp = _safe_log_path(name)
            if fp and os.path.isfile(fp):
                files.append({
                    "name": name,
                    "size": os.path.getsize(fp),
                    "modified": int(os.path.getmtime(fp)),
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    files.sort(key=lambda f: f["modified"], reverse=True)
    return jsonify(files)


@app.route("/api/system/logs/tail", methods=["GET"])
def api_system_log_tail():
    """
    Incremental log tail. The client sends the byte offset it already has;
    the server returns only appended content. offset=0 returns the last
    `max_bytes` of the file (initial view).
    """
    fp = _safe_log_path(request.args.get("file") or "")
    if not fp:
        return jsonify({"error": "Invalid log file name"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        max_bytes = min(262144, max(1024, int(request.args.get("max_bytes", 32768))))
    except (TypeError, ValueError):
        max_bytes = 32768

    if not os.path.isfile(fp):
        return jsonify({"data": "", "offset": 0, "size": 0, "reset": True})

    size = os.path.getsize(fp)

    if offset > size:
        # File was truncated or rotated — tell the client to reset
        return jsonify({"data": "", "offset": 0, "size": size, "reset": True})

    if offset == 0:
        # Initial view: last max_bytes, trimmed to a clean line boundary
        start = max(0, size - max_bytes)
        with open(fp, "rb") as f:
            f.seek(start)
            data = f.read().decode("utf-8", errors="replace")
        if start > 0:
            nl = data.find("\n")
            if nl != -1:
                data = data[nl + 1:]
        return jsonify({"data": data, "offset": size, "size": size, "reset": False})

    with open(fp, "rb") as f:
        f.seek(offset)
        chunk = f.read(max_bytes)
    data = chunk.decode("utf-8", errors="replace")
    new_offset = offset + len(chunk)

    # Avoid splitting a line across polls: trim back to the last newline
    if new_offset < size:
        nl = data.rfind("\n")
        if nl != -1:
            data = data[:nl + 1]
            new_offset = offset + len(data.encode("utf-8"))

    return jsonify({"data": data, "offset": new_offset, "size": size, "reset": False})


@app.route("/api/system/logs/download", methods=["GET"])
def api_system_log_download():
    """Download a full log file."""
    fp = _safe_log_path(request.args.get("file") or "")
    if not fp or not os.path.isfile(fp):
        abort(404)
    return send_file(fp, as_attachment=True, download_name=os.path.basename(fp))


@app.route("/api/transcode-caps", methods=["GET"])
def api_transcode_caps():
    """Reports the best available video encoder for compatibility playback."""
    from backend.streamer import describe_hw_encoder
    return jsonify(describe_hw_encoder())


@app.route("/api/stream-start/<int:media_id>")
def api_stream_start(media_id):
    """
    Returns the keyframe-aligned start position for a requested content time.
    The player calls this before switching to a transcoded audio track so the
    stream begins exactly where video and audio can start in sync.
    """
    media = get_best_media_source(media_id)
    if not media:
        abort(404)

    guard = _kids_guard_media(media, deep=True)
    if guard:
        return guard

    start_time = request.args.get("start", type=float, default=0.0)
    from backend.streamer import find_keyframe_before
    aligned = find_keyframe_before(media["file_path"], start_time)
    return jsonify({"requested": start_time, "start": aligned})


# ─── Subtitles ────────────────────────────────────────────────────────────────

@app.route("/api/subtitles/<int:media_id>/embedded/<int:stream_index>.vtt")
def api_embedded_subtitles(media_id, stream_index):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)

    from backend.subtitles import extract_embedded_vtt
    vtt_path = extract_embedded_vtt(media["file_path"], stream_index, media_id)
    if not vtt_path or not os.path.exists(vtt_path):
        abort(404)

    return send_file(vtt_path, mimetype="text/vtt")


@app.route("/api/media/<int:media_id>/download-subtitles", methods=["POST"])
def api_download_subtitles(media_id):
    """
    Search OpenSubtitles by file hash and download subtitles for this media
    file in the user's preferred language(s). Requires a free OpenSubtitles
    API key in Settings → Player & Subtitle Defaults.
    """
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


@app.route("/api/subtitles/<int:media_id>/<path:filename>")
def api_subtitles(media_id, filename):
    media = get_best_media_source(media_id)
    if not media:
        abort(404)

    video_dir = os.path.dirname(media["file_path"])
    sub_path  = os.path.normpath(os.path.join(video_dir, filename))

    video_dir_norm = os.path.normpath(video_dir).lower()
    parent_dir_norm = os.path.normpath(os.path.dirname(video_dir)).lower()
    sub_path_norm  = os.path.normpath(sub_path).lower()

    if not sub_path_norm.startswith(video_dir_norm) and not sub_path_norm.startswith(parent_dir_norm):
        abort(403)

    from backend.subtitles import get_vtt_path
    vtt_path = get_vtt_path(sub_path)
    if not vtt_path:
        abort(404)

    return send_file(vtt_path, mimetype="text/vtt")


@app.route("/api/subtitles/online/search", methods=["GET"])
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


@app.route("/api/subtitles/online/download", methods=["POST"])
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


# ─── Watch Progress ───────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def api_get_profile_stats():
    pid = _require_profile()
    from backend.db import get_profile_watch_stats
    stats = get_profile_watch_stats(pid)
    return jsonify(stats)


@app.route("/api/achievements/unlock", methods=["POST"])
def api_unlock_custom_achievement():
    pid = _require_profile()
    data = request.json or {}
    achievement_id = data.get("achievement_id")
    if not achievement_id:
        return jsonify({"error": "achievement_id required"}), 400
    from backend.db import unlock_achievement
    unlocked_ach = unlock_achievement(pid, achievement_id)
    return jsonify({"ok": True, "unlocked": unlocked_ach})


@app.route("/api/progress", methods=["POST"])
def api_save_progress():
    pid = _require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    position = data.get("position", 0)
    duration = data.get("duration", 0)
    completed = data.get("completed", False)

    if not media_id:
        return jsonify({"error": "media_id required"}), 400

    save_progress(pid, media_id, position, duration, completed)
    from backend.db import check_and_unlock_achievements, get_profile_catalog
    newly_unlocked_ids = check_and_unlock_achievements(pid)
    catalog = get_profile_catalog(pid)
    unlocked_items = [a for a in catalog if a["id"] in newly_unlocked_ids]
    return jsonify({"ok": True, "unlocked_achievements": unlocked_items})


@app.route("/api/progress/<int:media_id>", methods=["GET"])
def api_get_progress(media_id):
    pid = _require_profile()
    progress = get_progress(pid, media_id)
    return jsonify(dict(progress) if progress else {})


# ─── Seekbar Preview Thumbnails ───────────────────────────────────────────────

@app.route("/api/media/<int:media_id>/thumbnails", methods=["GET"])
def api_media_thumbnails(media_id):
    """
    Returns seekbar preview-sheet info. On first request the sheet is
    generated in a background thread (returns ready:false immediately);
    the player keeps its plain tooltip until the sheet is available.
    """
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
            print(f"[Thumbs] Sheet generated for media {media_id}")
        except Exception as e:
            print(f"[Thumbs] Generation failed for media {media_id}: {e}")

    threading.Thread(target=_gen, daemon=True).start()
    return jsonify({"ready": False})


@app.route("/api/media/<int:media_id>/thumbnails/sheet", methods=["GET"])
def api_media_thumbnail_sheet(media_id):
    from backend import thumbs
    if not thumbs.is_ready(media_id):
        abort(404)
    return send_file(thumbs._sheet(media_id), mimetype="image/jpeg")


@app.route("/api/progress/<int:media_id>", methods=["DELETE"])
def api_delete_progress(media_id):
    pid = _require_profile()
    delete_progress(pid, media_id)
    return jsonify({"ok": True})


# ─── Favorites ────────────────────────────────────────────────────────────────

@app.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    pid = _require_profile()
    favs = get_favorites(pid)
    if _active_is_kids():
        favs = filter_kids(favs)
    return _jsonify_rows(favs)


@app.route("/api/favorites/toggle", methods=["POST"])
@app.route("/api/favorites/<int:media_id>", methods=["POST"])
def api_toggle_favorite(media_id=None):
    pid = _require_profile()
    if media_id is None:
        data = request.json or {}
        media_id = data.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id is required"}), 400
    is_fav = toggle_favorite(pid, media_id)
    return jsonify({"is_favorite": is_fav})


# ─── Collections ─────────────────────────────────────────────────────────────

@app.route("/api/collections", methods=["GET"])
def api_get_collections():
    pid = _require_profile()
    result = get_collections(pid)
    all_media = get_unique_shows(None)
    kids = _active_is_kids()
    if kids:
        all_media = filter_kids(all_media)

    # ─── Smart collections (computed live, read-only) ───
    def _smart(cid, name, desc, items):
        return {
            "id": cid, "name": name, "description": desc,
            "smart": True, "items": items,
        }

    unwatched = [
        m for m in all_media
        if not get_progress(pid, m.get("id"))
    ]
    result.insert(0, _smart("smart-unwatched", "Unwatched",
                            "Library titles you haven't started yet", unwatched[:20]))
    result.insert(1, _smart("smart-recent", "Recently Added",
                            "The newest additions to your library", get_recently_added(limit=20)))
    result.insert(2, _smart("smart-top", "Top Rated",
                            "Highest rated titles in your library", get_top_rated(limit=20)))

    # ─── Cinematic Universe & Franchise Collections (2+ matching titles) ───
    universe_collections = get_universe_collections(all_media, min_count=2)
    result.extend(universe_collections)

    if kids:
        filtered = []
        for col in result:
            items = filter_kids(col.get("items"))
            if items:
                filtered.append({**col, "items": items})
        result = filtered

    return jsonify(result)


@app.route("/api/collections", methods=["POST"])
def api_create_collection():
    pid = _require_profile()
    data = request.json or {}
    name = data.get("name", "").strip()
    desc = data.get("description", "")
    if not name:
        return jsonify({"error": "Name required"}), 400
    cid = create_collection(pid, name, desc)
    return jsonify({"id": cid, "name": name, "description": desc, "items": []}), 201


@app.route("/api/collections/<int:collection_id>", methods=["DELETE"])
def api_delete_collection(collection_id):
    pid = _require_profile()
    delete_collection(collection_id, pid)
    return jsonify({"ok": True})


@app.route("/api/collections/<int:collection_id>/items", methods=["POST"])
def api_add_to_collection(collection_id):
    pid = _require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id required"}), 400
    add_to_collection(collection_id, media_id)
    return jsonify({"ok": True})


@app.route("/api/collections/<int:collection_id>/items/<int:media_id>", methods=["DELETE"])
def api_remove_from_collection(collection_id, media_id):
    pid = _require_profile()
    remove_from_collection(collection_id, media_id)
    return jsonify({"ok": True})


# ─── Library Scan ─────────────────────────────────────────────────────────────

_scan_thread = None


@app.route("/api/scan", methods=["POST"])
def api_scan():
    global _scan_thread
    status = get_scan_status()
    if status["running"]:
        return jsonify({"error": "Scan already in progress", "status": status}), 409

    def run_scan():
        scan_library()

    _scan_thread = threading.Thread(target=run_scan, daemon=True)
    _scan_thread.start()
    return jsonify({"ok": True, "message": "Library scan started"})


@app.route("/api/scan/status", methods=["GET"])
def api_scan_status():
    return jsonify(get_scan_status())


@app.route("/api/system/shutdown", methods=["POST"])
def api_system_shutdown():
    """Gracefully stop the Flask server, flush databases, then exit."""
    def _shutdown():
        import time as _t
        # Stop accepting new connections first
        try:
            func = request.environ.get("werkzeug.server.shutdown")
            if func:
                func()
        except Exception:
            pass
        # Grace period: let in-flight requests and daemon workers finish
        _t.sleep(1.0)
        # Flush SQLite WAL so all committed data is written into the main db file
        try:
            from backend.db import get_conn
            conn = get_conn()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
        except Exception as e:
            print(f"[Shutdown] SQLite checkpoint failed: {e}")
        # Hard-exit. sys.exit() cannot be used here: raised inside a daemon
        # thread it only terminates that thread, leaving the server alive.
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True, "message": "Server shutting down cleanly"})


@app.route("/offline-page")
def api_offline_page():
    """Serve the standalone offline page used by the shutdown flow."""
    return send_from_directory(app.static_folder, "offline.html")


# ─── Backup & Restore ─────────────────────────────────────────────────────────

@app.route("/api/system/backup", methods=["GET"])
def api_system_backup():
    """
    Download a backup zip containing config.json and the library database.
    include_metadata=1 additionally bundles the metadata cache (posters,
    backdrops, JSON) — can be large.
    """
    import zipfile
    from backend.settings import CONFIG_PATH

    include_metadata = request.args.get("include_metadata") in ("1", "true")
    db_path = os.path.join(BASE_DIR, "data", "capsstream.db")
    if not os.path.isfile(db_path):
        return jsonify({"error": "Database not found"}), 404

    backup_name = f"CapsStream-backup-{time.strftime('%Y%m%d-%H%M')}.zip"
    zip_path = os.path.join(BASE_DIR, "_backup_tmp.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.isfile(CONFIG_PATH):
                zf.write(CONFIG_PATH, "config.json")
            zf.write(db_path, "data/capsstream.db")
            if include_metadata:
                meta_dir = os.path.join(BASE_DIR, "data", "metadata")
                for root, _dirs, files in os.walk(meta_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        arc = os.path.relpath(fp, BASE_DIR)
                        try:
                            zf.write(fp, arc)
                        except Exception:
                            continue
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=backup_name,
            mimetype="application/zip",
        )
    finally:
        try:
            os.remove(zip_path)
        except Exception:
            pass


@app.route("/api/system/restore", methods=["POST"])
def api_system_restore():
    """
    Restore from a backup zip. config.json is applied immediately (with the
    previous version kept in data/pre_restore/); the database is staged and
    swapped in by start.bat on the next launch (same mechanism as updates),
    because the live SQLite file cannot be replaced while the server runs.
    """
    import zipfile

    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Please upload a CapsStream backup .zip file"}), 400

    from backend.settings import CONFIG_PATH
    restore_cfg = False
    restore_db = False
    staged_db = None

    try:
        file.save(file.filename and os.path.join(BASE_DIR, "_restore_tmp.zip"))
        tmp_zip = os.path.join(BASE_DIR, "_restore_tmp.zip")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            names = zf.namelist()
            for n in names:
                base = os.path.basename(n)
                if base == "config.json" and not restore_cfg:
                    pre_dir = os.path.join(BASE_DIR, "data", "pre_restore")
                    os.makedirs(pre_dir, exist_ok=True)
                    if os.path.isfile(CONFIG_PATH):
                        shutil.copy2(CONFIG_PATH, os.path.join(
                            pre_dir, f"config.{time.strftime('%Y%m%d-%H%M%S')}.json"))
                    zf.extract(n, BASE_DIR)
                    restore_cfg = True
                elif base == "capsstream.db" and not restore_db:
                    from backend.updater import PENDING_DIR, _write_pending_manifest
                    rel = "data/capsstream.db"
                    pend = os.path.join(PENDING_DIR, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(pend), exist_ok=True)
                    with zf.open(n) as src, open(pend, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    staged_db = rel
                    restore_db = True

        os.remove(tmp_zip)
    except zipfile.BadZipFile:
        return jsonify({"error": "That file is not a valid backup zip"}), 400
    except Exception as e:
        return jsonify({"error": f"Restore failed: {e}"}), 500

    if staged_db:
        from backend.updater import _write_pending_manifest
        _write_pending_manifest([staged_db])

    if not restore_cfg and not restore_db:
        return jsonify({"error": "No config.json or capsstream.db found in that backup"}), 400

    return jsonify({
        "ok": True,
        "restored_config": restore_cfg,
        "restored_database": restore_db,
        "message": (
            "Settings restored. " if restore_cfg else ""
        ) + (
            "Database staged — it will be applied on the next server start (close CapsStream and run start.bat)."
            if restore_db else ""
        ),
    })


# ─── Scheduled Library Scans ──────────────────────────────────────────────────
# Optional auto-scan cadence (config: library.scan_interval_hours, 0 = off).
# A daemon thread checks every 10 minutes whether the interval has elapsed
# and triggers a scan through the same pipeline as POST /api/scan.

_SCAN_SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "scan_schedule.json")


def _read_last_scheduled_scan():
    try:
        with open(_SCAN_SCHEDULE_FILE, encoding="utf-8") as f:
            return float(json.load(f).get("last_run", 0))
    except Exception:
        return 0.0


def _write_last_scheduled_scan(ts):
    try:
        os.makedirs(os.path.dirname(_SCAN_SCHEDULE_FILE), exist_ok=True)
        with open(_SCAN_SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_run": ts}, f)
    except Exception:
        pass


def _scan_scheduler_loop():
    from backend.settings import load_config
    from backend.scanner import get_scan_status
    # First-run baseline: never fire immediately on server start or when the
    # schedule file is missing/zero — the countdown starts from now.
    if _read_last_scheduled_scan() <= 0:
        _write_last_scheduled_scan(time.time())
    while True:
        try:
            interval = float((load_config().get("library") or {}).get("scan_interval_hours") or 0)
            if interval > 0 and not get_scan_status()["running"]:
                last = _read_last_scheduled_scan()
                if last <= 0:
                    _write_last_scheduled_scan(time.time())
                elif time.time() - last >= interval * 3600:
                    status = get_scan_status()
                    if not status["running"]:
                        print(f"[Scheduler] Interval {interval}h elapsed — starting scheduled scan")
                        _write_last_scheduled_scan(time.time())
                        scan_library()
        except Exception as e:
            print(f"[Scheduler] Scan scheduler error: {e}")
        time.sleep(600)  # check every 10 minutes


def start_scan_scheduler():
    threading.Thread(target=_scan_scheduler_loop, daemon=True).start()


@app.route("/api/unmatched", methods=["GET"])
def api_unmatched():
    return _jsonify_rows(get_unmatched())


@app.route("/api/tmdb/search", methods=["GET"])
def api_tmdb_search():
    query = request.args.get("query", "").strip()
    mtype = request.args.get("type", "movie")
    year = request.args.get("year", "").strip()
    if not query:
        return jsonify([])
    from backend.matcher import search_tmdb
    results = search_tmdb(query, media_type=mtype, year=year or None)
    return jsonify(results)


@app.route("/api/override", methods=["POST"])
def api_override():
    """
    Manually set/fix a TMDb ID for a media item or an entire series.
    Body: { "media_id": <int optional>, "old_tmdb_id": <int optional>, "tmdb_id": <int>, "type": "movie"|"series"|"anime" }
    """
    data = request.json or {}
    media_id = data.get("media_id")
    old_tmdb_id = data.get("old_tmdb_id")
    tmdb_id = data.get("tmdb_id")
    mtype = data.get("type", "movie")

    if not tmdb_id:
        return jsonify({"error": "tmdb_id is required"}), 400

    from backend.matcher import override_match, get_season_episodes
    meta = override_match(media_id, tmdb_id, mtype)
    if not meta:
        return jsonify({"error": "TMDb metadata not found for ID"}), 404

    from backend.db import get_conn
    conn = get_conn()
    rows = []
    if old_tmdb_id:
        rows = conn.execute("SELECT * FROM media WHERE tmdb_id=? AND type=?", (old_tmdb_id, mtype)).fetchall()
    if not rows and media_id:
        row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if row:
            if row["type"] in ("series", "anime") and row["tmdb_id"]:
                rows = conn.execute("SELECT * FROM media WHERE tmdb_id=? AND type=?", (row["tmdb_id"], row["type"])).fetchall()
            else:
                rows = [row]

    if not rows and media_id:
        r = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if r:
            rows = [r]

    if not rows:
        conn.close()
        return jsonify({"error": "No media records found to update"}), 404

    season_cache = {}
    updated_count = 0
    for r in rows:
        row_dict = dict(r)
        ep_title = row_dict.get("ep_title")
        season_num = row_dict.get("season")
        ep_num = row_dict.get("episode")

        # If it's a series, try to fetch season episode name
        if mtype in ("series", "anime") and season_num is not None and ep_num is not None:
            if season_num not in season_cache:
                season_cache[season_num] = get_season_episodes(tmdb_id, season_num, media_type=mtype)
            ep_list = season_cache[season_num] or []
            ep_info = next((e for e in ep_list if e.get("episode_number") == ep_num), None)
            if ep_info and ep_info.get("name"):
                ep_title = ep_info.get("name")

        updated_dict = {
            **row_dict,
            **meta,
            "id": row_dict["id"],
            "file_path": row_dict["file_path"],
            "type": mtype,
            "tmdb_id": tmdb_id,
            "season": row_dict.get("season"),
            "episode": row_dict.get("episode"),
            "ep_title": ep_title,
            "tmdb_matched": 1,
            "manually_overridden": 1
        }
        upsert_media(updated_dict)
        updated_count += 1

    conn.close()
    return jsonify({"ok": True, "updated": updated_count})



@app.route("/api/recache", methods=["POST"])
def api_recache_media():
    """
    Re-cache a title: deletes its cached TMDb metadata JSONs, season caches,
    external-ID cache and ALL downloaded artwork files, then re-downloads
    fresh metadata + images and updates every library row of the title
    (episode-specific fields like season/episode/markers are preserved).
    Body: { "tmdb_id": <int>, "type": "movie"|"series"|"anime" }
    """
    data = request.json or {}
    tmdb_id = data.get("tmdb_id")
    mtype = data.get("type", "movie")

    if not tmdb_id:
        return jsonify({"error": "This title has no TMDb match. Use 'Fix Match' first."}), 400

    import glob as _glob
    from backend.db import get_conn
    from backend.matcher import (
        METADATA_DIR, match_movie_by_id, match_show_by_id, fetch_imdb_id,
    )

    removed = 0

    # ── 1) Delete cached metadata JSONs (title + seasons + external ids) ──
    delete_paths = [
        os.path.join(METADATA_DIR, f"{mtype}_{tmdb_id}.json"),
        os.path.join(METADATA_DIR, f"external_ids_{mtype}_{tmdb_id}.json"),
    ]
    delete_paths.extend(_glob.glob(os.path.join(METADATA_DIR, f"season_{tmdb_id}_*.json")))
    for p in delete_paths:
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM media WHERE tmdb_id=? AND type=?", (tmdb_id, mtype)
    ).fetchall()
    if not rows:
        conn.close()
        return jsonify({"error": "No library rows found for this title"}), 404

    # ── 2) Delete downloaded artwork referenced by any row of this title ──
    for r in rows:
        for key in ("poster_path", "backdrop_path", "logo_path"):
            rel = r[key]
            if not rel or not str(rel).startswith("images/"):
                continue
            p = os.path.join(METADATA_DIR, str(rel).replace("/", os.sep))
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass

    # ── 3) Fresh fetch from TMDb (re-downloads images, rewrites caches) ──
    meta = (
        match_show_by_id(tmdb_id, mtype)
        if mtype in ("series", "anime")
        else match_movie_by_id(tmdb_id)
    )
    if not meta:
        conn.close()
        return jsonify({"error": "TMDb refresh failed — check connection/API key and retry"}), 502

    try:
        fetch_imdb_id(tmdb_id, mtype)
    except Exception:
        pass

    # ── 4) Update every row of the title, preserving episode-specific fields.
    #       upsert_media does not touch skip markers or duration. ──
    for r in rows:
        upsert_media({
            **meta,
            "file_path":   r["file_path"],
            "file_size":   r["file_size"] or 0,
            "season":      r["season"],
            "episode":     r["episode"],
            "ep_title":    r["ep_title"],
            "tmdb_matched": 1,
        })
    conn.close()

    return jsonify({
        "ok": True,
        "removed_files": removed,
        "updated_rows": len(rows),
        "title": meta.get("title"),
        "year": meta.get("year"),
    })



def _media_duration_seconds(file_path):
    """Best-effort stream duration via ffprobe (0 if unavailable)."""
    ffprobe = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffprobe.exe")
    if not file_path or not os.path.isfile(ffprobe):
        return 0.0
    try:
        from backend.proc_utils import CREATE_NO_WINDOW
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        info = json.loads(out.stdout)
        return round(float(info.get("format", {}).get("duration") or 0), 3)
    except Exception:
        return 0.0


@app.route("/api/media/<int:media_id>/skip-timestamps", methods=["POST"])
def api_update_skip_timestamps(media_id):
    """
    Save manual skip markers with AniSkip-style validation:
      - recap / intro:            max 5 min
      - outro / preview:          max 15 min
      - all segments:             at least 5s long
      - 0/0 sentinel:             "confirmed — no segment of this type"
      - outro end omitted or within 10s of duration → snapped to duration
    """
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

        # Normalize to int-or-None
        def _to_int(v):
            if v is None or v == "":
                return None
            try:
                return int(round(float(v)))
            except (TypeError, ValueError):
                return None

        s_i, e_i = _to_int(s), _to_int(e)

        # Unsubmitted segment → leave existing value untouched
        if s_i is None and e_i is None:
            continue

        # Sentinel: 0/0 = "confirmed — this episode has no segment of this type"
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

        # Outro end omitted or zero → runs to the end of the stream
        # (checked BEFORE the required-end validation)
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
        # Snap an end within 10s of the stream duration to the exact duration
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


@app.route("/favicon.ico")
def favicon():
    fav_path = os.path.join(BASE_DIR, "static", "img", "favicon.png")
    if os.path.exists(fav_path):
        return send_file(fav_path, mimetype="image/png")
    return "", 204


@app.route("/api/system/browse-folder", methods=["POST"])
def api_system_browse_folder():
    from backend.settings import browse_folder_dialog
    folder_path = browse_folder_dialog()
    if folder_path:
        return jsonify({"ok": True, "path": folder_path})
    return jsonify({"ok": False, "cancelled": True}), 200


@app.route("/api/system/validate-paths", methods=["POST"])
def api_system_validate_paths():
    data = request.json or {}
    paths_list = data.get("paths", [])
    from backend.settings import validate_media_paths
    results = validate_media_paths(paths_list)
    return jsonify(results)


@app.route("/api/system/info", methods=["GET"])
def api_system_info():
    import sys
    import platform
    import json
    from backend.db import DB_PATH, get_conn
    from backend.updater import _read_state as _updater_state

    db_size_str = "0 KB"
    if os.path.exists(DB_PATH):
        sz = os.path.getsize(DB_PATH)
        if sz >= 1024 * 1024:
            db_size_str = f"{sz / (1024 * 1024):.1f} MB"
        else:
            db_size_str = f"{sz / 1024:.1f} KB"

    ffmpeg_path = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")
    ffprobe_path = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffprobe.exe")
    has_ffmpeg = os.path.exists(ffmpeg_path)
    has_ffprobe = os.path.exists(ffprobe_path)

    # Fast SQL counts — never load the whole media table into memory here
    movies_count = series_count = anime_count = 0
    skip_markers_count = 0
    try:
        conn = get_conn()
        for r in conn.execute("SELECT type, COUNT(*) FROM media GROUP BY type").fetchall():
            if r[0] == "movie":
                movies_count = r[1]
            elif r[0] == "series":
                series_count = r[1]
            elif r[0] == "anime":
                anime_count = r[1]
        # Count media that has markers — either manual DB values (a 0/0 pair
        # means "confirmed none", so only count > 0) OR a resolved skip-time
        # cache entry (AniSkip / chapter detection), which the player uses too.
        manual_marker_ids = {
            row[0] for row in conn.execute("""
                SELECT id FROM media WHERE
                  (recap_start  IS NOT NULL AND recap_start  > 0) OR
                  (intro_start  IS NOT NULL AND intro_start  > 0) OR
                  (outro_start  IS NOT NULL AND outro_start  > 0) OR
                  (preview_start IS NOT NULL AND preview_start > 0)
            """).fetchall()
        }
        all_media_ids = {row[0] for row in conn.execute("SELECT id FROM media").fetchall()}
        auto_marker_ids = set()
        skip_cache_dir = os.path.join(BASE_DIR, "data", "metadata", "skip_times")
        if os.path.isdir(skip_cache_dir):
            for fname in os.listdir(skip_cache_dir):
                base = os.path.splitext(fname)[0]
                if base.isdigit():
                    auto_marker_ids.add(int(base))
        skip_markers_count = len(manual_marker_ids | (auto_marker_ids & all_media_ids))
        conn.close()
    except Exception:
        pass
    total_count = movies_count + series_count + anime_count

    github_profile = _get_github_profile()

    # Calculate media storage sizes via instant SQL aggregation
    total_bytes, movies_bytes, series_bytes, anime_bytes = 0, 0, 0, 0
    try:
        from backend.db import get_conn
        conn = get_conn()
        res = conn.execute("""
            SELECT 
                COALESCE(SUM(file_size), 0) as total_bytes,
                COALESCE(SUM(CASE WHEN type='movie' THEN file_size ELSE 0 END), 0) as movies_bytes,
                COALESCE(SUM(CASE WHEN type='series' THEN file_size ELSE 0 END), 0) as series_bytes,
                COALESCE(SUM(CASE WHEN type='anime' THEN file_size ELSE 0 END), 0) as anime_bytes
            FROM media
        """).fetchone()
        conn.close()
        if res:
            total_bytes = res[0] or 0
            movies_bytes = res[1] or 0
            series_bytes = res[2] or 0
            anime_bytes = res[3] or 0
    except Exception:
        pass

    def format_bytes(b):
        if not b or b <= 0:
            return "0 GB"
        tb = b / (1024 ** 4)
        if tb >= 1.0:
            return f"{tb:.2f} TB" if tb < 10 else f"{tb:.1f} TB"
        gb = b / (1024 ** 3)
        if gb >= 1.0:
            return f"{gb:.2f} GB" if gb < 10 else f"{gb:.1f} GB"
        mb = b / (1024 ** 2)
        if mb >= 1.0:
            return f"{mb:.1f} MB"
        return f"{b / 1024:.0f} KB"

    storage_info = {
        "total_size": format_bytes(total_bytes),
        "total_bytes": total_bytes,
        "movies_size": format_bytes(movies_bytes),
        "series_size": format_bytes(series_bytes),
        "anime_size": format_bytes(anime_bytes),
        "movies_pct": round((movies_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
        "series_pct": round((series_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
        "anime_pct": round((anime_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
    }

    # Uptime calculation
    uptime_sec = int(time.time() - SERVER_START_TIME)
    uptime_h = uptime_sec // 3600
    uptime_m = (uptime_sec % 3600) // 60
    uptime_s = uptime_sec % 60
    uptime_str = f"{uptime_h}h {uptime_m}m {uptime_s}s" if uptime_h > 0 else f"{uptime_m}m {uptime_s}s"

    # Native System RAM Load calculation
    ram_info = {"load_pct": 0, "total_gb": 0, "free_gb": 0, "used_gb": 0}
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong),
                ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong)
            ]
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            tot_gb = round(ms.ullTotalPhys / (1024**3), 1)
            free_gb = round(ms.ullAvailPhys / (1024**3), 1)
            used_gb = round(tot_gb - free_gb, 1)
            ram_info = {
                "load_pct": ms.dwMemoryLoad,
                "total_gb": tot_gb,
                "free_gb": free_gb,
                "used_gb": used_gb
            }
    except Exception:
        pass

    # Database Table Metrics
    db_metrics = {
        "profiles_count": len(get_all_profiles() or []),
        "favorites_count": 0,
        "progress_count": 0,
        "skip_markers_count": skip_markers_count
    }
    try:
        from backend.db import get_db
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM progress")
            db_metrics["progress_count"] = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM favorites")
            db_metrics["favorites_count"] = c.fetchone()[0] or 0
    except Exception:
        pass

    # External API Health (real probes, cached)
    config = load_config()
    api_health = _get_api_health(config)

    # Drive health — auto-detect ALL system drives (fixed + removable)
    import shutil
    drive_roots = set()
    try:
        if hasattr(os, "listdrives"):  # Python 3.12+ on Windows
            drive_roots = {d + "\\" for d in os.listdrives()}
        else:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive_roots.add(chr(ord("A") + i) + ":\\")
    except Exception:
        drive_roots = {os.path.splitdrive(BASE_DIR)[0] + "\\"}

    disk_info = []
    for drive in sorted(drive_roots):
        try:
            usage = shutil.disk_usage(drive)
            if usage.total <= 0:
                continue
            disk_info.append({
                "drive": drive,
                "free_gb": round(usage.free / 1024**3, 1),
                "total_gb": round(usage.total / 1024**3, 1),
                "used_pct": round(100 * usage.used / usage.total) if usage.total else 0,
            })
        except Exception:
            continue  # empty card reader / disconnected drive

    return jsonify({
        "version": get_app_version(),
        "is_dev": is_dev_mode(),
        "app_name": "CapsStream",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
        "os_name": os.name,
        "server_uptime": uptime_str,
        "database_size": db_size_str,
        "has_ffmpeg": has_ffmpeg,
        "has_ffprobe": has_ffprobe,
        "ram_info": ram_info,
        "db_metrics": db_metrics,
        "api_health": api_health,
        "github_profile": github_profile,
        "server_addr": f"{config.get('host', '127.0.0.1')}:{config.get('port', 8000)}",
        "last_checked": _updater_state().get("last_checked"),
        "latest_version": _updater_state().get("latest"),
        "storage_info": storage_info,
        "disk_info": disk_info,
        "media_counts": {
            "total": total_count,
            "movies": movies_count,
            "series": series_count,
            "anime": anime_count
        }
    })


# ─── Network Activity & Outgoing Request Inspector ───────────────────────────

@app.route("/api/system/network-requests", methods=["GET"])
def api_get_network_requests():
    """Return recorded outgoing HTTP requests and activity metrics."""
    service_filter = request.args.get("service")
    status_filter = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 150))
    except (TypeError, ValueError):
        limit = 150
    limit = max(1, min(limit, 200))
    data = get_recorded_requests(limit=limit, service_filter=service_filter, status_filter=status_filter)
    return jsonify(data)


@app.route("/api/system/network-requests/clear", methods=["POST"])
def api_clear_network_requests():
    """Clear recorded outgoing HTTP requests."""
    clear_recorded_requests()
    return jsonify({"ok": True, "message": "Network activity log cleared"})


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  CapsStream — Starting up")
    print("=" * 50)

    # Initialize database
    init_db()

    # Start the scheduled-scan daemon (respects library.scan_interval_hours)
    start_scan_scheduler()

    # Background pass: audio-based intro detection for shows without markers.
    # Delayed 2 minutes so it never competes with app launch or initial playback.
    from backend.scanner import start_intro_detection_pass
    threading.Timer(120, start_intro_detection_pass).start()

    # Load config and apply system file hiding
    cfg = load_config()
    apply_system_file_hiding()
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8000)

    # Library scanning is intentionally NOT started here.
    # The scan waits until the user logs into a profile (frontend triggers POST /api/scan after login).

    print(f"\n  ==========================================================")
    print(f"   CapsStream Server running at: http://{host}:{port}")
    print(f"   TO STOP THE SERVER: Press Ctrl+C in this window")
    print(f"  ==========================================================\n")

    app.run(host=host, port=port, debug=False, threaded=True)
