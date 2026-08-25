"""
db.py — SQLite database schema, initialization, and query helpers for CapsStream.
"""

import sqlite3
import os
import shutil

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "capsstream.db")
TEMPLATE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "templates", "fresh_capsstream.db")


def get_conn():
    """Get a SQLite connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
            avatar     TEXT DEFAULT '🎬',
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

        CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);
        CREATE INDEX IF NOT EXISTS idx_media_tmdb ON media(tmdb_id);
        CREATE INDEX IF NOT EXISTS idx_media_title ON media(title);
        CREATE INDEX IF NOT EXISTS idx_progress_profile ON watch_progress(profile_id);
        CREATE INDEX IF NOT EXISTS idx_favorites_profile ON favorites(profile_id);
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
    except Exception as e:
        print("[DB] Migration notice:", e)


    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


# ─── Media Queries ────────────────────────────────────────────────────────────

_DRIVE_MOUNT_CACHE = {}
_DRIVE_MOUNT_CACHE_TIME = 0

def is_drive_mounted(file_path):
    """Check if the drive root of a file path is mounted, cached for 5 seconds."""
    global _DRIVE_MOUNT_CACHE, _DRIVE_MOUNT_CACHE_TIME
    import time
    now = time.time()
    if now - _DRIVE_MOUNT_CACHE_TIME > 5:
        _DRIVE_MOUNT_CACHE = {}
        _DRIVE_MOUNT_CACHE_TIME = now

    if not file_path:
        return True

    drive = os.path.splitdrive(file_path)[0]
    if drive:
        drive_root = drive + os.sep
        if drive_root in _DRIVE_MOUNT_CACHE:
            return _DRIVE_MOUNT_CACHE[drive_root]
        mounted = os.path.exists(drive_root)
        _DRIVE_MOUNT_CACHE[drive_root] = mounted
        return mounted

    return True


def is_item_mounted(item):
    """Fast check if the media file drive is mounted."""
    if not item:
        return False
    file_path = item.get("file_path")
    if file_path:
        return is_drive_mounted(file_path)
    return True


def enrich_mounted(item):
    if isinstance(item, dict):
        item["is_mounted"] = is_item_mounted(item)
    return item


def get_disabled_path_roots(cfg=None):
    if cfg is None:
        try:
            from backend.settings import load_config
            cfg = load_config()
        except Exception:
            return []

    disabled_cfg = cfg.get("disabled_paths", {})
    all_disabled = []
    if isinstance(disabled_cfg, dict):
        for cat_paths in disabled_cfg.values():
            if isinstance(cat_paths, list):
                all_disabled.extend(cat_paths)
    elif isinstance(disabled_cfg, list):
        all_disabled.extend(disabled_cfg)

    from backend.settings import ROOT_DIR
    roots = []
    for p in all_disabled:
        if not p or not str(p).strip():
            continue
        p_str = str(p).strip()
        abs_p = p_str if os.path.isabs(p_str) else os.path.join(ROOT_DIR, p_str)
        clean_p = abs_p.replace("/", "\\").lower().rstrip("\\")
        if clean_p:
            roots.append(clean_p)
    return roots


def is_file_path_disabled(file_path, disabled_roots=None):
    if not file_path:
        return False
    if disabled_roots is None:
        disabled_roots = get_disabled_path_roots()
    if not disabled_roots:
        return False

    fp = file_path.replace("/", "\\").lower()
    for root in disabled_roots:
        if fp == root or fp.startswith(root + "\\"):
            return True
    return False


def is_item_disabled(item, disabled_roots=None):
    if not item or not isinstance(item, dict):
        return False
    fp = item.get("file_path")
    return is_file_path_disabled(fp, disabled_roots)



def get_all_sources_for_media(media):
    """
    Find all media records in SQLite for the same title/episode across multiple sources.
    """
    if not media:
        return []
    if isinstance(media, (int, str)):
        conn = get_conn()
        row = conn.execute("SELECT * FROM media WHERE id=?", (int(media),)).fetchone()
        conn.close()
        if not row:
            return []
        media = dict(row)

    conn = get_conn()
    tmdb_id = media.get("tmdb_id")
    mtype = media.get("type", "movie")
    season = media.get("season")
    episode = media.get("episode")
    title = media.get("title")

    if tmdb_id:
        if mtype in ("series", "anime"):
            sql = "SELECT * FROM media WHERE tmdb_id=? AND type=? AND season IS ? AND episode IS ?"
            rows = conn.execute(sql, (tmdb_id, mtype, season, episode)).fetchall()
        else:
            sql = "SELECT * FROM media WHERE tmdb_id=? AND type=?"
            rows = conn.execute(sql, (tmdb_id, mtype)).fetchall()
    else:
        if mtype in ("series", "anime"):
            sql = "SELECT * FROM media WHERE title=? AND type=? AND season IS ? AND episode IS ?"
            rows = conn.execute(sql, (title, mtype, season, episode)).fetchall()
        else:
            sql = "SELECT * FROM media WHERE title=? AND type=?"
            rows = conn.execute(sql, (title, mtype)).fetchall()

    conn.close()
    items = [dict(r) for r in rows]

    # For series/anime: distinct filenames inside the SAME directory are separate episodes, never quality options!
    if mtype in ("series", "anime") and len(items) > 1 and isinstance(media, dict) and media.get("file_path"):
        target_dir = os.path.dirname(media["file_path"])
        target_file = os.path.basename(media["file_path"])
        same_dir_items = [i for i in items if os.path.dirname(i.get("file_path", "")) == target_dir]
        if len(same_dir_items) > 1:
            items = [
                i for i in items 
                if os.path.dirname(i.get("file_path", "")) != target_dir or os.path.basename(i.get("file_path", "")) == target_file
            ]

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [i for i in items if not is_item_disabled(i, disabled_roots)]

    for item in items:
        item["is_mounted"] = is_item_mounted(item)
    return items


def resolve_best_media(media):
    """
    Returns the single best media dict among all duplicates across sources:
    1. Prefer mounted (is_mounted == True) over unmounted.
    2. Among mounted (or unmounted), prefer higher file_size (quality/bitrate).
    """
    sources = get_all_sources_for_media(media)
    if not sources:
        return enrich_mounted(media) if isinstance(media, dict) else None

    sources.sort(key=lambda s: (1 if s.get("is_mounted") else 0, s.get("file_size") or 0), reverse=True)
    best = dict(sources[0])
    best["has_duplicates"] = len(sources) > 1
    best["total_sources"] = len(sources)
    return best


def get_best_media_source(media_id):
    """
    Given a media_id, fetch record and automatically fall back to best mounted copy if unmounted.
    """
    media = get_media_by_id(media_id)
    if not media:
        return None
    if media.get("is_mounted"):
        return media

    best = resolve_best_media(media)
    return best if best else media


def format_file_size_bytes(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return ""
    tb = bytes_val / (1024 ** 4)
    if tb >= 1.0:
        return f"{tb:.2f} TB" if tb < 10 else f"{tb:.1f} TB"
    gb = bytes_val / (1024 ** 3)
    if gb >= 1.0:
        return f"{gb:.2f} GB" if gb < 10 else f"{gb:.1f} GB"
    mb = bytes_val / (1024 ** 2)
    return f"{mb:.0f} MB"


def get_media_quality_options(media_id):
    """
    Finds all mounted source copies of the media file, probes their video resolution,
    and returns a list of formatted quality options.
    Only movies support multi-drive quality switching. Series/anime always return a single option.
    """
    media = get_media_by_id(media_id)
    if not media:
        return []

    # Series and anime episodes are individual — never group as quality options
    if media.get("type") in ("series", "anime"):
        return [{
            "media_id": media["id"],
            "file_path": media.get("file_path", ""),
            "resolution": "Default",
            "display_label": "Default",
            "size_str": format_file_size_bytes(media.get("file_size")),
            "file_size": media.get("file_size") or 0,
            "is_current": True,
        }]

    sources = get_all_sources_for_media(media)
    mounted_sources = [s for s in sources if s.get("is_mounted")]
    if not mounted_sources:
        mounted_sources = [media]

    from backend.video_probe import probe_video_resolution

    # Sort sources by file size descending
    mounted_sources.sort(key=lambda s: s.get("file_size") or 0, reverse=True)

    # Probe every source once and remember its resolution label
    probed = []
    for s in mounted_sources:
        probe_res = probe_video_resolution(s["file_path"])
        res_label = probe_res.get("label") or "Standard Quality"
        probed.append((s, res_label))

    current_label = next((lbl for s, lbl in probed if s["id"] == media_id), None)
    if current_label is None and probed:
        current_label = probed[0][1]

    # Only offer quality switching when at least one alternative file has a
    # DIFFERENT resolution than the current one — same-resolution duplicates
    # (or single files) should not show a Quality dropdown at all.
    distinct_labels = {lbl for _, lbl in probed}
    if len(distinct_labels) <= 1:
        return [{
            "media_id": media["id"],
            "file_path": media.get("file_path", ""),
            "resolution": current_label,
            "display_label": current_label,
            "size_str": format_file_size_bytes(media.get("file_size")),
            "file_size": media.get("file_size") or 0,
            "is_current": True,
        }]

    options = []
    seen_labels = set()

    for idx, (s, res_label) in enumerate(probed):
        size_str = format_file_size_bytes(s.get("file_size"))
        display_label = res_label
        if res_label in seen_labels and size_str:
            display_label = f"{res_label} ({size_str})"
        seen_labels.add(res_label)

        options.append({
            "media_id": s["id"],
            "file_path": s["file_path"],
            "resolution": res_label,
            "display_label": display_label,
            "size_str": size_str,
            "file_size": s.get("file_size") or 0,
            "is_current": s["id"] == media_id
        })

    return options


def enrich_mounted_list(items):
    if not items:
        return []

    try:
        from backend.settings import load_config
        cfg = load_config()
        disabled_roots = get_disabled_path_roots(cfg)
    except Exception:
        cfg = {}
        disabled_roots = []

    # Hide media items from disabled storage locations
    if disabled_roots:
        items = [item for item in items if isinstance(item, dict) and not is_item_disabled(item, disabled_roots)]

    # Fast in-memory drive mount enrichment without nested SQL queries per item
    for item in items:
        if isinstance(item, dict):
            item["is_mounted"] = is_item_mounted(item)

    if cfg.get("hide_unmounted_items", False):
        items = [item for item in items if isinstance(item, dict) and item.get("is_mounted", True)]

    return items


def get_all_media(media_type=None):
    conn = get_conn()
    if media_type:
        rows = conn.execute(
            "SELECT * FROM media WHERE type=? ORDER BY title, season, episode", (media_type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM media ORDER BY added_at DESC"
        ).fetchall()
    conn.close()
    return enrich_mounted_list([dict(r) for r in rows])


def get_media_by_id(media_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    if is_item_disabled(item):
        return None
    return enrich_mounted(item)


def update_skip_timestamps(media_id, data):
    """
    Updates recap/intro/outro/preview skip markers for a media item.
    Values are seconds (int). A 0/0 pair is a valid "confirmed none" sentinel.
    Only provided segment keys are touched — absent keys keep old values.
    """
    if not media_id or not isinstance(data, dict):
        return False

    fields = {}
    for name in ("recap", "intro", "outro", "preview"):
        for bound in ("start", "end"):
            key = f"{name}_{bound}"
            if key in data:
                try:
                    fields[key] = int(float(data.get(key) or 0))
                except (TypeError, ValueError):
                    fields[key] = 0

    if not fields:
        return False

    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE media SET {sets} WHERE id=?",
        (*fields.values(), media_id),
    )
    conn.commit()
    conn.close()
    return True


def get_media_by_tmdb(tmdb_id, media_type=None):
    conn = get_conn()
    if media_type:
        rows = conn.execute(
            "SELECT * FROM media WHERE tmdb_id=? AND type=? ORDER BY season, episode",
            (tmdb_id, media_type)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM media WHERE tmdb_id=? ORDER BY season, episode", (tmdb_id,)
        ).fetchall()
    conn.close()

    items = [dict(r) for r in rows]
    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [ep for ep in items if not is_item_disabled(ep, disabled_roots)]

    grouped = {}
    for ep in items:
        key = (ep.get("season"), ep.get("episode"))
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(ep)

    deduped = []
    for key, candidates in grouped.items():
        candidates.sort(key=lambda s: (1 if is_item_mounted(s) else 0, s.get("file_size") or 0), reverse=True)
        best = dict(candidates[0])
        best["is_mounted"] = is_item_mounted(best)
        deduped.append(best)

    return sorted(deduped, key=lambda e: (e.get("season") or 0, e.get("episode") or 0))


def search_media(query, media_type=None, genre=None):
    conn = get_conn()
    params = [f"%{query}%", f"%{query}%"]
    sql = "SELECT * FROM media WHERE (title LIKE ? OR ep_title LIKE ?)"
    if media_type:
        sql += " AND type=?"
        params.append(media_type)
    if genre:
        sql += " AND genres LIKE ?"
        params.append(f"%{genre}%")
    sql += " ORDER BY rating DESC, title"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return enrich_mounted_list([dict(r) for r in rows])


def get_unique_shows(media_type=None):
    """Return one row per show/movie (grouped by tmdb_id or title)."""
    conn = get_conn()
    type_filter = f"WHERE type='{media_type}'" if media_type else ""
    rows = conn.execute(f"""
        SELECT * FROM media
        {type_filter}
        ORDER BY added_at DESC
    """).fetchall()
    conn.close()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    grouped = {}
    for item in items:
        key = item.get("tmdb_id") or item.get("title")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = item
        else:
            if not grouped[key].get("poster_path") and item.get("poster_path"):
                grouped[key] = item

    result = list(grouped.values())
    result.sort(key=lambda x: (x.get("title") or "").lower())
    return enrich_mounted_list(result)


def get_recently_added(limit=20):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM media
        ORDER BY added_at DESC
    """).fetchall()
    conn.close()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    grouped = {}
    for item in items:
        key = item.get("tmdb_id") or item.get("title")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = item

    result = list(grouped.values())
    result.sort(key=lambda x: x.get("added_at") or 0, reverse=True)
    return enrich_mounted_list(result[:limit])


