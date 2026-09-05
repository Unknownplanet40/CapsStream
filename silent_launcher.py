"""
silent_launcher.py — Windowless CapsStream launcher.

Started by "Start CapsStream Silent.vbs" (which runs this file under
pythonw.exe — no console is ever shown). Flow:

  1. Pre-flight: apply pending update swaps, system-file hiding, and a
     quiet pip install (all output captured to logs/capsstream_YYYYMMDD.log)
  2. Spawn the Flask server as a background process (pythonw.exe app.py)
  3. Poll http://127.0.0.1:<port>/ until it responds (or fail visibly)
  4. Open the app-mode browser window (dedicated profile so the process
     lifetime exactly matches the window)
  5. Wait for that window to close, then tree-kill the server (and any
     children — ffmpeg transcoders, etc.) so nothing is left running.

The original start.bat remains the verbose/debug fallback launcher.
"""

import os
import sys
import json
import time
import base64
import pathlib
import subprocess
import ctypes
import threading
import traceback
import urllib.request
import urllib.error
from datetime import datetime

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, "winpython", "python", "python.exe")
PYTHONW = os.path.join(ROOT, "winpython", "python", "pythonw.exe")
APP_SCRIPT = os.path.join(ROOT, "app.py")
LOG_DIR = os.path.join(ROOT, "logs")
APP_PROFILE_DIR = os.path.join(ROOT, "data", "app_profile")
HEALTH_TIMEOUT_SEC = 60
HEALTH_POLL_INTERVAL = 0.5


