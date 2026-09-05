# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from .connection import get_conn
from .media import is_item_mounted, is_item_disabled, enrich_mounted_list

def can_edit_playlist(conn, playlist_id, profile_id):
    """Check if profile is creator of playlist or an admin."""
    row = conn.execute("SELECT profile_id FROM playlists WHERE id=?", (playlist_id,)).fetchone()
    if not row:
        return False
    if row["profile_id"] == profile_id:
        return True
    admin_row = conn.execute("SELECT is_admin FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return bool(admin_row and admin_row["is_admin"])


def get_playlists(profile_id):
    """Retrieve all playlists for a profile (including shared family playlists) with item count and sample posters."""
    conn = get_conn()
    admin_row = conn.execute("SELECT is_admin, is_kids FROM profiles WHERE id=?", (profile_id,)).fetchone()
    is_admin = bool(admin_row["is_admin"]) if admin_row else False

    rows = conn.execute("""
        SELECT p.*, pr.name as creator_name, pr.avatar as creator_avatar, pr.color as creator_color
        FROM playlists p
        LEFT JOIN profiles pr ON pr.id = p.profile_id
        WHERE p.profile_id=? OR p.is_shared=1
        ORDER BY p.updated_at DESC
    """, (profile_id,)).fetchall()

    result = []
    for row in rows:
        pl = dict(row)
        pl["is_shared"] = bool(pl.get("is_shared", 0))
        pl["can_edit"] = bool(pl.get("profile_id") == profile_id or is_admin)

        items = conn.execute("""
            SELECT pi.id as item_id, pi.position, m.id as media_id, m.title, m.poster_path, m.backdrop_path, m.type, m.certification, m.genres
            FROM playlist_items pi
            JOIN media m ON m.id = pi.media_id
            WHERE pi.playlist_id=?
            ORDER BY pi.position ASC
        """, (pl["id"],)).fetchall()
        pl["item_count"] = len(items)
        pl["item_ids"] = [i["media_id"] for i in items]
        pl["sample_posters"] = [i["poster_path"] for i in items if i["poster_path"]][:4]
        result.append(pl)
    conn.close()
    return result


def get_playlist(playlist_id, profile_id=None):
    """Retrieve a single playlist with its full ordered items and metadata."""
    conn = get_conn()
    row = conn.execute("""
        SELECT p.*, pr.name as creator_name, pr.avatar as creator_avatar, pr.color as creator_color
        FROM playlists p
        LEFT JOIN profiles pr ON pr.id = p.profile_id
        WHERE p.id=?
    """, (playlist_id,)).fetchone()

    if not row:
        conn.close()
        return None

    pl = dict(row)
    pl["is_shared"] = bool(pl.get("is_shared", 0))

    is_admin = False
    if profile_id is not None:
        admin_row = conn.execute("SELECT is_admin FROM profiles WHERE id=?", (profile_id,)).fetchone()
        is_admin = bool(admin_row["is_admin"]) if admin_row else False

        if pl["profile_id"] != profile_id and not is_admin and not pl["is_shared"]:
            conn.close()
            return None

    pl["can_edit"] = bool(profile_id is not None and (pl["profile_id"] == profile_id or is_admin))

    items = conn.execute("""
        SELECT pi.id as item_id, pi.position, pi.added_at,
               m.id, m.tmdb_id, m.title, m.original_title, m.type, m.year, m.overview,
               m.rating, m.poster_path, m.backdrop_path, m.duration,
               m.season as season_number, m.episode as episode_number, m.ep_title as episode_title,
               m.file_path, m.certification, m.genres
        FROM playlist_items pi
        JOIN media m ON m.id = pi.media_id
        WHERE pi.playlist_id=?
        ORDER BY pi.position ASC, pi.id ASC
    """, (pl["id"],)).fetchall()

    enriched_items = enrich_mounted_list([dict(i) for i in items])
    pl["items"] = enriched_items
    pl["item_ids"] = [i["id"] for i in enriched_items]
    pl["item_count"] = len(enriched_items)
    conn.close()
    return pl


def is_media_in_playlist(playlist_id, media_id):
    """Check if a media item is already present in a playlist."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM playlist_items WHERE playlist_id=? AND media_id=? LIMIT 1",
        (playlist_id, media_id)
    ).fetchone()
    conn.close()
    return row is not None


def create_playlist(profile_id, name, description="", is_shared=False):
    """Create a new playlist for a profile with optional family sharing."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO playlists (profile_id, name, description, is_shared) VALUES (?,?,?,?)",
        (profile_id, name.strip(), description.strip(), 1 if is_shared else 0)
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_playlist(playlist_id, profile_id, name=None, description=None, is_shared=None):
    """Update playlist name, description, and/or is_shared status."""
    conn = get_conn()
    if not can_edit_playlist(conn, playlist_id, profile_id):
        conn.close()
        return False

    fields = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())
    if is_shared is not None:
        fields.append("is_shared = ?")
        params.append(1 if is_shared else 0)

    params.append(playlist_id)
    conn.execute(
        f"UPDATE playlists SET {', '.join(fields)} WHERE id=?",
        params
    )
    conn.commit()
    conn.close()
    return True


def delete_playlist(playlist_id, profile_id):
    """Delete a playlist and its items if caller has permissions."""
    conn = get_conn()
    if not can_edit_playlist(conn, playlist_id, profile_id):
        conn.close()
        return False

    conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    conn.commit()
    conn.close()
    return True


def add_to_playlist(playlist_id, media_id, profile_id=None):
    """Append a media item to the end of a playlist."""
    conn = get_conn()
    if profile_id is not None and not can_edit_playlist(conn, playlist_id, profile_id):
        conn.close()
        return None

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


def remove_from_playlist(playlist_id, item_id, profile_id=None):
    """Remove an item from a playlist and re-index remaining positions."""
    conn = get_conn()
    if profile_id is not None and not can_edit_playlist(conn, playlist_id, profile_id):
        conn.close()
        return False

    conn.execute(
        "DELETE FROM playlist_items WHERE playlist_id=? AND id=?",
        (playlist_id, item_id)
    )
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
    return True


def reorder_playlist(playlist_id, item_ids, profile_id=None):
    """Reorder playlist items according to the given array of item_ids."""
    conn = get_conn()
    if profile_id is not None and not can_edit_playlist(conn, playlist_id, profile_id):
        conn.close()
        return False

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
    return True
