# -*- coding: utf-8 -*-
"""
routes/media.py — Home, library, media detail, search, genres, kids overrides.
"""
import json
import threading

from flask import Blueprint, jsonify, request, current_app

from .middleware import (
    current_profile, active_is_kids, kids_guard_media,
    filter_for_profile, require_admin,
)
from backend.db import (
    get_all_media, get_media_by_id, get_media_by_tmdb, get_best_media_source,
    get_media_quality_options, search_media as db_search_media, get_unique_shows,
    get_recently_added, get_top_rated, get_by_genre, get_all_genres,
    get_random_pick, get_continue_watching, get_profile_recommendations, get_progress, is_favorite,
    get_unmatched, upsert_media,
    delete_media_by_id, delete_media_by_tmdb, delete_media_by_title_and_type,
)

media_bp = Blueprint("media", __name__)

# Shared home-page cache (bust on scan/library writes)
_HOME_CACHE: dict = {"data": None, "ts": 0.0}
_HOME_CACHE_TTL = 30.0


def bust_home_cache():
    """Invalidate /api/home cache. Called from scan/library write endpoints."""
    _HOME_CACHE["data"] = None
    _HOME_CACHE["ts"] = 0.0


def _merge_season_episodes(tmdb_id, s_num, local_map, pid, fallback_backdrop=None, show_title=None):
    from backend.matcher import fetch_season_episodes
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
                ep["still_path"] = meta.get("still_path") or ep.get("backdrop_path") or fallback_backdrop
                if meta.get("runtime"):
                    ep["duration"] = meta.get("runtime") * 60
                if pid and ep.get("id"):
                    ep_progress = get_progress(pid, ep["id"])
                    ep["progress"] = dict(ep_progress) if ep_progress else None
                merged_list.append(ep)
            else:
                merged_list.append({
                    "id": None, "is_local": False,
                    "season": s_num, "episode": ep_num,
                    "ep_title": meta.get("name"), "overview": meta.get("overview"),
                    "still_path": meta.get("still_path") or fallback_backdrop,
                    "duration": (meta.get("runtime") * 60) if meta.get("runtime") else None,
                    "title": show_title or (local_map.get((s_num, ep_num), {}).get("title")),
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
    return sorted(merged_list, key=lambda e: e.get("episode") or 0)


# ─── Anime Detection job state ─────────────────────────────────────────────────

_ANIME_DETECT = {
    "running": False, "done": False, "total": 0,
    "processed": 0, "reclassified": 0, "error": None,
}


def _is_anime_detail(detail):
    if not detail:
        return False
    genres = ", ".join(g.get("name", "") for g in detail.get("genres", []))
    origin = detail.get("origin_country") or []
    return "Animation" in genres and (
        detail.get("original_language") == "ja" or "JP" in origin
    )


def _detect_anime_job():
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
            except Exception as e:
                print(f"[AnimeDetect] Error for tmdb_id {tmdb_id}: {e}")
            finally:
                _ANIME_DETECT["processed"] = idx + 1
        _ANIME_DETECT["reclassified"] = reclassified
    except Exception as e:
        _ANIME_DETECT["error"] = str(e)
    finally:
        _ANIME_DETECT["running"] = False
        _ANIME_DETECT["done"] = True


# ─── Routes ───────────────────────────────────────────────────────────────────

@media_bp.route("/api/home", methods=["GET"])
def api_home():
    import time
    pid = current_profile()
    kids = active_is_kids()

    now = time.time()
    cache_valid = (
        _HOME_CACHE["data"] is not None
        and now - _HOME_CACHE["ts"] < _HOME_CACHE_TTL
    )

    if cache_valid:
        rows = list(_HOME_CACHE["data"])
    else:
        rows = []
        all_shows = get_unique_shows(None)
        by_type = {"movie": [], "series": [], "anime": []}
        for show in all_shows:
            t = show.get("type")
            if t in by_type:
                by_type[t].append(show)

        recent = get_recently_added(limit=20)
        if recent:
            rows.append({"title": "Recently Added", "type": "row", "items": recent})
        top = get_top_rated(limit=20)
        if top:
            rows.append({"title": "Top Rated", "type": "row", "items": top})
        movies = sorted(by_type["movie"], key=lambda m: m.get("rating") or 0, reverse=True)[:20]
        if movies:
            rows.append({"title": "Movies", "type": "row", "items": movies})
        series = by_type["series"]
        if series:
            rows.append({"title": "Series", "type": "row", "items": series[:20]})
        anime = by_type["anime"]
        if anime:
            rows.append({"title": "Anime", "type": "row", "items": anime[:20]})
        random_picks = get_random_pick(limit=10)
        if random_picks:
            rows.append({"title": "Discover Something New", "type": "row", "items": random_picks})

        genres = get_all_genres()
        priority_genres = ["Action", "Comedy", "Drama", "Horror", "Sci-Fi", "Science Fiction",
                           "Romance", "Thriller", "Animation", "Documentary", "Fantasy"]
        shown_genres = [g for g in priority_genres if g in genres]
        if not shown_genres:
            shown_genres = genres[:5]
        for genre in shown_genres[:4]:
            items = get_by_genre(genre, limit=15)
            if items:
                rows.append({"title": genre, "type": "row", "items": items})

        _HOME_CACHE["data"] = rows
        _HOME_CACHE["ts"] = now

    final_rows = []
    if pid:
        cw = get_continue_watching(pid, limit=15)
        if cw:
            final_rows.append({"title": "Continue Watching", "type": "continue", "items": cw})
        recs = get_profile_recommendations(pid, limit=2)
    else:
        recs = []

    rec_idx = 0
    for i, r in enumerate(rows):
        final_rows.append(r)
        # Place 1st recommendation row after Recently Added / 1st catalog row
        if rec_idx == 0 and recs and (r.get("title") == "Recently Added" or i == 0):
            final_rows.append(recs[0])
            rec_idx += 1
        # Place 2nd recommendation row after Top Rated or 3rd catalog row
        elif rec_idx == 1 and len(recs) > 1 and (r.get("title") == "Top Rated" or i == 2):
            final_rows.append(recs[1])
            rec_idx += 1

    while rec_idx < len(recs):
        final_rows.append(recs[rec_idx])
        rec_idx += 1

    if kids:
        filtered_rows = []
        for row in final_rows:
            items = filter_for_profile(row.get("items"))
            if items:
                filtered_rows.append({**row, "items": items})
        final_rows = filtered_rows

    return jsonify(final_rows)


@media_bp.route("/api/library", methods=["GET"])
def api_library():
    media_type = request.args.get("type")
    rows = get_unique_shows(media_type if media_type else None)
    if active_is_kids():
        rows = filter_for_profile(rows)
    return jsonify(rows)


@media_bp.route("/api/library/delete", methods=["POST"])
def api_library_delete():
    if active_is_kids():
        return jsonify({"error": "Not available in Kids Mode"}), 403

    data = request.json or {}
    tmdb_id = data.get("tmdb_id")
    mtype = data.get("type")
    media_id = data.get("media_id")
    title = data.get("title")

    try:
        if tmdb_id is not None and int(tmdb_id) <= 0:
            tmdb_id = None
    except (ValueError, TypeError):
        tmdb_id = None

    row = None
    if media_id:
        try:
            row = get_media_by_id(int(media_id))
        except (ValueError, TypeError):
            row = None

    if row:
        if not tmdb_id:
            tmdb_id = row.get("tmdb_id")
        if not mtype:
            mtype = row.get("type")
        if not title:
            title = row.get("title")

    removed = 0
    if tmdb_id and mtype:
        removed = delete_media_by_tmdb(int(tmdb_id), mtype)
    elif title and mtype:
        removed = delete_media_by_title_and_type(title, mtype)
    elif media_id:
        removed = delete_media_by_id(int(media_id))
    else:
        return jsonify({"error": "media_id, or tmdb_id + type, or title + type required"}), 400

    bust_home_cache()
    return jsonify({"ok": True, "removed": removed})


@media_bp.route("/api/library/detect-anime", methods=["POST"])
def api_detect_anime_start():
    if _ANIME_DETECT["running"]:
        return jsonify({"started": False, "message": "Detection is already running"})
    _ANIME_DETECT.update({
        "running": True, "done": False, "total": 0,
        "processed": 0, "reclassified": 0, "error": None,
    })
    threading.Thread(target=_detect_anime_job, daemon=True).start()
    return jsonify({"started": True})


@media_bp.route("/api/library/detect-anime/status", methods=["GET"])
def api_detect_anime_status():
    return jsonify(dict(_ANIME_DETECT))


@media_bp.route("/api/media/<int:media_id>", methods=["GET"])
def api_media_detail(media_id):
    media = get_best_media_source(media_id)
    if not media:
        return jsonify({"error": "Not found"}), 404

    guard = kids_guard_media(media, deep=True)
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

    pid = current_profile()
    if pid:
        progress = get_progress(pid, media_id)
        media["progress"] = dict(progress) if progress else None
        media["is_favorite"] = is_favorite(pid, media_id)
    else:
        media["progress"] = None
        media["is_favorite"] = False

    if media["type"] in ("series", "anime") and media.get("tmdb_id"):
        all_eps = get_media_by_tmdb(media["tmdb_id"], media["type"])
        from backend.matcher import fetch_season_episodes, get_show_seasons_list
        local_map = {}
        for ep_row in all_eps:
            ep = dict(ep_row)
            s_int = int(ep.get("season") or 1)
            ep_int = int(ep.get("episode") or 1)
            local_map[(s_int, ep_int)] = ep

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
            seasons[str(s_num)] = _merge_season_episodes(
                media["tmdb_id"], s_num, local_map, pid,
                fallback_backdrop=media.get("backdrop_path"),
                show_title=media.get("title")
            )
        media["seasons"] = seasons

    if media.get("cast_json"):
        try:
            media["cast"] = json.loads(media["cast_json"])
        except Exception:
            media["cast"] = []
    else:
        media["cast"] = []

    from backend.subtitles import get_all_subtitles
    media["subtitles"] = get_all_subtitles(media["file_path"], media_id)
    media["quality_options"] = get_media_quality_options(media_id)

    from backend.audio_probe import probe_audio_tracks
    media["audio_tracks"] = probe_audio_tracks(media["file_path"])
    media["has_multi_audio"] = len(media["audio_tracks"]) > 1

    return jsonify(media)


@media_bp.route("/api/media/<int:media_id>/trailer", methods=["GET"])
def api_media_trailer(media_id):
    media = get_media_by_id(media_id)
    if not media:
        return jsonify({"error": "Media not found"}), 404
    if active_is_kids():
        return jsonify({"error": "Trailers are disabled in Kids Mode"}), 403
    from backend.matcher import get_media_trailer
    trailer = get_media_trailer(media.get("tmdb_id"), media.get("type", "movie"))
    if not trailer:
        return jsonify({"error": "Trailer not available for this title"}), 404
    return jsonify(trailer)


@media_bp.route("/api/kids-overrides", methods=["GET"])
def api_get_kids_overrides():
    if active_is_kids():
        return jsonify({"error": "Not available in Kids Mode"}), 403
    from backend.db import list_kids_overrides
    return jsonify(list_kids_overrides())


@media_bp.route("/api/kids-overrides", methods=["POST"])
def api_set_kids_override():
    data = request.json or {}
    action = data.get("action")
    if action not in ("allow", "block"):
        return jsonify({"error": "action must be 'allow' or 'block'"}), 400
    tmdb_id = data.get("tmdb_id")
    title = None
    if not tmdb_id and data.get("media_id"):
        media = get_media_by_id(int(data["media_id"]))
        if not media:
            return jsonify({"error": "Media not found"}), 404
        tmdb_id = media.get("tmdb_id")
        title = media.get("title")
    if not tmdb_id:
        return jsonify({"error": "tmdb_id or media_id required"}), 400
    from backend.db import set_kids_override
    set_kids_override(tmdb_id, action, title or None)
    return jsonify({"ok": True, "tmdb_id": tmdb_id, "action": action})


@media_bp.route("/api/kids-overrides/<int:tmdb_id>", methods=["DELETE"])
def api_remove_kids_override(tmdb_id):
    if active_is_kids():
        return jsonify({"error": "Not available in Kids Mode"}), 403
    from backend.db import remove_kids_override
    remove_kids_override(tmdb_id)
    return jsonify({"ok": True})


@media_bp.route("/api/show/<int:tmdb_id>", methods=["GET"])
def api_show_detail(tmdb_id):
    media_type = request.args.get("type", "series")
    episodes = get_media_by_tmdb(tmdb_id, media_type)
    if not episodes:
        single = get_media_by_id(tmdb_id)
        if single:
            if single.get("tmdb_id"):
                episodes = get_media_by_tmdb(single["tmdb_id"], single.get("type", media_type))
            else:
                episodes = [single]
    if not episodes:
        return jsonify({"error": "Not found"}), 404

    show = dict(episodes[0])
    show["is_mounted"] = any(ep.get("is_mounted", False) for ep in episodes)
    for f in ["season", "episode", "ep_title", "file_path", "file_size", "duration"]:
        show.pop(f, None)

    show_tmdb_id = show.get("tmdb_id")
    if not show.get("status") and show_tmdb_id:
        from backend.matcher import get_show_status
        show["status"] = get_show_status(show_tmdb_id, show.get("type", media_type))

    if show.get("cast_json"):
        try:
            show["cast"] = json.loads(show["cast_json"])
        except Exception:
            show["cast"] = []

    pid = current_profile()
    from backend.matcher import fetch_season_episodes

    local_map = {}
    for ep_row in episodes:
        ep = dict(ep_row)
        s_int = int(ep.get("season") or 1)
        ep_int = int(ep.get("episode") or 1)
        key = (s_int, ep_int)
        if key not in local_map:
            local_map[key] = ep
        else:
            curr = local_map[key]
            curr_mounted = bool(curr.get("is_mounted"))
            ep_mounted = bool(ep.get("is_mounted"))
            if (not curr_mounted and ep_mounted) or (curr_mounted == ep_mounted and (ep.get("file_size") or 0) > (curr.get("file_size") or 0)):
                local_map[key] = ep

    seasons = {}
    show_tmdb_id = show.get("tmdb_id")
    s_nums = set(k[0] for k in local_map.keys())
    if not s_nums:
        s_nums = {1}

    for s_num in s_nums:
        seasons[str(s_num)] = _merge_season_episodes(
            show_tmdb_id, s_num, local_map, pid,
            fallback_backdrop=show.get("backdrop_path"),
            show_title=show.get("title")
        )

    # Missing seasons (placeholder)
    expected_seasons = 0
    if show_tmdb_id:
        from backend.matcher import _load_cache, _tmdb_get
        for cache_type in (media_type, "series", "anime"):
            cached_show = _load_cache(cache_type, show_tmdb_id)
            if cached_show and cached_show.get("seasons"):
                try:
                    expected_seasons = int(cached_show["seasons"])
                    break
                except (TypeError, ValueError):
                    continue
        if expected_seasons <= 0:
            detail = _tmdb_get(f"tv/{show_tmdb_id}", {"language": "en-US"})
            if detail:
                try:
                    expected_seasons = int(detail.get("number_of_seasons") or 0)
                except (TypeError, ValueError):
                    expected_seasons = 0

    for s_num in range(1, expected_seasons + 1):
        if s_num in s_nums:
            continue
        tmdb_eps = fetch_season_episodes(show_tmdb_id, s_num) if show_tmdb_id else []
        if not tmdb_eps:
            continue
        placeholder_list = []
        for meta in tmdb_eps:
            placeholder_list.append({
                "id": None, "is_local": False,
                "season": s_num, "episode": meta.get("episode_number"),
                "ep_title": meta.get("name"), "overview": meta.get("overview"),
                "still_path": meta.get("still_path") or show.get("backdrop_path"),
                "duration": (meta.get("runtime") * 60) if meta.get("runtime") else None,
                "title": show.get("title"), "progress": None,
            })
        seasons[str(s_num)] = sorted(placeholder_list, key=lambda e: e.get("episode") or 0)

    show["seasons"] = seasons
    if pid and episodes:
        show["is_favorite"] = is_favorite(pid, episodes[0]["id"])
    else:
        show["is_favorite"] = False

    if episodes:
        first_local = next((ep for ep in episodes if ep.get("file_path")), None)
        if first_local:
            from backend.audio_probe import probe_audio_tracks
            show["audio_tracks"] = probe_audio_tracks(first_local["file_path"])
            show["has_multi_audio"] = len(show.get("audio_tracks", [])) > 1

    return jsonify(show)


@media_bp.route("/api/search", methods=["GET"])
def api_search():
    q = request.args.get("q", "").strip()
    media_type = request.args.get("type", "all")
    genre = request.args.get("genre", "all")
    sort_by = request.args.get("sort", "relevance")
    results = db_search_media(query=q, media_type=media_type, genre=genre, sort_by=sort_by)
    if active_is_kids():
        results = filter_for_profile(results)
    return jsonify(results)


@media_bp.route("/api/genres", methods=["GET"])
def api_genres():
    return jsonify(get_all_genres())


@media_bp.route("/api/unmatched", methods=["GET"])
def api_unmatched():
    require_admin()
    return jsonify(get_unmatched())


@media_bp.route("/api/tmdb/search", methods=["GET"])
def api_tmdb_search():
    query = request.args.get("query", "").strip()
    mtype = request.args.get("type", "movie")
    year = request.args.get("year", "").strip()
    if not query:
        return jsonify([])
    from backend.matcher import search_tmdb
    results = search_tmdb(query, media_type=mtype, year=year or None)
    return jsonify(results)


@media_bp.route("/api/override", methods=["POST"])
def api_override():
    require_admin()
    data = request.json or {}
    media_id = data.get("media_id")
    old_tmdb_id = data.get("old_tmdb_id")
    tmdb_id = data.get("tmdb_id")
    mtype = data.get("type", "movie")

    if not tmdb_id:
        return jsonify({"error": "tmdb_id is required"}), 400

    from backend.matcher import override_match, fetch_season_episodes
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
        if mtype in ("series", "anime") and season_num is not None and ep_num is not None:
            if season_num not in season_cache:
                season_cache[season_num] = fetch_season_episodes(tmdb_id, season_num)
            ep_list = season_cache[season_num] or []
            ep_info = next((e for e in ep_list if e.get("episode_number") == ep_num), None)
            if ep_info and ep_info.get("name"):
                ep_title = ep_info.get("name")
        updated_dict = {
            **row_dict, **meta,
            "id": row_dict["id"], "file_path": row_dict["file_path"],
            "type": mtype, "tmdb_id": tmdb_id,
            "season": row_dict.get("season"), "episode": row_dict.get("episode"),
            "ep_title": ep_title, "tmdb_matched": 1, "manually_overridden": 1
        }
        upsert_media(updated_dict)
        updated_count += 1
    conn.close()
    return jsonify({"ok": True, "updated": updated_count})


@media_bp.route("/api/recache", methods=["POST"])
def api_recache_media():
    import glob as _glob
    data = request.json or {}
    tmdb_id = data.get("tmdb_id")
    mtype = data.get("type", "movie")

    if not tmdb_id:
        return jsonify({"error": "This title has no TMDb match. Use 'Fix Match' first."}), 400

    from backend.db import get_conn
    from backend.matcher import (
        METADATA_DIR, match_movie_by_id, match_show_by_id, fetch_imdb_id,
    )

    removed = 0
    delete_paths = [
        __import__("os").path.join(METADATA_DIR, f"{mtype}_{tmdb_id}.json"),
        __import__("os").path.join(METADATA_DIR, f"external_ids_{mtype}_{tmdb_id}.json"),
    ]
    delete_paths.extend(_glob.glob(__import__("os").path.join(METADATA_DIR, f"season_{tmdb_id}_*.json")))
    for p in delete_paths:
        if __import__("os").path.isfile(p):
            try:
                __import__("os").remove(p)
                removed += 1
            except OSError:
                pass

    conn = get_conn()
    rows = conn.execute("SELECT * FROM media WHERE tmdb_id=? AND type=?", (tmdb_id, mtype)).fetchall()
    if not rows:
        conn.close()
        return jsonify({"error": "No library rows found for this title"}), 404

    import os
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
