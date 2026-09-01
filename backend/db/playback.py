# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from .connection import get_conn
from .media import is_item_mounted, is_item_disabled, get_media_by_id, get_all_sources_for_media, enrich_mounted_list

def get_progress(profile_id, media_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM watch_progress WHERE profile_id=? AND media_id=?",
        (profile_id, media_id)
    ).fetchone()
    if not row:
        media = get_media_by_id(media_id)
        if media:
            sources = get_all_sources_for_media(media)
            for s in sources:
                if s.get("id") and s["id"] != media_id:
                    alt_row = conn.execute(
                        "SELECT * FROM watch_progress WHERE profile_id=? AND media_id=?",
                        (profile_id, s["id"])
                    ).fetchone()
                    if alt_row:
                        row = alt_row
                        break
    conn.close()
    return dict(row) if row else None


def save_progress(profile_id, media_id, position, duration=0, completed=False):
    conn = get_conn()
    media = get_media_by_id(media_id)
    sources = get_all_sources_for_media(media) if media else []
    target_ids = {s["id"] for s in sources if s.get("id")} | {media_id}

    for mid in target_ids:
        conn.execute("""
            INSERT INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at)
            VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(profile_id, media_id) DO UPDATE SET
                position=excluded.position,
                duration=excluded.duration,
                completed=excluded.completed,
                updated_at=CURRENT_TIMESTAMP
        """, (profile_id, mid, position, duration, 1 if completed else 0))
    conn.commit()
    conn.close()


def delete_progress(profile_id, media_id):
    conn = get_conn()
    media = get_media_by_id(media_id)
    sources = get_all_sources_for_media(media) if media else []
    target_ids = {s["id"] for s in sources if s.get("id")} | {media_id}

    for mid in target_ids:
        conn.execute(
            "DELETE FROM watch_progress WHERE profile_id=? AND media_id=?",
            (profile_id, mid)
        )
    conn.commit()
    conn.close()


def get_continue_watching(profile_id, limit=20):
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.*, wp.position, wp.duration, wp.completed, wp.updated_at as last_watched
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND wp.completed=0 AND wp.position > 5
        ORDER BY wp.updated_at DESC
    """, (profile_id,)).fetchall()
    conn.close()

    items = enrich_mounted_list([dict(r) for r in rows])
    deduped = {}
    for it in items:
        # Group by tmdb_id + type + season + episode (or title + type + season + episode)
        key = (it.get("tmdb_id") or it.get("title"), it.get("type"), it.get("season"), it.get("episode"))
        if key not in deduped:
            deduped[key] = it
        else:
            curr = deduped[key]
            # Prefer mounted copy, then larger file size (higher quality)
            curr_mounted = bool(curr.get("is_mounted"))
            it_mounted = bool(it.get("is_mounted"))
            if (not curr_mounted and it_mounted) or (curr_mounted == it_mounted and (it.get("file_size") or 0) > (curr.get("file_size") or 0)):
                deduped[key] = it

    results = list(deduped.values())[:limit]
    try:
        from backend.matcher import fetch_season_episodes
        for it in results:
            if it.get("type") in ("series", "anime") and it.get("tmdb_id") and it.get("season") is not None and it.get("episode") is not None:
                try:
                    s_num = int(it["season"] or 1)
                    e_num = int(it["episode"] or 1)
                    eps = fetch_season_episodes(it["tmdb_id"], s_num)
                    for ep in eps:
                        if ep.get("episode_number") == e_num:
                            if ep.get("still_path"):
                                it["still_path"] = ep["still_path"]
                            if ep.get("name") and (not it.get("ep_title") or it.get("ep_title") == it.get("title")):
                                it["ep_title"] = ep["name"]
                            break
                except Exception:
                    pass
    except Exception:
        pass

    return results


def get_profile_recommendations(profile_id, limit=2):
    """
    Find recently watched seeds (in-progress or completed) for profile_id,
    and find matching unique titles in the library based on shared genres and cast.
    Returns list of row dicts: [{"title": "Because you watched ...", "type": "row", "is_recommendation": True, "seed_title": "...", "items": [...]}, ...]
    """
    import json
    from backend.db.media import get_unique_shows, enrich_mounted_list

    conn = get_conn()
    recent_rows = conn.execute("""
        SELECT m.id, m.tmdb_id, m.title, m.type, m.genres, m.cast_json, wp.updated_at
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND wp.position > 15
        ORDER BY wp.updated_at DESC
        LIMIT 40
    """, (profile_id,)).fetchall()
    conn.close()

    if not recent_rows:
        return []

    seen_seeds = set()
    seed_list = []
    for r in recent_rows:
        d = dict(r)
        key = (d.get("tmdb_id") or d.get("title"), d.get("type"))
        if key not in seen_seeds:
            seen_seeds.add(key)
            seed_list.append(d)
        if len(seed_list) >= limit:
            break

    if not seed_list:
        return []

    all_shows = enrich_mounted_list(get_unique_shows(None))
    recommendations = []

    for seed in seed_list:
        seed_genres = [g.strip().lower() for g in (seed.get("genres") or "").split(",") if g.strip()]
        seed_cast = []
        if seed.get("cast_json"):
            try:
                c_data = json.loads(seed["cast_json"])
                seed_cast = [c.get("name", "").lower() for c in c_data if c.get("name")]
            except Exception:
                pass

        if not seed_genres and not seed_cast:
            continue

        scored_items = []
        for show in all_shows:
            # Skip the seed itself
            if (show.get("tmdb_id") and show.get("tmdb_id") == seed.get("tmdb_id")) or (show.get("title") == seed.get("title")):
                continue

            show_genres = [g.strip().lower() for g in (show.get("genres") or "").split(",") if g.strip()]
            genre_overlap = len(set(seed_genres) & set(show_genres))

            actor_overlap = 0
            if seed_cast and show.get("cast_json"):
                try:
                    show_c_data = json.loads(show["cast_json"])
                    show_cast = [c.get("name", "").lower() for c in show_c_data if c.get("name")]
                    actor_overlap = len(set(seed_cast) & set(show_cast))
                except Exception:
                    pass

            score = (genre_overlap * 2.5) + (actor_overlap * 3.5) + (float(show.get("rating") or 0) * 0.1)
            if genre_overlap > 0 or actor_overlap > 0:
                scored_items.append((score, show))

        scored_items.sort(key=lambda x: x[0], reverse=True)
        items = [x[1] for x in scored_items[:15]]
        if len(items) >= 2:
            recommendations.append({
                "title": f"Because you watched {seed['title']}",
                "type": "row",
                "is_recommendation": True,
                "seed_title": seed["title"],
                "items": items,
            })

    return recommendations


