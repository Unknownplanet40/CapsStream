import os
import json
import urllib.request
import urllib.error
import ctypes
import subprocess

from dotenv import load_dotenv

from backend.proc_utils import CREATE_NO_WINDOW

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

# Secrets (API keys) live in .env / environment variables — never in config.json
load_dotenv(ENV_PATH)

DEFAULT_CONFIG = {
    "tmdb_api_key": "",
    "hide_system_files": False,
    "hide_unmounted_items": False,
    "browser": "edge",
    "launch_browser_on_start": True,
    "metadata_sources": {
        "enable_jikan": True
    },
    "port": 8000,
    "host": "127.0.0.1",
    "media_paths": {
        "movies": [],
        "series": [],
        "anime": []
    },
    "disabled_paths": {
        "movies": [],
        "series": [],
        "anime": []
    },
    "library": {
        "scan_on_startup": True,
        "scan_interval_hours": 0,
        "skip_patterns": "sample,trailer",
        "remove_missing_files": True
    },
    "updates": {
        "auto_check": True
    },
    "subtitles": {
        "auto_load": True,
        "preferred_language": "Auto",
        "opensubtitles_api_key": "",
        "auto_download": False,
        "appearance": {
            "fontSize": "1.1rem",
            "textColor": "#ffffff",
            "bgOpacity": 0.5
        }
    },
    "playback": {
        "auto_play_next": True,
        "auto_skip_intro": False,
        "seek_step": 10,
        "default_volume": 1,
        "default_speed": 1,
        "resume_behavior": "ask",
        "auto_fullscreen": False,
        "start_muted": False
    },
    "profiles": {
        "max_profiles": 8
    },
    "supabase_url": "",
    "supabase_anon_key": "",
    "features": {
        "requests": True,
        "online_requests": True
    }
}


# NOTE: The built-in "media/" default folders have been removed.
# Users provide their own media sources via Settings → Media Scanner Paths.

# In-process config cache: avoid reading config.json on every single request.
# TTL of 5 seconds is short enough to pick up manual edits quickly while
# eliminating the O(N-requests) disk reads that add up for common API calls.
_CONFIG_CACHE: dict = {"data": None, "ts": 0.0}
_CONFIG_CACHE_TTL = 5.0  # seconds

def load_config():
    """Load configuration from config.json with fallback defaults."""
    import time as _time
    now = _time.time()
    if _CONFIG_CACHE["data"] is not None and now - _CONFIG_CACHE["ts"] < _CONFIG_CACHE_TTL:
        return _CONFIG_CACHE["data"]

    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        result = dict(DEFAULT_CONFIG)
        _CONFIG_CACHE["data"] = result
        _CONFIG_CACHE["ts"] = now
        return result

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        merged = dict(DEFAULT_CONFIG)
        merged.update(data)

        # Deep merge nested dicts
        for key in ["metadata_sources", "media_paths", "disabled_paths", "library", "updates", "subtitles", "playback", "profiles", "features"]:
            if key in data and isinstance(data[key], dict):
                default_sub = dict(DEFAULT_CONFIG.get(key, {}))
                for sub_k, sub_v in data[key].items():
                    if isinstance(sub_v, dict) and sub_k in default_sub and isinstance(default_sub[sub_k], dict):
                        nested = dict(default_sub[sub_k])
                        nested.update(sub_v)
                        default_sub[sub_k] = nested
                    else:
                        default_sub[sub_k] = sub_v
                merged[key] = default_sub

        # Migration: strip the removed built-in "media/" default folders so
        # upgraded installs don't keep scanning them silently
        legacy_defaults = {
            "movies": {"media/movies"},
            "series": {"media/series"},
            "anime": {"media/anime"},
        }
        mp = merged.get("media_paths", {})
        for category, legacy in legacy_defaults.items():
            cat_list = mp.get(category)
            if isinstance(cat_list, list):
                filtered = [
                    p for p in cat_list
                    if str(p).replace("\\", "/").strip("/") not in legacy
                ]
                if len(filtered) != len(cat_list):
                    print(f"[Settings] Removed legacy built-in path(s) from '{category}'")
                    mp[category] = filtered

        # Migration: OMDb support was removed — drop stale keys from old configs
        if "omdb_api_key" in merged:
            merged.pop("omdb_api_key", None)
        if isinstance(merged.get("metadata_sources"), dict):
            merged["metadata_sources"].pop("enable_omdb", None)

        # Migration: remove legacy subtitles.font_size key in favor of subtitles.appearance.fontSize
        if isinstance(merged.get("subtitles"), dict) and "font_size" in merged["subtitles"]:
            merged["subtitles"].pop("font_size", None)

        # Secrets are provided via environment / .env — env values win over
        # anything stale in config.json, and empty config values get filled.
        for secret in ("tmdb_api_key", "supabase_url", "supabase_anon_key"):
            env_val = os.environ.get(secret.upper())
            if env_val:
                merged[secret] = env_val

        _CONFIG_CACHE["data"] = merged
        _CONFIG_CACHE["ts"] = now
        return merged
    except Exception as e:
        print(f"[Settings] Error loading config.json: {e}")
        return dict(DEFAULT_CONFIG)


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def set_file_hidden(path, hide=True):
    """Set (+h +s) or remove (-h -s) Windows hidden and system attributes on a file/directory."""
    if not os.path.exists(path):
        return
    try:
        if os.name == "nt":
            cmd = f'attrib {"+h +s" if hide else "-h -s"} "{path}"'
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        print(f"[Settings] Error setting hidden attribute on {path}: {e}")


