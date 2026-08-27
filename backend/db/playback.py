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

    return list(deduped.values())[:limit]


