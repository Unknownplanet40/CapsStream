# -*- coding: utf-8 -*-
"""
backend/theme_music.py — Theme audio preview resolution and fetching.

Resolution hierarchy:
  1. Local Plex-standard theme audio in media directory:
     - <media_dir>/theme.mp3, theme.ogg, theme.m4a, theme.wav, theme.flac
     - For TV/Anime shows: checks episode folder and show root directory.
  2. Cached server storage in data/metadata/theme_music/{key}.{ext}
  3. Online provider: AnimeThemes.moe for Anime (OP1/opening audio track)
     - Cached locally on first request for snappy future playback.
"""

import os
import re
import json
import logging
import requests
from backend.utils.paths import BASE_DIR
from backend.db import get_media_by_id, get_media_by_tmdb

logger = logging.getLogger(__name__)

THEME_MUSIC_DIR = os.path.join(BASE_DIR, "data", "metadata", "theme_music")
os.makedirs(THEME_MUSIC_DIR, exist_ok=True)

THEME_EXTENSIONS = [".mp3", ".ogg", ".m4a", ".wav", ".flac"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://animethemes.moe/"
}


def _clean_cache_key(name):
    """Generate a filesystem-safe cache key."""
    if not name:
        return "unknown"
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', str(name).strip().lower())


def find_local_theme_file(file_path, is_series=False):
    """
    Look for a local theme file in the media item's directory or show parent directory.
    Follows Plex Local Media Assets naming conventions:
      - /Show Name/theme.mp3
      - /Show Name/Season 01/theme.mp3 (fallback)
      - /Movie Name (Year)/theme.mp3
    """
    if not file_path or not os.path.exists(file_path):
        return None

    dirs_to_check = []
    item_dir = os.path.dirname(os.path.abspath(file_path))
    dirs_to_check.append(item_dir)

    if is_series:
        # Check show folder (parent of Season folder or item folder)
        parent_dir = os.path.dirname(item_dir)
        if parent_dir and parent_dir != item_dir and parent_dir not in dirs_to_check:
            dirs_to_check.append(parent_dir)

    # Candidate filenames to match:
    # 1. Plex standard: theme.ext, Theme.ext
    # 2. CapsStream companion standard: <media_stem>.theme_song.ext, <clean_title>.theme_song.ext
    # 3. Direct theme_song.ext
    media_stem = os.path.splitext(os.path.basename(file_path))[0].lower() if file_path else ""

    for directory in dirs_to_check:
        if not os.path.isdir(directory):
            continue

        try:
            files_in_dir = os.listdir(directory)
        except OSError:
            continue

        for fname in files_in_dir:
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue
            f_stem, f_ext = os.path.splitext(fname)
            if f_ext.lower() not in THEME_EXTENSIONS:
                continue
            f_stem_l = f_stem.lower()

            # Direct Plex convention: "theme" or "Theme"
            if f_stem_l in ("theme", "theme_song"):
                return fpath

            # Explicit companion convention: <media_name>.theme_song or <media_name> (year).theme_song
            if f_stem_l.endswith(".theme_song") or f_stem_l.endswith("-theme_song"):
                prefix = f_stem_l[:-11]  # remove .theme_song or -theme_song
                if not media_stem or prefix in media_stem or media_stem.startswith(prefix):
                    return fpath
                return fpath

            if "theme_song" in f_stem_l:
                return fpath

    return None


def find_cached_theme_file(cache_key):
    """Check if theme music was previously downloaded and cached."""
    if not cache_key:
        return None
    for ext in THEME_EXTENSIONS:
        candidate = os.path.join(THEME_MUSIC_DIR, f"{cache_key}{ext}")
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 1024:
            return candidate
    return None


def fetch_animethemes_audio(title, tmdb_id=None):
    """
    Query AnimeThemes.moe API to fetch opening theme audio stream.
    Caches the audio file locally for fast subsequent plays.
    """
    if not title:
        return None

    clean_key = f"anime_{tmdb_id or _clean_cache_key(title)}"
    cached = find_cached_theme_file(clean_key)
    if cached:
        return cached

    try:
        url = f"https://api.animethemes.moe/anime?search={requests.utils.quote(title)}&include=animethemes.animethemeentries.videos.audio&page[size]=3"
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None

        data = r.json()
        animes = data.get("anime") or []
        if not animes:
            return None

        # Pick best match (look for OP first, fallback to first theme)
        target_audio_url = None
        for anime in animes:
            themes = anime.get("animethemes") or []
            # First look for OP
            for th in themes:
                if (th.get("type") or "").upper() == "OP":
                    entries = th.get("animethemeentries") or []
                    for entry in entries:
                        videos = entry.get("videos") or []
                        for vid in videos:
                            audio = vid.get("audio")
                            if audio and audio.get("link"):
                                target_audio_url = audio["link"]
                                break
                        if target_audio_url:
                            break
                if target_audio_url:
                    break

            # Fallback to any theme entry
            if not target_audio_url and themes:
                for th in themes:
                    for entry in th.get("animethemeentries") or []:
                        for vid in entry.get("videos") or []:
                            audio = vid.get("audio")
                            if audio and audio.get("link"):
                                target_audio_url = audio["link"]
                                break
                        if target_audio_url:
                            break
                    if target_audio_url:
                        break

            if target_audio_url:
                break

        if not target_audio_url:
            return None

        # Download and cache audio stream
        audio_ext = ".ogg" if target_audio_url.endswith(".ogg") else ".mp3"
        dest_path = os.path.join(THEME_MUSIC_DIR, f"{clean_key}{audio_ext}")
        temp_dest = dest_path + ".tmp"

        with requests.get(target_audio_url, headers=HEADERS, stream=True, timeout=15) as res:
            if res.status_code == 200:
                with open(temp_dest, "wb") as f:
                    for chunk in res.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                if os.path.isfile(temp_dest) and os.path.getsize(temp_dest) > 1024:
                    os.replace(temp_dest, dest_path)
                    logger.info(f"[ThemeMusic] Cached AnimeThemes audio for '{title}' -> {dest_path}")
                    return dest_path

        if os.path.isfile(temp_dest):
            try:
                os.remove(temp_dest)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[ThemeMusic] Failed to fetch AnimeThemes for '{title}': {e}")

    return None


