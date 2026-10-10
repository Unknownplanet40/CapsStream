# System Architecture: CapsStream Moments

## 1. Database Schema (SQLite)
A new `bookmarks` table is introduced in `backend/db/schema.py`:

```sql
CREATE TABLE IF NOT EXISTS bookmarks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    media_id   INTEGER NOT NULL,
    position   INTEGER NOT NULL,          -- timestamp in seconds
    note       TEXT DEFAULT '',           -- custom text note
    category   TEXT DEFAULT 'general',    -- action, funny, quote, plot_twist, music, general
    color      TEXT DEFAULT '#e50914',    -- hex accent color for seekbar pin
    is_shared  INTEGER NOT NULL DEFAULT 0,-- 0 = private to profile, 1 = shared with household
    thumb_path TEXT DEFAULT '',           -- optional cached snapshot image path
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_media ON bookmarks(media_id, position);
CREATE INDEX IF NOT EXISTS idx_bookmarks_profile ON bookmarks(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_shared ON bookmarks(media_id, is_shared);
```

## 2. API Endpoints (`backend/routes/media.py`)
- `GET /api/media/<int:media_id>/bookmarks?profile_id=<int>`:
  Returns all bookmarks for the media item visible to the given profile (where `profile_id = ? OR is_shared = 1`).
- `POST /api/media/<int:media_id>/bookmarks`:
  Creates a new bookmark. Payload: `{ profile_id, position, note, category, color, is_shared, thumb_data_url }`.
  Saves `thumb_data_url` (base64) to `data/metadata/moments/{bookmark_id}.webp`.
- `PATCH /api/bookmarks/<int:bookmark_id>`:
  Updates `note`, `category`, `color`, or `is_shared`. Validates profile ownership.
- `DELETE /api/bookmarks/<int:bookmark_id>`:
  Deletes the bookmark and cleans up associated thumbnail files.
- `GET /api/profile/<int:profile_id>/bookmarks`:
  Returns all saved moments across the library for the user's Profile gallery view.

## 3. Frontend Architecture
- **Player Component (`static/js/player.js`)**:
  - `bookmarks`: Reactive ref array containing moments for the current media item.
  - `shortcut 'b' / 'B'`: Triggers `saveQuickMoment()`.
  - `saveQuickMoment()`: Captures `currentTime`, extracts a frame into `<canvas>`, posts to API, and pushes to local `bookmarks` array.
  - `momentToast`: Reactive state showing 3-second quick action toast with "Add Note" button.
  - `momentNoteModal`: Modal dialog to edit note, category chip, and family sharing.
  - `player-progress-bar`: Renders `.moment-seekbar-pin` elements positioned by `(bookmark.position / duration) * 100%`.
  - `momentsDrawer`: Side-drawer inside player HUD listing all video moments.
- **App Single-Page Application (`static/js/app.js`)**:
  - `DetailPage`: Adds "Moments" tab with thumbnail cards, timestamps, category badges, and play links (`/watch/:id?t=:position`).
  - `ProfilesPage`: Adds "Saved Moments" gallery tab with search and category filtering.
- **Styling (`static/css/main.css`)**:
  - CSS styles for `.moment-seekbar-pin`, `.moment-hover-card`, `.moment-toast`, and `.moment-drawer`.

---

# System Architecture: Theme Audio Previews

## 1. Resolution & Cache Service (`backend/theme_music.py`)
- Directory: `data/metadata/theme_music/`.
- Resolves theme audio via `find_local_theme_file()`, `find_cached_theme_file()`, and `fetch_animethemes_audio()`.
- Supports audio extensions `.mp3`, `.ogg`, `.m4a`, `.wav`, `.flac`.

## 2. Streaming Endpoints (`backend/routes/streaming.py`)
- `GET /api/media/<int:media_id>/theme-music`: Streams audio file for movie or episode with RFC 7233 byte-range support.
- `GET /api/show/<int:tmdb_id>/theme-music`: Streams audio file for TV or anime series.
- `api_media_detail` & `api_show_detail` in `backend/routes/media.py`: Returns `has_theme_music: bool` and `theme_music_url: str`.

## 3. Frontend Audio Controller & UI
- **Detail Page Component (`static/js/app.js`)**:
  - Audio controller: HTML5 `Audio()` instance with 1.5s volume fade-in from 0 to 15%.
  - Looping: Continuous playback while viewing detail page.
  - Event hooks: Pauses on trailer launch and cleans up completely on page leave (`onUnmounted`).
  - `.theme-music-pill`: Floating glassmorphic soundwave pill with animated CSS equalizer bars and mute toggle.
  - Global toggle in Settings (`playback.enable_theme_music`) and localStorage mute preference.

