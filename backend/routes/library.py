# -*- coding: utf-8 -*-
"""
routes/library.py — Watch progress, favorites, collections, playlists.
"""
from flask import Blueprint, jsonify, request

from .middleware import (
    current_profile, require_profile, active_is_kids, filter_for_profile,
    kids_guard_media,
)
from backend.db import (
    get_media_by_id, get_media_by_tmdb, get_unique_shows, get_recently_added, get_top_rated,
    get_progress, save_progress, delete_progress, get_continue_watching,
    get_favorites, toggle_favorite, is_favorite,
    get_collections, create_collection, delete_collection,
    add_to_collection, remove_from_collection,
    get_playlists, get_playlist, create_playlist, update_playlist,
    delete_playlist, add_to_playlist, remove_from_playlist, reorder_playlist,
    is_media_in_playlist,
)
from backend.franchises import get_universe_collections
from backend.regional import get_country_collections

library_bp = Blueprint("library", __name__)


import time

_LAST_ACHIEVEMENT_CHECK = {}
ACHIEVEMENT_CHECK_INTERVAL = 30.0  # Throttle full achievement evaluations during frequent playback heartbeats

# ─── Watch Progress ────────────────────────────────────────────────────────────

@library_bp.route("/api/progress", methods=["POST"])
def api_save_progress():
    pid = require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    position = data.get("position", 0)
    duration = data.get("duration", 0)
    completed = data.get("completed", False)
    check_achievements = data.get("check_achievements", False)

    if not media_id:
        return jsonify({"error": "media_id required"}), 400

    save_progress(pid, media_id, position, duration, completed)
    
    unlocked_items = []
    now = time.time()
    if completed or check_achievements or (now - _LAST_ACHIEVEMENT_CHECK.get(pid, 0.0) >= ACHIEVEMENT_CHECK_INTERVAL):
        _LAST_ACHIEVEMENT_CHECK[pid] = now
        from backend.db import check_and_unlock_achievements, get_profile_catalog
        newly_unlocked_ids = check_and_unlock_achievements(pid)
        if newly_unlocked_ids:
            catalog = get_profile_catalog(pid)
            unlocked_items = [a for a in catalog if a["id"] in newly_unlocked_ids]

    return jsonify({"ok": True, "unlocked_achievements": unlocked_items})


@library_bp.route("/api/progress/<int:media_id>", methods=["GET"])
def api_get_progress(media_id):
    pid = require_profile()
    progress = get_progress(pid, media_id)
    return jsonify(dict(progress) if progress else {})


@library_bp.route("/api/progress/<int:media_id>", methods=["DELETE"])
def api_delete_progress(media_id):
    pid = require_profile()
    delete_progress(pid, media_id)
    return jsonify({"ok": True})


@library_bp.route("/api/progress/mark-watched", methods=["POST"])
def api_mark_watched():
    pid = require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    tmdb_id = data.get("tmdb_id")
    media_type = data.get("type")

    if not media_id and not tmdb_id:
        return jsonify({"error": "media_id or tmdb_id required"}), 400

    if media_id:
        media = get_media_by_id(int(media_id))
        if not media:
            return jsonify({"error": "Not found"}), 404

        guard = kids_guard_media(media, deep=True)
        if guard:
            return guard

        if media.get("type") in ("series", "anime"):
            # Mark all episodes of the series as watched
            episodes = get_media_by_tmdb(media.get("tmdb_id"), media.get("type")) if media.get("tmdb_id") else []
            for ep in episodes:
                dur = int(ep.get("duration") or 0)
                if ep.get("id"):
                    save_progress(pid, ep["id"], dur, dur, True)
            duration = int(media.get("duration") or 0)
            save_progress(pid, media.get("id"), duration, duration, True)
        else:
            duration = int(media.get("duration") or 0)
            save_progress(pid, media.get("id"), duration, duration, True)
    elif tmdb_id:
        episodes = get_media_by_tmdb(int(tmdb_id), media_type)
        if not episodes:
            return jsonify({"error": "Not found"}), 404
        for ep in episodes:
            dur = int(ep.get("duration") or 0)
            if ep.get("id"):
                save_progress(pid, ep["id"], dur, dur, True)

    return jsonify({"ok": True, "completed": True})


