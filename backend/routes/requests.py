# -*- coding: utf-8 -*-
"""
backend/routes/requests.py — Hybrid Online & Drive-Based Media Requests API.

Supports both offline drive exchanges and cross-network online synchronization via Supabase.
- If the root DEV file exists, the instance is Desktop 1 (server / developer side):
  it receives requests from all clients, auto-detects additions against the local media library,
  updates fulfillment statuses (pending, in_progress, completed, rejected), and attaches admin notes.
- If DEV is absent, the instance is Desktop 2 (requester client):
  it generates a persistent client UUID (data/client_id), scopes its requests, and only sees its
  own requests and server responses.
"""
import os
import json
import time
import secrets
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request, abort

import re
from backend.utils.paths import BASE_DIR, get_client_id
from backend.utils.version import is_dev_mode
from backend.utils.supabase_client import (
    is_supabase_configured,
    fetch_online_requests,
    upsert_online_request,
    update_online_request,
    delete_online_request
)
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

                if prev_status in ("pending", "in_progress"):
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


def sync_online_requests():
    """
    Bi-directional sync between local data/requests.json and Supabase.
    - Desktop 1 (DEV): pulls all requests from Supabase, detects local library matches,
      pushes status updates back to Supabase, and updates local cache.
    - Desktop 2 (Client): pulls only requests for its client_id, updates local cache,
      and pushes any offline-created requests to Supabase.
    Returns (requests_to_display, detected_count, online_synced_bool).
    """
    dev = is_dev_mode()
    my_client_id = get_client_id()
    online_available = is_supabase_configured()

    with _LOCK:
        local_items = _load_requests()
        # Backwards compatibility: ensure every local item has a client_id
        for item in local_items:
            if not item.get("client_id"):
                item["client_id"] = my_client_id

        items_by_id = {item["id"]: item for item in local_items if item.get("id")}
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detected_count = 0

        if online_available:
            try:
                # Desktop 1 (DEV) queries all requests; Desktop 2 queries only its own
                target_cid = None if dev else my_client_id
                remote_items = fetch_online_requests(client_id=target_cid)

                for r_item in remote_items:
                    rid = r_item.get("id")
                    if not rid:
                        continue
                    if rid in items_by_id:
                        # Merge remote fields over local (remote is source of truth for status/notes)
                        items_by_id[rid].update(r_item)
                    else:
                        items_by_id[rid] = r_item

                # Desktop 2 pushes any local requests that haven't reached Supabase yet
                if not dev:
                    remote_ids = {r.get("id") for r in remote_items if r.get("id")}
                    for item in local_items:
                        iid = item.get("id")
                        if iid and iid not in remote_ids and item.get("client_id") == my_client_id:
                            upsert_online_request(item)
            except Exception as e:
                print(f"[Requests] Supabase sync error: {e}")

        # If Desktop 1 (DEV), perform library detection against local media DB
        if dev:
            for req in items_by_id.values():
                matched = detect_media_in_library(req)
                if matched:
                    prev_status = req.get("status")
                    req["detected_media_id"] = matched["id"]
                    req["detected_media_type"] = matched["type"]
                    req["detected_tmdb_id"] = matched.get("tmdb_id")

                    if prev_status in ("pending", "in_progress"):
                        req["status"] = "completed"
                        req["auto_detected"] = True
                        req["completed_at"] = now_str
                        req["updated_at"] = now_str
                        detected_count += 1
                        if online_available:
                            try:
                                update_online_request(req["id"], {
                                    "status": "completed",
                                    "detected_media_id": matched["id"],
                                    "detected_media_type": matched["type"],
                                    "detected_tmdb_id": matched.get("tmdb_id"),
                                    "completed_at": now_str,
                                    "updated_at": now_str
                                })
                            except Exception as e:
                                print(f"[Requests] Failed to push auto-detection to Supabase: {e}")
                elif req.get("auto_detected"):
                    req["status"] = "pending"
                    req["auto_detected"] = False
                    req["detected_media_id"] = None
                    req["detected_media_type"] = None
                    req["detected_tmdb_id"] = None
                    req["completed_at"] = None
                    req["updated_at"] = now_str
                    if online_available:
                        try:
                            update_online_request(req["id"], {
                                "status": "pending",
                                "detected_media_id": None,
                                "detected_media_type": None,
                                "detected_tmdb_id": None,
                                "completed_at": None,
                                "updated_at": now_str
                            })
                        except Exception as e:
                            print(f"[Requests] Failed to push revert to Supabase: {e}")

        # Sort all items newest first and save to disk
        all_sorted = sorted(
            items_by_id.values(),
            key=lambda x: str(x.get("created_at") or ""),
            reverse=True
        )
        _save_requests(all_sorted)

        # Scoping: Desktop 2 sees ONLY its own requests; Desktop 1 (DEV) sees all
        if not dev:
            display_items = [it for it in all_sorted if it.get("client_id") == my_client_id]
        else:
            display_items = all_sorted

        return display_items, detected_count, online_available


