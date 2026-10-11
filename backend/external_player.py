# -*- coding: utf-8 -*-
"""
backend/external_player.py — External desktop player integration (VLC & System Default).

Features:
- Auto-detects VLC Media Player across Windows, macOS, and Linux.
- Builds Extended M3U8 playlists for single media or entire series/seasons.
- Supports Dual Mode: direct local file paths on the host PC vs HTTP stream URLs on remote clients.
- Launches VLC with its HTTP control interface on an ephemeral port.
- Spawns a background daemon (VLCProgressTracker) that polls playback status every 5 seconds,
  mapping active files/URIs back to CapsStream media IDs to persist watch progress,
  watch history, and achievements in real time.
- Gracefully falls back to the system default media player (via os.startfile / xdg-open)
  when VLC is not installed.
"""

import os
import sys
import time
import socket
import secrets
import logging
import urllib.parse
import subprocess
import threading
import tempfile
from typing import List, Dict, Any, Optional

logger = logging.getLogger("capsstream.external_player")

# Track active background tracker threads so they don't get garbage-collected prematurely
_ACTIVE_TRACKERS: List["VLCProgressTracker"] = []
_TRACKERS_LOCK = threading.Lock()

_CURRENT_VLC_SESSION: Dict[str, Any] = {
    "active": False,
    "media_id": None,
    "title": None,
    "ep_title": None,
    "season": None,
    "episode": None,
    "time": 0,
    "duration": 0,
    "percent": 0,
    "state": "idle",
    "last_sync": 0,
    "last_completed": False,
}


def find_vlc_binary() -> Optional[str]:
    """
    Search for VLC binary on Windows, macOS, or Linux.
    Returns the absolute path to vlc executable if found, else None.
    """
    import shutil

    if sys.platform == "win32":
        # Check standard Windows paths
        candidates = [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ]
        prog_files = os.environ.get("ProgramFiles")
        if prog_files:
            candidates.append(os.path.join(prog_files, "VideoLAN", "VLC", "vlc.exe"))
        prog_files_x86 = os.environ.get("ProgramFiles(x86)")
        if prog_files_x86:
            candidates.append(os.path.join(prog_files_x86, "VideoLAN", "VLC", "vlc.exe"))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(os.path.join(local_app_data, "Programs", "VideoLAN", "VLC", "vlc.exe"))

        for c in candidates:
            if c and os.path.isfile(c):
                return os.path.normpath(c)

        # Check Windows Registry
        try:
            import winreg
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey in (r"SOFTWARE\VideoLAN\VLC", r"SOFTWARE\WOW6432Node\VideoLAN\VLC"):
                    try:
                        with winreg.OpenKey(root_key, subkey) as k:
                            install_dir, _ = winreg.QueryValueEx(k, "InstallDir")
                            if install_dir:
                                exe = os.path.join(install_dir, "vlc.exe")
                                if os.path.isfile(exe):
                                    return os.path.normpath(exe)
                    except OSError:
                        pass
        except ImportError:
            pass

        which = shutil.which("vlc.exe") or shutil.which("vlc")
        if which and os.path.isfile(which):
            return os.path.normpath(which)

    elif sys.platform == "darwin":
        mac_app = "/Applications/VLC.app/Contents/MacOS/VLC"
        if os.path.isfile(mac_app):
            return mac_app
        which = shutil.which("vlc")
        if which:
            return which

    else:
        for p in ("/usr/bin/vlc", "/usr/local/bin/vlc", "/snap/bin/vlc"):
            if os.path.isfile(p):
                return p
        which = shutil.which("vlc")
        if which:
            return which

    return None