def apply_system_file_hiding():
    """Hide (+h +s) or unhide (-h -s) system files/folders in the project root directory based on config.json setting."""
    config = load_config()
    should_hide = bool(config.get("hide_system_files", False))
    exempt_names = {"start.bat", "media"}

    try:
        if os.name == "nt":
            for entry in os.listdir(ROOT_DIR):
                full_path = os.path.join(ROOT_DIR, entry)
                if should_hide and entry.lower() not in exempt_names:
                    subprocess.run(f'attrib +h +s "{full_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW)
                else:
                    subprocess.run(f'attrib -h -s "{full_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW)

            # Ensure start.bat is explicitly unhidden (-h -s)
            start_bat = os.path.join(ROOT_DIR, "start.bat")
            if os.path.exists(start_bat):
                subprocess.run(f'attrib -h -s "{start_bat}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW)

        print(f"[Settings] System file hiding updated (hide_system_files={should_hide})")
    except Exception as e:
        print(f"[Settings] Error applying system file hiding: {e}")


def save_config(new_data):
    """Save configuration to config.json with deep dictionary merging."""
    config = load_config() if os.path.exists(CONFIG_PATH) else dict(DEFAULT_CONFIG)
    
    for k, v in new_data.items():
        if isinstance(v, dict) and k in config and isinstance(config[k], dict):
            if k == "subtitles" and "appearance" in v and isinstance(config[k].get("appearance"), dict):
                config[k]["appearance"].update(v["appearance"])
                for sub_k, sub_v in v.items():
                    if sub_k != "appearance":
                        config[k][sub_k] = sub_v
            else:
                config[k].update(v)
        else:
            config[k] = v

    try:
        set_file_hidden(CONFIG_PATH, hide=False)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # Apply system file hiding rules live
        apply_system_file_hiding()

        # Bust the in-process config cache so the next read picks up new values
        _CONFIG_CACHE["ts"] = 0.0

        return True, config
    except Exception as e:
        print(f"[Settings] Error saving config.json: {e}")
        return False, str(e)


def test_api_key(provider, api_key, url=None):
    """Test an API key live."""
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty"

    key = api_key.strip()
    if provider.lower() == "tmdb":
        endpoint = f"https://api.themoviedb.org/3/authentication?api_key={key}"
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "CapsStream/1.0"})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("success") is True:
                    return True, "TMDB API key valid"
                return False, data.get("status_message", "Invalid TMDB API key")
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                return False, err_body.get("status_message", f"HTTP Error {e.code}")
            except Exception:
                return False, f"HTTP Error {e.code}: Invalid TMDB API key"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    if provider.lower() == "supabase":
        from backend.utils.supabase_client import test_supabase_connection
        cfg = load_config()
        supabase_url = (url or "").strip() or cfg.get("supabase_url") or os.environ.get("SUPABASE_URL", "")
        return test_supabase_connection(url=supabase_url, key=key)


    return False, "Unknown provider"


def browse_folder_dialog():
    """
    Opens a native OS folder selection dialog using tkinter / PowerShell fallback.
    Returns the selected folder path string or None if cancelled.
    """
    selected_path = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path = filedialog.askdirectory(title="Select Media Folder")
        root.destroy()
    except Exception as e:
        print(f"[Settings] Tkinter folder dialog error: {e}")

    if not selected_path and os.name == "nt":
        try:
            ps_cmd = (
                'Add-Type -AssemblyName System.Windows.Forms; '
                '$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; '
                '$dialog.Description = "Select Media Folder"; '
                'if ($dialog.ShowDialog() -eq "OK") { Write-Output $dialog.SelectedPath }'
            )
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                 creationflags=CREATE_NO_WINDOW)
            out = res.stdout.strip()
            if out:
                selected_path = out
        except Exception as e:
            print(f"[Settings] PowerShell folder dialog error: {e}")

    if selected_path:
        selected_path = os.path.normpath(selected_path).replace("\\", "/")
    return selected_path


