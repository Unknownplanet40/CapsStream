# -*- coding: utf-8 -*-
"""
routes/social.py — Stats, achievements, and network inspector.
"""
from flask import Blueprint, jsonify, request

from .middleware import require_profile

social_bp = Blueprint("social", __name__)


@social_bp.route("/api/stats", methods=["GET"])
def api_get_profile_stats():
    pid = require_profile()
    from backend.db import get_profile_watch_stats
    stats = get_profile_watch_stats(pid)
    return jsonify(stats)


@social_bp.route("/api/analytics/wrapped", methods=["GET"])
def api_get_wrapped_analytics():
    pid = require_profile()
    period = request.args.get("period", "year")
    year = request.args.get("year")
    archetype_override = request.args.get("archetype")
    from backend.db import get_profile_wrapped_analytics
    data = get_profile_wrapped_analytics(pid, period=period, year=year, archetype_override=archetype_override)
    return jsonify(data)


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


@social_bp.route("/api/social/debug/snapshot", methods=["POST"])
def api_debug_snapshot():
    """Create a point-in-time backup snapshot of the active profile."""
    pid = require_profile()
    data = request.json or {}
    label = data.get("label", "Pre-Debug Easter Egg Backup")
    from backend.db import create_profile_snapshot
    res = create_profile_snapshot(pid, label=label)
    if not res:
        return jsonify({"ok": False, "error": "Failed to create snapshot"}), 500
    return jsonify({"ok": True, "snapshot": res})


@social_bp.route("/api/social/debug/snapshot/latest", methods=["GET"])
def api_debug_latest_snapshot():
    """Get metadata for the active profile's latest snapshot."""
    pid = require_profile()
    from backend.db import get_latest_profile_snapshot
    snap = get_latest_profile_snapshot(pid)
    return jsonify({"ok": True, "snapshot": snap})


@social_bp.route("/api/social/debug/revert", methods=["POST"])
def api_debug_revert():
    """Revert the active profile's data from the latest (or specified) snapshot."""
    pid = require_profile()
    data = request.json or {}
    snapshot_id = data.get("snapshot_id")
    from backend.db import revert_profile_snapshot
    success, msg = revert_profile_snapshot(pid, snapshot_id=snapshot_id)
    if not success:
        return jsonify({"ok": False, "error": msg}), 400
    return jsonify({"ok": True, "message": msg})


@social_bp.route("/api/social/debug/achievements/unlock-all", methods=["POST"])
def api_debug_unlock_all():
    """Unlock all achievements for the active profile."""
    pid = require_profile()
    from backend.db import unlock_all_achievements
    res = unlock_all_achievements(pid)
    if isinstance(res, tuple):
        count, newly_unlocked = res
    else:
        count, newly_unlocked = res, []
    return jsonify({"ok": True, "unlocked_count": count, "unlocked_items": newly_unlocked})


@social_bp.route("/api/social/debug/achievements/reset-all", methods=["POST"])
def api_debug_reset_all():
    """Reset / clear all achievements for the active profile."""
    pid = require_profile()
    from backend.db import reset_all_achievements
    count = reset_all_achievements(pid)
    return jsonify({"ok": True, "removed_count": count})


@social_bp.route("/api/social/debug/achievements/toggle-category", methods=["POST"])
def api_debug_toggle_category():
    """Toggle unlocks for an entire category."""
    pid = require_profile()
    data = request.json or {}
    category = data.get("category")
    unlock = data.get("unlock", True)
    if not category:
        return jsonify({"error": "category required"}), 400
    from backend.db import toggle_category_achievements
    count = toggle_category_achievements(pid, category, unlock=unlock)
    return jsonify({"ok": True, "affected_count": count})


@social_bp.route("/api/social/debug/simulate-stats", methods=["POST"])
def api_debug_simulate_stats():
    """Simulate activity for testing heatmap, streaks, and habits."""
    pid = require_profile()
    data = request.json or {}
    streak_days = int(data.get("streak_days", 14))
    hours_to_add = float(data.get("hours_to_add", 20.0))
    weekend_spike = bool(data.get("weekend_spike", True))
    from backend.db import simulate_profile_stats
    added = simulate_profile_stats(pid, streak_days=streak_days, hours_to_add=hours_to_add, weekend_spike=weekend_spike)
    return jsonify({"ok": True, "added_records": added})


@social_bp.route("/api/social/debug/export", methods=["GET"])
def api_debug_export():
    """Export profile data payload as JSON."""
    pid = require_profile()
    from backend.db import export_profile_data
    payload = export_profile_data(pid)
    if not payload:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(payload)


@social_bp.route("/api/social/debug/import", methods=["POST"])
def api_debug_import():
    """Import profile data payload."""
    pid = require_profile()
    payload = request.json or {}
    from backend.db import import_profile_data
    success, msg = import_profile_data(pid, payload)
    if not success:
        return jsonify({"ok": False, "error": msg}), 400
    return jsonify({"ok": True, "message": msg})



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
