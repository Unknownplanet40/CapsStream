"""
matcher.py — TMDb API matching and metadata caching for CapsStream.

Strategy:
  1. Clean the folder/file name → extract title + optional year
  2. Search TMDb with the cleaned title
  3. Accept top result if similarity ≥ 0.80
  4. Cache full metadata as JSON in data/metadata/
  5. Download and cache poster + backdrop images
"""

import os
import re
import json
import time
import difflib
import hashlib
import requests

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
METADATA_DIR = os.path.join(BASE_DIR, "data", "metadata")
IMAGES_DIR = os.path.join(METADATA_DIR, "images")
os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG  = "https://image.tmdb.org/t/p"

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cfg():
    # Delegates to settings.load_config so secrets from .env / environment
    # are included (config.json itself no longer stores API keys).
    from backend.settings import load_config
    return load_config()


def _api_key():
    return _cfg().get("tmdb_api_key", "")


def _clean_name(name):
    """
    Strip resolution, codec, release group tags from a folder/filename.
    Extracts IMDb ID if present (tt12345678).
    Returns (cleaned_title, year, imdb_id).
    """
    # Extract IMDb ID if present
    imdb_match = re.search(r'(tt\d{7,8})', name, re.IGNORECASE)
    imdb_id = imdb_match.group(1).lower() if imdb_match else None

    # Remove file extension
    clean = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', name)

    # Extract year (must capture all 4 digits)
    year_match = re.search(r'[\(\[\.\s_\-]((?:19|20)\d{2})[\)\]\.\s_\-]?', clean)
    year = int(year_match.group(1)) if year_match else None

    # Strip IMDb ID from clean title string
    clean = re.sub(r'tt\d{7,8}', '', clean, flags=re.IGNORECASE)

    # Strip scene / release tags
    tags = [
        r'720p', r'1080p', r'2160p', r'4k', r'uhd', r'hdr', r'bluray', r'brrip', r'webrip', r'web-dl', r'web',
        r'dvdrip', r'x264', r'x265', r'hevc', r'10bit', r'8bit', r'aac5\.1', r'aac', r'ac3', r'dts', r'5\.1', r'7\.1',
        r'yts\.[a-z0-9\.\-]+', r'yts', r'yify', r'wd', r'hdtv', r'proper', r'repack', r'remux', r'extended',
        r'unrated', r'directors\.cut', r'atmos', r'truehd', r'xvid', r'amzn', r'nf', r'hulu', r'dsnp', r'hmax', r'atvp',
        r'complete(?:\.series)?', r'full'
    ]
    # Strip bracketed metadata like [Multi-audio] or [TGx]
    clean = re.sub(r'\[.*?\]', '', clean)

    # Strip S01, S02, S1, S2, Season 1, Season.01, Complete series indicators from folder names
    clean = re.sub(r'[\.\[\(\s_\-](?:[Ss]eason[\. _\-]?(?:\d{1,2}|[Cc]omplete)|[Ss]\d{1,2}|[Cc]omplete(?:\.?[Ss]eries)?).*$', '', clean, flags=re.IGNORECASE)

    # Strip year and everything after
    clean = re.sub(r'[\.\[\(\s_\-](19|20)\d{2}.*$', '', clean, flags=re.IGNORECASE)
    # Strip quality tags and everything after
    clean = re.sub(r'[\.\[\(\s_\-](' + '|'.join(tags) + r').*$', '', clean, flags=re.IGNORECASE)

    # Replace dots, underscores, dashes with spaces
    clean = re.sub(r'[\._\-]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean, year, imdb_id


def _similarity(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _cache_path(media_type, tmdb_id):
    return os.path.join(METADATA_DIR, f"{media_type}_{tmdb_id}.json")


def _load_cache(media_type, tmdb_id):
    path = _cache_path(media_type, tmdb_id)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_cache(media_type, tmdb_id, data):
    path = _cache_path(media_type, tmdb_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _download_image(tmdb_path, size="w500"):
    """Download a TMDb image and save locally. Returns local relative path."""
    if not tmdb_path:
        return None
    fname = f"{size}{tmdb_path.replace('/', '_')}"
    local_path = os.path.join(IMAGES_DIR, fname)
    if os.path.exists(local_path):
        return f"images/{fname}"
    try:
        url = f"{TMDB_IMG}/{size}{tmdb_path}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(r.content)
            return f"images/{fname}"
    except Exception as e:
        print(f"[Matcher] Image download failed: {e}")
    return None


def _tmdb_get(endpoint, params=None):
    """Make a TMDb API request with error handling and rate-limit awareness."""
    api_key = _api_key()
    if not api_key:
        return None
    url = f"{TMDB_BASE}/{endpoint}"
    p = {"api_key": api_key, **(params or {})}
    try:
        r = requests.get(url, params=p, timeout=10)
        if r.status_code == 429:
            print("[Matcher] TMDb rate limit hit, sleeping 2s...")
            time.sleep(2)
            r = requests.get(url, params=p, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[Matcher] TMDb request failed: {e}")
    return None


def _extract_logo(detail, media_type, tmdb_id):
    images = (detail or {}).get("images", {})
    logos = images.get("logos", [])
    if not logos and tmdb_id:
        endpoint = f"movie/{tmdb_id}/images" if media_type == "movie" else f"tv/{tmdb_id}/images"
        img_res = _tmdb_get(endpoint)
        if img_res:
            logos = img_res.get("logos", [])
    if logos:
        # Prefer English or language-less logo
        en_logo = next((l["file_path"] for l in logos if l.get("iso_639_1") in ("en", "en-US", None, "")), None)
        logo_tmdb = en_logo or logos[0].get("file_path")
        return _download_image(logo_tmdb, "w500")
    return None


def ensure_media_logo(media_dict):
    """Ensure a media item dictionary has a downloaded logo_path. Returns updated logo_path."""
    if not media_dict:
        return None
    if media_dict.get("logo_path"):
        return media_dict["logo_path"]

    tmdb_id = media_dict.get("tmdb_id")
    if not tmdb_id:
        return None

    m_type = media_dict.get("type", "movie")
    endpoint = f"movie/{tmdb_id}" if m_type == "movie" else f"tv/{tmdb_id}"
    detail = _tmdb_get(endpoint, {"append_to_response": "images"})
    logo = _extract_logo(detail, m_type, tmdb_id)
    if logo:
        media_dict["logo_path"] = logo
        try:
            from backend.db import get_conn
            conn = get_conn()
            conn.execute("UPDATE media SET logo_path=? WHERE tmdb_id=? AND type=?", (logo, tmdb_id, m_type))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Matcher] Failed to update logo in db: {e}")
    return logo


def _fetch_movie_detail(tmdb_id, default_title="", year=None):
    cached = _load_cache("movie", tmdb_id)
    if cached:
        # Ensure cached items get logo if missing
        if "logo_path" not in cached:
            detail = _tmdb_get(f"movie/{tmdb_id}", {"language": "en-US", "append_to_response": "images", "include_image_language": "en,null"})
            if detail:
                cached["logo_path"] = _extract_logo(detail, "movie", tmdb_id)
                _save_cache("movie", tmdb_id, cached)
        return cached

    detail = _tmdb_get(f"movie/{tmdb_id}", {"language": "en-US", "append_to_response": "credits,videos,images", "include_image_language": "en,null"})
    if not detail:
        return None

    poster_local   = _download_image(detail.get("poster_path"), "w500")
    backdrop_local = _download_image(detail.get("backdrop_path"), "original")
    logo_local     = _extract_logo(detail, "movie", tmdb_id)

    genres = ", ".join(g["name"] for g in detail.get("genres", []))
    cast   = [
        {"name": c["name"], "character": c["character"], "profile": c.get("profile_path")}
        for c in detail.get("credits", {}).get("cast", [])[:10]
    ]
    trailer = next(
        (v["key"] for v in detail.get("videos", {}).get("results", [])
         if v["site"] == "YouTube" and v["type"] == "Trailer"),
        None
    )

    release = detail.get("release_date", "")
    release_year = int(release[:4]) if release and len(release) >= 4 else year

    result = {
        "tmdb_id":       tmdb_id,
        "type":          "movie",
        "title":         detail.get("title", default_title),
        "original_title": detail.get("original_title"),
        "year":          release_year,
        "overview":      detail.get("overview"),
        "tagline":       detail.get("tagline"),
        "genres":        genres,
        "rating":        detail.get("vote_average", 0),
        "vote_count":    detail.get("vote_count", 0),
        "poster_path":   poster_local,
        "backdrop_path": backdrop_local,
        "logo_path":     logo_local,
        "trailer_key":   trailer,
        "cast_json":     json.dumps(cast),
        "runtime":       detail.get("runtime"),
    }
    _save_cache("movie", tmdb_id, result)
    print(f"[Matcher] Matched movie: {result['title']} ({result['year']})")
    return result


def get_show_seasons_list(tmdb_id, media_type="series"):
    if not tmdb_id:
        return []
    cached = _load_cache(media_type, tmdb_id)
    if cached and "seasons_list" in cached and isinstance(cached["seasons_list"], list):
        return cached["seasons_list"]

    detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US"})
    if not detail:
        return []
    seasons = detail.get("seasons", [])
    s_list = [s["season_number"] for s in seasons if s.get("season_number") is not None and s.get("episode_count", 0) > 0]
    if cached:
        cached["seasons_list"] = s_list
        _save_cache(media_type, tmdb_id, cached)
    return s_list


def get_media_trailer(tmdb_id, media_type="movie"):
    if not tmdb_id:
        return None
    endpoint = f"tv/{tmdb_id}/videos" if media_type in ("series", "anime", "tv") else f"movie/{tmdb_id}/videos"
    res = _tmdb_get(endpoint, {"language": "en-US"})
    if not res or "results" not in res:
        return None

    results = res.get("results", [])
    trailers = [v for v in results if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not trailers:
        trailers = [v for v in results if v.get("site") == "YouTube"]

    if trailers:
        key = trailers[0].get("key")
        name = trailers[0].get("name", "Trailer")
        return {
            "key": key,
            "title": name,
            "embed_url": f"https://www.youtube-nocookie.com/embed/{key}?autoplay=1&rel=0"
        }
    return None


def get_show_status(tmdb_id, media_type="series"):
    if not tmdb_id:
        return None
    cached = _load_cache(media_type, tmdb_id)
    if cached and cached.get("status"):
        return cached["status"]

    detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US"})
    if not detail:
        return None
    status = detail.get("status")
    if cached:
        cached["status"] = status
        _save_cache(media_type, tmdb_id, cached)
    return status


def _fetch_show_detail(tmdb_id, default_title="", year=None, media_type="series"):
    cached = _load_cache(media_type, tmdb_id)
    if cached:
        updated = False
        if "logo_path" not in cached:
            detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US", "append_to_response": "images", "include_image_language": "en,null"})
            if detail:
                cached["logo_path"] = _extract_logo(detail, media_type, tmdb_id)
                if not cached.get("status") and detail.get("status"):
                    cached["status"] = detail.get("status")
                updated = True
        if "status" not in cached:
            st = get_show_status(tmdb_id, media_type)
            if st:
                cached["status"] = st
                updated = True
        if updated:
            _save_cache(media_type, tmdb_id, cached)
        return cached

    detail = _tmdb_get(f"tv/{tmdb_id}", {"language": "en-US", "append_to_response": "credits,videos,images", "include_image_language": "en,null"})
    if not detail:
        return None

    poster_local   = _download_image(detail.get("poster_path"), "w500")
    backdrop_local = _download_image(detail.get("backdrop_path"), "original")
    logo_local     = _extract_logo(detail, media_type, tmdb_id)

    genres = ", ".join(g["name"] for g in detail.get("genres", []))
    cast = [
        {"name": c["name"], "character": c["character"], "profile": c.get("profile_path")}
        for c in detail.get("credits", {}).get("cast", [])[:10]
    ]
    trailer = next(
        (v["key"] for v in detail.get("videos", {}).get("results", [])
         if v["site"] == "YouTube" and v["type"] == "Trailer"),
        None
    )

    first_air = detail.get("first_air_date", "")
    show_year = int(first_air[:4]) if first_air and len(first_air) >= 4 else year

    # Strict anime detection: Animation genre AND Japanese origin.
    # Western animation (Arcane, Family Guy, ...) stays "series".
    origin_country = detail.get("origin_country") or []
    is_anime = (
        "Animation" in genres
        and (detail.get("original_language") == "ja" or "JP" in origin_country)
    )

    result = {
        "tmdb_id":       tmdb_id,
        "type":          "anime" if (media_type == "series" and is_anime) else media_type,
        "is_anime":      is_anime,
        "title":         detail.get("name", default_title),
        "original_title": detail.get("original_name"),
        "year":          show_year,
        "status":        detail.get("status"),
        "overview":      detail.get("overview"),
        "tagline":        detail.get("tagline"),
        "genres":        genres,
        "rating":        detail.get("vote_average", 0),
        "vote_count":    detail.get("vote_count", 0),
        "poster_path":   poster_local,
        "backdrop_path": backdrop_local,
        "logo_path":     logo_local,
        "trailer_key":   trailer,
        "cast_json":     json.dumps(cast),
        "seasons":       detail.get("number_of_seasons", 1),
    }
    _save_cache(media_type, tmdb_id, result)
    print(f"[Matcher] Matched show: {result['title']} ({result['year']})"
          + (" [anime]" if is_anime else ""))
    return result


# ─── Main Matching Functions ──────────────────────────────────────────────────

def match_movie(folder_name):
    """
    Given a movie folder name or filename, return a dict of metadata (or None if no match).
    """
    title, year, imdb_id = _clean_name(folder_name)
    print(f"[Matcher] Searching movie: '{title}' (year={year}, imdb_id={imdb_id})")

    # Strategy 1: Exact IMDb ID lookup if present
    if imdb_id:
        data = _tmdb_get(f"find/{imdb_id}", {"external_source": "imdb_id"})
        if data and data.get("movie_results"):
            best = data["movie_results"][0]
            return _fetch_movie_detail(best["id"], title, year)

    # Strategy 2: Text search with year
    params = {"query": title, "language": "en-US"}
    if year:
        params["year"] = year

    data = _tmdb_get("search/movie", params)
    if not data or not data.get("results"):
        # Retry without year
        if year:
            data = _tmdb_get("search/movie", {"query": title, "language": "en-US"})

    # Strategy 3: Retry with primary title prefix (first 4 words) if long title fails
    if (not data or not data.get("results")) and len(title.split()) > 3:
        short_title = " ".join(title.split()[:4])
        print(f"[Matcher] Retrying search with short title: '{short_title}'")
        data = _tmdb_get("search/movie", {"query": short_title, "language": "en-US"})

    if not data or not data.get("results"):
        print(f"[Matcher] No results for movie: {title}")
        return None

    results = data["results"]
    best = None
    best_score = 0

    for r in results[:5]:
        r_title = r.get("title", "")
        r_orig = r.get("original_title", "")
        score = max(_similarity(title, r_title), _similarity(title, r_orig))
        # Also check against short title
        if len(title.split()) > 3:
            short = " ".join(title.split()[:4])
            score = max(score, _similarity(short, r_title), _similarity(short, r_orig))
        if score > best_score:
            best_score = score
            best = r

    # Fallback acceptance for foreign/pinyin titles: if 1 result returned or year matches ±1 year, accept top result
    if best:
        rel_str = best.get("release_date", "")
        rel_year = int(rel_str[:4]) if rel_str and len(rel_str) >= 4 else None
        if len(results) == 1 or (year and rel_year and abs(rel_year - year) <= 1):
            return _fetch_movie_detail(best["id"], title, year)

    if best_score < 0.60:
        print(f"[Matcher] Low confidence ({best_score:.2f}) for '{title}', skipping")
        return None

    return _fetch_movie_detail(best["id"], title, year)


def match_show(folder_name, media_type="series"):
    """
    Given a series/anime folder name or filename, return show-level metadata.
    """
    title, year, imdb_id = _clean_name(folder_name)
    print(f"[Matcher] Searching {media_type}: '{title}' (year={year}, imdb_id={imdb_id})")

    # Strategy 1: Exact IMDb ID lookup if present
    if imdb_id:
        data = _tmdb_get(f"find/{imdb_id}", {"external_source": "imdb_id"})
        if data and data.get("tv_results"):
            best = data["tv_results"][0]
            return _fetch_show_detail(best["id"], title, year, media_type)

    # Strategy 2: Text search with year
    params = {"query": title, "language": "en-US"}
    if year:
        params["first_air_date_year"] = year

    data = _tmdb_get("search/tv", params)
    if not data or not data.get("results"):
        if year:
            data = _tmdb_get("search/tv", {"query": title, "language": "en-US"})

    if not data or not data.get("results"):
        print(f"[Matcher] No results for show: {title}")
        return None

    results = data["results"]
    best = None
    best_score = 0

    for r in results[:5]:
        r_title = r.get("name", "")
        r_orig  = r.get("original_name", "")
        score = max(_similarity(title, r_title), _similarity(title, r_orig))
        if score > best_score:
            best_score = score
            best = r

    if best:
        air_str = best.get("first_air_date", "")
        air_year = int(air_str[:4]) if air_str and len(air_str) >= 4 else None
        if len(results) == 1 or (year and air_year and abs(air_year - year) <= 1) or best_score >= 0.80:
            return _fetch_show_detail(best["id"], title, year, media_type)

    if best_score < 0.60:
        print(f"[Matcher] Low confidence ({best_score:.2f}) for '{title}'")
        return None

    return _fetch_show_detail(best["id"], title, year, media_type)


def search_tmdb(query, media_type="movie"):
    """
    Search TMDb directly for manual match override.
    Supports IMDb IDs (tt...), TMDb IDs (digits), or title text.
    """
    query = (query or "").strip()
    if not query:
        return []

    # Check if query is IMDb ID
    if re.match(r'^tt\d{7,8}$', query, re.I):
        data = _tmdb_get(f"find/{query}", {"external_source": "imdb_id"})
        if not data:
            return []
        items = data.get("movie_results", []) if media_type == "movie" else data.get("tv_results", [])
        return [{
            "tmdb_id": item["id"],
            "title": item.get("title") or item.get("name"),
            "year": int(item.get("release_date" if media_type == "movie" else "first_air_date", "")[:4]) if (item.get("release_date") or item.get("first_air_date")) else None,
            "poster_path": item.get("poster_path"),
            "overview": item.get("overview")
        } for item in items]

    # Check if query is numeric TMDb ID
    if query.isdigit():
        detail = _tmdb_get(f"{'movie' if media_type == 'movie' else 'tv'}/{query}", {"language": "en-US"})
        if detail and "id" in detail:
            return [{
                "tmdb_id": detail["id"],
                "title": detail.get("title") or detail.get("name"),
                "year": int(detail.get("release_date" if media_type == "movie" else "first_air_date", "")[:4]) if (detail.get("release_date") or detail.get("first_air_date")) else None,
                "poster_path": detail.get("poster_path"),
                "overview": detail.get("overview")
            }]

    # General text search
    endpoint = "search/movie" if media_type == "movie" else "search/tv"
    data = _tmdb_get(endpoint, {"query": query, "language": "en-US"})
    if not data or not data.get("results"):
        return []

    out = []
    for item in data.get("results", [])[:8]:
        rel = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
        yr = int(rel[:4]) if rel and len(rel) >= 4 else None
        out.append({
            "tmdb_id": item["id"],
            "title": item.get("title") or item.get("name"),
            "year": yr,
            "poster_path": item.get("poster_path"),
            "overview": item.get("overview")
        })
    return out


def fetch_season_episodes(tmdb_id, season_num):
    """Fetch episode metadata for a given season."""
    cache_key = f"season_{tmdb_id}_{season_num}"
    cached = _load_cache("season", cache_key)
    if cached:
        return cached

    data = _tmdb_get(f"tv/{tmdb_id}/season/{season_num}", {"language": "en-US"})
    if not data:
        return []

    episodes = []
    for ep in data.get("episodes", []):
        still_local = _download_image(ep.get("still_path"), "w300") if ep.get("still_path") else None
        episodes.append({
            "episode_number": ep.get("episode_number"),
            "name":           ep.get("name"),
            "overview":       ep.get("overview"),
            "still_path":     still_local or ep.get("still_path"),
            "air_date":       ep.get("air_date"),
            "runtime":        ep.get("runtime"),
        })

    _save_cache("season", cache_key, episodes)
    return episodes


def override_match(media_id, tmdb_id, media_type):
    """
    Manually override a TMDb match for a specific media file.
    Returns the new metadata dict or None.
    """
    if media_type == "movie":
        return match_movie_by_id(tmdb_id)
    else:
        return match_show_by_id(tmdb_id, media_type)


def match_movie_by_id(tmdb_id):
    return _fetch_movie_detail(tmdb_id)


def match_show_by_id(tmdb_id, media_type="series"):
    return _fetch_show_detail(tmdb_id, media_type=media_type)


def fetch_imdb_id(tmdb_id, media_type="movie"):
    """
    Fetches external_ids from TMDb API for a given tmdb_id and returns the IMDb ID (e.g. 'tt0111161').
    """
    key = _api_key()
    if not key or not tmdb_id:
        return None

    cache_file = os.path.join(METADATA_DIR, f"external_ids_{media_type}_{tmdb_id}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("imdb_id")
        except Exception:
            pass

    endpoint = "movie" if media_type == "movie" else "tv"
    url = f"{TMDB_BASE}/{endpoint}/{tmdb_id}/external_ids"
    try:
        r = requests.get(url, params={"api_key": key}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            imdb_id = data.get("imdb_id")
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return imdb_id
    except Exception as e:
        print(f"[Matcher] Error fetching IMDb ID for {tmdb_id}: {e}")
    return None


# In-memory cache for backdrop lists: disk cache already avoids network hits
# across restarts, but this avoids even the JSON file read on repeat detail views.
_BACKDROPS_CACHE: dict = {}  # (tmdb_id, media_type) → (list, fetched_at)
_BACKDROPS_CACHE_TTL = 3600  # 1 hour


def fetch_media_backdrops(tmdb_id, media_type="movie"):
    """
    Fetches alternative backdrop images from TMDb API for a movie/show.
    Returns list of backdrop image paths.
    Results are cached in-memory (1 h TTL) after the first disk or network fetch.
    """
    import time as _time
    key = (tmdb_id, media_type)
    entry = _BACKDROPS_CACHE.get(key)
    if entry is not None:
        paths, fetched_at = entry
        if _time.time() - fetched_at < _BACKDROPS_CACHE_TTL:
            return paths

    api_key = _api_key()
    if not api_key or not tmdb_id:
        return []

    cache_file = os.path.join(METADATA_DIR, f"backdrops_{media_type}_{tmdb_id}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                paths = json.load(f)
            _BACKDROPS_CACHE[key] = (paths, _time.time())
            return paths
        except Exception:
            pass

    endpoint = "tv" if media_type in ("series", "anime") else "movie"
    url = f"{TMDB_BASE}/{endpoint}/{tmdb_id}/images"
    try:
        r = requests.get(url, params={"api_key": api_key, "include_image_language": "en,null"}, timeout=8)
        if r.status_code == 200:
            data = r.json()
            raw_backdrops = data.get("backdrops") or []
            paths = []
            for b in raw_backdrops[:8]:
                fp = b.get("file_path")
                if fp and fp not in paths:
                    local_img = _download_image(fp, f"backdrop_{tmdb_id}_{len(paths)}")
                    paths.append(local_img or fp)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(paths, f)
            _BACKDROPS_CACHE[key] = (paths, _time.time())
            return paths
    except Exception as e:
        print(f"[Matcher] Error fetching backdrops for {tmdb_id}: {e}")
    return []


def search_tmdb(query, media_type="movie", year=None):
    """
    Search TMDb for movies or TV shows and return formatted list of candidates.
    """
    if not query:
        return []
    endpoint = "search/movie" if media_type == "movie" else "search/tv"
    params = {"query": str(query).strip(), "language": "en-US"}
    if year:
        try:
            y = int(year)
            if media_type == "movie":
                params["year"] = str(y)
            else:
                params["first_air_date_year"] = str(y)
        except Exception:
            pass

    res = _tmdb_get(endpoint, params)
    if (not res or not res.get("results")) and year:
        params.pop("year", None)
        params.pop("first_air_date_year", None)
        res = _tmdb_get(endpoint, params)

    if not res:
        return []

    results = []
    for r in res.get("results", [])[:15]:
        title = r.get("title") if media_type == "movie" else r.get("name")
        orig_title = r.get("original_title") if media_type == "movie" else r.get("original_name")
        release_date = r.get("release_date") if media_type == "movie" else r.get("first_air_date")
        y = release_date[:4] if release_date else ""
        poster_path = r.get("poster_path")
        backdrop_path = r.get("backdrop_path")
        results.append({
            "tmdb_id": r.get("id"),
            "title": title,
            "original_title": orig_title,
            "year": y,
            "release_date": release_date,
            "overview": r.get("overview", ""),
            "poster_path": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
            "backdrop_path": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
            "vote_average": round(float(r.get("vote_average", 0)), 1),
            "media_type": media_type
        })
    return results