def get_free_port(start_port: int = 8089) -> int:
    """Find an available TCP port on localhost for VLC HTTP control."""
    for port in range(start_port, start_port + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_playlist_content(
    items: List[Dict[str, Any]],
    is_local_client: bool = True,
    host_url: str = ""
) -> str:
    """
    Generate Extended M3U8 playlist content.
    - Local client: references local filesystem paths for direct, lossless playback.
    - Remote client: references HTTP stream URLs.
    """
    lines = ["#EXTM3U"]
    for item in items:
        dur = int(item.get("duration") or -1)
        s = item.get("season")
        ep = item.get("episode")
        if s is not None and ep is not None:
            ep_tag = f"S{int(s):02d}E{int(ep):02d}"
            title = f"{item.get('title') or 'Series'} - {ep_tag} - {item.get('ep_title') or 'Episode'}"
        else:
            title = item.get("ep_title") or item.get("title") or "Video"

        lines.append(f"#EXTINF:{dur},{title}")
        file_path = item.get("file_path")
        if is_local_client and file_path and os.path.isfile(file_path):
            lines.append(os.path.normpath(os.path.abspath(file_path)))
        else:
            stream_url = f"{host_url.rstrip('/')}/api/stream/{item['id']}"
            lines.append(stream_url)

    return "\n".join(lines) + "\n"


def prune_temp_playlists(max_age_seconds: int = 3600) -> None:
    """Remove orphaned temporary playlist files older than max_age_seconds."""
    temp_dir = os.path.join(tempfile.gettempdir(), "capsstream_playlists")
    if not os.path.isdir(temp_dir):
        return
    now = time.time()
    try:
        for entry in os.scandir(temp_dir):
            if entry.is_file() and entry.name.endswith(".m3u8"):
                try:
                    if now - entry.stat().st_mtime > max_age_seconds:
                        os.remove(entry.path)
                except OSError:
                    pass
    except Exception:
        pass


def create_temp_playlist_file(
    content: str,
    title_hint: str = "playlist"
) -> str:
    """Save playlist content to a temporary .m3u8 file with utf-8 encoding."""
    prune_temp_playlists()
    safe_name = "".join(c for c in title_hint if c.isalnum() or c in (" ", "-", "_")).strip() or "playlist"
    temp_dir = os.path.join(tempfile.gettempdir(), "capsstream_playlists")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{safe_name}_{secrets.token_hex(4)}.m3u8")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
    return temp_path


class VLCProgressTracker(threading.Thread):
    """
    Background daemon thread polling VLC HTTP API status.json.
    Maps playing file/URI to CapsStream media_id, saves progress,
    and cleanly handles auto-advancing across episodes.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        port: int,
        password: str,
        items: List[Dict[str, Any]],
        profile_id: int,
        temp_files: Optional[List[str]] = None,
        poll_interval: float = 5.0
    ):
        super().__init__(name=f"VLCProgressTracker-{port}", daemon=True)
        self.process = process
        self.port = port
        self.password = password
        self.items = items
        self.profile_id = profile_id
        self.temp_files = temp_files or []
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()

        # Build lookup maps for fast matching
        self.path_map: Dict[str, int] = {}
        self.filename_map: Dict[str, int] = {}
        self.id_map: Dict[int, Dict[str, Any]] = {}

        for item in items:
            mid = item.get("id")
            if not mid:
                continue
            self.id_map[mid] = item
            fp = item.get("file_path")
            if fp:
                norm_fp = os.path.normpath(os.path.abspath(fp)).lower()
                self.path_map[norm_fp] = mid
                base = os.path.basename(fp).lower()
                self.filename_map[base] = mid
                self.filename_map[urllib.parse.unquote(base).lower()] = mid

        self.current_media_id: Optional[int] = items[0].get("id") if items else None
        self.last_saved_time: int = 0
        self.last_duration: int = 0

    def stop(self):
        self._stop_event.set()

    def resolve_media_id(self, meta: Dict[str, Any]) -> Optional[int]:
        """Resolve VLC metadata (filename, uri, title) to a CapsStream media ID."""
        if not meta:
            return self.current_media_id or (self.items[0].get("id") if self.items else None)

        uri = (meta.get("uri") or "").strip()
        filename = (meta.get("filename") or "").strip()
        title = (meta.get("title") or "").strip()
        artist = (meta.get("artist") or "").strip()

        # 1. Check season/episode pattern (e.g. S01E02, s01e02, 1x02) in filename, title, artist, or URI
        import re
        search_blob = f"{filename} {title} {artist} {uri}"
        se_match = re.search(r"(?:[Ss](\d{1,2})[Ee](\d{1,3})|(\d{1,2})x(\d{1,3}))", search_blob)
        if se_match:
            s_num = int(se_match.group(1) or se_match.group(3))
            e_num = int(se_match.group(2) or se_match.group(4))
            for item in self.items:
                if item.get("season") is not None and item.get("episode") is not None:
                    if int(item["season"]) == s_num and int(item["episode"]) == e_num:
                        return item["id"]

        # 2. Check filename directly (both raw and URL-decoded)
        if filename:
            clean_fn = urllib.parse.unquote(filename)
            for fn in (clean_fn, filename):
                norm_base = os.path.basename(fn).lower()
                if norm_base in self.filename_map:
                    return self.filename_map[norm_base]
                norm_full = os.path.normpath(fn).lower()
                if norm_full in self.path_map:
                    return self.path_map[norm_full]

        # 3. Check local file path or stream URL in URI
        if uri:
            clean_uri = urllib.parse.unquote(uri)
            for u in (clean_uri, uri):
                if "/api/stream/" in u:
                    try:
                        stream_id_part = u.split("/api/stream/")[1].split("?")[0].split("/")[0]
                        mid = int(stream_id_part)
                        if mid in self.id_map:
                            return mid
                    except (ValueError, IndexError):
                        pass

                p = u
                for prefix in ("file:///", "file://"):
                    if p.startswith(prefix):
                        p = p[len(prefix):]
                        break
                norm_clean = os.path.normpath(p).lower()
                if norm_clean in self.path_map:
                    return self.path_map[norm_clean]
                base_clean = os.path.basename(norm_clean).lower()
                if base_clean in self.filename_map:
                    return self.filename_map[base_clean]

        # 4. Check by item title / episode title match
        if title:
            tl = title.lower()
            for item in self.items:
                it_t = (item.get("title") or "").lower()
                it_ep = (item.get("ep_title") or "").lower()
                if it_t and (it_t == tl or it_t in tl or tl in it_t):
                    return item["id"]
                if it_ep and (it_ep == tl or it_ep in tl or tl in it_ep):
                    return item["id"]

        return self.current_media_id or (self.items[0].get("id") if self.items else None)

    def run(self):
        import requests
        from backend.db import save_progress

        status_url = f"http://127.0.0.1:{self.port}/requests/status.json"
        auth = ("", self.password)

        logger.info(f"VLCProgressTracker started on port {self.port} for profile {self.profile_id}")
        print(f"[CapsStream VLC Tracker] Started tracking on port {self.port} for profile {self.profile_id}", flush=True)

        # Wait a moment for VLC HTTP server to bind
        time.sleep(1.5)

        consecutive_errors = 0
        max_consecutive_errors = 10

        try:
            while not self._stop_event.is_set():
                # Check if VLC process has ended
                if self.process.poll() is not None:
                    logger.info("VLC process exited, saving final progress and terminating tracker")
                    print("[CapsStream VLC Tracker] VLC window closed, finalizing watch progress...", flush=True)
                    break

                try:
                    resp = requests.get(status_url, auth=auth, timeout=3.0)
                    if resp.status_code == 200:
                        consecutive_errors = 0
                        data = resp.json()
                        time_sec = int(data.get("time") or 0)
                        length_sec = int(data.get("length") or 0)
                        state = data.get("state") or ""

                        # Safely unnest information metadata (handles information: None)
                        info_dict = data.get("information") if isinstance(data.get("information"), dict) else {}
                        category_dict = info_dict.get("category") if isinstance(info_dict.get("category"), dict) else {}
                        info_meta = category_dict.get("meta") if isinstance(category_dict.get("meta"), dict) else {}

                        detected_mid = self.resolve_media_id(info_meta)

                        if detected_mid:
                            # Detect episode transition
                            if self.current_media_id and detected_mid != self.current_media_id:
                                if self.last_duration > 0 and (self.last_saved_time / self.last_duration >= 0.85):
                                    try:
                                        save_progress(
                                            self.profile_id,
                                            self.current_media_id,
                                            self.last_duration,
                                            self.last_duration,
                                            completed=True
                                        )
                                        print(f"[CapsStream VLC Tracker] Marked episode {self.current_media_id} completed", flush=True)
                                    except Exception as e:
                                        logger.warning(f"Error marking episode {self.current_media_id} completed: {e}")

                                self.last_saved_time = 0
                                self.last_duration = 0

                            self.current_media_id = detected_mid

                        active_mid = self.current_media_id or detected_mid

                        if active_mid and length_sec > 0 and time_sec > 0:
                            is_completed = (time_sec / length_sec) >= 0.90
                            self.last_saved_time = time_sec
                            self.last_duration = length_sec

                            try:
                                save_progress(
                                    self.profile_id,
                                    active_mid,
                                    time_sec,
                                    length_sec,
                                    completed=is_completed
                                )
                            except Exception as e:
                                logger.warning(f"Error saving progress for media {active_mid}: {e}")

                            item_obj = self.id_map.get(active_mid, {})
                            item_title = item_obj.get("title") or item_obj.get("ep_title") or "Video"
                            if item_obj.get("season") is not None and item_obj.get("episode") is not None:
                                item_title = f"{item_title} S{int(item_obj['season']):02d}E{int(item_obj['episode']):02d}"

                            percent = int((time_sec / length_sec) * 100) if length_sec > 0 else 0

                            with _TRACKERS_LOCK:
                                _CURRENT_VLC_SESSION.update({
                                    "active": True,
                                    "media_id": active_mid,
                                    "title": item_title,
                                    "ep_title": item_obj.get("ep_title"),
                                    "season": item_obj.get("season"),
                                    "episode": item_obj.get("episode"),
                                    "time": time_sec,
                                    "duration": length_sec,
                                    "percent": percent,
                                    "state": state,
                                    "last_sync": time.time(),
                                    "last_completed": is_completed,
                                })

                            print(f"[CapsStream VLC Sync] 🎬 {item_title} • {time_sec}s / {length_sec}s ({percent}%) [{state}]", flush=True)

                except Exception as err:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors and self.process.poll() is not None:
                        break

                self._stop_event.wait(self.poll_interval)

        finally:
            with _TRACKERS_LOCK:
                _CURRENT_VLC_SESSION["active"] = False
                _CURRENT_VLC_SESSION["state"] = "stopped"

            # Final save if we have an active item and position
            if self.current_media_id and self.last_saved_time > 0 and self.last_duration > 0:
                try:
                    is_completed = (self.last_saved_time / self.last_duration) >= 0.90
                    save_progress(
                        self.profile_id,
                        self.current_media_id,
                        self.last_saved_time,
                        self.last_duration,
                        completed=is_completed
                    )
                    print(f"[CapsStream VLC Tracker] Final progress recorded: {self.last_saved_time}s / {self.last_duration}s", flush=True)
                except Exception as e:
                    logger.warning(f"Error saving final progress: {e}")

            # Clean up temporary playlist files
            for tf in self.temp_files:
                try:
                    if tf and os.path.isfile(tf):
                        os.remove(tf)
                except OSError:
                    pass

            with _TRACKERS_LOCK:
                if self in _ACTIVE_TRACKERS:
                    _ACTIVE_TRACKERS.remove(self)

            logger.info("VLCProgressTracker terminated cleanly")
            print("[CapsStream VLC Tracker] Tracker shutdown complete.", flush=True)


def stop_vlc_playback() -> bool:
    """
    Stop active VLC playback instances, terminate processes,
    and reset the active session state.
    """
    with _TRACKERS_LOCK:
        trackers = list(_ACTIVE_TRACKERS)

    if not trackers:
        with _TRACKERS_LOCK:
            _CURRENT_VLC_SESSION["active"] = False
            _CURRENT_VLC_SESSION["state"] = "stopped"
        return True

    for tracker in trackers:
        try:
            try:
                import requests
                requests.get(
                    f"http://127.0.0.1:{tracker.port}/requests/status.json?command=pl_stop",
                    auth=("", tracker.password),
                    timeout=1.0
                )
            except Exception:
                pass

            tracker.stop()

            if tracker.process and tracker.process.poll() is None:
                tracker.process.terminate()
                try:
                    tracker.process.wait(timeout=1.5)
                except Exception:
                    tracker.process.kill()
        except Exception as e:
            logger.warning(f"Error stopping VLC playback: {e}")

    with _TRACKERS_LOCK:
        _CURRENT_VLC_SESSION["active"] = False
        _CURRENT_VLC_SESSION["state"] = "stopped"

    return True


def minimize_capsstream_window(url: str = "http://127.0.0.1:8000") -> bool:
    """
    Locate and minimize the CapsStream browser or standalone PWA window on Windows.
    Returns True if a matching window was minimized, False otherwise.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        SW_MINIMIZE = 6
        minimized = [False]

        try:
            from silent_launcher import find_capsstream_window
            hwnd = find_capsstream_window(url)
            if hwnd:
                user32.ShowWindow(hwnd, SW_MINIMIZE)
                minimized[0] = True
        except Exception:
            pass

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        ignore_markers = (
            "github", "google search", "bing search", "duckduckgo",
            "reddit", "gitlab", "stackoverflow", "commit", "action",
            "workflow", "pull request", "issue", "blob", "tree",
            "antigravity", "visual studio", "powershell"
        )
        known_browsers = (
            "msedge", "chrome", "brave", "opera", "vivaldi",
            "firefox", "arc", "applicationframehost", "python", "pythonw"
        )

        def _enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip().lower()

                    if not title or any(ign in title for ign in ignore_markers):
                        return True

                    is_match = (
                        title == "capsstream"
                        or title.startswith("capsstream -")
                        or title.startswith("capsstream —")
                        or title.startswith("capsstream |")
                        or title.startswith("capsstream •")
                        or ("capsstream" in title and any(p in title for p in ("8000", "localhost", "127.0.0.1")))
                    )

                    if is_match:
                        pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        pname = ""
                        hProc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
                        if hProc:
                            pbuff = ctypes.create_unicode_buffer(260)
                            if psapi.GetModuleBaseNameW(hProc, None, pbuff, 260):
                                pname = pbuff.value.lower()
                            kernel32.CloseHandle(hProc)

                        if not pname or any(b in pname for b in known_browsers):
                            user32.ShowWindow(hwnd, SW_MINIMIZE)
                            minimized[0] = True
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ssize_t, ctypes.c_ssize_t)
        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        return minimized[0]
    except Exception as e:
        logger.debug(f"Failed to minimize CapsStream window: {e}")
        return False


