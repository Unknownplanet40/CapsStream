# -*- coding: utf-8 -*-
"""
backend/routes/requests.py — Offline, drive-based media requests API.

Allows users (e.g., Uncle) to submit movie, show, or anime requests stored
locally in data/requests.json. When the drive is returned to the developer
(indicated by the root DEV file), DEV mode unlocks status toggling, editing,
and clearing completed requests.
"""
import os
import json
import time
import secrets
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request, abort

import re
from backend.utils.paths import BASE_DIR
from backend.utils.version import is_dev_mode
from backend.db.profiles import get_profile
from backend.db.connection import get_conn
from .middleware import current_profile

requests_bp = Blueprint("requests", __name__)


@requests_bp.before_request
def _check_requests_feature():
    from backend.settings import load_config
    cfg = load_config()
    features = cfg.get("features", {})
    if not features.get("requests", False):
        return jsonify({"error": "Media requests feature is currently disabled"}), 403

_LOCK = threading.Lock()
REQUESTS_FILE = os.path.join(BASE_DIR, "data", "requests.json")


def _load_requests():
    """Load requests from data/requests.json with thread safety."""
    if not os.path.isfile(REQUESTS_FILE):
        return []
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_requests(reqs):
    """Atomically write requests to data/requests.json."""
    os.makedirs(os.path.dirname(REQUESTS_FILE), exist_ok=True)
    tmp_file = REQUESTS_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(reqs, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, REQUESTS_FILE)