def _enrich_item_profile(item):
    """Fill in missing profile name and avatar fields for UI presentation."""
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


def _check_kids_guard():
    """Kids profiles are blocked from accessing or submitting requests."""
    pid = current_profile()
    if pid:
        prof = get_profile(pid)
        if prof and prof.get("is_kids"):
            abort(403, description="Media requests are not accessible in Kids mode.")


@requests_bp.route("/api/requests", methods=["GET"])
def api_get_requests():
    """
    Fetch requests. Desktop 1 (DEV) sees all requests; Desktop 2 sees only its own requests.
    Automatically performs online sync if Supabase is configured.
    """
    _check_kids_guard()
    items, _, online_synced = sync_online_requests()
    for item in items:
        _enrich_item_profile(item)

    return jsonify({
        "requests": items,
        "dev_mode": is_dev_mode(),
        "online_synced": online_synced,
        "client_id": get_client_id()
    })


@requests_bp.route("/api/requests", methods=["POST"])
def api_create_request():
    """Submit a new media request to local data/requests.json and push to Supabase."""
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

    has_digital_release = data.get("has_digital_release")
    digital_release_date = data.get("digital_release_date")
    digital_status_label = data.get("digital_status_label")

    # If tmdb_id is present and digital status not passed in request body, detect via TMDb
    if tmdb_id and has_digital_release is None:
        try:
            from backend.matcher import get_tmdb_digital_release_status
            m_lookup = "tv" if media_type in ("TV Show", "Anime") else "movie"
            d_status = get_tmdb_digital_release_status(tmdb_id, media_type=m_lookup, season=season, episode=episode)
            has_digital_release = d_status.get("has_digital_release", True)
            digital_release_date = d_status.get("digital_release_date")
            digital_status_label = d_status.get("digital_status_label")
        except Exception as e:
            print(f"[Requests] Digital status detection failed: {e}")

    my_client_id = get_client_id()
    new_item = {
        "id": req_id,
        "client_id": my_client_id,
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
        "has_digital_release": has_digital_release,
        "digital_release_date": digital_release_date,
        "digital_status_label": digital_status_label,
        "status": "pending",
        "admin_note": None,
        "profile_id": pid,
        "requested_by": prof["name"] if prof else (data.get("requested_by") or "CapsStream User"),
        "profile_avatar": prof.get("avatar", "🎬") if prof else (data.get("profile_avatar") or "🎬"),
        "custom_avatar_url": prof.get("custom_avatar_url", "") if prof else (data.get("custom_avatar_url") or ""),
        "profile_color": prof.get("color", "#e50914") if prof else (data.get("profile_color") or "#e50914"),
        "created_at": now_str,
        "updated_at": now_str
    }

    # If Desktop 1 (DEV), check if already in local library
    if is_dev_mode():
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
        items.insert(0, new_item)
        _save_requests(items)

    # Push to Supabase if configured
    if is_supabase_configured():
        try:
            upsert_online_request(new_item)
        except Exception as e:
            print(f"[Requests] Failed to push new request to Supabase: {e}")

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
        _enrich_item_profile(item)
    return jsonify({
        "ok": True,
        "detected_count": detected_count,
        "requests": items
    })


@requests_bp.route("/api/requests/sync-online", methods=["POST"])
def api_sync_online():
    """Trigger online synchronization pass with Supabase."""
    _check_kids_guard()
    items, detected_count, online_synced = sync_online_requests()
    for item in items:
        _enrich_item_profile(item)
    return jsonify({
        "ok": True,
        "online_synced": online_synced,
        "detected_count": detected_count,
        "requests": items,
        "dev_mode": is_dev_mode()
    })


@requests_bp.route("/api/requests/clear-completed", methods=["POST"])
def api_clear_completed():
    """DEV mode only: clear all completed/added requests."""
    _check_kids_guard()
    if not is_dev_mode():
        return jsonify({"error": "DEV mode required to clear completed requests"}), 403

    with _LOCK:
        items = _load_requests()
        completed_ids = [item.get("id") for item in items if item.get("status") == "completed"]
        initial_len = len(items)
        items = [item for item in items if item.get("status") != "completed"]
        removed_count = initial_len - len(items)
        _save_requests(items)

    if is_supabase_configured():
        for cid in completed_ids:
            try:
                delete_online_request(cid)
            except Exception as e:
                print(f"[Requests] Error deleting completed request {cid} from Supabase: {e}")

    return jsonify({"ok": True, "removed_count": removed_count})


