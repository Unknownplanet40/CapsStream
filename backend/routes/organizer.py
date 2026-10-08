# -*- coding: utf-8 -*-
"""
backend/routes/organizer.py — Media Renamer & File Organizer HTTP API & Webhooks.

Provides endpoints for:
  - Viewing and saving organizer configuration.
  - Generating dry-run preview batches of incoming media.
  - Executing organization plans (smart hardlinks / moves).
  - Viewing history and rolling back batches.
  - Webhook integration (/api/hooks/downloaded) for downloaders (qBittorrent, etc.).
"""

import os
import json
import logging
from flask import Blueprint, jsonify, request

from .middleware import require_admin, is_admin
from backend.settings import load_config, save_config
from backend.utils.paths import BASE_DIR
from backend.organizer import (
    scan_incoming_for_preview,
    execute_organization_plan,
    clean_empty_subfolders,
    undo_batch,
    ORGANIZER_HISTORY_FILE,
    trigger_post_processing,
    classify_media_file,
    resolve_canonical_item,
    build_destination_path,
    find_companion_subtitles,
    get_organizer_library_roots,
    REGIONS,
)

organizer_bp = Blueprint("organizer", __name__)
logger = logging.getLogger("media_organizer_api")


def _is_safe_abs_path(path_str: str) -> bool:
    """Validate that path is absolute and free of traversal segments."""
    if not path_str or not path_str.strip():
        return True
    cleaned = path_str.strip()
    if ".." in cleaned:
        return False
    return os.path.isabs(cleaned)


def _get_organizer_config() -> dict:
    cfg = load_config()
    org_cfg = cfg.get("organizer", {})
    default_incoming = org_cfg.get("incoming_dir") or os.path.join(BASE_DIR, "data", "incoming")
    media_paths = cfg.get("media_paths", {})

    def _first_path(val, default):
        if isinstance(val, list):
            return val[0] if val else default
        return val or default

    def _list_paths(val):
        if isinstance(val, list):
            return [str(p) for p in val if p]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    movies_available = _list_paths(media_paths.get("movies"))
    series_available = _list_paths(media_paths.get("series") or media_paths.get("tv"))
    anime_available = _list_paths(media_paths.get("anime"))

    target_movies = org_cfg.get("target_movies_path") or _first_path(media_paths.get("movies"), os.path.join(BASE_DIR, "data", "media", "Movies"))
    target_series = org_cfg.get("target_series_path") or _first_path(media_paths.get("series") or media_paths.get("tv"), os.path.join(BASE_DIR, "data", "media", "TV Shows"))
    target_anime = org_cfg.get("target_anime_path") or _first_path(media_paths.get("anime"), os.path.join(BASE_DIR, "data", "media", "Anime"))

    target_local_movies = org_cfg.get("target_local_movies_path") or ""
    target_local_series = org_cfg.get("target_local_series_path") or ""

    library_roots = get_organizer_library_roots(cfg)

    return {
        "enabled": org_cfg.get("enabled", True),
        "incoming_dir": default_incoming,
        "mode": org_cfg.get("mode", "smart"),
        "auto_watch": org_cfg.get("auto_watch", False),
        "watch_interval_seconds": org_cfg.get("watch_interval_seconds", 60),
        "target_movies_path": target_movies,
        "target_series_path": target_series,
        "target_anime_path": target_anime,
        "local_region": org_cfg.get("local_region", ""),
        "target_local_movies_path": target_local_movies,
        "target_local_series_path": target_local_series,
        "collision_policy": org_cfg.get("collision_policy", "skip"),
        "regions": REGIONS,
        "available_paths": {
            "movies": movies_available,
            "series": series_available,
            "anime": anime_available,
        },
        "library_roots": library_roots,
    }


@organizer_bp.route("/api/admin/organizer/config", methods=["GET"])
def api_get_organizer_config():
    require_admin()
    return jsonify(_get_organizer_config())


