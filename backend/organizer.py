# -*- coding: utf-8 -*-
"""
backend/organizer.py — Automated Media Renamer & File Organizer for CapsStream.

A post-processing engine that transforms scene-tagged downloads into a standardized,
Plex/Jellyfin/CapsStream-compliant media library structure:
  - Movies:    Movies/{Title} ({Year})/{Title} ({Year}).ext
  - TV Series: TV Shows/{Title}/Season {SS}/{Title} - S{SS}E{EE}.ext

Features:
  - Smart Mode: Uses NTFS hardlinks on the same drive (preserves torrent seeding with 0 extra disk space).
    Gracefully falls back to atomic move or copy.
  - In-Progress Protection: Blacklists .part/.!ut/.tmp extensions, verifies Windows exclusive file locks,
    and applies a size stability debounce.
  - Hybrid Identification: Cross-references data/requests.json and TMDb API with offline regex fallback.
  - Companion File Handling: Renames matching subtitles (.srt, .ass, .vtt) in lockstep.
  - Context-Aware Clutter Handling: Ignores clutter when hardlinking (preserving torrent integrity);
    prunes clutter (.nfo, .txt, .url, samples < 50MB) and empty directories when moving.
  - Full Undo Support: Logs operations to data/organizer_history.json for 1-click rollback.
  - Multi-Surface: CLI hook (for uTorrent/qBittorrent), REST API, and folder watcher compatible.
"""

import os
import sys
import re
import json
import time
import shutil
import uuid
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Ensure project root in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.utils.paths import BASE_DIR
from backend.matcher import _clean_name
from backend.scanner import _parse_episode, VIDEO_EXTS
from backend.sub_naming import parse_filename, format_filename_tag, normalize_lang

# Supported Local Regions mapping ISO 3166-1 alpha-2 -> English Name
REGIONS: Dict[str, str] = {
    "PH": "Philippines",
    "US": "United States",
    "GB": "United Kingdom",
    "KR": "South Korea",
    "JP": "Japan",
    "ES": "Spain",
    "FR": "France",
    "DE": "Germany",
    "CA": "Canada",
    "AU": "Australia",
    "IN": "India",
    "IT": "Italy",
    "MX": "Mexico",
    "BR": "Brazil",
    "TH": "Thailand",
}


def get_organizer_library_roots(cfg: Dict[str, Any]) -> Dict[str, str]:
    """
    Build the canonical library roots dictionary from server config.
    Synchronizes roots across REST API, background watcher, and CLI.
    """
    org_cfg = cfg.get("organizer", {})
    media_paths = cfg.get("media_paths", {})

    def _first_or(val, default):
        if isinstance(val, list):
            return val[0] if val else default
        return val or default

    target_movies = org_cfg.get("target_movies_path") or _first_or(
        media_paths.get("movies"), os.path.join(BASE_DIR, "data", "media", "Movies")
    )
    target_series = org_cfg.get("target_series_path") or _first_or(
        media_paths.get("series") or media_paths.get("tv"), os.path.join(BASE_DIR, "data", "media", "TV Shows")
    )
    target_anime = org_cfg.get("target_anime_path") or _first_or(
        media_paths.get("anime"), os.path.join(BASE_DIR, "data", "media", "Anime")
    )

    roots: Dict[str, str] = {
        "movies": target_movies,
        "tv": target_series,
        "anime": target_anime,
    }

    target_local_movies = org_cfg.get("target_local_movies_path")
    if target_local_movies and str(target_local_movies).strip():
        roots["local_movies"] = str(target_local_movies).strip()

    target_local_series = org_cfg.get("target_local_series_path")
    if target_local_series and str(target_local_series).strip():
        roots["local_tv"] = str(target_local_series).strip()

    return roots


# Constants
SUBTITLE_EXTS = {".srt", ".ass", ".vtt", ".sub", ".idx"}
INCOMPLETE_EXTS = {".part", ".!ut", ".crdownload", ".tmp", ".downloading", ".aria2", ".temp"}
CLUTTER_EXTS = {".nfo", ".txt", ".url", ".website", ".lnk", ".exe", ".bat", ".cmd", ".md"}
SAMPLE_SIZE_THRESHOLD_BYTES = 50 * 1024 * 1024  # 50 MB

ORGANIZER_HISTORY_FILE = os.path.join(BASE_DIR, "data", "organizer_history.json")
REQUESTS_FILE = os.path.join(BASE_DIR, "data", "requests.json")

logger = logging.getLogger("media_organizer")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[MediaOrganizer] %(levelname)s: %(message)s"))
    logger.addHandler(sh)


# ─── File Safety & Protection ──────────────────────────────────────────────────

def is_incomplete_file(file_path: str) -> bool:
    """Return True if the file matches an active/temporary download extension."""
    base, ext = os.path.splitext(file_path)
    ext_lower = ext.lower()
    if ext_lower in INCOMPLETE_EXTS:
        return True
    if any(base.lower().endswith(inc) for inc in INCOMPLETE_EXTS):
        return True
    return False


def is_file_locked(file_path: str) -> bool:
    """
    Check if a file is currently open with an exclusive write lock by another process.
    On Windows, attempts a non-sharing read/write open.
    """
    if is_incomplete_file(file_path):
        return True

    if not os.path.exists(file_path):
        return False

    if sys.platform == "win32":
        try:
            # On Windows, opening with 'r+b' fails with PermissionError (WinError 32)
            # if a downloader (like qBittorrent or uTorrent) holds a write lock.
            with open(file_path, "r+b"):
                pass
            return False
        except (PermissionError, OSError):
            return True
    else:
        try:
            with open(file_path, "a+"):
                pass
            return False
        except (PermissionError, OSError):
            return True


def is_file_settled(file_path: str, min_age_seconds: float = 15.0) -> bool:
    """Check if the file has existed without modifications for at least min_age_seconds."""
    if not os.path.exists(file_path):
        return False
    try:
        mtime = os.path.getmtime(file_path)
        return (time.time() - mtime) >= min_age_seconds
    except OSError:
        return False


def is_clutter(file_path: str) -> bool:
    """Return True for samples, text files, nfo, url shortcuts, or tiny promo videos."""
    fname = os.path.basename(file_path).lower()
    ext = os.path.splitext(fname)[1]

    if ext in CLUTTER_EXTS:
        return True

    # Sample detection
    if re.search(r'(?:^|[\._\-\s])sample(?:[\._\-\s]|$)', fname):
        if not os.path.exists(file_path):
            return True
        try:
            size = os.path.getsize(file_path)
            if size < SAMPLE_SIZE_THRESHOLD_BYTES:
                return True
        except OSError:
            return True

    return False


def is_media_file(file_path: str) -> bool:
    """Return True if file is a playable media file and not clutter."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in VIDEO_EXTS:
        return False
    if is_clutter(file_path):
        return False
    return True


def is_subtitle_file(file_path: str) -> bool:
    """Return True if file is a supported subtitle format."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUBTITLE_EXTS


# ─── Media Classification & Parsing ───────────────────────────────────────────

ANIME_RELEASE_GROUPS = {
    "subsplease", "erai-raws", "horriblesubs", "judas", "asw", "golumpa",
    "commie", "cleo", "ember", "moozzi2", "smallsizedanimations", "db",
    "anime time", "puyasubs!", "nc-raws", "nekomoe kissaten", "b-global",
    "tsundere", "coalgirls", "doki", "chibiki", "kessen"
}