@requests_bp.route("/api/requests/<req_id>", methods=["PATCH"])
def api_update_request(req_id):
    """Update request status, admin note, or user editable details."""
    _check_kids_guard()
    data = request.get_json(silent=True) or {}
    dev = is_dev_mode()
    my_client_id = get_client_id()

    with _LOCK:
        items = _load_requests()
        target = next((item for item in items if item.get("id") == req_id), None)
        if not target:
            return jsonify({"error": "Request not found"}), 404

        # Non-dev clients can only modify their own requests
        if not dev and target.get("client_id") != my_client_id and target.get("profile_id") != current_profile():
            return jsonify({"error": "Unauthorized to modify this request"}), 403

        # Status update check
        if "status" in data:
            new_status = data["status"]
            if new_status not in ("pending", "in_progress", "completed", "rejected"):
                return jsonify({"error": "Invalid status value"}), 400
            if not dev:
                return jsonify({"error": "Only developer mode can change fulfillment status"}), 403
            target["status"] = new_status
            if new_status == "completed" and not target.get("completed_at"):
                target["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Admin note update check (DEV mode only)
        if "admin_note" in data:
            if not dev:
                return jsonify({"error": "Only developer mode can update admin response notes"}), 403
            target["admin_note"] = str(data["admin_note"]).strip() if data["admin_note"] else None

        # User editable fields
        if dev or target.get("client_id") == my_client_id or target.get("profile_id") == current_profile():
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
            if "has_digital_release" in data:
                target["has_digital_release"] = data["has_digital_release"]
            if "digital_release_date" in data:
                target["digital_release_date"] = data["digital_release_date"]
            if "digital_status_label" in data:
                target["digital_status_label"] = data["digital_status_label"]

            # Re-check library in DEV mode if title or seasons changed
            if dev:
                matched = detect_media_in_library(target)
                if matched:
                    target["detected_media_id"] = matched["id"]
                    target["detected_media_type"] = matched["type"]
                    target["detected_tmdb_id"] = matched.get("tmdb_id")
                    if target.get("status") in ("pending", "in_progress"):
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

    # Push update to Supabase
    if is_supabase_configured():
        try:
            update_online_request(
                req_id,
                target,
                client_id=None if dev else my_client_id
            )
        except Exception as e:
            print(f"[Requests] Error updating request in Supabase: {e}")

    return jsonify({"ok": True, "request": target})


@requests_bp.route("/api/requests/<req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    """Delete a request."""
    _check_kids_guard()
    dev = is_dev_mode()
    my_client_id = get_client_id()

    with _LOCK:
        items = _load_requests()
        target = next((item for item in items if item.get("id") == req_id), None)
        if not target:
            return jsonify({"error": "Request not found"}), 404

        # Non-dev clients can only delete their own pending requests
        if not dev:
            if target.get("client_id") != my_client_id and target.get("profile_id") != current_profile():
                return jsonify({"error": "Unauthorized to delete this request"}), 403
            if target.get("status") != "pending":
                return jsonify({"error": "Only pending requests can be deleted in standard mode"}), 403

        items = [item for item in items if item.get("id") != req_id]
        _save_requests(items)

    if is_supabase_configured():
        try:
            delete_online_request(req_id, client_id=None if dev else my_client_id)
        except Exception as e:
            print(f"[Requests] Error deleting request from Supabase: {e}")

    return jsonify({"ok": True})


# Background poller for Desktop 1 (DEV mode)
_BACKGROUND_SYNC_RUNNING = False

def start_requests_sync_worker():
    """Start background sync poller if in DEV mode (Desktop 1)."""
    global _BACKGROUND_SYNC_RUNNING
    if _BACKGROUND_SYNC_RUNNING:
        return
    _BACKGROUND_SYNC_RUNNING = True

    def _worker():
        while True:
            time.sleep(300)  # Check every 5 minutes
            try:
                if is_dev_mode() and is_supabase_configured():
                    sync_online_requests()
            except Exception as e:
                print(f"[RequestsSyncWorker] Background sync error: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="RequestsOnlineSyncThread")
    t.start()


# Trigger background worker on startup
start_requests_sync_worker()