@organizer_bp.route("/api/admin/organizer/config", methods=["POST"])
def api_save_organizer_config():
    require_admin()
    data = request.json or {}
    cfg = load_config()
    org_cfg = cfg.get("organizer", {})

    # Validation: local_region
    if "local_region" in data:
        reg_val = str(data["local_region"]).strip().upper()
        if reg_val and reg_val not in REGIONS:
            return jsonify({"error": f"Invalid local_region code '{reg_val}'. Must be in supported regions or empty."}), 400
        org_cfg["local_region"] = reg_val

    # Validation: collision_policy
    if "collision_policy" in data:
        pol_val = str(data["collision_policy"]).strip().lower()
        if pol_val not in ("skip", "suffix"):
            return jsonify({"error": f"Invalid collision_policy '{pol_val}'. Allowed: 'skip', 'suffix'."}), 400
        org_cfg["collision_policy"] = pol_val

    # Path traversal and absolute path validation
    path_keys = [
        "incoming_dir", "target_movies_path", "target_series_path",
        "target_anime_path", "target_local_movies_path", "target_local_series_path"
    ]
    for pk in path_keys:
        if pk in data:
            raw_path = str(data[pk]).strip()
            if raw_path and not _is_safe_abs_path(raw_path):
                return jsonify({"error": f"Invalid path for '{pk}'. Path must be absolute and contain no traversal ('..')."}), 400
            org_cfg[pk] = raw_path

    if "mode" in data and data["mode"] in ("smart", "move", "copy"):
        org_cfg["mode"] = data["mode"]
    if "auto_watch" in data:
        org_cfg["auto_watch"] = bool(data["auto_watch"])
    if "watch_interval_seconds" in data:
        try:
            org_cfg["watch_interval_seconds"] = max(15, int(data["watch_interval_seconds"]))
        except ValueError:
            pass

    cfg["organizer"] = org_cfg
    ok, err = save_config(cfg)
    if not ok:
        return jsonify({"error": f"Failed to save settings: {err}"}), 500

    return jsonify({"success": True, "config": _get_organizer_config()})


@organizer_bp.route("/api/admin/organizer/preview", methods=["POST"])
def api_organizer_preview():
    """Run a dry-run scan on the incoming folder and return candidate items."""
    require_admin()
    body = request.json or {}
    org_cfg = _get_organizer_config()

    incoming_dir = body.get("incoming_dir") or org_cfg["incoming_dir"]
    if not os.path.isdir(incoming_dir):
        return jsonify({"error": f"Directory not found: {incoming_dir}", "items": []}), 404

    lib_roots = org_cfg["library_roots"]
    cfg = load_config()
    tmdb_key = cfg.get("tmdb_api_key")
    local_reg = org_cfg.get("local_region", "")
    col_policy = org_cfg.get("collision_policy", "skip")

    items = scan_incoming_for_preview(
        incoming_dir,
        lib_roots,
        tmdb_api_key=tmdb_key,
        clean_empty=True,
        local_region=local_reg,
        collision_policy=col_policy,
    )
    cleaned = clean_empty_subfolders(incoming_dir, delete_root_if_empty=False)
    return jsonify({
        "incoming_dir": incoming_dir,
        "count": len(items),
        "items": items,
        "cleaned_folders": cleaned
    })


@organizer_bp.route("/api/admin/organizer/execute", methods=["POST"])
def api_organizer_execute():
    """Execute organization for selected or all previewed items."""
    require_admin()
    body = request.json or {}
    items = body.get("items", [])
    if not items:
        return jsonify({"error": "No items provided for organization"}), 400

    org_cfg = _get_organizer_config()
    mode = body.get("mode") or org_cfg.get("mode", "smart")
    lib_roots = org_cfg["library_roots"]
    incoming_dir = org_cfg.get("incoming_dir")
    col_policy = org_cfg.get("collision_policy", "skip")

    for item in items:
        if item.get("canonical_title") or item.get("media_type"):
            if not item.get("extension") and item.get("source_path"):
                item["extension"] = os.path.splitext(item["source_path"])[1].lower()
            item["destination_path"] = build_destination_path(item, lib_roots)

    res = execute_organization_plan(items, mode=mode, incoming_dir=incoming_dir, collision_policy=col_policy)
    trigger_post_processing(res)

    return jsonify(res)


