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

---

# System Architecture: Random Suggestion & Mood Match

## 1. Backend API (`backend/routes/media.py`)
- `GET /api/media/suggest`:
  - Query parameters:
    - `mood`: optional mood filter (`laugh`, `thrill`, `relax`, `mind-bend`, `cry`, `action-packed`).
    - `type`: optional type filter (`movie`, `series`, `anime`, or omit for all).
    - `unwatched`: optional boolean (`1` / `true`) - excludes titles with progress >= 90%.
    - `limit`: number of results (default 10, max 30).
    - `exclude_id`: comma-separated media IDs to exclude to avoid duplicate rolls.
  - Profile & Security:
    - Enforces active profile Kids filtering (`active_is_kids()`, `filter_for_profile()`).
    - Checks drive mount availability (`is_file_path_disabled`).

## 2. Frontend Architecture (`static/js/app.js` & `static/css/main.css`)
- **Navigation Trigger**:
  - Adds Dice button (`#nav-suggest` / `#tv-nav-suggest`) next to search in desktop and TV navigation headers.
  - Global reactive modal state `store.showSuggestModal`.
- **Suggestion Modal Component**:
  - Tab 1: **Quick Pick**:
    - Animated dice-roll state with shimmering placeholder during fetch.
    - Card preview with title, poster, year, rating badge, genres, and synopsis.
    - Dual CTA: "Play Now" (routes directly to watch) and "Details" (routes to title page).
    - Full-width "Roll Again" action button.
  - Tab 2: **Mood Match**:
    - Interactive mood chips mapped to genres.
    - Media type chips (All, Movies, TV Shows, Anime).
    - Unwatched only switch.
    - Matching cards grid / randomized selection list.
- **Styling**:
  - Modern glassmorphic modal design matching CapsStream design system.
  - Responsive layout down to 320px mobile viewports.

---

# System Architecture: Animated Preset Profile Avatars

## 1. Static Assets & Persistence (`static/img/Profile_Assets/` & `backend/routes/profiles.py`)
- **Asset Directory**: `static/img/Profile_Assets/` containing 10 animated GIFs:
  - `Profile 1.gif`, `Profile 2.gif`, `Profile 3.gif`, `Profile 4.gif`, `profile 5.gif`, `Profile 6.gif`, `Profile 7.gif`, `Profile 8.gif`, `Profile 9.gif`, `Profile 10.gif`.
- **Persistence**: Selected preset URLs (e.g. `/static/img/Profile_Assets/Profile 1.gif`) are stored directly in the `profiles.custom_avatar_url` column via `POST /api/profiles` and `PUT /api/profiles/<id>`.
- **URL Resolution**: `imgUrl()` in `static/js/app.js` passes `/static/...` paths through unchanged, enabling all existing avatar views (Profile Switcher, Navbar, TV Mode, PIN Modals) to display animated GIFs without schema changes.

## 2. Frontend Component (`ProfilesPage` in `static/js/app.js`)
- `presetAvatars`: Array of the 10 `/static/img/Profile_Assets/...` paths.
- `avatarPickerTab`: Reactive ref (`'animated' | 'icons' | 'upload'`) controlling the active tab in Create and Edit forms.
- `openCreateView()`: Sets `avatarPickerTab = 'animated'` and selects the first preset avatar not currently used by existing profiles.
- `openEditView(profile)`: Automatically opens the tab matching the profile's current avatar (`'animated'` if `custom_avatar_url` is in `presetAvatars`, `'upload'` if custom uploaded photo, otherwise `'icons'`).
- `onNewAvatarSelected(e)`: Previews uploaded file in Create Profile via object/data URL and uploads to `POST /api/profiles/<id>/avatar` upon creation if a file was staged.

---

# System Architecture: Media Deletion & Recycle Bin Integration

## 1. Native Recycle Bin Utility (`backend/trash.py`)
- Standardizes cross-platform recycling without external dependencies:
  - Windows: Uses `ctypes.windll.shell32.SHFileOperationW` with `FO_DELETE (0x0003)` and `FOF_ALLOWUNDO (0x0040)` to move files/directories into the Windows Recycle Bin so users can undo accidental deletions.
  - Fallback / Other OS: Delegates to `send2trash` if installed or `os.remove`.
- Includes directory cleanup if an empty series/show folder remains after deleting all media files.

## 2. API Endpoints (`backend/routes/media.py`)
- `POST /api/media/delete`:
  - Enforces Admin authentication (`require_admin` / PIN verification).
  - Accepts `{ media_id, tmdb_id, media_type, title, delete_files, admin_pin }`.
  - Determines affected file paths via repository lookups (`get_media_by_id`, `get_all_sources_for_media`, or `get_conn()`).
  - Calls `send_to_trash(file_path)` for each file.
  - Removes SQLite database rows (`delete_media_by_id`, `delete_media_by_tmdb`, `delete_media_by_title_and_type`).
  - Cascades foreign keys automatically (progress, favorites, bookmarks).
  - Invalidates home and library caches via `bust_home_cache()`.
- `POST /api/media/delete/preview`:
  - Returns `{ title, file_count, files, requires_pin }` to populate the danger confirmation modal before user execution.

## 3. Frontend Component (`DetailPage` in `static/js/app.js`)
- `detail-delete-btn`: Action circle button in `detail-quick-actions` (hidden from Kids profiles).
- `ep-delete-btn`: Trash button in `episode-action-btns` for individual episodes.
- `deleteMediaModal`: Danger confirmation dialog with glassmorphic red styling, summary of items/files to delete, PIN entry if required, and double-confirmation CTA.

