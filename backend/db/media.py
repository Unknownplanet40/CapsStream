# -*- coding: utf-8 -*-
import os
import json
import time
import random
import sqlite3
from .connection import get_conn

_DRIVE_MOUNT_CACHE = {}
_DRIVE_MOUNT_CACHE_TIME = 0

def is_drive_mounted(file_path):
    """Check if the drive root of a file path is mounted, cached for 5 seconds."""
    global _DRIVE_MOUNT_CACHE, _DRIVE_MOUNT_CACHE_TIME
    now = time.time()
    if now - _DRIVE_MOUNT_CACHE_TIME > 5:
        _DRIVE_MOUNT_CACHE = {}
        _DRIVE_MOUNT_CACHE_TIME = now

    if not file_path:
        return True

    # Support Windows drive letters on both Windows and POSIX (e.g. CI testing)
    import ntpath
    drive = ntpath.splitdrive(file_path)[0]
    if drive:
        drive_root = drive + "\\"
        if drive_root in _DRIVE_MOUNT_CACHE:
            return _DRIVE_MOUNT_CACHE[drive_root]
        if os.name == "nt":
            mounted = os.path.exists(drive + os.sep)
        else:
            mounted = os.path.exists(file_path) or os.path.exists(drive_root)
        _DRIVE_MOUNT_CACHE[drive_root] = mounted
        return mounted

    if file_path.startswith("/"):
        parts = [p for p in file_path.split("/") if p]
        mount_check = "/" + parts[0] if parts else "/"
        if mount_check in _DRIVE_MOUNT_CACHE:
            return _DRIVE_MOUNT_CACHE[mount_check]
        mounted = os.path.exists(mount_check)
        _DRIVE_MOUNT_CACHE[mount_check] = mounted
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
    Finds all mounted source copies of the media file (movie, series, or anime episode),
    probes their video resolution, extracts drive letters, and returns formatted quality options.
    """
    media = get_media_by_id(media_id)
    if not media:
        return []

    sources = get_all_sources_for_media(media)
    mounted_sources = [s for s in sources if s.get("is_mounted")]
    if not mounted_sources:
        mounted_sources = [media]

    from backend.video_probe import probe_video_resolution

    # Sort sources by file size descending (prefer higher quality / higher bitrate)
    mounted_sources.sort(key=lambda s: s.get("file_size") or 0, reverse=True)

    # Probe every source once and extract resolution label and drive letter
    probed = []
    for s in mounted_sources:
        fp = s.get("file_path") or ""
        drive = os.path.splitdrive(fp)[0].upper() if fp else ""
        probe_res = probe_video_resolution(fp)
        res_label = probe_res.get("label") or "Standard Quality"
        base_label = probe_res.get("base_label") or "Standard"
        probed.append((s, res_label, base_label, drive))

    # If only 1 source exists, return standard single option
    if len(probed) <= 1:
        s, res_label, base_label, drive = probed[0] if probed else (media, "Default", "Default", "")
        size_str = format_file_size_bytes(s.get("file_size"))
        lbl = f"{res_label} ({size_str})" if size_str else res_label
        if drive:
            lbl += f" — {drive}"
        return [{
            "media_id": s["id"],
            "file_path": s.get("file_path", ""),
            "drive": drive,
            "resolution": res_label,
            "base_label": base_label,
            "display_label": lbl,
            "size_str": size_str,
            "file_size": s.get("file_size") or 0,
            "is_current": True,
            "is_mounted": bool(s.get("is_mounted", True)),
        }]

    options = []
    for idx, (s, res_label, base_label, drive) in enumerate(probed):
        size_str = format_file_size_bytes(s.get("file_size"))
        display_label = res_label
        if size_str:
            display_label += f" ({size_str})"
        if drive:
            display_label += f" — {drive}"

        options.append({
            "media_id": s["id"],
            "file_path": s.get("file_path", ""),
            "drive": drive,
            "resolution": res_label,
            "base_label": base_label,
            "display_label": display_label,
            "size_str": size_str,
            "file_size": s.get("file_size") or 0,
            "is_current": (s["id"] == media_id),
            "is_mounted": bool(s.get("is_mounted", True)),
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


def delete_media_by_id(media_id):
    """
    Remove a single media row (one movie file or one episode).
    Watch progress and favorites cascade-delete via FK.
    Returns number of rows removed.
    """
    conn = get_conn()
    cur = conn.execute("DELETE FROM media WHERE id=?", (int(media_id),))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def delete_media_by_tmdb(tmdb_id, media_type):
    """
    Remove every row of a title (all episodes of a series/anime, or all
    quality copies of a movie). Progress/favorites cascade via FK.
    Returns number of rows removed.
    """
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM media WHERE tmdb_id=? AND type=?",
        (int(tmdb_id), media_type),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def delete_media_by_title_and_type(title, media_type):
    """
    Remove every row of a title matching title and type (for unmatched titles without tmdb_id).
    Progress/favorites cascade via FK.
    Returns number of rows removed.
    """
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM media WHERE title=? AND type=?",
        (title, media_type),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


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
        try:
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
        except Exception:
            pass

    results = enrich_mounted_list(results)
    return results[:60]


def get_unique_shows(media_type=None):
    """
    Return one row per show/movie (grouped by tmdb_id or title).

    Uses a SQL subquery to select only the best representative row per title
    (rows with a poster preferred, otherwise the lowest id) so we avoid
    pulling every episode row into Python memory just to deduplicate.
    """
    conn = get_conn()
    type_clause = "AND type=?" if media_type else ""
    params = (media_type,) if media_type else ()

    # Pick the row with a poster_path when available, else the earliest id.
    rows = conn.execute(f"""
        SELECT m.* FROM media m
        JOIN (
            SELECT
                COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                MIN(
                    CASE WHEN poster_path IS NOT NULL AND poster_path != ''
                         THEN 0 ELSE 1 END
                ) AS has_poster_rank,
                MIN(CASE WHEN poster_path IS NOT NULL AND poster_path != ''
                         THEN id ELSE NULL END) AS poster_id,
                MIN(id) AS fallback_id
            FROM media
            WHERE 1=1 {type_clause}
            GROUP BY grp
        ) g ON m.id = COALESCE(g.poster_id, g.fallback_id)
        ORDER BY m.title COLLATE NOCASE
    """, params).fetchall()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    return enrich_mounted_list(items)


def get_recently_added(limit=20):
    """Return the `limit` most recently added unique titles."""
    conn = get_conn()
    # SQL-level dedup: pick the most recently added row per title group
    rows = conn.execute("""
        SELECT m.* FROM media m
        JOIN (
            SELECT
                COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                MAX(added_at) AS latest_added,
                MIN(CASE WHEN poster_path IS NOT NULL AND poster_path != ''
                         THEN id ELSE NULL END) AS poster_id,
                MIN(id) AS fallback_id
            FROM media
            GROUP BY grp
        ) g ON m.id = COALESCE(g.poster_id, g.fallback_id)
        ORDER BY g.latest_added DESC
        LIMIT ?
    """, (limit * 2,)).fetchall()  # fetch 2× to allow disabled-path filtering

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    return enrich_mounted_list(items[:limit])


def get_top_rated(limit=20, media_type=None):
    """Return the `limit` highest-rated unique titles."""
    conn = get_conn()
    type_clause = "AND type=?" if media_type else ""
    params = (media_type,) if media_type else ()
    # SQL-level dedup: pick the highest-rated row per title group
    rows = conn.execute(f"""
        SELECT m.* FROM media m
        JOIN (
            SELECT
                COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                MAX(rating) AS best_rating,
                MAX(vote_count) AS best_votes,
                MIN(CASE WHEN poster_path IS NOT NULL AND poster_path != ''
                         THEN id ELSE NULL END) AS poster_id,
                MIN(id) AS fallback_id
            FROM media
            WHERE rating > 0 {type_clause}
            GROUP BY grp
        ) g ON m.id = COALESCE(g.poster_id, g.fallback_id)
        ORDER BY g.best_rating DESC, g.best_votes DESC
        LIMIT ?
    """, (*params, limit * 2)).fetchall()

    disabled_roots = get_disabled_path_roots()
    if disabled_roots:
        items = [dict(r) for r in rows if not is_file_path_disabled(r["file_path"], disabled_roots)]
    else:
        items = [dict(r) for r in rows]

    return enrich_mounted_list(items[:limit])


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