@organizer_bp.route("/api/admin/organizer/history", methods=["GET"])
def api_organizer_history():
    """Retrieve history of past organization operations."""
    require_admin()
    if not os.path.exists(ORGANIZER_HISTORY_FILE):
        return jsonify({"batches": []})

    try:
        with open(ORGANIZER_HISTORY_FILE, "r", encoding="utf-8") as f:
            batches = json.load(f)
            if not isinstance(batches, list):
                batches = []
        return jsonify({"batches": batches})
    except Exception as e:
        return jsonify({"error": f"Failed to read history: {e}", "batches": []}), 500


@organizer_bp.route("/api/admin/organizer/undo", methods=["POST"])
def api_organizer_undo():
    """Roll back an organization batch."""
    require_admin()
    body = request.json or {}
    batch_id = body.get("batch_id")
    if not batch_id:
        return jsonify({"error": "batch_id is required"}), 400

    res = undo_batch(batch_id)
    if not res.get("success"):
        return jsonify(res), 400

    return jsonify(res)


def _is_path_allowed(target_path: str, org_cfg: dict) -> bool:
    """Ensure target path resides within incoming directory or configured library roots."""
    target_norm = os.path.abspath(target_path)
    allowed_roots = []
    inc = org_cfg.get("incoming_dir")
    if inc:
        allowed_roots.append(os.path.abspath(inc))
    for roots in (org_cfg.get("available_paths") or {}).values():
        if isinstance(roots, list):
            allowed_roots.extend([os.path.abspath(r) for r in roots if r])
        elif isinstance(roots, str) and roots:
            allowed_roots.append(os.path.abspath(roots))
    for r in (org_cfg.get("library_roots") or {}).values():
        if isinstance(r, str) and r:
            allowed_roots.append(os.path.abspath(r))

    for root in allowed_roots:
        try:
            if os.path.commonpath([root, target_norm]) == root:
                return True
        except (ValueError, OSError):
            continue
    return False


@organizer_bp.route("/api/hooks/downloaded", methods=["POST"])
def api_webhook_downloaded():
    """
    Downloader Webhook endpoint.
    Accepts JSON payload or form data:
      - path: Full path to completed download file or folder
      - name: Optional torrent name / title hint
      - mode: Optional 'smart' | 'move' | 'copy'
    """
    client_ip = request.remote_addr or ""
    is_local_client = client_ip in ("127.0.0.1", "::1", "localhost") or client_ip.startswith("127.")
    if not is_local_client and not is_admin():
        return jsonify({"error": "Administrator privileges or localhost access required"}), 403

    data = request.json if request.is_json else request.form.to_dict()
    target_path = data.get("path")
    if not target_path or not os.path.exists(target_path):
        return jsonify({"error": "Valid target 'path' is required"}), 400

    org_cfg = _get_organizer_config()
    if not _is_path_allowed(target_path, org_cfg):
        return jsonify({"error": "Target path is outside allowed incoming or media library directories"}), 403

    mode = data.get("mode") or org_cfg.get("mode", "smart")
    lib_roots = org_cfg["library_roots"]
    hint_name = data.get("name")

    if os.path.isfile(target_path):
        classified = classify_media_file(target_path, hint_title=hint_name)
        cfg = load_config()
        resolved = resolve_canonical_item(classified, tmdb_api_key=cfg.get("tmdb_api_key"))
        dest = build_destination_path(resolved, lib_roots)
        plan = [{
            "source_path": target_path,
            "destination_path": dest,
            "media_type": resolved["media_type"],
            "request_id": resolved.get("request_id"),
            "subtitles": find_companion_subtitles(target_path)
        }]
    else:
        cfg = load_config()
        plan = scan_incoming_for_preview(target_path, lib_roots, tmdb_api_key=cfg.get("tmdb_api_key"))

    res = execute_organization_plan(plan, mode=mode)
    trigger_post_processing(res)

    return jsonify({
        "success": True,
        "batch_id": res.get("batch_id"),
        "organized_count": res.get("success_count"),
        "failed_count": res.get("failed_count")
    })