def get_vlc_tracker_status() -> Dict[str, Any]:
    """Return the current VLC playback tracking status."""
    with _TRACKERS_LOCK:
        sess = dict(_CURRENT_VLC_SESSION)
        if sess.get("active"):
            if time.time() - sess.get("last_sync", 0) > 25:
                sess["active"] = False
        return sess


def launch_external_player(
    items: List[Dict[str, Any]],
    profile_id: int,
    is_local_client: bool = True,
    host_url: str = "",
    title_hint: str = "media"
) -> Dict[str, Any]:
    """
    Launch external player for one or more media items.
    1. If VLC is detected: creates .m3u8 playlist, launches VLC with HTTP tracking enabled.
    2. If VLC is not found: falls back to system default player via os.startfile / xdg-open.
    """
    if not items:
        return {"ok": False, "error": "No media items provided"}

    vlc_bin = find_vlc_binary() if is_local_client else None
    playlist_content = build_playlist_content(items, is_local_client=is_local_client, host_url=host_url)

    if not is_local_client:
        # Remote client: return playlist stream URL for browser download / remote player
        first_id = items[0]["id"]
        return {
            "ok": True,
            "launched": False,
            "method": "playlist",
            "stream_url": f"/api/media/{first_id}/playlist.m3u",
            "filename": f"{title_hint}.m3u8",
            "items_count": len(items)
        }

    # Local host client:
    # If single item and not VLC, we can launch the file directly or via playlist
    temp_playlist = create_temp_playlist_file(playlist_content, title_hint=title_hint)

    if vlc_bin:
        port = get_free_port(8089)
        password = secrets.token_hex(8)

        cmd = [
            vlc_bin,
            temp_playlist,
            "--extraintf", "http",
            "--http-password", password,
            "--http-port", str(port),
        ]

        try:
            # VLC is a GUI player; do NOT pass CREATE_NO_WINDOW or SW_HIDE so the window displays
            proc = subprocess.Popen(cmd)
            tracker = VLCProgressTracker(
                process=proc,
                port=port,
                password=password,
                items=items,
                profile_id=profile_id,
                temp_files=[temp_playlist]
            )
            tracker.start()

            with _TRACKERS_LOCK:
                _ACTIVE_TRACKERS.append(tracker)

            # Auto-minimize CapsStream window so VLC player takes foreground
            def _delayed_minimize():
                time.sleep(0.35)
                minimize_capsstream_window()

            min_thread = threading.Thread(target=_delayed_minimize, name="VLCAutoMinimize", daemon=True)
            min_thread.start()

            return {
                "ok": True,
                "launched": True,
                "method": "vlc",
                "tracked": True,
                "player": "VLC Media Player",
                "file": os.path.basename(temp_playlist),
                "title": title_hint,
                "items_count": len(items)
            }
        except Exception as e:
            logger.warning(f"Failed to launch VLC with tracking: {e}. Falling back to system default.")

    # Fallback to system default player
    try:
        if sys.platform == "win32" and hasattr(os, "startfile"):
            # On Windows, startfile opens the file with whatever player is registered for .m3u8 (or single video)
            os.startfile(temp_playlist)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", temp_playlist])
        else:
            subprocess.Popen(["xdg-open", temp_playlist])

        # Schedule delayed cleanup after default player has read the file
        def _delayed_cleanup():
            try:
                if os.path.isfile(temp_playlist):
                    os.remove(temp_playlist)
            except OSError:
                pass
        t = threading.Timer(120.0, _delayed_cleanup)
        t.daemon = True
        t.start()

        return {
            "ok": True,
            "launched": True,
            "method": "system",
            "tracked": False,
            "player": "System Default Player",
            "file": os.path.basename(temp_playlist),
            "title": title_hint,
            "items_count": len(items)
        }
    except Exception as e:
        try:
            if os.path.isfile(temp_playlist):
                os.remove(temp_playlist)
        except OSError:
            pass
        return {"ok": False, "error": f"Failed to launch default player: {e}"}