def log(msg):
    """Append a line to the dated log file."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(LOG_DIR, f"capsstream_{datetime.now():%Y%m%d}.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [Launcher] {msg}\n")
    except Exception:
        pass


def fail(message):
    """Log + show a visible error dialog (the only window we ever raise)."""
    log("FATAL: " + message)
    send_toast("CapsStream failed to start", message.splitlines()[0][:120])
    try:
        ctypes.windll.user32.MessageBoxW(
            None, message + "\n\nDetails were written to logs/ (see the newest capsstream_*.log).",
            "CapsStream — Launch Failed", 0x10 | 0x0  # MB_ICONERROR
        )
    except Exception:
        pass
    sys.exit(1)


# ─── Native toast notifications (WinRT via PowerShell — no dependencies) ─────

APP_ID = "CapsStream"


def register_app_identity():
    """
    Register the CapsStream AppUserModelID under HKCU (no admin required)
    so toasts appear as 'CapsStream' with the app icon, per the user's
    reference (tempfile/CustomAPPID.ps1). Idempotent.
    """
    try:
        import winreg
        key_path = r"Software\Classes\AppUserModelId\CapsStream"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "CapsStream")
            icon = os.path.join(ROOT, "static", "img", "favicon.png")
            if os.path.isfile(icon):
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon)
    except Exception as e:
        log(f"App identity registration skipped: {e}")


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def send_toast(title, message):
    """
    Show a native Windows toast notification as 'CapsStream' using the
    built-in WinRT toast API via PowerShell — no BurntToast/module install.
    The app icon is embedded in the toast itself (appLogoOverride = the
    image slot on the left side of the notification).
    Failures are logged but never fatal.
    """
    if os.name != "nt":
        return
    try:
        register_app_identity()
        icon = os.path.join(ROOT, "static", "img", "favicon.png")
        image_el = ""
        if os.path.isfile(icon):
            icon_uri = pathlib.Path(icon).as_uri()
            image_el = f'<image placement="appLogoOverride" src="{_xml_escape(icon_uri)}" />'
        xml = (
            '<toast><visual><binding template="ToastGeneric">'
            f'{image_el}'
            f'<text>{_xml_escape(title)}</text>'
            f'<text>{_xml_escape(message)}</text>'
            '</binding></visual></toast>'
        )
        # Single-quote literal in PS: escape embedded quotes by doubling
        xml_ps = xml.replace("'", "''")
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
            f"$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            f"$xml.LoadXml('{xml_ps}')\n"
            "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($toast)\n"
        )
        b64 = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", b64],
            creationflags=CREATE_NO_WINDOW, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log(f"Toast sent: {title}")
    except Exception as e:
        log(f"Toast notification failed: {e}")


def read_config():
    cfg_path = os.path.join(ROOT, "config.json")
    cfg = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception as e:
            log(f"Could not parse config.json ({e}) — using defaults")
    return cfg


def server_url(cfg):
    host = (cfg.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(cfg.get("port") or 8000)
    proto = "https" if cfg.get("ssl", False) else "http"
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    return f"{proto}://{display_host}:{port}", display_host, port


def server_responding(url):
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "CapsStream-Launcher"})
        with urllib.request.urlopen(req, timeout=2, context=ctx) as resp:
            return resp.status < 500
    except urllib.error.HTTPError:
        return True  # server answered — it's up
    except Exception:
        return False


def pre_flight():
    """Pending update swaps, system-file hiding, quiet pip install."""
    log("Pre-flight starting")
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    try:
        from backend.updater import apply_pending_swaps
        applied = apply_pending_swaps()
        if applied:
            log(f"Applied {applied} pending update file(s)")
    except Exception as e:
        log(f"Pending update swap step skipped: {e}")

    try:
        from backend.settings import apply_system_file_hiding
        apply_system_file_hiding()
    except Exception as e:
        log(f"System file hiding step skipped: {e}")

    if os.path.isfile(PYTHON):
        req_file = os.path.join(ROOT, "requirements.txt")
        stamp_file = os.path.join(ROOT, "data", "pip_stamp")
        _run_pip = True
        if os.path.isfile(req_file):
            try:
                import hashlib as _hl
                with open(req_file, "rb") as _f:
                    current_hash = _hl.md5(_f.read()).hexdigest()
                if os.path.isfile(stamp_file):
                    with open(stamp_file, encoding="utf-8") as _sf:
                        stored_hash = _sf.read().strip()
                    if stored_hash == current_hash:
                        log("requirements.txt unchanged — skipping pip install")
                        _run_pip = False
            except Exception as _e:
                log(f"pip stamp check failed ({_e}) — running pip to be safe")
        if _run_pip:
            try:
                subprocess.run(
                    [PYTHON, "-m", "pip", "install", "-q", "-r", req_file],
                    cwd=ROOT, timeout=600,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                # Write the stamp so subsequent launches can skip this step
                try:
                    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
                    with open(stamp_file, "w", encoding="utf-8") as _sf:
                        _sf.write(current_hash if os.path.isfile(req_file) else "")
                except Exception:
                    pass
                log("Dependency check complete")
            except Exception as e:
                log(f"pip install step failed (continuing): {e}")
    else:
        fail(f"Python interpreter not found at:\n{PYTHON}")


def start_server(cfg):
    """Spawn the Flask server under pythonw (no window). Returns the Popen."""
    log_file = os.path.join(LOG_DIR, f"capsstream_{datetime.now():%Y%m%d}.log")
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    log_handle = open(log_file, "a", encoding="utf-8", buffering=1)
    log("Spawning server process (pythonw app.py)")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [PYTHONW, APP_SCRIPT],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    return proc


def find_browser_exe(choice):
    """Mirror launch_browser()'s Edge/Chrome path selection."""
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    candidates = []
    if choice == "edge":
        candidates = edge_paths + chrome_paths  # fall back to the other Chromium browser
    elif choice == "chrome":
        candidates = chrome_paths + edge_paths
    else:  # "system" — no tracked app window possible; caller falls back
        return None
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def bring_window_to_foreground(hwnd):
    """Restore (if minimized) and bring the target window to foreground."""
    if not hwnd or os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        SW_SHOW = 5
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        try:
            user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass

        # Windows foreground lock bypass via Alt key simulation
        user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
        user32.BringWindowToTop(hwnd)
        return True
    except Exception as e:
        log(f"Notice: could not bring window {hwnd} to foreground: {e}")
        return False


