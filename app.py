"""
app.py — CapsStream main Flask application entry point.

Run with: python app.py
Or double-click start.bat
"""

import os
import re
import sys
import time
import json
import threading
import subprocess

# Ensure UTF-8 output encoding and line buffering on Windows so logs flush immediately and emojis/unicode never crash stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# Ensure 'routes' package maps to 'backend.routes' in sys.modules so all legacy/deferred imports resolve
try:
    import backend.routes as _br
    sys.modules.setdefault("routes", _br)
    import backend.routes.middleware as _bm
    sys.modules.setdefault("routes.middleware", _bm)
    import backend.routes.profiles as _bp
    sys.modules.setdefault("routes.profiles", _bp)
    import backend.routes.media as _bme
    sys.modules.setdefault("routes.media", _bme)
    import backend.routes.streaming as _bs
    sys.modules.setdefault("routes.streaming", _bs)
    import backend.routes.library as _bl
    sys.modules.setdefault("routes.library", _bl)
    import backend.routes.social as _bso
    sys.modules.setdefault("routes.social", _bso)
    import backend.routes.admin as _ba
    sys.modules.setdefault("routes.admin", _ba)
except Exception:
    pass

from flask import (
    Flask, jsonify, request, send_file,
    send_from_directory, render_template, session, abort, Response, make_response
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from limits.storage import MemoryStorage

from backend.db import init_db, get_all_profiles
from backend.settings import load_config, save_config, apply_system_file_hiding
from backend.network_inspector import init_network_inspector
from backend.kids_filter import start_background_enrichment
from backend.utils.version import get_app_version, is_dev_mode
from backend.utils.scheduler import read_last_scheduled_scan, write_last_scheduled_scan

# Initialize outgoing HTTP interceptor
init_network_inspector()

# ─── App Constants ─────────────────────────────────────────────────────────────

SERVER_START_TIME = time.time()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Flask App Factory ─────────────────────────────────────────────────────────

app = Flask(__name__, template_folder="templates", static_folder="static")

# Expose BASE_DIR and SERVER_START_TIME to Blueprints via app.config
app.config["BASE_DIR"] = BASE_DIR
app.config["SERVER_START_TIME"] = SERVER_START_TIME


def _load_or_create_secret_key():
    """
    Per-install secret key for session signing, persisted to data/secret_key.
    A unique key per install beats the old hardcoded value: sessions can't be
    forged by anyone who read the source, while still surviving restarts.
    """
    import secrets as _secrets
    key_file = os.path.join(BASE_DIR, "data", "secret_key")
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        if os.path.isfile(key_file):
            with open(key_file, encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        key = _secrets.token_hex(32)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(key)
        return key
    except Exception:
        return _secrets.token_hex(32)


app.secret_key = _load_or_create_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB max upload
# Static assets are cache-busted with ?v=<version> on every template reference.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 12 * 3600

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
    default_limits=["60 per minute"],
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "Too many requests — please slow down.",
        "message": str(e.description if hasattr(e, "description") else e),
    }), 429

# ─── Register Blueprints + Per-Route Limits ────────────────────────────────────

try:
    from backend.routes import register_blueprints
except ImportError:
    from routes import register_blueprints

register_blueprints(app, limiter)

# ─── Per-request DB connection teardown ────────────────────────────────────────

@app.teardown_appcontext
def _teardown_db_conn(exc):
    """Release the per-request SQLite connection stored in Flask g."""
    from backend.db import release_conn
    release_conn()





# ─── API Health / GitHub cache (used by admin blueprint) ───────────────────────

_API_HEALTH_CACHE = {"ts": 0.0, "data": None}
API_HEALTH_TTL_SEC = 120
_GITHUB_PROFILE_CACHE = {"data": None, "fetched_at": 0.0}


def _probe_url(url, timeout=4):
    """Return (reachable, latency_ms). Any HTTP response counts as reachable."""
    import urllib.request
    import urllib.error
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CapsStream-Diagnostics"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)
        return True, int((time.monotonic() - start) * 1000)
    except urllib.error.HTTPError:
        return True, int((time.monotonic() - start) * 1000)
    except Exception:
        return False, None


