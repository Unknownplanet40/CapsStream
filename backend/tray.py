# -*- coding: utf-8 -*-
"""
backend/tray.py — Native Windows System Tray companion for CapsStream.

Provides a lightweight, zero-dependency tray icon using Win32 API via ctypes.
No Electron, no Node.js, no Rust toolchain — pure Windows native integration.
Runs in a background thread and dispatches callbacks for UI, server control,
quick folder access, and clipboard operations.
"""

import os
import sys
import time
import socket
import threading
import subprocess
import logging
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("capsstream.tray")

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    # Win32 Constants
    WM_USER = 0x0400
    WM_TRAY = WM_USER + 20
    WM_COMMAND = 0x0111
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    WM_DESTROY = 0x0002
    WM_NULL = 0x0000

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002

    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010

    NIIF_NONE = 0x00000000
    NIIF_INFO = 0x00000001
    NIIF_WARNING = 0x00000002
    NIIF_ERROR = 0x00000003

    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    MF_POPUP = 0x00000010
    MF_DEFAULT = 0x00001000
    MF_GRAYED = 0x00000001

    TPM_RIGHTBUTTON = 0x0002
    TPM_RETURNCMD = 0x0100

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    # Set up ctypes prototypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.AppendMenuW.argtypes = [wintypes.HMENU, ctypes.c_uint, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, ctypes.c_uint, ctypes.c_uint]
    user32.SetMenuDefaultItem.restype = wintypes.BOOL

    user32.GetCursorPos.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, ctypes.c_void_p
    ]
    user32.TrackPopupMenu.restype = ctypes.c_uint
    user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = wintypes.LPARAM
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.c_void_p]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
    user32.DispatchMessageW.restype = wintypes.LPARAM
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON

    # NOTIFYICONDATA structure
    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", ctypes.c_uint),
            ("uFlags", ctypes.c_uint),
            ("uCallbackMessage", ctypes.c_uint),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", ctypes.c_uint),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL



def copy_to_clipboard(text: str) -> bool:
    """Copy text string to Windows clipboard natively using Win32 API."""
    if not IS_WINDOWS:
        return False
    try:
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            encoded = (text + "\0").encode("utf-16-le")
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not h_mem:
                return False
            p_mem = kernel32.GlobalLock(h_mem)
            if not p_mem:
                kernel32.GlobalFree(h_mem)
                return False
            ctypes.memmove(p_mem, encoded, len(encoded))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            return True
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.warning(f"Failed to copy to clipboard: {e}")
        return False


def get_lan_url(port: int, ssl: bool = False) -> str:
    """Return primary LAN streaming URL for local network access."""
    proto = "https" if ssl else "http"
    try:
        from backend.utils.network import get_device_ip
        ip = get_device_ip()
    except Exception:
        ip = "127.0.0.1"
    return f"{proto}://{ip}:{port}"


def open_folder(path: str) -> bool:
    """Open folder in Windows Explorer."""
    if not path or not os.path.exists(path):
        return False
    try:
        if IS_WINDOWS:
            os.startfile(os.path.abspath(path))
        else:
            subprocess.Popen(["xdg-open", os.path.abspath(path)])
        return True
    except Exception as e:
        logger.warning(f"Could not open folder '{path}': {e}")
        return False


