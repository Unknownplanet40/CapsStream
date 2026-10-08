import os
import glob
import subprocess
import json
import re
import requests
import urllib.parse
import base64
import zipfile
import io
import shutil
import logging

from backend.proc_utils import CREATE_NO_WINDOW
from backend.utils.paths import BASE_DIR, FFPROBE_BIN, FFMPEG_BIN

logger = logging.getLogger("subtitles")

SUB_CACHE_DIR = os.path.join(BASE_DIR, "data", "metadata", "subtitles")

from backend.sub_naming import (
    LANG_NAMES,
    LANG_MAP,
    parse_filename,
    display_label,
    normalize_lang,
)


def _parse_sub_label(file_name):
    """
    Parses display label, language code (ISO 639-1), SDH/HI flag, and forced flag.
    Reimplemented on top of backend.sub_naming.
    """
    parsed = parse_filename(file_name)
    label = display_label(parsed, file_name)
    return label, parsed.lang, parsed.is_hi, file_name


def _dir_has_other_videos(dir_path, current_video_path, video_extensions):
    """Check if dir_path contains video files other than current_video_path."""
    if not os.path.isdir(dir_path):
        return False
    current_norm = os.path.normpath(current_video_path).lower()
    try:
        for item in os.listdir(dir_path):
            ext = os.path.splitext(item)[1].lower()
            if ext in video_extensions:
                full_p = os.path.normpath(os.path.join(dir_path, item)).lower()
                if full_p != current_norm:
                    return True
    except Exception:
        pass
    return False