def get_series_library_inventory(title=None, tmdb_id=None):
    """
    Check what seasons and episodes of a series are currently in the library.
    Returns dict with {in_library, total_episodes, seasons, seasons_display}.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        rows = []
        if tmdb_id:
            try:
                cur.execute(
                    "SELECT season, episode FROM media WHERE type IN ('series', 'anime') AND tmdb_id = ?",
                    (int(tmdb_id),)
                )
                rows = cur.fetchall()
            except Exception:
                rows = []

        if not rows and title:
            clean_title = re.sub(r"[^\w\s]", "", title.lower()).strip()
            if clean_title:
                cur.execute(
                    "SELECT title, original_title, season, episode FROM media WHERE type IN ('series', 'anime')"
                )
                candidates = cur.fetchall()
                for c in candidates:
                    ct = re.sub(r"[^\w\s]", "", (c["title"] or "").lower()).strip()
                    co = re.sub(r"[^\w\s]", "", (c["original_title"] or "").lower()).strip()
                    if clean_title == ct or (co and clean_title == co):
                        rows.append(c)

        if not rows:
            return {"in_library": False, "total_episodes": 0, "seasons": {}, "seasons_display": ""}

        seasons_map = {}
        for r in rows:
            s = r["season"] if r["season"] is not None else 1
            seasons_map[s] = seasons_map.get(s, 0) + 1

        sorted_seasons = sorted(seasons_map.keys())
        parts = []
        for s in sorted_seasons:
            count = seasons_map[s]
            parts.append(f"Season {s} ({count} ep{'s' if count != 1 else ''})")

        return {
            "in_library": True,
            "total_episodes": len(rows),
            "seasons": seasons_map,
            "seasons_display": ", ".join(parts)
        }
    except Exception as e:
        print(f"[Requests] Error querying series library inventory: {e}")
        return {"in_library": False, "total_episodes": 0, "seasons": {}, "seasons_display": ""}


def detect_media_in_library(req):
    """
    Check if a requested media item exists in the CapsStream database.
    If season/episode are specified in the request, checks that specific season/episode.
    Returns dict with {id, type, title, tmdb_id, year, season, episode} if found, else None.
    """
    tmdb_id = req.get("tmdb_id")
    title = (req.get("title") or "").strip()
    year = req.get("year")
    req_type = req.get("type") or "Movie"

    req_season = req.get("season")
    try:
        req_season = int(req_season) if req_season is not None and str(req_season).strip() != "" else None
    except (ValueError, TypeError):
        req_season = None

    req_episode = req.get("episode")
    try:
        req_episode = int(req_episode) if req_episode is not None and str(req_episode).strip() != "" else None
    except (ValueError, TypeError):
        req_episode = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        # 1. Exact TMDb ID match
        if tmdb_id:
            try:
                tmdb_int = int(tmdb_id)
                query = "SELECT id, type, title, year, tmdb_id, season, episode FROM media WHERE tmdb_id = ?"
                params = [tmdb_int]
                if req_season is not None:
                    query += " AND season = ?"
                    params.append(req_season)
                if req_episode is not None:
                    query += " AND episode = ?"
                    params.append(req_episode)
                query += " LIMIT 1"

                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    return dict(row)
            except (ValueError, TypeError):
                pass

        # 2. Title + Year normalization match
        if not title:
            return None

        clean_req_title = re.sub(r"[^\w\s]", "", title.lower()).strip()
        if not clean_req_title:
            return None

        type_filter = ""
        if req_type == "Movie":
            type_filter = "AND type = 'movie'"
        elif req_type in ("TV Show", "Anime"):
            type_filter = "AND type IN ('series', 'anime')"

        query = f"SELECT id, type, title, original_title, year, tmdb_id, season, episode FROM media WHERE 1=1 {type_filter}"
        params = []
        if req_season is not None:
            query += " AND season = ?"
            params.append(req_season)
        if req_episode is not None:
            query += " AND episode = ?"
            params.append(req_episode)

        cur.execute(query, params)
        candidates = cur.fetchall()
        for r in candidates:
            row_title = re.sub(r"[^\w\s]", "", (r["title"] or "").lower()).strip()
            row_orig = re.sub(r"[^\w\s]", "", (r["original_title"] or "").lower()).strip()
            if clean_req_title == row_title or (row_orig and clean_req_title == row_orig):
                if year and r["year"]:
                    try:
                        if abs(int(r["year"]) - int(year)) <= 1:
                            return dict(r)
                    except Exception:
                        pass
                elif not year:
                    return dict(r)
    except Exception as e:
        print(f"[Requests] Error detecting media in library: {e}")

    return None


def sync_requests_with_library(items=None):
    """
    Auto-detect if pending or untracked requests have been added to the media library.
    Marks newly detected requests as 'completed' and links their library media_id.
    """
    save_needed = False
    with _LOCK:
        if items is None:
            items = _load_requests()
            save_needed = True

        detected_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for req in items:
            matched = detect_media_in_library(req)
            if matched:
                prev_status = req.get("status")
                req["detected_media_id"] = matched["id"]
                req["detected_media_type"] = matched["type"]
                req["detected_tmdb_id"] = matched.get("tmdb_id")

                if prev_status == "pending":
                    req["status"] = "completed"
                    req["auto_detected"] = True
                    req["completed_at"] = now_str
                    req["updated_at"] = now_str
                    detected_count += 1
                    save_needed = True
                elif not req.get("detected_media_id"):
                    save_needed = True
            elif req.get("auto_detected"):
                req["status"] = "pending"
                req["auto_detected"] = False
                req["detected_media_id"] = None
                req["detected_media_type"] = None
                req["detected_tmdb_id"] = None
                req["completed_at"] = None
                req["updated_at"] = now_str
                save_needed = True

        if save_needed:
            _save_requests(items)

    return items, detected_count


def _check_kids_guard():
    """Kids profiles are blocked from accessing or submitting requests."""
    pid = current_profile()
    if pid:
        prof = get_profile(pid)
        if prof and prof.get("is_kids"):
            abort(403, description="Media requests are not accessible in Kids mode.")


@requests_bp.route("/api/requests", methods=["GET"])
def api_get_requests():
    """Fetch all submitted requests and current dev_mode status, auto-detecting library items."""
    _check_kids_guard()
    items, _ = sync_requests_with_library()
    for item in items:
        p_id = item.get("profile_id")
        if p_id:
            p = get_profile(p_id)
            if p:
                if not item.get("requested_by") or item.get("requested_by") == "CapsStream User":
                    item["requested_by"] = p.get("name")
                if not item.get("profile_avatar") or item.get("profile_avatar") == "ph-user":
                    item["profile_avatar"] = p.get("avatar") or "🎬"
                if p.get("custom_avatar_url"):
                    item["custom_avatar_url"] = p.get("custom_avatar_url")
                if p.get("color"):
                    item["profile_color"] = p.get("color")
    return jsonify({
        "requests": items,
        "dev_mode": is_dev_mode()
    })


@requests_bp.route("/api/requests", methods=["POST"])
def api_create_request():
    """Submit a new media request to data/requests.json."""
    _check_kids_guard()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    media_type = (data.get("type") or "Movie").strip()
    if media_type not in ("Movie", "TV Show", "Anime"):
        media_type = "Movie"

    year = (str(data.get("year") or "").strip())[:4]
    notes = (data.get("notes") or "").strip()

    tmdb_id = data.get("tmdb_id")
    try:
        tmdb_id = int(tmdb_id) if tmdb_id is not None else None
    except (ValueError, TypeError):
        tmdb_id = None

    poster_path = data.get("poster_path")
    if poster_path and isinstance(poster_path, str):
        poster_path = poster_path.strip()
    else:
        poster_path = None

    backdrop_path = data.get("backdrop_path")
    if backdrop_path and isinstance(backdrop_path, str):
        backdrop_path = backdrop_path.strip()
    else:
        backdrop_path = None

    overview = data.get("overview")
    if overview and isinstance(overview, str):
        overview = overview.strip()
    else:
        overview = None

    vote_average = data.get("vote_average")
    try:
        vote_average = round(float(vote_average), 1) if vote_average is not None else None
    except (ValueError, TypeError):
        vote_average = None

    pid = current_profile()
    if not pid and data.get("profile_id"):
        try:
            pid = int(data.get("profile_id"))
        except (ValueError, TypeError):
            pid = None
    prof = get_profile(pid) if pid else None

    req_id = f"req_{int(time.time())}_{secrets.token_hex(4)}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    season = data.get("season")
    try:
        season = int(season) if season is not None and str(season).strip() != "" else None
    except (ValueError, TypeError):
        season = None

    episode = data.get("episode")
    try:
        episode = int(episode) if episode is not None and str(episode).strip() != "" else None
    except (ValueError, TypeError):
        episode = None

    new_item = {
        "id": req_id,
        "title": title,
        "type": media_type,
        "year": year or None,
        "season": season,
        "episode": episode,
        "notes": notes or None,
        "tmdb_id": tmdb_id,
        "poster_path": poster_path,
        "backdrop_path": backdrop_path,
        "overview": overview,
        "vote_average": vote_average,
        "status": "pending",
        "profile_id": pid,
        "requested_by": prof["name"] if prof else (data.get("requested_by") or "CapsStream User"),
        "profile_avatar": prof.get("avatar", "🎬") if prof else (data.get("profile_avatar") or "🎬"),
        "custom_avatar_url": prof.get("custom_avatar_url", "") if prof else (data.get("custom_avatar_url") or ""),
        "profile_color": prof.get("color", "#e50914") if prof else (data.get("profile_color") or "#e50914"),
        "created_at": now_str,
        "updated_at": now_str
    }

    # Automatically check if this item is already in the local library
    matched = detect_media_in_library(new_item)
    if matched:
        new_item["status"] = "completed"
        new_item["auto_detected"] = True
        new_item["detected_media_id"] = matched["id"]
        new_item["detected_media_type"] = matched["type"]
        new_item["detected_tmdb_id"] = matched.get("tmdb_id")
        new_item["completed_at"] = now_str

    with _LOCK:
        items = _load_requests()
        # Add newest to the top
        items.insert(0, new_item)
        _save_requests(items)

    return jsonify({"ok": True, "request": new_item}), 201


@requests_bp.route("/api/requests/series-inventory", methods=["GET"])
def api_series_inventory():
    """Return existing season/episode breakdown for a series in the library."""
    _check_kids_guard()
    tmdb_id = request.args.get("tmdb_id")
    title = request.args.get("title")
    inventory = get_series_library_inventory(title=title, tmdb_id=tmdb_id)
    return jsonify({"ok": True, "inventory": inventory})


@requests_bp.route("/api/requests/sync-library", methods=["POST"])
def api_sync_library():
    """Trigger an auto-detection pass of all requests against the CapsStream library."""
    _check_kids_guard()
    items, detected_count = sync_requests_with_library()
    for item in items:
        p_id = item.get("profile_id")
        if p_id:
            p = get_profile(p_id)
            if p:
                if not item.get("requested_by") or item.get("requested_by") == "CapsStream User":
                    item["requested_by"] = p.get("name")
                if not item.get("profile_avatar") or item.get("profile_avatar") == "ph-user":
                    item["profile_avatar"] = p.get("avatar") or "🎬"
                if p.get("custom_avatar_url"):
                    item["custom_avatar_url"] = p.get("custom_avatar_url")
                if p.get("color"):
                    item["profile_color"] = p.get("color")
    return jsonify({
        "ok": True,
        "detected_count": detected_count,
        "requests": items
    })


@requests_bp.route("/api/requests/clear-completed", methods=["POST"])
def api_clear_completed():
    """DEV mode only: clear all completed/added requests."""
    _check_kids_guard()
    if not is_dev_mode():
        return jsonify({"error": "DEV mode required to clear completed requests"}), 403

    with _LOCK:
        items = _load_requests()
        initial_len = len(items)
        items = [item for item in items if item.get("status") != "completed"]
        removed_count = initial_len - len(items)
        _save_requests(items)

    return jsonify({"ok": True, "removed_count": removed_count})


@requests_bp.route("/api/requests/<req_id>", methods=["PATCH"])
def api_update_request(req_id):
    """Update request status or details."""
    _check_kids_guard()
    data = request.get_json(silent=True) or {}
    dev = is_dev_mode()

    with _LOCK:
        items = _load_requests()
        target = next((item for item in items if item.get("id") == req_id), None)
        if not target:
            return jsonify({"error": "Request not found"}), 404

        # Status update check
        if "status" in data:
            new_status = data["status"]
            if new_status not in ("pending", "completed"):
                return jsonify({"error": "Invalid status value"}), 400
            if not dev:
                return jsonify({"error": "Only developer mode can change fulfillment status"}), 403
            target["status"] = new_status

        # Editable fields (title, type, year, notes, TMDb metadata, season, episode)
        if dev or target.get("profile_id") == current_profile():
            if "title" in data and str(data["title"]).strip():
                target["title"] = str(data["title"]).strip()
            if "type" in data and data["type"] in ("Movie", "TV Show", "Anime"):
                target["type"] = data["type"]
            if "year" in data:
                target["year"] = str(data["year"]).strip()[:4] if data["year"] else None
            if "season" in data:
                try:
                    s_val = data["season"]
                    target["season"] = int(s_val) if s_val is not None and str(s_val).strip() != "" else None
                except (ValueError, TypeError):
                    target["season"] = None
            if "episode" in data:
                try:
                    ep_val = data["episode"]
                    target["episode"] = int(ep_val) if ep_val is not None and str(ep_val).strip() != "" else None
                except (ValueError, TypeError):
                    target["episode"] = None
            if "notes" in data:
                target["notes"] = str(data["notes"]).strip() if data["notes"] else None
            if "tmdb_id" in data:
                try:
                    target["tmdb_id"] = int(data["tmdb_id"]) if data["tmdb_id"] is not None else None
                except (ValueError, TypeError):
                    target["tmdb_id"] = None
            if "poster_path" in data:
                target["poster_path"] = str(data["poster_path"]).strip() if data["poster_path"] else None
            if "backdrop_path" in data:
                target["backdrop_path"] = str(data["backdrop_path"]).strip() if data["backdrop_path"] else None
            if "overview" in data:
                target["overview"] = str(data["overview"]).strip() if data["overview"] else None
            if "vote_average" in data:
                try:
                    target["vote_average"] = round(float(data["vote_average"]), 1) if data["vote_average"] is not None else None
                except (ValueError, TypeError):
                    target["vote_average"] = None

            # Re-check library in case season/title was edited
            matched = detect_media_in_library(target)
            if matched:
                target["detected_media_id"] = matched["id"]
                target["detected_media_type"] = matched["type"]
                target["detected_tmdb_id"] = matched.get("tmdb_id")
                if target.get("status") == "pending":
                    target["status"] = "completed"
                    target["auto_detected"] = True
                    target["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif target.get("auto_detected"):
                target["status"] = "pending"
                target["auto_detected"] = False
                target["detected_media_id"] = None
                target["detected_media_type"] = None
                target["detected_tmdb_id"] = None
                target["completed_at"] = None

        target["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_requests(items)

    return jsonify({"ok": True, "request": target})


@requests_bp.route("/api/requests/<req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    """Delete a request."""
    _check_kids_guard()
    dev = is_dev_mode()

    with _LOCK:
        items = _load_requests()
        target = next((item for item in items if item.get("id") == req_id), None)
        if not target:
            return jsonify({"error": "Request not found"}), 404

        # Uncle can delete pending requests; DEV mode can delete any
        if not dev and target.get("status") != "pending":
            return jsonify({"error": "Completed requests cannot be deleted in standard mode"}), 403

        items = [item for item in items if item.get("id") != req_id]
        _save_requests(items)

    return jsonify({"ok": True})

