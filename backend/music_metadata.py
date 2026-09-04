# -*- coding: utf-8 -*-
"""Free metadata, cover art, and synced lyrics client for CapsStream.

Integrates:
- LRCLIB (lrclib.net): 100% free line-by-line synchronized lyrics API.
- MusicBrainz (musicbrainz.org): 100% free open music database for artist/album MBIDs.
- Cover Art Archive (coverartarchive.org): 100% free high-resolution front covers.
- TheAudioDB (theaudiodb.com): Free artist biographies and fanart portraits.
"""

import os
import json
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

from backend.utils.paths import BASE_DIR

USER_AGENT = "CapsStream/2.21 ( https://github.com/ryanj/CapsStream )"
COVERS_DIR = os.path.join(BASE_DIR, "data", "music_covers")
LYRICS_DIR = os.path.join(BASE_DIR, "data", "music_lyrics")


def _http_get_json(url, headers=None, timeout=12):
    """Safe HTTP GET returning parsed JSON or None."""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _http_download_image(url, out_path, timeout=10):
    """Download image from url and save to out_path. Returns True on success."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            if content and len(content) > 1024:  # At least 1KB
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(content)
                return True
    except Exception:
        pass
    return False


# ─── LRCLIB: Synced Lyrics ────────────────────────────────────────────────────

def fetch_synced_lyrics(title, artist, album=None, duration=None):
    """Query lrclib.net for synchronized or plain lyrics.
    
    Returns dict:
      {
        "synced": bool,
        "lyrics": str or None,
        "source": "lrclib"
      }
    """
    if not title or not artist:
        return {"synced": False, "lyrics": None, "source": None}

    clean_title = title.split("(")[0].split("[")[0].strip()
    clean_artist = artist.split(",")[0].split("&")[0].split("feat.")[0].strip()

    # 1. Direct GET endpoint
    params = {
        "track_name": clean_title,
        "artist_name": clean_artist,
    }
    if album and album.lower() not in {"unknown album", "singles", "single"}:
        params["album_name"] = album
    if duration and duration > 0:
        params["duration"] = int(duration)

    query_str = urllib.parse.urlencode(params)
    url = f"https://lrclib.net/api/get?{query_str}"
    res = _http_get_json(url, timeout=5)

    if res and isinstance(res, dict):
        synced = res.get("syncedLyrics")
        plain = res.get("plainLyrics")
        if synced:
            return {"synced": True, "lyrics": synced, "source": "lrclib"}
        if plain:
            return {"synced": False, "lyrics": plain, "source": "lrclib"}

    # 2. Search fallback endpoint
    search_params = {
        "track_name": clean_title,
        "artist_name": clean_artist,
    }
    search_url = f"https://lrclib.net/api/search?{urllib.parse.urlencode(search_params)}"
    search_res = _http_get_json(search_url, timeout=5)
    if search_res and isinstance(search_res, list) and len(search_res) > 0:
        top = search_res[0]
        synced = top.get("syncedLyrics")
        plain = top.get("plainLyrics")
        if synced:
            return {"synced": True, "lyrics": synced, "source": "lrclib"}
        if plain:
            return {"synced": False, "lyrics": plain, "source": "lrclib"}

    return {"synced": False, "lyrics": None, "source": None}


def save_lyrics_file(track_id, lyrics_text):
    """Save lyrics text to data/music_lyrics/<track_id>.lrc and return absolute path."""
    if not lyrics_text:
        return None
    try:
        os.makedirs(LYRICS_DIR, exist_ok=True)
        file_path = os.path.join(LYRICS_DIR, f"{track_id}.lrc")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(lyrics_text)
        return file_path
    except Exception as e:
        print(f"[MusicMetadata] Failed to save lyrics for track {track_id}: {e}")
        return None


# ─── MusicBrainz & Cover Art Archive ──────────────────────────────────────────

def search_musicbrainz_album(album_title, artist_name):
    """Search MusicBrainz for a release/album.
    
    Returns dict with mbid, title, year, or None.
    """
    if not album_title or album_title.lower() in {"unknown album", "singles"}:
        return None

    query = f'release:"{album_title}"'
    if artist_name and artist_name.lower() != "unknown artist":
        clean_artist = artist_name.split(",")[0].split("&")[0].strip()
        query += f' AND artist:"{clean_artist}"'

    url = f"https://musicbrainz.org/ws/2/release/?query={urllib.parse.quote(query)}&fmt=json&limit=3"
    data = _http_get_json(url, timeout=6)
    if not data or "releases" not in data or not data["releases"]:
        return None

    top = data["releases"][0]
    mbid = top.get("id")
    date_str = top.get("date", "")
    year = None
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        year = int(date_str[:4])

    return {
        "mbid": mbid,
        "title": top.get("title"),
        "year": year,
        "country": top.get("country"),
    }


def fetch_cover_art_archive(release_mbid):
    """Download front cover from Cover Art Archive for release_mbid.
    
    Returns relative cover path e.g. 'music_covers/<hash>.jpg' or None.
    """
    if not release_mbid:
        return None

    url = f"https://coverartarchive.org/release/{release_mbid}/front-500"
    h = hashlib.md5(release_mbid.encode("utf-8")).hexdigest()[:16]
    out_filename = f"caa_{h}.jpg"
    out_path = os.path.join(COVERS_DIR, out_filename)

    if os.path.isfile(out_path):
        return f"music_covers/{out_filename}"

    if _http_download_image(url, out_path, timeout=10):
        return f"music_covers/{out_filename}"

    url_orig = f"https://coverartarchive.org/release/{release_mbid}/front"
    if _http_download_image(url_orig, out_path, timeout=10):
        return f"music_covers/{out_filename}"

    return None


# ─── TheAudioDB: Rich Artist & Album Metadata ─────────────────────────────────

def fetch_artist_info(artist_name):
    """Query TheAudioDB (free API key: 2) for artist bio, photo, banner, and logo.
    
    Returns dict:
      {
        "biography": str or None,
        "photo_path": str or None,
        "banner_path": str or None,
        "logo_path": str or None,
        "fanart_path": str or None,
        "genre": str or None,
        "country": str or None,
        "mbid": str or None,
      }
    """
    if not artist_name or artist_name.lower() == "unknown artist":
        return {"biography": None, "photo_path": None}

    clean_artist = artist_name.split(",")[0].split("&")[0].strip()
    encoded = urllib.parse.quote(clean_artist)
    url = f"https://theaudiodb.com/api/v1/json/2/search.php?s={encoded}"
    data = _http_get_json(url, timeout=10)

    if not data or "artists" not in data or not data["artists"]:
        return {"biography": None, "photo_path": None}

    art = data["artists"][0]
    bio = art.get("strBiography") or art.get("strBiographyEN") or None
    h = hashlib.md5(clean_artist.lower().encode("utf-8")).hexdigest()[:16]

    photo_rel = None
    thumb_url = art.get("strArtistThumb") or art.get("strArtistCutout")
    if thumb_url:
        out_filename = f"artist_thumb_{h}.jpg"
        out_path = os.path.join(COVERS_DIR, out_filename)
        if os.path.isfile(out_path):
            photo_rel = f"music_covers/{out_filename}"
        elif _http_download_image(thumb_url, out_path, timeout=10):
            photo_rel = f"music_covers/{out_filename}"

    fanart_rel = None
    fanart_url = art.get("strArtistFanart") or art.get("strArtistWideThumb")
    if fanart_url:
        out_fanart = f"artist_fanart_{h}.jpg"
        out_path = os.path.join(COVERS_DIR, out_fanart)
        if os.path.isfile(out_path):
            fanart_rel = f"music_covers/{out_fanart}"
        elif _http_download_image(fanart_url, out_path, timeout=10):
            fanart_rel = f"music_covers/{out_fanart}"

    return {
        "biography": bio,
        "photo_path": photo_rel,
        "fanart_path": fanart_rel,
        "genre": art.get("strGenre"),
        "country": art.get("strCountry"),
        "mbid": art.get("strMusicBrainzID"),
    }


def fetch_theaudiodb_album(album_title, artist_name):
    """Query TheAudioDB for album cover art, year, description, and disc art.
    
    Returns dict:
      {
        "cover_path": str or None,
        "cdart_path": str or None,
        "description": str or None,
        "year": int or None,
        "genre": str or None,
      }
    """
    if not album_title or album_title.lower() in {"unknown album", "singles"}:
        return None

    clean_artist = (artist_name or "").split(",")[0].split("&")[0].strip()
    clean_album = album_title.split("(")[0].split("[")[0].strip()

    s = urllib.parse.quote(clean_artist)
    a = urllib.parse.quote(clean_album)
    url = f"https://theaudiodb.com/api/v1/json/2/searchalbum.php?s={s}&a={a}"
    data = _http_get_json(url, timeout=10)

    if not data or "album" not in data or not data["album"]:
        return None

    alb = data["album"][0]
    h = hashlib.md5(f"{clean_artist}_{clean_album}".lower().encode("utf-8")).hexdigest()[:16]

    cover_rel = None
    thumb_url = alb.get("strAlbumThumb")
    if thumb_url:
        out_filename = f"tadb_cover_{h}.jpg"
        out_path = os.path.join(COVERS_DIR, out_filename)
        if os.path.isfile(out_path):
            cover_rel = f"music_covers/{out_filename}"
        elif _http_download_image(thumb_url, out_path, timeout=10):
            cover_rel = f"music_covers/{out_filename}"

    year_str = alb.get("intYearReleased")
    year = int(year_str) if year_str and str(year_str).isdigit() else None

    return {
        "cover_path": cover_rel,
        "description": alb.get("strDescription") or alb.get("strDescriptionEN"),
        "year": year,
        "genre": alb.get("strGenre"),
    }