# Movie sequel, chapter, volume, and franchise indicators that must NOT be parsed as TV episode numbers
_MOVIE_SEQUEL_KEYWORD_RE = re.compile(
    r'\b(?:part|chapter|vol(?:ume)?|act|phase|saga|movie|film)[\s._-]*(\d+|[ivxlcdm]+)\b',
    re.IGNORECASE
)
_STAR_WARS_EPISODE_RE = re.compile(
    r'\bstar[\s._-]*wars.*?episode[\s._-]*([ivxlcdm]+|\d+)\b',
    re.IGNORECASE
)


def _detect_episodic_signature(
    filename: str,
    parent_dir: str = "",
    hint_title: Optional[str] = None
) -> Tuple[bool, Optional[int], Optional[int]]:
    """
    Carefully inspect filename, hint_title, and parent directory to determine whether
    the media file is an episode of a TV series.
    Returns (is_tv: bool, season: Optional[int], episode: Optional[int]).

    Protects against movie sequels, prequels, chapters, volumes, Roman numerals,
    and numbered movie titles (e.g. Deadpool 2, Spider-Man 2, Iron Man 3, Dune Part 2,
    Star Wars Episode II, Ocean's 11, 300, District 9, 1917).
    """
    name = os.path.splitext(filename)[0]
    target = hint_title if hint_title else name

    # 1. Standard scene notation: S01E02, s1e2, S02E15, S01.E02, S01_E02
    m_sxe = re.search(r'[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})', target)
    if m_sxe:
        return True, int(m_sxe.group(1)), int(m_sxe.group(2))

    # 2. Standard 1x02 notation
    m_x = re.search(r'\b(\d{1,2})[xX](\d{1,3})\b', target)
    if m_x:
        return True, int(m_x.group(1)), int(m_x.group(2))

    # 3. Check for Season directory in parent folder: e.g. "Season 1", "Season 02", "Staffel 2", "Series 3"
    season_from_parent = None
    if parent_dir:
        m_sdir = re.search(r'\b(?:[Ss]eason|[Ss]taffel|[Ss]aison|[Ss]eries)[\s._-]*(\d{1,2})\b', parent_dir, re.IGNORECASE)
        if not m_sdir:
            m_sdir = re.search(r'^[Ss](\d{1,2})$', parent_dir.strip())
        if m_sdir:
            season_from_parent = int(m_sdir.group(1))

    # 4. Check for explicit episode prefix: "E02", "EP02", "Episode 02"
    # Guard: Must NOT be a movie sequel keyword like "Star Wars Episode II" or "Part 2"
    if not _STAR_WARS_EPISODE_RE.search(target):
        m_ep = re.search(r'(?:^|[\s._\-\[\(])(?:[Ee]pisode|[Ee]p)[\s._-]*(\d{1,3})(?:[\s._\-\]\)]|$)', target, re.IGNORECASE)
        if m_ep:
            ep_num = int(m_ep.group(1))
            return True, (season_from_parent or 1), ep_num

        m_single_e = re.search(r'(?:^|[\s._\-\[\(])[Ee](\d{2,3})(?:[\s._\-\]\)]|$)', target)
        if m_single_e:
            ep_num = int(m_single_e.group(1))
            return True, (season_from_parent or 1), ep_num

    # 5. If inside a verified Season folder, check if there's an episode number (e.g. "01 - Title" or "02")
    if season_from_parent is not None:
        m_num = re.search(r'(?:^|[\s._\-\[\(])(\d{1,3})(?:[\s._\-\]\)]|$)', target)
        if m_num:
            return True, season_from_parent, int(m_num.group(1))
        return True, season_from_parent, 1

    return False, None, None


def _check_anime_signature(filename: str, hint_title: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[int], Optional[int]]:
    """
    Inspect filename and hint for anime release groups, bracket patterns, or absolute episode numbering.
    Returns (is_anime: bool, title: Optional[str], season: Optional[int], episode: Optional[int]).
    """
    target = hint_title if hint_title else filename

    # 1. Fansub group in brackets at start: [SubsPlease] Show Name - 01 (1080p) [CRC].mkv
    m_group = re.match(r"^\[([A-Za-z0-9_ \-\.!]+)\]\s*(.+)$", target)
    if m_group:
        group_name = m_group.group(1).strip().lower()
        rest = m_group.group(2).strip()
        is_known_group = group_name in ANIME_RELEASE_GROUPS

        # Check for episode number pattern in rest: e.g. "Show Name - 28 (1080p)..."
        m_dash = re.search(r"^(.*?)\s+-\s+(\d{1,4})(?:\s*v\d)?(?:\s*[\(\[\._]|\s*$)", rest)
        if m_dash:
            raw_title = m_dash.group(1).strip()
            ep_num = int(m_dash.group(2))
            s_match = re.search(r'[Ss](\d{1,2})', raw_title)
            season = int(s_match.group(1)) if s_match else 1
            clean_t, _, _ = _clean_name(raw_title)
            return True, clean_t, season, ep_num

        if is_known_group:
            m_sxe = re.search(r'[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})', rest)
            if m_sxe:
                clean_t, _, _ = _clean_name(rest)
                return True, clean_t, int(m_sxe.group(1)), int(m_sxe.group(2))
            clean_t, _, _ = _clean_name(rest)
            return True, clean_t, 1, 1

    # 2. Pattern: Show Title - 01 [1080p].mkv (Must be zero-padded 2+ digits or 3 digits, NOT a single digit movie sequel)
    # Must NOT have movie sequel keywords like Part, Chapter, Vol, or movie release year
    if not _MOVIE_SEQUEL_KEYWORD_RE.search(target):
        m_dash_ep = re.search(r"^(.+?)\s+-\s+(0\d|\d{2,4})(?:\s*v\d)?(?:\s*[\(\[\._]|\s*$)", target)
        if m_dash_ep and not re.search(r'[Ss]\d{1,2}[Ee]\d{1,4}', target):
            ep_str = m_dash_ep.group(2)
            # Guard against 4-digit release years (19xx, 20xx)
            if not (len(ep_str) == 4 and (ep_str.startswith("19") or ep_str.startswith("20"))):
                raw_title = m_dash_ep.group(1).strip()
                ep_num = int(ep_str)
                clean_t, y, _ = _clean_name(raw_title)
                if clean_t and clean_t.lower() not in ("sample", "trailer", "preview"):
                    return True, clean_t, 1, ep_num

    return False, None, None, None


