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
    get_progress, save_progress, delete_progress, delete_watch_history, get_continue_watching,
    get_favorites, toggle_favorite, is_favorite,
    get_collections, create_collection, update_collection, update_smart_collection_rule, delete_collection,
    add_to_collection, remove_from_collection, get_progress_for_media_items,
    validate_smart_collection_rule,
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
                    delete_progress(pid, ep["id"], clear_history=True)
            delete_progress(pid, int(media_id), clear_history=True)
            if media.get("tmdb_id"):
                delete_watch_history(pid, tmdb_id=media.get("tmdb_id"), media_type=media.get("type"))
            elif media.get("title"):
                delete_watch_history(pid, title=media.get("title"), media_type=media.get("type"))
        else:
            delete_progress(pid, int(media_id), clear_history=True)
    elif tmdb_id:
        episodes = get_media_by_tmdb(int(tmdb_id), media_type)
        for ep in episodes:
            if ep.get("id"):
                delete_progress(pid, ep["id"], clear_history=True)
        delete_watch_history(pid, tmdb_id=int(tmdb_id), media_type=media_type)

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
    all_media = filter_for_profile(get_unique_shows(None))
    kids = active_is_kids()
    progress_by_id = get_progress_for_media_items(pid, all_media)
    from backend.video_probe import probe_video_resolution
    result = get_collections(pid, progress_by_id, probe_video_resolution, media_items=all_media)

    def _smart(cid, name, desc, items):
        return {"id": cid, "name": name, "description": desc, "smart": True, "items": items}

    unwatched = [m for m in all_media if progress_by_id.get(m.get("id")) is None]
    result.insert(0, _smart("smart-unwatched", "Unwatched", "Library titles you haven't started yet", unwatched[:20]))
    recent = get_recently_added(limit=20)
    top = get_top_rated(limit=20)
    if kids:
        recent = filter_for_profile(recent)
        top = filter_for_profile(top)
    result.insert(1, _smart("smart-recent", "Recently Added", "The newest additions to your library", recent))
    result.insert(2, _smart("smart-top", "Top Rated", "Highest rated titles in your library", top))

    universe_collections = get_universe_collections(all_media, min_count=2)
    result.extend(universe_collections)

    country_collections = get_country_collections(all_media, min_count=2)
    result.extend(country_collections)

    filtered = [{**col, "items": filter_for_profile(col.get("items"))} for col in result]
    result = [col for col in filtered if col["items"]] if kids else filtered

    return jsonify(result)


@library_bp.route("/api/collections", methods=["POST"])
def api_create_collection():
    pid = require_profile()
    data = request.json or {}
    name = str(data.get("name", "") or "").strip()
    desc = str(data.get("description", "") or "")
    if not name:
        return jsonify({"error": "Name required"}), 400
    if len(name) > 100 or len(desc) > 500:
        return jsonify({"error": "Name must be 100 characters or fewer and description 500 or fewer"}), 400
    rule = data.get("rule")
    try:
        cid = create_collection(pid, name, desc, rule=rule)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": cid, "name": name, "description": desc, "items": [], "smart": rule is not None, "rule": rule}), 201


@library_bp.route("/api/collections/<int:collection_id>", methods=["DELETE"])
def api_delete_collection(collection_id):
    pid = require_profile()
    delete_collection(collection_id, pid)
    return jsonify({"ok": True})