def promote_subs_to_media_folder(video_path: str, max_subs: int = 5):
    """
    If no subtitle file exists directly beside the media file in its folder,
    inspect any Subs/ or Subtitles/ subfolder, extract prioritized companion
    subtitles (English standard -> HI English -> other languages), and copy them
    directly into the movie folder beside the media file using standard naming.

    Returns the list of created subtitle file paths.
    """
    if not video_path or not os.path.isfile(video_path):
        return []

    video_dir = os.path.dirname(os.path.abspath(video_path))
    if not os.path.isdir(video_dir):
        return []

    video_file = os.path.basename(video_path)
    video_stem, video_ext = os.path.splitext(video_file)
    video_stem_lower = video_stem.lower()
    subtitle_exts = {".srt", ".vtt", ".ass", ".sub"}

    try:
        dir_entries = os.listdir(video_dir)
    except OSError:
        return []

    # Detect other video files in directory
    video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
    video_files_in_dir = [
        f for f in dir_entries
        if os.path.splitext(f)[1].lower() in video_extensions
        and not f.lower().endswith(("-sample", "_sample", ".sample"))
        and "sample" not in f.lower()
    ]
    has_multiple_videos = len(video_files_in_dir) > 1

    ep_match = re.search(r"(s\d+e\d+|\d+x\d+|e\d+)", video_stem_lower)
    ep_token = ep_match.group(0) if ep_match else None

    # 1. Check if a subtitle file already exists directly beside the media
    has_sub_beside = False
    for fname in dir_entries:
        f_path = os.path.join(video_dir, fname)
        if not os.path.isfile(f_path):
            continue
        f_stem, f_ext = os.path.splitext(fname)
        if f_ext.lower() in subtitle_exts:
            f_stem_lower = f_stem.lower()
            if f_stem_lower.startswith(video_stem_lower) or video_stem_lower.startswith(f_stem_lower):
                has_sub_beside = True
                break
            if not has_multiple_videos:
                has_sub_beside = True
                break
            if ep_token and ep_token in f_stem_lower:
                has_sub_beside = True
                break

    if has_sub_beside:
        return []

    # 2. Check for Subs / Subtitles subfolders
    sub_dir_names = ["subs", "subtitles", "sub", "eng", "english"]
    candidate_sub_dirs = []
    for d in dir_entries:
        dp = os.path.join(video_dir, d)
        if os.path.isdir(dp) and d.lower() in sub_dir_names:
            candidate_sub_dirs.append(dp)

    # If none found in video_dir, check parent directory if video is in a nested folder (like CD1)
    if not candidate_sub_dirs:
        parent_dir = os.path.dirname(video_dir)
        if parent_dir and parent_dir != video_dir and os.path.isdir(parent_dir):
            try:
                for d in os.listdir(parent_dir):
                    dp = os.path.join(parent_dir, d)
                    if os.path.isdir(dp) and d.lower() in sub_dir_names:
                        candidate_sub_dirs.append(dp)
            except OSError:
                pass

    if not candidate_sub_dirs:
        return []

    # 3. Collect subtitle files from candidate subfolders
    found_sub_paths = []
    for s_dir in candidate_sub_dirs:
        try:
            for root, _, files in os.walk(s_dir):
                for f in files:
                    _, f_ext = os.path.splitext(f)
                    if f_ext.lower() in subtitle_exts:
                        full_sub = os.path.join(root, f)
                        try:
                            if os.path.getsize(full_sub) < 10:
                                continue
                        except OSError:
                            continue
                        f_lower = f.lower()
                        if not has_multiple_videos:
                            found_sub_paths.append(full_sub)
                        elif ep_token and ep_token in f_lower:
                            found_sub_paths.append(full_sub)
                        elif f_lower.startswith(video_stem_lower):
                            found_sub_paths.append(full_sub)
        except OSError:
            pass

    if not found_sub_paths:
        return []

    # 4. Sort and prioritize subtitles
    from backend.organizer import parse_subtitle_details, build_subtitle_destination_path

    parsed_subs = []
    for sp in found_sub_paths:
        details = parse_subtitle_details(sp, media_basename=video_stem)
        parsed_subs.append((details["priority"], sp, details))

    parsed_subs.sort(key=lambda x: (x[0], os.path.basename(x[1]).lower()))

    # 5. Select unique language variants to copy
    chosen_subs = []
    seen_keys = set()

    for priority, sp, details in parsed_subs:
        lang = details.get("lang", "und")
        is_hi = details.get("is_hi", False)
        is_forced = details.get("is_forced", False)
        key = (lang, is_hi, is_forced)

        if key not in seen_keys:
            seen_keys.add(key)
            chosen_subs.append(sp)
            if len(chosen_subs) >= max_subs:
                break

    if not chosen_subs and parsed_subs:
        chosen_subs.append(parsed_subs[0][1])

    # 6. Copy chosen subtitles beside the media file
    promoted_paths = []
    existing_destinations = set()

    for sub_src in chosen_subs:
        dest_path = build_subtitle_destination_path(sub_src, video_path, existing_destinations=existing_destinations)
        if dest_path and not os.path.exists(dest_path):
            try:
                shutil.copy2(sub_src, dest_path)
                promoted_paths.append(dest_path)
                if sub_src.lower().endswith(".sub"):
                    idx_src = os.path.splitext(sub_src)[0] + ".idx"
                    idx_dst = os.path.splitext(dest_path)[0] + ".idx"
                    if os.path.exists(idx_src) and not os.path.exists(idx_dst):
                        shutil.copy2(idx_src, idx_dst)
            except OSError as e:
                logger.warning(f"Failed to copy subtitle {sub_src} to {dest_path}: {e}")

    if promoted_paths:
        print(f"[Subtitles] Promoted {len(promoted_paths)} subtitle(s) from Subs folder to movie folder {video_dir}: {[os.path.basename(p) for p in promoted_paths]}")

    return promoted_paths


