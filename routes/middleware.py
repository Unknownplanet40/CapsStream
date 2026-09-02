# -*- coding: utf-8 -*-
"""
routes/middleware.py — Shared helpers and middleware for all CapsStream Blueprints.

This module contains all auth guards, profile helpers, and filter utilities
that were previously living as module-level functions in app.py.
"""
import os
import json
import time
import threading

from flask import session, request, abort, jsonify
from functools import wraps

# ─── PIN Brute-Force Protection ───────────────────────────────────────────────

_PIN_FAILS = {}          # profile_id -> [epoch timestamps of failures]
_PIN_FAILS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pin_fails.json")
_PIN_MAX_ATTEMPTS = 5
_PIN_LOCKOUT_SEC = 600   # 10 minutes


def _load_pin_fails():
    """Load persisted failure counts so restarts don't reset lockouts."""
    global _PIN_FAILS
    if _PIN_FAILS:
        return
    try:
        with open(_PIN_FAILS_FILE, encoding="utf-8") as f:
            raw = json.load(f) or {}
        now = time.time()
        _PIN_FAILS = {
            int(pid): [t for t in stamps if now - t < _PIN_LOCKOUT_SEC]
            for pid, stamps in raw.items()
        }
    except Exception:
        _PIN_FAILS = {}


def _save_pin_fails():
    try:
        os.makedirs(os.path.dirname(_PIN_FAILS_FILE), exist_ok=True)
        tmp = _PIN_FAILS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _PIN_FAILS.items()}, f)
        os.replace(tmp, _PIN_FAILS_FILE)
    except Exception:
        pass


def pin_lockout_remaining(profile_id):
    _load_pin_fails()
    now = time.time()
    fails = [t for t in _PIN_FAILS.get(profile_id, []) if now - t < _PIN_LOCKOUT_SEC]
    _PIN_FAILS[profile_id] = fails
    if len(fails) >= _PIN_MAX_ATTEMPTS:
        return int(_PIN_LOCKOUT_SEC - (now - fails[0])) + 1
    return 0


def record_pin_failure(profile_id):
    _load_pin_fails()
    fails = [t for t in _PIN_FAILS.get(profile_id, []) if time.time() - t < _PIN_LOCKOUT_SEC]
    fails.append(time.time())
    _PIN_FAILS[profile_id] = fails
    _save_pin_fails()


def clear_pin_failures(profile_id):
    _load_pin_fails()
    if _PIN_FAILS.pop(profile_id, None) is not None:
        _save_pin_fails()


# ─── Active Profile Session Tracking ──────────────────────────────────────────

ACTIVE_PROFILE_LOCK = threading.Lock()
ACTIVE_PROFILE_SESSIONS = {}  # profile_id -> {"session_id", "device_name", "last_seen", "evicted"}


# ─── Profile Session Helpers ──────────────────────────────────────────────────

def current_profile():
    return session.get("profile_id")


def require_profile():
    pid = current_profile()
    if not pid:
        abort(401, description="No profile selected")
    return pid


def get_admin_profiles():
    from backend.db import get_all_profiles
    all_profs = get_all_profiles()
    admins = [p for p in all_profs if p.get("is_admin")]
    if not admins and all_profs:
        return [all_profs[0]]
    return admins


def verify_admin_pin(pin):
    """
    Check if the provided PIN matches any admin profile.
    Returns (ok: bool, error_msg: str, status_code: int).
    """
    from backend.db import verify_pin_raw
    admins = get_admin_profiles()
    if not admins:
        return True, "", 200

    # If any admin profile has no PIN set, permission is granted directly
    if any(not a.get("has_pin") for a in admins):
        return True, "", 200

    pin_str = str(pin).strip() if pin is not None else ""
    if not pin_str:
        return False, "Admin PIN is required", 401

    for a in admins:
        if a.get("has_pin"):
            rem = pin_lockout_remaining(a["id"])
            if rem > 0:
                return False, f"Too many failed attempts — try again in {rem}s", 429
            if verify_pin_raw(a["id"], pin_str):
                clear_pin_failures(a["id"])
                return True, "", 200

    for a in admins:
        if a.get("has_pin"):
            record_pin_failure(a["id"])

    return False, "Incorrect Admin PIN", 401


def is_admin():
    """True when the active session profile is an Admin or a valid admin PIN was supplied."""
    if session.get("is_admin"):
        return True

    admin_pin = request.headers.get("X-Admin-PIN")
    if admin_pin is None and request.is_json and request.json:
        admin_pin = request.json.get("admin_pin")
    if admin_pin is None:
        admin_pin = request.args.get("admin_pin")
    if admin_pin is None and request.form:
        admin_pin = request.form.get("admin_pin")

    if admin_pin is not None and str(admin_pin).strip() != "":
        ok, _, _ = verify_admin_pin(admin_pin)
        if ok:
            return True

    # If there are no admin profiles with a PIN set, open access is allowed when no profile is active
    admins = get_admin_profiles()
    if not admins or any(not a.get("has_pin") for a in admins):
        if not current_profile():
            return True

    pid = current_profile()
    if not pid:
        from backend.db import get_all_profiles
        all_profs = get_all_profiles()
        return len(all_profs) == 0

    cached = session.get("is_admin")
    if cached is not None:
        return bool(cached)
    try:
        from backend.db import get_profile
        prof = get_profile(pid)
        val = bool(prof and prof.get("is_admin", 0))
        session["is_admin"] = val
        return val
    except Exception:
        return False


