"""
scanner.py — Media library scanner for CapsStream.

Scans configured folders, detects movies/series/anime, matches to TMDb,
and inserts/updates records in SQLite.

Folder conventions:
  Movies:      <movies_path>/<Movie Title (Year)>/<file.ext>
  Series:      <series_path>/<Show Title>/Season <N>/<file.ext>
  Anime:       <anime_path>/<Anime Title>/Season <N>/<file.ext>
               (or directly <anime_path>/<Anime Title>/<file.ext>)
"""

import os
import re
import json
import time
import threading
from backend.db import upsert_media, get_all_media, get_conn, is_drive_mounted
from backend.matcher import match_movie, match_show, fetch_season_episodes
from backend.utils.paths import BASE_DIR

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v", ".ts", ".wmv", ".flv", ".m2ts"}

_scan_status = {
    "running": False,
    "phase": "idle",        # idle | scanning | matching | complete
    "progress": "",
    "current_item": None,   # rich info about the file currently being processed
    "count": 0,
    "total": 0,
    "percent": 0,
    "scan_done": 0,         # folders walked during the scanning phase
    "scan_total": 0,
    "matched": 0,
    "elapsed": 0,
    "errors": [],
}
_scan_started_at = 0.0


def _set_status(phase=None, progress=None, **extra):
    """Update scan status; keeps elapsed time and recomputes percentage."""
    if _scan_started_at:
        _scan_status["elapsed"] = int(time.time() - _scan_started_at)
    if phase is not None:
        _scan_status["phase"] = phase
    if progress is not None:
        _scan_status["progress"] = progress
    for k, v in extra.items():
        _scan_status[k] = v
    # Live percentage based on active phase
    if _scan_status["phase"] == "scanning" and _scan_status.get("scan_total"):
        _scan_status["percent"] = round(
            100 * _scan_status.get("scan_done", 0) / _scan_status["scan_total"]
        )
    elif _scan_status["phase"] == "matching" and _scan_status.get("total"):
        _scan_status["percent"] = round(
            100 * min(_scan_status.get("count", 0), _scan_status["total"]) / _scan_status["total"]
        )
    else:
        _scan_status["percent"] = 100 if not _scan_status["running"] else _scan_status.get("percent", 0)


def get_scan_status():
    return dict(_scan_status)


