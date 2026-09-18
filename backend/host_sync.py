# -*- coding: utf-8 -*-
"""
backend/host_sync.py — Seamless Host PC Documents User Data Synchronization.

Provides two-way intelligent synchronization between CapsStream portable drives
and the host PC's local Documents folder:
  - Export: Saves profiles, watch history, progress, playlists, favorites,
    achievements, and custom avatars to %USERPROFILE%/Documents/CapsStream/user_data.db.
  - Import / Merge: Seamlessly restores personal watch data onto newly swapped or updated
    drives while preserving all newly scanned movies and series.
  - Missing Media Resilience: Media not present on the new drive remains intact in
    persistent watch history and statistics, while omitted from active playback queues.
  - Safety: Strictly disabled in Development Mode (is_dev_mode()) to prevent accidental
    overwrites of developer databases.
"""

import os
import re
import sys
import json
import time
import shutil
import ctypes
import sqlite3
import platform
import subprocess

from backend.utils.version import is_dev_mode
from backend.db.connection import get_conn, DB_PATH, DATA_DIR
from backend.db.playback import restore_progress_for_media
from backend.settings import load_config, save_config


def get_windows_volume_label(path: str) -> str:
    """
    Query the volume label of the drive containing the given path on Windows.
    Returns empty string if unavailable or not on Windows.
    """
    if platform.system() != "Windows":
        return ""
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return ""
        drive_root = drive + "\\"
        vol_buf = ctypes.create_unicode_buffer(1024)
        fs_buf = ctypes.create_unicode_buffer(1024)
        res = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_root),
            vol_buf,
            ctypes.sizeof(vol_buf),
            None,
            None,
            None,
            fs_buf,
            ctypes.sizeof(fs_buf)
        )
        if res and vol_buf.value:
            return vol_buf.value.strip()
    except Exception:
        pass
    return ""


def sanitize_tag(name: str) -> str:
    """Sanitize tag string for safe use in file paths."""
    if not name:
        return ""
    cleaned = re.sub(r'[^\w\s-]', '', str(name)).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    return cleaned


def get_drive_tag(custom_tag: str = None) -> str:
    """
    Resolve the unique drive / library tag for host sync subfolder separation:
    1. custom_tag parameter (if passed directly)
    2. In dev mode -> 'Dev_Test' (safe isolation for development)
    3. Configured tag in config.json (host_sync.drive_tag)
    4. Windows USB / partition volume label (e.g. 'CAPS_USB')
    5. Drive letter fallback (e.g. 'Drive_T', 'Drive_D') or 'Default_Drive'
    """
    if custom_tag:
        clean = sanitize_tag(custom_tag)
        if clean:
            return clean

    if is_dev_mode():
        return "Dev_Test"

    # Check config.json
    try:
        cfg = load_config()
        host_sync_cfg = cfg.get("host_sync")
        cfg_tag = ""
        if isinstance(host_sync_cfg, dict):
            cfg_tag = host_sync_cfg.get("drive_tag", "")
        if cfg_tag:
            clean = sanitize_tag(cfg_tag)
            if clean:
                return clean
    except Exception:
        pass

    # Check Windows volume label
    target_path = DATA_DIR if os.path.exists(DATA_DIR) else "."
    vol_label = get_windows_volume_label(target_path)
    if vol_label:
        clean = sanitize_tag(vol_label)
        if clean:
            return clean

    # Fallback to drive letter
    try:
        drive = os.path.splitdrive(os.path.abspath(target_path))[0]
        if drive:
            letter = drive.rstrip(":").replace("\\", "").replace("/", "").upper()
            if letter:
                return f"Drive_{letter}"
    except Exception:
        pass

    return "Default_Drive"


def get_host_sync_dir(custom_tag: str = None) -> str:
    """
    Resolve the platform-appropriate CapsStream Documents folder on the host PC:
    Windows: %USERPROFILE%/Documents/CapsStream/<Drive_Tag>
    macOS / Linux: ~/Documents/CapsStream/<Drive_Tag>
    """
    if platform.system() == "Windows":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile and os.path.isdir(user_profile):
            docs = os.path.join(user_profile, "Documents")
        else:
            docs = os.path.expanduser("~/Documents")
    else:
        docs = os.path.expanduser("~/Documents")

    tag = get_drive_tag(custom_tag)
    sync_dir = os.path.join(docs, "CapsStream", tag)
    return os.path.abspath(sync_dir)