def validate_media_paths(paths_list):
    """
    Validates a list of media folder paths.
    Returns a dict mapping path -> { 'accessible': bool, 'video_count': int, 'absolute_path': str }
    """
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
    results = {}

    for rel_or_abs in paths_list:
        if not rel_or_abs:
            continue

        abs_p = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(ROOT_DIR, rel_or_abs)
        abs_p = os.path.normpath(abs_p)

        exists = os.path.exists(abs_p) and os.path.isdir(abs_p)
        count = 0

        if exists:
            try:
                for root, dirs, files in os.walk(abs_p):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in video_exts:
                            count += 1
            except Exception:
                pass

        results[rel_or_abs] = {
            "accessible": exists,
            "video_count": count,
            "absolute_path": abs_p
        }

    return results


def find_installed_pwa(target_url=None):
    """
    Search for an installed CapsStream Desktop PWA (Edge or Chrome Web Application)
    matching the target URL/port. Returns launch information dict if found, otherwise None.
    """
    if os.name != "nt":
        return None

    import urllib.parse
    target_port = None
    if target_url:
        try:
            parsed = urllib.parse.urlparse(target_url)
            target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except Exception:
            pass

    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")

    # Inspect Chromium Preferences to map App IDs to their actual installed start URLs
    browser_user_data = [
        ("edge", os.path.join(localappdata, r"Microsoft\Edge\User Data")),
        ("chrome", os.path.join(localappdata, r"Google\Chrome\User Data")),
    ]

    installed_apps = {}  # app_id -> { browser, profile, name, url, port }
    for browser_name, user_data_root in browser_user_data:
        if not os.path.exists(user_data_root):
            continue
        try:
            for prof in os.listdir(user_data_root):
                pdir = os.path.join(user_data_root, prof)
                pref_file = os.path.join(pdir, "Preferences")
                if not os.path.isfile(pref_file):
                    continue
                try:
                    with open(pref_file, "r", encoding="utf-8", errors="ignore") as f:
                        pref_data = json.load(f)
                    ext_settings = pref_data.get("extensions", {}).get("settings", {})
                    for app_id, app_info in ext_settings.items():
                        manifest = app_info.get("manifest", {})
                        app_name = (manifest.get("name") or "").strip()
                        app_url = (manifest.get("app", {}).get("launch", {}).get("web_url") or manifest.get("start_url") or "").strip()
                        if "capsstream" in app_name.lower() or "capsstream" in app_url.lower():
                            port = None
                            try:
                                port = urllib.parse.urlparse(app_url).port
                            except Exception:
                                pass
                            installed_apps[app_id] = {
                                "browser": browser_name,
                                "profile": prof,
                                "name": app_name,
                                "url": app_url,
                                "port": port,
                            }
                except Exception:
                    pass
        except Exception:
            pass

    # Match installed PWA strictly against target port / URL
    for app_id, info in installed_apps.items():
        if target_port is not None:
            if info.get("port") == target_port or (target_url and target_url.lower() in (info.get("url") or "").lower()):
                return {
                    "type": "app_id",
                    "browser": info["browser"],
                    "app_id": app_id,
                    "profile": info["profile"],
                    "name": info["name"],
                    "url": info["url"],
                }
        elif not target_url:
            return {
                "type": "app_id",
                "browser": info["browser"],
                "app_id": app_id,
                "profile": info["profile"],
                "name": info["name"],
                "url": info["url"],
            }

    return None