def get_top_rated(limit=20, media_type=None):
    conn = get_conn()
    type_filter = f"WHERE type='{media_type}'" if media_type else ""
    rows = conn.execute(f"""
        SELECT * FROM media
        {type_filter}
        ORDER BY rating DESC, vote_count DESC
    """).fetchall()
    conn.close()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    grouped = {}
    for item in items:
        if not (item.get("rating") and item["rating"] > 0):
            continue
        key = item.get("tmdb_id") or item.get("title")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = item

    result = list(grouped.values())
    result.sort(key=lambda x: (x.get("rating") or 0, x.get("vote_count") or 0), reverse=True)
    return enrich_mounted_list(result[:limit])


def get_by_genre(genre, limit=20):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM media
        WHERE genres LIKE ?
        ORDER BY rating DESC
    """, (f"%{genre}%",)).fetchall()
    conn.close()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    grouped = {}
    for item in items:
        key = item.get("tmdb_id") or item.get("title")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = item

    result = list(grouped.values())
    result.sort(key=lambda x: x.get("rating") or 0, reverse=True)
    return enrich_mounted_list(result[:limit])


def get_random_pick(limit=10):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM media
        WHERE poster_path IS NOT NULL
    """).fetchall()
    conn.close()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    grouped = {}
    for item in items:
        key = item.get("tmdb_id") or item.get("title")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = item

    import random
    result = list(grouped.values())
    random.shuffle(result)
    return enrich_mounted_list(result[:limit])


