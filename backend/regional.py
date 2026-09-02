# -*- coding: utf-8 -*-
"""
backend/regional.py — Smart Country & Regional Collections Engine
Detects media country of origin and dynamically groups titles into Country Hubs.
"""

import os
import re
import json
from typing import List, Dict, Any, Optional

from backend.matcher import _load_cache, _save_cache, _tmdb_get

# ISO-3166-1 alpha-2 country definitions with language codes, flag emojis, and keyword triggers
COUNTRIES_MAP = {
    "PH": {
        "name": "Philippines",
        "flag": "🇵🇭",
        "languages": ["tl", "fil", "tgl", "ceb", "ilo", "hil", "war"],
        "keywords": [
            r"\bphilippines?\b", r"\bfilipino\b", r"\bpinoy\b", r"\btagalog\b",
            r"\bteleserye\b", r"\bvivamax\b", r"\bgma\b", r"\babs-cbn\b",
            r"\bstar cinema\b", r"\bregal\b", r"\bshake,? rattle\b",
            r"\bmanila('?s)?\b", r"\bprobinsyano\b", r"\bencantadia\b",
            r"\bcall me mother\b", r"\bmy husband is a mafia boss\b", r"\blove u lots\b",
            r"\bmiss behave\b", r"\bthe last house\b"
        ]
    },
    "KR": {
        "name": "South Korea",
        "flag": "🇰🇷",
        "languages": ["ko", "kor"],
        "keywords": [
            r"\bsouth korea\b", r"\bkorean?\b", r"\bk-drama\b", r"\bkdrama\b",
            r"\bk-series\b", r"\bk-movie\b", r"\bhallyu\b"
        ]
    },
    "JP": {
        "name": "Japan",
        "flag": "🇯🇵",
        "languages": ["ja", "jpn"],
        "keywords": [
            r"\bjapan(ese)?\b", r"\bj-drama\b", r"\bjdrama\b", r"\btokusatsu\b",
            r"\banime\b"
        ]
    },
    "US": {
        "name": "United States",
        "flag": "🇺🇸",
        "languages": ["en"],
        "keywords": [
            r"\bunited states\b", r"\bhollywood\b", r"\busa\b", r"\bamerican\b",
            r"\btoy story\b", r"\bvenom\b", r"\breacher\b", r"\bminions\b"
        ]
    },
    "GB": {
        "name": "United Kingdom",
        "flag": "🇬🇧",
        "languages": ["en"],
        "keywords": [
            r"\bunited kingdom\b", r"\bbritish\b", r"\buk\b", r"\bbbc\b", r"\bitv\b"
        ]
    },
    "CN": {
        "name": "China",
        "flag": "🇨🇳",
        "languages": ["zh", "cmn", "yue", "wuu"],
        "keywords": [
            r"\bchina\b", r"\bchinese\b", r"\bc-drama\b", r"\bcdrama\b", r"\bwuxia\b", r"\bxianxia\b"
        ]
    },
    "HK": {
        "name": "Hong Kong",
        "flag": "🇭🇰",
        "languages": ["yue", "zh"],
        "keywords": [
            r"\bhong kong\b", r"\bcantonese\b", r"\btvb\b"
        ]
    },
    "TW": {
        "name": "Taiwan",
        "flag": "🇹🇼",
        "languages": ["zh", "cmn"],
        "keywords": [
            r"\btaiwan(ese)?\b"
        ]
    },
    "TH": {
        "name": "Thailand",
        "flag": "🇹🇭",
        "languages": ["th", "tha"],
        "keywords": [
            r"\bthailand\b", r"\bthai\b", r"\bt-drama\b", r"\btdrama\b"
        ]
    },
    "ES": {
        "name": "Spain",
        "flag": "🇪🇸",
        "languages": ["es", "spa"],
        "keywords": [
            r"\bspain\b", r"\bspanish\b"
        ]
    },
    "FR": {
        "name": "France",
        "flag": "🇫🇷",
        "languages": ["fr", "fra"],
        "keywords": [
            r"\bfrance\b", r"\bfrench\b"
        ]
    },
    "DE": {
        "name": "Germany",
        "flag": "🇩🇪",
        "languages": ["de", "deu"],
        "keywords": [
            r"\bgermany\b", r"\bgerman\b"
        ]
    },
    "IN": {
        "name": "India",
        "flag": "🇮🇳",
        "languages": ["hi", "hin", "ta", "tam", "te", "tel", "ml", "mal", "bn", "pa"],
        "keywords": [
            r"\bindia(n)?\b", r"\bbollywood\b", r"\btollywood\b", r"\bkollywood\b",
            r"\bhindi\b", r"\btamil\b", r"\btelugu\b", r"\bmalayalam\b"
        ]
    },
    "IT": {
        "name": "Italy",
        "flag": "🇮🇹",
        "languages": ["it", "ita"],
        "keywords": [
            r"\bitaly\b", r"\bitalian\b"
        ]
    },
    "MX": {
        "name": "Mexico",
        "flag": "🇲🇽",
        "languages": ["es"],
        "keywords": [
            r"\bmexico\b", r"\bmexican\b", r"\btelenovela\b"
        ]
    },
    "CA": {
        "name": "Canada",
        "flag": "🇨🇦",
        "languages": ["en", "fr"],
        "keywords": [
            r"\bcanada\b", r"\bcanadian\b"
        ]
    },
    "AU": {
        "name": "Australia",
        "flag": "🇦🇺",
        "languages": ["en"],
        "keywords": [
            r"\baustralia(n)?\b"
        ]
    },
    "ID": {
        "name": "Indonesia",
        "flag": "🇮🇩",
        "languages": ["id", "ind"],
        "keywords": [
            r"\bindonesia(n)?\b", r"\bbahasa\b"
        ]
    }
}


