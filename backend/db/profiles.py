# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import hashlib
import hmac
import secrets
from .connection import get_conn

def get_all_profiles():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, avatar, color, theme, is_kids, is_admin, custom_avatar_url, "
            "maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, "
            "daily_limit_minutes, bedtime_curfew, COALESCE(has_completed_tour, 0) as has_completed_tour, "
            "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
            "FROM profiles ORDER BY position ASC, id ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT id, name, avatar, color, theme, is_kids, is_admin, custom_avatar_url, "
            "maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, "
            "daily_limit_minutes, bedtime_curfew, 0 as has_completed_tour, "
            "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
            "FROM profiles ORDER BY position ASC, id ASC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_profile(profile_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_profile(name, pin_hash, avatar="ph-film-strip", color="#e50914", is_kids=False,
                   daily_limit_minutes=0, bedtime_curfew="", theme="crimson",
                   is_admin=False, custom_avatar_url="", maturity_rating="All",
                   blocked_genres="", default_audio_lang="", default_sub_lang="",
                   position=0, auto_lock_minutes=0, has_completed_tour=0):
    conn = get_conn()
    count_row = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()
    if count_row and count_row[0] == 0:
        is_admin = True

    cur = conn.execute(
        "INSERT INTO profiles (name, pin_hash, avatar, color, is_kids, daily_limit_minutes, bedtime_curfew, theme, "
        "is_admin, custom_avatar_url, maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, has_completed_tour) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name.strip(), pin_hash, avatar, color, 1 if is_kids else 0, int(daily_limit_minutes or 0),
         str(bedtime_curfew or ''), str(theme or 'crimson'), 1 if is_admin else 0,
         str(custom_avatar_url or ''), str(maturity_rating or 'All'), str(blocked_genres or ''),
         str(default_audio_lang or ''), str(default_sub_lang or ''), int(position or 0), int(auto_lock_minutes or 0),
         1 if has_completed_tour else 0)
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_profile(profile_id, name, pin_hash=None, avatar="ph-film-strip", color="#e50914", is_kids=False,
                   update_pin=False, daily_limit_minutes=0, bedtime_curfew="", theme="crimson",
                   is_admin=None, custom_avatar_url=None, maturity_rating="All",
                   blocked_genres="", default_audio_lang="", default_sub_lang="",
                   position=None, auto_lock_minutes=0, has_completed_tour=None):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not row:
        conn.close()
        return
    existing = dict(row)

    admin_val = 1 if is_admin else (0 if is_admin is not None else existing.get("is_admin", 0))
    custom_avatar = custom_avatar_url if custom_avatar_url is not None else existing.get("custom_avatar_url", "")
    pos_val = position if position is not None else existing.get("position", 0)
    tour_val = 1 if has_completed_tour else (0 if has_completed_tour is not None else existing.get("has_completed_tour", 0))

    if is_kids:
        pin_hash = None
        update_pin = True
        admin_val = 0

    if update_pin:
        conn.execute(
            "UPDATE profiles SET name=?, pin_hash=?, avatar=?, color=?, is_kids=?, daily_limit_minutes=?, "
            "bedtime_curfew=?, theme=?, is_admin=?, custom_avatar_url=?, maturity_rating=?, blocked_genres=?, "
            "default_audio_lang=?, default_sub_lang=?, position=?, auto_lock_minutes=?, has_completed_tour=? WHERE id=?",
            (name, pin_hash, avatar, color, 1 if is_kids else 0, int(daily_limit_minutes or 0),
             str(bedtime_curfew or ''), str(theme or 'crimson'), int(admin_val or 0), str(custom_avatar or ''),
             str(maturity_rating or 'All'), str(blocked_genres or ''), str(default_audio_lang or ''),
             str(default_sub_lang or ''), int(pos_val or 0), int(auto_lock_minutes or 0), int(tour_val or 0), profile_id)
        )
    else:
        conn.execute(
            "UPDATE profiles SET name=?, avatar=?, color=?, is_kids=?, daily_limit_minutes=?, "
            "bedtime_curfew=?, theme=?, is_admin=?, custom_avatar_url=?, maturity_rating=?, blocked_genres=?, "
            "default_audio_lang=?, default_sub_lang=?, position=?, auto_lock_minutes=?, has_completed_tour=? WHERE id=?",
            (name, avatar, color, 1 if is_kids else 0, int(daily_limit_minutes or 0),
             str(bedtime_curfew or ''), str(theme or 'crimson'), int(admin_val or 0), str(custom_avatar or ''),
             str(maturity_rating or 'All'), str(blocked_genres or ''), str(default_audio_lang or ''),
             str(default_sub_lang or ''), int(pos_val or 0), int(auto_lock_minutes or 0), int(tour_val or 0), profile_id)
        )
    conn.commit()
    conn.close()