def is_browser_already_open(url):
    """Check if a standalone browser process (Edge/Chrome/Brave/Opera) or PWA is already open visiting the app URL."""
    if os.name != "nt":
        return False

    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        port_str = f":{target_port}"
        url_clean = f"{parsed.hostname}{port_str}".lower()
    except Exception:
        target_port = 8000
        port_str = ":8000"
        url_clean = "127.0.0.1:8000"

    url_full = url.lower()

    # 1. Inspect visible windows owned strictly by web browser processes (msedge, chrome, etc.)
    try:
        import ctypes
        EnumWindows = ctypes.windll.user32.EnumWindows
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        OpenProcess = ctypes.windll.kernel32.OpenProcess
        CloseHandle = ctypes.windll.kernel32.CloseHandle
        GetModuleBaseNameW = ctypes.windll.psapi.GetModuleBaseNameW

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010

        windows = []
        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buff, length + 1)
                    pid = ctypes.c_ulong()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    
                    pname = ""
                    hProcess = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
                    if hProcess:
                        p_buff = ctypes.create_unicode_buffer(260)
                        if GetModuleBaseNameW(hProcess, None, p_buff, 260):
                            pname = p_buff.value
                        CloseHandle(hProcess)
                    windows.append((hwnd, pname.lower(), buff.value, pid.value))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        EnumWindows(WNDENUMPROC(foreach_window), 0)

        ignore_markers = ("github", "google search", "bing search", "duckduckgo", "reddit", "commit", "action", "workflow", "pull request", "issue", "blob", "tree", "antigravity", "visual studio")
        for hwnd, pname, title, pid_val in windows:
            # Strictly restrict detection to actual browser processes
            if any(b in pname for b in ["msedge", "chrome", "brave", "opera", "vivaldi", "firefox"]):
                t_lower = title.lower()
                if any(ign in t_lower for ign in ignore_markers):
                    continue
                # Check for matching URL or port-specific CapsStream window
                if url_clean in t_lower or url_full in t_lower or (port_str in t_lower and "capsstream" in t_lower):
                    try:
                        # Bring existing window to foreground
                        SW_RESTORE = 9
                        SW_SHOW = 5
                        if ctypes.windll.user32.IsIconic(hwnd):
                            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                        else:
                            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
                        try:
                            ctypes.windll.user32.AllowSetForegroundWindow(-1)
                        except Exception:
                            pass
                        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                        ctypes.windll.user32.BringWindowToTop(hwnd)
                    except Exception:
                        pass
                    return True
    except Exception:
        pass

    # 2. Commandline Inspection Fallback (strictly checking target URL / port)
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"],
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        ).decode("utf-8", errors="ignore")
        
        target = f"--app={url}".lower()

        for line in out.splitlines():
            l = line.lower()
            if "python" in l or "cmd.exe" in l or "powershell" in l:
                continue
            if ("msedge" in l or "chrome" in l or "brave" in l) and target in l:
                return True
    except Exception:
        pass

    return False


