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


def get_profile_recommendations(profile_id, limit=3, all_shows=None):
    """
    Find recently watched seeds (high-engagement: >= 50% watched or completed, or favorited) for profile_id,
    and find matching unique titles in the library based on shared genres and cast.
    Returns list of row dicts: [{"title": "Because you watched ...", "type": "row", "is_recommendation": True, "seed_id": ..., "seed_title": "...", "items": [...]}, ...]
    """
    import json
    from backend.db.media import get_unique_shows, enrich_mounted_list

    conn = get_conn()
    # High-engagement viewing: completed, watched >= 50%, or watched at least 20 minutes (1200s)
    recent_rows = conn.execute("""
        SELECT m.id, m.tmdb_id, m.title, m.type, m.genres, m.cast_json, m.rating, wp.updated_at
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND (
            wp.completed = 1
            OR (wp.duration > 0 AND (CAST(wp.position AS FLOAT) / wp.duration) >= 0.5)
            OR wp.position >= 1200
        )
        ORDER BY wp.updated_at DESC
        LIMIT 50
    """, (profile_id,)).fetchall()

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

    # If recent watch history has fewer seeds than requested limit, supplement with favorites
    if len(seed_list) < limit:
        fav_rows = conn.execute("""
            SELECT m.id, m.tmdb_id, m.title, m.type, m.genres, m.cast_json, m.rating, f.added_at as updated_at
            FROM favorites f
            JOIN media m ON m.id = f.media_id
            WHERE f.profile_id=?
            ORDER BY f.added_at DESC
            LIMIT 20
        """, (profile_id,)).fetchall()
        for r in fav_rows:
            d = dict(r)
            key = (d.get("tmdb_id") or d.get("title"), d.get("type"))
            if key not in seen_seeds:
                seen_seeds.add(key)
                seed_list.append(d)
            if len(seed_list) >= limit:
                break

    conn.close()

    if not seed_list:
        return []

    if all_shows is None:
        all_shows = enrich_mounted_list(get_unique_shows(None))

    if profile_id:
        try:
            from backend.db.profiles import get_profile
            prof = get_profile(profile_id)
            if prof and prof.get("is_kids"):
                from backend.kids_filter import filter_kids
                all_shows = filter_kids(all_shows)
        except Exception:
            pass

    recommendations = []
    already_recommended_ids = set()

    for seed in seed_list:
        seed_genres = [g.strip().lower() for g in (seed.get("genres") or "").split(",") if g.strip()]
        seed_cast = []
        if seed.get("cast_json"):
            try:
                c_data = json.loads(seed["cast_json"])
                seed_cast = [c.get("name", "").lower() for c in c_data[:5] if c.get("name")]
            except Exception:
                pass

        if not seed_genres and not seed_cast:
            continue

        scored_items = []
        seed_tmdb = seed.get("tmdb_id")
        seed_title = (seed.get("title") or "").strip().lower()

        for show in all_shows:
            show_id = show.get("id")
            if not show_id or show_id in already_recommended_ids:
                continue

            # Skip the seed itself
            if (seed_tmdb and show.get("tmdb_id") == seed_tmdb) or ((show.get("title") or "").strip().lower() == seed_title):
                continue

            show_genres = [g.strip().lower() for g in (show.get("genres") or "").split(",") if g.strip()]
            genre_overlap = len(set(seed_genres) & set(show_genres))

            actor_overlap = 0
            if seed_cast and show.get("cast_json"):
                try:
                    show_c_data = json.loads(show["cast_json"])
                    show_cast = [c.get("name", "").lower() for c in show_c_data[:5] if c.get("name")]
                    actor_overlap = len(set(seed_cast) & set(show_cast))
                except Exception:
                    pass

            type_match = 1.0 if show.get("type") == seed.get("type") else 0.0
            rating_boost = float(show.get("rating") or 0) * 0.15

            if genre_overlap > 0 or actor_overlap > 0:
                score = (genre_overlap * 3.0) + (actor_overlap * 4.0) + type_match + rating_boost
                scored_items.append((score, show))

        scored_items.sort(key=lambda x: x[0], reverse=True)
        items = [x[1] for x in scored_items[:16]]
        if len(items) >= 2:
            for it in items:
                if it.get("id"):
                    already_recommended_ids.add(it["id"])
            recommendations.append({
                "title": f"Because you watched {seed['title']}",
                "type": "recommendation",
                "is_recommendation": True,
                "seed_id": seed.get("id"),
                "seed_title": seed["title"],
                "seed_type": seed.get("type"),
                "items": items,
            })

    return recommendations


