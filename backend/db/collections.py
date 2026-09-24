# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from .connection import get_conn
from .media import is_item_mounted, is_item_disabled, enrich_mounted_list


_SMART_RULE_KEYS = {"type", "genre", "year_from", "year_to", "watched", "duration_min", "duration_max", "resolution"}
_SMART_RESOLUTIONS = {480, 720, 1080, 1440, 2160}


def validate_smart_collection_rule(rule):
    if not isinstance(rule, dict) or not rule or set(rule) - _SMART_RULE_KEYS:
        raise ValueError("Provide one or more supported smart collection filters")
    if any(value is None or value == "" for value in rule.values()):
        raise ValueError("Smart collection filters cannot be empty")
    clean = {}
    if "type" in rule:
        if rule["type"] not in ("movie", "series", "anime"):
            raise ValueError("Type must be movie, series, or anime")
        clean["type"] = rule["type"]
    if "genre" in rule:
        genre = rule["genre"]
        if not isinstance(genre, str) or not genre.strip() or len(genre.strip()) > 60:
            raise ValueError("Genre must be 1–60 characters")
        clean["genre"] = genre.strip()
    for key, low, high in (("year_from", 1888, 2100), ("year_to", 1888, 2100), ("duration_min", 0, 10000), ("duration_max", 0, 10000)):
        if key in rule:
            value = rule[key]
            if isinstance(value, bool):
                raise ValueError(f"{key} must be a whole number")
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number")
            if str(value) != str(rule[key]) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            clean[key] = value
    if "year_from" in clean and "year_to" in clean and clean["year_from"] > clean["year_to"]:
        raise ValueError("year_from cannot be after year_to")
    if "duration_min" in clean and "duration_max" in clean and clean["duration_min"] > clean["duration_max"]:
        raise ValueError("duration_min cannot exceed duration_max")
    if "watched" in rule:
        if not isinstance(rule["watched"], bool):
            raise ValueError("watched must be true or false")
        clean["watched"] = rule["watched"]
    if "resolution" in rule:
        try:
            resolution = int(rule["resolution"])
        except (TypeError, ValueError):
            raise ValueError("Unsupported resolution")
        if isinstance(rule["resolution"], bool) or str(resolution) != str(rule["resolution"]) or resolution not in _SMART_RESOLUTIONS:
            raise ValueError("Unsupported resolution")
        clean["resolution"] = resolution
    return clean


def match_smart_collection_items(items, rule, progress_by_id=None, resolution_probe=None):
    rule = validate_smart_collection_rule(rule)
    progress_by_id = progress_by_id or {}
    result = []
    for item in items:
        if "type" in rule and item.get("type") != rule["type"]:
            continue
        if "genre" in rule and rule["genre"].casefold() not in (item.get("genres") or "").casefold():
            continue
        year = item.get("year")
        if "year_from" in rule and (year is None or year < rule["year_from"]):
            continue
        if "year_to" in rule and (year is None or year > rule["year_to"]):
            continue
        duration = item.get("duration")
        if "duration_min" in rule and (not duration or duration < rule["duration_min"] * 60):
            continue
        if "duration_max" in rule and (not duration or duration > rule["duration_max"] * 60):
            continue
        if "watched" in rule:
            progress = progress_by_id.get(item.get("id")) or {}
            watched = bool(progress.get("completed")) if isinstance(progress, dict) else False
            if watched != rule["watched"]:
                continue
        if "resolution" in rule:
            probe = resolution_probe(item.get("file_path")) if resolution_probe and item.get("file_path") else {}
            if not probe or int(probe.get("height") or 0) < rule["resolution"]:
                continue
        result.append(item)
    return result

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

def get_collections(profile_id, progress_by_media_id=None, resolution_probe=None, media_items=None):
    conn = get_conn()
    try:
        media_items = media_items if media_items is not None else enrich_mounted_list(
            [dict(i) for i in conn.execute("SELECT * FROM media ORDER BY title COLLATE NOCASE").fetchall()]
        )
        rows = conn.execute(
            "SELECT * FROM collections WHERE profile_id=? ORDER BY created_at DESC",
            (profile_id,)
        ).fetchall()
        result = []
        for row in rows:
            col = dict(row)
            if col.get("rule_json"):
                rule = json.loads(col["rule_json"])
                col["items"] = match_smart_collection_items(media_items, rule, progress_by_media_id, resolution_probe)
                col["smart"] = True
                col["rule"] = rule
            else:
                items = conn.execute("""
                    SELECT m.* FROM collection_items ci
                    JOIN media m ON m.id = ci.media_id
                    WHERE ci.collection_id=?
                    ORDER BY ci.sort_order
                """, (col["id"],)).fetchall()
                col["items"] = enrich_mounted_list([dict(i) for i in items])
            result.append(col)
        return result
    finally:
        conn.close()


def create_collection(profile_id, name, description="", rule=None):
    conn = get_conn()
    if rule is None:
        cur = conn.execute(
            "INSERT INTO collections (profile_id, name, description) VALUES (?,?,?)",
            (profile_id, name, description)
        )
    else:
        clean_rule = validate_smart_collection_rule(rule)
        cur = conn.execute(
            "INSERT INTO collections (profile_id, name, description, rule_json) VALUES (?,?,?,?)",
            (profile_id, name, description, json.dumps(clean_rule, separators=(",", ":")))
        )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def update_smart_collection_rule(collection_id, profile_id, rule):
    clean_rule = validate_smart_collection_rule(rule)
    conn = get_conn()
    cur = conn.execute(
        "UPDATE collections SET rule_json=? WHERE id=? AND profile_id=?",
        (json.dumps(clean_rule, separators=(",", ":")), collection_id, profile_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount == 1


def delete_collection(collection_id, profile_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM collections WHERE id=? AND profile_id=?",
        (collection_id, profile_id)
    )
    conn.commit()
    conn.close()


_UNSET = object()


def update_collection(collection_id, profile_id, name=None, description=None, cover_id=_UNSET):
    conn = get_conn()
    fields = []
    params = []
    if name is not None:
        fields.append("name=?")
        params.append(name)
    if description is not None:
        fields.append("description=?")
        params.append(description)
    if cover_id is not _UNSET:
        fields.append("cover_id=?")
        params.append(cover_id)
    if fields:
        params.extend([collection_id, profile_id])
        conn.execute(f"UPDATE collections SET {', '.join(fields)} WHERE id=? AND profile_id=?", params)
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

