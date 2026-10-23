# -*- coding: utf-8 -*-
"""
backend/trash.py — Native OS Recycle Bin / Trash integration.

Sends files or directories to the system Recycle Bin (Windows Shell API)
or desktop trash with fallback to permanent deletion.
"""
import os
import sys
import logging

logger = logging.getLogger("capsstream.trash")

def send_to_trash(path: str) -> bool:
    """
    Safely sends a file or directory to the OS Recycle Bin/Trash.
    Returns True if successfully trashed or removed, False otherwise.
    """
    if not path or not os.path.exists(path):
        return False

    abs_path = os.path.abspath(path)

    # 1. Native Windows Shell API
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ('hwnd', wintypes.HWND),
                    ('wFunc', wintypes.UINT),
                    ('pFrom', wintypes.LPCWSTR),
                    ('pTo', wintypes.LPCWSTR),
                    ('fFlags', wintypes.WORD),
                    ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', wintypes.LPVOID),
                    ('lpszProgressTitle', wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040        # Move to Recycle Bin instead of hard delete
            FOF_NOCONFIRMATION = 0x0010   # Do not ask user with native Win32 dialog
            FOF_SILENT = 0x0004           # Do not display native progress dialog
            FOF_NOERRORUI = 0x0400        # Suppress error UI dialog

            # Windows Shell API requires double null termination
            norm_path = abs_path + "\0\0"

            fileop = SHFILEOPSTRUCTW()
            fileop.hwnd = None
            fileop.wFunc = FO_DELETE
            fileop.pFrom = norm_path
            fileop.pTo = None
            fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
            fileop.fAnyOperationsAborted = False
            fileop.hNameMappings = None
            fileop.lpszProgressTitle = None

            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
            if res == 0 and not fileop.fAnyOperationsAborted:
                logger.info(f"[trash] Moved to Windows Recycle Bin: {abs_path}")
                return True
            logger.warning(f"[trash] SHFileOperationW failed (code={res}, aborted={fileop.fAnyOperationsAborted}) for {abs_path}")
        except Exception as e:
            logger.warning(f"[trash] Windows native trash exception: {e}")

    # 2. send2trash package fallback if installed
    try:
        import send2trash
        send2trash.send2trash(abs_path)
        logger.info(f"[trash] Moved to trash via send2trash: {abs_path}")
        return True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[trash] send2trash error: {e}")

    # 3. Last fallback: permanent deletion if user explicitly requested delete
    try:
        if os.path.isdir(abs_path):
            import shutil
            shutil.rmtree(abs_path)
        else:
            os.remove(abs_path)
        logger.info(f"[trash] Fallback permanent delete completed: {abs_path}")
        return True
    except Exception as e:
        logger.error(f"[trash] Failed to remove file {abs_path}: {e}")
        return False