def get_all_subtitles(video_path, media_id):
    """
    Returns unified list of external subtitles (strictly matched to video) and embedded subtitles.
    """
    if not os.path.isfile(video_path):
        return []

    # Ensure companion subtitles from Subs/ subfolder are promoted to movie folder if none exist beside media
    try:
        promote_subs_to_media_folder(video_path)
    except Exception as e:
        print(f"[Subtitles] Note: Error promoting subs for {video_path}: {e}")

    sub_list = []
    video_dir = os.path.dirname(video_path)
    video_basename = os.path.splitext(os.path.basename(video_path))[0].lower()

    # Extract episode tag (e.g. s01e01, 1x01, ep01, e01) if present
    ep_match = re.search(r"(s\d+e\d+|\d+x\d+|e\d+)", video_basename)
    ep_tag = ep_match.group(0) if ep_match else None

    # Find all other video stems and episode tags in the directory
    video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
    other_video_stems = set()
    other_ep_tags = set()
    has_multiple_videos = False

    if os.path.isdir(video_dir):
        video_files = [
            f for f in os.listdir(video_dir)
            if os.path.splitext(f)[1].lower() in video_extensions
        ]
        if len(video_files) > 1:
            has_multiple_videos = True

        for f in video_files:
            f_stem = os.path.splitext(f)[0].lower()
            if f_stem != video_basename:
                other_video_stems.add(f_stem)
                other_m = re.search(r"(s\d+e\d+|\d+x\d+|e\d+)", f_stem)
                if other_m and (not ep_tag or other_m.group(0) != ep_tag):
                    other_ep_tags.add(other_m.group(0))

    # Folders to walk: video_dir, plus parent directory if parent contains Subs/ or Subtitles/
    search_roots = [video_dir]
    parent_dir = os.path.dirname(video_dir)
    if parent_dir and parent_dir != video_dir and os.path.isdir(parent_dir):
        for s_name in ["Subs", "subs", "Subtitles", "subtitles"]:
            p_sub = os.path.join(parent_dir, s_name)
            if os.path.isdir(p_sub):
                search_roots.append(p_sub)

    seen_paths = set()

    # 1. External Subtitles — Walk search_roots for all .srt, .vtt, .ass, .sub files
    for search_root in search_roots:
        for root, dirs, files in os.walk(search_root):
            # Prune directories so we don't enter unrelated subfolders or subfolders containing other videos
            valid_dirs = []
            for d in dirs:
                subfolder_path = os.path.join(root, d)
                d_lower = d.lower()

                # If subfolder contains other video files, do NOT enter it
                if _dir_has_other_videos(subfolder_path, video_path, video_extensions):
                    continue

                # If directly inside video_dir, only enter if it's a subtitle/language subfolder or matches video basename
                if os.path.normpath(root).lower() == os.path.normpath(video_dir).lower():
                    allowed_sub_folders = [
                        "subs", "subtitles", "sub", "eng", "english", "spa", "spanish", 
                        "fre", "french", "ger", "german", "ita", "italian", "jpn", "japanese", 
                        "zho", "chinese", "kor", "korean", "rus", "russian", "por", "portuguese"
                    ]
                    is_allowed_folder = (
                        d_lower in allowed_sub_folders or 
                        any(sf in d_lower for sf in ["sub", "eng", "spanish", "french", "german"]) or
                        video_basename in d_lower
                    )
                    if not is_allowed_folder:
                        continue

                valid_dirs.append(d)
            dirs[:] = valid_dirs

            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in [".srt", ".vtt", ".ass", ".sub"]:
                    continue

                full_sub_path = os.path.normpath(os.path.join(root, f))
                if full_sub_path in seen_paths:
                    continue

                fname_lower = f.lower()
                clean_sub_stem = os.path.splitext(fname_lower)[0]
                rel_dir = os.path.relpath(root, video_dir).lower()

                # Rule A: Disqualify subtitle if it explicitly matches another video's stem name
                skip_other_stem = False
                for o_stem in other_video_stems:
                    if len(o_stem) > 2 and (o_stem in fname_lower or fname_lower.startswith(o_stem)):
                        skip_other_stem = True
                        break
                if skip_other_stem:
                    continue

                # Rule B: Disqualify subtitle if it explicitly contains a different episode tag
                skip_other_ep = False
                for other_tag in other_ep_tags:
                    if other_tag in fname_lower or other_tag in rel_dir:
                        skip_other_ep = True
                        break
                if skip_other_ep:
                    continue

                # Rule C: If current video has an episode tag, require subtitle to match or not conflict
                if ep_tag:
                    sub_ep_m = re.search(r"(s\d+e\d+|\d+x\d+|e\d+)", fname_lower + " " + rel_dir)
                    if sub_ep_m and sub_ep_m.group(0) != ep_tag:
                        continue
                    if not sub_ep_m and has_multiple_videos and video_basename not in fname_lower and ep_tag not in rel_dir:
                        continue

                # Rule D: In multi-video folders (movies), generic subtitle names must contain video stem or be in dedicated video subfolder
                if has_multiple_videos and not ep_tag:
                    sub_in_dedicated_folder = video_basename in rel_dir or video_basename in root.lower()
                    matches_video_prefix = clean_sub_stem.startswith(video_basename) or video_basename in clean_sub_stem
                    if not matches_video_prefix and not sub_in_dedicated_folder:
                        continue

                seen_paths.add(full_sub_path)

                # Get path relative to video directory for URL serving
                rel_path = os.path.relpath(full_sub_path, video_dir).replace("\\", "/")
                parent_folder_name = os.path.basename(root)
                parsed = parse_filename(f, parent_folder=parent_folder_name)
                label = display_label(parsed, f)

                # Clean display label
                if parent_folder_name.lower() in ["subs", "subtitles", "eng", "english"] and parent_folder_name.lower() != os.path.basename(video_dir).lower():
                    if parent_folder_name.lower() not in label.lower():
                        label = f"{label} ({parent_folder_name})"

                sub_list.append({
                    "type": "external",
                    "label": label,
                    "language": parsed.lang,
                    "forced": parsed.is_forced,
                    "hi": parsed.is_hi,
                    "is_sdh": parsed.is_hi,
                    "filename": f,
                    "raw_filename": f,
                    "url": f"/api/subtitles/{media_id}/{rel_path}"
                })

    # 2. Embedded Subtitles in Video Container (via ffprobe)
    # Bitmap subtitle codecs cannot be converted to WebVTT by ffmpeg —
    # offering them only produces 404s when the player requests extraction.
    UNSUPPORTED_TEXT_CODECS = {
        "hdmv_pgs_subtitle", "pgssub",   # Blu-ray bitmap subs
        "dvd_subtitle", "dvbsub",        # DVD / DVB bitmap subs
        "arib_caption",                  # Japanese broadcast bitmap subs
    }
    if os.path.exists(FFPROBE_BIN):
        try:
            cmd = [
                FFPROBE_BIN, "-v", "quiet",
                "-print_format", "json",
                "-show_streams", video_path
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10,
                                          creationflags=CREATE_NO_WINDOW)
            data = json.loads(out.decode("utf-8", errors="ignore"))
            streams = data.get("streams", [])

            sub_idx = 0
            for s in streams:
                if s.get("codec_type") == "subtitle":
                    if s.get("codec_name", "").lower() in UNSUPPORTED_TEXT_CODECS:
                        continue
                    tags = s.get("tags", {})
                    lang = (tags.get("language") or tags.get("LANGUAGE") or "und").lower()
                    title_tag = tags.get("title") or tags.get("TITLE") or ""
                    codec = s.get("codec_name", "sub").upper()

                    is_sdh = "sdh" in title_tag.lower() or "hearing" in title_tag.lower()
                    lang_disp = LANG_NAMES.get(lang, lang.upper())

                    label = f"Embedded: {lang_disp}"
                    if title_tag:
                        label += f" — {title_tag}"
                    elif codec != "SUB":
                        label += f" ({codec})"
                    if is_sdh and "[SDH]" not in label:
                        label += " [SDH]"

                    sub_list.append({
                        "type": "embedded",
                        "stream_index": s.get("index"),
                        "sub_index": sub_idx,
                        "label": label,
                        "language": lang,
                        "is_sdh": is_sdh,
                        "filename": f"embedded_{s.get('index')}.vtt",
                        "raw_filename": title_tag or f"Embedded Track {sub_idx+1}",
                        "url": f"/api/subtitles/{media_id}/embedded/{s.get('index')}.vtt"
                    })
                    sub_idx += 1
        except Exception as e:
            print(f"[Subtitles] Error probing embedded subs for {video_path}: {e}")

    return sub_list


