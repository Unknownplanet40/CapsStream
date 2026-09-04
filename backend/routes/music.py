# -*- coding: utf-8 -*-
"""Music API blueprint for CapsStream."""

import os
import threading
from flask import Blueprint, jsonify, request, send_file, abort, session
from backend.db import music as mdb
from backend.music_scanner import scan_music_library, get_music_scan_status, _read_tags
from backend.streamer import stream_file
from backend.utils.paths import BASE_DIR

music_bp = Blueprint("music", __name__, url_prefix="/api/music")


def _profile_id():
    pid = session.get("profile_id")
    if pid:
        try:
            return int(pid)
        except Exception:
            pass
    # Check header or query param if session is not set
    hdr = request.headers.get("X-Profile-ID") or request.args.get("profile_id")
    if hdr:
        try:
            return int(hdr)
        except Exception:
            pass
    return 1


@music_bp.route("/artists")
def api_artists():
    limit = min(int(request.args.get("limit", 500)), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows = mdb.get_artists(limit=limit, offset=offset)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/artists/<int:artist_id>")
def api_artist(artist_id):
    pid = _profile_id()
    row = mdb.get_artist(artist_id)
    if not row:
        abort(404)
    albums = mdb.get_albums(artist_id=artist_id)
    tracks = mdb.get_tracks(artist_id=artist_id, limit=200, profile_id=pid)
    return jsonify({
        "artist": dict(row),
        "albums": [dict(a) for a in albums],
        "tracks": [dict(t) for t in tracks],
    })


@music_bp.route("/albums")
def api_albums():
    limit = min(int(request.args.get("limit", 500)), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)
    artist_id = request.args.get("artist_id", type=int)
    rows = mdb.get_albums(artist_id=artist_id, limit=limit, offset=offset)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/albums/<int:album_id>")
def api_album(album_id):
    pid = _profile_id()
    row = mdb.get_album(album_id)
    if not row:
        abort(404)
    tracks = mdb.get_tracks(album_id=album_id, profile_id=pid)
    return jsonify({
        "album": dict(row),
        "tracks": [dict(t) for t in tracks],
    })


@music_bp.route("/tracks")
def api_tracks():
    pid = _profile_id()
    album_id = request.args.get("album_id", type=int)
    artist_id = request.args.get("artist_id", type=int)
    limit = min(int(request.args.get("limit", 1000)), 2000)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows = mdb.get_tracks(album_id=album_id, artist_id=artist_id, limit=limit, offset=offset, profile_id=pid)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/tracks/<int:track_id>")
def api_track(track_id):
    pid = _profile_id()
    row = mdb.get_track(track_id, profile_id=pid)
    if not row:
        abort(404)
    return jsonify(dict(row))


@music_bp.route("/search")
def api_search():
    pid = _profile_id()
    q = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 50)), 100)
    rows = mdb.search_music(q, limit=limit, profile_id=pid)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/stream/<int:track_id>")