def is_server_running(url=None):
    """Check if a CapsStream server instance is already running and responding, or if a server process is active."""
    import urllib.request
    import urllib.error
    import ssl
    import ctypes

    # 1. Quick check for Windows named mutex held by active server process
    if os.name == "nt":
        try:
            h_mutex = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "CapsStream_Server_Instance_Mutex")
            if h_mutex:
                ctypes.windll.kernel32.CloseHandle(h_mutex)
                return True
        except Exception:
            pass

    # 2. HTTP health check against local endpoint
    if not url:
        config = load_config()
        host = (config.get("host") or "127.0.0.1").strip()
        port = int(config.get("port") or 8000)
        proto = "https" if config.get("ssl", False) else "http"
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        url = f"{proto}://{display_host}:{port}"

    health_url = f"{url.rstrip('/')}/api/health"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(health_url, headers={"User-Agent": "CapsStream-Launcher"})
        with urllib.request.urlopen(req, timeout=1.5, context=ctx) as resp:
            return resp.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def launch_browser():
    """Launch the application URL in the installed PWA or preferred browser window (defaults to Microsoft Edge)."""
    import subprocess
    import webbrowser

    config = load_config()

    # Respect the user's "open browser on launch" preference
    if not config.get("launch_browser_on_start", True):
        print("[Launcher] launch_browser_on_start is disabled — skipping browser launch")
        return

    browser_choice = str(config.get("browser", "edge")).lower().strip()
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8000)
    proto = "https" if config.get("ssl", False) else "http"
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"{proto}://{display_host}:{port}"

    # Guard: Check if standalone browser window / PWA is already open for this URL
    if is_browser_already_open(url):
        print(f"[Launcher] CapsStream window is already open ({url}). Reusing existing window for server auto-reconnect.")
        return

    # Check for installed Desktop PWA for this URL
    pwa = find_installed_pwa(url)
    if pwa:
        try:
            if pwa["type"] == "shortcut":
                os.startfile(pwa["path"])
                print(f"[Launcher] Opened installed Desktop PWA shortcut ({pwa['name']})")
                return
            elif pwa["type"] == "app_id":
                exe_name = "msedge.exe" if pwa["browser"] == "edge" else "chrome.exe"
                cmd = f'start {exe_name} --profile-directory="{pwa.get("profile", "Default")}" --app-id={pwa["app_id"]} --start-maximized'
                subprocess.Popen(cmd, shell=True, creationflags=CREATE_NO_WINDOW)
                print(f"[Launcher] Opened installed {pwa['browser'].title()} PWA (app-id: {pwa['app_id']})")
                return
        except Exception as e:
            print(f"[Launcher] Notice: could not launch PWA directly ({e}), falling back to standalone window.")

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    if browser_choice == "edge":
        for path in edge_paths:
            if os.path.exists(path):
                subprocess.Popen([path, f"--app={url}", "--start-maximized"])
                print(f"[Launcher] Opened Microsoft Edge in standalone app mode ({url})")
                return
        if os.name == "nt":
            subprocess.Popen(f'start msedge --app={url} --start-maximized', shell=True,
                             creationflags=CREATE_NO_WINDOW)
            print(f"[Launcher] Launched msedge ({url})")
            return

    elif browser_choice == "chrome":
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path, f"--app={url}", "--start-maximized"])
                print(f"[Launcher] Opened Google Chrome in standalone app mode ({url})")
                return
        if os.name == "nt":
            subprocess.Popen(f'start chrome --app={url} --start-maximized', shell=True,
                             creationflags=CREATE_NO_WINDOW)
            print(f"[Launcher] Launched chrome ({url})")
            return

    # Fallback to system default browser
    webbrowser.open(url)
    print(f"[Launcher] Opened system default browser ({url})")


