"""
kids_filter.py — Central kid-safety content rules and filtering.

Single source of truth for what Kids profiles may see. Used by every
backend endpoint that serves media so enforcement never depends on the
frontend.

Rules (an item is allowed ONLY if ALL pass):
  1. Genre gate      — has at least one safe genre (Animation, Family,
                       Kids, Children); anime counts as Animation.
  2. Blocked genres  — Horror/Thriller/Crime/War/Romance/Mystery always block;
                       Action/Drama only allowed when the item also has a
                       core safe genre and no other blocked genre.
  3. Rating gate     — stored TMDb certification must be G / PG / TV-Y /
                       TV-Y7 / TV-G / TV-PG. Missing rating falls back to a
                       strict genre rule (pure Animation/Family/Kids only).
  4. Keyword gate    — title + overview + tagline must not match the sexual /
                       mature-content denylist (covers sex education and
                       teen/adult anatomy content even when mis-genred).
  5. Documentary     — documentary-only titles are blocked unless clearly
                       children's nature/science content.
"""

import re
import threading

# ─── Genre configuration ──────────────────────────────────────────────────────

KIDS_SAFE_GENRES = {"animation", "family", "kids", "children"}

# Always-blocked genres
KIDS_BLOCKED_GENRES = {"horror", "thriller", "crime", "war", "romance", "mystery"}

# Conditionally allowed: only when a core safe genre is present and nothing
# from KIDS_BLOCKED_GENRES is present.
KIDS_SOFT_GENRES = {"action", "drama"}

# Neutral genres that neither help nor hurt
KIDS_NEUTRAL_GENRES = {
    "adventure", "comedy", "fantasy", "music", "musical", "science fiction",
    "sci-fi", "sport", "sports", "history", "western",
}

# ─── Rating configuration (TMDb certifications) ───────────────────────────────

KID_SAFE_RATINGS = {"g", "pg", "tv-y", "tv-y7", "tv-g", "tv-pg"}
KID_BLOCKED_RATINGS = {"pg-13", "tv-14", "r", "nc-17", "tv-ma", "nr", "unrated", "not rated"}

# ─── Keyword denylist (title + overview + tagline) ────────────────────────────
# Word-boundary regexes, case-insensitive. Covers explicit sexual content AND
# educational material about human sexuality aimed at teens/adults.
_KID_KEYWORD_PATTERNS = [
    r"\bsex\b", r"\bsexual\w*\b", r"\bsexuality\b", r"\bsexy\b",
    r"\bporn\w*\b", r"\berotic\w*\b", r"\berotica\b",
    r"\bnude\b", r"\bnudity\b", r"\bnaked\b", r"\bnakeder?\b",
    r"\bintercourse\b", r"\bfornicat\w*\b", r"\bprostitut\w*\b",
    r"\bpuberty\b", r"\bcontracept\w*\b", r"\babortion\w*\b",
    r"\bmasturbat\w*\b", r"\borgasm\w*\b", r"\bfetish\w*\b", r"\bbdsm\b",
    r"\bkink\w*\b", r"\bsensual\w*\b", r"\bkamasutra\b", r"\btantric sex\b",
    r"\bqueer sex\b", r"\blgbtq?\W+(?:explicit|sex)",
    r"\bsex\s*ed(?:ucation)?\b", r"\bbirds\s+and\s+bees\b",
    r"\bhuman\s+reproduction\b", r"\breproductive\s+(?:system|organs|health)\b",
    r"\bwhere\s+babies\s+come\s+from\b", r"\bthe\s+birds\b.*\bthe\s+bees\b",
    r"\bhentai\b", r"\becchi\b", r"\byaoi\b", r"\byuri\b",
    r"\bstriptease\b", r"\bstripper\b", r"\bescort\s+service\b",
    r"\baffair\b", r"\badulter\w*\b", r"\bthreesome\b", r"\borgy\b",
]
_KID_KEYWORD_RE = [re.compile(p, re.IGNORECASE) for p in _KID_KEYWORD_PATTERNS]

# Fields scanned for keyword hits (in priority order)
_TEXT_FIELDS = ("title", "original_title", "ep_title", "tagline", "overview")

# Children-friendly documentary topics — a doc-only title mentioning one of
# these in its text is considered nature/science content for kids.
_KID_DOC_KEYWORDS = re.compile(
    r"\b(animal\w*|wildlife|nature|ocean\w*|sea |underwater|shark|whale|dolphin|"
    r"dinosaur\w*|space|planet\w*|solar system|universe|weather|volcano\w*|"
    r"jungle|rainforest|penguin\w*|polar bear\w*|lion\w*|elephant\w*|"
    r"insect\w*|bug\b|bugs\b|reptile\w*|bird\w*|forest\w*|farm\b|"
    r"science|experiment\w*|robot\w*|dinosaurs)\b",
    re.IGNORECASE,
)

# ─── Certification fetch cache ────────────────────────────────────────────────
_cert_lock = threading.Lock()
_cert_failed = set()   # tmdb_ids we failed to enrich recently — don't retry hot


def _genres_of(item):
    return {
        g.strip().lower()
        for g in (item.get("genres") or "").split(",")
        if g.strip()
    }


