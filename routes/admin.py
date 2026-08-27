# -*- coding: utf-8 -*-
"""
routes/admin.py — Settings, system info, logs, scan, backup, restore, updates.
"""
import os
import re
import time
import shutil
import threading

from flask import Blueprint, jsonify, request, send_file, abort, current_app, session

from routes.middleware import require_admin, is_admin, require_profile

admin_bp = Blueprint("admin", __name__)

LOG_NAME_RE = re.compile(r"^capsstream_\d{8}\.log$")
LOG_RETENTION_DAYS = 14


def _safe_log_path(name, log_dir):
    if not name or not LOG_NAME_RE.match(name.strip()):
        return None
    return os.path.join(log_dir, name.strip())


def _get_log_dir():
    return os.path.join(current_app.config["BASE_DIR"], "logs")


def get_app_version():
    try:
        with open(os.path.join(current_app.config["BASE_DIR"], "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "2.0.0.0"
    except Exception:
        return "2.0.0.0"


# ─── Settings ─────────────────────────────────────────────────────────────────

@admin_bp.route("/api/settings", methods=["GET"])
def api_get_settings():
    from backend.settings import load_config
    return jsonify(load_config())


@admin_bp.route("/api/settings", methods=["POST"])
def api_post_settings():
    from backend.settings import load_config, save_config
    require_profile()
    data = request.json or {}
    if not is_admin():
        cfg = load_config()
        if "player" in data and isinstance(data["player"], dict):
            cfg["player"] = data["player"]
            ok, result = save_config(cfg)
            if ok:
                return jsonify({"ok": True, "config": result})
            return jsonify({"error": result}), 500
        return jsonify({"error": "Administrator privileges required to change system settings"}), 403

    ok, result = save_config(data)
    if ok:
        if "library" in data and "scan_interval_hours" in (data.get("library") or {}):
            _write_last_scheduled_scan(time.time())
        return jsonify({"ok": True, "config": result})
    return jsonify({"error": result}), 500


@admin_bp.route("/api/settings/test-api", methods=["POST"])
def api_test_api_key():
    require_admin()
    from backend.settings import test_api_key
    data = request.json or {}
    provider = data.get("provider", "")
    key = data.get("key", "")
    ok, message = test_api_key(provider, key)
    return jsonify({"ok": ok, "message": message})


@admin_bp.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok"})


# ─── Cache ────────────────────────────────────────────────────────────────────

@admin_bp.route("/api/system/cache", methods=["GET"])
def api_cache_info():
    from backend.settings import get_cache_info
    return jsonify(get_cache_info())


@admin_bp.route("/api/system/cache", methods=["DELETE"])
def api_clear_cache():
    require_admin()
    from backend.settings import clear_cache
    cleared = clear_cache()
    return jsonify({"ok": True, "cleared": cleared})


@admin_bp.route("/api/system/reset", methods=["POST"])
def api_system_reset():
    require_admin()
    data = request.json or {}
    clear_media = data.get("clear_media_files", False)
    from backend.settings import reset_application
    reset_application(clear_media_files=clear_media)
    session.clear()
    return jsonify({"ok": True, "message": "Application reset complete"})


# ─── System Shutdown / Restart ────────────────────────────────────────────────

def _graceful_shutdown():
    def _shutdown():
        import time as _t
        try:
            func = request.environ.get("werkzeug.server.shutdown")
            if func:
                func()
        except Exception:
            pass
        _t.sleep(1.0)
        try:
            from backend.db import get_conn
            conn = get_conn()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
        except Exception as e:
            print(f"[Shutdown] SQLite checkpoint failed: {e}")
        os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()


@admin_bp.route("/api/system/shutdown", methods=["POST"])
def api_system_shutdown():
    require_admin()
    _graceful_shutdown()
    return jsonify({"ok": True, "message": "Server shutting down cleanly"})


@admin_bp.route("/api/system/restart-after-update", methods=["POST"])
def api_restart_after_update():
    require_admin()
    from backend.updater import spawn_restart_helper
    try:
        spawn_restart_helper()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not spawn restart helper: {e}"}), 500
    _graceful_shutdown()
    return jsonify({"ok": True, "message": "Restarting to finish the update"})


# ─── Updates ──────────────────────────────────────────────────────────────────

@admin_bp.route("/api/system/check-update", methods=["GET"])
def api_check_update():
    from backend.updater import check_for_update
    try:
        result = check_for_update()
        result["version"] = get_app_version()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "version": get_app_version()}), 500


