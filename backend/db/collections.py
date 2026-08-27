# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from .connection import get_conn
from .media import is_item_mounted, is_item_disabled, enrich_mounted_list

def get_favorites(profile_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.*, f.added_at as fav_added
        FROM favorites f
        JOIN media m ON m.id = f.media_id
        WHERE f.profile_id=?
        ORDER BY f.added_at DESC
    """, (profile_id,)).fetchall()
    conn.close()
    return enrich_mounted_list([dict(r) for r in rows])


def toggle_favorite(profile_id, media_id):
    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM favorites WHERE profile_id=? AND media_id=?",
        (profile_id, media_id)
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM favorites WHERE profile_id=? AND media_id=?",
            (profile_id, media_id)
        )
        is_fav = False
    else:
        conn.execute(
            "INSERT INTO favorites (profile_id, media_id) VALUES (?,?)",
            (profile_id, media_id)
        )
        is_fav = True
    conn.commit()
    conn.close()
    return is_fav


def is_favorite(profile_id, media_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM favorites WHERE profile_id=? AND media_id=?",
        (profile_id, media_id)
    ).fetchone()
    conn.close()
    return row is not None


# ─── Collections Queries ──────────────────────────────────────────────────────

def get_collections(profile_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM collections WHERE profile_id=? ORDER BY created_at DESC",
        (profile_id,)
    ).fetchall()
    result = []
    for row in rows:
        col = dict(row)
        items = conn.execute("""
            SELECT m.* FROM collection_items ci
            JOIN media m ON m.id = ci.media_id
            WHERE ci.collection_id=?
            ORDER BY ci.sort_order
        """, (col["id"],)).fetchall()
        col["items"] = enrich_mounted_list([dict(i) for i in items])
        result.append(col)
    conn.close()
    return result


def create_collection(profile_id, name, description=""):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO collections (profile_id, name, description) VALUES (?,?,?)",
        (profile_id, name, description)
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def delete_collection(collection_id, profile_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM collections WHERE id=? AND profile_id=?",
        (collection_id, profile_id)
    )
    conn.commit()
    conn.close()


def add_to_collection(collection_id, media_id):
    conn = get_conn()
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order),0)+1 FROM collection_items WHERE collection_id=?",
        (collection_id,)
    ).fetchone()[0]
    try:
        conn.execute(
            "INSERT INTO collection_items (collection_id, media_id, sort_order) VALUES (?,?,?)",
            (collection_id, media_id, max_order)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already in collection
    conn.close()


def remove_from_collection(collection_id, media_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM collection_items WHERE collection_id=? AND media_id=?",
        (collection_id, media_id)
    )
    conn.commit()
    conn.close()


# ─── Playlists Queries ────────────────────────────────────────────────────────

