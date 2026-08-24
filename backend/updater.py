"""
updater.py — Self-update system for CapsStream (GitHub Releases based).

Flow:
  1. check_for_update()  → compares local VERSION with the latest GitHub
     release (GitHub API first, raw version.json as fallback).
  2. apply_update()      → downloads the release zip, verifies every entry
     against a strict allow-list, extracts into a staging folder, then moves
     files into place.

SAFETY GUARANTEES
  - NEVER touches: config.json, .env, data/, media/, winpython/, ffmpeg/
  - Only files under the ALLOWED top-level entries can be replaced
  - Zip entries are sanitized (no absolute paths, no "..", no symlinks)

Restart semantics:
  - backend code (app.py, backend/*.py, requirements.txt, start.bat,
    update.bat, VERSION) changed → restart_required = True
  - only static/ + templates/ changed → ui_only = True
"""

import os
import json
import shutil
import zipfile
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
STATE_FILE = os.path.join(BASE_DIR, "data", "updater_state.json")
TMP_DIR = os.path.join(BASE_DIR, "_update_tmp")

# ─── CHANGE THIS to your public repository ───────────────────
GITHUB_REPO = "Unknownplanet40/CapsStream"
# ─────────────────────────────────────────────────────────────

RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Top-level entries an update package may contain
ALLOWED_FILES = {"app.py", "requirements.txt", "start.bat", "update.bat", "VERSION"}
ALLOWED_DIRS = ("backend", "static", "templates")

# Files/dirs an update may NEVER touch (defense in depth — the allow-list
# above already excludes them, this is a second guard)
DENY = ("config.json", ".env", "data", "media", "winpython", "ffmpeg", ".git")

# Files whose change requires an application restart
RESTART_INDICATORS = ("app.py", "backend/", "requirements.txt", "start.bat", "update.bat", "version")


# ─── Small helpers ────────────────────────────────────────────