@admin_bp.route("/api/system/apply-update", methods=["POST"])
def api_apply_update():
    require_admin()
    from backend.updater import apply_update
    data = request.json or {}
    try:
        result = apply_update(data.get("download_url"), force=bool(data.get("force")))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "restart_required": False, "ui_only": False}), 500


@admin_bp.route("/api/system/update-progress", methods=["GET"])
def api_update_progress():
    from backend.updater import get_update_progress
    return jsonify(get_update_progress())


# ─── Logs ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/api/system/logs", methods=["GET"])
def api_system_logs():
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    files = []
    try:
        for name in os.listdir(log_dir):
            fp = _safe_log_path(name, log_dir)
            if fp and os.path.isfile(fp):
                files.append({
                    "name": name,
                    "size": os.path.getsize(fp),
                    "modified": int(os.path.getmtime(fp)),
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    files.sort(key=lambda f: f["modified"], reverse=True)
    return jsonify(files)


@admin_bp.route("/api/system/logs/tail", methods=["GET"])
def api_system_log_tail():
    log_dir = _get_log_dir()
    fp = _safe_log_path(request.args.get("file") or "", log_dir)
    if not fp:
        return jsonify({"error": "Invalid log file name"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        max_bytes = min(262144, max(1024, int(request.args.get("max_bytes", 32768))))
    except (TypeError, ValueError):
        max_bytes = 32768

    if not os.path.isfile(fp):
        return jsonify({"data": "", "offset": 0, "size": 0, "reset": True})

    size = os.path.getsize(fp)
    if offset > size:
        return jsonify({"data": "", "offset": 0, "size": size, "reset": True})

    if offset == 0:
        start = max(0, size - max_bytes)
        with open(fp, "rb") as f:
            f.seek(start)
            data = f.read().decode("utf-8", errors="replace")
        if start > 0:
            nl = data.find("\n")
            if nl != -1:
                data = data[nl + 1:]
        return jsonify({"data": data, "offset": size, "size": size, "reset": False})

    with open(fp, "rb") as f:
        f.seek(offset)
        chunk = f.read(max_bytes)
    data = chunk.decode("utf-8", errors="replace")
    new_offset = offset + len(chunk)
    if new_offset < size:
        nl = data.rfind("\n")
        if nl != -1:
            data = data[:nl + 1]
            new_offset = offset + len(data.encode("utf-8"))
    return jsonify({"data": data, "offset": new_offset, "size": size, "reset": False})


@admin_bp.route("/api/system/logs/download", methods=["GET"])
def api_system_log_download():
    log_dir = _get_log_dir()
    fp = _safe_log_path(request.args.get("file") or "", log_dir)
    if not fp or not os.path.isfile(fp):
        abort(404)
    return send_file(fp, as_attachment=True, download_name=os.path.basename(fp))


# ─── Library Scan ─────────────────────────────────────────────────────────────

_scan_thread = None
_SCAN_SCHEDULE_FILE = None


def _get_scan_schedule_file():
    global _SCAN_SCHEDULE_FILE
    if _SCAN_SCHEDULE_FILE is None:
        _SCAN_SCHEDULE_FILE = os.path.join(current_app.config["BASE_DIR"], "data", "scan_schedule.json")
    return _SCAN_SCHEDULE_FILE


def _write_last_scheduled_scan(ts):
    import json
    try:
        sf = os.path.join(current_app.config["BASE_DIR"], "data", "scan_schedule.json")
        os.makedirs(os.path.dirname(sf), exist_ok=True)
        with open(sf, "w", encoding="utf-8") as f:
            json.dump({"last_run": ts}, f)
    except Exception:
        pass


@admin_bp.route("/api/scan", methods=["POST"])
def api_scan():
    from routes.media import bust_home_cache
    require_admin()
    global _scan_thread
    from backend.scanner import scan_library, get_scan_status
    status = get_scan_status()
    if status["running"]:
        return jsonify({"ok": True, "already_running": True, "status": status})

    def run_scan():
        from backend.kids_filter import start_background_enrichment
        scan_library()
        bust_home_cache()
        start_background_enrichment()

    _scan_thread = threading.Thread(target=run_scan, daemon=True)
    _scan_thread.start()
    return jsonify({"ok": True, "message": "Library scan started"})


@admin_bp.route("/api/scan/status", methods=["GET"])
def api_scan_status():
    from backend.scanner import get_scan_status
    return jsonify(get_scan_status())


# ─── Backup & Restore ─────────────────────────────────────────────────────────

@admin_bp.route("/api/system/backup", methods=["GET"])
def api_system_backup():
    require_admin()
    import zipfile
    from backend.settings import CONFIG_PATH
    BASE_DIR = current_app.config["BASE_DIR"]
    include_metadata = request.args.get("include_metadata") in ("1", "true")
    db_path = os.path.join(BASE_DIR, "data", "capsstream.db")
    if not os.path.isfile(db_path):
        return jsonify({"error": "Database not found"}), 404

    backup_name = f"CapsStream-backup-{time.strftime('%Y%m%d-%H%M')}.zip"
    zip_path = os.path.join(BASE_DIR, "_backup_tmp.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.isfile(CONFIG_PATH):
                zf.write(CONFIG_PATH, "config.json")
            zf.write(db_path, "data/capsstream.db")
            if include_metadata:
                meta_dir = os.path.join(BASE_DIR, "data", "metadata")
                for root, _dirs, files in os.walk(meta_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        arc = os.path.relpath(fp, BASE_DIR)
                        try:
                            zf.write(fp, arc)
                        except Exception:
                            continue
        return send_file(zip_path, as_attachment=True, download_name=backup_name, mimetype="application/zip")
    finally:
        try:
            os.remove(zip_path)
        except Exception:
            pass


@admin_bp.route("/api/system/restore", methods=["POST"])
def api_system_restore():
    require_admin()
    import zipfile
    from backend.settings import CONFIG_PATH
    BASE_DIR = current_app.config["BASE_DIR"]

    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Please upload a CapsStream backup .zip file"}), 400

    restore_cfg = False
    restore_db = False
    staged_db = None

    try:
        file.save(file.filename and os.path.join(BASE_DIR, "_restore_tmp.zip"))
        tmp_zip = os.path.join(BASE_DIR, "_restore_tmp.zip")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            names = zf.namelist()
            for n in names:
                base = os.path.basename(n)
                if base == "config.json" and not restore_cfg:
                    pre_dir = os.path.join(BASE_DIR, "data", "pre_restore")
                    os.makedirs(pre_dir, exist_ok=True)
                    if os.path.isfile(CONFIG_PATH):
                        shutil.copy2(CONFIG_PATH, os.path.join(pre_dir, f"config.{time.strftime('%Y%m%d-%H%M%S')}.json"))
                    zf.extract(n, BASE_DIR)
                    restore_cfg = True
                elif base == "capsstream.db" and not restore_db:
                    from backend.updater import PENDING_DIR, _write_pending_manifest
                    rel = "data/capsstream.db"
                    pend = os.path.join(PENDING_DIR, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(pend), exist_ok=True)
                    with zf.open(n) as src, open(pend, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    staged_db = rel
                    restore_db = True
        os.remove(tmp_zip)
    except zipfile.BadZipFile:
        return jsonify({"error": "That file is not a valid backup zip"}), 400
    except Exception as e:
        return jsonify({"error": f"Restore failed: {e}"}), 500

    if staged_db:
        from backend.updater import _write_pending_manifest
        _write_pending_manifest([staged_db])

    if not restore_cfg and not restore_db:
        return jsonify({"error": "No config.json or capsstream.db found in that backup"}), 400

    return jsonify({
        "ok": True,
        "restored_config": restore_cfg,
        "restored_database": restore_db,
        "message": (
            "Settings restored. " if restore_cfg else ""
        ) + (
            "Database staged — it will be applied on the next server start (close CapsStream and run start.bat)."
            if restore_db else ""
        ),
    })


# ─── System Info ──────────────────────────────────────────────────────────────

@admin_bp.route("/api/system/info", methods=["GET"])
def api_system_info():
    import sys, platform, json
    BASE_DIR = current_app.config["BASE_DIR"]
    SERVER_START_TIME = current_app.config["SERVER_START_TIME"]
    from backend.db import DB_PATH, get_conn, get_all_profiles
    from backend.updater import _read_state as _updater_state

    db_size_str = "0 KB"
    if os.path.exists(DB_PATH):
        sz = os.path.getsize(DB_PATH)
        if sz >= 1024 * 1024:
            db_size_str = f"{sz / (1024 * 1024):.1f} MB"
        else:
            db_size_str = f"{sz / 1024:.1f} KB"

    ffmpeg_path = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")
    has_ffmpeg = os.path.exists(ffmpeg_path)
    has_ffprobe = os.path.exists(os.path.join(BASE_DIR, "ffmpeg", "bin", "ffprobe.exe"))

    movies_count = series_count = anime_count = 0
    skip_markers_count = 0
    try:
        conn = get_conn()
        for r in conn.execute("SELECT type, COUNT(*) FROM media GROUP BY type").fetchall():
            if r[0] == "movie":
                movies_count = r[1]
            elif r[0] == "series":
                series_count = r[1]
            elif r[0] == "anime":
                anime_count = r[1]
        manual_marker_ids = {
            row[0] for row in conn.execute("""
                SELECT id FROM media WHERE
                  (recap_start  IS NOT NULL AND recap_start  > 0) OR
                  (intro_start  IS NOT NULL AND intro_start  > 0) OR
                  (outro_start  IS NOT NULL AND outro_start  > 0) OR
                  (preview_start IS NOT NULL AND preview_start > 0)
            """).fetchall()
        }
        all_media_ids = {row[0] for row in conn.execute("SELECT id FROM media").fetchall()}
        auto_marker_ids = set()
        skip_cache_dir = os.path.join(BASE_DIR, "data", "metadata", "skip_times")
        if os.path.isdir(skip_cache_dir):
            for fname in os.listdir(skip_cache_dir):
                base = os.path.splitext(fname)[0]
                if base.isdigit():
                    auto_marker_ids.add(int(base))
        skip_markers_count = len(manual_marker_ids | (auto_marker_ids & all_media_ids))
        conn.close()
    except Exception:
        pass
    total_count = movies_count + series_count + anime_count

    from backend.settings import load_config
    config = load_config()

    # API health (cached in app.py level)
    from app import _get_api_health, _get_github_profile
    api_health = _get_api_health(config)
    github_profile = _get_github_profile()

    # Storage
    total_bytes, movies_bytes, series_bytes, anime_bytes = 0, 0, 0, 0
    try:
        conn = get_conn()
        res = conn.execute("""
            SELECT
                COALESCE(SUM(file_size), 0) as total_bytes,
                COALESCE(SUM(CASE WHEN type='movie' THEN file_size ELSE 0 END), 0) as movies_bytes,
                COALESCE(SUM(CASE WHEN type='series' THEN file_size ELSE 0 END), 0) as series_bytes,
                COALESCE(SUM(CASE WHEN type='anime' THEN file_size ELSE 0 END), 0) as anime_bytes
            FROM media
        """).fetchone()
        conn.close()
        if res:
            total_bytes = res[0] or 0
            movies_bytes = res[1] or 0
            series_bytes = res[2] or 0
            anime_bytes = res[3] or 0
    except Exception:
        pass

    def format_bytes(b):
        if not b or b <= 0:
            return "0 GB"
        tb = b / (1024 ** 4)
        if tb >= 1.0:
            return f"{tb:.2f} TB" if tb < 10 else f"{tb:.1f} TB"
        gb = b / (1024 ** 3)
        if gb >= 1.0:
            return f"{gb:.2f} GB" if gb < 10 else f"{gb:.1f} GB"
        mb = b / (1024 ** 2)
        if mb >= 1.0:
            return f"{mb:.1f} MB"
        return f"{b / 1024:.0f} KB"

    storage_info = {
        "total_size": format_bytes(total_bytes), "total_bytes": total_bytes,
        "movies_size": format_bytes(movies_bytes), "series_size": format_bytes(series_bytes),
        "anime_size": format_bytes(anime_bytes),
        "movies_pct": round((movies_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
        "series_pct": round((series_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
        "anime_pct": round((anime_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
    }

    # Uptime
    uptime_sec = int(time.time() - SERVER_START_TIME)
    uptime_h = uptime_sec // 3600
    uptime_m = (uptime_sec % 3600) // 60
    uptime_s = uptime_sec % 60
    uptime_str = f"{uptime_h}h {uptime_m}m {uptime_s}s" if uptime_h > 0 else f"{uptime_m}m {uptime_s}s"

    # RAM
    ram_info = {"load_pct": 0, "total_gb": 0, "free_gb": 0, "used_gb": 0}
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong)
            ]
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            tot_gb = round(ms.ullTotalPhys / (1024**3), 1)
            free_gb = round(ms.ullAvailPhys / (1024**3), 1)
            ram_info = {"load_pct": ms.dwMemoryLoad, "total_gb": tot_gb, "free_gb": free_gb, "used_gb": round(tot_gb - free_gb, 1)}
    except Exception:
        pass

    db_metrics = {"profiles_count": len(get_all_profiles() or []), "favorites_count": 0, "progress_count": 0, "skip_markers_count": skip_markers_count}
    try:
        from backend.db import get_db
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM progress")
            db_metrics["progress_count"] = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM favorites")
            db_metrics["favorites_count"] = c.fetchone()[0] or 0
    except Exception:
        pass

    # Drives
    drive_roots = set()
    try:
        import ctypes as _c
        if hasattr(os, "listdrives"):
            drive_roots = {d + "\\" for d in os.listdrives()}
        else:
            bitmask = _c.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive_roots.add(chr(ord("A") + i) + ":\\")
    except Exception:
        drive_roots = {os.path.splitdrive(BASE_DIR)[0] + "\\"}

    disk_info = []
    for drive in sorted(drive_roots):
        try:
            usage = shutil.disk_usage(drive)
            if usage.total <= 0:
                continue
            disk_info.append({
                "drive": drive,
                "free_gb": round(usage.free / 1024**3, 1),
                "total_gb": round(usage.total / 1024**3, 1),
                "used_pct": round(100 * usage.used / usage.total) if usage.total else 0,
            })
        except Exception:
            continue

    from app import is_dev_mode
    return jsonify({
        "version": get_app_version(),
        "is_dev": is_dev_mode(),
        "app_name": "CapsStream",
        "remote_exposed": (config.get("host", "127.0.0.1") not in ("127.0.0.1", "localhost", "::1")),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
        "os_name": os.name,
        "server_uptime": uptime_str,
        "database_size": db_size_str,
        "has_ffmpeg": has_ffmpeg,
        "has_ffprobe": has_ffprobe,
        "ram_info": ram_info,
        "db_metrics": db_metrics,
        "api_health": api_health,
        "github_profile": github_profile,
        "server_addr": f"{config.get('host', '127.0.0.1')}:{config.get('port', 8000)}",
        "last_checked": _updater_state().get("last_checked"),
        "latest_version": _updater_state().get("latest"),
        "storage_info": storage_info,
        "disk_info": disk_info,
        "media_counts": {"total": total_count, "movies": movies_count, "series": series_count, "anime": anime_count}
    })


@admin_bp.route("/api/system/browse-folder", methods=["POST"])
def api_system_browse_folder():
    from backend.settings import browse_folder_dialog
    folder_path = browse_folder_dialog()
    if folder_path:
        return jsonify({"ok": True, "path": folder_path})
    return jsonify({"ok": False, "cancelled": True}), 200


@admin_bp.route("/api/system/validate-paths", methods=["POST"])
def api_system_validate_paths():
    data = request.json or {}
    paths_list = data.get("paths", [])
    from backend.settings import validate_media_paths
    results = validate_media_paths(paths_list)
    return jsonify(results)