def extract_embedded_vtt(video_path, stream_index, media_id):
    """
    Extracts embedded subtitle stream to WebVTT format using FFmpeg and caches it.
    """
    os.makedirs(SUB_CACHE_DIR, exist_ok=True)
    out_vtt = os.path.join(SUB_CACHE_DIR, f"{media_id}_sub_{stream_index}.vtt")

    if os.path.exists(out_vtt) and os.path.getsize(out_vtt) > 0:
        return out_vtt

    if not os.path.exists(FFMPEG_BIN):
        return None

    # Extract to a unique temp file first, then atomically swap into place so
    # concurrent requests can never read (or corrupt) a half-written VTT.
    import threading
    out_tmp = f"{out_vtt}.{os.getpid()}.{threading.get_ident()}.part"

    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", video_path,
            "-map", f"0:{stream_index}",
            "-f", "webvtt",
            out_tmp
        ]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=30,
                                creationflags=CREATE_NO_WINDOW)
        if os.path.exists(out_tmp):
            os.makedirs(SUB_CACHE_DIR, exist_ok=True)
            os.replace(out_tmp, out_vtt)
            return out_vtt
        if os.path.exists(out_vtt) and os.path.getsize(out_vtt) > 0:
            return out_vtt
    except Exception as e:
        print(f"[Subtitles] Error extracting embedded VTT for stream {stream_index}: {e}")
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass

    return None


