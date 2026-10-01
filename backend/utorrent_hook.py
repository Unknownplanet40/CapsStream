# -*- coding: utf-8 -*-
"""
backend/utorrent_hook.py — Standalone uTorrent Automation Hook for CapsStream Media Requests.

This script can be executed by uTorrent's "Run Program" feature:
  - When a torrent finishes downloading (State 11 / Seeding / Finished)
  - On any state change while downloading or seeding

Key Features:
  - Operates standalone: Updates data/requests.json directly even when CapsStream is NOT open / running.
  - Automatically matches torrent titles, filenames, and directories to active media requests.
  - Handles movie requests (title + year) and TV/Anime requests (title + season/episode).
  - Pushes status updates to Supabase (if configured) so client devices are immediately notified.
  - If CapsStream server happens to be running, triggers an instant library scan/sync via HTTP.
  - Logs all execution events and matching decisions to logs/utorrent_updater.log.
"""

import os
import sys
import re
import json
import time
import argparse
import difflib
import logging
import contextlib
from datetime import datetime

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.utils.paths import BASE_DIR
from backend.utils.supabase_client import is_supabase_configured, update_online_request
from backend.matcher import _clean_name
from backend.scanner import _parse_episode

REQUESTS_FILE = os.path.join(BASE_DIR, "data", "requests.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "utorrent_updater.log")

# Setup logger
logger = logging.getLogger("utorrent_updater")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[uTorrentHook] %(message)s"))
    logger.addHandler(sh)


# uTorrent State Definitions (from docs/utorrent-run-program.md)
# Finished / Completed states:
# 4: Super seeding, 5: Seeding, 7: Super seed [F], 8: Seeding [F], 10: Queued seed, 11: Finished, 20: Moving, 21: Flushing
FINISHED_STATES = {4, 5, 7, 8, 10, 11, 20, 21}

# Actively downloading states:
# 6: Downloading, 9: Downloading [F], 17: Preallocating, 18: Downloading Metadata, 19: Connecting to Peers, 22: Need DHT, 23: Finding Peers, 24: Resolving, 25: Writing
DOWNLOADING_STATES = {6, 9, 17, 18, 19, 22, 23, 24, 25}

# Inactive states (do NOT transition to in_progress or completed):
# 2: Checked (Hash checking), 3: Paused, 12: Queued (Waiting for download slot), 13: Stopped
INACTIVE_STATES = {2, 3, 12, 13}

# Error states:
ERROR_STATES = {1}

LOCK_FILE = os.path.join(BASE_DIR, "data", ".requests_lock")
NOTIFY_CACHE_FILE = os.path.join(BASE_DIR, "data", ".notify_cache.json")


@contextlib.contextmanager
def file_lock(lock_path: str = LOCK_FILE, timeout: float = 6.0):
    """
    Cross-process file lock ensuring concurrent uTorrent events serialize cleanly.
    Prevents race conditions where simultaneous state transitions overwrite requests.json.
    """
    lock_dir = os.path.dirname(lock_path)
    os.makedirs(lock_dir, exist_ok=True)
    f = None
    locked = False
    try:
        f = open(lock_path, "a+")
        if sys.platform == "win32":
            import msvcrt
            start_t = time.time()
            while time.time() - start_t < timeout:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except (IOError, OSError):
                    time.sleep(0.04)
        else:
            locked = True
        yield locked
    finally:
        if locked and sys.platform == "win32" and f:
            try:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        if f:
            try:
                f.close()
            except Exception:
                pass


def resolve_torrent_status(state: int = None, status_msg: str = "", is_finish: bool = False):
    """
    Accurately resolve the target request status ('in_progress', 'completed', or None).

    Priority (highest → lowest):
      1. is_finish flag  → always completed
      2. state code      → hard gate (INACTIVE/DOWNLOADING always wins, even if msg says "Finished")
      3. status_msg (%M) → used only when state is None or unknown
    """
    if is_finish:
        return "completed"

    # State code is a hard gate — if µTorrent tells us the state explicitly,
    # trust it over the human-readable %M string, which can lag or carry
    # stale text (e.g. state=12 Queued shows msg="Finished" from prior seeding).
    if state is not None:
        if state in INACTIVE_STATES or state in ERROR_STATES:
            return None
        if state in DOWNLOADING_STATES:
            return "in_progress"
        if state in FINISHED_STATES:
            return "completed"
        # Unknown state — fall through to msg parsing below

    msg = (status_msg or "").strip().lower()
    if msg:
        if any(term in msg for term in ["seed", "finish", "complete", "100%"]):
            return "completed"
        if any(term in msg for term in ["download", "connecting", "metadata", "allocat", "peers", "finding", "resolv"]):
            return "in_progress"
        if any(term in msg for term in ["paused", "stopped", "queued", "error"]):
            return None

    return None


def _should_suppress_notification(req_id: str, status: str, cooldown: float = 12.0) -> bool:
    """Prevent duplicate desktop notification spam within `cooldown` seconds for the same request and status."""
    now = time.time()
    cache = {}
    if os.path.isfile(NOTIFY_CACHE_FILE):
        try:
            with open(NOTIFY_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    key = f"{req_id}:{status}"
    last_time = cache.get(key, 0.0)
    if (now - last_time) < cooldown:
        return True

    cache[key] = now
    # Evict entries older than 2 hours
    cleaned = {k: v for k, v in cache.items() if (now - v) < 7200}
    try:
        with open(NOTIFY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cleaned, f)
    except Exception:
        pass
    return False


def _normalize_str(text: str) -> str:
    """Normalize string by removing punctuation and lowercasing."""
    if not text:
        return ""
    return re.sub(r"[^\w\s]", "", str(text).lower()).strip()


def _extract_candidates(name: str = "", filename: str = "", dir_path: str = ""):
    """Extract candidate (title, year, season, episode) parsed info from arguments."""
    candidates = []
    seen = set()

    for raw in [name, filename, os.path.basename(dir_path or "") if dir_path else ""]:
        raw_str = (raw or "").strip()
        if not raw_str or raw_str in seen:
            continue
        seen.add(raw_str)

        clean_t, parsed_year, imdb_id = _clean_name(raw_str)
        season, episode = _parse_episode(raw_str)

        # Fallback season check from dir_path if not found in raw string
        if season is None and dir_path:
            from backend.scanner import _parse_season_dir
            season = _parse_season_dir(dir_path)

        candidates.append({
            "raw": raw_str,
            "title": clean_t,
            "norm_title": _normalize_str(clean_t),
            "year": parsed_year,
            "season": season,
            "episode": episode,
            "imdb_id": imdb_id
        })

    return candidates


def match_torrent_to_request(torrent_name: str, filename: str = "", dir_path: str = "", requests_list: list = None):
    """
    Find the best matching media request in requests_list.
    Returns (matched_request, match_reason, match_score).
    """
    if requests_list is None:
        return None, "No requests to check", 0.0

    candidates = _extract_candidates(torrent_name, filename, dir_path)
    if not candidates:
        return None, "No candidate titles extracted from arguments", 0.0

    best_match = None
    best_score = 0.0
    best_reason = ""

    for req in requests_list:
        if not isinstance(req, dict):
            continue

        req_title = req.get("title") or ""
        norm_req_title = _normalize_str(req_title)
        if not norm_req_title:
            continue

        req_year = None
        if req.get("year"):
            try:
                req_year = int(str(req.get("year"))[:4])
            except (ValueError, TypeError):
                req_year = None

        req_type = req.get("type", "Movie")
        is_tv = req_type in ("TV Show", "Anime")
        req_season = req.get("season")
        req_episode = req.get("episode")
        try:
            req_season = int(req_season) if req_season is not None and str(req_season).strip() != "" else None
        except (ValueError, TypeError):
            req_season = None
        try:
            req_episode = int(req_episode) if req_episode is not None and str(req_episode).strip() != "" else None
        except (ValueError, TypeError):
            req_episode = None

        for cand in candidates:
            score = 0.0
            cand_norm = cand["norm_title"]
            cand_year = cand["year"]
            cand_season = cand["season"]
            cand_episode = cand["episode"]

            # Season / Episode filtering for TV series
            if is_tv:
                if req_season is not None and cand_season is not None and req_season != cand_season:
                    continue  # Different season, discard candidate
                if req_episode is not None and cand_episode is not None and req_episode != cand_episode:
                    continue  # Different episode, discard candidate

            # Title matching
            sim = difflib.SequenceMatcher(None, cand_norm, norm_req_title).ratio()
            exact = (cand_norm == norm_req_title) or (cand_norm.replace(" ", "") == norm_req_title.replace(" ", ""))
            substring = (norm_req_title in cand_norm) or (cand_norm in norm_req_title)

            if exact:
                score += 0.8
            elif substring and len(norm_req_title) >= 4:
                score += 0.65
            elif sim >= 0.80:
                score += sim * 0.7
            else:
                continue

            # Year matching bonus / penalty
            if req_year is not None and cand_year is not None:
                if abs(req_year - cand_year) <= 1:
                    score += 0.2
                else:
                    score -= 0.3
            elif req_year is not None and cand_year is None:
                score += 0.05  # neutral

            # Season/episode matching bonus
            if is_tv and req_season is not None and cand_season is not None and req_season == cand_season:
                score += 0.1
                if req_episode is not None and cand_episode is not None and req_episode == cand_episode:
                    score += 0.1

            # Active request preference (pending or in_progress get priority over completed)
            if req.get("status") in ("pending", "in_progress"):
                score += 0.1

            if score > best_score and score >= 0.70:
                best_score = score
                best_match = req
                best_reason = f"Candidate '{cand['raw']}' matched '{req_title}' (score: {round(score, 2)})"

    return best_match, best_reason, best_score


def load_requests():
    """Load requests from data/requests.json safely."""
    if not os.path.isfile(REQUESTS_FILE):
        return []
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Failed to read requests file: {e}")
        return []


def save_requests(items):
    """Atomically save requests to data/requests.json."""
    os.makedirs(os.path.dirname(REQUESTS_FILE), exist_ok=True)
    tmp_file = REQUESTS_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, REQUESTS_FILE)


SERVER_PORT = 8700


def is_server_live(port: int = SERVER_PORT, timeout: float = 0.8) -> bool:
    """Return True if the CapsStream web server is currently running and listening on 127.0.0.1:port."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (OSError, socket.error):
        return False


def trigger_server_sync(port: int = SERVER_PORT) -> bool:
    """If CapsStream server is running locally on port 8700, notify it to re-scan and sync. Returns True if server is live and responded."""
    base_url = f"http://127.0.0.1:{port}"
    try:
        import urllib.request
        import urllib.error
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        sync_url = f"{base_url}/api/requests/sync-library"
        req = urllib.request.Request(
            sync_url,
            data=b"{}",
            headers={"Content-Type": "application/json", "User-Agent": "CapsStream-uTorrentHook"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=2.5, context=ctx) as res:
            logger.info(f"Triggered live CapsStream library sync on port {port} (HTTP {res.status})")
            return True
    except urllib.error.HTTPError as e:
        logger.info(f"CapsStream server responded on port {port} (HTTP {e.code})")
        return True
    except Exception as e:
        logger.debug(f"CapsStream server notification on port {port} skipped or offline: {e}")
        return False


def register_app_identity():
    """Register CapsStream AppUserModelId under HKCU so toasts show the CapsStream brand."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        key_path = r"Software\Classes\AppUserModelId\CapsStream"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "CapsStream")
            icon = os.path.join(BASE_DIR, "static", "img", "favicon.png")
            if os.path.isfile(icon):
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon)
    except Exception:
        pass


