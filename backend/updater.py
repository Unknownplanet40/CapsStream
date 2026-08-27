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
import re
import json
import time
import shutil
import zipfile
import filecmp
import urllib.request
import urllib.error
import threading
import hashlib
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
STATE_FILE = os.path.join(BASE_DIR, "data", "updater_state.json")
TMP_DIR = os.path.join(BASE_DIR, "_update_tmp")

# Live progress of a running update, polled by the Settings UI via
# /api/system/update-progress.
PROGRESS_FILE = os.path.join(BASE_DIR, "data", "update_progress.json")

# Originals of files replaced by an update are parked here (timestamped,
# newest 3 kept) so a bad release can always be rolled back by hand.
PRE_UPDATE_DIR = os.path.join(BASE_DIR, "data", "pre_update")
PRE_UPDATE_KEEP = 3

# Update files that couldn't be replaced while the server was running
# (the entry script app.py stays open) are parked here and swapped in by
# start.bat BEFORE the next launch.
PENDING_DIR = os.path.join(BASE_DIR, "data", "pending_update")
PENDING_MANIFEST = os.path.join(PENDING_DIR, "manifest.json")

# Only one update may run at a time
_UPDATE_LOCK = threading.Lock()

# ─── CHANGE THIS to your public repository ───────────────────
GITHUB_REPO = "Unknownplanet40/CapsStream"
# ─────────────────────────────────────────────────────────────

RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Top-level entries an update package may contain
ALLOWED_FILES = {
    "app.py", "requirements.txt", "start.bat", "update.bat", "VERSION",
    "silent_launcher.py", "Start CapsStream Silent.vbs",
}
ALLOWED_DIRS = ("backend", "routes", "static", "templates")

# Files/dirs an update may NEVER touch (defense in depth — the allow-list
# above already excludes them, this is a second guard)
DENY = ("config.json", ".env", "data", "media", "winpython", "ffmpeg", ".git")

# Files whose change requires an application restart.
# NOTE: VERSION is intentionally excluded — get_app_version() reads it live
# on every request, so version bumps alone never need a restart.
RESTART_INDICATORS = ("app.py", "backend/", "routes/", "requirements.txt", "start.bat", "update.bat")

# Commit-message override: appending [restart] (or +restart) to a commit
# forces the restart prompt even when file comparison finds no backend change.
RESTART_HINT_RE = re.compile(r"\[restart\]|\+restart", re.IGNORECASE)


# ─── Small helpers ────────────────────────────────────────────

def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CapsStream-Updater/1.0",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


class ReleaseNotPublished(Exception):
    """The release exists but its zip asset is not downloadable (404)."""


# ─── Progress reporting ───────────────────────────────────────────────────────

def _write_progress(**kwargs):
    try:
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        state = {"stage": "idle", "bytes_done": 0, "total": 0, "message": ""}
        if os.path.isfile(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, encoding="utf-8") as f:
                    state.update(json.load(f) or {})
            except Exception:
                pass
        state.update(kwargs)
        tmp = PROGRESS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, PROGRESS_FILE)
    except Exception:
        pass


def get_update_progress():
    """Current update progress for the Settings UI (safe on any error)."""
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f) or {"stage": "idle"}
    except Exception:
        return {"stage": "idle"}


