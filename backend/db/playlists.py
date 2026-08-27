# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from .connection import get_conn
from .media import is_item_mounted, is_item_disabled, enrich_mounted_list

def get_playlists(profile_id):
    """Retrieve all playlists for a profile with item count and sample posters."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM playlists WHERE profile_id=? ORDER BY updated_at DESC",
        (profile_id,)
    ).fetchall()
    result = []
    for row in rows:
        pl = dict(row)
        items = conn.execute("""
            SELECT pi.id as item_id, pi.position, m.id as media_id, m.title, m.poster_path, m.backdrop_path, m.type
            FROM playlist_items pi
            JOIN media m ON m.id = pi.media_id
            WHERE pi.playlist_id=?
            ORDER BY pi.position ASC
        """, (pl["id"],)).fetchall()
        pl["item_count"] = len(items)
        pl["sample_posters"] = [i["poster_path"] for i in items if i["poster_path"]][:4]
        result.append(pl)
    conn.close()
    return result


def get_playlist(playlist_id, profile_id=None):
    """Retrieve a single playlist with its full ordered items and metadata."""
    conn = get_conn()
    if profile_id is not None:
        row = conn.execute(
            "SELECT * FROM playlists WHERE id=? AND profile_id=?",
            (playlist_id, profile_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM playlists WHERE id=?",
            (playlist_id,)
        ).fetchone()

    if not row:
        conn.close()
        return None

    pl = dict(row)
    items = conn.execute("""
        SELECT pi.id as item_id, pi.position, pi.added_at,
               m.id, m.tmdb_id, m.title, m.original_title, m.type, m.year, m.overview,
               m.rating, m.poster_path, m.backdrop_path, m.duration,
               m.season as season_number, m.episode as episode_number, m.ep_title as episode_title,
               m.file_path
        FROM playlist_items pi
        JOIN media m ON m.id = pi.media_id
        WHERE pi.playlist_id=?
        ORDER BY pi.position ASC, pi.id ASC
    """, (pl["id"],)).fetchall()

    enriched_items = enrich_mounted_list([dict(i) for i in items])
    pl["items"] = enriched_items
    pl["item_count"] = len(enriched_items)
    conn.close()
    return pl


def create_playlist(profile_id, name, description=""):
    """Create a new playlist for a profile."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO playlists (profile_id, name, description) VALUES (?,?,?)",
        (profile_id, name.strip(), description.strip())
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_playlist(playlist_id, profile_id, name=None, description=None):
    """Update playlist name and/or description."""
    conn = get_conn()
    fields = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())
    params.extend([playlist_id, profile_id])
    conn.execute(
        f"UPDATE playlists SET {', '.join(fields)} WHERE id=? AND profile_id=?",
        params
    )
    conn.commit()
    conn.close()


def delete_playlist(playlist_id, profile_id):
    """Delete a playlist and its items."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM playlists WHERE id=? AND profile_id=?",
        (playlist_id, profile_id)
    )
    conn.commit()
    conn.close()


def add_to_playlist(playlist_id, media_id):
    """Append a media item to the end of a playlist."""
    conn = get_conn()
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_items WHERE playlist_id=?",
        (playlist_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO playlist_items (playlist_id, media_id, position) VALUES (?,?,?)",
        (playlist_id, media_id, max_pos)
    )
    conn.execute(
        "UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id=?",
        (playlist_id,)
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def remove_from_playlist(playlist_id, item_id):
    """Remove an item from a playlist and re-index remaining positions."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM playlist_items WHERE playlist_id=? AND id=?",
        (playlist_id, item_id)
    )
    # Re-normalize positions
    rows = conn.execute(
        "SELECT id FROM playlist_items WHERE playlist_id=? ORDER BY position ASC, id ASC",
        (playlist_id,)
    ).fetchall()
    for idx, r in enumerate(rows):
        conn.execute("UPDATE playlist_items SET position=? WHERE id=?", (idx, r["id"]))
    conn.execute(
        "UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id=?",
        (playlist_id,)
    )
    conn.commit()
    conn.close()


def reorder_playlist(playlist_id, item_ids):
    """Reorder playlist items according to the given array of item_ids."""
    conn = get_conn()
    for pos, iid in enumerate(item_ids):
        conn.execute(
            "UPDATE playlist_items SET position=? WHERE playlist_id=? AND id=?",
            (pos, playlist_id, iid)
        )
    conn.execute(
        "UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id=?",
        (playlist_id,)
    )
    conn.commit()
    conn.close()