def _get_flag_emoji(country_code: str) -> str:
    """Convert a 2-letter country code (ISO 3166-1 alpha-2) to its flag emoji."""
    if not country_code or len(country_code) != 2:
        return "🌐"
    code = country_code.upper()
    return chr(127397 + ord(code[0])) + chr(127397 + ord(code[1]))


def _load_or_fetch_origin(m_type: str, tmdb_id: int, cached: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ensure origin_country, production_countries, and original_language are loaded or backfilled."""
    if not tmdb_id:
        return cached

    if cached and ("origin_country" in cached or "production_countries" in cached or "original_language" in cached):
        return cached

    # Query TMDb to backfill origin & production country metadata for existing library items
    endpoint = f"tv/{tmdb_id}" if m_type in ("series", "anime") else f"movie/{tmdb_id}"
    try:
        detail = _tmdb_get(endpoint, {"language": "en-US"})
        if detail:
            if cached is None:
                cached = {}
            cached["origin_country"] = detail.get("origin_country") or []
            cached["production_countries"] = detail.get("production_countries") or []
            cached["original_language"] = detail.get("original_language")
            _save_cache("series" if m_type in ("series", "anime") else "movie", tmdb_id, cached)
    except Exception as e:
        pass

    return cached


def detect_item_country(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Detect the primary country of origin for a media item.
    Uses multi-source resolution:
      1. Cached TMDb metadata (origin_country, production_countries, original_language) with on-demand backfill
      2. File path & title keyword heuristics
    """
    if not item:
        return None

    m_type = item.get("type") or "movie"
    tmdb_id = item.get("tmdb_id")
    cached = None
    if tmdb_id:
        try:
            cached = _load_cache("series" if m_type in ("series", "anime") else "movie", tmdb_id)
            cached = _load_or_fetch_origin(m_type, tmdb_id, cached)
        except Exception:
            pass

    # 1. Check explicit TMDb origin_country (e.g. ['PH'])
    origin_countries = []
    if cached and cached.get("origin_country"):
        oc = cached.get("origin_country")
        if isinstance(oc, list):
            origin_countries = [c.upper() for c in oc if isinstance(c, str)]
        elif isinstance(oc, str):
            origin_countries = [oc.upper()]

    if origin_countries:
        for code in origin_countries:
            if code in COUNTRIES_MAP:
                c_info = COUNTRIES_MAP[code]
                return {
                    "code": code,
                    "name": c_info["name"],
                    "flag": c_info["flag"],
                }
            # Fallback for any other valid ISO country code
            if len(code) == 2 and code.isalpha():
                return {
                    "code": code,
                    "name": code,
                    "flag": _get_flag_emoji(code),
                }

    # 2. Check TMDb production_countries (e.g. [{'iso_3166_1': 'PH', 'name': 'Philippines'}])
    prod_countries = []
    if cached and cached.get("production_countries"):
        pcs = cached.get("production_countries")
        if isinstance(pcs, list):
            for pc in pcs:
                if isinstance(pc, dict) and pc.get("iso_3166_1"):
                    prod_countries.append(pc.get("iso_3166_1").upper())
                elif isinstance(pc, str):
                    prod_countries.append(pc.upper())

    if prod_countries:
        for code in prod_countries:
            if code in COUNTRIES_MAP:
                c_info = COUNTRIES_MAP[code]
                return {
                    "code": code,
                    "name": c_info["name"],
                    "flag": c_info["flag"],
                }
            if len(code) == 2 and code.isalpha():
                return {
                    "code": code,
                    "name": code,
                    "flag": _get_flag_emoji(code),
                }

    # 3. Check TMDb original_language (e.g. 'tl' -> PH, 'ko' -> KR, 'ja' -> JP)
    orig_lang = (cached.get("original_language") if cached else None) or item.get("original_language")
    if orig_lang:
        orig_lang = str(orig_lang).lower().strip()
        for code, info in COUNTRIES_MAP.items():
            if orig_lang in info.get("languages", []):
                # Don't assign English automatically unless verified by keywords or production countries
                if orig_lang == "en":
                    continue
                return {
                    "code": code,
                    "name": info["name"],
                    "flag": info["flag"],
                }

    # 4. Keyword Fallback against file_path, title, and original_title
    search_text = " ".join([
        str(item.get("file_path") or ""),
        str(item.get("title") or ""),
        str(item.get("original_title") or ""),
    ]).lower()

    for code, info in COUNTRIES_MAP.items():
        for pattern in info.get("keywords", []):
            if re.search(pattern, search_text, re.IGNORECASE):
                return {
                    "code": code,
                    "name": info["name"],
                    "flag": info["flag"],
                }

    return None


def get_country_collections(all_media: List[Dict[str, Any]], min_count: int = 2) -> List[Dict[str, Any]]:
    """
    Groups all library media into auto-generated Country Hub Smart Collections.
    Only returns countries with >= min_count unique titles.
    """
    if not all_media:
        return []

    # Map country_code -> list of media items
    country_groups: Dict[str, List[Dict[str, Any]]] = {}
    country_meta: Dict[str, Dict[str, str]] = {}

    for item in all_media:
        detected = detect_item_country(item)
        if not detected:
            continue
        code = detected["code"]
        if code not in country_groups:
            country_groups[code] = []
            country_meta[code] = detected
        country_groups[code].append(item)

    collections = []
    for code, items in country_groups.items():
        if len(items) < min_count:
            continue

        meta = country_meta[code]
        c_name = meta["name"]
        flag = meta["flag"]

        # Sort items: latest release year first, then title
        sorted_items = sorted(
            items,
            key=lambda x: (-(int(x.get("year") or 0)), (x.get("title") or "").lower())
        )

        movie_count = sum(1 for i in sorted_items if (i.get("type") or "movie") == "movie")
        series_count = sum(1 for i in sorted_items if (i.get("type") or "") in ("series", "anime"))

        collections.append({
            "id": f"country-{code.lower()}",
            "name": f"{c_name}",
            "country_code": code,
            "country_name": c_name,
            "flag": flag,
            "flag_svg": f"/static/img/flags/{code.lower()}.svg",
            "description": f"All movies, television series, and local cinema from {c_name}.",
            "is_country_hub": True,
            "smart": True,
            "items": sorted_items,
            "movie_count": movie_count,
            "series_count": series_count,
        })

    # Sort collections: largest collection count first
    collections.sort(key=lambda c: len(c.get("items") or []), reverse=True)
    return collections