def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CapsStream-Updater/1.0",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def _read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _touch_last_checked():
    import time
    state = _read_state()
    state["last_checked"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    _write_state(state)
    return state["last_checked"]


# ─── Public API ───────────────────────────────────────────────

def get_local_version():
    """Read the local VERSION file (fallback: 0.0.0)."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def check_for_update():
    """
    Compare the local version against the latest GitHub release.
    Returns dict:
      { status, current, latest, changelog, download_url, last_checked }
      status: "up_to_date" | "available" | "error"
    """
    current = get_local_version()
    result = {
        "status": "error",
        "current": current,
        "latest": None,
        "changelog": "",
        "download_url": None,
        "last_checked": None,
    }

    latest = None
    download_url = None
    changelog = ""

    # Primary: GitHub Releases API (gives changelog body + asset URL)
    try:
        raw = _http_get(RELEASES_API).decode("utf-8")
        rel = json.loads(raw)
        latest = (rel.get("tag_name") or "").lstrip("vV")
        changelog = rel.get("body") or ""
        for asset in rel.get("assets", []):
            if asset.get("name", "").startswith("CapsStream-update-") and asset.get("name", "").endswith(".zip"):
                download_url = asset.get("browser_download_url")
                break
    except Exception as e:
        print(f"[Updater] Releases API unavailable: {e}")

    # Fallback: raw version.json in the repository
    if not latest:
        try:
            raw = _http_get(RAW_VERSION_URL).decode("utf-8")
            vj = json.loads(raw)
            latest = (vj.get("version") or "").strip()
            download_url = vj.get("download_url") or download_url
            changelog = vj.get("changelog") or changelog
        except Exception as e:
            print(f"[Updater] Raw version.json unavailable: {e}")

    # The release asset name is deterministic (built by the Release
    # workflow), so the download URL can always be constructed — even when
    # version.json on the repo predates the release or omits the URL.
    if latest and not download_url:
        download_url = (
            f"https://github.com/{GITHUB_REPO}/releases/download/"
            f"v{latest}/CapsStream-update-{latest}.zip"
        )

    result["latest"] = latest
    result["download_url"] = download_url
    result["changelog"] = changelog

    if latest:
        result["status"] = "available" if latest != current else "up_to_date"
    else:
        result["status"] = "error"

    result["last_checked"] = _touch_last_checked()
    _write_state({**_read_state(), "latest": latest, "status": result["status"]})
    return result


def _entry_allowed(name):
    """Zip-entry allow-list + deny-list + traversal checks."""
    name = name.replace("\\", "/")
    if name.startswith("/") or ".." in name or ":" in name:
        return False
    top = name.split("/", 1)[0]
    if top in DENY:
        return False
    if name in ALLOWED_FILES:
        return True
    if name.endswith("/") and top in ALLOWED_DIRS:
        return True
    if "/" in name and top in ALLOWED_DIRS:
        return True
    return False


def _is_restart_file(name):
    name = name.replace("\\", "/")
    return any(name == ind or name.startswith(ind) for ind in RESTART_INDICATORS)


def apply_update(download_url=None):
    """
    Download the update zip and safely replace allowed files only.
    Returns: { success, message, new_version, restart_required, ui_only }
    """
    current = get_local_version()

    info = check_for_update()
    url = download_url or info.get("download_url")
    latest = info.get("latest")

    if not url:
        return {
            "success": False,
            "message": "No update package available (check your GITHUB_REPO setting or internet connection).",
            "new_version": latest,
            "restart_required": False,
            "ui_only": False,
        }

    os.makedirs(TMP_DIR, exist_ok=True)
    zip_path = os.path.join(TMP_DIR, "update.zip")

    # 1) Download
    try:
        data = _http_get(url, timeout=120)
        with open(zip_path, "wb") as f:
            f.write(data)
    except Exception as e:
        return {
            "success": False,
            "message": f"Download failed: {e}",
            "new_version": latest,
            "restart_required": False,
            "ui_only": False,
        }

    # 2) Inspect & stage
    staging = os.path.join(TMP_DIR, "staging")
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    restart_required = False
    frontend_only = True
    applied = 0

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            allowed_names = [n for n in names if _entry_allowed(n)]

            if not allowed_names:
                return {
                    "success": False,
                    "message": "Update package contained no allowed files.",
                    "new_version": latest,
                    "restart_required": False,
                    "ui_only": False,
                }

            for name in allowed_names:
                # Skip pure directory entries
                if name.endswith("/"):
                    continue
                zf.extract(name, staging)
                applied += 1

                rel = name.replace("\\", "/")
                if _is_restart_file(rel) or not rel.startswith(("static/", "templates/")):
                    restart_required = True
                    frontend_only = False
                else:
                    # static/ or templates/ asset — UI-only change
                    pass

        ui_only = frontend_only and not restart_required

        # 3) Move staged files into the application tree
        for root, _dirs, files in os.walk(staging):
            rel_root = os.path.relpath(root, staging)
            dest_root = BASE_DIR if rel_root == "." else os.path.join(BASE_DIR, rel_root)
            os.makedirs(dest_root, exist_ok=True)
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(dest_root, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                applied = applied  # informational only

    except zipfile.BadZipFile:
        return {
            "success": False,
            "message": "Downloaded update package is corrupted.",
            "new_version": latest,
            "restart_required": False,
            "ui_only": False,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Update failed: {e}",
            "new_version": latest,
            "restart_required": False,
            "ui_only": False,
        }
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    new_version = get_local_version()

    # Persist outcome so /api/system/info can report it after a restart
    state = _read_state()
    state.update({
        "last_applied": state.get("last_checked"),
        "previous_version": current,
        "new_version": new_version,
        "restart_required": restart_required,
        "ui_only": ui_only,
    })
    _write_state(state)

    if restart_required:
        message = "Update installed. Please close CapsStream and run start.bat again."
    else:
        message = "Update installed — reloading the interface."

    return {
        "success": True,
        "message": message,
        "new_version": new_version,
        "restart_required": restart_required,
        "ui_only": ui_only and not restart_required,
    }
