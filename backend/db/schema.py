# -*- coding: utf-8 -*-
import os
import json
import shutil
import sqlite3
from .connection import get_conn, DB_PATH, TEMPLATE_DB_PATH, DATA_DIR, _apply_pragmas

def init_db():
    """Create all tables if they don't exist. Copies template DB if missing."""
    data_dir = os.path.dirname(DB_PATH)
    os.makedirs(data_dir, exist_ok=True)

    if not os.path.exists(DB_PATH) and os.path.exists(TEMPLATE_DB_PATH):
        shutil.copy2(TEMPLATE_DB_PATH, DB_PATH)
        print(f"[DB] Copied fresh master template database to {DB_PATH}")

    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            type          TEXT NOT NULL CHECK(type IN ('movie','series','anime')),
            tmdb_id       INTEGER,
            title         TEXT NOT NULL,
            original_title TEXT,
            year          INTEGER,
            season        INTEGER,
            episode       INTEGER,
            ep_title      TEXT,
            file_path     TEXT NOT NULL UNIQUE,
            file_size     INTEGER DEFAULT 0,
            duration      INTEGER,
            added_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            genres        TEXT,
            rating        REAL DEFAULT 0,
            vote_count    INTEGER DEFAULT 0,
            overview      TEXT,
            tagline       TEXT,
            poster_path   TEXT,
            backdrop_path TEXT,
            logo_path     TEXT,
            trailer_key   TEXT,
            cast_json     TEXT,
            tmdb_matched  INTEGER DEFAULT 0,
            manually_overridden INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            pin_hash   TEXT,
            avatar     TEXT DEFAULT 'ph-film-strip',
            color      TEXT DEFAULT '#e50914',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS watch_progress (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            media_id   INTEGER NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            duration   INTEGER DEFAULT 0,
            completed  INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(profile_id, media_id),
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS collections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            cover_id    INTEGER,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id INTEGER NOT NULL,
            media_id      INTEGER NOT NULL,
            sort_order    INTEGER DEFAULT 0,
            PRIMARY KEY (collection_id, media_id),
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS favorites (
            profile_id INTEGER NOT NULL,
            media_id   INTEGER NOT NULL,
            added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (profile_id, media_id),
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS achievements (
            profile_id     INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (profile_id, achievement_id),
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS kids_overrides (
            profile_id INTEGER NOT NULL DEFAULT 0,
            tmdb_id    INTEGER NOT NULL,
            action     TEXT NOT NULL CHECK(action IN ('allow','block')),
            title      TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (profile_id, tmdb_id)
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS playlist_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            media_id    INTEGER NOT NULL,
            position    INTEGER NOT NULL DEFAULT 0,
            added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);
        CREATE INDEX IF NOT EXISTS idx_media_tmdb ON media(tmdb_id);
        CREATE INDEX IF NOT EXISTS idx_media_title ON media(title);
        CREATE INDEX IF NOT EXISTS idx_progress_profile ON watch_progress(profile_id);
        CREATE INDEX IF NOT EXISTS idx_favorites_profile ON favorites(profile_id);
        CREATE INDEX IF NOT EXISTS idx_playlists_prof ON playlists(profile_id);
        CREATE INDEX IF NOT EXISTS idx_playlist_items_pl ON playlist_items(playlist_id, position);
        CREATE INDEX IF NOT EXISTS idx_watch_progress_prof_upd ON watch_progress(profile_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_watch_progress_prof_med ON watch_progress(profile_id, media_id);
        CREATE INDEX IF NOT EXISTS idx_watch_progress_prof_comp_upd ON watch_progress(profile_id, completed, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_favorites_prof_add ON favorites(profile_id, added_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_type_rating ON media(type, rating DESC);
        CREATE INDEX IF NOT EXISTS idx_media_type_added ON media(type, added_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_added ON media(added_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_title_season_ep ON media(title, season, episode);
    """)

    # Migration guards for media table columns
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                profile_id     INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (profile_id, achievement_id),
                FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
            );
        """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(media)").fetchall()]
        if "added_at" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN added_at DATETIME DEFAULT CURRENT_TIMESTAMP")
        if "tmdb_matched" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN tmdb_matched INTEGER DEFAULT 0")
        if "manually_overridden" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN manually_overridden INTEGER DEFAULT 0")
        if "logo_path" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN logo_path TEXT")
            print("[DB] Migrated: added logo_path column to media")
        if "imdb_id" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN imdb_id TEXT")
            print("[DB] Migrated: added imdb_id column to media")
        if "certification" not in cols:
            conn.execute("ALTER TABLE media ADD COLUMN certification TEXT")
            print("[DB] Migrated: added certification column to media")
        
        for sc in ["recap_start", "recap_end", "intro_start", "intro_end", "outro_start", "outro_end", "preview_start", "preview_end"]:
            if sc not in cols:
                conn.execute(f"ALTER TABLE media ADD COLUMN {sc} INTEGER DEFAULT 0")
                print(f"[DB] Migrated: added {sc} column to media")
    except Exception as e:
        print("[DB] Migration notice:", e)

    # Migration guard for profiles table — kids mode
    try:
        pcols = [r["name"] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
        if "is_kids" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN is_kids INTEGER DEFAULT 0")
            print("[DB] Migrated: added is_kids column to profiles")
        if "daily_limit_minutes" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN daily_limit_minutes INTEGER DEFAULT 0")
            print("[DB] Migrated: added daily_limit_minutes column to profiles")
        if "bedtime_curfew" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN bedtime_curfew TEXT DEFAULT ''")
            print("[DB] Migrated: added bedtime_curfew column to profiles")
        if "theme" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN theme TEXT DEFAULT 'crimson'")
            print("[DB] Migrated: added theme column to profiles")
        if "is_admin" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN is_admin INTEGER DEFAULT 0")
            print("[DB] Migrated: added is_admin column to profiles")
        if "custom_avatar_url" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN custom_avatar_url TEXT DEFAULT ''")
            print("[DB] Migrated: added custom_avatar_url column to profiles")
        if "maturity_rating" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN maturity_rating TEXT DEFAULT 'All'")
            print("[DB] Migrated: added maturity_rating column to profiles")
        if "blocked_genres" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN blocked_genres TEXT DEFAULT ''")
            print("[DB] Migrated: added blocked_genres column to profiles")
        if "default_audio_lang" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN default_audio_lang TEXT DEFAULT ''")
            print("[DB] Migrated: added default_audio_lang column to profiles")
        if "default_sub_lang" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN default_sub_lang TEXT DEFAULT ''")
            print("[DB] Migrated: added default_sub_lang column to profiles")
        if "position" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN position INTEGER DEFAULT 0")
            print("[DB] Migrated: added position column to profiles")
        if "auto_lock_minutes" not in pcols:
            conn.execute("ALTER TABLE profiles ADD COLUMN auto_lock_minutes INTEGER DEFAULT 0")
            print("[DB] Migrated: added auto_lock_minutes column to profiles")

        # Guarantee at least one admin profile exists if profiles exist
        conn.execute("""
            UPDATE profiles SET is_admin = 1
            WHERE id = (SELECT id FROM profiles WHERE is_kids = 0 ORDER BY id ASC LIMIT 1)
            AND NOT EXISTS (SELECT 1 FROM profiles WHERE is_admin = 1)
        """)
    except Exception as e:
        print("[DB] Migration notice:", e)


    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


# ─── Media Queries ────────────────────────────────────────────────────────────

