# -*- coding: utf-8 -*-
"""Music library scanner for CapsStream – FLAC + tags + covers + .lrc."""

import os
import re
import hashlib
import threading
from pathlib import Path

from backend.settings import load_config
from backend.db.music import (
    upsert_artist,
    upsert_album,
    upsert_track,
    remove_missing_tracks,
)
from backend.utils.paths import BASE_DIR

try:
    from mutagen import File as MutagenFile
    from mutagen.flac import FLAC
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}

_scan_status = {
    "running": False,
    "phase": "idle",
    "progress": "",
    "count": 0,
    "total": 0,
    "percent": 0,
    "errors": [],
}
_scan_lock = threading.Lock()


def get_music_scan_status():
    with _scan_lock:
        return dict(_scan_status)


def _set_status(**kwargs):
    with _scan_lock:
        _scan_status.update(kwargs)


def _resolve_paths(path_list):
    resolved = []
    for p in path_list or []:
        if not p:
            continue
        if os.path.isabs(p):
            resolved.append(p)
        else:
            resolved.append(os.path.join(BASE_DIR, p))
    return [p for p in resolved if os.path.isdir(p)]


def _find_lrc(file_path):
    base = os.path.splitext(file_path)[0]
    for candidate in (base + ".lrc", base + ".LRC"):
        if os.path.isfile(candidate):
            return candidate
    return None


def _extract_cover(audio, file_path, covers_dir):
    """Extract embedded cover and save to covers_dir. Returns relative path or None."""
    try:
        os.makedirs(covers_dir, exist_ok=True)
        data = None
        mime = "image/jpeg"

        if isinstance(audio, FLAC) and audio.pictures:
            pic = audio.pictures[0]
            data = pic.data
            mime = pic.mime or "image/jpeg"
        elif hasattr(audio, "pictures") and audio.pictures:
            pic = audio.pictures[0]
            data = pic.data
            mime = getattr(pic, "mime", "image/jpeg")
        elif hasattr(audio, "tags") and audio.tags:
            # MP3 / ID3
            for key in ("APIC:", "APIC"):
                if key in audio.tags:
                    apic = audio.tags[key]
                    data = apic.data
                    mime = getattr(apic, "mime", "image/jpeg")
                    break
            # MP4 / M4A
            if not data and "covr" in audio.tags:
                covr = audio.tags["covr"][0]
                data = bytes(covr)
                mime = "image/jpeg"

        # Also check for folder art / cover.jpg / folder.jpg next to the file
        if not data:
            parent_dir = os.path.dirname(file_path)
            for art_name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "album.jpg", "front.jpg"):
                candidate = os.path.join(parent_dir, art_name)
                if os.path.isfile(candidate):
                    try:
                        with open(candidate, "rb") as f:
                            data = f.read()
                        mime = "image/png" if art_name.endswith(".png") else "image/jpeg"
                        break
                    except Exception:
                        pass

        if not data:
            return None

        ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
        h = hashlib.md5(data).hexdigest()[:16]
        filename = f"{h}{ext}"
        out_path = os.path.join(covers_dir, filename)
        if not os.path.exists(out_path):
            with open(out_path, "wb") as f:
                f.write(data)
        return f"music_covers/{filename}"
    except Exception as e:
        print(f"[MusicScanner] Cover extract failed for {file_path}: {e}")
        return None


def _safe_int(val, default=0):
    try:
        if val is None:
            return default
        if isinstance(val, (list, tuple)):
            val = val[0] if val else default
        s = str(val).split("/")[0].strip()
        return int(float(s))
    except Exception:
        return default


def _read_tags(file_path):
    """Return a dict of cleaned tags + duration + technical info."""
    info = {
        "title": Path(file_path).stem,
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "albumartist": None,
        "track_number": 0,
        "disc_number": 1,
        "year": None,
        "genre": None,
        "duration": 0,
        "bitrate": None,
        "sample_rate": None,
        "format": os.path.splitext(file_path)[1][1:].lower(),
        "embedded_lyrics": None,
        "_audio_full": None,
    }
    if not HAS_MUTAGEN:
        return info

    try:
        audio = MutagenFile(file_path, easy=True)
        if audio is not None:
            def get(key, default=None):
                v = audio.get(key)
                if isinstance(v, list):
                    return v[0] if v else default
                return v if v is not None else default

            info["title"] = str(get("title") or info["title"]).strip()
            info["artist"] = str(get("artist") or info["artist"]).strip()
            info["album"] = str(get("album") or info["album"]).strip()
            info["albumartist"] = str(get("albumartist") or "").strip() or None
            info["genre"] = str(get("genre") or "").strip() or None
            info["track_number"] = _safe_int(get("tracknumber"))
            info["disc_number"] = _safe_int(get("discnumber"), 1)
            date = get("date") or get("year")
            if date:
                m = re.search(r"(\d{4})", str(date))
                if m:
                    info["year"] = int(m.group(1))

            if audio.info:
                info["duration"] = int(getattr(audio.info, "length", 0) or 0)
                bitrate = getattr(audio.info, "bitrate", 0)
                info["bitrate"] = int(bitrate) // 1000 if bitrate else None
                info["sample_rate"] = getattr(audio.info, "sample_rate", None)

        # Smart fallback inference from filename and directory
        stem = Path(file_path).stem
        if (not info["title"] or info["title"] == stem) and " - " in stem:
            parts = stem.split(" - ", 1)
            if len(parts) == 2:
                p0 = parts[0].strip()
                p1 = parts[1].strip()
                if p0.isdigit():
                    info["track_number"] = _safe_int(p0)
                    info["title"] = p1
                else:
                    if not info["artist"] or info["artist"] == "Unknown Artist":
                        info["artist"] = p0
                    info["title"] = p1

        # Fallback artist from parent folder if still unknown
        if not info["artist"] or info["artist"] == "Unknown Artist":
            parent_name = os.path.basename(os.path.dirname(file_path))
            if parent_name and parent_name.lower() not in {"music", "deemix music", "audio", "tracks", "songs", "downloads"}:
                # Check if parent is an album like "Post Malone - Twelve Carat Toothache"
                if " - " in parent_name:
                    info["artist"] = parent_name.split(" - ", 1)[0].strip()
                else:
                    info["artist"] = parent_name

        # Non-easy mutagen access for lyrics and artwork
        audio_full = MutagenFile(file_path)
        info["_audio_full"] = audio_full
        if audio_full and hasattr(audio_full, "tags") and audio_full.tags:
            # Check ID3 lyrics
            for tag_key, tag_val in audio_full.tags.items():
                if tag_key.startswith("USLT") or "lyrics" in tag_key.lower():
                    text = getattr(tag_val, "text", str(tag_val))
                    if text:
                        info["embedded_lyrics"] = str(text).strip()
                        break
    except Exception as e:
        print(f"[MusicScanner] Tag read notice for {file_path}: {e}")
    return info