def is_capsstream_title(title: str, pname: str, url_clean: str = "127.0.0.1:8000", url_alt: str = "localhost:8000", port_str: str = ":8000") -> bool:
    """
    Determine whether a window title and browser process belong to CapsStream.
    Strictly filters out unrelated browser tabs/windows (e.g. GitHub repos,
    search engine queries, documentation, IDEs) mentioning 'CapsStream'.
    """
    known_browsers = (
        "msedge", "chrome", "brave", "opera", "vivaldi",
        "firefox", "arc", "applicationframehost"
    )
    pname_lower = (pname or "").lower()
    if not any(b in pname_lower for b in known_browsers):
        return False

    t = (title or "").strip().lower()
    if not t:
        return False

    ignore_keywords = (
        "github", "google search", "bing search", "duckduckgo",
        "reddit", "gitlab", "stackoverflow", "commit", "action",
        "workflow", "pull request", "issue", "blob", "tree",
        "antigravity", "visual studio"
    )
    if any(ign in t for ign in ignore_keywords):
        return False

    # Matches:
    # 1. Standalone app window: title is exactly "capsstream"
    # 2. CapsStream browser tab: title starts with "capsstream" followed by standard separator
    # 3. URL match: contains 127.0.0.1:8000 or localhost:8000 without search engine markers
    is_exact = (t == "capsstream")
    is_browser_tab = (
        t.startswith("capsstream -")
        or t.startswith("capsstream —")
        or t.startswith("capsstream |")
        or t.startswith("capsstream •")
    )
    is_url_match = (
        (url_clean in t or url_alt in t or (port_str in t and "capsstream" in t))
        and not any(ign in t for ign in ("search", "google", "bing", "github"))
    )

    return is_exact or is_browser_tab or is_url_match


def find_capsstream_window(url, browser_proc=None):
    """
    Locate an existing visible or minimized window displaying CapsStream.
    Returns the HWND of the window if found, otherwise None.
    Strictly filters out unrelated browser windows/tabs (e.g. GitHub repos,
    search results, dev tools) that happen to mention 'CapsStream' in their title.
    """
    if os.name != "nt":
        return None
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        port_str = f":{target_port}"
        url_clean = f"{parsed.hostname}{port_str}".lower()
        url_alt = f"localhost{port_str}".lower()

        user32 = ctypes.windll.user32
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32

        GetWindowTextW = user32.GetWindowTextW
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        IsWindowVisible = user32.IsWindowVisible
        IsIconic = user32.IsIconic
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        OpenProcess = kernel32.OpenProcess
        CloseHandle = kernel32.CloseHandle
        GetModuleBaseNameW = psapi.GetModuleBaseNameW

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010

        target_pid = browser_proc.pid if (browser_proc is not None and browser_proc.poll() is None) else None
        found_hwnd = [None]

        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd) or IsIconic(hwnd):
                length = GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()

                    pid = ctypes.c_ulong()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                    # 1. Exact PID match from our tracked browser process
                    if target_pid is not None and pid.value == target_pid:
                        found_hwnd[0] = hwnd
                        return False

                    # 2. Check process name for browser windows
                    pname = ""
                    hProcess = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
                    if hProcess:
                        p_buff = ctypes.create_unicode_buffer(260)
                        if GetModuleBaseNameW(hProcess, None, p_buff, 260):
                            pname = p_buff.value.lower()
                        CloseHandle(hProcess)

                    if is_capsstream_title(title, pname, url_clean, url_alt, port_str):
                        found_hwnd[0] = hwnd
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(WNDENUMPROC(foreach_window), 0)
        return found_hwnd[0]
    except Exception as e:
        log(f"Window detection notice: {e}")
        return None


def is_capsstream_window_visible(url, browser_proc=None):
    """
    Check if any visible or minimized browser window or PWA window is displaying CapsStream.
    Returns True if at least one CapsStream window exists (active or minimized).
    """
    return find_capsstream_window(url, browser_proc) is not None