def get_cache_info():
    """Calculate storage usage for metadata images and JSON cache files."""
    cache_dir = os.path.join(ROOT_DIR, "data", "metadata")
    total_size = 0
    file_count = 0
    if os.path.exists(cache_dir):
        for root, dirs, files in os.walk(cache_dir):
            for f in files:
                file_count += 1
                fp = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fp)
                except Exception:
                    pass

    size_mb = round(total_size / (1024 * 1024), 2)
    formatted = f"{size_mb} MB" if size_mb >= 1 else f"{round(total_size / 1024, 1)} KB"
    return {
        "file_count": file_count,
        "size_bytes": total_size,
        "size_formatted": formatted
    }


def clear_cache():
    """Wipe cached images and temporary metadata files, and reset matched status in DB so scanning refetches fresh metadata."""
    cache_dir = os.path.join(ROOT_DIR, "data", "metadata")
    cleared_count = 0
    if os.path.exists(cache_dir):
        for root, dirs, files in os.walk(cache_dir):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                    cleared_count += 1
                except Exception:
                    pass

    # Reset tmdb_matched status in database so scanner will re-fetch metadata
    try:
        from backend.db import get_conn
        conn = get_conn()
        conn.execute("""
            UPDATE media SET
                tmdb_matched = 0,
                poster_path = NULL,
                backdrop_path = NULL,
                logo_path = NULL,
                overview = NULL,
                tagline = NULL,
                cast_json = NULL,
                genres = NULL,
                rating = 0,
                vote_count = 0
            WHERE manually_overridden = 0
        """)
        conn.commit()
        conn.close()
        print("[Settings] Reset database media matching status for fresh rescan.")
    except Exception as e:
        print("[Settings] Failed to reset media matching status in DB:", e)

    return cleared_count


def reset_application(clear_media_files=False):
    """Perform a fresh start reset: unlinks external paths, clears media path config, clears metadata cache, resets database, and optionally clears leftover files in the local 'media' folder."""
    clear_cache()

    # Reset config media_paths to empty (users provide their own sources)
    config = load_config()
    config["media_paths"] = {
        "movies": [],
        "series": [],
        "anime": []
    }
    config["disabled_paths"] = {
        "movies": [],
        "series": [],
        "anime": []
    }
    config["library"] = dict(DEFAULT_CONFIG.get("library", {}))
    save_config(config)

    # Clear custom avatars
    avatars_dir = os.path.join(ROOT_DIR, "data", "avatars")
    if os.path.isdir(avatars_dir):
        for root, dirs, files in os.walk(avatars_dir):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass

    # Clear state files
    for state_file in ["pin_fails.json", "library_state.json", "scan_schedule.json"]:
        p = os.path.join(ROOT_DIR, "data", state_file)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    # Thoroughly wipe all database tables (works even if database file is locked by open connections)
    try:
        from backend.db import get_conn
        conn = get_conn()
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = [
            "watch_progress", "collection_items", "collections", "favorites",
            "achievements", "kids_overrides", "playlist_items", "playlists",
            "media", "profiles"
        ]
        for t in tables:
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        try:
            conn.execute("VACUUM")
        except Exception:
            pass
    except Exception as e:
        print("[Settings] Database reset table wipe notice:", e)

    # Attempt database file removal if not locked
    db_path = os.path.join(ROOT_DIR, "data", "capsstream.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            for extra in [db_path + "-wal", db_path + "-shm"]:
                if os.path.exists(extra):
                    os.remove(extra)
        except Exception:
            pass

    # Optionally delete leftover files inside the local "media" folder
    # (legacy built-in folder — may still exist from previous installs)
    if clear_media_files:
        legacy_media_dir = os.path.join(ROOT_DIR, "media")
        if os.path.isdir(legacy_media_dir):
            for root, dirs, files in os.walk(legacy_media_dir):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass

    from backend.db import init_db
    init_db()
    return True



