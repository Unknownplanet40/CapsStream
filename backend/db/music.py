# -*- coding: utf-8 -*-
"""Music library database helpers for CapsStream."""

from .connection import get_conn


def upsert_artist(name, sort_name=None, cover_path=None):
    if not name or not name.strip():
        name = "Unknown Artist"
    name = name.strip()
    conn = get_conn()
    row = conn.execute(
        "SELECT id, cover_path FROM music_artists WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        if cover_path and not row["cover_path"]:
            conn.execute(
                "UPDATE music_artists SET cover_path = ? WHERE id = ?",
                (cover_path, row["id"]),
            )
            conn.commit()
        conn.close()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO music_artists (name, sort_name, cover_path) VALUES (?, ?, ?)",
        (name, sort_name or name, cover_path),
    )
    conn.commit()
    res = cur.lastrowid
    conn.close()
    return res


def upsert_album(title, artist_id=None, album_artist=None, year=None, cover_path=None, genre=None):
    if not title or not title.strip():
        title = "Unknown Album"
    title = title.strip()
    conn = get_conn()
    if artist_id:
        row = conn.execute(
            "SELECT id, cover_path, year, genre, album_artist FROM music_albums WHERE title = ? COLLATE NOCASE AND artist_id = ?",
            (title, artist_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, cover_path, year, genre, album_artist FROM music_albums WHERE title = ? COLLATE NOCASE AND (artist_id IS NULL OR artist_id = 0)",
            (title,),
        ).fetchone()

    if row:
        updates = []
        params = []
        if cover_path and not row["cover_path"]:
            updates.append("cover_path = ?")
            params.append(cover_path)
        if year and not row["year"]:
            updates.append("year = ?")
            params.append(year)
        if genre and not row["genre"]:
            updates.append("genre = ?")
            params.append(genre)
        if album_artist and not row["album_artist"]:
            updates.append("album_artist = ?")
            params.append(album_artist)

        if updates:
            params.append(row["id"])
            conn.execute(
                f"UPDATE music_albums SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        res_id = row["id"]
        conn.close()
        return res_id

    cur = conn.execute(
        """INSERT INTO music_albums
           (artist_id, album_artist, title, year, cover_path, genre)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (artist_id, album_artist, title, year, cover_path, genre),
    )
    conn.commit()
    res_id = cur.lastrowid
    conn.close()
    return res_id


def upsert_track(
    file_path,
    title,
    artist_id=None,
    album_id=None,
    track_number=0,
    disc_number=1,
    duration=0,
    file_size=0,
    bitrate=None,
    sample_rate=None,
    fmt=None,
    genre=None,
    year=None,
    lyrics_path=None,
):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM music_tracks WHERE file_path = ?", (file_path,)
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE music_tracks SET
                title=?, artist_id=?, album_id=?, track_number=?, disc_number=?,
                duration=?, file_size=?, bitrate=?, sample_rate=?, format=?,
                genre=?, year=?, lyrics_path=COALESCE(?, lyrics_path)
               WHERE id=?""",
            (
                title, artist_id, album_id, track_number, disc_number,
                duration, file_size, bitrate, sample_rate, fmt,
                genre, year, lyrics_path, row["id"],
            ),
        )
        conn.commit()
        res_id = row["id"]
        conn.close()
        return res_id

    cur = conn.execute(
        """INSERT INTO music_tracks
           (album_id, artist_id, title, track_number, disc_number, duration,
            file_path, file_size, bitrate, sample_rate, format, genre, year, lyrics_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            album_id, artist_id, title, track_number, disc_number, duration,
            file_path, file_size, bitrate, sample_rate, fmt, genre, year, lyrics_path,
        ),
    )
    conn.commit()
    res_id = cur.lastrowid
    conn.close()
    return res_id


def get_artists(limit=500, offset=0):
    conn = get_conn()
    return conn.execute(
        """SELECT a.*, COUNT(t.id) AS track_count, COUNT(DISTINCT al.id) AS album_count
           FROM music_artists a
           LEFT JOIN music_tracks t ON t.artist_id = a.id
           LEFT JOIN music_albums al ON al.artist_id = a.id
           GROUP BY a.id
           ORDER BY a.sort_name COLLATE NOCASE
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()


def get_artist(artist_id):
    conn = get_conn()
    return conn.execute("SELECT * FROM music_artists WHERE id = ?", (artist_id,)).fetchone()


def get_albums(artist_id=None, limit=500, offset=0):
    conn = get_conn()
    if artist_id:
        return conn.execute(
            """SELECT al.*, ar.name AS artist_name, COUNT(t.id) AS track_count
               FROM music_albums al
               LEFT JOIN music_artists ar ON ar.id = al.artist_id
               LEFT JOIN music_tracks t ON t.album_id = al.id
               WHERE al.artist_id = ?
               GROUP BY al.id
               ORDER BY al.year DESC, al.title COLLATE NOCASE
               LIMIT ? OFFSET ?""",
            (artist_id, limit, offset),
        ).fetchall()
    return conn.execute(
        """SELECT al.*, ar.name AS artist_name, COUNT(t.id) AS track_count
           FROM music_albums al
           LEFT JOIN music_artists ar ON ar.id = al.artist_id
           LEFT JOIN music_tracks t ON t.album_id = al.id
           GROUP BY al.id
           ORDER BY al.added_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()


def get_album(album_id):
    conn = get_conn()
    return conn.execute(
        """SELECT al.*, ar.name AS artist_name
           FROM music_albums al
           LEFT JOIN music_artists ar ON ar.id = al.artist_id
           WHERE al.id = ?""",
        (album_id,),
    ).fetchone()


def get_tracks(album_id=None, artist_id=None, limit=1000, offset=0, profile_id=None):
    conn = get_conn()
    fav_join = ""
    fav_col = "0 AS is_favorite"
    params = []

    if profile_id:
        fav_join = "LEFT JOIN music_favorites f ON f.track_id = t.id AND f.profile_id = ?"
        fav_col = "CASE WHEN f.track_id IS NOT NULL THEN 1 ELSE 0 END AS is_favorite"
        params.append(profile_id)

    if album_id:
        params.extend([album_id, limit, offset])
        return conn.execute(
            f"""SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, {fav_col}
               FROM music_tracks t
               LEFT JOIN music_artists ar ON ar.id = t.artist_id
               LEFT JOIN music_albums al ON al.id = t.album_id
               {fav_join}
               WHERE t.album_id = ?
               ORDER BY t.disc_number, t.track_number, t.title
               LIMIT ? OFFSET ?""",
            params,
        ).fetchall()

    if artist_id:
        params.extend([artist_id, limit, offset])
        return conn.execute(
            f"""SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, {fav_col}
               FROM music_tracks t
               LEFT JOIN music_artists ar ON ar.id = t.artist_id
               LEFT JOIN music_albums al ON al.id = t.album_id
               {fav_join}
               WHERE t.artist_id = ?
               ORDER BY al.year DESC, t.disc_number, t.track_number
               LIMIT ? OFFSET ?""",
            params,
        ).fetchall()

    params.extend([limit, offset])
    return conn.execute(
        f"""SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, {fav_col}
           FROM music_tracks t
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           {fav_join}
           ORDER BY t.added_at DESC
           LIMIT ? OFFSET ?""",
        params,
    ).fetchall()


def get_track(track_id, profile_id=None):
    conn = get_conn()
    if profile_id:
        return conn.execute(
            """SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path,
                      CASE WHEN f.track_id IS NOT NULL THEN 1 ELSE 0 END AS is_favorite
               FROM music_tracks t
               LEFT JOIN music_artists ar ON ar.id = t.artist_id
               LEFT JOIN music_albums al ON al.id = t.album_id
               LEFT JOIN music_favorites f ON f.track_id = t.id AND f.profile_id = ?
               WHERE t.id = ?""",
            (profile_id, track_id),
        ).fetchone()

    return conn.execute(
        """SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, 0 AS is_favorite
           FROM music_tracks t
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           WHERE t.id = ?""",
        (track_id,),
    ).fetchone()


def search_music(q, limit=50, profile_id=None):
    pattern = f"%{(q or '').strip()}%"
    conn = get_conn()
    fav_join = ""
    fav_col = "0 AS is_favorite"
    params = []
    if profile_id:
        fav_join = "LEFT JOIN music_favorites f ON f.track_id = t.id AND f.profile_id = ?"
        fav_col = "CASE WHEN f.track_id IS NOT NULL THEN 1 ELSE 0 END AS is_favorite"
        params.append(profile_id)

    params.extend([pattern, pattern, pattern, limit])
    tracks = conn.execute(
        f"""SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, {fav_col}
           FROM music_tracks t
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           {fav_join}
           WHERE t.title LIKE ? OR ar.name LIKE ? OR al.title LIKE ?
           ORDER BY t.title LIMIT ?""",
        params,
    ).fetchall()
    return tracks


def record_play(profile_id, track_id, duration_played=0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO music_history (profile_id, track_id, duration_played) VALUES (?, ?, ?)",
        (profile_id, track_id, duration_played),
    )
    conn.execute(
        "UPDATE music_tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?",
        (track_id,),
    )
    conn.commit()


def get_recently_played(profile_id, limit=30):
    conn = get_conn()
    return conn.execute(
        """SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path,
                  h.played_at,
                  CASE WHEN f.track_id IS NOT NULL THEN 1 ELSE 0 END AS is_favorite
           FROM music_history h
           JOIN music_tracks t ON t.id = h.track_id
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           LEFT JOIN music_favorites f ON f.track_id = t.id AND f.profile_id = h.profile_id
           WHERE h.profile_id = ?
           ORDER BY h.played_at DESC
           LIMIT ?""",
        (profile_id, limit),
    ).fetchall()


# ─── Favorites / Liked Songs ──────────────────────────────────────────────────

def toggle_favorite_track(profile_id, track_id):
    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM music_favorites WHERE profile_id = ? AND track_id = ?",
        (profile_id, track_id),
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM music_favorites WHERE profile_id = ? AND track_id = ?",
            (profile_id, track_id),
        )
        conn.commit()
        return False
    else:
        conn.execute(
            "INSERT OR IGNORE INTO music_favorites (profile_id, track_id) VALUES (?, ?)",
            (profile_id, track_id),
        )
        conn.commit()
        return True


def get_favorite_tracks(profile_id, limit=500, offset=0):
    conn = get_conn()
    return conn.execute(
        """SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path,
                  f.added_at AS favorited_at, 1 AS is_favorite
           FROM music_favorites f
           JOIN music_tracks t ON t.id = f.track_id
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           WHERE f.profile_id = ?
           ORDER BY f.added_at DESC
           LIMIT ? OFFSET ?""",
        (profile_id, limit, offset),
    ).fetchall()


# ─── Playlists ───────────────────────────────────────────────────────────────

def get_playlists(profile_id):
    conn = get_conn()
    return conn.execute(
        """SELECT p.*, COUNT(pt.id) AS track_count
           FROM music_playlists p
           LEFT JOIN music_playlist_tracks pt ON pt.playlist_id = p.id
           WHERE p.profile_id = ?
           GROUP BY p.id
           ORDER BY p.updated_at DESC""",
        (profile_id,),
    ).fetchall()


def get_playlist(playlist_id, profile_id=None):
    conn = get_conn()
    if profile_id:
        return conn.execute(
            "SELECT * FROM music_playlists WHERE id = ? AND profile_id = ?",
            (playlist_id, profile_id),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM music_playlists WHERE id = ?",
        (playlist_id,),
    ).fetchone()


def create_playlist(profile_id, name, description=""):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO music_playlists (profile_id, name, description) VALUES (?, ?, ?)",
        (profile_id, name, description),
    )
    conn.commit()
    return cur.lastrowid


def delete_playlist(playlist_id, profile_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM music_playlists WHERE id = ? AND profile_id = ?",
        (playlist_id, profile_id),
    )
    conn.commit()


def get_playlist_tracks(playlist_id, profile_id=None):
    conn = get_conn()
    fav_join = ""
    fav_col = "0 AS is_favorite"
    params = []
    if profile_id:
        fav_join = "LEFT JOIN music_favorites f ON f.track_id = t.id AND f.profile_id = ?"
        fav_col = "CASE WHEN f.track_id IS NOT NULL THEN 1 ELSE 0 END AS is_favorite"
        params.append(profile_id)
    params.append(playlist_id)

    return conn.execute(
        f"""SELECT t.*, ar.name AS artist_name, al.title AS album_title, al.cover_path, pt.position, {fav_col}
           FROM music_playlist_tracks pt
           JOIN music_tracks t ON t.id = pt.track_id
           LEFT JOIN music_artists ar ON ar.id = t.artist_id
           LEFT JOIN music_albums al ON al.id = t.album_id
           {fav_join}
           WHERE pt.playlist_id = ?
           ORDER BY pt.position""",
        params,
    ).fetchall()


def add_to_playlist(playlist_id, track_id, position=None):
    conn = get_conn()
    if position is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM music_playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()
        position = row["pos"]
    conn.execute(
        "INSERT INTO music_playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
        (playlist_id, track_id, position),
    )
    conn.execute(
        "UPDATE music_playlists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (playlist_id,),
    )
    conn.commit()


def remove_from_playlist(playlist_id, track_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM music_playlist_tracks WHERE playlist_id = ? AND track_id = ?",
        (playlist_id, track_id),
    )
    conn.execute(
        "UPDATE music_playlists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (playlist_id,),
    )
    conn.commit()


def remove_missing_tracks(existing_file_paths):
    """Clean up track records whose file paths no longer exist on disk."""
    conn = get_conn()
    all_tracks = conn.execute("SELECT id, file_path FROM music_tracks").fetchall()
    deleted = 0
    for t in all_tracks:
        if t["file_path"] not in existing_file_paths:
            conn.execute("DELETE FROM music_tracks WHERE id = ?", (t["id"],))
            deleted += 1

    if deleted > 0:
        # Clean up orphan albums and artists with 0 tracks
        conn.execute("DELETE FROM music_albums WHERE id NOT IN (SELECT DISTINCT album_id FROM music_tracks WHERE album_id IS NOT NULL)")
        conn.execute("DELETE FROM music_artists WHERE id NOT IN (SELECT DISTINCT artist_id FROM music_tracks WHERE artist_id IS NOT NULL)")
        conn.commit()
    conn.close()
    return deleted


def update_track_lyrics(track_id, lyrics_path):
    conn = get_conn()
    conn.execute("UPDATE music_tracks SET lyrics_path = ? WHERE id = ?", (lyrics_path, track_id))
    conn.commit()
    conn.close()


def update_album_metadata(album_id, cover_path=None, year=None, mbid=None):
    conn = get_conn()
    updates = []
    params = []
    if cover_path:
        updates.append("cover_path = ?")
        params.append(cover_path)
    if year:
        updates.append("year = ?")
        params.append(year)
    if mbid:
        updates.append("mbid = ?")
        params.append(mbid)
    if updates:
        params.append(album_id)
        conn.execute(f"UPDATE music_albums SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()


def update_artist_metadata(artist_id, cover_path=None, biography=None, mbid=None):
    conn = get_conn()
    updates = []
    params = []
    if cover_path:
        updates.append("cover_path = ?")
        params.append(cover_path)
    if biography:
        updates.append("biography = ?")
        params.append(biography)
    if mbid:
        updates.append("mbid = ?")
        params.append(mbid)
    if updates:
        params.append(artist_id)
        conn.execute(f"UPDATE music_artists SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()