def get_all_genres():
    conn = get_conn()
    rows = conn.execute("SELECT genres FROM media WHERE genres IS NOT NULL").fetchall()
    conn.close()
    genres = set()
    for row in rows:
        if row["genres"]:
            for g in row["genres"].split(","):
                g = g.strip()
                if g:
                    genres.add(g)
    return sorted(genres)



def upsert_media(data):
    """Insert or update a media row. Returns the row id."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM media WHERE file_path=?", (data["file_path"],)
    ).fetchone()

    if existing:
        row_id = existing["id"]
        # Only update metadata fields, not the file_path
        conn.execute("""
            UPDATE media SET
                tmdb_id=?, title=?, original_title=?, year=?, season=?, episode=?,
                ep_title=?, file_size=?, genres=?, rating=?, vote_count=?,
                overview=?, tagline=?, poster_path=?, backdrop_path=?, logo_path=?,
                trailer_key=?, cast_json=?, tmdb_matched=?, type=?
            WHERE id=?
        """, (
            data.get("tmdb_id"), data.get("title"), data.get("original_title"),
            data.get("year"), data.get("season"), data.get("episode"),
            data.get("ep_title"), data.get("file_size", 0),
            data.get("genres"), data.get("rating", 0), data.get("vote_count", 0),
            data.get("overview"), data.get("tagline"),
            data.get("poster_path"), data.get("backdrop_path"), data.get("logo_path"),
            data.get("trailer_key"), data.get("cast_json"),
            1 if data.get("tmdb_id") else 0,
            data.get("type"), row_id
        ))
    else:
        cur = conn.execute("""
            INSERT INTO media (
                type, tmdb_id, title, original_title, year, season, episode,
                ep_title, file_path, file_size, genres, rating, vote_count,
                overview, tagline, poster_path, backdrop_path, logo_path,
                trailer_key, cast_json, tmdb_matched
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("type"), data.get("tmdb_id"), data.get("title"),
            data.get("original_title"), data.get("year"),
            data.get("season"), data.get("episode"), data.get("ep_title"),
            data["file_path"], data.get("file_size", 0),
            data.get("genres"), data.get("rating", 0), data.get("vote_count", 0),
            data.get("overview"), data.get("tagline"),
            data.get("poster_path"), data.get("backdrop_path"), data.get("logo_path"),
            data.get("trailer_key"), data.get("cast_json"),
            1 if data.get("tmdb_id") else 0
        ))
        row_id = cur.lastrowid

    conn.commit()
    conn.close()
    return row_id


def update_duration(media_id, duration):
    conn = get_conn()
    conn.execute("UPDATE media SET duration=? WHERE id=?", (duration, media_id))
    conn.commit()
    conn.close()


def get_unmatched():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM media WHERE tmdb_matched=0 ORDER BY title"
    ).fetchall()
    conn.close()
    return enrich_mounted_list([dict(r) for r in rows])


# ─── Profile Queries ──────────────────────────────────────────────────────────

