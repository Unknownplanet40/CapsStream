"""
skip_times.py — Skip segment resolution for CapsStream.

Priority order:
  1. Manual skip markers (user-stamped recap/intro/outro stored on the media row)
  2. AniSkip API — ONLY for auto-detected anime (fallback)
  3. FFprobe embedded chapters (local, keyword-based fallback)

Returns normalized dict: { "op": {...}, "ed": {...}, "recap": {...} }
Each entry carries a "source" field: "manual" | "aniskip" | "chapters".
"""

import os
import json
import subprocess
import requests
from backend.db import get_media_by_id
from backend.proc_utils import CREATE_NO_WINDOW
from backend.utils.paths import BASE_DIR, FFPROBE_BIN

SKIP_CACHE_DIR = os.path.join(BASE_DIR, "data", "metadata", "skip_times")
CHAPTERS_CACHE_DIR = os.path.join(BASE_DIR, "data", "metadata", "chapters")
MAL_CACHE_FILE = os.path.join(BASE_DIR, "data", "metadata", "mal_ids.json")
os.makedirs(SKIP_CACHE_DIR, exist_ok=True)
os.makedirs(CHAPTERS_CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CapsStream/1.0",
    "Content-Type": "application/json"
}

LABELS = {"op": "Skip Intro", "ed": "Skip Outro", "recap": "Skip Recap", "preview": "Skip Preview"}


def _load_mal_cache():
    if os.path.isfile(MAL_CACHE_FILE):
        try:
            with open(MAL_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_mal_cache(cache):
    try:
        with open(MAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def get_mal_id_for_title(title, tmdb_id=None):
    """
    Finds MyAnimeList (MAL) ID for an anime title using AniList GraphQL
    (primary) and Jikan (fallback), with local disk caching.
    """
    cache = _load_mal_cache()
    key = str(tmdb_id) if tmdb_id else title.lower().strip()
    if cache.get(key):
        return cache[key]

    try:
        gql_query = """
        query ($search: String) {
          Media (search: $search, type: ANIME) {
            id
            idMal
          }
        }
        """
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": gql_query, "variables": {"search": title}},
            headers=HEADERS,
            timeout=6
        )
        if r.status_code == 200:
            data = r.json()
            media = data.get("data", {}).get("Media") or {}
            mal_id = media.get("idMal") or media.get("id")
            if mal_id:
                cache[key] = mal_id
                _save_mal_cache(cache)
                return mal_id
    except Exception as e:
        print(f"[Skips] AniList GraphQL error for {title}: {e}")

    try:
        # Respect the user's "Enable Jikan API" setting (Settings → Metadata Providers)
        try:
            from backend.settings import load_config
            if not (load_config().get("metadata_sources") or {}).get("enable_jikan", True):
                return None
        except Exception:
            pass

        url = f"https://api.jikan.moe/v4/anime?q={requests.utils.quote(title)}&limit=1"
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            data = r.json()
            results = data.get("data", [])
            if results and len(results) > 0:
                mal_id = results[0].get("mal_id")
                if mal_id:
                    cache[key] = mal_id
                    _save_mal_cache(cache)
                    return mal_id
    except Exception as e:
        print(f"[Skips] Jikan API error for {title}: {e}")

    return None


def probe_chapters_for_skips(file_path):
    """
    Probes video file embedded FFmpeg chapter markers for intro/outro keywords.
    """
    if not file_path or not os.path.exists(file_path) or not os.path.exists(FFPROBE_BIN):
        return {}

    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_chapters",
        file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6,
                             creationflags=CREATE_NO_WINDOW)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            chapters = data.get("chapters", [])
            skips = {}
            for c in chapters:
                start = float(c.get("start_time", 0))
                end = float(c.get("end_time", 0))
                tags = c.get("tags", {})
                title = (tags.get("title") or tags.get("TITLE") or "").lower()

                if any(kw in title for kw in ["preview", "next time", "next episode"]):
                    skips["preview"] = {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "type": "preview",
                        "label": "Skip Preview",
                        "source": "chapters"
                    }
                elif any(kw in title for kw in ["intro", "opening", "theme", "op"]):
                    skips["op"] = {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "type": "op",
                        "label": "Skip Intro",
                        "source": "chapters"
                    }
                elif any(kw in title for kw in ["outro", "ending", "credit", "ed"]):
                    skips["ed"] = {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "type": "ed",
                        "label": "Skip Outro",
                        "source": "chapters"
                    }
            return skips
    except Exception as e:
        print(f"[Skips] FFprobe chapter probe error: {e}")

    return {}


def probe_chapters_full(file_path):
    """
    Probes video file embedded FFmpeg chapter markers and returns a structured list:
    [
      { "id": 0, "start": 0.0, "end": 120.5, "title": "Prologue" },
      ...
    ]
    """
    if not file_path or not os.path.exists(file_path) or not os.path.exists(FFPROBE_BIN):
        return []

    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_chapters",
        file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6,
                             creationflags=CREATE_NO_WINDOW)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            raw_chapters = data.get("chapters", [])
            parsed = []
            for i, c in enumerate(raw_chapters):
                start = float(c.get("start_time", 0))
                end = float(c.get("end_time", 0))
                tags = c.get("tags", {})
                title = tags.get("title") or tags.get("TITLE") or f"Chapter {i + 1}"
                parsed.append({
                    "id": c.get("id", i),
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "title": str(title).strip()
                })
            return parsed
    except Exception as e:
        print(f"[Chapters] FFprobe chapter probe error: {e}")

    return []


