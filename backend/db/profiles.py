# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import hashlib
import hmac
import secrets
from datetime import datetime
from .connection import get_conn

def get_all_profiles():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, avatar, color, theme, is_kids, is_admin, custom_avatar_url, "
            "maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, "
            "daily_limit_minutes, bedtime_curfew, COALESCE(has_completed_tour, 0) as has_completed_tour, "
            "COALESCE(default_speed, 1.0) as default_speed, "
            "(CASE WHEN totp_secret IS NOT NULL AND totp_secret != '' THEN 1 ELSE 0 END) as totp_enabled, "
            "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
            "FROM profiles ORDER BY position ASC, id ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        try:
            rows = conn.execute(
                "SELECT id, name, avatar, color, is_kids, is_admin, custom_avatar_url, "
                "maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, "
                "daily_limit_minutes, bedtime_curfew, 0 as has_completed_tour, 1.0 as default_speed, 0 as totp_enabled, "
                "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
                "FROM profiles ORDER BY position ASC, id ASC"
            ).fetchall()
        except sqlite3.OperationalError:
            try:
                rows = conn.execute(
                    "SELECT id, name, avatar, color, 'crimson' as theme, is_kids, 0 as is_admin, "
                    "'' as custom_avatar_url, 'All' as maturity_rating, '' as blocked_genres, "
                    "'' as default_audio_lang, '' as default_sub_lang, 0 as position, 0 as auto_lock_minutes, "
                    "daily_limit_minutes, bedtime_curfew, 0 as has_completed_tour, 1.0 as default_speed, "
                    "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
                    "FROM profiles ORDER BY id ASC"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT id, name, avatar, color, 'crimson' as theme, 0 as is_kids, 0 as is_admin, "
                    "'' as custom_avatar_url, 'All' as maturity_rating, '' as blocked_genres, "
                    "'' as default_audio_lang, '' as default_sub_lang, 0 as position, 0 as auto_lock_minutes, "
                    "0 as daily_limit_minutes, '' as bedtime_curfew, 0 as has_completed_tour, 1.0 as default_speed, "
                    "(CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at "
                    "FROM profiles ORDER BY id ASC"
                ).fetchall()
    conn.close()
    profiles = []
    for r in rows:
        d = dict(r)
        d.setdefault("theme", "crimson")
        d.setdefault("is_kids", 0)
        d.setdefault("is_admin", 0)
        d.setdefault("has_pin", 0)
        d.setdefault("totp_enabled", 0)
        d.setdefault("has_completed_tour", 0)
        d.setdefault("default_speed", 1.0)
        d.setdefault("position", 0)
        d.setdefault("auto_lock_minutes", 0)
        d.setdefault("daily_limit_minutes", 0)
        d.setdefault("bedtime_curfew", "")
        d.setdefault("custom_avatar_url", "")
        d.setdefault("maturity_rating", "All")
        d.setdefault("blocked_genres", "")
        d.setdefault("default_audio_lang", "")
        d.setdefault("default_sub_lang", "")
        profiles.append(d)
    return profiles