def get_all_profiles():
    conn = get_conn()
    rows = conn.execute("SELECT id, name, avatar, color, is_kids, (CASE WHEN pin_hash IS NOT NULL AND pin_hash != '' THEN 1 ELSE 0 END) as has_pin, created_at FROM profiles").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_profile(profile_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_profile(name, pin_hash, avatar="🎦", color="#e50914", is_kids=False):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO profiles (name, pin_hash, avatar, color, is_kids) VALUES (?,?,?,?,?)",
        (name, pin_hash, avatar, color, 1 if is_kids else 0)
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_profile(profile_id, name, pin_hash=None, avatar="🎦", color="#e50914", is_kids=False, update_pin=False):
    conn = get_conn()
    if is_kids:
        pin_hash = None
        update_pin = True

    if update_pin:
        conn.execute(
            "UPDATE profiles SET name=?, pin_hash=?, avatar=?, color=?, is_kids=? WHERE id=?",
            (name, pin_hash, avatar, color, 1 if is_kids else 0, profile_id)
        )
    else:
        conn.execute(
            "UPDATE profiles SET name=?, avatar=?, color=?, is_kids=? WHERE id=?",
            (name, avatar, color, 1 if is_kids else 0, profile_id)
        )
    conn.commit()
    conn.close()


def delete_profile(profile_id):
    conn = get_conn()
    conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
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
    if row["pin_hash"] is None:
        return True  # No PIN set
    return row["pin_hash"] == pin_hash


# ─── Watch Progress Queries ───────────────────────────────────────────────────

def get_progress(profile_id, media_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM watch_progress WHERE profile_id=? AND media_id=?",
        (profile_id, media_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_progress(profile_id, media_id, position, duration=0, completed=False):
    conn = get_conn()
    conn.execute("""
        INSERT INTO watch_progress (profile_id, media_id, position, duration, completed, updated_at)
        VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(profile_id, media_id) DO UPDATE SET
            position=excluded.position,
            duration=excluded.duration,
            completed=excluded.completed,
            updated_at=CURRENT_TIMESTAMP
    """, (profile_id, media_id, position, duration, 1 if completed else 0))
    conn.commit()
    conn.close()


def delete_progress(profile_id, media_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM watch_progress WHERE profile_id=? AND media_id=?",
        (profile_id, media_id)
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
        LIMIT ?
    """, (profile_id, limit)).fetchall()
    conn.close()
    return enrich_mounted_list([dict(r) for r in rows])


ACHIEVEMENTS = [
    {
        "id": "first_watch",
        "title": "First Steps",
        "icon": "\ud83c\udfac",
        "description": "Watch your first video title in CapsStream",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "marathoner",
        "title": "Marathon Runner",
        "icon": "\u23f1\ufe0f",
        "description": "Accumulate 5 hours of total watch time",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "binge_master",
        "title": "Binge Titan",
        "icon": "\ud83c\udfc6",
        "description": "Accumulate 24 hours of total watch time",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "century_watcher",
        "title": "100 Hour Club",
        "icon": "\u23f3",
        "description": "Accumulate 100 hours of total watch time",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "cinephile",
        "title": "Cinephile Legend",
        "icon": "\ud83c\udf7f",
        "description": "Complete 5 or more movies or episodes",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "master_completer",
        "title": "Master Completer",
        "icon": "\ud83d\udc8e",
        "description": "Complete 20 or more titles or episodes",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "titan_completer",
        "title": "Titan Completer",
        "icon": "\u26a1",
        "description": "Complete 50 or more titles or episodes",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "streak_3",
        "title": "3-Day Streak",
        "icon": "\ud83d\udd25",
        "description": "Watch media 3 days in a row",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "streak_7",
        "title": "Weekly Streak",
        "icon": "\ud83d\uddd3\ufe0f",
        "description": "Watch media every day for a full week",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "streak_30",
        "title": "Monthly Legend",
        "icon": "\u2b50",
        "description": "Watch media 30 days in a row",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "ten_titles",
        "title": "Ten Down",
        "icon": "\ud83c\udfaf",
        "description": "Watch at least 10 different library titles",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "fifty_titles",
        "title": "Library Veteran",
        "icon": "\ud83d\udcda",
        "description": "Watch at least 50 different library titles",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "hundred_titles",
        "title": "Centurion Streamer",
        "icon": "\ud83d\udc51",
        "description": "Watch at least 100 different library titles",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "quick_session",
        "title": "Quick Bite",
        "icon": "\u26a1",
        "description": "Complete a short watch session (under 15m)",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "long_session",
        "title": "Feature Length",
        "icon": "\ud83c\udfa5",
        "description": "Watch a single session over 2 hours long",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "marathon_session",
        "title": "Mega Marathon",
        "icon": "\ud83d\ude80",
        "description": "Watch a single continuous session over 4 hours long",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "first_finish",
        "title": "Finish Line",
        "icon": "\ud83c\udfc1",
        "description": "Complete your very first movie or show episode",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "halfway_there",
        "title": "Halfway Hero",
        "icon": "\ud83d\udcc8",
        "description": "Reach 50% completion on a series",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "season_finale",
        "title": "Season Finale",
        "icon": "\ud83c\udf86",
        "description": "Watch the final episode of any TV season",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "credits_roll",
        "title": "Roll Credits",
        "icon": "\ud83d\udcdc",
        "description": "Watch a movie all the way through to 100%",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "night_owl",
        "title": "Night Owl",
        "icon": "\ud83c\udf19",
        "description": "Watch a title late at night (12 AM - 4 AM)",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "early_bird",
        "title": "Early Bird",
        "icon": "\u2600\ufe0f",
        "description": "Watch a title early in the morning (5 AM - 8 AM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "midnight_marauder",
        "title": "Midnight Marauder",
        "icon": "\ud83c\udf0c",
        "description": "Start playing video exactly at midnight",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "lunchtime_streamer",
        "title": "Lunch Streamer",
        "icon": "\ud83c\udf71",
        "description": "Watch media during lunch hour (12 PM - 2 PM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "primetime_viewer",
        "title": "Prime Time",
        "icon": "\ud83d\udcfa",
        "description": "Watch media during evening prime time (8 PM - 10 PM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "weekend_warrior",
        "title": "Weekend Warrior",
        "icon": "\ud83c\udf89",
        "description": "Stream 5 or more titles during Saturday & Sunday",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "monday_blues",
        "title": "Monday Cure",
        "icon": "\u2615",
        "description": "Watch a movie or episode on a Monday",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "friday_night",
        "title": "Friday Movie Night",
        "icon": "\ud83c\udf7f",
        "description": "Stream a movie on Friday night",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "dawn_patrol",
        "title": "Dawn Patrol",
        "icon": "\ud83c\udf05",
        "description": "Watch media right at sunrise",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "afternoon_delight",
        "title": "Afternoon Matinee",
        "icon": "\ud83c\udf24\ufe0f",
        "description": "Watch a movie between 2 PM and 5 PM",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "daily_dose",
        "title": "Daily Ritual",
        "icon": "\ud83d\udcc6",
        "description": "Watch at least one title every day for 5 days",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "binge_session",
        "title": "Binge Session",
        "icon": "\ud83d\udd25",
        "description": "Watch 3 consecutive episodes in one sitting",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "triple_threat",
        "title": "Triple Feature",
        "icon": "\ud83c\udfac",
        "description": "Watch 3 full movies in a single day",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "all_nighter",
        "title": "All Nighter",
        "icon": "\ud83c\udf15",
        "description": "Stream continuously from 1 AM to 6 AM",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "tea_time",
        "title": "Tea Break",
        "icon": "\ud83c\udf75",
        "description": "Watch a short episode during afternoon tea time",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "clockwork",
        "title": "Like Clockwork",
        "icon": "\u23f0",
        "description": "Stream at the exact same hour 3 days in a row",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "holiday_binge",
        "title": "Holiday Binger",
        "icon": "\ud83c\udf84",
        "description": "Watch media during a weekend holiday",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "silent_watcher",
        "title": "Silent Watcher",
        "icon": "\ud83c\udfa7",
        "description": "Watch media late night with muted or low volume",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "marathon_master",
        "title": "Season Marathoner",
        "icon": "\ud83d\ude80",
        "description": "Finish an entire season of a show in under 48 hours",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "constant_streamer",
        "title": "Non-Stop Streamer",
        "icon": "\ud83d\udc8e",
        "description": "Log watch activity for 14 straight days",
        "category": "Viewing Habits",
        "rarity": "Platinum"
    },
    {
        "id": "speed_demon",
        "title": "Speed Demon",
        "icon": "\u26a1",
        "description": "Watch video content at accelerated speed (1.25x+)",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "double_speed",
        "title": "Lightning Speed",
        "icon": "\u23e9",
        "description": "Watch video at 2.0x maximum speed",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "slow_motion",
        "title": "Detail Analyst",
        "icon": "\ud83d\udc0c",
        "description": "Watch video at 0.5x slow-motion playback speed",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "sub_master",
        "title": "Subtitle Connoisseur",
        "icon": "\ud83d\udcac",
        "description": "Apply custom subtitles to your playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "sub_styler",
        "title": "Subtitle Architect",
        "icon": "\ud83c\udfa8",
        "description": "Customize subtitle font size, text color, or box opacity",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "audio_enthusiast",
        "title": "Audio Specialist",
        "icon": "\ud83c\udf99\ufe0f",
        "description": "Play media with multi-audio stream selection",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "volume_booster",
        "title": "Volume Overdrive",
        "icon": "\ud83d\udd0a",
        "description": "Boost audio volume past 100% up to 200% gain",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "skip_master",
        "title": "Skip Master",
        "icon": "\u23e9",
        "description": "Use Skip Intro or Skip Outro feature during playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "skip_champion",
        "title": "Skip Champion",
        "icon": "\u26a1",
        "description": "Use Skip Intro 10 or more times",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "fullscreen_pro",
        "title": "Immersion Master",
        "icon": "\ud83d\udda5\ufe0f",
        "description": "Toggle fullscreen mode for cinematic playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "resume_master",
        "title": "Resume Master",
        "icon": "\ud83d\udd04",
        "description": "Resume playback from where you previously left off",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "quality_switcher",
        "title": "Resolution Switcher",
        "icon": "\u2699\ufe0f",
        "description": "Switch video quality streams mid-playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "hd_master",
        "title": "HD Purist",
        "icon": "\ud83c\udfac",
        "description": "Watch content in 1080p Full HD resolution",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "four_k_king",
        "title": "4K Ultra HD King",
        "icon": "\ud83d\udc8e",
        "description": "Watch content in 4K Ultra HD resolution",
        "category": "Player Master",
        "rarity": "Platinum"
    },
    {
        "id": "seeker",
        "title": "Precision Seeker",
        "icon": "\ud83c\udfaf",
        "description": "Seek forward or backward using player controls",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "keyboard_ninja",
        "title": "Keyboard Ninja",
        "icon": "\u2328\ufe0f",
        "description": "Use keyboard shortcuts to control video",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "pip_master",
        "title": "Multitasker",
        "icon": "\ud83d\uddbc\ufe0f",
        "description": "Use Picture-in-Picture or pop-out window controls",
        "category": "Player Master",
        "rarity": "Gold"
    },
    {
        "id": "mute_master",
        "title": "Stealth Mode",
        "icon": "\ud83d\udd07",
        "description": "Mute and unmute playback using player controls",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "next_ep_advance",
        "title": "Auto Advancer",
        "icon": "\u23ed\ufe0f",
        "description": "Click Next Episode button to start subsequent episode",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "player_god",
        "title": "Player Grandmaster",
        "icon": "\ud83d\udc51",
        "description": "Use all core player features (subtitles, audio, speed, quality)",
        "category": "Player Master",
        "rarity": "Platinum"
    },
    {
        "id": "movie_buff",
        "title": "Movie Buff",
        "icon": "\ud83c\udf7f",
        "description": "Watch 3 or more Movie titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "series_addict",
        "title": "Series Addict",
        "icon": "\ud83d\udcfa",
        "description": "Watch 3 or more TV Series",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "otaku",
        "title": "Otaku Master",
        "icon": "\ud83c\udf8c",
        "description": "Watch 3 or more Anime titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "explorer",
        "title": "Genre Explorer",
        "icon": "\ud83d\udd0d",
        "description": "Watch titles across 3 or more distinct genres",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "genre_virtuoso",
        "title": "Genre Virtuoso",
        "icon": "\ud83e\udded",
        "description": "Watch titles across 8 or more distinct genres",
        "category": "Discovery",
        "rarity": "Gold"
    },
    {
        "id": "action_junkie",
        "title": "Action Hero",
        "icon": "\ud83d\udca5",
        "description": "Watch 3 or more Action movies or series",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "comedy_lover",
        "title": "Laugh Track",
        "icon": "\ud83d\ude02",
        "description": "Watch 3 or more Comedy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "drama_queen",
        "title": "Drama Enthusiast",
        "icon": "\ud83c\udfad",
        "description": "Watch 3 or more Drama titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "sci_fi_fan",
        "title": "Sci-Fi Voyager",
        "icon": "\ud83d\ude80",
        "description": "Watch 3 or more Sci-Fi & Fantasy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "horror_seeker",
        "title": "Thrill Seeker",
        "icon": "\ud83d\udc7b",
        "description": "Watch 3 or more Horror or Thriller titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "romance_hopeless",
        "title": "Hopeless Romantic",
        "icon": "\ud83d\udc96",
        "description": "Watch 3 or more Romance titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "docu_fanatic",
        "title": "Knowledge Seeker",
        "icon": "\ud83d\udcd6",
        "description": "Watch 2 or more Documentary titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "animation_fan",
        "title": "Toon Collector",
        "icon": "\ud83c\udfa8",
        "description": "Watch 3 or more Animated movies or shows",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "crime_detective",
        "title": "Master Detective",
        "icon": "\ud83d\udd75\ufe0f",
        "description": "Watch 3 or more Crime or Mystery titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "fantasy_realm",
        "title": "Realm Traveler",
        "icon": "\ud83e\uddd9\u200d\u2642\ufe0f",
        "description": "Watch 3 or more Fantasy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "trailer_buff",
        "title": "Trailer Aficionado",
        "icon": "\ud83c\udfad",
        "description": "Watch an official YouTube movie or show trailer",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "imdb_surfer",
        "title": "IMDb Explorer",
        "icon": "\u2b50",
        "description": "Click an IMDb link to view external movie metadata",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "search_master",
        "title": "Search Master",
        "icon": "\ud83d\udd0e",
        "description": "Use the search bar to find specific titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "filter_pro",
        "title": "Filter Pro",
        "icon": "\ud83d\udcd1",
        "description": "Filter media by genre or media type in the library",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "omni_viewer",
        "title": "Omni Viewer",
        "icon": "\ud83c\udf10",
        "description": "Watch movies, series, and anime all on one profile",
        "category": "Discovery",
        "rarity": "Gold"
    },
    {
        "id": "curator",
        "title": "Master Curator",
        "icon": "\u2b50",
        "description": "Add 3 or more titles to Watchlist or Collections",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "collection_king",
        "title": "Collection Architect",
        "icon": "\ud83d\udcc1",
        "description": "Create 3 or more custom media Collections",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "collection_empire",
        "title": "Collection Empire",
        "icon": "\ud83c\udfdb\ufe0f",
        "description": "Create 10 or more custom media Collections",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "fav_collector",
        "title": "Favorite Hoarder",
        "icon": "\u2764\ufe0f",
        "description": "Add 10 or more items to your Favorites list",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "fav_legend",
        "title": "Favorite Legend",
        "icon": "\ud83d\udc96",
        "description": "Add 25 or more items to your Favorites list",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "trophy_collector",
        "title": "Trophy Collector",
        "icon": "\ud83c\udfc6",
        "description": "Unlock 10 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "trophy_quarter",
        "title": "Trophy Specialist",
        "icon": "\ud83e\udd49",
        "description": "Unlock 25 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "trophy_half",
        "title": "Trophy Master",
        "icon": "\ud83e\udd48",
        "description": "Unlock 50 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "trophy_legend",
        "title": "Trophy Legend",
        "icon": "\ud83d\udc8e",
        "description": "Unlock 75 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Platinum"
    },
    {
        "id": "trophy_god",
        "title": "Grandmaster Completionist",
        "icon": "\ud83d\udc51",
        "description": "Unlock all 100 achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Platinum"
    },
    {
        "id": "storage_gigabyte",
        "title": "Storage Saver",
        "icon": "\ud83d\udcbe",
        "description": "Have over 10 GB of media mounted in your library",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "storage_terabyte",
        "title": "Terabyte Hoarder",
        "icon": "\ud83d\uddc4\ufe0f",
        "description": "Have over 100 GB of media mounted in your library",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "drive_mounter",
        "title": "Drive Mounter",
        "icon": "\ud83d\udd0c",
        "description": "Mount external storage paths or drives to your library",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "multi_drive",
        "title": "Multi-Drive Collector",
        "icon": "\ud83d\uddc2\ufe0f",
        "description": "Mount 3 or more distinct media folders or drives",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "hd_collector",
        "title": "HD Vault",
        "icon": "\ud83c\udfac",
        "description": "Have at least 10 HD or 4K titles in your media library",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "profile_customizer",
        "title": "Profile Stylist",
        "icon": "\ud83d\udc64",
        "description": "Customize your avatar icon or theme color",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "pin_defender",
        "title": "PIN Defender",
        "icon": "\ud83d\udd12",
        "description": "Secure your profile with a 4-digit security PIN",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "kids_creator",
        "title": "Family Guardian",
        "icon": "\ud83c\udf88",
        "description": "Create a Kids Safe Mode profile",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "scan_master",
        "title": "Library Scanner",
        "icon": "\ud83d\udd04",
        "description": "Run a manual library disk scan from settings",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "theme_master",
        "title": "Dark Mode Aficionado",
        "icon": "\u2728",
        "description": "Explore CapsStream premium dark theme interface",
        "category": "Collector",
        "rarity": "Bronze"
    }
]


def unlock_achievement(profile_id, achievement_id):
    if not profile_id or not achievement_id:
        return None
    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM achievements WHERE profile_id=? AND achievement_id=?",
        (profile_id, achievement_id)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO achievements (profile_id, achievement_id) VALUES (?,?)",
            (profile_id, achievement_id)
        )
        conn.commit()
        conn.close()
        ach = next((a for a in ACHIEVEMENTS if a["id"] == achievement_id), None)
        return ach
    conn.close()
    return None


def check_and_unlock_achievements(profile_id):
    conn = get_conn()

    unlocked_ids = set(
        r["achievement_id"] for r in conn.execute(
            "SELECT achievement_id FROM achievements WHERE profile_id=?", (profile_id,)
        ).fetchall()
    )

    new_unlocked = []

    stats_total = conn.execute("""
        SELECT SUM(position) as total_seconds, COUNT(*) as total_items, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as completed_items
        FROM watch_progress WHERE profile_id=?
    """, (profile_id,)).fetchone()

    total_seconds = stats_total["total_seconds"] or 0
    total_items = stats_total["total_items"] or 0
    completed_items = stats_total["completed_items"] or 0

    fav_cnt = conn.execute("SELECT COUNT(*) as c FROM favorites WHERE profile_id=?", (profile_id,)).fetchone()["c"]
    col_cnt = conn.execute("SELECT COUNT(*) as c FROM collections WHERE profile_id=?", (profile_id,)).fetchone()["c"]

    movie_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='movie'
    """, (profile_id,)).fetchone()["c"]

    series_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='series'
    """, (profile_id,)).fetchone()["c"]

    anime_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='anime'
    """, (profile_id,)).fetchone()["c"]

    # 1. Milestones
    if "first_watch" not in unlocked_ids and total_items > 0: new_unlocked.append("first_watch")
    if "marathoner" not in unlocked_ids and total_seconds >= 18000: new_unlocked.append("marathoner")
    if "binge_master" not in unlocked_ids and total_seconds >= 86400: new_unlocked.append("binge_master")
    if "century_watcher" not in unlocked_ids and total_seconds >= 360000: new_unlocked.append("century_watcher")
    if "cinephile" not in unlocked_ids and completed_items >= 5: new_unlocked.append("cinephile")
    if "master_completer" not in unlocked_ids and completed_items >= 20: new_unlocked.append("master_completer")
    if "titan_completer" not in unlocked_ids and completed_items >= 50: new_unlocked.append("titan_completer")
    if "ten_titles" not in unlocked_ids and total_items >= 10: new_unlocked.append("ten_titles")
    if "fifty_titles" not in unlocked_ids and total_items >= 50: new_unlocked.append("fifty_titles")
    if "hundred_titles" not in unlocked_ids and total_items >= 100: new_unlocked.append("hundred_titles")
    if "first_finish" not in unlocked_ids and completed_items >= 1: new_unlocked.append("first_finish")
    if "credits_roll" not in unlocked_ids and completed_items >= 1: new_unlocked.append("credits_roll")

    # 2. Discovery
    if "movie_buff" not in unlocked_ids and movie_cnt >= 3: new_unlocked.append("movie_buff")
    if "series_addict" not in unlocked_ids and series_cnt >= 3: new_unlocked.append("series_addict")
    if "otaku" not in unlocked_ids and anime_cnt >= 3: new_unlocked.append("otaku")
    if "omni_viewer" not in unlocked_ids and (movie_cnt > 0 and series_cnt > 0 and anime_cnt > 0): new_unlocked.append("omni_viewer")

    genre_rows = conn.execute("""
        SELECT DISTINCT m.genres FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.genres IS NOT NULL
    """, (profile_id,)).fetchall()
    distinct_genres = set()
    for gr in genre_rows:
        for g in (gr["genres"] or "").split(","):
            if g.strip(): distinct_genres.add(g.strip())
    if "explorer" not in unlocked_ids and len(distinct_genres) >= 3: new_unlocked.append("explorer")
    if "genre_virtuoso" not in unlocked_ids and len(distinct_genres) >= 8: new_unlocked.append("genre_virtuoso")

    # 3. Collector
    if "curator" not in unlocked_ids and (fav_cnt + col_cnt) >= 3: new_unlocked.append("curator")
    if "collection_king" not in unlocked_ids and col_cnt >= 3: new_unlocked.append("collection_king")
    if "collection_empire" not in unlocked_ids and col_cnt >= 10: new_unlocked.append("collection_empire")
    if "fav_collector" not in unlocked_ids and fav_cnt >= 10: new_unlocked.append("fav_collector")
    if "fav_legend" not in unlocked_ids and fav_cnt >= 25: new_unlocked.append("fav_legend")

    # 4. Viewing Habits
    if "night_owl" not in unlocked_ids:
        if conn.execute("SELECT 1 FROM watch_progress WHERE profile_id=? AND strftime('%H', updated_at) IN ('00','01','02','03','04')", (profile_id,)).fetchone():
            new_unlocked.append("night_owl")
    if "early_bird" not in unlocked_ids:
        if conn.execute("SELECT 1 FROM watch_progress WHERE profile_id=? AND strftime('%H', updated_at) IN ('05','06','07','08')", (profile_id,)).fetchone():
            new_unlocked.append("early_bird")

    # 5. Profile & Storage
    p_row = conn.execute("SELECT avatar, color, is_kids, pin_hash FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if p_row:
        if "pin_defender" not in unlocked_ids and p_row["pin_hash"]: new_unlocked.append("pin_defender")
        if "kids_creator" not in unlocked_ids and p_row["is_kids"]: new_unlocked.append("kids_creator")

    # 6. Trophy Case Collector Milestones
    current_total_unlocked = len(unlocked_ids) + len(new_unlocked)
    if "trophy_collector" not in unlocked_ids and current_total_unlocked >= 10: new_unlocked.append("trophy_collector")
    if "trophy_quarter" not in unlocked_ids and current_total_unlocked >= 25: new_unlocked.append("trophy_quarter")
    if "trophy_half" not in unlocked_ids and current_total_unlocked >= 50: new_unlocked.append("trophy_half")
    if "trophy_legend" not in unlocked_ids and current_total_unlocked >= 75: new_unlocked.append("trophy_legend")
    if "trophy_god" not in unlocked_ids and current_total_unlocked >= 99: new_unlocked.append("trophy_god")

    for aid in new_unlocked:
        conn.execute("INSERT OR IGNORE INTO achievements (profile_id, achievement_id) VALUES (?,?)", (profile_id, aid))

    if new_unlocked:
        conn.commit()

    conn.close()
    return new_unlocked


def get_profile_achievements(profile_id):
    conn = get_conn()
    check_and_unlock_achievements(profile_id)

    unlocked_rows = conn.execute(
        "SELECT achievement_id, unlocked_at FROM achievements WHERE profile_id=?",
        (profile_id,)
    ).fetchall()
    conn.close()

    unlocked_map = {r["achievement_id"]: r["unlocked_at"] for r in unlocked_rows}

    results = []
    for ach in ACHIEVEMENTS:
        aid = ach["id"]
        is_unlocked = aid in unlocked_map
        unlocked_at_str = None
        if is_unlocked and unlocked_map[aid]:
            try:
                # Format unlocked date e.g. "Aug 19"
                from datetime import datetime
                dt = datetime.strptime(str(unlocked_map[aid]).split(".")[0], "%Y-%m-%d %H:%M:%S")
                unlocked_at_str = dt.strftime("%b %d")
            except Exception:
                unlocked_at_str = "Unlocked"

        results.append({
            "id": aid,
            "title": ach["title"],
            "icon": ach["icon"],
            "description": ach["description"],
            "category": ach.get("category", "General"),
            "rarity": ach.get("rarity", "Bronze"),
            "unlocked": is_unlocked,
            "unlocked_at": unlocked_at_str
        })

    return results


def get_profile_watch_stats(profile_id):
    conn = get_conn()
    from datetime import datetime, timedelta

    # 1. Total seconds watched & total items tracked
    total_row = conn.execute("""
        SELECT SUM(position) as total_seconds, COUNT(*) as total_items, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as completed_items
        FROM watch_progress
        WHERE profile_id=?
    """, (profile_id,)).fetchone()

    total_seconds = total_row["total_seconds"] or 0
    total_items = total_row["total_items"] or 0
    completed_items = total_row["completed_items"] or 0
    completion_rate = round((completed_items / total_items * 100), 1) if total_items > 0 else 0
    avg_session_minutes = round((total_seconds / max(1, total_items)) / 60, 1)

    # 2. Peak Viewing Hour
    peak_row = conn.execute("""
        SELECT strftime('%H', updated_at) as hr, COUNT(*) as cnt
        FROM watch_progress
        WHERE profile_id=? AND updated_at IS NOT NULL
        GROUP BY hr ORDER BY cnt DESC LIMIT 1
    """, (profile_id,)).fetchone()

    peak_hour_str = "N/A"
    if peak_row and peak_row["hr"] is not None:
        try:
            h = int(peak_row["hr"])
            h_next = (h + 1) % 24
            ampm1 = "AM" if h < 12 else "PM"
            ampm2 = "AM" if h_next < 12 else "PM"
            display_h1 = h if h <= 12 else h - 12
            if display_h1 == 0: display_h1 = 12
            display_h2 = h_next if h_next <= 12 else h_next - 12
            if display_h2 == 0: display_h2 = 12
            peak_hour_str = f"{display_h1} {ampm1} - {display_h2} {ampm2}"
        except Exception:
            peak_hour_str = "Evening"

    # 3. 7-Day Watch Activity Bar Chart
    now_dt = datetime.now()
    days_data = []
    for i in range(6, -1, -1):
        dt_day = now_dt - timedelta(days=i)
        day_str = dt_day.strftime("%Y-%m-%d")
        day_name = dt_day.strftime("%a")
        
        row_day = conn.execute("""
            SELECT SUM(position) as sec FROM watch_progress
            WHERE profile_id=? AND date(updated_at)=?
        """, (profile_id, day_str)).fetchone()
        sec = row_day["sec"] or 0
        days_data.append({
            "day": day_name,
            "date": day_str,
            "minutes": round(sec / 60, 1)
        })

    # 4. Type breakdown (movies vs series vs anime)
    type_rows = conn.execute("""
        SELECT m.type, COUNT(*) as cnt, SUM(wp.position) as seconds
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=?
        GROUP BY m.type
    """, (profile_id,)).fetchall()

    type_breakdown = {r["type"]: {"count": r["cnt"], "seconds": r["seconds"] or 0} for r in type_rows}

    # 5. Genre breakdown (aggregate genres from media)
    media_genres = conn.execute("""
        SELECT m.genres, wp.position
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.genres IS NOT NULL AND m.genres != ''
    """, (profile_id,)).fetchall()

    genre_counts = {}
    for r in media_genres:
        g_list = [g.strip() for g in r["genres"].split(",") if g.strip()]
        for g in g_list:
            genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted([{"genre": g, "count": c} for g, c in genre_counts.items()], key=lambda x: x["count"], reverse=True)[:6]

    # 6. Technical Stats & Resolution/Storage
    tech_rows = conn.execute("""
        SELECT file_size, duration FROM media
    """).fetchall()

    total_storage_bytes = sum((r["file_size"] or 0) for r in tech_rows)
    total_storage_formatted = format_file_size_bytes(total_storage_bytes) or "0 GB"
    total_storage_gb = round(total_storage_bytes / (1024 * 1024 * 1024), 2)

    res_counts = {"4K": 0, "1080p": 0, "720p": 0, "SD": 0}
    for r in tech_rows:
        sz = r["file_size"] or 0
        if sz >= 3.5 * 1024 * 1024 * 1024:
            res_counts["4K"] += 1
        elif sz >= 1.2 * 1024 * 1024 * 1024:
            res_counts["1080p"] += 1
        elif sz >= 400 * 1024 * 1024:
            res_counts["720p"] += 1
        elif sz > 0:
            res_counts["SD"] += 1

    # 7. Recent history (Consolidated 10 distinct titles watched)
    all_history = conn.execute("""
        SELECT m.*, wp.position, wp.duration, wp.completed, wp.updated_at as last_watched
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=?
        ORDER BY wp.updated_at DESC
    """, (profile_id,)).fetchall()

    grouped_history = []
    seen_groups = set()

    for row in all_history:
        item = dict(row)
        m_type = item.get("type", "movie")
        tmdb_id = item.get("tmdb_id")
        title = item.get("title", "")

        if m_type in ("series", "anime") and tmdb_id:
            group_key = f"{m_type}_{tmdb_id}"
        elif m_type in ("series", "anime") and title:
            group_key = f"{m_type}_{title.lower()}"
        else:
            group_key = f"movie_{item.get('id')}"

        if group_key not in seen_groups:
            seen_groups.add(group_key)
            if m_type in ("series", "anime"):
                ep_cnt = sum(
                    1 for r in all_history 
                    if r["type"] == m_type and (
                        (tmdb_id and r["tmdb_id"] == tmdb_id) or 
                        (not tmdb_id and (r["title"] or "").lower() == title.lower())
                    )
                )
                item["ep_count"] = ep_cnt
            else:
                item["ep_count"] = 1
            grouped_history.append(item)
            if len(grouped_history) >= 10:
                break

    history_rows = grouped_history
    conn.close()

    achievements = get_profile_achievements(profile_id)

    return {
        "total_seconds": total_seconds,
        "total_items": total_items,
        "completed_items": completed_items,
        "completion_rate": completion_rate,
        "avg_session_minutes": avg_session_minutes,
        "peak_hour": peak_hour_str,
        "weekly_activity": days_data,
        "type_breakdown": type_breakdown,
        "top_genres": top_genres,
        "technical_stats": {
            "total_storage_gb": total_storage_gb,
            "total_storage_formatted": total_storage_formatted,
            "resolutions": res_counts
        },
        "recent_history": enrich_mounted_list([dict(r) for r in history_rows]),
        "achievements": achievements
    }


# ─── Favorites Queries ────────────────────────────────────────────────────────

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


# ─── Search Queries ───────────────────────────────────────────────────────────

def search_media(query="", media_type=None, genre=None, sort_by="relevance"):
    """
    Multi-field deep search for media items matching query across:
    title, original_title, cast_json (actor names), genres, year, overview, and file_path.
    Also probes audio tracks for 'multi audio' / 'dual audio' queries.
    Groups unique TV Series and Anime titles so duplicate episode rows aren't returned.
    """
    conn = get_conn()
    sql = "SELECT m.* FROM media m"
    conditions = []
    params = []

    if media_type and media_type != "all":
        conditions.append("m.type = ?")
        params.append(media_type)

    if genre and genre != "all":
        conditions.append("m.genres LIKE ?")
        params.append(f"%{genre}%")

    query_clean = (query or "").strip().lower()
    is_multi_query = any(k in query_clean for k in ["multi", "dual", "dub", "multi audio", "dual audio", "multi-audio", "multiaudio"])

    if query and query.strip() and not is_multi_query:
        q = f"%{query.strip()}%"
        if query_clean.isdigit() and len(query_clean) == 4:
            conditions.append("(m.title LIKE ? OR m.original_title LIKE ? OR m.year = ?)")
            params.extend([q, q, int(query_clean)])
        else:
            conditions.append("""(
                m.title LIKE ? OR 
                m.original_title LIKE ? OR 
                m.genres LIKE ? OR 
                m.cast_json LIKE ? OR 
                m.overview LIKE ? OR
                m.file_path LIKE ?
            )""")
            params.extend([q, q, q, q, q, q])

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += """
        GROUP BY CASE 
            WHEN m.type IN ('series', 'anime') AND m.tmdb_id IS NOT NULL THEN 'tmdb_' || m.tmdb_id 
            WHEN m.type IN ('series', 'anime') THEN 'title_' || LOWER(m.title)
            ELSE 'id_' || m.id 
        END
    """

    if sort_by == "rating_desc":
        sql += " ORDER BY m.rating DESC, m.added_at DESC"
    elif sort_by == "year_desc":
        sql += " ORDER BY m.year DESC, m.added_at DESC"
    elif sort_by == "title_asc":
        sql += " ORDER BY m.title ASC"
    else:
        sql += " ORDER BY m.rating DESC, m.added_at DESC"

    sql += " LIMIT 150"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = [dict(r) for r in rows]

    # Handle multi-audio probing & filtering if requested
    if is_multi_query:
        from backend.audio_probe import probe_audio_tracks
        filtered = []
        for m in results:
            fp = m.get("file_path", "")
            if not fp:
                continue
            fp_lower = fp.lower()
            if any(k in fp_lower for k in ["multi", "dual", "dub", "2audio", "multiaudio"]):
                filtered.append(m)
            else:
                tracks = probe_audio_tracks(fp)
                if len(tracks) > 1:
                    filtered.append(m)
        results = filtered

    results = enrich_mounted_list(results)
    return results[:60]
