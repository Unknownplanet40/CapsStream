"""
opensubs.py — Automatic subtitle downloads via the OpenSubtitles API.

Searches by the OpenSubtitles movie hash (exact file match, best quality
results) plus the title fallback, downloads the best subtitle for the
preferred language, and saves it next to the media file as
"<basename>.<lang>.srt" so the existing external-subtitle scanner picks
it up on the next get_all_subtitles() call.

Requires a free API key from https://www.opensubtitles.com — set it in
Settings → Player & Subtitle Defaults (config: subtitles.opensubtitles_api_key).
"""

import os
import json
import struct
import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "CapsStream v1.0"


def compute_os_hash(file_path):
    """
    OpenSubtitles movie hash: size + sum of little-endian 64-bit ints from
    the first and last 64KB of the file, mod 2^64.
    """
    if os.path.getsize(file_path) < 65536:
        return None

    def chunk_sum(fh):
        data = fh.read(65536)
        if len(data) % 8:
            data += b"\x00" * (8 - len(data) % 8)
        return sum(struct.unpack("<%dQ" % (len(data) // 8), data))

    total = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        total += chunk_sum(f)
        f.seek(-65536, 2)
        total += chunk_sum(f)
    return total & 0xFFFFFFFFFFFFFFFF


def _api_get(url, api_key, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Api-Key": api_key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8"))


def _api_post(url, api_key, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Api-Key": api_key,
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def _download_link(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as res:
        data = res.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return os.path.getsize(dest_path)


def download_subtitles_for_file(file_path, api_key, languages="en"):
    """
    Find and download the best subtitle for a media file.
    Returns list of saved file paths.
    """
    moviehash = compute_os_hash(file_path)
    if not moviehash:
        return []

    params = {"moviehash": str(moviehash), "languages": languages}
    result = _api_get(f"{API_BASE}/subtitles", api_key, params)
    entries = (result.get("data") or [])[:10]
    if not entries:
        return []

    saved = []
    base = os.path.splitext(file_path)[0]
    tried_file_ids = set()

    # Prefer entries matching the requested language order, then by download count
    def sort_key(entry):
        attrs = entry.get("attributes", {})
        lang = (attrs.get("language") or "").split("-")[0]
        pref = list(languages.split(",")).index(lang) if lang in languages else 99
        return (pref, -(attrs.get("download_count") or 0))

    for entry in sorted(entries, key=sort_key):
        attrs = entry.get("attributes", {})
        lang = (attrs.get("language") or "en").split("-")[0]
        files = attrs.get("files") or []
        if not files:
            continue
        file_id = files[0].get("file_id")
        if not file_id or file_id in tried_file_ids:
            continue
        tried_file_ids.add(file_id)

        try:
            dl = _api_post(f"{API_BASE}/download", api_key, {"file_id": file_id})
            link = dl.get("link")
            if not link:
                continue
            fname = dl.get("file_name") or f"{os.path.basename(base)}.{lang}.srt"
            ext = os.path.splitext(fname)[1].lower() or ".srt"
            if ext not in (".srt", ".ass", ".ssa", ".vtt"):
                ext = ".srt"
            dest = f"{base}.{lang}{ext}"
            if os.path.exists(dest):
                continue  # already have this language
            size = _download_link(link, dest)
            if size > 0:
                saved.append(dest)
                if len(saved) >= len(languages.split(",")):
                    break
        except urllib.error.HTTPError as e:
            # 406 = daily download quota exhausted — stop entirely
            if e.code == 406:
                break
            continue
        except Exception:
            continue

    return saved