def _load_config():
    cfg_path = os.path.join(BASE_DIR, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_paths(path_list):
    """Resolve relative paths relative to BASE_DIR; keep absolute paths as-is."""
    resolved = []
    for p in path_list:
        if os.path.isabs(p):
            resolved.append(p)
        else:
            resolved.append(os.path.join(BASE_DIR, p))
    return [p for p in resolved if os.path.isdir(p)]


def _is_video(filename):
    return os.path.splitext(filename)[1].lower() in VIDEO_EXTS


_SKIP_PATTERNS = []


def _load_skip_patterns(cfg=None):
    """Load comma-separated skip patterns from config (e.g. 'sample,trailer')."""
    global _SKIP_PATTERNS
    try:
        if cfg is None:
            cfg = _load_config()
        raw = str((cfg.get("library") or {}).get("skip_patterns", "") or "")
        _SKIP_PATTERNS = [p.strip().lower() for p in raw.split(",") if p.strip()]
    except Exception:
        _SKIP_PATTERNS = []
    return _SKIP_PATTERNS


def _should_skip(name):
    """True if a file/folder name contains any user-configured skip pattern."""
    if not _SKIP_PATTERNS:
        return False
    low = name.lower()
    return any(p in low for p in _SKIP_PATTERNS)


def _parse_episode(filename):
    """
    Try to extract season and episode number from a filename.
    Supports: S01E02, s1e2, 1x02, EP02, E02, 01 - Title, 02. Title, [01], (01), etc.
    Returns (season, episode) or (None, None).
    """
    name = os.path.splitext(filename)[0]
    patterns = [
        r'[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})',   # S01E02 / S01_E02
        r'(\d{1,2})[xX](\d{1,3})',               # 1x02
        r'(?:[Ee]pisode|[Ee]p|[Ee])[\s._-]*(\d{1,3})', # Episode 02 / Ep 02 / E02
        r'(?:^|[\s._\-\[\(])(\d{1,3})(?:[\s._\-\]\)]|$)', # [01] / (01) / - 01 / 01
    ]
    for pat in patterns:
        m = re.search(pat, name)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                return int(groups[0]), int(groups[1])
            elif len(groups) == 1:
                return None, int(groups[0])
    return None, None


def _parse_season_dir(rel_path):
    """Detect season number from folder names like S02, S2, Season 2, s03, Specials, Extras, OADs, etc."""
    if not rel_path or rel_path == ".":
        return None
    parts = os.path.normpath(rel_path).split(os.sep)
    for part in reversed(parts):
        part_clean = part.strip()
        if re.search(r'\b(specials?|extras?|oads?|ovas?|nced|ncop|featurettes?|shorts?|bonus|sp)\b', part_clean, re.IGNORECASE):
            return 0
        m = re.search(r'(?:[Ss]eason|[Ss]taffel|[Ss]aison|[Ss]eries|[Ss])\s*[-_]?\s*(\d{1,2})\b', part_clean)
        if m:
            return int(m.group(1))
    return None


def _fix_existing_seasons():
    """Correct season and episode numbers for existing media rows based on improved folder/file parsing."""
    try:
        from backend.db import get_conn
        conn = get_conn()
        rows = conn.execute("SELECT id, file_path, season, episode FROM media WHERE type IN ('series', 'anime') ORDER BY file_path ASC").fetchall()
        
        dir_map = {}
        for r in rows:
            d = os.path.dirname(r["file_path"])
            dir_map.setdefault(d, []).append(r)
            
        for dpath, file_rows in dir_map.items():
            s_from_dir = _parse_season_dir(os.path.basename(dpath))
            seen_episodes = set()
            
            for idx, r in enumerate(file_rows):
                fname = os.path.basename(r["file_path"])
                s_from_fn, ep_from_fn = _parse_episode(fname)
                
                correct_s = s_from_fn if (s_from_fn and re.search(r'[Ss]\d{1,2}', fname)) else (s_from_dir or s_from_fn or r["season"] or 1)
                correct_ep = ep_from_fn if ep_from_fn is not None else (idx + 1)
                
                if correct_ep in seen_episodes:
                    correct_ep = idx + 1
                seen_episodes.add(correct_ep)
                
                if correct_s != r["season"] or correct_ep != r["episode"]:
                    conn.execute("UPDATE media SET season=?, episode=? WHERE id=?", (correct_s, correct_ep, r["id"]))
                    print(f"[Scanner] Corrected S/E for {fname}: S{r['season']}E{r['episode']} -> S{correct_s}E{correct_ep}")
                    
        conn.commit()
        conn.close()
    except Exception as e:
        print("[Scanner] Failed to fix existing seasons/episodes:", e)


def _list_entries(base):
    """Safely list sorted directory entries for a base path."""
    try:
        return sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return []


def _scan_movies(path_list, existing_paths, on_progress=None):
    """Scan movie folders and return list of media dicts."""
    results = []
    entries = []
    for base in path_list:
        if not os.path.isdir(base):
            continue
        # Each immediate subfolder = one movie
        entries.extend((base, e) for e in _list_entries(base))

    total = len(entries)
    if on_progress and total:
        on_progress(0, total, "Starting movies scan")

    for done, (base, entry) in enumerate(entries, 1):
        if on_progress:
            on_progress(done - 1, total, entry.name)
        if _should_skip(entry.name):
            continue
        if not entry.is_dir():
            # Also handle flat file directly in movies folder
            if entry.is_file() and _is_video(entry.name):
                if entry.path not in existing_paths:
                    results.append({
                        "file_path":   entry.path,
                        "folder_name": os.path.splitext(entry.name)[0],
                        "type":        "movie",
                    })
            continue
        folder_name = entry.name
        # Find video files inside this folder (recursive)
        for root, dirs, files in os.walk(entry.path):
            dirs[:] = [d for d in sorted(dirs) if not _should_skip(d)]
            for fname in sorted(files):
                if _is_video(fname) and not _should_skip(fname):
                    fpath = os.path.join(root, fname)
                    if fpath not in existing_paths:
                        results.append({
                            "file_path":   fpath,
                            "folder_name": folder_name,
                            "type":        "movie",
                        })
    if on_progress and total:
        on_progress(total, total, "")
    return results


def _scan_shows(path_list, existing_paths, media_type, on_progress=None):
    """Scan series/anime folders. Returns list of media dicts with season/episode."""
    results = []
    entries = []
    for base in path_list:
        if not os.path.isdir(base):
            continue
        entries.extend((base, e) for e in _list_entries(base))

    total = len(entries)
    if on_progress and total:
        on_progress(0, total, f"Starting {media_type} scan")

    for done, (base, show_entry) in enumerate(entries, 1):
        if on_progress:
            on_progress(done - 1, total, show_entry.name)
        if _should_skip(show_entry.name):
            continue
        if not show_entry.is_dir():
            if show_entry.is_file() and _is_video(show_entry.name):
                fpath = show_entry.path
                if fpath not in existing_paths:
                    season, episode = _parse_episode(show_entry.name)
                    results.append({
                        "file_path":   fpath,
                        "folder_name": os.path.splitext(show_entry.name)[0],
                        "season":      season or 1,
                        "episode":     episode or 1,
                        "type":        media_type,
                    })
            continue
        show_name = show_entry.name
        # Walk inside show folder looking for video files
        for root, dirs, files in os.walk(show_entry.path):
            dirs[:] = [d for d in sorted(dirs) if not _should_skip(d)]
            rel = os.path.relpath(root, show_entry.path)
            season_from_dir = _parse_season_dir(rel)

            video_files = [f for f in sorted(files) if _is_video(f) and not _should_skip(f)]
            for idx, fname in enumerate(video_files):
                fpath = os.path.join(root, fname)
                if fpath in existing_paths:
                    continue
                season, episode = _parse_episode(fname)
                if season is None or not re.search(r'[Ss]\d{1,2}', fname):
                    season = season_from_dir if season_from_dir is not None else (season or 1)
                if episode is None:
                    episode = idx + 1
                results.append({
                    "file_path":   fpath,
                    "folder_name": show_name,
                    "season":      season or 1,
                    "episode":     episode,
                    "type":        media_type,
                })
    if on_progress and total:
        on_progress(total, total, "")
    return results


def scan_library(callback=None):
    """
    Main scan entry point. Scans all configured media paths.
    callback(message) is called with progress updates if provided.
    Returns dict with counts.
    """
    global _scan_status, _scan_started_at
    _scan_started_at = time.time()
    _scan_status = {
        "running": True,
        "phase": "scanning",
        "progress": "Starting scan...",
        "current_item": None,
        "count": 0,
        "total": 0,
        "percent": 0,
        "scan_done": 0,
        "scan_total": 0,
        "matched": 0,
        "elapsed": 0,
        "errors": [],
    }

    def log(msg):
        _set_status(progress=msg)
        print(f"[Scanner] {msg}")
        if callback:
            callback(msg)

    def scan_progress(done, total, label):
        """Per-folder progress during the disk-walk (Scanning) phase."""
        _set_status(
            scan_done=done,
            scan_total=total,
            current_item={"folder": label} if label else None,
            progress=f"Scanning folders: {done}/{total}" + (f" — {label}" if label else ""),
        )

    log("Preparing library...")
    _fix_existing_seasons()

    cfg = _load_config()
    media_paths = cfg.get("media_paths", {})
    _load_skip_patterns(cfg)

    movies_paths = _resolve_paths(media_paths.get("movies", []))
    series_paths = _resolve_paths(media_paths.get("series", []))
    anime_paths  = _resolve_paths(media_paths.get("anime",  []))

    # Filter out user-disabled directories
    disabled = cfg.get("disabled_paths", {})
    def _filter_disabled(paths, category):
        off = set(disabled.get(category, []))
        if not off:
            return paths
        kept = [p for p in paths if not any(
            os.path.normpath(p) == os.path.normpath(d if os.path.isabs(d) else os.path.join(BASE_DIR, d))
            for d in off
        )]
        skipped = len(paths) - len(kept)
        if skipped:
            log(f"Skipping {skipped} disabled path(s) in '{category}'")
        return kept

    movies_paths = _filter_disabled(movies_paths, "movies")
    series_paths = _filter_disabled(series_paths, "series")
    anime_paths  = _filter_disabled(anime_paths,  "anime")

    def _has_valid_image(m):
        p = m.get("poster_path")
        if not p:
            return False
        abs_p = os.path.join(BASE_DIR, "data", "metadata", p)
        return os.path.isfile(abs_p)

    # Only skip files that have already been matched to TMDb AND have valid images on disk
    existing = {
        m["file_path"] for m in get_all_media()
        if m.get("tmdb_matched") == 1 and _has_valid_image(m)
    }

    all_new = []

    log("Scanning movie folders...")
    all_new += _scan_movies(movies_paths, existing, on_progress=scan_progress)

    log("Scanning series folders...")
    all_new += _scan_shows(series_paths, existing, "series", on_progress=scan_progress)

    log("Scanning anime folders...")
    all_new += _scan_shows(anime_paths, existing, "anime", on_progress=scan_progress)

    # ─── Matching phase ───
    _set_status(phase="matching", total=len(all_new), count=0)
    log(f"Found {len(all_new)} new files. Matching to TMDb...")

    # TMDb cache per show and season to avoid redundant API calls
    show_meta_cache = {}
    season_meta_cache = {}
    count = 0
    matched_count = 0

    try:
        for idx, item in enumerate(all_new):
            fpath     = item["file_path"]
            fname     = item["folder_name"]
            mtype     = item["type"]
            season    = item.get("season")
            episode   = item.get("episode")
            file_size = os.path.getsize(fpath) if os.path.exists(fpath) else 0

            # Rich info about the file currently being processed
            current_item = {
                "type":       mtype,
                "title":      fname,
                "season":     season if mtype != "movie" else None,
                "episode":    episode if mtype != "movie" else None,
                "file_name":  os.path.basename(fpath),
                "file_size":  file_size,
                "matched_title": None,
                "year":       None,
                "rating":     None,
            }
            _set_status(current_item=current_item)
            log(f"Matching {mtype}: {fname}" + (f" S{season}E{episode}" if (season and mtype != 'movie') else ""))

            try:
                if mtype == "movie":
                    meta = match_movie(fname)
                    if meta:
                        matched_count += 1
                        current_item.update({
                            "matched_title": meta.get("title"),
                            "year":          meta.get("year"),
                            "rating":        meta.get("rating"),
                        })
                        _set_status(current_item=current_item)
                        upsert_media({
                            **meta,
                            "file_path": fpath,
                            "file_size": file_size,
                        })
                    else:
                        upsert_media({
                            "type":      "movie",
                            "title":     fname,
                            "file_path": fpath,
                            "file_size": file_size,
                        })

                else:  # series or anime
                    cache_key = (mtype, fname)
                    if cache_key not in show_meta_cache:
                        show_meta_cache[cache_key] = match_show(fname, mtype)
                    show_meta = show_meta_cache[cache_key]

                    if show_meta:
                        matched_count += 1
                        current_item.update({
                            "matched_title": show_meta.get("title"),
                            "year":          show_meta.get("year"),
                            "rating":        show_meta.get("rating"),
                        })
                        _set_status(current_item=current_item)

                        ep_title = None
                        if season and episode:
                            s_key = (show_meta["tmdb_id"], season)
                            if s_key not in season_meta_cache:
                                try:
                                    season_meta_cache[s_key] = fetch_season_episodes(show_meta["tmdb_id"], season)
                                except Exception:
                                    season_meta_cache[s_key] = []
                            eps = season_meta_cache[s_key]
                            ep_data = next((e for e in eps if e.get("episode_number") == episode), None)
                            ep_title = ep_data.get("name") if ep_data else None

                        upsert_media({
                            **show_meta,
                            "file_path": fpath,
                            "file_size": file_size,
                            "season":    season,
                            "episode":   episode,
                            "ep_title":  ep_title,
                        })
                    else:
                        upsert_media({
                            "type":      mtype,
                            "title":     fname,
                            "file_path": fpath,
                            "file_size": file_size,
                            "season":    season,
                            "episode":   episode,
                        })

                count += 1
                _set_status(count=count, matched=matched_count)

            except Exception as e:
                err = f"Error processing {fpath}: {e}"
                _scan_status["errors"].append(err)
                # Keep the payload small — never retain thousands of errors
                if len(_scan_status["errors"]) > 50:
                    _scan_status["errors"] = _scan_status["errors"][-50:]
                print(f"[Scanner] ERROR: {err}")
    finally:
        _set_status(
            running=False,
            phase="complete",
            count=count,
            matched=matched_count,
            progress=f"Scan complete. Processed {count} new files.",
        )
        print(f"[Scanner] Scan complete. {count} new files added.")
        try:
            removed = _prune_missing_files()
            if removed:
                _set_status(removed_missing=removed)
        except Exception as e:
            print(f"[Scanner] Missing-file prune failed: {e}")
        try:
            new_episodes = _diff_new_episodes()
            if new_episodes:
                _set_status(new_episodes=new_episodes)
        except Exception as e:
            print(f"[Scanner] New-episode diff failed: {e}")
        try:
            start_intro_detection_pass()
        except Exception as e:
            print(f"[Scanner] Intro detection pass failed to start: {e}")
        try:
            from backend.routes.requests import sync_requests_with_library
            _, auto_count = sync_requests_with_library()
            if auto_count:
                print(f"[Scanner] Auto-detected {auto_count} requested media added to library.")
        except Exception as e:
            print(f"[Scanner] Auto-detect requests failed: {e}")

    return {"new_files": count, "matched": matched_count, "errors": _scan_status["errors"]}


# ─── Missing-file pruning ─────────────────────────────────────────────────────

def _prune_missing_files():
    """
    Remove library entries whose source file no longer exists — but ONLY when
    the file's drive is currently mounted, so temporarily disconnected
    external/NAS drives never wipe the library. Disabled via
    config: library.remove_missing_files = false.
    Returns the number of rows removed.
    """
    try:
        from backend.settings import load_config
        lib_cfg = (load_config().get("library") or {})
        if lib_cfg.get("remove_missing_files") is False:
            return 0
    except Exception:
        pass

    conn = get_conn()
    rows = conn.execute("SELECT id, file_path FROM media").fetchall()
    to_delete = []
    for r in rows:
        fp = r["file_path"]
        if os.path.isfile(fp):
            continue                      # still there — fine
        if not is_drive_mounted(fp):
            continue                      # drive offline — keep, don't wipe
        to_delete.append(r["id"])

    if not to_delete:
        conn.close()
        return 0

    # Progress/favorites cascade-delete via FK on media.id
    conn.executemany("DELETE FROM media WHERE id=?", [(i,) for i in to_delete])
    conn.commit()
    conn.close()
    print(f"[Scanner] Pruned {len(to_delete)} library entries whose source file no longer exists.")
    return len(to_delete)


# ─── Background intro detection pass ─────────────────────────────────────────
# Audio-based intro detection takes ~30s per file (I/O bound), so it runs in
# a background daemon thread after scans and at server startup — never
# synchronously when a user opens an episode. Results land in the skip-time
# cache (source "audio") so the player picks them up automatically.

INTRO_DETECT_BATCH = 12   # max files per pass — keep disk I/O polite
INTRO_DETECT_SLEEP = 4    # seconds between files — never saturate the drive


def _intro_detect_pass():
    from backend.db import get_conn
    from backend.skip_times import SKIP_CACHE_DIR, LABELS
    from backend.intro_detect import detect_intro

    conn = get_conn()
    rows = conn.execute("""
        SELECT m.id, m.file_path, m.title FROM media m
        WHERE m.type IN ('series', 'anime') AND m.file_path IS NOT NULL
          AND m.intro_start = 0
          AND NOT EXISTS (SELECT 1 FROM media m2 WHERE m2.tmdb_id = m.tmdb_id AND m2.intro_start > 0)
        ORDER BY m.added_at DESC
    """).fetchall()
    conn.close()

    processed = 0
    for media_id, file_path, title in rows:
        if processed >= INTRO_DETECT_BATCH:
            break
        cache_path = os.path.join(SKIP_CACHE_DIR, f"{media_id}.json")
        if os.path.isfile(cache_path):
            continue  # already has resolved skip data
        if not os.path.isfile(file_path):
            continue

        detected = detect_intro(file_path)
        if detected:
            data = {
                "op": {
                    "start": detected["start"],
                    "end": detected["end"],
                    "type": "op",
                    "label": LABELS.get("op", "Skip Intro"),
                    "source": "audio",
                }
            }
            try:
                os.makedirs(SKIP_CACHE_DIR, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print(f"[IntroDetect] '{title}' intro {detected['start']}s → {detected['end']}s")
            except Exception as e:
                print(f"[IntroDetect] Cache write failed for {title}: {e}")
        processed += 1
        time.sleep(INTRO_DETECT_SLEEP)  # breathe — never saturate media drives

    print(f"[IntroDetect] Pass complete — {processed} file(s) analyzed")


def start_intro_detection_pass():
    threading.Thread(target=_intro_detect_pass, daemon=True).start()


# ─── New-episode notifications ────────────────────────────────────────────────
# After each scan, diff per-show episode counts against the previous scan's
# snapshot (data/library_state.json). Shows with new episodes are surfaced in
# the scan status so the frontend can toast them.

_LIBRARY_STATE_FILE = os.path.join(BASE_DIR, "data", "library_state.json")


def _diff_new_episodes():
    from backend.db import get_conn
    conn = get_conn()
    counts = {
        row[0]: {"title": row[1], "type": row[2], "count": row[3]}
        for row in conn.execute("""
            SELECT tmdb_id, MIN(title), MIN(type), COUNT(*)
            FROM media WHERE type IN ('series', 'anime') AND tmdb_id IS NOT NULL
            GROUP BY tmdb_id
        """).fetchall()
    }
    conn.close()

    snapshot = {}
    if os.path.isfile(_LIBRARY_STATE_FILE):
        try:
            with open(_LIBRARY_STATE_FILE, encoding="utf-8") as f:
                snapshot = json.load(f) or {}
        except Exception:
            snapshot = {}

    prev = snapshot.get("shows") or {}
    new_episodes = []
    for tmdb_id, info in counts.items():
        key = str(tmdb_id)
        before = prev.get(key, {}).get("count", 0)
        added = info["count"] - before
        if added > 0 and before > 0:  # brand-new shows get no spam on first scan
            new_episodes.append({
                "title": info["title"],
                "type": info["type"],
                "added": added,
            })
    new_episodes.sort(key=lambda x: -x["added"])

    snapshot["shows"] = {k: {"count": v["count"]} for k, v in counts.items()}
    snapshot["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(_LIBRARY_STATE_FILE), exist_ok=True)
        with open(_LIBRARY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as e:
        print(f"[Scanner] Could not save library state: {e}")

    return new_episodes[:10]
