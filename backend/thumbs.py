"""
thumbs.py — Seekbar preview thumbnail sheets.

Generates a tiled sprite sheet per media file (ffmpeg samples a frame every
N seconds and tiles them into one JPEG). The player crops cells out of the
sprite for seekbar hover previews.

Sheets are cached in data/metadata/thumbs/<media_id>.jpg with a sidecar JSON
holding the geometry; regenerated only when the source file changes.
"""

import os
import json
import math
import shutil
import subprocess

from backend.proc_utils import CREATE_NO_WINDOW, BELOW_NORMAL_PRIORITY
from backend.utils.paths import BASE_DIR, FFMPEG_BIN, FFPROBE_BIN

THUMB_DIR = os.path.join(BASE_DIR, "data", "metadata", "thumbs")

MAX_CELLS = 60         # 10-wide grid, ~1 frame per N seconds — 4K files stay tractable
CELL_WIDTH = 160       # sprite cell width (height follows aspect ratio)


def _sidecar(media_id):
    return os.path.join(THUMB_DIR, f"{media_id}.json")


def _sheet(media_id):
    return os.path.join(THUMB_DIR, f"{media_id}.jpg")


def is_ready(media_id):
    return os.path.isfile(_sheet(media_id)) and os.path.isfile(_sidecar(media_id))


def get_info(media_id):
    if not is_ready(media_id):
        return None
    try:
        with open(_sidecar(media_id), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def generate_sheet(media_id, file_path, duration):
    """
    Generate the sprite sheet for a media file. Returns the info dict
    ({url, interval, cols, count, cell_width}) or None on failure.

    Strategy: fast-seek (-ss before -i) + single-frame extraction per cell.
    The naive fps-filter approach decodes EVERY frame of the file (hours of
    4K HEVC = forever), while input seeking decodes exactly one frame per
    sample point.
    """
    if not os.path.isfile(file_path) or not os.path.exists(FFMPEG_BIN):
        return None
    if not duration or duration < 30:
        return None

    interval = max(10, math.ceil(duration / MAX_CELLS))
    count = min(MAX_CELLS, max(1, math.floor(duration / interval)))
    cols = min(10, count)

    os.makedirs(THUMB_DIR, exist_ok=True)
    cells_dir = os.path.join(THUMB_DIR, f"{media_id}_cells")
    os.makedirs(cells_dir, exist_ok=True)

    creation = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY
    last_good = None
    extracted = 0
    for i in range(count):
        t = i * interval + interval / 2
        cell = os.path.join(cells_dir, f"cell_{i:04d}.jpg")
        if last_good and os.path.exists(cell):
            continue
        try:
            subprocess.run(
                [FFMPEG_BIN, "-hide_banner", "-y",
                 "-ss", f"{t:.1f}", "-i", file_path,
                 "-frames:v", "1", "-vf", f"scale={CELL_WIDTH}:-2",
                 "-q:v", "5", cell],
                capture_output=True, timeout=45,
                creationflags=creation,
            )
        except Exception:
            pass
        if os.path.isfile(cell) and os.path.getsize(cell) > 512:
            last_good = cell
            extracted += 1
        elif last_good:
            # Seek/decode failed for this point — reuse the previous frame
            shutil.copyfile(last_good, cell)
            extracted += 1
        if extracted >= count:
            break

    if not extracted:
        return None

    # Fill any gaps so the tile filter has a complete, evenly-numbered set
    for i in range(count):
        cell = os.path.join(cells_dir, f"cell_{i:04d}.jpg")
        if not os.path.isfile(cell):
            prev = os.path.join(cells_dir, f"cell_{i-1:04d}.jpg")
            if os.path.isfile(prev):
                shutil.copyfile(prev, cell)

    # Tile the cells into one sprite
    sheet = _sheet(media_id)
    rows = math.ceil(count / cols)
    try:
        subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-y",
             "-framerate", "1", "-i", os.path.join(cells_dir, "cell_%04d.jpg"),
             "-vf", f"tile={cols}x{rows}",
             "-frames:v", "1", "-q:v", "5", sheet],
            capture_output=True, timeout=120,
            creationflags=creation,
        )
    except Exception:
        return None

    # Cleanup individual cells
    shutil.rmtree(cells_dir, ignore_errors=True)

    if not os.path.isfile(sheet) or os.path.getsize(sheet) < 1024:
        return None

    # Measure the sheet so the player can crop cells precisely
    cell_height = None
    try:
        probe = subprocess.run(
            [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
             "-show_streams", sheet],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            creationflags=creation,
        )
        import json as _json
        streams = _json.loads(probe.stdout or "{}").get("streams", [])
        if streams:
            cell_height = int(streams[0].get("height", 0)) // rows
    except Exception:
        pass

    info = {
        "url": f"/api/media/{media_id}/thumbnails/sheet",
        "interval": interval,
        "cols": cols,
        "count": count,
        "cell_width": CELL_WIDTH,
        "cell_height": cell_height,
        "duration": int(duration),
    }
    try:
        with open(_sidecar(media_id), "w", encoding="utf-8") as f:
            json.dump(info, f)
    except Exception:
        pass
    return info
