# -*- coding: utf-8 -*-
"""
routes/social.py — Stats, achievements, and network inspector.
"""
from flask import Blueprint, jsonify, request

from routes.middleware import require_profile

social_bp = Blueprint("social", __name__)


@social_bp.route("/api/stats", methods=["GET"])
def api_get_profile_stats():
    pid = require_profile()
    from backend.db import get_profile_watch_stats
    stats = get_profile_watch_stats(pid)
    return jsonify(stats)


@social_bp.route("/api/achievements/unlock", methods=["POST"])
def api_unlock_custom_achievement():
    pid = require_profile()
    data = request.json or {}
    achievement_id = data.get("achievement_id")
    if not achievement_id:
        return jsonify({"error": "achievement_id required"}), 400
    from backend.db import unlock_achievement
    unlocked_ach = unlock_achievement(pid, achievement_id)
    return jsonify({"ok": True, "unlocked": unlocked_ach})


@social_bp.route("/api/system/network-requests", methods=["GET"])
def api_get_network_requests():
    """Return recorded outgoing HTTP requests and activity metrics."""
    service_filter = request.args.get("service")
    status_filter = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 150))
    except (TypeError, ValueError):
        limit = 150
    limit = max(1, min(limit, 200))
    from backend.network_inspector import get_recorded_requests
    data = get_recorded_requests(limit=limit, service_filter=service_filter, status_filter=status_filter)
    return jsonify(data)


@social_bp.route("/api/system/network-requests/clear", methods=["POST"])
def api_clear_network_requests():
    """Clear recorded outgoing HTTP requests."""
    from backend.network_inspector import clear_recorded_requests
    clear_recorded_requests()
    return jsonify({"ok": True, "message": "Network activity log cleared"})