@library_bp.route("/api/collections/<int:collection_id>", methods=["PUT", "PATCH"])
def api_update_collection(collection_id):
    pid = require_profile()
    data = request.json or {}
    name = data.get("name")
    desc = data.get("description")
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 100):
        return jsonify({"error": "Name must be 1–100 characters"}), 400
    if desc is not None and (not isinstance(desc, str) or len(desc) > 500):
        return jsonify({"error": "Description must be 500 characters or fewer"}), 400
    kwargs = {}
    if "cover_id" in data:
        kwargs["cover_id"] = data["cover_id"]
    update_collection(collection_id, pid, name=name.strip() if isinstance(name, str) else name, description=desc, **kwargs)
    if "rule" in data:
        try:
            if not update_smart_collection_rule(collection_id, pid, data["rule"]):
                return jsonify({"error": "Collection not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "cover_id": data.get("cover_id")})


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


# ─── Cinematic Universes & Franchises ─────────────────────────────────────────

@library_bp.route("/api/universes", methods=["GET"])
def api_get_universes():
    from backend.db import get_all_media
    all_media = get_all_media()
    if active_is_kids():
        all_media = filter_for_profile(all_media)

    universes = get_universe_collections(all_media, min_count=1)
    results = []
    for u in universes:
        items = u.get("items") or []
        results.append({
            "id": u["id"],
            "name": u["name"],
            "description": u.get("description", ""),
            "icon": u.get("icon", "ph ph-sparkle"),
            "poster_path": u.get("poster_path") or (items[0].get("poster_path") if items else None),
            "backdrop_path": u.get("backdrop_path") or (items[0].get("backdrop_path") if items else None),
            "has_timeline": bool(u.get("has_timeline")),
            "item_count": len(items),
            "preview_items": items[:4],
        })
    return jsonify(results)


@library_bp.route("/api/universes/<universe_id>", methods=["GET"])
def api_get_universe(universe_id):
    from backend.db import get_all_media
    all_media = get_all_media()
    if active_is_kids():
        all_media = filter_for_profile(all_media)

    universes = get_universe_collections(all_media, min_count=1)
    target = next((u for u in universes if u["id"] == universe_id), None)
    if not target:
        return jsonify({"error": "Universe not found"}), 404

    items = target.get("items") or []
    for idx, it in enumerate(items, 1):
        it["sequence_number"] = idx

    timeline_items = target.get("timeline_items") or []
    for idx, it in enumerate(timeline_items, 1):
        it["sequence_number"] = idx

    return jsonify({
        "id": target["id"],
        "name": target["name"],
        "description": target.get("description", ""),
        "icon": target.get("icon", "ph ph-sparkle"),
        "poster_path": target.get("poster_path") or (items[0].get("poster_path") if items else None),
        "backdrop_path": target.get("backdrop_path") or (items[0].get("backdrop_path") if items else None),
        "has_timeline": bool(target.get("has_timeline")),
        "item_count": len(items),
        "items": items,
        "timeline_items": timeline_items,
    })


# ─── Regional / Country Hubs ──────────────────────────────────────────────────

@library_bp.route("/api/regional/countries", methods=["GET"])
def api_get_regional_countries():
    from backend.db import get_all_media
    all_media = get_all_media()
    if active_is_kids():
        all_media = filter_for_profile(all_media)

    country_collections = get_country_collections(all_media, min_count=1)
    results = []
    for c in country_collections:
        items = c.get("items") or []
        results.append({
            "id": c["id"],
            "country_code": c.get("country_code"),
            "country_name": c.get("country_name") or c.get("name"),
            "flag": c.get("flag"),
            "flag_svg": c.get("flag_svg"),
            "description": c.get("description", ""),
            "item_count": len(items),
            "movie_count": c.get("movie_count", sum(1 for i in items if (i.get("type") or "movie") == "movie")),
            "series_count": c.get("series_count", sum(1 for i in items if (i.get("type") or "") in ("series", "anime"))),
            "poster_path": items[0].get("poster_path") if items else None,
            "backdrop_path": items[0].get("backdrop_path") if items else None,
            "preview_items": items[:4],
        })
    return jsonify(results)


@library_bp.route("/api/regional/countries/<country_code>", methods=["GET"])
def api_get_regional_country(country_code):
    from backend.db import get_all_media
    all_media = get_all_media()
    if active_is_kids():
        all_media = filter_for_profile(all_media)

    code_upper = country_code.upper().strip()
    country_collections = get_country_collections(all_media, min_count=1)
    target = next((c for c in country_collections if (c.get("country_code") or "").upper() == code_upper or c.get("id") == f"country-{code_upper.lower()}"), None)
    if not target:
        return jsonify({"error": "Country hub not found"}), 404

    items = target.get("items") or []
    return jsonify({
        "id": target["id"],
        "country_code": target.get("country_code", code_upper),
        "country_name": target.get("country_name") or target.get("name"),
        "flag": target.get("flag"),
        "flag_svg": target.get("flag_svg"),
        "description": target.get("description", ""),
        "item_count": len(items),
        "movie_count": target.get("movie_count", sum(1 for i in items if (i.get("type") or "movie") == "movie")),
        "series_count": target.get("series_count", sum(1 for i in items if (i.get("type") or "") in ("series", "anime"))),
        "poster_path": items[0].get("poster_path") if items else None,
        "backdrop_path": items[0].get("backdrop_path") if items else None,
        "items": items,
    })