def show_windows_notification(title: str, message: str, actions: list = None, launch_url: str = None):
    """Display a native Windows Toast notification with CapsStream logo and action buttons without flashing any terminal or console window."""
    if sys.platform != "win32":
        return

    try:
        import base64
        import pathlib
        import subprocess

        register_app_identity()

        icon = os.path.join(BASE_DIR, "static", "img", "favicon.png")
        image_el = ""
        def _clean_xml(s: str) -> str:
            return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

        if os.path.isfile(icon):
            icon_uri = pathlib.Path(icon).as_uri()
            image_el = f'<image placement="appLogoOverride" src="{_clean_xml(icon_uri)}" />'

        clean_title = _clean_xml(title or "CapsStream")
        clean_msg = _clean_xml(message or "")
        launch_attr = f' activationType="protocol" launch="{_clean_xml(launch_url)}"' if launch_url else ''

        actions_xml = ""
        if actions:
            action_tags = []
            for act in actions:
                content = _clean_xml(act.get("content") or act.get("title", ""))
                args = _clean_xml(act.get("arguments") or act.get("arg", ""))
                act_type = _clean_xml(act.get("activationType") or act.get("type", "protocol"))
                if content:
                    action_tags.append(
                        f'<action content="{content}" arguments="{args}" activationType="{act_type}" />'
                    )
            if action_tags:
                actions_xml = f"<actions>{''.join(action_tags)}</actions>"

        xml = f'<toast{launch_attr}><visual><binding template="ToastGeneric">{image_el}<text>{clean_title}</text><text>{clean_msg}</text></binding></visual>{actions_xml}</toast>'
        xml_ps = xml.replace("'", "''")
        ps_code = (
            "$ProgressPreference = 'SilentlyContinue'\n"
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            f"$x.LoadXml('{xml_ps}')\n"
            "$t = New-Object Windows.UI.Notifications.ToastNotification $x\n"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('CapsStream').Show($t)\n"
        )
        enc = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")

        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            startupinfo=si,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug(f"Failed to display native Windows notification: {e}")



