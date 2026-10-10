# Implementation Plan: Plex-Style TV & Movie Theme Audio Previews

## Summary
Add Plex-style ambient theme music audio previews to TV and Movie media detail pages. Automatically checks for local `theme.mp3` / `theme.ogg` / `theme.m4a` / `theme.wav` in the media item's directory (following Plex conventions), falls back to cached downloads from AnimeThemes.moe for anime titles, and provides a sleek floating glassmorphic soundwave pill with animated equalizer bars, mute toggle, and volume control. Supports looping, auto-ducking on video trailer open, and profile/settings toggles.

## Proposed Changes

### Backend

#### 1. Theme Music Resolution & Cache Module (`backend/theme_music.py`)
- Define cache directory: `data/metadata/theme_music/`.
- Function `get_theme_audio_path(media_id_or_dict, media_type=None)`:
  1. **Local Media Folder (Plex Standard)**:
     - For movies: Check the directory containing the media file for `theme.mp3`, `theme.ogg`, `theme.wav`, `theme.m4a`.
     - For series/anime: Check the show's root directory (or parent directory of season folders) for `theme.mp3`, etc.
  2. **Cached Server Storage**:
     - Check `data/metadata/theme_music/{clean_key}.{ext}`.
  3. **Online Auto-Fetch (Anime via AnimeThemes.moe)**:
     - If media is anime or has a MAL ID / AniList match (via `get_mal_id_for_title` in `backend/skip_times.py`), query `https://api.animethemes.moe/anime?filter[has]=resources&include=animethemes.animethemeentries.videos.audio`.
     - Extract OP1 audio URL (or first OP audio).
     - Download audio file (with proper headers) and save to `data/metadata/theme_music/{clean_key}.ogg`.
  4. Returns `{ "has_theme": True, "file_path": path, "source": "local"|"animethemes"|"cached" }` or `{ "has_theme": False }`.

#### 2. Streaming & Metadata Endpoints (`backend/routes/streaming.py` & `backend/routes/media.py`)
- Endpoint: `GET /api/media/<int:media_id>/theme-music`
  - Streams the theme audio file with `Range` header support and caching headers (`audio/mpeg` or `audio/ogg`).
  - Supports kids guard (consistent with other media streaming).
- Endpoint: `GET /api/show/<int:tmdb_id>/theme-music`
  - Streams the show's theme audio using any episode or show directory as the base.
- Enhance `api_media_detail` and `api_show_detail` in `backend/routes/media.py`:
  - Include `has_theme_music: bool` and `theme_music_url: str` in the payload so the frontend knows immediately if theme music is available without a separate roundtrip.

#### 3. Settings Config (`backend/settings.py`)
- Add `"enable_theme_music": True` under `playback` in `DEFAULT_CONFIG`.
- Support saving and retrieving `playback.enable_theme_music` in `/api/settings`.

---

### Frontend

#### 4. Detail Page Theme Audio Player & Soundwave Pill (`static/js/app.js` & `static/css/main.css`)
- **Soundwave Pill UI**:
  - Located in the hero banner (top-right or adjacent to backdrop indicators).
  - Glassmorphic container with 4 animated vertical equalizer bars that pulse when playing.
  - Interactive volume control / mute icon (`ph-speaker-high` / `ph-speaker-slash`).
  - Tooltip: "Theme Music Preview • Click to mute / adjust volume".
- **Audio Lifecycle**:
  - Automatically loads audio from `theme_music_url`.
  - Smooth fade-in from 0 to 15% volume over 1.5 seconds.
  - Smooth continuous loop (`audio.loop = true`).
  - Immediately pauses / ducks volume if trailer modal opens or video playback begins.
  - Cleans up and stops audio immediately when navigating away (`onUnmounted` or route change).
  - Respects global setting (`store.playback?.enable_theme_music !== false`) and profile preference stored in `localStorage` (`capsstream_theme_music_muted`).

#### 5. Settings Playback Toggle (`static/js/app.js`)
- Add switch in Settings -> Playback section:
  - "Theme Music Previews: Softly play theme music when viewing movie and TV series detail pages."

---

### Documentation & Tracking

#### 6. Living Docs & GitHub Issue
- Create GitHub issue `#26` (already completed: `feat(player): Plex-style TV and movie theme audio previews`).
- Update `docs/prd.md` and `docs/architecture.md`.
- Append to `PROJECT-LOG.md`.

---

### Verification Plan
- Unit tests: Create `backend/tests/test_theme_music.py`:
  - Test local `theme.mp3` resolution in movie and show directories.
  - Test AnimeThemes query parsing and audio extraction mock.
  - Test `GET /api/media/<id>/theme-music` and `GET /api/show/<tmdb_id>/theme-music` endpoints.
  - Test `playback.enable_theme_music` toggle in settings.
- Integration test: Run full test suite (`pytest backend/tests`).
- Manual verification: Open detail page, verify soundwave pill animation, volume fading, mute toggling, and trailer pause.