def get_similar_media(media_id, limit=16, profile_id=None):
    """
    Find titles in the user's library similar to media_id.
    Scores candidates by franchise connection, shared genres, lead actors,
    same media type, and era (decade).
    """
    import json
    from backend.db.media import get_media_by_id, get_unique_shows, enrich_mounted_list

    target = get_media_by_id(media_id)
    if not target:
        return []

    unique_shows = enrich_mounted_list(get_unique_shows(None))
    if not unique_shows:
        return []

    if profile_id:
        try:
            from backend.db.profiles import get_profile
            prof = get_profile(profile_id)
            if prof and prof.get("is_kids"):
                from backend.kids_filter import filter_kids
                unique_shows = filter_kids(unique_shows)
        except Exception:
            pass

    # Check franchise membership
    franchise_item_ids = set()
    try:
        from backend.franchises import get_media_franchise
        fr = get_media_franchise(target, unique_shows)
        if fr and fr.get("items"):
            franchise_item_ids = {i.get("id") for i in fr["items"] if i.get("id")}
    except Exception:
        pass

    target_genres = [g.strip().lower() for g in (target.get("genres") or "").split(",") if g.strip()]
    target_cast = []
    if target.get("cast_json"):
        try:
            c_data = json.loads(target["cast_json"])
            target_cast = [c.get("name", "").lower() for c in c_data[:6] if c.get("name")]
        except Exception:
            pass

    target_type = target.get("type")
    target_year = target.get("year")
    target_decade = (target_year // 10 * 10) if (target_year and target_year > 1900) else None
    target_tmdb = target.get("tmdb_id")
    target_title = (target.get("title") or "").strip().lower()

    scored = []
    for show in unique_shows:
        show_id = show.get("id")
        if not show_id or show_id == media_id:
            continue

        # Skip exact same show/movie
        if (target_tmdb and show.get("tmdb_id") == target_tmdb) or ((show.get("title") or "").strip().lower() == target_title):
            continue

        score = 0.0

        # Same franchise/universe collection (+10.0)
        if show_id in franchise_item_ids:
            score += 10.0

        # Shared genre overlap (+3.0 per matching genre)
        show_genres = [g.strip().lower() for g in (show.get("genres") or "").split(",") if g.strip()]
        genre_overlap = len(set(target_genres) & set(show_genres))
        score += genre_overlap * 3.0

        # Shared lead actors (+3.0 per actor)
        actor_overlap = 0
        if target_cast and show.get("cast_json"):
            try:
                show_c_data = json.loads(show["cast_json"])
                show_cast = [c.get("name", "").lower() for c in show_c_data[:6] if c.get("name")]
                actor_overlap = len(set(target_cast) & set(show_cast))
                score += actor_overlap * 3.0
            except Exception:
                pass

        # Same media type (+1.5)
        if show.get("type") == target_type:
            score += 1.5

        # Same era / decade (+1.0)
        show_year = show.get("year")
        if target_decade and show_year and (show_year // 10 * 10) == target_decade:
            score += 1.0

        # Rating quality boost (+0.1 * rating)
        score += float(show.get("rating") or 0) * 0.1

        # Must have at least a meaningful connection
        if (genre_overlap > 0 or actor_overlap > 0 or show_id in franchise_item_ids):
            scored.append((score, show))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:limit]]



