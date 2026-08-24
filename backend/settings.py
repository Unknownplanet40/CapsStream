import os
import json
import urllib.request
import urllib.error
import ctypes
import subprocess

from dotenv import load_dotenv

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

# Secrets (API keys) live in .env / environment variables — never in config.json
load_dotenv(ENV_PATH)

DEFAULT_CONFIG = {
    "tmdb_api_key": "",
    "omdb_api_key": "",
    "hide_system_files": False,
    "hide_unmounted_items": False,
    "browser": "edge",
    "metadata_sources": {
        "enable_jikan": True,
        "enable_omdb": True
    },
    "port": 8000,
    "host": "127.0.0.1",
    "media_paths": {
        "movies": [],
        "series": [],
        "anime": []
    },
    "subtitles": {
        "auto_load": True,
        "preferred_language": "Auto",
        "font_size": "normal",
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
        "default_volume": 1
    }
}

# NOTE: The built-in "media/" default folders have been removed.
# Users provide their own media sources via Settings → Media Scanner Paths.

def load_config():
    """Load configuration from config.json with fallback defaults."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        merged = dict(DEFAULT_CONFIG)
        merged.update(data)

        # Deep merge nested dicts
        for key in ["metadata_sources", "media_paths", "subtitles", "playback"]:
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

        # Secrets are provided via environment / .env — env values win over
        # anything stale in config.json, and empty config values get filled.
        for secret in ("tmdb_api_key", "omdb_api_key"):
            env_val = os.environ.get(secret.upper())
            if env_val:
                merged[secret] = env_val

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
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                    subprocess.run(f'attrib +h +s "{full_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(f'attrib -h -s "{full_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Ensure start.bat is explicitly unhidden (-h -s)
            start_bat = os.path.join(ROOT_DIR, "start.bat")
            if os.path.exists(start_bat):
                subprocess.run(f'attrib -h -s "{start_bat}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

        return True, config
    except Exception as e:
        print(f"[Settings] Error saving config.json: {e}")
        return False, str(e)


def test_api_key(provider, api_key):
    """Test a TMDb or OMDb API key live."""
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty"

    key = api_key.strip()
    if provider.lower() == "tmdb":
        url = f"https://api.themoviedb.org/3/authentication?api_key={key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CapsStream/1.0"})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("success") is True:
                    return True, "TMDB API key valid ✓"
                return False, data.get("status_message", "Invalid TMDB API key")
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                return False, err_body.get("status_message", f"HTTP Error {e.code}")
            except Exception:
                return False, f"HTTP Error {e.code}: Invalid TMDB API key"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    elif provider.lower() == "omdb":
        url = f"https://www.omdbapi.com/?apikey={key}&t=Inception"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CapsStream/1.0"})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("Response") == "True":
                    return True, "OMDB API key valid ✓"
                return False, data.get("Error", "Invalid OMDB API key")
        except Exception as e:
            return False, f"OMDB connection error: {str(e)}"

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
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
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


def is_browser_already_open(url):
    """Check if a standalone browser process (Edge/Chrome/Brave/Opera) is already open visiting the app URL."""
    if os.name != "nt":
        return False

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

        url_clean = url.replace("http://", "").replace("https://", "").lower()
        url_full = url.lower()

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
                    windows.append((pname.lower(), buff.value))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        EnumWindows(WNDENUMPROC(foreach_window), 0)

        for pname, title in windows:
            # Strictly restrict detection to actual browser processes
            if any(b in pname for b in ["msedge", "chrome", "brave", "opera", "vivaldi"]):
                t_lower = title.lower()
                # STRICT: the window title must contain the FULL app URL
                # (e.g. "127.0.0.1:8000"). Loose matches like the word
                # "capsstream" or a bare "localhost" caused false positives
                # that suppressed launching.
                if url_clean in t_lower or url_full in t_lower:
                    return True
    except Exception:
        pass

    # 2. Commandline Inspection Fallback
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="ignore")
        
        target = f"--app={url}".lower()

        for line in out.splitlines():
            l = line.lower()
            if "python" in l or "cmd.exe" in l or "powershell" in l:
                continue
            # STRICT: require the exact --app flag for THIS URL. Edge keeps
            # background processes (with their original command lines) alive
            # after the window is closed — a bare host match caused false
            # positives that suppressed launching.
            if ("msedge" in l or "chrome" in l or "brave" in l) and target in l:
                return True
    except Exception:
        pass

    return False


def launch_browser():
    """Launch the application URL in the browser specified by config.json (defaults to Microsoft Edge)."""
    import subprocess
    import webbrowser

    config = load_config()
    browser_choice = str(config.get("browser", "edge")).lower().strip()
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8000)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"

    # Guard: Check if standalone browser window is already open for this URL
    if is_browser_already_open(url):
        print(f"[Launcher] Standalone browser window is already open ({url}). Reusing existing window for server auto-reconnect.")
        return

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
            subprocess.Popen(f'start msedge --app={url} --start-maximized', shell=True)
            print(f"[Launcher] Launched msedge ({url})")
            return

    elif browser_choice == "chrome":
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path, f"--app={url}", "--start-maximized"])
                print(f"[Launcher] Opened Google Chrome in standalone app mode ({url})")
                return
        if os.name == "nt":
            subprocess.Popen(f'start chrome --app={url} --start-maximized', shell=True)
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
    save_config(config)

    # Delete database file
    db_path = os.path.join(ROOT_DIR, "data", "capsstream.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
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