@library_bp.route("/api/progress/mark-unwatched", methods=["POST"])
def api_mark_unwatched():
    pid = require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    tmdb_id = data.get("tmdb_id")
    media_type = data.get("type")

    if not media_id and not tmdb_id:
        return jsonify({"error": "media_id or tmdb_id required"}), 400

    if media_id:
        media = get_media_by_id(int(media_id))
        if media and media.get("type") in ("series", "anime"):
            episodes = get_media_by_tmdb(media.get("tmdb_id"), media.get("type")) if media.get("tmdb_id") else []
            for ep in episodes:
                if ep.get("id"):
                    delete_progress(pid, ep["id"])
            delete_progress(pid, int(media_id))
        else:
            delete_progress(pid, int(media_id))
    elif tmdb_id:
        episodes = get_media_by_tmdb(int(tmdb_id), media_type)
        for ep in episodes:
            if ep.get("id"):
                delete_progress(pid, ep["id"])

    return jsonify({"ok": True, "completed": False})


# ─── Favorites ─────────────────────────────────────────────────────────────────

@library_bp.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    pid = require_profile()
    favs = get_favorites(pid)
    if active_is_kids():
        favs = filter_for_profile(favs)
    return jsonify(favs)


@library_bp.route("/api/favorites/toggle", methods=["POST"])
@library_bp.route("/api/favorites/<int:media_id>", methods=["POST"])
def api_toggle_favorite(media_id=None):
    pid = require_profile()
    if media_id is None:
        data = request.json or {}
        media_id = data.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id is required"}), 400
    is_fav = toggle_favorite(pid, media_id)
    return jsonify({"is_favorite": is_fav})


# ─── Collections ──────────────────────────────────────────────────────────────

@library_bp.route("/api/collections", methods=["GET"])
def api_get_collections():
    pid = require_profile()
    result = get_collections(pid)
    all_media = get_unique_shows(None)
    kids = active_is_kids()
    if kids:
        all_media = filter_for_profile(all_media)

    def _smart(cid, name, desc, items):
        return {"id": cid, "name": name, "description": desc, "smart": True, "items": items}

    unwatched = [m for m in all_media if not get_progress(pid, m.get("id"))]
    result.insert(0, _smart("smart-unwatched", "Unwatched", "Library titles you haven't started yet", unwatched[:20]))
    result.insert(1, _smart("smart-recent", "Recently Added", "The newest additions to your library", get_recently_added(limit=20)))
    result.insert(2, _smart("smart-top", "Top Rated", "Highest rated titles in your library", get_top_rated(limit=20)))

    universe_collections = get_universe_collections(all_media, min_count=2)
    result.extend(universe_collections)

    country_collections = get_country_collections(all_media, min_count=2)
    result.extend(country_collections)

    if kids:
        filtered = []
        for col in result:
            items = filter_for_profile(col.get("items"))
            if items:
                filtered.append({**col, "items": items})
        result = filtered

    return jsonify(result)


@library_bp.route("/api/collections", methods=["POST"])
def api_create_collection():
    pid = require_profile()
    data = request.json or {}
    name = data.get("name", "").strip()
    desc = data.get("description", "")
    if not name:
        return jsonify({"error": "Name required"}), 400
    cid = create_collection(pid, name, desc)
    return jsonify({"id": cid, "name": name, "description": desc, "items": []}), 201


@library_bp.route("/api/collections/<int:collection_id>", methods=["DELETE"])
def api_delete_collection(collection_id):
    pid = require_profile()
    delete_collection(collection_id, pid)
    return jsonify({"ok": True})


@library_bp.route("/api/collections/<int:collection_id>/items", methods=["POST"])
def api_add_to_collection(collection_id):
    pid = require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id required"}), 400
    add_to_collection(collection_id, media_id)
    return jsonify({"ok": True})


@library_bp.route("/api/collections/<int:collection_id>/items/<int:media_id>", methods=["DELETE"])
def api_remove_from_collection(collection_id, media_id):
    pid = require_profile()
    remove_from_collection(collection_id, media_id)
    return jsonify({"ok": True})


