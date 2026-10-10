# -*- coding: utf-8 -*-
"""
bookmarks.py — Database queries and helpers for CapsStream Moments (scene bookmarks).
"""

import os
import sqlite3
from .connection import get_conn


def create_bookmark(profile_id, media_id, position, note="", category="general", color="#e50914", is_shared=False, thumb_path=""):
    """
    Create a new bookmark moment.
    Returns the newly created bookmark dictionary with profile info.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO bookmarks (profile_id, media_id, position, note, category, color, is_shared, thumb_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(profile_id),
        int(media_id),
        int(position),
        str(note or "").strip(),
        str(category or "general").strip().lower(),
        str(color or "#e50914").strip(),
        1 if is_shared else 0,
        str(thumb_path or "").strip()
    ))
    bookmark_id = c.lastrowid
    conn.commit()
    conn.close()
    return get_bookmark(bookmark_id)


def get_bookmark(bookmark_id):
    """Retrieve a single bookmark by ID including media and profile details."""
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*,
               p.name AS profile_name, p.avatar AS profile_avatar, p.color AS profile_color,
               m.title AS media_title, m.type AS media_type, m.season, m.episode,
               m.ep_title, m.year, m.poster_path, m.backdrop_path, m.duration AS media_duration
        FROM bookmarks b
        JOIN profiles p ON p.id = b.profile_id
        JOIN media m ON m.id = b.media_id
        WHERE b.id = ?
    """, (int(bookmark_id),)).fetchone()
    conn.close()
    if not row:
        return None
    res = dict(row)
    res["is_shared"] = bool(res.get("is_shared", 0))
    return res


def get_bookmarks_for_media(media_id, profile_id=None):
    """
    Retrieve all moments for a media item visible to a profile.
    Visible if bookmark.profile_id == profile_id OR is_shared == 1.
    If profile_id is None, returns all bookmarks for the media item.
    """
    conn = get_conn()
    if profile_id is not None:
        rows = conn.execute("""
            SELECT b.*,
                   p.name AS profile_name, p.avatar AS profile_avatar, p.color AS profile_color
            FROM bookmarks b
            JOIN profiles p ON p.id = b.profile_id
            WHERE b.media_id = ? AND (b.profile_id = ? OR b.is_shared = 1)
            ORDER BY b.position ASC
        """, (int(media_id), int(profile_id))).fetchall()
    else:
        rows = conn.execute("""
            SELECT b.*,
                   p.name AS profile_name, p.avatar AS profile_avatar, p.color AS profile_color
            FROM bookmarks b
            JOIN profiles p ON p.id = b.profile_id
            WHERE b.media_id = ?
            ORDER BY b.position ASC
        """, (int(media_id),)).fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        item["is_shared"] = bool(item.get("is_shared", 0))
        item["can_edit"] = bool(profile_id is None or item["profile_id"] == int(profile_id))
        result.append(item)
    return result


def get_bookmarks_for_profile(profile_id, category=None):
    """
    Retrieve all moments created by a profile (or shared with family) across the entire library.
    Optionally filter by category.
    """
    conn = get_conn()
    query = """
        SELECT b.*,
               p.name AS profile_name, p.avatar AS profile_avatar, p.color AS profile_color,
               m.title AS media_title, m.type AS media_type, m.season, m.episode,
               m.ep_title, m.year, m.poster_path, m.backdrop_path, m.duration AS media_duration
        FROM bookmarks b
        JOIN profiles p ON p.id = b.profile_id
        JOIN media m ON m.id = b.media_id
        WHERE (b.profile_id = ? OR b.is_shared = 1)
    """
    params = [int(profile_id)]
    if category and category.lower() != "all":
        query += " AND b.category = ?"
        params.append(category.lower().strip())

    query += " ORDER BY b.created_at DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        item["is_shared"] = bool(item.get("is_shared", 0))
        item["can_edit"] = bool(item["profile_id"] == int(profile_id))
        result.append(item)
    return result


def update_bookmark(bookmark_id, profile_id=None, note=None, category=None, color=None, is_shared=None):
    """
    Update a bookmark's note, category, color, or is_shared status.
    If profile_id is provided, verifies ownership or admin status before editing.
    """
    existing = get_bookmark(bookmark_id)
    if not existing:
        return None

    if profile_id is not None and existing["profile_id"] != int(profile_id):
        # Check if caller is admin
        conn = get_conn()
        admin_row = conn.execute("SELECT is_admin FROM profiles WHERE id=?", (int(profile_id),)).fetchone()
        conn.close()
        if not (admin_row and admin_row["is_admin"]):
            return None

    fields = []
    params = []
    if note is not None:
        fields.append("note = ?")
        params.append(str(note).strip())
    if category is not None:
        fields.append("category = ?")
        params.append(str(category).strip().lower())
    if color is not None:
        fields.append("color = ?")
        params.append(str(color).strip())
    if is_shared is not None:
        fields.append("is_shared = ?")
        params.append(1 if is_shared else 0)

    if not fields:
        return existing

    params.append(int(bookmark_id))
    conn = get_conn()
    conn.execute(f"UPDATE bookmarks SET {', '.join(fields)} WHERE id = ?", tuple(params))
    conn.commit()
    conn.close()
    return get_bookmark(bookmark_id)


def delete_bookmark(bookmark_id, profile_id=None):
    """
    Delete a bookmark.
    If profile_id is provided, verifies ownership or admin status.
    Returns True if deleted, False otherwise.
    """
    existing = get_bookmark(bookmark_id)
    if not existing:
        return False

    if profile_id is not None and existing["profile_id"] != int(profile_id):
        conn = get_conn()
        admin_row = conn.execute("SELECT is_admin FROM profiles WHERE id=?", (int(profile_id),)).fetchone()
        conn.close()
        if not (admin_row and admin_row["is_admin"]):
            return False

    # Delete physical thumbnail file if present
    if existing.get("thumb_path") and os.path.exists(existing["thumb_path"]):
        try:
            os.remove(existing["thumb_path"])
        except Exception:
            pass

    conn = get_conn()
    conn.execute("DELETE FROM bookmarks WHERE id = ?", (int(bookmark_id),))
    conn.commit()
    conn.close()
    return True