def _get_api_health(config):
    now = time.time()
    if _API_HEALTH_CACHE["data"] is not None and now - _API_HEALTH_CACHE["ts"] < API_HEALTH_TTL_SEC:
        return _API_HEALTH_CACHE["data"]

    health = {}
    tmdb_key = (config.get("tmdb_api_key") or "").strip()
    if tmdb_key:
        ok, ms = _probe_url(f"https://api.themoviedb.org/3/configuration?api_key={tmdb_key}")
        health["tmdb"] = {"status": "ok" if ok else "error", "latency_ms": ms}
    else:
        health["tmdb"] = {"status": "unconfigured", "latency_ms": None}

    ok, ms = _probe_url("https://api.aniskip.com/v2/skip-times/21/1?types=op&episodeLength=0")
    health["aniskip"] = {"status": "ok" if ok else "error", "latency_ms": ms}

    try:
        os.makedirs(os.path.join(BASE_DIR, "data", "metadata"), exist_ok=True)
        health["poster_cache"] = {"status": "ok", "latency_ms": None}
    except Exception:
        health["poster_cache"] = {"status": "error", "latency_ms": None}

    _API_HEALTH_CACHE["data"] = health
    _API_HEALTH_CACHE["ts"] = now
    return health


def _get_github_profile():
    """Cached GitHub profile — refreshed at most once per hour."""
    now = time.time()
    if _GITHUB_PROFILE_CACHE["data"] and now - _GITHUB_PROFILE_CACHE["fetched_at"] < 3600:
        return _GITHUB_PROFILE_CACHE["data"]
    profile = {
        "login": "Unknownplanet40",
        "name": "<Caps />",
        "avatar_url": "https://avatars.githubusercontent.com/u/57881134?v=4",
        "html_url": "https://github.com/Unknownplanet40",
        "bio": "I debug life the same way I debug code with patience, caffeine, and a bit of panic.",
        "location": "Philippines",
        "public_repos": 20, "followers": 13, "following": 8, "created_year": "2019"
    }
    try:
        import urllib.request
        req = urllib.request.Request("https://api.github.com/users/Unknownplanet40", headers={"User-Agent": "CapsStream"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            gh_data = json.loads(resp.read().decode())
            if gh_data and "avatar_url" in gh_data:
                profile["name"] = gh_data.get("name") or gh_data.get("login") or "<Caps />"
                profile["login"] = gh_data.get("login") or "Unknownplanet40"
                profile["avatar_url"] = gh_data.get("avatar_url") or profile["avatar_url"]
                profile["html_url"] = gh_data.get("html_url") or profile["html_url"]
                profile["bio"] = gh_data.get("bio") or profile["bio"]
                profile["location"] = gh_data.get("location") or profile["location"]
                profile["public_repos"] = gh_data.get("public_repos", 20)
                profile["followers"] = gh_data.get("followers", 13)
                profile["following"] = gh_data.get("following", 8)
                created_raw = gh_data.get("created_at") or ""
                if len(created_raw) >= 4:
                    profile["created_year"] = created_raw[:4]
    except Exception:
        pass
    _GITHUB_PROFILE_CACHE["data"] = profile
    _GITHUB_PROFILE_CACHE["fetched_at"] = now
    return profile


# ─── Main Page & Static Routes ─────────────────────────────────────────────────

_BOOT_TS = int(time.time())


@app.route("/")
@limiter.exempt
def index():
    t_val = int(time.time()) if is_dev_mode() else _BOOT_TS
    resp = make_response(render_template("index.html", version=get_app_version(), t=t_val))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/.well-known/appspecific/com.chrome.devtools.json")
@limiter.exempt
def chrome_devtools_json():
    return jsonify({})


@app.route("/sw.js")
@limiter.exempt
def service_worker():
    resp = make_response(send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js"))
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.route("/manifest.webmanifest")
@app.route("/manifest.json")
@limiter.exempt
def web_manifest():
    manifest_path = os.path.join(BASE_DIR, "static", "manifest.webmanifest")
    if not os.path.isfile(manifest_path):
        manifest_path = os.path.join(BASE_DIR, "static", "manifest.json")
    if os.path.isfile(manifest_path):
        resp = make_response(send_file(manifest_path, mimetype="application/manifest+json"))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return jsonify({
        "name": "CapsStream",
        "short_name": "CapsStream",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#050508",
        "theme_color": "#050508",
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ]
    })


@app.route("/offline.html")
@limiter.exempt
def offline_page():
    resp = make_response(render_template("offline.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/favicon.ico")
@limiter.exempt
def favicon():
    fav_path = os.path.join(BASE_DIR, "static", "img", "favicon.png")
    if os.path.exists(fav_path):
        return send_file(fav_path, mimetype="image/png")
    return "", 204


@app.route("/offline-page")
@limiter.exempt
def serve_offline_page():
    return send_from_directory(app.static_folder, "offline.html")


# ─── Static Media (images & avatars) ──────────────────────────────────────────

import requests as _requests

_IMAGE_INFLIGHT_LOCK = threading.Lock()
_IMAGE_INFLIGHT = set()
_IMAGE_DOWNLOAD_SEM = threading.BoundedSemaphore(4)


def _download_image_background(size, tmdb_file, filename, img_dir, img_path):
    try:
        with _IMAGE_DOWNLOAD_SEM:
            url = f"https://image.tmdb.org/t/p/{size}/{tmdb_file}"
            r = _requests.get(url, timeout=10)
            if r.status_code == 200:
                os.makedirs(img_dir, exist_ok=True)
                with open(img_path, "wb") as f:
                    f.write(r.content)
    except Exception as e:
        print(f"[Image Server] Background download failed for {filename}: {e}")
    finally:
        with _IMAGE_INFLIGHT_LOCK:
            _IMAGE_INFLIGHT.discard(filename)


@app.route("/metadata/images/<path:filename>")
@limiter.exempt
def serve_metadata_image(filename):
    img_dir = os.path.join(BASE_DIR, "data", "metadata", "images")
    img_path = os.path.join(img_dir, filename)

    if os.path.isfile(img_path):
        resp = send_file(img_path, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp

    parts = filename.split("_", 1)
    if len(parts) == 2:
        size, tmdb_file = parts[0], parts[1]
        should_spawn = False
        with _IMAGE_INFLIGHT_LOCK:
            if filename not in _IMAGE_INFLIGHT:
                _IMAGE_INFLIGHT.add(filename)
                should_spawn = True
        if should_spawn:
            threading.Thread(
                target=_download_image_background,
                args=(size, tmdb_file, filename, img_dir, img_path),
                daemon=True, name=f"img-dl-{filename[:20]}"
            ).start()

    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450">
      <rect width="300" height="450" fill="#181824"/>
      <g transform="translate(118, 175) scale(1.6)" fill="#444455">
        <path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/>
      </g>
      <text x="50%" y="60%" dominant-baseline="middle" text-anchor="middle" fill="#888" font-family="sans-serif" font-size="14">Loading...</text>
    </svg>"""
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=5"})


@app.route("/metadata/avatars/<path:filename>")
@limiter.exempt
def serve_avatar_image(filename):
    avatars_dir = os.path.join(BASE_DIR, "data", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    img_path = os.path.join(avatars_dir, filename)
    if not os.path.isfile(img_path):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 24 24" fill="none">
          <rect width="24" height="24" fill="#1f1f2e"/>
          <circle cx="12" cy="8" r="4" fill="#666"/>
          <path d="M4 20c0-4 4-6 8-6s8 2 8 6" fill="#666"/>
        </svg>"""
        return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=60"})
    resp = send_from_directory(avatars_dir, filename)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


# ─── Scheduled Scan helpers (used by admin blueprint and __main__) ─────────────

def _scan_scheduler_loop():
    from backend.settings import load_config as _lc
    from backend.scanner import get_scan_status, scan_library
    from backend.routes.middleware import has_active_profile_session
    if read_last_scheduled_scan() <= 0:
        write_last_scheduled_scan(time.time())
    while True:
        try:
            interval = float((_lc().get("library") or {}).get("scan_interval_hours") or 0)
            if interval > 0 and not get_scan_status()["running"]:
                if not has_active_profile_session():
                    write_last_scheduled_scan(time.time())
                    time.sleep(600)
                    continue
                last = read_last_scheduled_scan()
                if last <= 0:
                    write_last_scheduled_scan(time.time())
                elif time.time() - last >= interval * 3600:
                    if not get_scan_status()["running"]:
                        print(f"[Scheduler] Interval {interval}h elapsed — starting scheduled scan")
                        write_last_scheduled_scan(time.time())
                        scan_library()
        except Exception as e:
            print(f"[Scheduler] Scan scheduler error: {e}")
        time.sleep(600)


def start_scan_scheduler():
    threading.Thread(target=_scan_scheduler_loop, daemon=True).start()


# ─── Auto-Backup ───────────────────────────────────────────────────────────────

AUTO_BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
AUTO_BACKUP_KEEP = 4


def _create_auto_backup():
    import zipfile
    from backend.settings import CONFIG_PATH
    from backend.db import get_conn
    db_path = os.path.join(BASE_DIR, "data", "capsstream.db")
    if not os.path.isfile(db_path):
        return None
    try:
        conn = get_conn()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        pass
    os.makedirs(AUTO_BACKUP_DIR, exist_ok=True)
    name = f"autobackup-{time.strftime('%Y%m%d-%H%M')}.zip"
    path = os.path.join(AUTO_BACKUP_DIR, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.isfile(CONFIG_PATH):
            zf.write(CONFIG_PATH, "config.json")
        zf.write(db_path, "data/capsstream.db")
        avatars_dir = os.path.join(BASE_DIR, "data", "avatars")
        if os.path.isdir(avatars_dir):
            for root, _dirs, files in os.walk(avatars_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    arc = os.path.relpath(fp, BASE_DIR)
                    try:
                        zf.write(fp, arc)
                    except Exception:
                        pass
    backups = sorted(f for f in os.listdir(AUTO_BACKUP_DIR) if f.startswith("autobackup-") and f.endswith(".zip"))
    for old in backups[:-AUTO_BACKUP_KEEP]:
        try:
            os.remove(os.path.join(AUTO_BACKUP_DIR, old))
        except OSError:
            pass
    return path


def _auto_backup_loop():
    cfg = load_config()
    backup_cfg = cfg.get("backup") or {}
    if backup_cfg.get("auto_backup") is False:
        print("[Backup] Auto-backup disabled in settings")
        return
    interval_hours = int(backup_cfg.get("backup_interval_hours", 168) or 168)
    while True:
        try:
            path = _create_auto_backup()
            if path:
                print(f"[Backup] Auto-backup created: {os.path.basename(path)}")
        except Exception as e:
            print(f"[Backup] Auto-backup failed: {e}")
        time.sleep(interval_hours * 3600)


def start_auto_backups():
    threading.Thread(target=_auto_backup_loop, daemon=True, name="auto-backup").start()


# ─── DB Maintenance Daemon ─────────────────────────────────────────────────────

def _prune_old_logs():
    log_name_re = re.compile(r"^capsstream_\d{8}\.log$")
    log_dir = os.path.join(BASE_DIR, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        cutoff = time.time() - 14 * 86400
        removed = 0
        for name in os.listdir(log_dir):
            fp = os.path.join(log_dir, name)
            if log_name_re.match(name) and os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
                removed += 1
        if removed:
            print(f"[Maintenance] Pruned {removed} old log file(s)")
    except Exception as e:
        print(f"[Maintenance] Log prune failed: {e}")
    for legacy in ("_finish_update_fallback.bat", "_finish_update.bat", "_finish_update_helper.py"):
        fp = os.path.join(BASE_DIR, legacy)
        if os.path.isfile(fp):
            try:
                os.remove(fp)
            except OSError:
                pass


def _db_maintenance_daemon():
    from backend.db import get_conn
    time.sleep(300)
    while True:
        try:
            conn = get_conn()
            conn.execute("PRAGMA optimize")
            row = conn.execute("PRAGMA quick_check").fetchone()
            status = row[0] if row else "unknown"
            conn.close()
            print(f"[DB] Weekly maintenance done (quick_check: {status})")
        except Exception as e:
            print(f"[DB] Maintenance failed: {e}")
        time.sleep(7 * 86400)


# ─── Single-Instance Guard ─────────────────────────────────────────────────────

def _port_owner_pid(port):
    try:
        from backend.proc_utils import CREATE_NO_WINDOW
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, creationflags=CREATE_NO_WINDOW,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
                return int(parts[-1])
    except Exception as e:
        print(f"[Startup] Could not inspect port {port}: {e}")
    return None


def _process_cmdline(pid):
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
        return out
    except Exception:
        return ""


def _ensure_single_instance(host, port):
    owner = _port_owner_pid(port)
    if not owner or owner == os.getpid():
        return
    cmdline = _process_cmdline(owner).lower()
    is_ours = (
        "app.py" in cmdline
        and os.path.normcase(BASE_DIR) in cmdline.replace("/", "\\")
        and "python" in cmdline
    )
    if is_ours:
        print(f"[Startup] Port {port} is held by a leftover CapsStream instance (pid {owner}) — terminating it.")
        subprocess.run(["taskkill", "/PID", str(owner), "/F"], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(10):
            time.sleep(0.5)
            if not _port_owner_pid(port):
                break
    else:
        print(f"\n  [ERROR] Port {port} is already in use by another program (pid {owner}).")
        if cmdline:
            print(f"     Command line: {cmdline[:200]}")
        print(f"     CapsStream cannot start. Free the port or change 'port' in config.json.\n")
        sys.exit(1)


# ─── SSL ───────────────────────────────────────────────────────────────────────

def _generate_self_signed_cert(cert_path, key_path, host="127.0.0.1"):
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime, ipaddress

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "CapsStream"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CapsStream Local Server"),
        ])
        san_list = [x509.DNSName("localhost")]
        try:
            san_list.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san_list.append(x509.DNSName(host))

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(issuer).public_key(key.public_key()).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.now(datetime.timezone.utc)
        ).not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
        ).add_extension(x509.SubjectAlternativeName(san_list), critical=False).sign(key, hashes.SHA256())

        os.makedirs(os.path.dirname(cert_path), exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception as e:
        print(f"  [!] SSL certificate auto-generation failed: {e}")
        return False


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  CapsStream — Starting up")
    print("=" * 50)

    init_db()
    start_scan_scheduler()

    from backend.scanner import start_intro_detection_pass
    threading.Timer(120, start_intro_detection_pass).start()
    threading.Timer(90, start_background_enrichment).start()

    start_auto_backups()
    _prune_old_logs()
    threading.Thread(target=_db_maintenance_daemon, daemon=True, name="db-maintenance").start()

    cfg = load_config()
    apply_system_file_hiding()
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8000)

    _ensure_single_instance(host, port)
    try:
        with open(os.path.join(BASE_DIR, "data", "server.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"\n  [!] WARNING: The server is bound to a non-localhost address ({host}) -- "
            "anyone on your local network can access CapsStream.\n"
            "      Set host back to '127.0.0.1' in config.json if you want to restrict access to this PC."
        )

    use_ssl = cfg.get("ssl", False)
    ssl_context = None
    if use_ssl:
        ssl_dir = os.path.join(BASE_DIR, "data", "ssl")
        cert_path = os.path.join(ssl_dir, "cert.pem")
        key_path = os.path.join(ssl_dir, "key.pem")
        if not (os.path.exists(cert_path) and os.path.exists(key_path)):
            _generate_self_signed_cert(cert_path, key_path, host)
        ssl_context = (cert_path, key_path)

    proto = "https" if ssl_context else "http"
    print(f"\n  ==========================================================")
    print(f"   CapsStream Server running at: {proto}://{host}:{port}")
    print(f"   TO STOP THE SERVER: Press Ctrl+C in this window")
    print(f"  ==========================================================\n")

    app.run(host=host, port=port, debug=False, threaded=True, ssl_context=ssl_context)