@library_bp.route("/api/collections/convert-to-playlist", methods=["POST"])
def api_convert_collection_to_playlist():
    pid = require_profile()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    desc = (data.get("description") or "").strip()
    is_shared = bool(data.get("is_shared", False))
    include_all_episodes = bool(data.get("include_all_episodes", False))
    raw_items = data.get("items") or []

    if not name:
        return jsonify({"error": "Playlist name is required"}), 400

    if not raw_items:
        return jsonify({"error": "No items provided to convert"}), 400

    if active_is_kids():
        raw_items = filter_for_profile(raw_items)
        if not raw_items:
            return jsonify({"error": "No eligible titles found for this profile"}), 400

    pl_id = create_playlist(pid, name, desc, is_shared=is_shared)

    media_ids_to_add = []
    for it in raw_items:
        item_type = it.get("type", "movie")
        tmdb_id = it.get("tmdb_id")
        mid = it.get("id")

        if item_type in ("series", "anime") and tmdb_id:
            eps = get_media_by_tmdb(tmdb_id, item_type)
            if eps:
                sorted_eps = sorted(
                    eps,
                    key=lambda e: (int(e.get("season") or 1), int(e.get("episode") or 1))
                )
                if include_all_episodes:
                    for ep in sorted_eps:
                        if ep.get("id"):
                            media_ids_to_add.append(ep["id"])
                else:
                    first_ep = sorted_eps[0]
                    if first_ep.get("id"):
                        media_ids_to_add.append(first_ep["id"])
            elif mid:
                media_ids_to_add.append(mid)
        elif mid:
            media_ids_to_add.append(mid)

    for m_id in media_ids_to_add:
        try:
            add_to_playlist(pl_id, int(m_id), profile_id=pid)
        except Exception:
            pass

    pl = get_playlist(pl_id, pid)
    return jsonify(pl), 201


# ─── Playlists ─────────────────────────────────────────────────────────────────

@library_bp.route("/api/playlists", methods=["GET"])
def api_get_playlists():
    pid = require_profile()
    return jsonify(get_playlists(pid))


@library_bp.route("/api/playlists", methods=["POST"])
def api_create_playlist():
    pid = require_profile()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    desc = (data.get("description") or "").strip()
    is_shared = bool(data.get("is_shared", False))
    if not name:
        return jsonify({"error": "Playlist name is required"}), 400
    pl_id = create_playlist(pid, name, desc, is_shared=is_shared)
    pl = get_playlist(pl_id, pid)
    return jsonify(pl), 201


@library_bp.route("/api/playlists/<int:playlist_id>", methods=["GET"])
def api_get_playlist(playlist_id):
    pid = require_profile()
    pl = get_playlist(playlist_id, pid)
    if not pl:
        return jsonify({"error": "Playlist not found"}), 404
    if active_is_kids():
        pl["items"] = filter_for_profile(pl.get("items", []))
        pl["item_count"] = len(pl["items"])
    return jsonify(pl)


@library_bp.route("/api/playlists/<int:playlist_id>", methods=["PUT"])
def api_update_playlist(playlist_id):
    pid = require_profile()
    data = request.json or {}
    name = data.get("name")
    desc = data.get("description")
    is_shared = data.get("is_shared")
    ok = update_playlist(playlist_id, pid, name=name, description=desc, is_shared=is_shared)
    if not ok:
        return jsonify({"error": "Permission denied"}), 403
    pl = get_playlist(playlist_id, pid)
    return jsonify(pl)


@library_bp.route("/api/playlists/<int:playlist_id>", methods=["DELETE"])
def api_delete_playlist(playlist_id):
    pid = require_profile()
    ok = delete_playlist(playlist_id, pid)
    if not ok:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"ok": True})


@library_bp.route("/api/playlists/<int:playlist_id>/items", methods=["POST"])
def api_add_to_playlist(playlist_id):
    pid = require_profile()
    data = request.json or {}
    media_id = data.get("media_id")
    if not media_id:
        return jsonify({"error": "media_id is required"}), 400
    mid = int(media_id)
    was_already = is_media_in_playlist(playlist_id, mid)
    item_id = add_to_playlist(playlist_id, mid, profile_id=pid)
    if item_id is None:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"ok": True, "item_id": item_id, "already_in_playlist": was_already})


@library_bp.route("/api/playlists/<int:playlist_id>/items/<int:item_id>", methods=["DELETE"])
def api_remove_from_playlist(playlist_id, item_id):
    pid = require_profile()
    ok = remove_from_playlist(playlist_id, item_id, profile_id=pid)
    if not ok:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"ok": True})


@library_bp.route("/api/playlists/<int:playlist_id>/reorder", methods=["POST"])
def api_reorder_playlist(playlist_id):
    pid = require_profile()
    data = request.json or {}
    item_ids = data.get("item_ids", [])
    if not isinstance(item_ids, list):
        return jsonify({"error": "item_ids array is required"}), 400
    ok = reorder_playlist(playlist_id, [int(i) for i in item_ids], profile_id=pid)
    if not ok:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"ok": True})