def fetch_chapters(media_id):
    """
    Fetches chapters for a media item, with persistent file caching.
    Returns: list of { "id": int, "start": float, "end": float, "title": str }
    """
    media = get_media_by_id(media_id)
    if not media:
        return []

    cache_path = os.path.join(CHAPTERS_CACHE_DIR, f"{media_id}.json")
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
                if isinstance(cached, list):
                    return cached
        except Exception:
            pass

    file_path = media.get("file_path")
    chapters = probe_chapters_full(file_path)
    if chapters:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(chapters, f)
        except Exception as e:
            print(f"[Chapters] Failed writing cache for media {media_id}: {e}")

    return chapters



def is_anime(media):
    """
    Auto-detect anime content:
      - Explicit 'anime' library category, OR
      - A series whose TMDb genres include Animation AND whose title matched
        the anime library conventions (kept permissive: Animation genre alone
        on a series is treated as likely anime).
    """
    if not media:
        return False
    if media.get("type") == "anime":
        return True
    genres = (media.get("genres") or "").lower()
    return media.get("type") == "series" and "animation" in genres


def fetch_skip_times(media_id):
    """
    Resolves skip segments for a media file.

    Priority:
      1. Manual skip markers (always win, per-segment)
      2. AniSkip API — ONLY when the media is detected as anime
      3. FFprobe embedded chapters

    Returns normalized dict: { "op": {...}, "ed": {...}, "recap": {...} }
    """
    media = get_media_by_id(media_id)
    if not media:
        return {}

    skip_data = {}

    # ── 1. Manual skip markers (highest priority, per-segment) ──
    def _manual(key_start, key_end, seg_type):
        s = media.get(key_start, 0) or 0
        e = media.get(key_end, 0) or 0
        if e > s:
            skip_data[seg_type] = {
                "start": float(s),
                "end": float(e),
                "type": seg_type,
                "label": LABELS[seg_type],
                "source": "manual",
            }

    _manual("recap_start", "recap_end", "recap")
    _manual("intro_start", "intro_end", "op")
    _manual("outro_start", "outro_end", "ed")
    _manual("preview_start", "preview_end", "preview")

    # All four covered by manual markers — nothing else needed
    if {"recap", "op", "ed", "preview"}.issubset(skip_data):
        return skip_data

    # ── Cached remote/chapter results fill remaining gaps ──
    cache_path = os.path.join(SKIP_CACHE_DIR, f"{media_id}.json")
    cached_data = {}
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached_data = json.load(f) or {}
        except Exception:
            pass

    # Drop stale cache entries that would override fresh manual markers
    for k, v in cached_data.items():
        if k not in skip_data and v.get("source") != "manual":
            skip_data[k] = v

    if {"recap", "op", "ed", "preview"}.issubset(skip_data):
        return skip_data

    # ── 2. AniSkip fallback — ONLY for auto-detected anime ──
    if is_anime(media):
        title = media.get("title") or ""
        ep_num = media.get("episode") or 1
        tmdb_id = media.get("tmdb_id")

        mal_id = get_mal_id_for_title(title, tmdb_id)
        if mal_id:
            try:
                duration_sec = int(media.get("duration") or 0)
                url = f"https://api.aniskip.com/v2/skip-times/{mal_id}/{ep_num}?types=op&types=ed&types=recap&episodeLength={duration_sec}"
                r = requests.get(url, headers={"User-Agent": "CapsStream/1.0"}, timeout=6)
                if r.status_code == 200:
                    res = r.json()
                    for item in res.get("results", []):
                        stype = (item.get("skipType") or "").lower()
                        interval = item.get("interval") or {}
                        start = interval.get("startTime")
                        end = interval.get("endTime")
                        if start is not None and end is not None and stype not in skip_data:
                            skip_data[stype] = {
                                "start": round(float(start), 2),
                                "end": round(float(end), 2),
                                "type": stype,
                                "label": LABELS.get(stype, "Skip Segment"),
                                "source": "aniskip",
                            }
                elif r.status_code == 404:
                    print(f"[Skips] AniSkip has no times for MAL {mal_id} ep {ep_num}")
            except Exception as e:
                print(f"[Skips] AniSkip query error: {e}")

    # ── 3. FFprobe embedded chapters (local fallback) ──
    file_path = media.get("file_path")
    if file_path:
        chapter_skips = probe_chapters_for_skips(file_path)
        for k, v in chapter_skips.items():
            if k not in skip_data:
                skip_data[k] = v

    if skip_data:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(skip_data, f, indent=2)
        except Exception:
            pass

    return skip_data