def get_vtt_path(sub_path):
    """
    Given an external subtitle file path (.srt, .vtt, .ass, .sub),
    converts it to WebVTT if needed and returns the .vtt file path.
    """
    if not os.path.exists(sub_path):
        return None

    ext = os.path.splitext(sub_path)[1].lower()
    if ext == ".vtt":
        return sub_path

    vtt_dir = os.path.join(BASE_DIR, "data", "metadata", "subtitles")
    os.makedirs(vtt_dir, exist_ok=True)

    clean_name = os.path.basename(sub_path).replace(".", "_") + ".vtt"
    vtt_path = os.path.join(vtt_dir, clean_name)

    if os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 0:
        return vtt_path

    # Attempt FFmpeg conversion
    if os.path.exists(FFMPEG_BIN):
        try:
            cmd = [FFMPEG_BIN, "-y", "-i", sub_path, "-f", "webvtt", vtt_path]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15,
                                    creationflags=CREATE_NO_WINDOW)
            if os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 0:
                return vtt_path
        except Exception as e:
            print(f"[Subtitles] FFmpeg srt to vtt error for {sub_path}: {e}")

    # Fallback SRT to VTT text converter in pure Python with multi-encoding support
    try:
        content = None
        for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1", "utf-16"]:
            try:
                with open(sub_path, "r", encoding=enc) as f_in:
                    content = f_in.read()
                break
            except Exception:
                continue

        if content is None:
            with open(sub_path, "r", encoding="utf-8", errors="ignore") as f_in:
                content = f_in.read()

        lines = content.splitlines(keepends=True)
        vtt_lines = ["WEBVTT\n\n"]
        for line in lines:
            line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
            vtt_lines.append(line)

        with open(vtt_path, "w", encoding="utf-8") as f_out:
            f_out.writelines(vtt_lines)

        return vtt_path
    except Exception as e:
        print(f"[Subtitles] Python srt to vtt conversion error for {sub_path}: {e}")
        return None


find_subtitles = get_all_subtitles


