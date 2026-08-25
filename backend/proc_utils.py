"""
proc_utils.py — Windows console suppression for subprocess calls.

When the server runs windowless (pythonw via the silent launcher), any CLI
child process (ffmpeg, ffprobe, attrib, powershell, pip) spawned without
CREATE_NO_WINDOW flashes a visible console window. Every backend subprocess
call that runs a CLI tool must include this flag on Windows.

Usage:
    from backend.proc_utils import CREATE_NO_WINDOW
    subprocess.run(cmd, creationflags=CREATE_NO_WINDOW, ...)
"""

import os

# 0x08000000 = CREATE_NO_WINDOW. The flag is Windows-only — pass 0 elsewhere.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