def _text_hits_denylist(item):
    for field in _TEXT_FIELDS:
        text = item.get(field)
        if not text:
            continue
        for rx in _KID_KEYWORD_RE:
            if rx.search(text):
                return f"keyword '{rx.pattern}' in {field}"
    return None


def _rating_verdict(certification):
    cert = (certification or "").strip().lower()
    if not cert:
        return None  # missing — caller decides fallback
    if cert in KID_SAFE_RATINGS:
        return True
    if cert in KID_BLOCKED_RATINGS:
        return False
    # Unknown certificate string — treat conservatively
    return None


def is_kid_safe(item, deep=False, debug=True):
    """
    Central verdict for whether a media item may appear in Kids Mode.

    Returns (safe: bool, reason: str). reason is '' when safe, otherwise a
    short human-readable explanation suitable for debug logging.
    """
    if not item:
        return False, "missing item"

    genres = _genres_of(item)
    if item.get("type") == "anime":
        genres.add("animation")

    has_core_safe = bool(genres & KIDS_SAFE_GENRES)
    hard_blocked = genres & KIDS_BLOCKED_GENRES
    soft_blocked = genres & KIDS_SOFT_GENRES
    unknown = genres - KIDS_SAFE_GENRES - KIDS_BLOCKED_GENRES - KIDS_SOFT_GENRES - KIDS_NEUTRAL_GENRES

    # 1) Hard-blocked genres always disqualify
    if hard_blocked:
        return False, f"blocked genre(s): {', '.join(sorted(hard_blocked))}"

    # 2) Soft genres (action/drama) only OK alongside a core safe genre
    if soft_blocked and not has_core_safe:
        return False, f"{', '.join(sorted(soft_blocked))} without Animation/Family"

    # 2b) Documentary-only titles need an explicitly child-friendly topic
    #     (checked before the genre-anchor gate — a kids' nature doc may not
    #     carry the Animation/Family genre at all)
    if genres <= {"documentary"}:
        text = " ".join(filter(None, (item.get(f) or "" for f in ("title", "overview", "tagline"))))
        if _KID_DOC_KEYWORDS.search(text):
            return True, ""
        return False, "documentary without children's topic"

    # 3) Unknown/mature genres with no safe anchor → block
    if not has_core_safe:
        if genres:
            return False, f"no Animation/Family/Kids genre ({', '.join(sorted(genres))})"
        return False, "no genre data"

    # 5) Keyword denylist over title/tagline/overview
    hit = _text_hits_denylist(item)
    if hit:
        return False, hit

    # 6) Rating gate
    cert = (item.get("certification") or "").strip()
    if not cert and deep and item.get("tmdb_id"):
        cert = ensure_certification(item) or ""
    verdict = _rating_verdict(cert)
    if verdict is True:
        return True, ""
    if verdict is False:
        return False, f"rating '{cert}' is not kid-safe"

    # 7) Missing rating → require pure kid-core genres (no soft/unknown mix)
    if soft_blocked or unknown:
        return False, f"unrated and mixed genres ({', '.join(sorted(genres))})"

    return True, ""


def filter_kids(items, deep=False):
    """Filter a list of media dicts down to kid-safe entries. Logs blocks."""
    result = []
    for item in items or []:
        safe, reason = is_kid_safe(item, deep=deep)
        if safe:
            result.append(item)
        elif debug_enabled():
            print(f"[KidsFilter] blocked '{item.get('title')}' — {reason}")
    return result


_debug = True


def debug_enabled():
    return _debug


def set_debug(enabled):
    global _debug
    _debug = bool(enabled)


# ─── TMDb certification enrichment ────────────────────────────────────────────

def ensure_certification(item):
    """
    Lazily fetch and persist the US certification for an item from TMDb.
    Returns the certification string ('' when unavailable). Only called for
    single-item decisions (detail page / playback), never bulk lists.
    """
    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        return ""
    media_type = "movie" if item.get("type") == "movie" else "tv"

    with _cert_lock:
        if tmdb_id in _cert_failed:
            return ""

    cert = _fetch_tmdb_certification(tmdb_id, media_type)

    if cert:
        try:
            from backend.db import get_conn
            conn = get_conn()
            conn.execute(
                "UPDATE media SET certification=? WHERE tmdb_id=?",
                (cert, tmdb_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[KidsFilter] Could not persist certification for tmdb {tmdb_id}: {e}")
    else:
        with _cert_lock:
            _cert_failed.add(tmdb_id)
    return cert or ""


def _fetch_tmdb_certification(tmdb_id, media_type):
    try:
        from backend.matcher import _tmdb_get
        if media_type == "movie":
            data = _tmdb_get(f"movie/{tmdb_id}/release_dates")
            for country in (data or {}).get("results", []):
                if country.get("iso_3166_1") == "US":
                    for rd in country.get("release_dates", []):
                        c = (rd.get("certification") or "").strip()
                        if c:
                            return c
        else:
            data = _tmdb_get(f"tv/{tmdb_id}/content_ratings")
            for rating in (data or {}).get("results", []):
                if rating.get("iso_3166_1") == "US":
                    c = (rating.get("rating") or "").strip()
                    if c:
                        return c
    except Exception as e:
        print(f"[KidsFilter] Certification lookup failed for tmdb {tmdb_id}: {e}")
    return ""
