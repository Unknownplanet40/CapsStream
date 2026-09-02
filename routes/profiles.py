# -*- coding: utf-8 -*-
"""
routes/profiles.py — Profile management, auth, session, and PIN endpoints.
"""
import os
import time
import threading

from flask import Blueprint, jsonify, request, session
from flask_limiter import Limiter

from routes.middleware import (
    current_profile, require_profile, require_admin, is_admin,
    pin_lockout_remaining, record_pin_failure, clear_pin_failures,
    verify_admin_pin, get_admin_profiles, sanitize_profile,
    ACTIVE_PROFILE_LOCK, ACTIVE_PROFILE_SESSIONS,
)

from backend.db import (
    get_all_profiles, get_profile, create_profile, update_profile,
    delete_profile, reorder_profiles, verify_pin_raw, hash_pin,
)

profiles_bp = Blueprint("profiles", __name__)

# ─── Limiter reference (injected from app.py at registration time) ─────────────
_limiter: Limiter = None


def init_limiter(limiter_instance):
    global _limiter
    _limiter = limiter_instance


# ─── Profiles CRUD ────────────────────────────────────────────────────────────

@profiles_bp.route("/api/profiles", methods=["GET"])
def api_get_profiles():
    now = time.time()
    with ACTIVE_PROFILE_LOCK:
        stale_pids = [pid for pid, sess in ACTIVE_PROFILE_SESSIONS.items() if now - sess.get("last_seen", 0) > 45]
        for pid in stale_pids:
            del ACTIVE_PROFILE_SESSIONS[pid]
        active_map = {pid: dict(sess) for pid, sess in ACTIVE_PROFILE_SESSIONS.items()}

    profiles = get_all_profiles()
    for p in profiles:
        pid = p.get("id")
        sess = active_map.get(pid)
        if sess and not sess.get("evicted"):
            p["in_use"] = True
            p["active_device"] = sess.get("device_name", "Another Device")
            p["active_session_id"] = sess.get("session_id", "")
        else:
            p["in_use"] = False
            p["active_device"] = ""
            p["active_session_id"] = ""
    return jsonify(profiles)


@profiles_bp.route("/api/profiles", methods=["POST"])
def api_create_profile():
    require_admin()
    from backend.settings import load_config
    cfg = load_config()
    max_profiles = int(cfg.get("profiles", {}).get("max_profiles", 8) if isinstance(cfg.get("profiles"), dict) else 8)
    all_prof = get_all_profiles()
    if len(all_prof) >= max_profiles:
        return jsonify({"error": f"Maximum profile capacity reached ({max_profiles} profiles)"}), 400

    data = request.json or {}
    name = (data.get("name") or "").strip()
    raw_pin = data.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""
    avatar = data.get("avatar", "ph-film-strip")
    color  = data.get("color", "#e50914")
    theme  = str(data.get("theme", "crimson") or "crimson").strip()
    is_admin_flag = bool(data.get("is_admin", False))
    custom_avatar_url = str(data.get("custom_avatar_url", "") or "").strip()
    maturity_rating = str(data.get("maturity_rating", "All") or "All").strip()
    blocked_genres = str(data.get("blocked_genres", "") or "").strip()
    default_audio_lang = str(data.get("default_audio_lang", "") or "").strip()
    default_sub_lang = str(data.get("default_sub_lang", "") or "").strip()
    auto_lock_minutes = int(data.get("auto_lock_minutes", 0) or 0)

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if pin and len(pin) != 4:
        return jsonify({"error": "PIN must be exactly 4 digits"}), 400

    is_kids = bool(data.get("is_kids", False))
    daily_limit_minutes = int(data.get("daily_limit_minutes", 0) or 0)
    bedtime_curfew = str(data.get("bedtime_curfew", "") or "").strip()
    pin_hash = hash_pin(pin) if pin else None
    pid = create_profile(
        name, pin_hash, avatar, color, is_kids=is_kids,
        daily_limit_minutes=daily_limit_minutes, bedtime_curfew=bedtime_curfew,
        theme=theme, is_admin=is_admin_flag, custom_avatar_url=custom_avatar_url,
        maturity_rating=maturity_rating, blocked_genres=blocked_genres,
        default_audio_lang=default_audio_lang, default_sub_lang=default_sub_lang,
        position=len(all_prof), auto_lock_minutes=auto_lock_minutes
    )
    if is_kids:
        active_pid = current_profile()
        if active_pid:
            from backend.db import unlock_achievement
            unlock_achievement(active_pid, "kids_creator")
    created_prof = get_profile(pid)
    if created_prof:
        return jsonify(sanitize_profile(created_prof)), 201
    return jsonify({
        "id": pid, "name": name, "avatar": avatar, "color": color, "theme": theme,
        "is_kids": is_kids, "is_admin": is_admin_flag, "custom_avatar_url": custom_avatar_url,
        "maturity_rating": maturity_rating, "blocked_genres": blocked_genres,
        "default_audio_lang": default_audio_lang, "default_sub_lang": default_sub_lang,
        "daily_limit_minutes": daily_limit_minutes, "bedtime_curfew": bedtime_curfew,
        "auto_lock_minutes": auto_lock_minutes
    }), 201