def reorder_profiles(ordered_ids):
    """Update profile order position."""
    conn = get_conn()
    for pos, pid in enumerate(ordered_ids):
        conn.execute("UPDATE profiles SET position=? WHERE id=?", (pos, int(pid)))
    conn.commit()
    conn.close()


def delete_profile(profile_id):
    conn = get_conn()
    conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    # Ensure at least one remaining adult profile is admin
    conn.execute("""
        UPDATE profiles SET is_admin = 1
        WHERE id = (SELECT id FROM profiles WHERE is_kids = 0 ORDER BY id ASC LIMIT 1)
        AND NOT EXISTS (SELECT 1 FROM profiles WHERE is_admin = 1)
    """)
    conn.commit()
    conn.close()


def verify_pin(profile_id, pin_hash):
    conn = get_conn()
    row = conn.execute(
        "SELECT pin_hash FROM profiles WHERE id=?", (profile_id,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    stored = row["pin_hash"]
    if not stored:
        return True  # No PIN set (NULL or legacy empty string)
    return stored == pin_hash


# ─── PIN Hashing (salted PBKDF2 with transparent legacy upgrade) ─────────────

_PBKDF2_ITERATIONS = 120_000


def hash_pin(pin):
    """
    Salted PBKDF2-SHA256 PIN hash, stored as:
      'pbkdf2$<iterations>$<salt_hex>$<hash_hex>'
    A unique per-profile salt defeats rainbow tables (plain SHA-256 did not).
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin_raw(profile_id, raw_pin):
    """
    Verify a raw PIN string against the stored profile hash.
      - no PIN stored        → True  (open profile, any/no PIN accepted)
      - legacy plain SHA-256 → compare directly, auto-upgrade to salted on match
      - pbkdf2$ format       → constant-time compare
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT pin_hash FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
        stored = row["pin_hash"] if row else None

        if not stored:
            return True

        raw = str(raw_pin).strip() if raw_pin is not None else ""
        if not raw:
            return False  # PIN required but none supplied

        if stored.startswith("pbkdf2$"):
            try:
                _, iters, salt_hex, hash_hex = stored.split("$")
                digest = hashlib.pbkdf2_hmac(
                    "sha256", raw.encode(), bytes.fromhex(salt_hex), int(iters)
                )
                return hmac.compare_digest(digest.hex(), hash_hex)
            except Exception:
                return False

        # Legacy unsalted SHA-256 — verify, then transparently upgrade
        legacy = hashlib.sha256(raw.encode()).hexdigest()
        if hmac.compare_digest(legacy, stored):
            conn.execute(
                "UPDATE profiles SET pin_hash=? WHERE id=?",
                (hash_pin(raw), profile_id),
            )
            conn.commit()
            return True
        return False
    finally:
        conn.close()


# ─── Kids Mode Parental Overrides ─────────────────────────────────────────────
# profile_id = 0 applies to ALL kids profiles (parent-managed global rule).
# action 'allow' whitelists a title the rules engine would block;
# action 'block' blacklists a title the rules engine would allow.

def get_kids_override_map():
    """Return {'allow': {tmdb_id, ...}, 'block': {tmdb_id, ...}}."""
    conn = get_conn()
    rows = conn.execute("SELECT tmdb_id, action FROM kids_overrides").fetchall()
    conn.close()
    result = {"allow": set(), "block": set()}
    for r in rows:
        bucket = "allow" if r["action"] == "allow" else "block"
        result[bucket].add(r["tmdb_id"])
    return result


def list_kids_overrides():
    conn = get_conn()
    rows = conn.execute(
        "SELECT tmdb_id, action, title, created_at FROM kids_overrides ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_kids_override(tmdb_id, action, title=None):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO kids_overrides (profile_id, tmdb_id, action, title) VALUES (0, ?, ?, ?)",
        (int(tmdb_id), action, title),
    )
    conn.commit()
    conn.close()


def remove_kids_override(tmdb_id):
    conn = get_conn()
    conn.execute("DELETE FROM kids_overrides WHERE tmdb_id=?", (int(tmdb_id),))
    conn.commit()
    conn.close()


# ─── Watch Progress Queries ───────────────────────────────────────────────────