def shift_vtt_content(vtt_text, offset_seconds):
    """
    Shifts all WebVTT timestamp lines by subtracting offset_seconds.
    """
    if not offset_seconds or offset_seconds <= 0:
        return vtt_text

    def shift_match(match):
        t_str = match.group(0)
        parts = t_str.split(":")
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            tot = h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = int(parts[0]), float(parts[1])
            tot = m * 60 + s
        else:
            return t_str

        new_tot = max(0.0, tot - offset_seconds)
        nh = int(new_tot // 3600)
        nm = int((new_tot % 3600) // 60)
        ns = new_tot % 60
        return f"{nh:02d}:{nm:02d}:{ns:06.3f}"

    lines = []
    for line in vtt_text.splitlines():
        if "-->" in line:
            line = re.sub(r"\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3}", shift_match, line)
        lines.append(line)

    return "\n".join(lines)


def search_online_subtitles(title, imdb_id=None, season=None, episode=None, lang="english"):
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # Clean title for query
    clean_title = re.sub(r'[\(\)\[\]]', '', title or '').strip()

    # 1. Search by IMDb ID if available
    if imdb_id:
        imdb_str = str(imdb_id).strip()
        if not imdb_str.startswith("tt"):
            try:
                imdb_str = f"tt{int(imdb_str):07d}"
            except Exception:
                pass
        url = f"https://yts-subs.com/movie-imdb/{imdb_str}"
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                matches = set(re.findall(r'/subtitles/([a-zA-Z0-9\-]+)', r.text))
                for slug in matches:
                    if not lang or lang.lower() in slug.lower() or "english" in slug.lower():
                        results.append({
                            "id": slug,
                            "title": slug.replace("-", " ").title(),
                            "slug": slug,
                            "lang": "English" if "english" in slug.lower() else "Other"
                        })
        except Exception as e:
            print("[Subtitles] Online IMDb search error:", e)

    # 2. Search by title if no IMDb results found
    if not results and clean_title:
        q_url = f"https://yts-subs.com/search/{requests.utils.quote(clean_title)}"
        try:
            r = requests.get(q_url, headers=headers, timeout=8)
            if r.status_code == 200:
                movies = set(re.findall(r'/movie-imdb/(tt\d+)', r.text))
                for m_id in list(movies)[:2]:
                    m_url = f"https://yts-subs.com/movie-imdb/{m_id}"
                    mr = requests.get(m_url, headers=headers, timeout=8)
                    if mr.status_code == 200:
                        matches = set(re.findall(r'/subtitles/([a-zA-Z0-9\-]+)', mr.text))
                        for slug in matches:
                            if not lang or lang.lower() in slug.lower() or "english" in slug.lower():
                                results.append({
                                    "id": slug,
                                    "title": slug.replace("-", " ").title(),
                                    "slug": slug,
                                    "lang": "English" if "english" in slug.lower() else "Other"
                                })
        except Exception as e:
            print("[Subtitles] Online title search error:", e)

    return results[:15]


def _is_safe_subtitle_download_url(url: str) -> bool:
    """Validate external download URL to prevent SSRF against loopback or private networks."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.endswith(".internal"):
            return False
        import socket
        import ipaddress
        for res in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(res[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def download_online_subtitle(slug, media_id):
    safe_slug = re.sub(r"[^a-zA-Z0-9_\-]", "", str(slug or "")).strip()
    if not safe_slug:
        return None

    try:
        clean_mid = int(media_id)
    except (TypeError, ValueError):
        return None

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = f"https://yts-subs.com/subtitles/{safe_slug}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None

        m = re.search(r'data-link=["\']([^"\']+)["\']', r.text)
        if not m:
            return None

        b64_url = m.group(1)
        dl_url = base64.b64decode(b64_url).decode("utf-8")

        if not _is_safe_subtitle_download_url(dl_url):
            logger.warning(f"[Subtitles] Blocked unsafe subtitle download URL: {dl_url}")
            return None

        zip_resp = requests.get(dl_url, headers=headers, timeout=10)
        if zip_resp.status_code != 200:
            return None

        cache_dir = os.path.abspath(SUB_CACHE_DIR)
        os.makedirs(cache_dir, exist_ok=True)
        out_vtt_filename = f"online_{clean_mid}_{safe_slug}.vtt"
        out_vtt_path = os.path.abspath(os.path.join(cache_dir, out_vtt_filename))
        if os.path.commonpath([cache_dir, out_vtt_path]) != cache_dir:
            return None

        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
            for filename in z.namelist():
                if filename.lower().endswith(".srt"):
                    srt_data = z.read(filename)

                    text = None
                    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
                        try:
                            text = srt_data.decode(enc)
                            break
                        except Exception:
                            continue
                    if not text:
                        text = srt_data.decode("utf-8", errors="ignore")

                    vtt_lines = ["WEBVTT\n\n"]
                    for line in text.splitlines():
                        line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
                        vtt_lines.append(line + "\n")

                    with open(out_vtt_path, "w", encoding="utf-8") as f:
                        f.writelines(vtt_lines)

                    return {
                        "label": f"{safe_slug.replace('-', ' ').title()[:30]} (Online)",
                        "url": f"/api/subtitles/{clean_mid}/{out_vtt_filename}",
                        "language": "en",
                        "is_online": True
                    }
    except Exception as e:
        print("[Subtitles] Download online subtitle error:", e)

    return None