@profiles_bp.route("/api/profiles/<int:profile_id>", methods=["PUT"])
def api_update_profile(profile_id):
    active_pid = current_profile()
    if not is_admin() and active_pid != profile_id:
        return jsonify({"error": "Administrator privileges required to edit other profiles"}), 403

    data = request.json or {}
    name = (data.get("name") or "").strip()
    raw_pin = data.get("pin")
    is_kids = bool(data.get("is_kids", False))
    avatar = data.get("avatar", "ph-film-strip")
    color  = data.get("color", "#e50914")
    theme  = str(data.get("theme", "crimson") or "crimson").strip()
    is_admin_flag = data.get("is_admin")
    custom_avatar_url = data.get("custom_avatar_url")
    maturity_rating = str(data.get("maturity_rating", "All") or "All").strip()
    blocked_genres = str(data.get("blocked_genres", "") or "").strip()
    default_audio_lang = str(data.get("default_audio_lang", "") or "").strip()
    default_sub_lang = str(data.get("default_sub_lang", "") or "").strip()
    auto_lock_minutes = int(data.get("auto_lock_minutes", 0) or 0)
    update_pin = bool(data.get("update_pin", False))

    if not is_admin():
        existing = get_profile(profile_id)
        if existing:
            is_admin_flag = bool(existing.get("is_admin", 0))
            maturity_rating = str(existing.get("maturity_rating", "All") or "All")
            is_kids = bool(existing.get("is_kids", 0))

    if not name:
        return jsonify({"error": "Name is required"}), 400

    if is_kids:
        pin_hash = None
        update_pin = True
    else:
        if update_pin:
            pin = str(raw_pin).strip() if raw_pin is not None else ""
            if pin and len(pin) != 4:
                return jsonify({"error": "PIN must be exactly 4 digits"}), 400
            pin_hash = hash_pin(pin) if pin else None
        else:
            pin_hash = None

    daily_limit_minutes = int(data.get("daily_limit_minutes", 0) or 0)
    bedtime_curfew = str(data.get("bedtime_curfew", "") or "").strip()
    update_profile(
        profile_id, name, pin_hash, avatar, color, is_kids,
        update_pin=update_pin, daily_limit_minutes=daily_limit_minutes,
        bedtime_curfew=bedtime_curfew, theme=theme, is_admin=is_admin_flag,
        custom_avatar_url=custom_avatar_url, maturity_rating=maturity_rating,
        blocked_genres=blocked_genres, default_audio_lang=default_audio_lang,
        default_sub_lang=default_sub_lang, auto_lock_minutes=auto_lock_minutes
    )

    if update_pin:
        clear_pin_failures(profile_id)

    prof = get_profile(profile_id)
    return jsonify(sanitize_profile(prof))