def is_host_sync_allowed(force_dev: bool = False) -> bool:
    """
    Returns True if Host PC Sync is permitted.
    For background/automatic operations (startup/shutdown), disabled in dev mode unless force_dev is True.
    Checks config `host_sync.enabled` (defaulting to False).
    """
    if is_dev_mode() and not force_dev:
        return False

    cfg = load_config()
    host_sync_cfg = cfg.get("host_sync", {})
    if isinstance(host_sync_cfg, dict):
        return bool(host_sync_cfg.get("enabled", False))
    return bool(cfg.get("auto_sync_host", False))


def get_host_sync_status(custom_tag: str = None) -> dict:
    """
    Inspect the host sync directory and return current status, timestamps, and statistics.
    """
    tag = get_drive_tag(custom_tag)
    sync_dir = get_host_sync_dir(custom_tag)
    db_file = os.path.join(sync_dir, "user_data.db")
    stamp_file = os.path.join(sync_dir, "sync_manifest.json")
    summary_file = os.path.join(sync_dir, "export_summary.txt")

    dev_active = is_dev_mode()
    has_data = os.path.isfile(db_file)

    manifest = {}
    if os.path.isfile(stamp_file):
        try:
            with open(stamp_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    summary_text = ""
    if os.path.isfile(summary_file):
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = ""

    cfg = load_config()
    host_sync_cfg = cfg.get("host_sync", {})
    enabled = bool(host_sync_cfg.get("enabled", False)) if isinstance(host_sync_cfg, dict) else False

    return {
        "ok": True,
        "is_dev": dev_active,
        "enabled": enabled,
        "drive_tag": tag,
        "sync_dir": sync_dir,
        "has_host_data": has_data,
        "db_size": os.path.getsize(db_file) if has_data else 0,
        "last_sync_timestamp": manifest.get("timestamp"),
        "last_sync_formatted": manifest.get("formatted_time"),
        "profile_count": manifest.get("profiles_count", 0),
        "history_count": manifest.get("history_count", 0),
        "summary": summary_text,
    }


def export_user_data_to_host(force_dev: bool = False, conn=None, custom_tag: str = None) -> dict:
    """
    Export user data (profiles, history, progress, playlists, favorites, achievements, avatars)
    from current CapsStream database to %USERPROFILE%/Documents/CapsStream/<Drive_Tag>/user_data.db.
    """
    tag = get_drive_tag(custom_tag)
    # Dev mode is allowed to export/import to Dev_Test for testing
    if is_dev_mode() and tag != "Dev_Test" and not force_dev:
        return {
            "ok": False,
            "error": "Host PC Sync is disabled in Development Mode for non-test tags.",
            "is_dev": True
        }

    sync_dir = get_host_sync_dir(custom_tag)
    os.makedirs(sync_dir, exist_ok=True)
    avatars_host_dir = os.path.join(sync_dir, "avatars")
    os.makedirs(avatars_host_dir, exist_ok=True)

    target_db = os.path.join(sync_dir, "user_data.db")
    tmp_db = os.path.join(sync_dir, "user_data.tmp.db")

    close_local = False
    if conn is None:
        conn = get_conn()
        close_local = True
    else:
        conn.row_factory = sqlite3.Row

    try:
        # 1. Initialize temporary SQLite database with clean sync schema
        if os.path.exists(tmp_db):
            try: os.remove(tmp_db)
            except Exception: pass

        t_conn = sqlite3.connect(tmp_db)
        t_conn.row_factory = sqlite3.Row

        t_conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id                  INTEGER PRIMARY KEY,
                name                TEXT NOT NULL,
                pin_hash            TEXT,
                avatar              TEXT DEFAULT 'ph-film-strip',
                color               TEXT DEFAULT '#e50914',
                theme               TEXT DEFAULT 'crimson',
                is_kids             INTEGER DEFAULT 0,
                is_admin            INTEGER DEFAULT 0,
                daily_limit_minutes INTEGER DEFAULT 0,
                bedtime_curfew      TEXT DEFAULT '',
                custom_avatar_url   TEXT DEFAULT '',
                maturity_rating     TEXT DEFAULT 'All',
                blocked_genres      TEXT DEFAULT '',
                default_audio_lang  TEXT DEFAULT '',
                default_sub_lang    TEXT DEFAULT '',
                position            INTEGER DEFAULT 0,
                auto_lock_minutes   INTEGER DEFAULT 0,
                has_completed_tour  INTEGER DEFAULT 0,
                default_speed       REAL DEFAULT 1.0,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watch_history (
                id          INTEGER PRIMARY KEY,
                profile_id  INTEGER NOT NULL,
                tmdb_id     INTEGER,
                title       TEXT NOT NULL,
                type        TEXT NOT NULL,
                season      INTEGER,
                episode     INTEGER,
                ep_title    TEXT,
                genres      TEXT,
                year        INTEGER,
                poster_path TEXT,
                position    INTEGER NOT NULL DEFAULT 0,
                duration    INTEGER DEFAULT 0,
                completed   INTEGER DEFAULT 0,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS achievements (
                profile_id     INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (profile_id, achievement_id)
            );

            CREATE TABLE IF NOT EXISTS kids_overrides (
                profile_id INTEGER NOT NULL DEFAULT 0,
                tmdb_id    INTEGER NOT NULL,
                action     TEXT NOT NULL,
                title      TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (profile_id, tmdb_id)
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id          INTEGER PRIMARY KEY,
                profile_id  INTEGER NOT NULL,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_shared   INTEGER NOT NULL DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlist_items_sync (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL,
                position    INTEGER NOT NULL DEFAULT 0,
                tmdb_id     INTEGER,
                type        TEXT,
                title       TEXT,
                year        INTEGER,
                season      INTEGER,
                episode     INTEGER,
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS favorites_sync (
                profile_id  INTEGER NOT NULL,
                tmdb_id     INTEGER,
                type        TEXT,
                title       TEXT,
                year        INTEGER,
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (profile_id, tmdb_id, type, title)
            );
        """)

        # 2. Export Profiles
        profiles = [dict(r) for r in conn.execute("SELECT * FROM profiles").fetchall()]
        for p_dict in profiles:
            cols = [k for k in p_dict.keys() if k in [
                "id", "name", "pin_hash", "avatar", "color", "theme", "is_kids", "is_admin",
                "daily_limit_minutes", "bedtime_curfew", "custom_avatar_url", "maturity_rating",
                "blocked_genres", "default_audio_lang", "default_sub_lang", "position",
                "auto_lock_minutes", "has_completed_tour", "default_speed", "created_at"
            ]]
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [p_dict[c] for c in cols]
            t_conn.execute(f"INSERT OR REPLACE INTO profiles ({col_str}) VALUES ({placeholders})", vals)

        # 3. Export Watch History
        history_rows = [dict(r) for r in conn.execute("SELECT * FROM watch_history").fetchall()]
        for h_dict in history_rows:
            cols = [k for k in h_dict.keys() if k in [
                "id", "profile_id", "tmdb_id", "title", "type", "season", "episode",
                "ep_title", "genres", "year", "poster_path", "position", "duration",
                "completed", "updated_at"
            ]]
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            vals = [h_dict[c] for c in cols]
            t_conn.execute(f"INSERT OR REPLACE INTO watch_history ({col_str}) VALUES ({placeholders})", vals)

        # 4. Export Achievements
        achievements = [dict(r) for r in conn.execute("SELECT * FROM achievements").fetchall()]
        for a in achievements:
            t_conn.execute(
                "INSERT OR REPLACE INTO achievements (profile_id, achievement_id, unlocked_at) VALUES (?, ?, ?)",
                (a["profile_id"], a["achievement_id"], a["unlocked_at"])
            )

        # 5. Export Kids Overrides
        try:
            overrides = [dict(r) for r in conn.execute("SELECT * FROM kids_overrides").fetchall()]
            for ko in overrides:
                t_conn.execute(
                    "INSERT OR REPLACE INTO kids_overrides (profile_id, tmdb_id, action, title, created_at) VALUES (?, ?, ?, ?, ?)",
                    (ko["profile_id"], ko["tmdb_id"], ko["action"], ko.get("title"), ko.get("created_at"))
                )
        except Exception:
            pass

        # 6. Export Playlists & Items (joined with media for portable metadata matching)
        pls = []
        try:
            pls = [dict(r) for r in conn.execute("SELECT * FROM playlists").fetchall()]
            for pl in pls:
                t_conn.execute(
                    "INSERT OR REPLACE INTO playlists (id, profile_id, name, description, is_shared, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pl["id"], pl["profile_id"], pl["name"], pl.get("description", ""), pl.get("is_shared", 0), pl.get("created_at"), pl.get("updated_at"))
                )

            pl_items = [dict(r) for r in conn.execute("""
                SELECT pi.playlist_id, pi.position, pi.added_at,
                       m.tmdb_id, m.type, m.title, m.year, m.season, m.episode
                FROM playlist_items pi
                JOIN media m ON m.id = pi.media_id
            """).fetchall()]
            for item in pl_items:
                t_conn.execute("""
                    INSERT INTO playlist_items_sync (playlist_id, position, tmdb_id, type, title, year, season, episode, added_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["playlist_id"], item["position"], item["tmdb_id"], item["type"],
                    item["title"], item["year"], item["season"], item["episode"], item["added_at"]
                ))
        except Exception as pl_err:
            print("[HostSync] Playlist export notice:", pl_err)

        # 7. Export Favorites (joined with media for portable metadata matching)
        try:
            favs = [dict(r) for r in conn.execute("""
                SELECT f.profile_id, f.added_at,
                       m.tmdb_id, m.type, m.title, m.year
                FROM favorites f
                JOIN media m ON m.id = f.media_id
            """).fetchall()]
            for fav in favs:
                t_conn.execute("""
                    INSERT OR REPLACE INTO favorites_sync (profile_id, tmdb_id, type, title, year, added_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    fav["profile_id"], fav["tmdb_id"], fav["type"],
                    fav["title"], fav["year"], fav["added_at"]
                ))
        except Exception as fav_err:
            print("[HostSync] Favorites export notice:", fav_err)

        t_conn.commit()
        t_conn.close()

        # Atomically move tmp_db to target_db
        if os.path.exists(target_db):
            try: os.remove(target_db)
            except Exception: pass
        shutil.move(tmp_db, target_db)

        # 8. Synchronize Custom Avatars to Documents/CapsStream/avatars/
        local_avatars_dir = os.path.join(DATA_DIR, "avatars")
        synced_avatars = 0
        if os.path.isdir(local_avatars_dir):
            for fname in os.listdir(local_avatars_dir):
                src_av = os.path.join(local_avatars_dir, fname)
                if os.path.isfile(src_av):
                    dst_av = os.path.join(avatars_host_dir, fname)
                    try:
                        shutil.copy2(src_av, dst_av)
                        synced_avatars += 1
                    except Exception:
                        pass

        # 9. Compute stats for export_summary.txt and manifest
        total_seconds = 0
        completed_count = 0
        for h in history_rows:
            total_seconds += (h["position"] or 0)
            if h["completed"]:
                completed_count += 1
        total_hours = round(total_seconds / 3600.0, 1)

        now_ts = int(time.time())
        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))

        # Write human-readable export_summary.txt
        summary_path = os.path.join(sync_dir, "export_summary.txt")
        profile_names = [p["name"] for p in profiles]
        with open(summary_path, "w", encoding="utf-8") as sf:
            sf.write("====================================================\n")
            sf.write("CapsStream Host User Data Backup & Sync\n")
            sf.write("====================================================\n")
            sf.write(f"Last Synced:    {formatted_time}\n")
            sf.write(f"Drive Tag:      {tag}\n")
            sf.write(f"Host Machine:   {platform.node()} ({platform.system()} {platform.release()})\n")
            sf.write(f"Backup Path:    {sync_dir}\n\n")
            sf.write(f"Profiles ({len(profile_names)}):\n")
            for p in profiles:
                admin_str = " [Admin]" if p.get("is_admin") else ""
                kids_str = " [Kids]" if p.get("is_kids") else ""
                sf.write(f"  • {p['name']}{admin_str}{kids_str} (Theme: {p.get('theme', 'crimson')})\n")
            sf.write("\nActivity & History:\n")
            sf.write(f"  • Total Watch History Entries: {len(history_rows)}\n")
            sf.write(f"  • Total Watch Time:           {total_hours} hours\n")
            sf.write(f"  • Completed Titles:           {completed_count}\n")
            sf.write(f"  • Playlists:                  {len(pls)}\n")
            sf.write(f"  • Achievements Unlocked:      {len(achievements)}\n")
            sf.write(f"  • Custom Profile Avatars:     {synced_avatars}\n")
            sf.write("====================================================\n")

        # Write machine-readable sync_manifest.json
        manifest_path = os.path.join(sync_dir, "sync_manifest.json")
        manifest_data = {
            "timestamp": now_ts,
            "formatted_time": formatted_time,
            "hostname": platform.node(),
            "drive_tag": tag,
            "profiles_count": len(profiles),
            "history_count": len(history_rows),
            "total_watch_hours": total_hours,
            "achievements_count": len(achievements),
            "avatars_count": synced_avatars
        }
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest_data, mf, indent=2)

        return {
            "ok": True,
            "message": f"Successfully synced user data to {sync_dir}",
            "sync_dir": sync_dir,
            "drive_tag": tag,
            "timestamp": now_ts,
            "formatted_time": formatted_time,
            "profiles_count": len(profiles),
            "history_count": len(history_rows),
            "avatars_count": synced_avatars
        }

    except Exception as e:
        if os.path.exists(tmp_db):
            try: os.remove(tmp_db)
            except Exception: pass
        return {"ok": False, "error": f"Failed to export user data: {str(e)}"}
    finally:
        if close_local and conn:
            conn.close()


def import_user_data_from_host(force_dev: bool = False, conn=None, custom_tag: str = None) -> dict:
    """
    Intelligently merge user data from %USERPROFILE%/Documents/CapsStream/<Drive_Tag>/user_data.db
    into current database, re-linking watch progress for all movies/series on the new drive.
    """
    tag = get_drive_tag(custom_tag)
    if is_dev_mode() and tag != "Dev_Test" and not force_dev:
        return {
            "ok": False,
            "error": "Host PC Sync is disabled in Development Mode for non-test tags.",
            "is_dev": True
        }

    sync_dir = get_host_sync_dir(custom_tag)
    host_db_path = os.path.join(sync_dir, "user_data.db")
    if not os.path.isfile(host_db_path):
        return {
            "ok": False,
            "error": f"No user data found in host Documents folder ({sync_dir}).",
            "sync_dir": sync_dir,
            "drive_tag": tag
        }

    close_local = False
    if conn is None:
        conn = get_conn()
        close_local = True
    else:
        conn.row_factory = sqlite3.Row

    try:
        h_conn = sqlite3.connect(host_db_path)
        h_conn.row_factory = sqlite3.Row

        # 1. Merge Profiles (match by name to avoid duplicate IDs)
        host_profiles = [dict(r) for r in h_conn.execute("SELECT * FROM profiles").fetchall()]
        existing_profiles = [dict(r) for r in conn.execute("SELECT * FROM profiles").fetchall()]
        existing_by_name = {p["name"].strip().lower(): dict(p) for p in existing_profiles}

        profile_map = {}  # host_id -> local_id

        restored_profiles = 0
        for hp in host_profiles:
            h_id = hp["id"]
            name_key = hp["name"].strip().lower()
            if name_key in existing_by_name:
                local_p = existing_by_name[name_key]
                profile_map[h_id] = local_p["id"]
                # If existing is just an unconfigured default, update preferences
                conn.execute("""
                    UPDATE profiles SET
                        avatar = COALESCE(NULLIF(avatar, 'ph-film-strip'), ?),
                        color = COALESCE(color, ?),
                        theme = COALESCE(theme, ?),
                        custom_avatar_url = COALESCE(NULLIF(custom_avatar_url, ''), ?),
                        maturity_rating = ?,
                        blocked_genres = ?,
                        default_speed = ?
                    WHERE id = ?
                """, (
                    hp["avatar"], hp["color"], hp["theme"], hp.get("custom_avatar_url", ""),
                    hp.get("maturity_rating", "All"), hp.get("blocked_genres", ""),
                    hp.get("default_speed", 1.0), local_p["id"]
                ))
            else:
                # Insert new profile
                cur = conn.execute("""
                    INSERT INTO profiles (
                        name, pin_hash, avatar, color, theme, is_kids, is_admin,
                        daily_limit_minutes, bedtime_curfew, custom_avatar_url, maturity_rating,
                        blocked_genres, default_audio_lang, default_sub_lang, position,
                        auto_lock_minutes, has_completed_tour, default_speed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hp["name"], hp.get("pin_hash"), hp.get("avatar", "ph-film-strip"),
                    hp.get("color", "#e50914"), hp.get("theme", "crimson"), hp.get("is_kids", 0),
                    hp.get("is_admin", 0), hp.get("daily_limit_minutes", 0), hp.get("bedtime_curfew", ""),
                    hp.get("custom_avatar_url", ""), hp.get("maturity_rating", "All"),
                    hp.get("blocked_genres", ""), hp.get("default_audio_lang", ""),
                    hp.get("default_sub_lang", ""), hp.get("position", 0),
                    hp.get("auto_lock_minutes", 0), hp.get("has_completed_tour", 0),
                    hp.get("default_speed", 1.0)
                ))
                new_id = cur.lastrowid
                profile_map[h_id] = new_id
                restored_profiles += 1

        # Fallback profile map: default to primary admin profile if unmapped
        primary_admin = conn.execute("SELECT id FROM profiles ORDER BY is_admin DESC, id ASC LIMIT 1").fetchone()
        default_local_pid = primary_admin["id"] if primary_admin else 1

        # 2. Merge Watch History
        host_history = [dict(r) for r in h_conn.execute("SELECT * FROM watch_history").fetchall()]
        restored_history = 0
        for hh in host_history:
            target_pid = profile_map.get(hh["profile_id"], default_local_pid)
            tmdb_id = hh["tmdb_id"]
            title = hh["title"]
            mtype = hh["type"]
            season = hh["season"]
            episode = hh["episode"]

            # Match existing history
            match = None
            if tmdb_id:
                match = conn.execute("""
                    SELECT id, position, duration, completed FROM watch_history
                    WHERE profile_id=? AND tmdb_id=? AND type=?
                      AND COALESCE(season, -1) = COALESCE(?, -1)
                      AND COALESCE(episode, -1) = COALESCE(?, -1)
                """, (target_pid, tmdb_id, mtype, season, episode)).fetchone()
            if not match and title:
                match = conn.execute("""
                    SELECT id, position, duration, completed FROM watch_history
                    WHERE profile_id=? AND title=? AND type=?
                      AND COALESCE(season, -1) = COALESCE(?, -1)
                      AND COALESCE(episode, -1) = COALESCE(?, -1)
                """, (target_pid, title, mtype, season, episode)).fetchone()

            if match:
                # Update if incoming record is more recent or further along
                if (hh["position"] or 0) > (match["position"] or 0) or hh["completed"]:
                    conn.execute("""
                        UPDATE watch_history SET
                            position = ?, duration = ?, completed = ?, updated_at = ?
                        WHERE id = ?
                    """, (
                        max(hh["position"] or 0, match["position"] or 0),
                        max(hh["duration"] or 0, match["duration"] or 0),
                        1 if (hh["completed"] or match["completed"]) else 0,
                        hh["updated_at"], match["id"]
                    ))
            else:
                conn.execute("""
                    INSERT INTO watch_history (
                        profile_id, tmdb_id, title, type, season, episode, ep_title,
                        genres, year, poster_path, position, duration, completed, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    target_pid, tmdb_id, title, mtype, season, episode, hh["ep_title"],
                    hh["genres"], hh["year"], hh["poster_path"], hh["position"],
                    hh["duration"], hh["completed"], hh["updated_at"]
                ))
                restored_history += 1

        # 3. Merge Achievements
        try:
            host_achievements = [dict(r) for r in h_conn.execute("SELECT * FROM achievements").fetchall()]
            for ha in host_achievements:
                target_pid = profile_map.get(ha["profile_id"], default_local_pid)
                conn.execute("""
                    INSERT OR IGNORE INTO achievements (profile_id, achievement_id, unlocked_at)
                    VALUES (?, ?, ?)
                """, (target_pid, ha["achievement_id"], ha["unlocked_at"]))
        except Exception:
            pass

        # 4. Re-link Active Watch Progress For All Media on the Drive
        # This checks watch_history for every movie/episode on the new drive and restores watch_progress!
        media_items = [dict(r) for r in conn.execute("SELECT * FROM media").fetchall()]
        relinked_progress = 0
        for m in media_items:
            restored = restore_progress_for_media(m, conn=conn)
            if restored:
                relinked_progress += 1

        # 5. Restore Custom Profile Avatars
        host_avatars_dir = os.path.join(sync_dir, "avatars")
        local_avatars_dir = os.path.join(DATA_DIR, "avatars")
        os.makedirs(local_avatars_dir, exist_ok=True)
        restored_avatars = 0
        if os.path.isdir(host_avatars_dir):
            for fname in os.listdir(host_avatars_dir):
                src_av = os.path.join(host_avatars_dir, fname)
                dst_av = os.path.join(local_avatars_dir, fname)
                if os.path.isfile(src_av) and not os.path.exists(dst_av):
                    try:
                        shutil.copy2(src_av, dst_av)
                        restored_avatars += 1
                    except Exception:
                        pass

        # 6. Merge Playlists & Items
        try:
            host_pls = [dict(r) for r in h_conn.execute("SELECT * FROM playlists").fetchall()]
            for hpl in host_pls:
                target_pid = profile_map.get(hpl["profile_id"], default_local_pid)
                existing_pl = conn.execute(
                    "SELECT id FROM playlists WHERE profile_id=? AND name=?",
                    (target_pid, hpl["name"])
                ).fetchone()

                if existing_pl:
                    target_pl_id = existing_pl["id"]
                else:
                    cur = conn.execute("""
                        INSERT INTO playlists (profile_id, name, description, is_shared, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        target_pid, hpl["name"], hpl.get("description", ""),
                        hpl.get("is_shared", 0), hpl.get("created_at"), hpl.get("updated_at")
                    ))
                    target_pl_id = cur.lastrowid

                # Match playlist items against new drive media by tmdb_id/title
                items_sync = [dict(r) for r in h_conn.execute(
                    "SELECT * FROM playlist_items_sync WHERE playlist_id=?", (hpl["id"],)
                ).fetchall()]

                for item in items_sync:
                    target_m = None
                    if item.get("tmdb_id"):
                        target_m = conn.execute(
                            "SELECT id FROM media WHERE tmdb_id=? AND type=? LIMIT 1",
                            (item["tmdb_id"], item["type"])
                        ).fetchone()
                    if not target_m and item.get("title"):
                        target_m = conn.execute(
                            "SELECT id FROM media WHERE title=? AND type=? LIMIT 1",
                            (item["title"], item["type"])
                        ).fetchone()

                    if target_m:
                        conn.execute("""
                            INSERT OR IGNORE INTO playlist_items (playlist_id, media_id, position, added_at)
                            VALUES (?, ?, ?, ?)
                        """, (target_pl_id, target_m["id"], item["position"], item["added_at"]))
        except Exception as pl_err:
            print("[HostSync] Playlist import notice:", pl_err)

        # 7. Merge Favorites
        try:
            host_favs = [dict(r) for r in h_conn.execute("SELECT * FROM favorites_sync").fetchall()]
            for fav in host_favs:
                target_pid = profile_map.get(fav["profile_id"], default_local_pid)
                target_m = None
                if fav.get("tmdb_id"):
                    target_m = conn.execute(
                        "SELECT id FROM media WHERE tmdb_id=? AND type=? LIMIT 1",
                        (fav["tmdb_id"], fav["type"])
                    ).fetchone()
                if not target_m and fav.get("title"):
                    target_m = conn.execute(
                        "SELECT id FROM media WHERE title=? AND type=? LIMIT 1",
                        (fav["title"], fav["type"])
                    ).fetchone()

                if target_m:
                    conn.execute("""
                        INSERT OR IGNORE INTO favorites (profile_id, media_id, added_at)
                        VALUES (?, ?, ?)
                    """, (target_pid, target_m["id"], fav["added_at"]))
        except Exception as fav_err:
            print("[HostSync] Favorites import notice:", fav_err)

        conn.commit()
        h_conn.close()

        return {
            "ok": True,
            "message": "User profiles, watch history, and progress successfully merged from Documents.",
            "drive_tag": tag,
            "sync_dir": sync_dir,
            "restored_profiles": restored_profiles,
            "restored_history": restored_history,
            "relinked_progress": relinked_progress,
            "restored_avatars": restored_avatars
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to import user data: {str(e)}"}
    finally:
        if close_local and conn:
            conn.close()


def open_host_sync_folder(custom_tag: str = None) -> dict:
    """
    Open the host PC Documents/CapsStream/<Drive_Tag> folder in Windows Explorer or default file manager.
    """
    sync_dir = get_host_sync_dir(custom_tag)
    os.makedirs(sync_dir, exist_ok=True)

    try:
        if platform.system() == "Windows":
            os.startfile(sync_dir)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", sync_dir])
        else:
            subprocess.Popen(["xdg-open", sync_dir])
        return {"ok": True, "path": sync_dir, "drive_tag": get_drive_tag(custom_tag)}
    except Exception as e:
        return {"ok": False, "error": f"Could not open directory: {str(e)}", "path": sync_dir}