def process_utorrent_event(
    torrent_name: str,
    state: int = None,
    dir_path: str = "",
    filename: str = "",
    status_msg: str = "",
    prev_state: int = None,
    is_finish: bool = False,
    dry_run: bool = False,
    port: int = SERVER_PORT,
    no_notify: bool = False
):
    """
    Process incoming uTorrent event and update matching request.
    Protected by cross-process file lock to serialize concurrent events and prevent race conditions.
    """
    logger.info(f"Event received: name='{torrent_name}', state={state}, msg='{status_msg}', prev_state={prev_state}, finish={is_finish}, dir='{dir_path}', file='{filename}'")

    if not torrent_name and not filename and not dir_path:
        logger.warning("No torrent name, filename, or directory provided. Aborting.")
        return {"ok": False, "error": "No media identifier provided"}

    # Accurately resolve target status from explicit finish, uTorrent status string (%M), or state code (%S)
    new_status = resolve_torrent_status(state=state, status_msg=status_msg, is_finish=is_finish)

    if not new_status:
        logger.info(f"State {state} (msg='{status_msg}') does not require a request status transition.")
        return {"ok": True, "message": f"State {state} requires no change"}

    with file_lock():
        items = load_requests()
        if not items:
            logger.info("No media requests found in data/requests.json.")
            return {"ok": True, "message": "No media requests found"}

        matched_req, reason, score = match_torrent_to_request(torrent_name, filename, dir_path, items)
        if not matched_req:
            logger.info(f"No matching request found for torrent '{torrent_name}'.")
            return {"ok": True, "message": "No matching request found"}

        req_id = matched_req.get("id")
        req_title = matched_req.get("title")
        curr_status = matched_req.get("status")

        logger.info(f"Matched: '{req_title}' (id: {req_id}, current status: '{curr_status}') - {reason}")

        # Guard: Never downgrade already completed requests back to in_progress or pending
        if curr_status == "completed" and new_status != "completed":
            logger.info(f"Request '{req_title}' is already completed. Skipping downgrade to {new_status}.")
            return {"ok": True, "message": "Request already completed"}

        if curr_status == new_status:
            if new_status == "completed":
                # Check for newly downloaded media file in library and refresh sync/toast
                try:
                    from backend.routes.requests import detect_media_in_library
                    matched_lib = detect_media_in_library(matched_req)
                    if matched_lib and not matched_req.get("detected_media_id"):
                        matched_req["detected_media_id"] = matched_lib.get("id")
                        matched_req["detected_media_type"] = matched_lib.get("type")
                        matched_req["detected_tmdb_id"] = matched_lib.get("tmdb_id")
                        matched_req["auto_detected"] = True
                        save_requests(items)
                except Exception as e:
                    logger.debug(f"Library detection check skipped: {e}")

                server_live = bool(trigger_server_sync(port=port))
                if not no_notify and not dry_run and not _should_suppress_notification(req_id, "completed"):
                    year_str = f" ({matched_req.get('year')})" if matched_req.get('year') else ""
                    watch_url = f"http://127.0.0.1:{port}/" if server_live else None
                    actions = None
                    if server_live:
                        actions = [
                            {"content": "Watch Now", "arguments": watch_url, "activationType": "protocol"},
                            {"content": "Dismiss", "arguments": "dismiss", "activationType": "system"},
                        ]
                    msg_ready = " • Ready in Library" if server_live else ""
                    show_windows_notification(
                        "CapsStream Media Request",
                        f"Download Completed: {req_title}{year_str}{msg_ready}",
                        actions=actions,
                        launch_url=watch_url,
                    )
                logger.info(f"Request '{req_title}' is already completed (sync & notification refreshed).")
                return {"ok": True, "message": "Request already completed, sync refreshed", "request": matched_req}

            logger.info(f"Request '{req_title}' is already '{new_status}'. No update needed.")
            return {"ok": True, "message": f"Request already {new_status}"}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update fields
        matched_req["status"] = new_status
        matched_req["updated_at"] = now_str
        if new_status == "completed" and not matched_req.get("completed_at"):
            matched_req["completed_at"] = now_str

        # Try local database check to see if media file exists in library
        try:
            from backend.routes.requests import detect_media_in_library
            matched_lib = detect_media_in_library(matched_req)
            if matched_lib:
                matched_req["detected_media_id"] = matched_lib.get("id")
                matched_req["detected_media_type"] = matched_lib.get("type")
                matched_req["detected_tmdb_id"] = matched_lib.get("tmdb_id")
                matched_req["auto_detected"] = True
        except Exception as e:
            logger.debug(f"Library detection check skipped: {e}")

        if dry_run:
            logger.info(f"[DRY RUN] Would update request '{req_title}' ({req_id}) -> '{new_status}'")
            return {"ok": True, "dry_run": True, "request": matched_req}

        # 1. Save locally to data/requests.json (even when CapsStream is NOT open)
        save_requests(items)
        logger.info(f"Successfully saved updated request '{req_title}' ({req_id}) -> '{new_status}' to data/requests.json")

    # 2. Push update to Supabase cloud (even when CapsStream server is NOT open)
    if is_supabase_configured():
        try:
            patch_data = {
                "status": new_status,
                "admin_note": matched_req.get("admin_note"),
                "updated_at": now_str
            }
            if new_status == "completed":
                patch_data["completed_at"] = now_str
            if matched_req.get("detected_media_id"):
                patch_data["detected_media_id"] = matched_req["detected_media_id"]
                patch_data["detected_media_type"] = matched_req.get("detected_media_type")
                patch_data["detected_tmdb_id"] = matched_req.get("detected_tmdb_id")

            res = update_online_request(req_id, patch_data)
            if res:
                logger.info(f"Successfully pushed status update to Supabase for request '{req_id}'")
            else:
                logger.warning(f"Supabase update returned empty response for request '{req_id}'")
        except Exception as e:
            logger.error(f"Failed to push update to Supabase: {e}")

    # 3. If CapsStream server is active on port 8700, notify it
    server_live = bool(trigger_server_sync(port=port))

    # 4. Native Windows notification on state change or completion (debounced)
    if not no_notify and not dry_run and not _should_suppress_notification(req_id, new_status):
        watch_url = f"http://127.0.0.1:{port}/" if server_live else None
        if new_status == "completed":
            year_str = f" ({matched_req.get('year')})" if matched_req.get('year') else ""
            actions = None
            if server_live:
                actions = [
                    {"content": "Watch Now", "arguments": watch_url, "activationType": "protocol"},
                    {"content": "Dismiss", "arguments": "dismiss", "activationType": "system"},
                ]
            msg_ready = " • Ready in Library" if server_live else ""
            show_windows_notification(
                "CapsStream Media Request",
                f"Download Completed: {req_title}{year_str}{msg_ready}",
                actions=actions,
                launch_url=watch_url,
            )
        elif new_status == "in_progress":
            actions = None
            if server_live:
                actions = [
                    {"content": "View Library", "arguments": watch_url, "activationType": "protocol"},
                    {"content": "Dismiss", "arguments": "dismiss", "activationType": "system"},
                ]
            show_windows_notification(
                "CapsStream Media Request",
                f"Downloading: {req_title} • Status: In Progress",
                actions=actions,
                launch_url=watch_url,
            )

    return {"ok": True, "updated": True, "request": matched_req}


