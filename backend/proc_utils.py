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

# 0x00004000 = BELOW_NORMAL_PRIORITY_CLASS — for background ffmpeg jobs
# (intro detection, thumbnail sheets) so they never starve streaming I/O.
BELOW_NORMAL_PRIORITY = 0x00004000 if os.name == "nt" else 0