def _version_tuple(v):
    """'2.24.1.0' → (2, 24, 1, 0); tolerates missing segments."""
    parts = [int(p) for p in re.findall(r"\d+", str(v))[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def _download(url, dest_path, attempts=3):
    """
    Stream url to dest_path with retries. Streaming avoids loading the whole
    zip into memory; the transfer is verified against Content-Length when the
    server provides it. 404s raise ReleaseNotPublished immediately (retrying
    cannot help — the asset is not there).
    """
    last_err = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "CapsStream-Updater/1.0",
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(req, timeout=120) as res, open(dest_path, "wb") as f:
                expected = res.headers.get("Content-Length")
                total = int(expected) if expected else 0
                done = 0
                _write_progress(stage="downloading", total=total, bytes_done=0)
                while True:
                    chunk = res.read(65536)
                    if not chunk:
                        break
                    done += len(chunk)
                    f.write(chunk)
                    _write_progress(stage="downloading", total=total or done, bytes_done=done)
                if expected and int(expected) != done:
                    raise IOError(f"incomplete download ({done}/{expected} bytes)")
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ReleaseNotPublished(url) from e
            last_err = e
        except Exception as e:
            last_err = e
        time.sleep(2 * (attempt + 1))
    raise last_err


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
    asset_digest = None

    # Primary: GitHub Releases API (gives changelog body + asset URL)
    try:
        raw = _http_get(RELEASES_API).decode("utf-8")
        rel = json.loads(raw)
        latest = (rel.get("tag_name") or "").lstrip("vV")
        changelog = rel.get("body") or ""
        for asset in rel.get("assets", []):
            if asset.get("name", "").startswith("CapsStream-update-") and asset.get("name", "").endswith(".zip"):
                download_url = asset.get("browser_download_url")
                # GitHub exposes sha256 as 'sha256:<hex>' — used to verify downloads
                asset_digest = (asset.get("digest") or "").strip() or None
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
    result["digest"] = asset_digest
    result["changelog"] = changelog
    result["restart_hint"] = bool(RESTART_HINT_RE.search(changelog or ""))

    if latest:
        result["status"] = "available" if latest != current else "up_to_date"
    else:
        result["status"] = "error"

    result["last_checked"] = _touch_last_checked()
    result["pending_swaps"] = _pending_count()
    _write_state({
        **_read_state(),
        "latest": latest,
        "status": result["status"],
        "restart_hint": result["restart_hint"],
    })
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


def _replace_with_retry(src, dst, attempts=4, delay=0.5):
    """
    os.replace with retries: on Windows, antivirus and sync clients (e.g.
    OneDrive) can hold a brief lock on a file that is about to be replaced.
    Retrying resolves those; only genuinely held handles (running server)
    end up raising PermissionError to the caller.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _pending_count():
    try:
        with open(PENDING_MANIFEST, encoding="utf-8") as f:
            return len(json.load(f) or [])
    except Exception:
        return 0


# ─── One-click restart helper ─────────────────────────────────────────────────

RESTART_HELPER_FILE = "_finish_update_helper.py"
RESTART_LOG = os.path.join(BASE_DIR, "data", "update_restart.log")

_RESTART_HELPER_SRC = '''\
"""CapsStream update finisher - waits for the old server process to exit,
applies pending locked-file swaps, then relaunches the server."""
import ctypes
import os
import subprocess
import sys
import time

pid = int(sys.argv[1])
root = sys.argv[2]
log_path = os.path.join(root, "data", "update_restart.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\\n")
    except Exception:
        pass


def pid_alive(target):
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(SYNCHRONIZE, False, target)
    if not handle:
        return False  # process gone (or cannot be opened)
    try:
        return k32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(handle)


log(f"helper started - waiting for server pid {pid} to exit")
waited = 0
while pid_alive(pid):
    time.sleep(0.5)
    waited += 0.5
    if waited > 120:
        log("old server still running after 120s - giving up (will not double-start)")
        sys.exit(1)
log(f"server exited after {waited:.0f}s")

sys.path.insert(0, root)
os.chdir(root)

try:
    from backend.updater import apply_pending_swaps
    swapped = apply_pending_swaps()
    log(f"pending swaps applied: {swapped}")
except Exception as e:
    log(f"pending-swap error: {e}")

# Prefer the windowless interpreter so the relaunched server doesn't open a
# black console window (matches the silent-launch experience).
python_exe = os.path.join(root, "winpython", "python", "pythonw.exe")
if not os.path.isfile(python_exe):
    python_exe = os.path.join(root, "winpython", "python", "python.exe")
if not os.path.isfile(python_exe):
    python_exe = sys.executable

launcher_script = os.path.join(root, "silent_launcher.py")
today_log_name = time.strftime("capsstream_%Y%m%d.log")
today_log_path = os.path.join(root, "logs", today_log_name)
try:
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
except Exception:
    pass

try:
    if os.path.isfile(launcher_script):
        subprocess.Popen(
            [python_exe, launcher_script],
            cwd=root,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        log("silent_launcher relaunched (logging to logs/ and window monitoring active)")
    else:
        out = open(today_log_path, "a", encoding="utf-8")
        subprocess.Popen(
            [python_exe, os.path.join(root, "app.py")],
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        log("server relaunched (startup output captured in " + today_log_name + ")")
except Exception as e:
    log(f"RELUNCH FAILED: {e}")
    sys.exit(2)

try:
    os.remove(__file__)
except Exception:
    pass
'''


def spawn_restart_helper():
    """
    Detached helper that survives this server's exit: waits for the current
    process to die, applies pending swaps, relaunches app.py and captures its
    startup output into data/update_restart.log for debugging.
    Returns (helper_path, log_path).
    """
    helper_path = os.path.join(BASE_DIR, RESTART_HELPER_FILE)
    with open(helper_path, "w", encoding="utf-8") as f:
        f.write(_RESTART_HELPER_SRC)

    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        # Fully invisible — DETACHED_PROCESS alone still lets console-host
        # helpers (python.exe) flash a window.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, helper_path, str(os.getpid()), BASE_DIR],
        cwd=BASE_DIR,
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
    )
    # Remove the legacy batch helper if an older version left one behind
    legacy = os.path.join(BASE_DIR, "_finish_update.bat")
    if os.path.isfile(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass
    print(f"[Updater] Restart helper spawned ({helper_path})")
    return helper_path, RESTART_LOG


def _validate_staging(staging, expected_version=None):
    """
    Safety gate run BEFORE anything is installed: every staged .py file must
    compile, and a staged VERSION must match the release being installed.
    Returns a list of human-readable errors (empty = safe to install).
    """
    errors = []
    for root, _dirs, files in os.walk(staging):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, staging).replace("\\", "/")
            try:
                with open(path, "rb") as fh:
                    compile(fh.read(), path, "exec")
            except SyntaxError as e:
                errors.append(f"{rel}: syntax error line {e.lineno}")
            except Exception as e:
                errors.append(f"{rel}: {e}")

    if expected_version:
        ver_path = os.path.join(staging, "VERSION")
        if os.path.isfile(ver_path):
            try:
                with open(ver_path, encoding="utf-8") as fh:
                    staged_ver = fh.read().strip()
                if staged_ver != expected_version:
                    errors.append(
                        f"package VERSION ({staged_ver}) does not match release v{expected_version}"
                    )
            except Exception as e:
                errors.append(f"VERSION unreadable: {e}")

    return errors


def _backup_original(dst, rel):
    """Copy the original of a soon-to-be-replaced file into data/pre_update/."""
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_root = os.path.join(PRE_UPDATE_DIR, stamp)
        backup_path = os.path.join(backup_root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(dst, backup_path)

        # Retention: keep only the newest PRE_UPDATE_KEEP timestamped folders
        stamps = sorted(
            d for d in os.listdir(PRE_UPDATE_DIR)
            if os.path.isdir(os.path.join(PRE_UPDATE_DIR, d))
        )
        for old in stamps[:-PRE_UPDATE_KEEP]:
            shutil.rmtree(os.path.join(PRE_UPDATE_DIR, old), ignore_errors=True)
    except Exception as e:
        print(f"[Updater] Could not back up {rel}: {e}")


def _write_pending_manifest(rel_paths):
    os.makedirs(PENDING_DIR, exist_ok=True)
    with open(PENDING_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(sorted(set(rel_paths)), f, indent=2)


def apply_pending_swaps():
    """
    Apply update files that were deferred because the running server had
    them locked. Called by start.bat BEFORE the server launches, when no
    file handles are held and the swap always succeeds.
    Returns the number of files applied.
    """
    if not os.path.isfile(PENDING_MANIFEST):
        return 0
    try:
        with open(PENDING_MANIFEST, encoding="utf-8") as f:
            rels = json.load(f) or []
    except Exception as e:
        print(f"[Updater] Could not read pending-update manifest: {e}")
        return 0

    applied = 0
    for rel in rels:
        pend = os.path.join(PENDING_DIR, rel.replace("/", os.sep))
        dst = os.path.join(BASE_DIR, rel.replace("/", os.sep))
        try:
            if not os.path.isfile(pend):
                continue
            try:
                if os.path.isfile(dst):
                    os.chmod(dst, 0o666)  # clear read-only if set
            except Exception:
                pass
            os.replace(pend, dst)
            applied += 1
        except Exception as e:
            print(f"[Updater] Pending swap failed for {rel}: {e}")

    if applied:
        try:
            os.remove(PENDING_MANIFEST)
        except Exception:
            pass
        # Remove now-empty pending folders (manifest removal leaves the root)
        for root, _dirs, _files in os.walk(PENDING_DIR, topdown=False):
            try:
                os.rmdir(root)
            except Exception:
                pass
        print(f"[Updater] Applied {applied} pending update file(s)")
    return applied


def apply_update(download_url=None, force=False):
    """
    Download the update zip and safely replace allowed files only.
    Returns: { success, message, new_version, restart_required, ui_only }
    """
    # Single-flight: a second concurrent call must never interleave
    if not _UPDATE_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "message": "An update is already in progress.",
            "new_version": None,
            "restart_required": False,
            "ui_only": False,
        }
    try:
        return _apply_update_impl(download_url=download_url, force=force)
    finally:
        _UPDATE_LOCK.release()


def _apply_update_impl(download_url=None, force=False):
    current = get_local_version()

    try:
        info = check_for_update()
        url = download_url or info.get("download_url")
        latest = info.get("latest")
        expected_digest = (info.get("digest") or "").strip()

        if not url:
            return {
                "success": False,
                "message": "No update package available (check your GITHUB_REPO setting or internet connection).",
                "new_version": latest,
                "restart_required": False,
                "ui_only": False,
            }

        # Downgrade protection: only numeric compare — 'latest' must be NEWER
        # than what's installed unless explicitly forced.
        if latest and _version_tuple(latest) <= _version_tuple(current):
            if not force:
                return {
                    "success": True,
                    "message": f"Already on v{current} — v{latest} is not newer. Use force to reinstall.",
                    "new_version": current,
                    "restart_required": False,
                    "ui_only": True,
                    "up_to_date": True,
                }
            print(f"[Updater] Forced install of v{latest} over v{current}")

        os.makedirs(TMP_DIR, exist_ok=True)
        zip_path = os.path.join(TMP_DIR, "update.zip")

        # 1) Download (streamed to disk, with retries + live progress)
        try:
            _write_progress(stage="downloading", message=f"Downloading v{latest}")
            _download(url, zip_path)
        except ReleaseNotPublished:
            _write_progress(stage="failed", message="release not published yet")
            return {
                "success": False,
                "message": f"Release v{latest} is still publishing — its package is not downloadable yet. Try again in a couple of minutes.",
                "new_version": latest,
                "restart_required": False,
                "ui_only": False,
            }
        except Exception as e:
            _write_progress(stage="failed", message=str(e))
            return {
                "success": False,
                "message": f"Download failed: {e}",
                "new_version": latest,
                "restart_required": False,
                "ui_only": False,
            }

        # 2) Integrity: sha256 from the Releases API when available
        if expected_digest:
            algo, _, expected_hex = expected_digest.partition(":")
            if algo.lower() == "sha256" and expected_hex:
                _write_progress(stage="verifying", message="checking checksum")
                actual_hex = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
                if actual_hex != expected_hex.lower():
                    _write_progress(stage="failed", message="checksum mismatch")
                    shutil.rmtree(TMP_DIR, ignore_errors=True)
                    return {
                        "success": False,
                        "message": "Checksum mismatch — the downloaded package is corrupted or was tampered with. Please retry.",
                        "new_version": latest,
                        "restart_required": False,
                        "ui_only": False,
                    }

        # 3) Inspect & stage
        staging = os.path.join(TMP_DIR, "staging")
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)

        restart_required = False
        anything_changed = False
        applied = 0

        _write_progress(stage="extracting", message="extracting package")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                # Full CRC pass before touching anything installed
                bad_entry = zf.testzip()
                if bad_entry is not None:
                    raise zipfile.BadZipFile(f"corrupt entry in package: {bad_entry}")

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

            # 4) Validation gate — nothing is installed until staged code is
            #    proven syntactically valid and the version matches the release.
            _write_progress(stage="validating", message="validating staged files")
            errors = _validate_staging(staging, expected_version=latest)
            if errors:
                _write_progress(stage="failed", message="staged validation failed")
                return {
                    "success": False,
                    "message": "Update package failed validation — nothing was changed. Details: " + "; ".join(errors[:3]),
                    "new_version": latest,
                    "restart_required": False,
                    "ui_only": False,
                }

            # 5) Install: two-phase swap. First copy every changed file next to
            #    its destination as '<name>.csnew' (plus backup originals), then
            #    rename all of them into place in one quick pass.
            _write_progress(stage="installing", message="installing files")
            deferred = []    # locked by the running server → applied on next start
            move_errors = []
            prepared = []    # (csnew_path, dst, rel)

            for root, _dirs, files in os.walk(staging):
                rel_root = os.path.relpath(root, staging)
                dest_root = BASE_DIR if rel_root == "." else os.path.join(BASE_DIR, rel_root)
                os.makedirs(dest_root, exist_ok=True)
                for f in files:
                    src = os.path.join(root, f)
                    dst = os.path.join(dest_root, f)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)

                    if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
                        # Identical to what's installed — not a change
                        continue

                    anything_changed = True
                    rel = os.path.relpath(dst, BASE_DIR).replace("\\", "/")

                    # Backup the original so a bad release can be rolled back
                    if os.path.isfile(dst):
                        _backup_original(dst, rel)

                    new_path = dst + ".csnew"
                    try:
                        # Clear read-only attribute if set (blocks overwrite on Windows)
                        try:
                            if os.path.isfile(dst):
                                os.chmod(dst, 0o666)
                        except Exception:
                            pass
                        shutil.copy2(src, new_path)
                        prepared.append((new_path, dst, rel))
                    except Exception as e:
                        move_errors.append(f"{rel}: {e}")
                        continue

            for csnew, dst, rel in prepared:
                try:
                    _replace_with_retry(csnew, dst)
                except PermissionError:
                    # The running server keeps its entry script (app.py) open,
                    # so Windows refuses to overwrite it. Park the new file and
                    # let start.bat swap it in before the next launch.
                    pend = os.path.join(PENDING_DIR, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(pend), exist_ok=True)
                    shutil.copy2(csnew, pend)
                    deferred.append(rel)
                    try:
                        os.remove(csnew)
                    except OSError:
                        pass
                    continue
                except Exception as e:
                    move_errors.append(f"{rel}: {e}")
                    continue

                if _is_restart_file(rel):
                    restart_required = True
                elif rel.startswith(("static/", "templates/")):
                    # static/ or templates/ asset — UI-only change
                    pass
                else:
                    restart_required = True

            if deferred:
                _write_pending_manifest(deferred)
                restart_required = True  # pending swaps finalize on next start

            ui_only = not restart_required

        except zipfile.BadZipFile:
            return {
                "success": False,
                "message": "Downloaded update package is corrupted.",
                "new_version": latest,
                "restart_required": False,
                "ui_only": False,
            }
        except Exception as e:
            _write_progress(stage="failed", message=str(e))
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

        # Commit-message override: [restart] / +restart in the release notes
        # forces the restart prompt even when file comparison found no change.
        if not restart_required and info.get("restart_hint"):
            restart_required = True
            ui_only = False

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

        if not anything_changed and not restart_required and not move_errors:
            message = "Already up to date — no changes to apply."
        elif restart_required:
            message = "Update installed. Backend changed — restart CapsStream to finish."
            if deferred:
                message += f" ({len(deferred)} locked file(s) will be finalized on next start.)"
        elif move_errors:
            message = "Update partially applied — some files failed: " + "; ".join(move_errors[:3])
        else:
            message = "Update installed — reloading the interface."

        _write_progress(stage="done", message=message)

        return {
            "success": True,
            "message": message,
            "new_version": new_version,
            "restart_required": restart_required,
            "ui_only": ui_only and not restart_required,
        }
    except Exception as e:
        _write_progress(stage="failed", message=str(e))
        return {
            "success": False,
            "message": f"Update failed: {e}",
            "new_version": None,
            "restart_required": False,
            "ui_only": False,
        }