def classify_media_file(file_path: str, hint_title: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse filename and directory path to determine media type (movie vs tv vs anime),
    season, episode, title, and year.
    Accurately classifies movie sequels, prequels, and franchises (e.g. Deadpool 2, Dune Part Two).
    """
    filename = os.path.basename(file_path)
    parent_dir = os.path.basename(os.path.dirname(file_path))
    clean_target = hint_title if hint_title else filename

    # 1. Check Anime signature
    is_anime, anime_title, anime_season, anime_ep = _check_anime_signature(filename, hint_title)

    # 2. Check TV episodic signature (protects against sequel/prequel movie titles)
    is_tv, tv_season, tv_episode = _detect_episodic_signature(filename, parent_dir, hint_title)

    clean_title, year, imdb_id = _clean_name(clean_target)

    # 3. Determine media_type and final parsed title
    if is_anime:
        media_type = "anime"
        title = anime_title or clean_title
        season = anime_season or tv_season or 1
        episode = anime_ep or tv_episode or 1
    elif is_tv:
        media_type = "tv"
        title = clean_title
        season = tv_season or 1
        episode = tv_episode or 1
    else:
        media_type = "movie"
        title = clean_title
        season = None
        episode = None

    title = sanitize_filename(title)

    # Confidence check
    confidence = "high"
    if not title or title.lower() in ("unknown", "video", "download", "movie", "series") or len(title) <= 2:
        confidence = "low"
    elif media_type == "movie" and not year and not imdb_id and len(title) < 5:
        confidence = "low"

    return {
        "file_path": file_path,
        "filename": filename,
        "media_type": media_type,
        "title": title,
        "year": year,
        "season": season,
        "episode": episode,
        "imdb_id": imdb_id,
        "confidence": confidence,
        "extension": os.path.splitext(filename)[1].lower(),
        "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
    }



def sanitize_filename(name: str) -> str:
    """Strip or replace characters that are invalid in Windows and POSIX filenames."""
    if not name:
        return "Unknown"
    sanitized = re.sub(r'[\\/*?:"<>|]', '', name)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized or "Unknown"


# ─── Hybrid Identification & Resolution ──────────────────────────────────────

def resolve_with_requests(item: Dict[str, Any], requests_file: str = REQUESTS_FILE) -> Optional[Dict[str, Any]]:
    """Check if the item fulfills an active request in data/requests.json."""
    if not os.path.exists(requests_file):
        return None

    try:
        with open(requests_file, "r", encoding="utf-8") as f:
            reqs = json.load(f)
            if not isinstance(reqs, list):
                return None
    except Exception as e:
        logger.warning(f"Error reading {requests_file}: {e}")
        return None

    item_title = item.get("title", "").lower()
    item_year = str(item.get("year") or "")
    item_type = item.get("media_type")

    for req in reqs:
        raw_rtype = req.get("type", "").lower()
        if raw_rtype == "anime":
            r_type = "anime"
        elif raw_rtype in ("movie", "movies"):
            r_type = "movie"
        else:
            r_type = "tv"

        # Allow anime request to match tv or anime item
        if r_type != item_type and not (r_type == "anime" and item_type in ("tv", "anime")):
            continue

        r_title = (req.get("title") or "").strip().lower()
        r_year = str(req.get("year") or "")

        # Compare titles
        if r_title and (r_title == item_title or r_title in item_title or item_title in r_title):
            if not item_year or not r_year or item_year == r_year:
                matched_type = "anime" if r_type == "anime" else item_type
                return {
                    "request_id": req.get("id"),
                    "canonical_title": req.get("title"),
                    "year": int(req.get("year")) if str(req.get("year", "")).isdigit() else item.get("year"),
                    "media_type": matched_type,
                    "matched_by": "requests.json",
                }

    return None


def resolve_canonical_item(
    item: Dict[str, Any],
    tmdb_api_key: Optional[str] = None,
    local_region: str = ""
) -> Dict[str, Any]:
    """
    Resolve canonical title and year using requests.json first,
    optionally TMDb API lookup, with local parsing as fallback.
    Also detects origin countries and route reason for local region routing.
    """
    resolved = dict(item)
    origin_countries: List[str] = []

    # 1. Check data/requests.json
    req_match = resolve_with_requests(item)
    if req_match:
        resolved["canonical_title"] = req_match["canonical_title"]
        if req_match.get("year"):
            resolved["year"] = req_match["year"]
        if req_match.get("media_type"):
            resolved["media_type"] = req_match["media_type"]
        resolved["match_source"] = "requests.json"
        resolved["request_id"] = req_match.get("request_id")
        resolved["origin_countries"] = []
        if local_region and local_region.strip():
            resolved["is_local"] = False
            resolved["route_reason"] = "origin-unknown"
            logger.info(f"Origin unknown for '{resolved['canonical_title']}'; routed normally.")
        else:
            resolved["is_local"] = False
            resolved["route_reason"] = "region-off"
        return resolved

    # 2. Check TMDb API if key is supplied (uses search/multi for cross-type disambiguation)
    if tmdb_api_key:
        try:
            import requests
            endpoint = "https://api.themoviedb.org/3/search/multi"
            params = {
                "api_key": tmdb_api_key,
                "query": item["title"],
                "include_adult": "false"
            }
            resp = requests.get(endpoint, params=params, timeout=5)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                valid_results = [r for r in results if r.get("media_type") in ("movie", "tv")]
                if valid_results:
                    # If item had a parsed release year, prioritize matching that year
                    best = None
                    target_year = item.get("year")
                    if target_year:
                        for r in valid_results:
                            r_date = r.get("release_date") if r.get("media_type") == "movie" else r.get("first_air_date")
                            if r_date and len(r_date) >= 4 and r_date[:4] == str(target_year):
                                best = r
                                break
                    if not best:
                        best = valid_results[0]

                    tmdb_type = best.get("media_type")  # "movie" or "tv"
                    canonical = best.get("title") if tmdb_type == "movie" else best.get("name")
                    release_date = best.get("release_date") if tmdb_type == "movie" else best.get("first_air_date")
                    resolved_year = None
                    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
                        resolved_year = int(release_date[:4])

                    if canonical:
                        resolved["canonical_title"] = sanitize_filename(canonical)
                        if resolved_year:
                            resolved["year"] = resolved_year
                        resolved["tmdb_id"] = best.get("id")
                        resolved["match_source"] = "tmdb"

                        # Extract origin countries
                        if tmdb_type == "tv":
                            origin_countries = [
                                str(c).strip().upper() for c in best.get("origin_country", []) if c
                            ]
                        elif tmdb_type == "movie":
                            # Movie search results omit production countries; call movie details only when local_region is set
                            if local_region and local_region.strip() and resolved.get("tmdb_id"):
                                try:
                                    m_resp = requests.get(
                                        f"https://api.themoviedb.org/3/movie/{resolved['tmdb_id']}",
                                        params={"api_key": tmdb_api_key},
                                        timeout=5
                                    )
                                    if m_resp.status_code == 200:
                                        prod_countries = m_resp.json().get("production_countries", [])
                                        origin_countries = [
                                            str(c.get("iso_3166_1", "")).strip().upper()
                                            for c in prod_countries if c.get("iso_3166_1")
                                        ]
                                except Exception as e:
                                    logger.debug(f"TMDb movie details origin country lookup skipped: {e}")

                        # Detect Japanese animation as Anime
                        is_japanese = best.get("original_language") == "ja"
                        is_animation = 16 in best.get("genre_ids", [])
                        if is_japanese and is_animation:
                            resolved["media_type"] = "anime"
                        elif tmdb_type == "movie":
                            resolved["media_type"] = "movie"
                            resolved["season"] = None
                            resolved["episode"] = None
                        elif tmdb_type == "tv":
                            # Only set TV if not already classified as Anime
                            if resolved.get("media_type") != "anime":
                                resolved["media_type"] = "tv"
                                resolved["season"] = resolved.get("season") or 1
                                resolved["episode"] = resolved.get("episode") or 1

                        resolved["origin_countries"] = origin_countries
                        if local_region and local_region.strip():
                            reg_code = local_region.strip().upper()
                            if origin_countries:
                                if reg_code in origin_countries:
                                    resolved["is_local"] = True
                                    resolved["route_reason"] = "local"
                                else:
                                    resolved["is_local"] = False
                                    resolved["route_reason"] = "non-local"
                            else:
                                resolved["is_local"] = False
                                resolved["route_reason"] = "origin-unknown"
                                logger.info(f"Origin unknown for '{resolved['canonical_title']}'; routed normally.")
                        else:
                            resolved["is_local"] = False
                            resolved["route_reason"] = "region-off"

                        return resolved
        except Exception as e:
            logger.debug(f"TMDb query skipped or failed: {e}")

    # 3. Fallback to clean parsed title
    resolved["canonical_title"] = sanitize_filename(item["title"])
    resolved["match_source"] = "parsed"
    resolved["origin_countries"] = []
    if local_region and local_region.strip():
        resolved["is_local"] = False
        resolved["route_reason"] = "origin-unknown"
        logger.info(f"Origin unknown for '{resolved['canonical_title']}'; routed normally.")
    else:
        resolved["is_local"] = False
        resolved["route_reason"] = "region-off"
    return resolved


# ─── Path Construction ─────────────────────────────────────────────────────────

def build_destination_path(resolved_item: Dict[str, Any], library_roots: Dict[str, Any]) -> str:
    """
    Construct the standard Plex/CapsStream destination path for Movies, TV, and Anime:
      Movies:    {movies_root}/{Title} ({Year})/{Title} ({Year}).ext
      TV Series: {tv_root}/{Title}/Season {SS:02d}/{Title} - S{SS:02d}E{EE:02d}.ext
      Anime:     {anime_root}/{Title}/Season {SS:02d}/{Title} - S{SS:02d}E{EE:02d}.ext

    Supports local region destination routing for Movies and TV (Anime is always untouched).
    """
    media_type = resolved_item["media_type"]
    title = resolved_item["canonical_title"]
    year = resolved_item.get("year")
    ext = resolved_item["extension"]
    is_local = bool(resolved_item.get("is_local"))

    year_str = f" ({year})" if year else ""

    if media_type == "movie":
        if is_local and library_roots.get("local_movies"):
            raw_root = library_roots.get("local_movies")
        else:
            raw_root = library_roots.get("movies")
        default_dir = os.path.join(BASE_DIR, "data", "media", "Movies")
    elif media_type == "anime":
        # Anime is untouched and always uses anime root
        raw_root = library_roots.get("anime")
        default_dir = os.path.join(BASE_DIR, "data", "media", "Anime")
    else:
        # TV / series
        if is_local and library_roots.get("local_tv"):
            raw_root = library_roots.get("local_tv")
        else:
            raw_root = library_roots.get("tv") or library_roots.get("series")
        default_dir = os.path.join(BASE_DIR, "data", "media", "TV Shows")

    if isinstance(raw_root, list):
        root = raw_root[0] if raw_root else default_dir
    elif isinstance(raw_root, str) and raw_root:
        root = raw_root
    else:
        root = default_dir

    if media_type == "movie":
        folder_name = f"{title}{year_str}"
        file_name = f"{title}{year_str}{ext}"
        return os.path.join(root, folder_name, file_name)
    elif media_type == "anime":
        season_num = resolved_item.get("season", 1) or 1
        episode_num = resolved_item.get("episode", 1) or 1
        show_folder = f"{title}"
        season_folder = f"Season {season_num:02d}"
        file_name = f"{title} - S{season_num:02d}E{episode_num:02d}{ext}"
        return os.path.join(root, show_folder, season_folder, file_name)
    else:
        show_folder = f"{title}{year_str}"
        season_num = resolved_item.get("season", 1) or 1
        episode_num = resolved_item.get("episode", 1) or 1
        season_folder = f"Season {season_num:02d}"
        file_name = f"{title} - S{season_num:02d}E{episode_num:02d}{ext}"
        return os.path.join(root, show_folder, season_folder, file_name)


# ─── Execution & Smart Linking ─────────────────────────────────────────────────

def execute_file_operation(src: str, dst: str, mode: str = "smart") -> Tuple[bool, str, Optional[str]]:
    """
    Execute file placement:
      - "smart": Hardlinks if on the same drive root, else moves.
      - "move": Moves file.
      - "copy": Copies file.

    Returns (success: bool, action_taken: str, error_message: Optional[str]).
    """
    if not os.path.exists(src):
        return False, "none", f"Source file does not exist: {src}"

    # Ensure parent destination directory exists
    dst_dir = os.path.dirname(dst)
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except Exception as e:
        return False, "none", f"Could not create destination directory {dst_dir}: {e}"

    # If destination exists, return collision note (caller decides collision policy)
    if os.path.exists(dst):
        if os.path.samefile(src, dst):
            return True, "already_linked", None
        return False, "collision", f"Destination file already exists: {dst}"

    # Smart mode: check same drive
    if mode == "smart":
        src_drive = os.path.splitdrive(os.path.abspath(src))[0].lower()
        dst_drive = os.path.splitdrive(os.path.abspath(dst))[0].lower()

        if src_drive and dst_drive and src_drive == dst_drive:
            try:
                os.link(src, dst)
                return True, "hardlink", None
            except OSError as e:
                logger.info(f"Hardlink failed ({e}); falling back to move: {src} -> {dst}")

        # Cross-drive or link unsupported: fallback to move
        try:
            shutil.move(src, dst)
            return True, "move", None
        except Exception as e:
            return False, "none", f"Move failed: {e}"

    elif mode == "move":
        try:
            shutil.move(src, dst)
            return True, "move", None
        except Exception as e:
            return False, "none", f"Move failed: {e}"

    elif mode == "copy":
        try:
            shutil.copy2(src, dst)
            return True, "copy", None
        except Exception as e:
            return False, "none", f"Copy failed: {e}"

    return False, "none", f"Unknown mode: {mode}"


def disambiguate_video_path(dest_path: str, existing_set: Optional[set] = None) -> str:
    """
    Append numeric suffix ' (2)', ' (3)' to a video destination path until non-colliding.
    """
    if (existing_set is None or dest_path not in existing_set) and not os.path.exists(dest_path):
        if existing_set is not None:
            existing_set.add(dest_path)
        return dest_path

    base, ext = os.path.splitext(dest_path)
    idx = 2
    while True:
        candidate = f"{base} ({idx}){ext}"
        if (existing_set is None or candidate not in existing_set) and not os.path.exists(candidate):
            if existing_set is not None:
                existing_set.add(candidate)
            return candidate
        idx += 1


def detect_subtitle_language(sub_path: str) -> Optional[str]:
    """
    Inspect the text content of a subtitle file to detect its ISO 639-1 language code.
    Reads up to 120 lines and checks character scripts and high-frequency stopwords.
    Returns ISO 639-1 code if confidently detected, else None.
    """
    if not os.path.isfile(sub_path):
        return None
    try:
        with open(sub_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = []
            for _ in range(120):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line or line.isdigit() or "-->" in line:
                    continue
                clean = re.sub(r"<[^>]+>", "", line).lower()
                clean = re.sub(r"\[.*?\]|\(.*?\)", "", clean).strip()
                if clean:
                    lines.append(clean)

            if not lines:
                return None

            full_text = " ".join(lines)

            # Non-Latin script checks
            if len(re.findall(r"[\u0400-\u04FF]", full_text)) >= 10:
                if any(w in full_text for w in ("і", "ї", "є")):
                    return "uk"
                return "ru"
            if len(re.findall(r"[\u0600-\u06FF]", full_text)) >= 10:
                return "ar"
            if len(re.findall(r"[\u3040-\u30FF]", full_text)) >= 5:
                return "ja"
            if len(re.findall(r"[\u4E00-\u9FFF]", full_text)) >= 10:
                return "zh"
            if len(re.findall(r"[\uAC00-\uD7AF]", full_text)) >= 5:
                return "ko"
            if len(re.findall(r"[\u0370-\u03FF]", full_text)) >= 10:
                return "el"
            if len(re.findall(r"[\u0590-\u05FF]", full_text)) >= 10:
                return "he"
            if len(re.findall(r"[\u0E00-\u0E7F]", full_text)) >= 10:
                return "th"

            # Latin stopwords
            words = set(re.findall(r"\b[a-zA-Z]{2,}\b", full_text.lower()))
            en_stop = {"the", "you", "to", "and", "that", "it", "is", "what", "of", "in", "we", "he", "she", "for", "on", "with", "this", "have", "from", "be", "my", "all", "do", "no", "are", "not", "your"}
            fr_stop = {"vous", "nous", "avec", "pour", "dans", "cette", "sont", "pas", "une", "les", "des", "est", "que", "qui"}
            es_stop = {"que", "para", "por", "con", "una", "uno", "los", "las", "este", "esta", "como", "pero", "mas", "del"}
            de_stop = {"nicht", "eine", "einer", "einem", "einen", "oder", "aber", "sind", "das", "ist", "und", "mit"}
            tl_stop = {"ang", "mga", "ng", "sa", "hindi", "para", "dahil", "ako", "ikaw", "siya", "kami", "tayo"}
            it_stop = {"non", "che", "per", "con", "una", "sono", "cosa", "questo", "della", "delle"}
            pt_stop = {"nao", "que", "para", "com", "uma", "voce", "esta", "isso", "esse"}

            scores = [
                ("en", len(words & en_stop)),
                ("fr", len(words & fr_stop)),
                ("es", len(words & es_stop)),
                ("de", len(words & de_stop)),
                ("tl", len(words & tl_stop)),
                ("it", len(words & it_stop)),
                ("pt", len(words & pt_stop)),
            ]
            scores.sort(key=lambda x: x[1], reverse=True)
            if scores[0][1] >= 2 and scores[0][1] > scores[1][1]:
                return scores[0][0]
    except Exception:
        pass
    return None


def parse_subtitle_details(sub_path: str, media_basename: str = "") -> Dict[str, Any]:
    """
    Extract language code, hearing-impaired (HI/SDH) status, forced status,
    and priority rank from a subtitle filename and its directory tree.
    Reimplemented on top of backend.sub_naming with content-aware fallback.

    Priority ranking (lower = higher priority):
      0: English standard (eng / en)
      1: English Hearing Impaired (HI eng / SDH / CC)
      2: English Forced
      3: Generic / default subtitle matching media name without language tag
      4: Other recognized language (es, fr, de, ja, etc.)
      5: Unknown / undetermined
    """
    p = parse_filename(sub_path, parent_folder=os.path.basename(os.path.dirname(sub_path)))
    lang = p.lang
    is_hi = p.is_hi
    is_forced = p.is_forced
    stem = os.path.splitext(os.path.basename(sub_path))[0].lower()
    parent = os.path.basename(os.path.dirname(sub_path)).lower()

    # 1. Content inspection if language is undetermined
    if lang == "und" and os.path.isfile(sub_path):
        detected = detect_subtitle_language(sub_path)
        if detected:
            lang = detected

    # 2. Check if this is a companion subtitle belonging to the media file
    is_companion = False
    if media_basename:
        m_res = _clean_name(media_basename)
        m_clean = (m_res[0] if isinstance(m_res, tuple) else str(m_res)).strip().lower()
        s_res = _clean_name(stem)
        s_clean = (s_res[0] if isinstance(s_res, tuple) else str(s_res)).strip().lower()
        if (m_clean and s_clean and (s_clean.startswith(m_clean) or m_clean.startswith(s_clean))) or stem.startswith(media_basename.lower()):
            is_companion = True
    if parent in ("subs", "subtitles", "sub", "eng", "english") or is_forced or is_hi:
        is_companion = True

    # 3. Companion subtitle defaulting: if it's a companion without an explicit language code,
    # default to English ("en")
    if lang == "und" and is_companion:
        lang = "en"

    is_eng = (lang == "en")

    # Priority Rank: English standard (0) -> HI English (1) -> Forced (2) -> Generic (3) -> Other (4) -> Unknown (5)
    if is_eng and not is_hi and not is_forced:
        priority = 0
    elif is_eng and is_hi:
        priority = 1
    elif is_eng and is_forced:
        priority = 2
    elif is_companion and lang == "und":
        priority = 3
    elif lang != "und":
        priority = 4
    else:
        priority = 5

    return {
        "lang": lang,
        "is_hi": is_hi,
        "is_forced": is_forced,
        "is_eng": is_eng,
        "is_companion": is_companion,
        "priority": priority,
    }


def build_subtitle_destination_path(
    sub_src: str,
    media_dst: str,
    existing_destinations: Optional[set] = None
) -> str:
    """
    Build a standard Plex/CapsStream-compliant destination path for a companion subtitle.
    Pattern: <Media Name>.<lang>[.<flag>][.<num>].<ext>
    If language is unknown and not a companion subtitle (e.g. Director_Commentary_Track),
    the subtitle keeps its original filename.
    """
    if existing_destinations is None:
        existing_destinations = set()

    sub_ext = os.path.splitext(sub_src)[1].lower()
    dst_dir = os.path.dirname(media_dst)
    dst_base = os.path.splitext(media_dst)[0]

    info = parse_subtitle_details(sub_src, media_basename=os.path.basename(dst_base))
    lang = info["lang"]
    is_hi = info["is_hi"]
    is_forced = info["is_forced"]

    # Unknown language and not a companion track: keep original filename inside destination directory
    if lang == "und" and not is_hi and not is_forced:
        logger.info(f"Unknown language for subtitle '{os.path.basename(sub_src)}'; keeping original filename.")
        orig_fname = os.path.basename(sub_src)
        candidate = os.path.join(dst_dir, orig_fname)
        if candidate not in existing_destinations and not os.path.exists(candidate):
            existing_destinations.add(candidate)
            return candidate

        orig_stem, orig_ext = os.path.splitext(orig_fname)
        idx = 2
        while True:
            disambiguated = os.path.join(dst_dir, f"{orig_stem}.{idx}{orig_ext}")
            if disambiguated not in existing_destinations and not os.path.exists(disambiguated):
                existing_destinations.add(disambiguated)
                return disambiguated
            idx += 1

    # Standard Plex/CapsStream-compliant companion subtitle naming
    tag = f".{lang}" if lang != "und" else ""
    if is_hi:
        tag += ".hi"
    elif is_forced:
        tag += ".forced"

    candidate = f"{dst_base}{tag}{sub_ext}"
    if candidate not in existing_destinations and not os.path.exists(candidate):
        existing_destinations.add(candidate)
        return candidate

    idx = 2
    while True:
        disambiguated = f"{dst_base}{tag}.{idx}{sub_ext}"
        if disambiguated not in existing_destinations and not os.path.exists(disambiguated):
            existing_destinations.add(disambiguated)
            return disambiguated
        idx += 1


def find_companion_subtitles(media_file_path: str) -> List[str]:
    """
    Find and prioritize companion subtitles for a media file.
    Searches the parent directory and allowed subtitle subfolders (Subs, Subtitles, eng, etc.).
    Always prioritizes English (.en / .eng) and HI English (.en.hi / .en.sdh / .cc) subtitles first.
    """
    parent_dir = os.path.dirname(media_file_path)
    if not os.path.isdir(parent_dir):
        return []

    base_name = os.path.splitext(os.path.basename(media_file_path))[0].lower()

    video_files = [f for f in os.listdir(parent_dir) if is_media_file(os.path.join(parent_dir, f))]
    has_multiple_videos = len(video_files) > 1

    ep_match = re.search(r"(s\d+e\d+|\d+x\d+|e\d+)", base_name)
    ep_token = ep_match.group(0) if ep_match else None

    found_subs = set()

    # 1. Search in parent directory
    try:
        for entry in os.listdir(parent_dir):
            ep_path = os.path.join(parent_dir, entry)
            if not os.path.isfile(ep_path):
                continue
            entry_base, entry_ext = os.path.splitext(entry)
            if entry_ext.lower() in SUBTITLE_EXTS:
                if entry_base.lower().startswith(base_name):
                    found_subs.add(ep_path)
                elif not has_multiple_videos:
                    found_subs.add(ep_path)
                elif ep_token and ep_token in entry_base.lower():
                    found_subs.add(ep_path)
    except OSError:
        pass

    # 2. Search in allowed subfolders: Subs, Subtitles, sub, subs, eng, english
    for sub_dir_name in ["subs", "subtitles", "sub", "eng", "english"]:
        sub_folder = os.path.join(parent_dir, sub_dir_name)
        if os.path.isdir(sub_folder):
            try:
                for root, _, files in os.walk(sub_folder):
                    for f in files:
                        _, f_ext = os.path.splitext(f)
                        if f_ext.lower() in SUBTITLE_EXTS:
                            fp = os.path.join(root, f)
                            f_lower = f.lower()
                            if not has_multiple_videos:
                                found_subs.add(fp)
                            elif ep_token and ep_token in f_lower:
                                found_subs.add(fp)
                            elif f_lower.startswith(base_name):
                                found_subs.add(fp)
            except OSError:
                pass

    # 3. Deduplicate exact duplicate files (e.g. YTS root subtitle duplicate of Subs/Forced.eng.srt)
    subs_folder_fingerprints = {}
    for p in found_subs:
        rel_parent = os.path.basename(os.path.dirname(p)).lower()
        if rel_parent in ("subs", "subtitles", "sub", "eng", "english"):
            try:
                sz = os.path.getsize(p)
                with open(p, "rb") as fp:
                    head = fp.read(1024)
                subs_folder_fingerprints[(sz, head)] = p
            except OSError:
                pass

    unique_subs = []
    for p in found_subs:
        rel_parent = os.path.basename(os.path.dirname(p)).lower()
        # If this subtitle is beside media in parent directory and is an exact duplicate of a file in Subs/, skip root copy
        if rel_parent not in ("subs", "subtitles", "sub", "eng", "english") and subs_folder_fingerprints:
            try:
                sz = os.path.getsize(p)
                with open(p, "rb") as fp:
                    head = fp.read(1024)
                if (sz, head) in subs_folder_fingerprints:
                    continue
            except OSError:
                pass
        unique_subs.append(p)

    # 4. Sort subtitles strictly by priority: English (0) -> HI English (1) -> Forced (2) -> Generic (3) -> Other (4)
    sorted_subs = sorted(
        unique_subs,
        key=lambda p: (
            parse_subtitle_details(p, base_name)["priority"],
            os.path.basename(p).lower()
        )
    )

    return sorted_subs


# ─── Undo & History ────────────────────────────────────────────────────────────

def record_history(batch_id: str, operations: List[Dict[str, Any]], history_file: Optional[str] = None):
    """Append a batch of operations to data/organizer_history.json."""
    hist_path = history_file or ORGANIZER_HISTORY_FILE
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    history = []
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except Exception:
            history = []

    batch_record = {
        "batch_id": batch_id,
        "timestamp": datetime.now().isoformat(),
        "count": len(operations),
        "operations": operations
    }
    history.insert(0, batch_record)

    # Keep last 50 batches
    history = history[:50]

    try:
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to record organizer history: {e}")


def undo_batch(batch_id: str, history_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Rollback a specific organization batch.
    - If hardlinked: deletes the destination hardlink (source remains intact).
    - If moved: moves destination back to source.
    """
    hist_path = history_file or ORGANIZER_HISTORY_FILE
    if not os.path.exists(hist_path):
        return {"success": False, "error": "No history file found"}

    try:
        with open(hist_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception as e:
        return {"success": False, "error": f"Failed to read history: {e}"}

    target_batch = None
    batch_idx = -1
    for i, b in enumerate(history):
        if b.get("batch_id") == batch_id:
            target_batch = b
            batch_idx = i
            break

    if not target_batch:
        return {"success": False, "error": f"Batch {batch_id} not found in history"}

    reverted_count = 0
    errors = []

    for op in target_batch.get("operations", []):
        action = op.get("action")
        src = op.get("source")
        dst = op.get("destination")

        if action == "hardlink":
            # Just remove the created destination link
            if dst and os.path.exists(dst):
                try:
                    os.remove(dst)
                    reverted_count += 1
                except Exception as e:
                    errors.append(f"Failed to remove link {dst}: {e}")
        elif action == "move":
            # Move back from dst to src
            if dst and os.path.exists(dst):
                try:
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    shutil.move(dst, src)
                    reverted_count += 1
                except Exception as e:
                    errors.append(f"Failed to restore {dst} -> {src}: {e}")

    # Remove batch from history if fully reverted
    if not errors and batch_idx >= 0:
        history.pop(batch_idx)
        try:
            with open(hist_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return {
        "success": len(errors) == 0,
        "batch_id": batch_id,
        "reverted_count": reverted_count,
        "errors": errors
    }


# ─── Orchestrator (Preview & Execute) ──────────────────────────────────────────

def scan_incoming_for_preview(
    incoming_dir: str,
    library_roots: Dict[str, Any],
    tmdb_api_key: Optional[str] = None,
    clean_empty: bool = True,
    local_region: str = "",
    collision_policy: str = "skip",
) -> List[Dict[str, Any]]:
    """
    Perform a dry-run scan of an incoming directory.
    Returns list of proposed actions without modifying disk.
    If clean_empty is True, cleans up any empty subfolders after scanning.
    """
    if not os.path.isdir(incoming_dir):
        return []

    results = []
    existing_preview_destinations = set()
    existing_preview_subs = set()

    for root, dirs, files in os.walk(incoming_dir):
        # Skip hidden/temporary directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("$")]

        for fname in files:
            fpath = os.path.join(root, fname)

            # Check incomplete or clutter
            if is_incomplete_file(fpath) or is_clutter(fpath) or not is_media_file(fpath):
                continue

            classified = classify_media_file(fpath)
            resolved = resolve_canonical_item(classified, tmdb_api_key=tmdb_api_key, local_region=local_region)
            dest_path = build_destination_path(resolved, library_roots)

            dest_exists = os.path.exists(dest_path)
            if dest_exists and collision_policy == "suffix":
                dest_path = disambiguate_video_path(dest_path, existing_preview_destinations)
            else:
                existing_preview_destinations.add(dest_path)

            is_locked = is_file_locked(fpath)
            is_settled = is_file_settled(fpath)
            companions = find_companion_subtitles(fpath)

            # Build companion subtitle plan
            subtitle_plan = []
            for sub_src in companions:
                sub_dst = build_subtitle_destination_path(sub_src, dest_path, existing_preview_subs)
                details = parse_subtitle_details(sub_src, media_basename=os.path.basename(os.path.splitext(dest_path)[0]))
                flags = []
                if details.get("is_forced"):
                    flags.append("forced")
                if details.get("is_hi"):
                    flags.append("hi")
                action = "rename" if os.path.basename(sub_dst) != os.path.basename(sub_src) else "keep_name"
                subtitle_plan.append({
                    "source": sub_src,
                    "destination": sub_dst,
                    "lang": details.get("lang"),
                    "flags": flags,
                    "action": action,
                    "skipped_reason": None,
                })

            results.append({
                "source_path": fpath,
                "filename": fname,
                "media_type": resolved["media_type"],
                "canonical_title": resolved["canonical_title"],
                "year": resolved.get("year"),
                "season": resolved.get("season"),
                "episode": resolved.get("episode"),
                "match_source": resolved.get("match_source"),
                "request_id": resolved.get("request_id"),
                "destination_path": dest_path,
                "file_size": resolved["file_size"],
                "confidence": resolved.get("confidence", "high"),
                "is_locked": is_locked,
                "is_settled": is_settled,
                "subtitles": companions,
                "subtitle_plan": subtitle_plan,
                "destination_exists": dest_exists,
                "route_reason": resolved.get("route_reason", "region-off"),
                "origin_countries": resolved.get("origin_countries", []),
                "collision_policy": collision_policy,
            })

    if clean_empty and os.path.isdir(incoming_dir):
        clean_empty_subfolders(incoming_dir, delete_root_if_empty=False)

    return results


def execute_organization_plan(
    plan_items: List[Dict[str, Any]],
    mode: str = "smart",
    prune_empty_dirs: bool = True,
    incoming_dir: Optional[str] = None,
    history_file: Optional[str] = None,
    collision_policy: str = "skip",
) -> Dict[str, Any]:
    """
    Execute a batch of approved organization items.
    Records history for rollback and returns execution metrics.
    """
    batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    operations = []
    successful_items = []
    failed_items = []

    for item in plan_items:
        src = item["source_path"]
        dst = item["destination_path"]

        # Safety check: if file is locked or incomplete, skip
        if is_incomplete_file(src) or is_file_locked(src):
            failed_items.append({"source": src, "error": "File is currently locked or downloading"})
            continue

        item_policy = item.get("collision_policy") or collision_policy
        if os.path.exists(dst) and not os.path.samefile(src, dst):
            if item_policy == "suffix":
                dst = disambiguate_video_path(dst)
                item["destination_path"] = dst
            else:
                msg = f"Destination file already exists: {dst}"
                logger.info(f"Skipping {src} (collision): {msg}")
                failed_items.append({"source": src, "error": msg})
                continue

        ok, action_taken, err = execute_file_operation(src, dst, mode=mode)
        if ok:
            op_record = {
                "source": src,
                "destination": dst,
                "action": action_taken,
                "media_type": item.get("media_type"),
                "request_id": item.get("request_id"),
            }
            operations.append(op_record)
            successful_items.append(item)

            # Organize companion subtitles (prioritizing English and HI English)
            existing_sub_dsts = set()
            for sub_src in item.get("subtitles", []):
                sub_dst = build_subtitle_destination_path(sub_src, dst, existing_sub_dsts)

                s_ok, s_action, s_err = execute_file_operation(sub_src, sub_dst, mode=mode)
                if s_ok:
                    operations.append({
                        "source": sub_src,
                        "destination": sub_dst,
                        "action": s_action,
                        "type": "subtitle"
                    })
                else:
                    logger.warning(f"Could not organize companion subtitle {sub_src} -> {sub_dst}: {s_err}")

        else:
            failed_items.append({"source": src, "error": err or "Operation failed"})

    cleaned_folders = []
    if prune_empty_dirs:
        candidate_dirs = set()
        if incoming_dir and os.path.isdir(incoming_dir):
            candidate_dirs.add(os.path.abspath(incoming_dir))

        try:
            from backend.settings import load_config
            cfg = load_config()
            cfg_inc = cfg.get("organizer", {}).get("incoming_dir")
            if cfg_inc and os.path.isdir(cfg_inc):
                candidate_dirs.add(os.path.abspath(cfg_inc))
        except Exception:
            pass

        if not candidate_dirs:
            for it in plan_items:
                s = it.get("source_path") or it.get("source")
                if s:
                    parent = os.path.abspath(os.path.dirname(s))
                    if os.path.isdir(parent):
                        candidate_dirs.add(parent)

        for c_dir in sorted(candidate_dirs, key=lambda x: len(x)):
            cleaned_folders.extend(clean_empty_subfolders(c_dir, delete_root_if_empty=False))

    if operations:
        record_history(batch_id, operations, history_file=history_file)

    return {
        "batch_id": batch_id,
        "total": len(plan_items),
        "success": len(failed_items) == 0,
        "success_count": len(successful_items),
        "organized_count": len(successful_items),
        "failed_count": len(failed_items),
        "operations": operations,
        "failures": failed_items,
        "cleaned_folders": list(set(cleaned_folders))
    }


def clean_empty_subfolders(incoming_dir: str, delete_root_if_empty: bool = False) -> List[str]:
    """
    Recursively scans the incoming directory from the bottom up and removes
    empty subfolders (including folders left with only non-media clutter like
    .nfo, .txt, .url, Thumbs.db, .DS_Store, or small sample clips).

    Never deletes the incoming_dir root itself unless delete_root_if_empty is True.
    Returns the list of deleted folder paths.
    """
    if not incoming_dir or not os.path.isdir(incoming_dir):
        return []

    incoming_norm = os.path.abspath(incoming_dir)
    deleted_folders: List[str] = []

    for root, dirs, files in os.walk(incoming_norm, topdown=False):
        norm_root = os.path.abspath(root)
        if norm_root == incoming_norm and not delete_root_if_empty:
            continue

        base_name = os.path.basename(norm_root)
        if base_name.startswith(".") or base_name.startswith("$"):
            continue

        try:
            entries = os.listdir(norm_root)
        except OSError:
            continue

        # If subdirectories still exist and couldn't be deleted, we can't delete this folder
        if any(os.path.isdir(os.path.join(norm_root, e)) for e in entries):
            continue

        has_media = False
        has_incomplete = False
        non_clutter_files = False

        for f in entries:
            fp = os.path.join(norm_root, f)
            if not os.path.isfile(fp):
                continue
            if is_incomplete_file(fp) or is_file_locked(fp):
                has_incomplete = True
                break
            if is_media_file(fp) or is_subtitle_file(fp):
                has_media = True
                break
            _, ext = os.path.splitext(f)
            ext_l = ext.lower()
            if not is_clutter(fp) and ext_l not in (CLUTTER_EXTS | {".db", ".ini", ".jpg", ".png", ".jpeg"}):
                non_clutter_files = True
                break

        if has_incomplete or has_media or non_clutter_files:
            continue

        # Only clutter files remain — remove them
        for f in entries:
            fp = os.path.join(norm_root, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass

        # If directory is now completely empty, remove it
        try:
            if not os.listdir(norm_root):
                os.rmdir(norm_root)
                deleted_folders.append(norm_root)
                logger.info(f"Cleaned empty subfolder: {norm_root}")
        except OSError as e:
            logger.debug(f"Could not remove directory {norm_root}: {e}")

    return deleted_folders


def _cleanup_empty_and_clutter(directory: str):
    """Backward-compatible helper that prunes empty directories and clutter."""
    clean_empty_subfolders(directory, delete_root_if_empty=True)


# ─── Post-Processing Downstream Trigger ────────────────────────────────────────

def trigger_post_processing(executed_batch: Dict[str, Any]):
    """
    Trigger downstream CapsStream actions:
    1. Update data/requests.json if any matching request IDs are present.
    2. Request incremental library scan via localhost HTTP API if server is up.
    """
    req_ids = [op.get("request_id") for op in executed_batch.get("operations", []) if op.get("request_id")]
    if req_ids and os.path.exists(REQUESTS_FILE):
        try:
            with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
                reqs = json.load(f)
            changed = False
            for req in reqs:
                if req.get("id") in req_ids:
                    req["status"] = "completed"
                    req["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    req["admin_note"] = "Organized into library"
                    changed = True
            if changed:
                with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(reqs, f, indent=2, ensure_ascii=False)
                logger.info(f"Marked {len(req_ids)} requests as completed in {REQUESTS_FILE}")
        except Exception as e:
            logger.warning(f"Failed to auto-fulfill requests: {e}")

    # Ping CapsStream server to trigger library scan
    try:
        import urllib.request
        cfg_file = os.path.join(BASE_DIR, "config.json")
        port = 5000
        if os.path.exists(cfg_file):
            with open(cfg_file, "r") as f:
                port = json.load(f).get("port", 5000)

        url = f"http://127.0.0.1:{port}/api/admin/scan"
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=2):
            logger.info("Triggered CapsStream library scan successfully")
    except Exception:
        pass


# ─── Background Incoming Folder Watcher ──────────────────────────────────────

_WATCHER_THREAD = None
_WATCHER_STOP_EVENT = threading.Event()


def start_organizer_watcher():
    """Start the background incoming folder watcher daemon if not already running."""
    global _WATCHER_THREAD
    if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
        return
    _WATCHER_STOP_EVENT.clear()
    _WATCHER_THREAD = threading.Thread(
        target=_organizer_watcher_loop,
        daemon=True,
        name="organizer-watcher"
    )
    _WATCHER_THREAD.start()
    logger.info("Organizer background folder watcher started")


def stop_organizer_watcher():
    """Signal the background incoming folder watcher to stop."""
    _WATCHER_STOP_EVENT.set()


def _organizer_watcher_loop():
    from backend.settings import load_config

    while not _WATCHER_STOP_EVENT.is_set():
        try:
            cfg = load_config()
            org_cfg = cfg.get("organizer", {})
            if org_cfg.get("enabled", True) and org_cfg.get("auto_watch", False):
                incoming = org_cfg.get("incoming_dir") or os.path.join(BASE_DIR, "data", "incoming")
                if os.path.isdir(incoming):
                    lib_roots = get_organizer_library_roots(cfg)
                    local_reg = org_cfg.get("local_region", "")
                    col_policy = org_cfg.get("collision_policy", "skip")
                    mode = org_cfg.get("mode", "smart")
                    preview = scan_incoming_for_preview(
                        incoming,
                        lib_roots,
                        tmdb_api_key=cfg.get("tmdb_api_key"),
                        local_region=local_reg,
                        collision_policy=col_policy,
                    )
                    ready = [
                        item for item in preview
                        if item.get("is_settled") and not item.get("is_locked") and item.get("confidence") != "low"
                    ]
                    if ready:
                        logger.info(f"[Watcher] Auto-organizing {len(ready)} settled media item(s) from {incoming}")
                        res = execute_organization_plan(ready, mode=mode, collision_policy=col_policy)
                        trigger_post_processing(res)
        except Exception as e:
            logger.debug(f"[Watcher] Watcher loop check: {e}")

        interval = 30
        try:
            cfg = load_config()
            interval = max(15, cfg.get("organizer", {}).get("watch_interval_seconds", 30))
        except Exception:
            pass

        for _ in range(int(interval)):
            if _WATCHER_STOP_EVENT.is_set():
                break
            time.sleep(1)


# ─── CLI Entrypoint ────────────────────────────────────────────────────────────

def main():
    import argparse
    from backend.settings import load_config

    parser = argparse.ArgumentParser(description="CapsStream Automated Media Renamer & File Organizer")
    parser.add_argument("--path", "-p", help="Path to downloaded file or directory", default=None)
    parser.add_argument("--name", "-n", help="Optional torrent/media title hint", default=None)
    parser.add_argument("--mode", "-m", choices=["smart", "move", "copy"], default="smart", help="File operation mode")
    parser.add_argument("--dry-run", action="store_true", help="Preview proposed renames without moving/linking files")
    parser.add_argument("--undo", help="Rollback an organization batch ID")

    args = parser.parse_args()

    if args.undo:
        res = undo_batch(args.undo)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("success") else 1)

    if not args.path:
        parser.print_help()
        sys.exit(1)

    target_path = os.path.abspath(args.path)
    if not os.path.exists(target_path):
        logger.error(f"Target path does not exist: {target_path}")
        sys.exit(1)

    cfg = load_config()
    lib_roots = get_organizer_library_roots(cfg)
    org_cfg = cfg.get("organizer", {})
    local_reg = org_cfg.get("local_region", "")
    col_policy = org_cfg.get("collision_policy", "skip")

    if os.path.isfile(target_path):
        classified = classify_media_file(target_path, hint_title=args.name)
        resolved = resolve_canonical_item(classified, tmdb_api_key=cfg.get("tmdb_api_key"), local_region=local_reg)
        dest = build_destination_path(resolved, lib_roots)
        if os.path.exists(dest) and col_policy == "suffix":
            dest = disambiguate_video_path(dest)
        plan = [{
            "source_path": target_path,
            "destination_path": dest,
            "media_type": resolved["media_type"],
            "request_id": resolved.get("request_id"),
            "subtitles": find_companion_subtitles(target_path),
            "route_reason": resolved.get("route_reason", "region-off"),
            "origin_countries": resolved.get("origin_countries", []),
            "collision_policy": col_policy,
        }]
    else:
        plan = scan_incoming_for_preview(
            target_path,
            lib_roots,
            tmdb_api_key=cfg.get("tmdb_api_key"),
            local_region=local_reg,
            collision_policy=col_policy,
        )

    if args.dry_run:
        print(f"--- Dry Run Preview ({len(plan)} item(s)) ---")
        for p in plan:
            print(f"Source:       {p['source_path']}")
            print(f"Destination:  {p['destination_path']}")
            print(f"Type:         {p.get('media_type')}")
            print(f"Route Reason: {p.get('route_reason', 'n/a')}")
            if p.get("origin_countries"):
                print(f"Countries:    {', '.join(p['origin_countries'])}")
            if p.get("subtitle_plan"):
                print("Subtitles:")
                for s in p["subtitle_plan"]:
                    print(f"  - [{s.get('action')}] {os.path.basename(s['source'])} -> {os.path.basename(s['destination'])} ({s.get('lang')})")
            print("-" * 50)
        sys.exit(0)

    res = execute_organization_plan(plan, mode=args.mode, collision_policy=col_policy)
    print(json.dumps(res, indent=2))
    trigger_post_processing(res)


if __name__ == "__main__":
    main()