def main():
    """Command line parser supporting both flag-based and positional arguments from uTorrent."""
    parser = argparse.ArgumentParser(
        description="CapsStream uTorrent Automation Hook — Updates Media Requests standalone on finish or state change."
    )
    # Flag arguments
    parser.add_argument("--name", "-n", dest="name", default="", help="Torrent Title (%N)")
    parser.add_argument("--state", "-s", dest="state", type=int, default=None, help="Current State code (%S)")
    parser.add_argument("--prev-state", "-p", dest="prev_state", type=int, default=None, help="Previous State code (%P)")
    parser.add_argument("--status-msg", "-m", dest="status_msg", default="", help="Status message string (%M)")
    parser.add_argument("--dir", "-d", dest="dir", default="", help="Directory where files are saved (%D)")
    parser.add_argument("--file", "-f", dest="file", default="", help="Downloaded file name (%F)")
    parser.add_argument("--kind", "-k", dest="kind", default="", help="Kind of torrent: single or multi (%K)")
    parser.add_argument("--finish", "--completed", dest="finish", action="store_true", help="Explicit finished/completed event")
    parser.add_argument("--port", dest="port", type=int, default=SERVER_PORT, help="Port of CapsStream server (default: 8700)")
    parser.add_argument("--no-notify", dest="no_notify", action="store_true", help="Disable Windows desktop notification")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Perform match without modifying files")

    # Positional arguments fallback (for uTorrent simple execution like: hook.bat "%N" "%S" "%D" "%F" "%M" "%P")
    parser.add_argument("positional_args", nargs="*", help="Positional arguments from uTorrent: [name, state, dir, file, status_msg, prev_state]")

    args = parser.parse_args()

    name = args.name
    state = args.state
    prev_state = args.prev_state
    status_msg = args.status_msg
    dir_path = args.dir
    file_name = args.file
    is_finish = args.finish
    no_notify = args.no_notify

    # Map positional arguments if flags weren't provided
    pos = args.positional_args
    if pos:
        # Check if first positional is a keyword flag
        clean_pos = []
        for p in pos:
            if p in ("--finish", "-finish", "/finish", "finish"):
                is_finish = True
            elif p in ("--dry-run", "-dry-run"):
                args.dry_run = True
            elif p in ("--no-notify", "-no-notify"):
                no_notify = True
            else:
                clean_pos.append(p)

        if len(clean_pos) >= 1 and not name:
            name = clean_pos[0]
        if len(clean_pos) >= 2 and state is None:
            try:
                state = int(clean_pos[1])
            except (ValueError, TypeError):
                if not status_msg and not clean_pos[1].isdigit():
                    status_msg = clean_pos[1]
                state = None
        if len(clean_pos) >= 3 and not dir_path:
            dir_path = clean_pos[2]
        if len(clean_pos) >= 4 and not file_name:
            file_name = clean_pos[3]
        if len(clean_pos) >= 5 and not status_msg:
            status_msg = clean_pos[4]
        if len(clean_pos) >= 6 and prev_state is None:
            try:
                prev_state = int(clean_pos[5])
            except (ValueError, TypeError):
                prev_state = None

    result = process_utorrent_event(
        torrent_name=name,
        state=state,
        dir_path=dir_path,
        filename=file_name,
        status_msg=status_msg,
        prev_state=prev_state,
        is_finish=is_finish,
        dry_run=args.dry_run,
        port=args.port,
        no_notify=no_notify
    )

    if not result.get("ok"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