@profiles_bp.route("/api/profiles/<int:profile_id>/avatar", methods=["POST"])
def api_upload_profile_avatar(profile_id):
    from flask import current_app
    active_pid = current_profile()
    if not is_admin() and active_pid != profile_id:
        return jsonify({"error": "Administrator privileges required to update other profiles' avatars"}), 403

    if "avatar" not in request.files:
        return jsonify({"error": "No avatar image file provided"}), 400
    file = request.files["avatar"]
    if not file or not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        return jsonify({"error": "Supported formats: png, jpg, jpeg, webp, gif"}), 400

    BASE_DIR = current_app.config["BASE_DIR"]
    avatars_dir = os.path.join(BASE_DIR, "data", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    filename = f"avatar_{profile_id}_{int(time.time())}{ext}"
    target_path = os.path.join(avatars_dir, filename)
    file.save(target_path)

    custom_url = f"/metadata/avatars/{filename}"
    prof = get_profile(profile_id)
    if prof:
        update_profile(
            profile_id,
            name=prof["name"],
            avatar=prof.get("avatar", "ph-film-strip"),
            color=prof.get("color", "#e50914"),
            is_kids=bool(prof.get("is_kids")),
            theme=prof.get("theme", "crimson"),
            is_admin=bool(prof.get("is_admin")),
            custom_avatar_url=custom_url,
            maturity_rating=prof.get("maturity_rating", "All"),
            blocked_genres=prof.get("blocked_genres", ""),
            default_audio_lang=prof.get("default_audio_lang", ""),
            default_sub_lang=prof.get("default_sub_lang", ""),
            position=prof.get("position", 0),
            auto_lock_minutes=prof.get("auto_lock_minutes", 0)
        )
    return jsonify({"ok": True, "custom_avatar_url": custom_url})


@profiles_bp.route("/api/profiles/reorder", methods=["POST"])
def api_reorder_profiles():
    require_admin()
    data = request.json or {}
    ordered_ids = data.get("ordered_ids", [])
    if not isinstance(ordered_ids, list):
        return jsonify({"error": "ordered_ids array required"}), 400
    reorder_profiles([int(i) for i in ordered_ids])
    return jsonify({"ok": True})


@profiles_bp.route("/api/profiles/<int:profile_id>", methods=["DELETE", "POST"])
def api_delete_profile(profile_id):
    require_admin()
    active_pid = current_profile()
    if active_pid:
        active_prof = get_profile(active_pid)
        if active_prof and active_prof.get("is_kids"):
            return jsonify({"error": "Kids profiles cannot delete profiles"}), 403

    all_profiles = get_all_profiles()
    if len(all_profiles) <= 1:
        return jsonify({"error": "Cannot delete the only profile"}), 400

    target = get_profile(profile_id)
    if not target:
        return jsonify({"error": "Profile not found"}), 404

    data = request.json if (request.data and request.is_json) else {}
    raw_pin = data.get("pin") if data else request.args.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""

    if target.get("pin_hash"):
        remaining = pin_lockout_remaining(profile_id)
        if remaining > 0:
            return jsonify({
                "error": f"Too many failed attempts — try again in {remaining}s",
                "retry_after": remaining,
            }), 429
        if not verify_pin_raw(profile_id, pin):
            record_pin_failure(profile_id)
            return jsonify({"error": "Incorrect PIN"}), 401
        clear_pin_failures(profile_id)

    delete_profile(profile_id)
    if session.get("profile_id") == profile_id:
        session.pop("profile_id", None)
    return jsonify({"ok": True})


# ─── Auth Endpoints (rate limited in app.py via limiter.limit on blueprint) ───

@profiles_bp.route("/api/profiles/auth", methods=["POST"])
def api_auth_profile():
    data = request.json or {}
    profile_id = data.get("profile_id")
    raw_pin = data.get("pin")
    pin = str(raw_pin).strip() if raw_pin is not None else ""
    force_takeover = bool(data.get("force_takeover", False))
    client_session_id = str(data.get("session_id") or "").strip()
    device_name = str(data.get("device_name") or "Desktop App").strip()

    if not profile_id:
        return jsonify({"error": "profile_id required"}), 400

    now = time.time()
    with ACTIVE_PROFILE_LOCK:
        curr_sess = ACTIVE_PROFILE_SESSIONS.get(profile_id)
        if curr_sess and not curr_sess.get("evicted") and (now - curr_sess.get("last_seen", 0) <= 45):
            if client_session_id and curr_sess.get("session_id") != client_session_id:
                if not force_takeover:
                    return jsonify({
                        "status": "in_use",
                        "in_use": True,
                        "device_name": curr_sess.get("device_name", "Another Device"),
                        "message": f"This profile is currently active on {curr_sess.get('device_name', 'another device')}."
                    }), 409

    remaining = pin_lockout_remaining(profile_id)
    if remaining > 0:
        return jsonify({
            "error": f"Too many failed attempts — try again in {remaining}s",
            "retry_after": remaining,
        }), 429

    profile = get_profile(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if not verify_pin_raw(profile_id, pin):
        record_pin_failure(profile_id)
        return jsonify({"error": "Incorrect PIN"}), 401
    clear_pin_failures(profile_id)

    with ACTIVE_PROFILE_LOCK:
        old_sess = ACTIVE_PROFILE_SESSIONS.get(profile_id)
        if old_sess and client_session_id and old_sess.get("session_id") != client_session_id:
            old_sess["evicted"] = True
        ACTIVE_PROFILE_SESSIONS[profile_id] = {
            "session_id": client_session_id,
            "device_name": device_name,
            "last_seen": now,
            "evicted": False,
        }

    session["profile_id"] = profile_id
    session["is_kids"] = bool(profile.get("is_kids", 0))
    session["is_admin"] = bool(profile.get("is_admin", 0))
    return jsonify({"ok": True, "profile": sanitize_profile(profile)})


@profiles_bp.route("/api/profiles/heartbeat", methods=["POST"])
def api_profile_heartbeat():
    data = request.json or {}
    client_session_id = str(data.get("session_id") or "").strip()
    device_name = str(data.get("device_name") or "Desktop App").strip()
    pid = current_profile()
    if not pid:
        return jsonify({"status": "no_profile", "evicted": False})

    now = time.time()
    with ACTIVE_PROFILE_LOCK:
        sess = ACTIVE_PROFILE_SESSIONS.get(pid)
        if sess:
            if sess.get("evicted") or (client_session_id and sess.get("session_id") != client_session_id):
                return jsonify({"status": "evicted", "evicted": True})
            sess["last_seen"] = now
            sess["device_name"] = device_name
        else:
            ACTIVE_PROFILE_SESSIONS[pid] = {
                "session_id": client_session_id,
                "device_name": device_name,
                "last_seen": now,
                "evicted": False,
            }
    return jsonify({"status": "ok", "evicted": False})


@profiles_bp.route("/api/profiles/release", methods=["POST"])
def api_release_profile():
    data = request.json or {}
    client_session_id = str(data.get("session_id") or "").strip()
    pid = current_profile() or data.get("profile_id")
    if pid:
        with ACTIVE_PROFILE_LOCK:
            sess = ACTIVE_PROFILE_SESSIONS.get(pid)
            if sess and (not client_session_id or sess.get("session_id") == client_session_id):
                del ACTIVE_PROFILE_SESSIONS[pid]
    return jsonify({"ok": True})


@profiles_bp.route("/api/profiles/me", methods=["GET"])
def api_me():
    pid = current_profile()
    if not pid:
        return jsonify(None)
    profile = get_profile(pid)
    if not profile:
        session.pop("profile_id", None)
        session.pop("is_kids", None)
        session.pop("is_admin", None)
        return jsonify(None)
    session["is_kids"] = bool(profile.get("is_kids", 0))
    session["is_admin"] = bool(profile.get("is_admin", 0))
    return jsonify(sanitize_profile(profile))


@profiles_bp.route("/api/profiles/logout", methods=["POST"])
def api_logout():
    pid = session.pop("profile_id", None)
    session.pop("is_kids", None)
    session.pop("is_admin", None)
    if pid:
        with ACTIVE_PROFILE_LOCK:
            ACTIVE_PROFILE_SESSIONS.pop(pid, None)
    return jsonify({"ok": True})


@profiles_bp.route("/api/profiles/admin-pin-status", methods=["GET"])
def api_admin_pin_status():
    admins = get_admin_profiles()
    if not admins:
        return jsonify({"pin_required": False, "admin_count": 0})
    pin_required = all(bool(a.get("has_pin")) for a in admins)
    return jsonify({"pin_required": pin_required, "admin_count": len(admins)})


@profiles_bp.route("/api/profiles/verify-admin-pin", methods=["POST"])
def api_verify_admin_pin():
    data = request.json or {}
    pin = data.get("pin", "")
    ok, err, code = verify_admin_pin(pin)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), code
