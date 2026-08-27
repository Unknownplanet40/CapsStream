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
    log_handle = open(log_file, "a", encoding="utf-8")
    log("Spawning server process (pythonw app.py)")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
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


def launch_app_window(cfg, url):
    """Open the tracked app-mode browser window or installed PWA. Returns the Popen or None."""
    # Check for installed Desktop PWA first
    try:
        from backend.settings import find_installed_pwa
        pwa = find_installed_pwa()
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
    except Exception as e:
        log(f"PWA detection notice: {e}")

    choice = str(cfg.get("browser", "edge")).lower().strip()
    exe = find_browser_exe(choice)
    if not exe:
        log(f"Browser choice '{choice}' has no trackable app-mode exe — opening system default (untracked)")
        os.startfile(url)
        return None

    os.makedirs(APP_PROFILE_DIR, exist_ok=True)
    log(f"Launching app window: {os.path.basename(exe)}")
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

    if not os.path.isfile(PYTHONW):
        fail(f"pythonw.exe not found at:\n{PYTHONW}")
    if not os.path.isfile(APP_SCRIPT):
        fail(f"app.py not found at:\n{APP_SCRIPT}")

    cfg = read_config()
    url, poll_host, poll_port = server_url(cfg)

    pre_flight()

    # Re-run safety: if a server is already up, just open a window and exit
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

    if not cfg.get("launch_browser_on_start", True):
        log("launch_browser_on_start is disabled — server left running headless")
        send_toast("CapsStream is running", f"Serving at {url} (headless mode)")
        log("Launcher exiting (server keeps running; stop it via Task Manager or start.bat)")
        return

    browser = launch_app_window(cfg, url)
    if browser is None:
        log("No tracked browser window — launcher exiting")
        send_toast("CapsStream is running", f"Serving at {url}")
        return

    send_toast("CapsStream is running", f"Serving at {url}")
    log(f"App window open (PID {browser.pid}) — monitoring until it closes")

    # Edge/Chrome "background mode" keeps the browser process alive after
    # the last window closes — process-exit polling alone would never fire
    # and orphan the server. So also track window visibility: when the
    # tracked browser has no visible window for a few seconds, treat the
    # app as closed (and take the background browser down with it).
    def browser_window_visible(pid):
        user32 = ctypes.windll.user32
        found = [False]
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        def cb(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                pid_ref = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
                if pid_ref.value == pid:
                    found[0] = True
                    return False
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return found[0]

    no_window_since = None
    try:
        while True:
            # Browser closed by the user → shut the whole stack down
            if browser.poll() is not None:
                log("App window closed — shutting down server")
                if server is not None:
                    kill_tree(server.pid)
                send_toast("CapsStream stopped", "Server shut down cleanly")
                break
            # Server died on its own → nothing to manage anymore
            if server is not None and server.poll() is not None:
                log("Server process exited on its own — launcher exiting")
                send_toast("CapsStream server exited", "The server process stopped unexpectedly. Check logs/ for details.")
                break
            # Background-mode guard: process alive but the app window is gone
            if not browser_window_visible(browser.pid):
                if no_window_since is None:
                    no_window_since = time.time()
                elif time.time() - no_window_since > 8:
                    log("Browser window gone (background mode) — shutting down browser and server")
                    kill_tree(browser.pid)
                    if server is not None:
                        kill_tree(server.pid)
                    send_toast("CapsStream stopped", "Server shut down cleanly")
                    break
            else:
                no_window_since = None
            time.sleep(2)
    finally:
        log("Launcher exiting")


if __name__ == "__main__":
    main()