def api_stream(track_id):
    row = mdb.get_track(track_id)
    if not row or not os.path.isfile(row["file_path"]):
        abort(404)

    file_path = row["file_path"]
    ext = os.path.splitext(file_path)[1].lower()

    # Direct range streaming for modern browser audio formats
    if ext in {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"}:
        return stream_file(file_path)

    # Fallback to direct range streaming
    return stream_file(file_path)


@music_bp.route("/lyrics/<int:track_id>")
def api_lyrics(track_id):
    row = mdb.get_track(track_id)
    if not row:
        abort(404)
    track = dict(row)

    # 1. Local .lrc file check
    path = track.get("lyrics_path")
    if (not path or not os.path.isfile(path)) and track.get("file_path"):
        from backend.music_scanner import _find_lrc
        candidate = _find_lrc(track["file_path"])
        if candidate and os.path.isfile(candidate):
            path = candidate
            mdb.update_track_lyrics(track_id, candidate)

    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            is_synced = "[" in content and "]" in content
            return jsonify({"lyrics": content, "synced": is_synced, "source": "local"})
        except Exception as e:
            print(f"[MusicAPI] Read lrc error {path}: {e}")

    # 2. Check for embedded lyrics in audio tags
    file_path = track.get("file_path")
    if file_path and os.path.isfile(file_path):
        try:
            tags = _read_tags(file_path)
            embedded = tags.get("embedded_lyrics")
            if embedded:
                is_synced = "[" in embedded and "]" in embedded
                return jsonify({"lyrics": embedded, "synced": is_synced, "source": "embedded"})
        except Exception:
            pass

    # 3. Automatic Online Fetch via LRCLIB (100% free synced lyrics)
    try:
        from backend.music_metadata import fetch_synced_lyrics, save_lyrics_file
        res = fetch_synced_lyrics(
            title=track.get("title"),
            artist=track.get("artist_name"),
            album=track.get("album_title"),
            duration=track.get("duration"),
        )
        if res and res.get("lyrics"):
            saved_path = save_lyrics_file(track_id, res["lyrics"])
            if saved_path:
                mdb.update_track_lyrics(track_id, saved_path)
            return jsonify({
                "lyrics": res["lyrics"],
                "synced": res.get("synced", False),
                "source": "lrclib",
            })
    except Exception as e:
        print(f"[MusicAPI] LRCLIB lyrics fetch notice for track {track_id}: {e}")

    return jsonify({"lyrics": None, "synced": False, "source": None})


@music_bp.route("/albums/<int:album_id>/fetch-cover", methods=["POST"])
def api_fetch_album_cover(album_id):
    row = mdb.get_album(album_id)
    if not row:
        abort(404)
    album = dict(row)
    from backend.music_metadata import search_musicbrainz_album, fetch_cover_art_archive, fetch_theaudiodb_album

    # 1. Try TheAudioDB first (fast & reliable direct cover art)
    tadb = fetch_theaudiodb_album(album["title"], album.get("artist_name"))
    if tadb and tadb.get("cover_path"):
        mdb.update_album_metadata(album_id, cover_path=tadb["cover_path"], year=tadb.get("year"))
        return jsonify({"ok": True, "cover_path": tadb["cover_path"], "source": "theaudiodb"})

    # 2. Try MusicBrainz & Cover Art Archive
    res = search_musicbrainz_album(album["title"], album.get("artist_name"))
    if res and res.get("mbid"):
        cover_rel = fetch_cover_art_archive(res["mbid"])
        if cover_rel:
            mdb.update_album_metadata(album_id, cover_path=cover_rel, year=res.get("year"), mbid=res.get("mbid"))
            return jsonify({"ok": True, "cover_path": cover_rel, "mbid": res["mbid"], "source": "musicbrainz"})

    return jsonify({"ok": False, "error": "No cover found online"}), 404


@music_bp.route("/artists/<int:artist_id>/fetch-info", methods=["POST"])
def api_fetch_artist_info(artist_id):
    row = mdb.get_artist(artist_id)
    if not row:
        abort(404)
    artist = dict(row)
    from backend.music_metadata import fetch_artist_info
    info = fetch_artist_info(artist["name"])
    if info:
        mdb.update_artist_metadata(artist_id, cover_path=info.get("photo_path"), biography=info.get("biography"))
        return jsonify({"ok": True, **info})
    return jsonify({"ok": False}), 404




@music_bp.route("/covers/<path:filename>")
def api_cover(filename):
    # Sanitize
    clean_filename = os.path.basename(filename)
    path = os.path.join(BASE_DIR, "data", "music_covers", clean_filename)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, conditional=True, max_age=86400 * 7)


@music_bp.route("/history", methods=["GET", "POST"])
def api_history():
    pid = _profile_id()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        track_id = data.get("track_id")
        duration_played = data.get("duration_played", 0)
        if track_id:
            mdb.record_play(pid, track_id, duration_played)
        return jsonify({"ok": True})

    limit = min(int(request.args.get("limit", 30)), 100)
    rows = mdb.get_recently_played(pid, limit=limit)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/favorites", methods=["GET", "POST"])
def api_favorites():
    pid = _profile_id()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        track_id = data.get("track_id")
        if not track_id:
            return jsonify({"error": "Missing track_id"}), 400
        is_fav = mdb.toggle_favorite_track(pid, track_id)
        return jsonify({"ok": True, "is_favorite": is_fav})

    limit = min(int(request.args.get("limit", 500)), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows = mdb.get_favorite_tracks(pid, limit=limit, offset=offset)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/playlists", methods=["GET", "POST"])
def api_playlists():
    pid = _profile_id()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "New Playlist").strip()
        pl_id = mdb.create_playlist(pid, name, data.get("description", ""))
        return jsonify({"id": pl_id, "name": name})

    rows = mdb.get_playlists(pid)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/playlists/<int:playlist_id>", methods=["GET", "DELETE"])
def api_playlist_detail(playlist_id):
    pid = _profile_id()
    if request.method == "DELETE":
        mdb.delete_playlist(playlist_id, pid)
        return jsonify({"ok": True})

    pl = mdb.get_playlist(playlist_id, pid)
    if not pl:
        abort(404)
    tracks = mdb.get_playlist_tracks(playlist_id, profile_id=pid)
    return jsonify({
        "playlist": dict(pl),
        "tracks": [dict(t) for t in tracks],
    })


@music_bp.route("/playlists/<int:playlist_id>/tracks", methods=["GET", "POST"])
def api_playlist_tracks(playlist_id):
    pid = _profile_id()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        track_id = data.get("track_id")
        if track_id:
            mdb.add_to_playlist(playlist_id, track_id)
        return jsonify({"ok": True})

    rows = mdb.get_playlist_tracks(playlist_id, profile_id=pid)
    return jsonify([dict(r) for r in rows])


@music_bp.route("/playlists/<int:playlist_id>/tracks/<int:track_id>", methods=["DELETE"])
def api_playlist_remove_track(playlist_id, track_id):
    mdb.remove_from_playlist(playlist_id, track_id)
    return jsonify({"ok": True})


@music_bp.route("/scan", methods=["POST"])
def api_scan():
    def _run():
        scan_music_library()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@music_bp.route("/scan/status")
def api_scan_status():
    return jsonify(get_music_scan_status())