class CapsStreamTray:
    """
    Lightweight Native Windows System Tray Companion for CapsStream.
    Provides tray icon, quick access menu, LAN IP copy, and lifecycle controls.
    """

    # Menu command IDs
    CMD_OPEN_UI = 1001
    CMD_COPY_LAN = 1002
    CMD_OPEN_MEDIA = 1003
    CMD_OPEN_LOGS = 1004
    CMD_OPEN_DATA = 1005
    CMD_RESTART_SERVER = 1006
    CMD_EXIT = 1007

    def __init__(
        self,
        local_url: str,
        lan_url: str,
        on_open_ui: Optional[Callable[[], None]] = None,
        on_restart: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        icon_path: Optional[str] = None,
        media_paths: Optional[Dict[str, str]] = None,
        log_dir: Optional[str] = None,
        data_dir: Optional[str] = None,
    ):
        self.local_url = local_url
        self.lan_url = lan_url
        self.on_open_ui = on_open_ui
        self.on_restart = on_restart
        self.on_exit = on_exit
        self.icon_path = icon_path
        self.media_paths = media_paths or {}
        self.log_dir = log_dir
        self.data_dir = data_dir

        self._hwnd = None
        self._hicon = None
        self._nid = None
        self._thread = None
        self._running = False
        self._exit_requested = False

    def _load_icon(self) -> Optional[int]:
        """Load icon from PNG/ICO file or fall back to application default icon."""
        if not IS_WINDOWS:
            return None

        # 1. Try loading specified PNG / ICO
        if self.icon_path and os.path.isfile(self.icon_path):
            try:
                with open(self.icon_path, "rb") as f:
                    data = f.read()
                # Windows 8/10/11 supports creating HICON directly from PNG bytes
                hicon = user32.CreateIconFromResourceEx(
                    data, len(data), True, 0x00030000, 32, 32, 0
                )
                if hicon:
                    return hicon
            except Exception as e:
                logger.debug(f"Failed to load icon from resource: {e}")

        # 2. Fallback to default Windows executable icon
        IDI_APPLICATION = 32512
        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _create_window(self):
        """Register custom window class and create hidden message receiver window."""
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
            wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
        )

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam == WM_RBUTTONUP:
                    self._show_context_menu()
                    return 0
                elif lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._trigger_open_ui()
                    return 0
            elif msg == WM_COMMAND:
                self._handle_command(wparam & 0xFFFF)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HICON),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        class_name = f"CapsStreamTray_{os.getpid()}"

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = self._hicon
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = class_name

        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            err = kernel32.GetLastError()
            logger.error(f"RegisterClassW failed: error {err}")
            return None

        hwnd = user32.CreateWindowExW(
            0, class_name, "CapsStream Tray Receiver",
            0, 0, 0, 0, 0, None, None, hinst, None
        )
        return hwnd

    def _show_context_menu(self):
        """Construct and display the tray popup menu at cursor position."""
        if not self._hwnd:
            return

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return

        # 1. Open Web UI (Default / bold)
        user32.AppendMenuW(hmenu, MF_STRING, self.CMD_OPEN_UI, "Open CapsStream")
        user32.SetMenuDefaultItem(hmenu, self.CMD_OPEN_UI, 0)

        # 2. Copy LAN URL
        lan_label = f"Copy LAN URL ({self.lan_url})"
        if len(lan_label) > 42:
            lan_label = f"Copy LAN URL: {self.lan_url}"
        user32.AppendMenuW(hmenu, MF_STRING, self.CMD_COPY_LAN, lan_label)

        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)

        # 3. Quick Folders submenu
        hfolder_menu = user32.CreatePopupMenu()
        if self.log_dir:
            user32.AppendMenuW(hfolder_menu, MF_STRING, self.CMD_OPEN_LOGS, "Logs Folder")
        if self.data_dir:
            user32.AppendMenuW(hfolder_menu, MF_STRING, self.CMD_OPEN_DATA, "Data Directory")

        user32.AppendMenuW(hmenu, MF_POPUP, ctypes.c_size_t(hfolder_menu), "Quick Folders")

        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)

        # 4. Server Controls
        user32.AppendMenuW(hmenu, MF_STRING, self.CMD_RESTART_SERVER, "Restart Server")
        user32.AppendMenuW(hmenu, MF_STRING, self.CMD_EXIT, "Exit CapsStream")

        user32.SetForegroundWindow(self._hwnd)
        user32.TrackPopupMenu(
            hmenu,
            TPM_RIGHTBUTTON,
            pt.x, pt.y,
            0, self._hwnd, None
        )
        user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(hmenu)

    def _handle_command(self, cmd_id: int):
        """Dispatch actions according to clicked menu ID."""
        if cmd_id == self.CMD_OPEN_UI:
            self._trigger_open_ui()
        elif cmd_id == self.CMD_COPY_LAN:
            if copy_to_clipboard(self.lan_url):
                self.show_toast("URL Copied", f"Copied LAN URL to clipboard:\n{self.lan_url}")
            else:
                self.show_toast("Clipboard Error", f"Could not copy URL: {self.lan_url}")
        elif cmd_id == self.CMD_OPEN_MEDIA:
            opened = False
            # Find first valid media path
            for path in self.media_paths.values():
                if path and os.path.isdir(path):
                    open_folder(path)
                    opened = True
                    break
            if not opened:
                # Open root or notify
                root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                open_folder(root)
        elif cmd_id == self.CMD_OPEN_LOGS:
            if self.log_dir:
                open_folder(self.log_dir)
        elif cmd_id == self.CMD_OPEN_DATA:
            if self.data_dir:
                open_folder(self.data_dir)
        elif cmd_id == self.CMD_RESTART_SERVER:
            if self.on_restart:
                threading.Thread(target=self.on_restart, daemon=True).start()
        elif cmd_id == self.CMD_EXIT:
            self._exit_requested = True
            if self.on_exit:
                threading.Thread(target=self.on_exit, daemon=True).start()
            self.stop()

    def _trigger_open_ui(self):
        """Trigger opening the web UI."""
        if self.on_open_ui:
            threading.Thread(target=self.on_open_ui, daemon=True).start()
        else:
            try:
                os.startfile(self.local_url)
            except Exception:
                pass

    def show_toast(self, title: str, message: str, level: str = "info"):
        """Show balloon tooltip or toast notification on the tray icon."""
        if not IS_WINDOWS or not self._nid or not self._hwnd:
            return
        try:
            flag = NIIF_INFO
            if level == "warning":
                flag = NIIF_WARNING
            elif level == "error":
                flag = NIIF_ERROR

            self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_INFO
            self._nid.szInfoTitle = title[:63]
            self._nid.szInfo = message[:255]
            self._nid.dwInfoFlags = flag
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception as e:
            logger.debug(f"Failed to show tray balloon: {e}")

    def update_lan_url(self, lan_url: str):
        """Update the known LAN URL displayed in the menu."""
        self.lan_url = lan_url

    def is_exit_requested(self) -> bool:
        """Check if user clicked 'Exit CapsStream' from tray."""
        return self._exit_requested

    def _run(self):
        """Tray thread message pump."""
        self._hicon = self._load_icon()
        self._hwnd = self._create_window()
        if not self._hwnd:
            logger.error("Could not initialize Win32 tray window")
            self._running = False
            return

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        if self.lan_url and self.lan_url != self.local_url:
            tip = f"CapsStream — Streaming Server\nLAN: {self.lan_url}\nLocal: {self.local_url}"
        else:
            tip = f"CapsStream — Streaming Server\n{self.local_url}"
        nid.szTip = tip[:127]

        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

        self._running = True
        logger.info("CapsStream system tray companion running")

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._cleanup()

    def _cleanup(self):
        """Remove tray icon and release resources."""
        if self._nid and shell32:
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            self._nid = None
        if self._hicon and user32:
            try:
                user32.DestroyIcon(self._hicon)
            except Exception:
                pass
            self._hicon = None
        self._running = False

    def start(self):
        """Start tray companion in a background daemon thread."""
        if not IS_WINDOWS:
            logger.info("Non-Windows OS: system tray companion disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="CapsStreamTray", daemon=True)
        self._thread.start()

    def stop(self):
        """Signal message pump to exit and remove tray icon."""
        if self._hwnd and user32:
            try:
                user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
            except Exception:
                pass
        self._cleanup()