def scan_music_library(callback=None):
    with _scan_lock:
        if _scan_status["running"]:
            return {"error": "Scan already running"}
        _scan_status.update({
            "running": True,
            "phase": "scanning",
            "progress": "Starting music scan...",
            "count": 0,
            "total": 0,
            "percent": 0,
            "errors": [],
        })

    def log(msg):
        _set_status(progress=str(msg))
        try:
            print(f"[MusicScanner] {msg}")
        except Exception:
            try:
                print(f"[MusicScanner] {str(msg).encode('ascii', 'replace').decode('ascii')}")
            except Exception:
                pass
        if callback:
            try:
                callback(msg)
            except Exception:
                pass

    try:
        cfg = load_config()
        paths = _resolve_paths((cfg.get("media_paths") or {}).get("music", []))
        disabled = set((cfg.get("disabled_paths") or {}).get("music", []))
        paths = [p for p in paths if p not in disabled]

        if not paths:
            log("No music paths configured")
            _set_status(running=False, phase="complete", percent=100, progress="No music paths configured")
            return {"scanned": 0, "total": 0}

        covers_dir = os.path.join(BASE_DIR, "data", "music_covers")
        lyrics_dir = os.path.join(BASE_DIR, "data", "music_lyrics")
        os.makedirs(covers_dir, exist_ok=True)
        os.makedirs(lyrics_dir, exist_ok=True)

        # Collect audio files
        files = []
        for base in paths:
            for root, dirs, filenames in os.walk(base):
                for fn in filenames:
                    if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                        files.append(os.path.join(root, fn))

        total = len(files)
        _set_status(total=total)
        log(f"Found {total} audio files")

        scanned = 0
        found_paths = set(files)

        for i, fpath in enumerate(files):
            try:
                tags = _read_tags(fpath)
                artist_id = upsert_artist(tags["artist"])
                album_id = upsert_album(
                    tags["album"],
                    artist_id=artist_id,
                    album_artist=tags["albumartist"],
                    year=tags["year"],
                    genre=tags["genre"],
                )

                cover_rel = None
                if tags.get("_audio_full"):
                    cover_rel = _extract_cover(tags["_audio_full"], fpath, covers_dir)
                    if cover_rel:
                        upsert_album(tags["album"], artist_id=artist_id, cover_path=cover_rel)
                        upsert_artist(tags["artist"], cover_path=cover_rel)

                lyrics = _find_lrc(fpath)
                st = os.stat(fpath)

                upsert_track(
                    file_path=fpath,
                    title=tags["title"],
                    artist_id=artist_id,
                    album_id=album_id,
                    track_number=tags["track_number"],
                    disc_number=tags["disc_number"],
                    duration=tags["duration"],
                    file_size=st.st_size,
                    bitrate=tags["bitrate"],
                    sample_rate=tags["sample_rate"],
                    fmt=tags["format"],
                    genre=tags["genre"],
                    year=tags["year"],
                    lyrics_path=lyrics,
                )
                scanned += 1
            except Exception as e:
                _scan_status["errors"].append(f"{fpath}: {e}")
                print(f"[MusicScanner] Error {fpath}: {e}")

            _set_status(
                count=i + 1,
                percent=round(100 * (i + 1) / total) if total else 100,
                progress=f"Scanning {i + 1}/{total} — {os.path.basename(fpath)}",
            )

        # Cleanup deleted tracks
        try:
            cleaned = remove_missing_tracks(found_paths)
            if cleaned > 0:
                log(f"Cleaned up {cleaned} missing audio tracks")
        except Exception as e:
            print(f"[MusicScanner] Missing track cleanup error: {e}")

        log(f"Music scan complete — {scanned} tracks")
        _set_status(running=False, phase="complete", percent=100, progress="Done")
        return {"scanned": scanned, "total": total}
    except Exception as e:
        log(f"Music scan failed: {e}")
        _set_status(running=False, phase="error", progress=str(e))
        return {"error": str(e)}