def get_profile(profile_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_totp_state(profile_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT totp_secret, totp_last_step FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_totp_secret(profile_id, encrypted_secret):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE profiles SET totp_secret=?, totp_last_step=-1 WHERE id=?",
            (encrypted_secret, profile_id),
        )
        conn.commit()
    finally:
        conn.close()


def activate_totp(profile_id, encrypted_secret, hashes):
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE profiles SET totp_secret=?, totp_last_step=-1 WHERE id=?",
            (encrypted_secret, profile_id),
        )
        conn.execute("DELETE FROM totp_recovery_codes WHERE profile_id=?", (profile_id,))
        conn.executemany(
            "INSERT INTO totp_recovery_codes (profile_id, code_hash) VALUES (?, ?)",
            [(profile_id, code_hash) for code_hash in hashes],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def clear_totp_secret(profile_id, expected_secret=None):
    conn = get_conn()
    try:
        if expected_secret is None:
            conn.execute(
                "UPDATE profiles SET totp_secret=NULL, totp_last_step=-1 WHERE id=?",
                (profile_id,),
            )
        else:
            conn.execute(
                "UPDATE profiles SET totp_secret=NULL, totp_last_step=-1 WHERE id=? AND totp_secret=?",
                (profile_id, expected_secret),
            )
        conn.execute("DELETE FROM totp_recovery_codes WHERE profile_id=?", (profile_id,))
        conn.commit()
    finally:
        conn.close()


def accept_totp_step(profile_id, step, expected_secret=None):
    conn = get_conn()
    try:
        if expected_secret is None:
            cur = conn.execute(
                "UPDATE profiles SET totp_last_step=? WHERE id=? AND COALESCE(totp_last_step, -1) < ?",
                (int(step), profile_id, int(step)),
            )
        else:
            cur = conn.execute(
                "UPDATE profiles SET totp_last_step=? WHERE id=? AND totp_secret=? AND COALESCE(totp_last_step, -1) < ?",
                (int(step), profile_id, expected_secret, int(step)),
            )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def replace_totp_recovery_codes(profile_id, hashes):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM totp_recovery_codes WHERE profile_id=?", (profile_id,))
        conn.executemany(
            "INSERT INTO totp_recovery_codes (profile_id, code_hash) VALUES (?, ?)",
            [(profile_id, code_hash) for code_hash in hashes],
        )
        conn.commit()
    finally:
        conn.close()


def consume_totp_recovery_code(profile_id, code_hash):
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM totp_recovery_codes WHERE profile_id=? AND code_hash=?",
            (profile_id, code_hash),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def create_profile(name, pin_hash, avatar="ph-film-strip", color="#e50914", is_kids=False,
                   daily_limit_minutes=0, bedtime_curfew="", theme="crimson",
                   is_admin=False, custom_avatar_url="", maturity_rating="All",
                   blocked_genres="", default_audio_lang="", default_sub_lang="",
                   position=0, auto_lock_minutes=0, has_completed_tour=0, default_speed=1.0):
    conn = get_conn()
    count_row = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()
    if count_row and count_row[0] == 0:
        is_admin = True

    cur = conn.execute(
        "INSERT INTO profiles (name, pin_hash, avatar, color, is_kids, daily_limit_minutes, bedtime_curfew, theme, "
        "is_admin, custom_avatar_url, maturity_rating, blocked_genres, default_audio_lang, default_sub_lang, position, auto_lock_minutes, has_completed_tour, default_speed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name.strip(), pin_hash, avatar, color, 1 if is_kids else 0, int(daily_limit_minutes or 0),
         str(bedtime_curfew or ''), str(theme or 'crimson'), 1 if is_admin else 0,
         str(custom_avatar_url or ''), str(maturity_rating or 'All'), str(blocked_genres or ''),
         str(default_audio_lang or ''), str(default_sub_lang or ''), int(position or 0), int(auto_lock_minutes or 0),
         1 if has_completed_tour else 0, float(default_speed or 1.0))
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_profile(profile_id, name, pin_hash=None, avatar="ph-film-strip", color="#e50914", is_kids=False,
                   update_pin=False, daily_limit_minutes=0, bedtime_curfew="", theme="crimson",
                   is_admin=None, custom_avatar_url=None, maturity_rating="All",
                   blocked_genres="", default_audio_lang="", default_sub_lang="",
                   position=None, auto_lock_minutes=0, has_completed_tour=None, default_speed=None):
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
    speed_val = float(default_speed) if default_speed is not None else float(existing.get("default_speed") or 1.0)
    disable_totp = bool(is_kids or not admin_val)

    if is_kids:
        pin_hash = None
        update_pin = True
        admin_val = 0

    if update_pin:
        conn.execute(
            "UPDATE profiles SET name=?, pin_hash=?, avatar=?, color=?, is_kids=?, "
            "totp_secret=CASE WHEN ? THEN NULL ELSE totp_secret END, "
            "totp_last_step=CASE WHEN ? THEN -1 ELSE totp_last_step END, daily_limit_minutes=?, "
            "bedtime_curfew=?, theme=?, is_admin=?, custom_avatar_url=?, maturity_rating=?, blocked_genres=?, "
            "default_audio_lang=?, default_sub_lang=?, position=?, auto_lock_minutes=?, has_completed_tour=?, default_speed=? WHERE id=?",
            (name, pin_hash, avatar, color, 1 if is_kids else 0, 1 if disable_totp else 0, 1 if disable_totp else 0, int(daily_limit_minutes or 0),
             str(bedtime_curfew or ''), str(theme or 'crimson'), int(admin_val or 0), str(custom_avatar or ''),
             str(maturity_rating or 'All'), str(blocked_genres or ''), str(default_audio_lang or ''),
             str(default_sub_lang or ''), int(pos_val or 0), int(auto_lock_minutes or 0), int(tour_val or 0),
             speed_val, profile_id)
        )
    else:
        conn.execute(
            "UPDATE profiles SET name=?, avatar=?, color=?, is_kids=?, "
            "totp_secret=CASE WHEN ? THEN NULL ELSE totp_secret END, "
            "totp_last_step=CASE WHEN ? THEN -1 ELSE totp_last_step END, daily_limit_minutes=?, "
            "bedtime_curfew=?, theme=?, is_admin=?, custom_avatar_url=?, maturity_rating=?, blocked_genres=?, "
            "default_audio_lang=?, default_sub_lang=?, position=?, auto_lock_minutes=?, has_completed_tour=?, default_speed=? WHERE id=?",
            (name, avatar, color, 1 if is_kids else 0, 1 if disable_totp else 0, 1 if disable_totp else 0, int(daily_limit_minutes or 0),
             str(bedtime_curfew or ''), str(theme or 'crimson'), int(admin_val or 0), str(custom_avatar or ''),
             str(maturity_rating or 'All'), str(blocked_genres or ''), str(default_audio_lang or ''),
             str(default_sub_lang or ''), int(pos_val or 0), int(auto_lock_minutes or 0), int(tour_val or 0),
             speed_val, profile_id)
        )
    if disable_totp:
        conn.execute("DELETE FROM totp_recovery_codes WHERE profile_id=?", (profile_id,))
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


def create_profile_snapshot(profile_id, label="Pre-Debug Easter Egg Backup"):
    """Capture achievements, watch_progress, watch_history, and favorites for a profile."""
    if not profile_id:
        return None
    conn = get_conn()
    try:
        ach_rows = [dict(r) for r in conn.execute("SELECT achievement_id, unlocked_at FROM achievements WHERE profile_id=?", (profile_id,)).fetchall()]
        wp_rows = [dict(r) for r in conn.execute("SELECT media_id, position, duration, completed, updated_at FROM watch_progress WHERE profile_id=?", (profile_id,)).fetchall()]
        wh_rows = [dict(r) for r in conn.execute("SELECT tmdb_id, title, type, season, episode, ep_title, genres, year, poster_path, position, duration, completed, updated_at FROM watch_history WHERE profile_id=?", (profile_id,)).fetchall()]
        fav_rows = [dict(r) for r in conn.execute("SELECT media_id, added_at FROM favorites WHERE profile_id=?", (profile_id,)).fetchall()]
        
        snapshot_payload = {
            "version": 1,
            "profile_id": profile_id,
            "label": label,
            "counts": {
                "achievements": len(ach_rows),
                "watch_progress": len(wp_rows),
                "watch_history": len(wh_rows),
                "favorites": len(fav_rows),
            },
            "achievements": ach_rows,
            "watch_progress": wp_rows,
            "watch_history": wh_rows,
            "favorites": fav_rows,
        }
        json_str = json.dumps(snapshot_payload)
        cur = conn.execute(
            "INSERT INTO profile_snapshots (profile_id, label, data_json) VALUES (?, ?, ?)",
            (profile_id, label, json_str)
        )
        snapshot_id = cur.lastrowid
        conn.commit()
        return {
            "id": snapshot_id,
            "profile_id": profile_id,
            "label": label,
            "counts": snapshot_payload["counts"],
        }
    finally:
        conn.close()


def get_latest_profile_snapshot(profile_id):
    """Retrieve the most recent snapshot metadata for a profile."""
    if not profile_id:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, profile_id, label, created_at, data_json FROM profile_snapshots WHERE profile_id=? ORDER BY id DESC LIMIT 1",
            (profile_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["data_json"])
        return {
            "id": row["id"],
            "profile_id": row["profile_id"],
            "label": row["label"],
            "created_at": row["created_at"],
            "counts": data.get("counts", {}),
        }
    except Exception:
        return None
    finally:
        conn.close()


def revert_profile_snapshot(profile_id, snapshot_id=None):
    """Restore profile data (achievements, watch_progress, watch_history, favorites) from snapshot."""
    if not profile_id:
        return False, "Invalid profile"
    conn = get_conn()
    try:
        if snapshot_id:
            row = conn.execute(
                "SELECT id, data_json FROM profile_snapshots WHERE profile_id=? AND id=?",
                (profile_id, int(snapshot_id))
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, data_json FROM profile_snapshots WHERE profile_id=? ORDER BY id DESC LIMIT 1",
                (profile_id,)
            ).fetchone()
        
        if not row:
            return False, "No snapshot found for profile"
        
        payload = json.loads(row["data_json"])
        
        # 1. Clear current state for this profile
        conn.execute("DELETE FROM achievements WHERE profile_id=?", (profile_id,))
        conn.execute("DELETE FROM watch_progress WHERE profile_id=?", (profile_id,))
        conn.execute("DELETE FROM watch_history WHERE profile_id=?", (profile_id,))
        conn.execute("DELETE FROM favorites WHERE profile_id=?", (profile_id,))
        
        # 2. Re-insert achievements
        for a in payload.get("achievements", []):
            conn.execute(
                "INSERT OR IGNORE INTO achievements (profile_id, achievement_id, unlocked_at) VALUES (?, ?, ?)",
                (profile_id, a["achievement_id"], a.get("unlocked_at"))
            )
        
        # 3. Re-insert watch_progress
        for wp in payload.get("watch_progress", []):
            conn.execute(
                "INSERT OR IGNORE INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, wp["media_id"], wp.get("position", 0), wp.get("duration", 0), wp.get("completed", 0), wp.get("updated_at"))
            )
        
        # 4. Re-insert watch_history
        for wh in payload.get("watch_history", []):
            conn.execute(
                "INSERT INTO watch_history (profile_id, tmdb_id, title, type, season, episode, ep_title, genres, year, poster_path, position, duration, completed, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (profile_id, wh.get("tmdb_id"), wh.get("title", ""), wh.get("type", "movie"), wh.get("season"), wh.get("episode"), wh.get("ep_title"), wh.get("genres"), wh.get("year"), wh.get("poster_path"), wh.get("position", 0), wh.get("duration", 0), wh.get("completed", 0), wh.get("updated_at"))
            )
        
        # 5. Re-insert favorites
        for f in payload.get("favorites", []):
            conn.execute(
                "INSERT OR IGNORE INTO favorites (profile_id, media_id, added_at) VALUES (?, ?, ?)",
                (profile_id, f["media_id"], f.get("added_at"))
            )
        
        conn.commit()
        return True, "Profile restored successfully"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def export_profile_data(profile_id):
    """Export current profile data state directly as dict."""
    if not profile_id:
        return None
    conn = get_conn()
    try:
        p_row = conn.execute("SELECT id, name, is_kids FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if not p_row:
            return None
        ach_rows = [dict(r) for r in conn.execute("SELECT achievement_id, unlocked_at FROM achievements WHERE profile_id=?", (profile_id,)).fetchall()]
        wp_rows = [dict(r) for r in conn.execute("SELECT media_id, position, duration, completed, updated_at FROM watch_progress WHERE profile_id=?", (profile_id,)).fetchall()]
        wh_rows = [dict(r) for r in conn.execute("SELECT tmdb_id, title, type, season, episode, ep_title, genres, year, poster_path, position, duration, completed, updated_at FROM watch_history WHERE profile_id=?", (profile_id,)).fetchall()]
        fav_rows = [dict(r) for r in conn.execute("SELECT media_id, added_at FROM favorites WHERE profile_id=?", (profile_id,)).fetchall()]
        return {
            "version": 1,
            "exported_at": datetime.now().isoformat() if "datetime" in globals() else "",
            "profile": dict(p_row),
            "achievements": ach_rows,
            "watch_progress": wp_rows,
            "watch_history": wh_rows,
            "favorites": fav_rows,
        }
    finally:
        conn.close()


def import_profile_data(profile_id, payload):
    """Import and apply profile data from payload dict."""
    if not profile_id or not isinstance(payload, dict):
        return False, "Invalid payload"
    conn = get_conn()
    try:
        if "achievements" in payload:
            conn.execute("DELETE FROM achievements WHERE profile_id=?", (profile_id,))
            for a in payload["achievements"]:
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (profile_id, achievement_id, unlocked_at) VALUES (?, ?, ?)",
                    (profile_id, a["achievement_id"], a.get("unlocked_at"))
                )
        if "watch_progress" in payload:
            conn.execute("DELETE FROM watch_progress WHERE profile_id=?", (profile_id,))
            for wp in payload["watch_progress"]:
                conn.execute(
                    "INSERT OR IGNORE INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (profile_id, wp["media_id"], wp.get("position", 0), wp.get("duration", 0), wp.get("completed", 0), wp.get("updated_at"))
                )
        if "watch_history" in payload:
            conn.execute("DELETE FROM watch_history WHERE profile_id=?", (profile_id,))
            for wh in payload["watch_history"]:
                conn.execute(
                    "INSERT INTO watch_history (profile_id, tmdb_id, title, type, season, episode, ep_title, genres, year, poster_path, position, duration, completed, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (profile_id, wh.get("tmdb_id"), wh.get("title", ""), wh.get("type", "movie"), wh.get("season"), wh.get("episode"), wh.get("ep_title"), wh.get("genres"), wh.get("year"), wh.get("poster_path"), wh.get("position", 0), wh.get("duration", 0), wh.get("completed", 0), wh.get("updated_at"))
                )
        if "favorites" in payload:
            conn.execute("DELETE FROM favorites WHERE profile_id=?", (profile_id,))
            for f in payload["favorites"]:
                conn.execute(
                    "INSERT OR IGNORE INTO favorites (profile_id, media_id, added_at) VALUES (?, ?, ?)",
                    (profile_id, f["media_id"], f.get("added_at"))
                )
        conn.commit()
        return True, "Data imported successfully"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()



# ─── Watch Progress Queries ───────────────────────────────────────────────────