def fetch_plex_tv_theme(tmdb_id, title=None):
    """
    Fetch theme music from Plex's TV theme song archive (http://tvthemes.plexapp.com/{tvdb_id}.mp3).
    Resolves tvdb_id via TMDb external_ids endpoint and caches the mp3 file locally.
    """
    if not tmdb_id:
        return None

    clean_key = f"series_{tmdb_id}"
    cached = find_cached_theme_file(clean_key)
    if cached:
        return cached

    tvdb_id = None
    try:
        from backend.matcher import _tmdb_get
        ext_ids = _tmdb_get(f"tv/{tmdb_id}/external_ids")
        if ext_ids and ext_ids.get("tvdb_id"):
            tvdb_id = ext_ids["tvdb_id"]
    except Exception as e:
        logger.debug(f"[ThemeMusic] Failed to resolve TVDB ID for TMDB {tmdb_id}: {e}")

    if not tvdb_id:
        return None

    plex_url = f"http://tvthemes.plexapp.com/{tvdb_id}.mp3"
    dest_path = os.path.join(THEME_MUSIC_DIR, f"{clean_key}.mp3")
    temp_dest = dest_path + ".tmp"

    try:
        with requests.get(plex_url, headers={"User-Agent": "PlexMediaPlayer/1.0"}, stream=True, timeout=10) as res:
            if res.status_code == 200:
                with open(temp_dest, "wb") as f:
                    for chunk in res.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                if os.path.isfile(temp_dest) and os.path.getsize(temp_dest) > 1024:
                    os.replace(temp_dest, dest_path)
                    logger.info(f"[ThemeMusic] Cached Plex TV theme for TMDB {tmdb_id} (TVDB {tvdb_id}) -> {dest_path}")
                    return dest_path

        if os.path.isfile(temp_dest):
            try:
                os.remove(temp_dest)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[ThemeMusic] Failed to download Plex TV theme for TVDB {tvdb_id}: {e}")

    return None


def resolve_theme_music(media_dict):
    """
    Main resolution function for a media dictionary (movie, anime, or series).
    Returns dict:
      {
         "has_theme": bool,
         "file_path": str | None,
         "source": "local" | "cached" | "animethemes" | None,
         "title": str
      }
    """
    if not media_dict:
        return {"has_theme": False, "file_path": None, "source": None}

    title = media_dict.get("title") or media_dict.get("name") or ""
    media_type = media_dict.get("type") or "movie"
    file_path = media_dict.get("file_path") or ""
    is_series = media_type in ("series", "anime", "show")
    tmdb_id = media_dict.get("tmdb_id")

    # 1. Local media asset (Plex standard)
    if file_path:
        local_theme = find_local_theme_file(file_path, is_series=is_series)
        if local_theme:
            return {
                "has_theme": True,
                "file_path": local_theme,
                "source": "local",
                "title": title
            }

    # 2. Check local disk cache (by tmdb_id or title)
    cache_key = f"{media_type}_{tmdb_id or _clean_cache_key(title)}"
    cached = find_cached_theme_file(cache_key)
    if cached:
        return {
            "has_theme": True,
            "file_path": cached,
            "source": "cached",
            "title": title
        }

    # 3. Online fetch: Anime via AnimeThemes.moe
    if media_type == "anime" or "anime" in str(media_dict.get("genres", "")).lower():
        anime_theme = fetch_animethemes_audio(title, tmdb_id=tmdb_id)
        if anime_theme:
            return {
                "has_theme": True,
                "file_path": anime_theme,
                "source": "animethemes",
                "title": title
            }

    # 4. Online fetch: TV Series via Plex TV Themes archive
    if is_series and tmdb_id:
        plex_theme = fetch_plex_tv_theme(tmdb_id, title=title)
        if plex_theme:
            return {
                "has_theme": True,
                "file_path": plex_theme,
                "source": "plextvthemes",
                "title": title
            }

    return {"has_theme": False, "file_path": None, "source": None}