def launch_app_window(cfg, url):
    """Open the tracked app-mode browser window or installed PWA. Returns the Popen or None."""
    # Check for installed Desktop PWA for THIS specific URL/port
    try:
        from backend.settings import find_installed_pwa
        pwa = find_installed_pwa(url)
        if pwa:
            creationflags = 0x08000000 if os.name == "nt" else 0
            if pwa["type"] == "shortcut":
                log(f"Launching installed PWA shortcut: {pwa['name']}")
                os.startfile(pwa["path"])
                return None
            elif pwa["type"] == "app_id":
                exe = find_browser_exe(pwa["browser"])
                if exe:
                    log(f"Launching installed {pwa['browser'].title()} PWA (app-id: {pwa['app_id']})")
                    return subprocess.Popen(
                        [exe, f"--profile-directory={pwa.get('profile', 'Default')}",
                         f"--app-id={pwa['app_id']}", "--start-maximized"],
                        creationflags=creationflags,
                    )
        if pwa:
            return None
    except Exception as e:
        log(f"PWA detection notice: {e}")

    choice = str(cfg.get("browser", "edge")).lower().strip()
    exe = find_browser_exe(choice)
    if not exe:
        log(f"Browser choice '{choice}' has no trackable app-mode exe — opening system default (untracked)")
        os.startfile(url)
        return None

    os.makedirs(APP_PROFILE_DIR, exist_ok=True)
    log(f"Launching standalone app window for {url} ({os.path.basename(exe)})")
    creationflags = 0x08000000 if os.name == "nt" else 0
    return subprocess.Popen(
        [exe, f"--app={url}", "--user-data-dir=" + APP_PROFILE_DIR,
         "--no-first-run", "--no-default-browser-check", "--disable-extensions",
         "--autoplay-policy=no-user-gesture-required",
         "--start-maximized"],
        creationflags=creationflags,
    )


