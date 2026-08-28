import os
import subprocess
import json

from backend.proc_utils import CREATE_NO_WINDOW
from backend.utils.paths import FFPROBE_BIN
from backend.utils import probe_cache

LANG_NAMES = {
    "eng": "English", "jpn": "Japanese", "spa": "Spanish", "fre": "French", "fra": "French",
    "ger": "German", "deu": "German", "ita": "Italian", "zho": "Chinese", "chi": "Chinese",
    "kor": "Korean", "rus": "Russian", "por": "Portuguese", "tag": "Tagalog", "tgl": "Tagalog",
    "und": "Default Audio"
}


def probe_audio_tracks(file_path):
    """
    Probes video file using ffprobe and returns list of available audio tracks.
    Results are cached by (path, size, mtime).
    """
    if not os.path.isfile(file_path) or not os.path.exists(FFPROBE_BIN):
        return []

    try:
        st = os.stat(file_path)
        cache_key = ("audio_tracks", os.path.abspath(file_path), st.st_size, st.st_mtime)
    except OSError:
        return []

    cached = probe_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        cmd = [
            FFPROBE_BIN,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            file_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10,
                                      creationflags=CREATE_NO_WINDOW)
        data = json.loads(out.decode("utf-8", errors="ignore"))
        streams = data.get("streams", [])

        audio_tracks = []
        track_num = 0
        for s in streams:
            if s.get("codec_type") == "audio":
                tags = s.get("tags", {})
                lang = (tags.get("language") or tags.get("LANGUAGE") or "und").lower()
                title_tag = tags.get("title") or tags.get("TITLE") or ""
                codec = (s.get("codec_name") or "audio").upper()
                channels = s.get("channels", 2)
                ch_label = "5.1" if channels == 6 else "7.1" if channels == 8 else "Stereo" if channels == 2 else f"{channels}ch"

                lang_disp = LANG_NAMES.get(lang, lang.upper())

                label = f"Track {track_num + 1}: {lang_disp}"
                if title_tag:
                    label += f" — {title_tag}"
                else:
                    label += f" ({codec} {ch_label})"

                audio_tracks.append({
                    "index": track_num,
                    "stream_index": s.get("index"),
                    "title": label,
                    "language": lang,
                    "codec": codec,
                    "channels": channels,
                    # Which track the container flags as default — this is the
                    # one browsers actually play during direct playback.
                    "default": bool((s.get("disposition") or {}).get("default"))
                })
                track_num += 1

        probe_cache.put(cache_key, audio_tracks)
        return audio_tracks
    except Exception as e:
        print(f"[AudioProbe] Error probing {file_path}: {e}")
        return []