def require_admin():
    """Abort with 403 Forbidden if the active profile or request is not an Administrator."""
    if not is_admin():
        abort(403, description="Administrator privileges required")


def active_is_kids():
    """True when the active session profile is a Kids profile."""
    pid = current_profile()
    if not pid:
        return False
    cached = session.get("is_kids")
    if cached is not None:
        return bool(cached)
    try:
        from backend.db import get_profile
        prof = get_profile(pid)
        is_kids_flag = bool(prof and prof.get("is_kids"))
        session["is_kids"] = is_kids_flag
        return is_kids_flag
    except Exception:
        return False


def kids_overrides():
    """Parental allow/block decisions (global, profile_id=0)."""
    try:
        from backend.db import get_kids_override_map
        return get_kids_override_map()
    except Exception:
        return {"allow": set(), "block": set()}


def active_profile_obj():
    pid = current_profile()
    if not pid:
        return None
    try:
        from backend.db import get_profile
        return get_profile(pid)
    except Exception:
        return None


def filter_for_profile(items):
    """Server-side profile filtering for Kids mode, Maturity Rating tiers, and Blocked Genres."""
    if not items:
        return []
    prof = active_profile_obj()
    if not prof:
        return items

    if prof.get("is_kids"):
        from backend.kids_filter import filter_kids
        return filter_kids(items, overrides=kids_overrides())

    maturity = (prof.get("maturity_rating") or "All").strip()
    blocked_str = (prof.get("blocked_genres") or "").strip()
    blocked_genres_set = {g.strip().lower() for g in blocked_str.split(",") if g.strip()}

    TEEN_ALLOWED_CERTS = {"g", "pg", "pg-13", "tv-g", "tv-pg", "tv-14", "tv-y", "tv-y7", "u", "12", "12a", "15"}
    KIDS_ALLOWED_CERTS = {"g", "tv-g", "tv-y", "tv-y7", "u"}

    filtered = []
    for it in items:
        genres_str = (it.get("genres") or "").lower()
        if blocked_genres_set and any(bg in genres_str for bg in blocked_genres_set):
            continue
        cert = str(it.get("certification") or "").strip().lower()
        if maturity == "Kids":
            if cert and cert not in KIDS_ALLOWED_CERTS:
                continue
        elif maturity == "Teens":
            if cert and cert not in TEEN_ALLOWED_CERTS:
                continue
        filtered.append(it)
    return filtered


def kids_guard_media(media, deep=True):
    """Hard gate for single-item endpoints (detail page / playback)."""
    if not media:
        return None
    prof = active_profile_obj()
    if not prof:
        return None

    if prof.get("is_kids"):
        from backend.kids_filter import is_kid_safe
        safe, reason = is_kid_safe(media, deep=deep, overrides=kids_overrides())
        if not safe:
            return jsonify({"error": "Not available in Kids Mode", "reason": "kid_unsafe"}), 404
        return None

    blocked_str = (prof.get("blocked_genres") or "").strip()
    if blocked_str:
        blocked_genres_set = {g.strip().lower() for g in blocked_str.split(",") if g.strip()}
        genres_str = (media.get("genres") or "").lower()
        if any(bg in genres_str for bg in blocked_genres_set):
            return jsonify({"error": "Title is in your profile's blocked genres list", "reason": "genre_blocked"}), 404

    maturity = (prof.get("maturity_rating") or "All").strip()
    cert = str(media.get("certification") or "").strip().lower()
    TEEN_ALLOWED_CERTS = {"g", "pg", "pg-13", "tv-g", "tv-pg", "tv-14", "tv-y", "tv-y7", "u", "12", "12a", "15"}
    if maturity == "Teens" and cert and cert not in TEEN_ALLOWED_CERTS:
        return jsonify({"error": "Title exceeds profile maturity rating (Teens)", "reason": "maturity_exceeded"}), 404

    return None


def sanitize_profile(profile):
    if not profile:
        return None
    return {
        "id": profile["id"],
        "name": profile["name"],
        "avatar": profile.get("avatar", "ph-film-strip"),
        "color": profile.get("color", "#e50914"),
        "theme": profile.get("theme", "crimson"),
        "is_kids": bool(profile.get("is_kids", 0)),
        "is_admin": bool(profile.get("is_admin", 0)),
        "custom_avatar_url": profile.get("custom_avatar_url", ""),
        "maturity_rating": profile.get("maturity_rating", "All"),
        "blocked_genres": profile.get("blocked_genres", ""),
        "default_audio_lang": profile.get("default_audio_lang", ""),
        "default_sub_lang": profile.get("default_sub_lang", ""),
        "position": int(profile.get("position", 0) or 0),
        "auto_lock_minutes": int(profile.get("auto_lock_minutes", 0) or 0),
        "daily_limit_minutes": int(profile.get("daily_limit_minutes", 0) or 0),
        "bedtime_curfew": str(profile.get("bedtime_curfew", "") or ""),
        "has_pin": bool(profile.get("pin_hash")),
    }