def kill_tree(pid):
    """Kill a process and all of its children (ffmpeg, pip, etc.)."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log(f"Killed process tree for PID {pid}")
    except Exception as e:
        log(f"Failed to kill PID {pid}: {e}")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    log("=" * 50)
    log("CapsStream silent launcher starting")

    from_restart = "--restarted" in sys.argv or "--from-restart" in sys.argv or "--no-browser" in sys.argv

    if not os.path.isfile(PYTHONW):
        fail(f"pythonw.exe not found at:\n{PYTHONW}")
    if not os.path.isfile(APP_SCRIPT):
        fail(f"app.py not found at:\n{APP_SCRIPT}")

    cfg = read_config()
    url, poll_host, poll_port = server_url(cfg)

    pre_flight()

    # Re-run safety: if a server is already up, just attach to it
    already_up = server_responding(url)
    server = None
    if already_up:
        log(f"Server already responding at {url} — attaching to it")
    else:
        server = start_server(cfg)
        log(f"Server PID {server.pid} — waiting for {url} to come up")

        deadline = time.time() + HEALTH_TIMEOUT_SEC
        while time.time() < deadline:
            if server.poll() is not None:
                fail(
                    f"The server process exited early (code {server.returncode}).\n"
                    "Another program may be using the port, or the server hit an error."
                )
            if server_responding(url):
                already_up = True
                break
            time.sleep(HEALTH_POLL_INTERVAL)

        if not already_up:
            kill_tree(server.pid)
            fail(f"The server did not respond within {HEALTH_TIMEOUT_SEC} seconds.\n"
                 f"Check http://{poll_host}:{poll_port} and the newest log in logs/")

    log(f"Server is live at {url}")

    # Initialize native System Tray companion
    tray = None
    exit_requested = threading.Event()
    browser_state = {"proc": None}

    def do_open_ui():
        log("Opening CapsStream UI from tray or launcher")
        hwnd = find_capsstream_window(url, browser_state.get("proc"))
        if hwnd:
            log(f"Found existing CapsStream window (HWND {hwnd}) — bringing to foreground")
            if bring_window_to_foreground(hwnd):
                return
            log("Could not bring existing window to foreground — launching fresh window")
        log(f"Launching standalone app window for {url}")
        browser_state["proc"] = launch_app_window(cfg, url)

    def do_restart_server():
        nonlocal server
        log("Server restart requested via tray")
        send_toast("CapsStream", "Restarting media server...")
        if server is not None and server.poll() is None:
            kill_tree(server.pid)
            server = None

        server = start_server(cfg)
        deadline = time.time() + HEALTH_TIMEOUT_SEC
        restarted = False
        while time.time() < deadline:
            if server_responding(url):
                restarted = True
                break
            time.sleep(HEALTH_POLL_INTERVAL)

        if restarted:
            raw_host = (cfg.get("host") or "127.0.0.1").strip()
            is_lan = raw_host in ("0.0.0.0", "::")
            restart_label = f"Serving on LAN: {lan_url} (Local: {url})" if is_lan else f"Serving at {url}"
            log(f"Server restarted successfully — {restart_label}")
            send_toast("CapsStream Ready", f"Server restarted: {restart_label}")
        else:
            log("Server failed to respond after restart")
            send_toast("CapsStream Error", "Server failed to respond after restart")

    def do_exit():
        log("Clean exit requested via tray")
        exit_requested.set()

    try:
        from backend.tray import CapsStreamTray, get_lan_url
        lan_url = get_lan_url(poll_port, ssl=cfg.get("ssl", False))
        icon_file = os.path.join(ROOT, "static", "img", "favicon.png")
        tray = CapsStreamTray(
            local_url=url,
            lan_url=lan_url,
            on_open_ui=do_open_ui,
            on_restart=do_restart_server,
            on_exit=do_exit,
            icon_path=icon_file if os.path.isfile(icon_file) else None,
            media_paths=cfg.get("media_paths", {}),
            log_dir=LOG_DIR,
            data_dir=os.path.join(ROOT, "data"),
        )
        tray.start()
        log(f"System tray companion initialized (LAN URL: {lan_url})")
    except Exception as e:
        log(f"Tray initialization notice: {e}")

    raw_host = (cfg.get("host") or "127.0.0.1").strip()
    is_lan = raw_host in ("0.0.0.0", "::")
    serving_label = f"Serving on LAN: {lan_url} (Local: {url})" if is_lan else f"Serving at {url}"

    if not cfg.get("launch_browser_on_start", True):
        log("launch_browser_on_start is disabled — server left running headless")
        send_toast("CapsStream is running", f"{serving_label} (headless mode)")
        log("Launcher running in background tray mode (stop it via tray icon or Task Manager)")

    window_already_open = is_capsstream_window_visible(url)
    if cfg.get("launch_browser_on_start", True):
        if from_restart:
            log(f"CapsStream window detected after restart (window_open={window_already_open}) — attaching to existing window")
        elif window_already_open:
            log(f"CapsStream window already open for {url} — bringing to foreground")
            bring_window_to_foreground(find_capsstream_window(url))
        else:
            browser_state["proc"] = launch_app_window(cfg, url)
            send_toast("CapsStream is running", serving_label)
            log(f"CapsStream window launched for {url} (LAN URL: {lan_url})")

    # Initial grace period for window to render / reload and be visible
    start_wait = time.time()
    grace_seconds = 12 if from_restart else 8
    while time.time() - start_wait < grace_seconds:
        if is_capsstream_window_visible(url, browser_state["proc"]):
            log("CapsStream window active — monitoring in background")
            break
        time.sleep(0.5)
    else:
        if from_restart and not is_capsstream_window_visible(url, browser_state["proc"]):
            log("No existing window detected after restart grace period — launching app window")
            browser_state["proc"] = launch_app_window(cfg, url)

    shutdown_on_close = cfg.get("shutdown_on_window_close", False)
    notified_background = False

    try:
        while not exit_requested.is_set():
            # Check if tray requested exit
            if tray and tray.is_exit_requested():
                break

            # Server died on its own → nothing to manage anymore
            if server is not None and server.poll() is not None:
                log("Server process exited on its own — launcher exiting")
                break

            is_visible = is_capsstream_window_visible(url, browser_state["proc"])

            if not is_visible and not notified_background:
                log("CapsStream window closed — continuing in background system tray mode")
                send_toast("CapsStream Running in Tray", "CapsStream is still running. Right-click the tray icon to reopen or exit.")
                notified_background = True
            elif is_visible:
                notified_background = False

            # If user explicitly opted into shutdown_on_window_close in config
            if shutdown_on_close and not is_visible:
                log("shutdown_on_window_close is enabled and window closed — shutting down")
                break

            time.sleep(1.5)
    finally:
        log("Cleaning up launcher and stopping services")
        if tray:
            tray.stop()
        if server is not None and server.poll() is None:
            kill_tree(server.pid)
            send_toast("CapsStream stopped", "Server shut down cleanly")
        log("Launcher exiting")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL in launcher main:\n" + traceback.format_exc())
        fail(f"CapsStream launcher error:\n{e}")

