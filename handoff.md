# Handoff

## 1. Goal
Implement Plex-Style TV & Movie Theme Audio Previews with local media folder auto-detection, server caching, AnimeThemes.moe online provider integration, RFC 7233 audio streaming, and ambient glassmorphic soundwave controls.

## 2. Current State
- **Branch:** `main`
- **Remote Status:** Remote has CI patch bump commit `d35cbea` (`chore(release): patch bump to 2.81.1.0 [skip ci]`). Rebase required before push.
- **Release CI:** Next auto-release upon push will cut minor feature release (`feat(...)`).
- **Tests:** 5/5 theme music unit and integration tests passing (`test_theme_music.py`); 48/48 regression tests passing (`test_route_media.py` and `test_streaming.py`).
- **Working Tree:** All changes implemented, verified, and staged.

## 3. Active Files
- `backend/theme_music.py`: Resolution hierarchy for local `theme.mp3`, cached audio, and AnimeThemes.moe API fetcher.
- `backend/routes/streaming.py`: Added `GET /api/media/<id>/theme-music` and `GET /api/show/<tmdb_id>/theme-music`.
- `backend/routes/media.py`: Added `has_theme_music` and `theme_music_url` metadata to `api_media_detail` and `api_show_detail`.
- `backend/settings.py`: Added `enable_theme_music: True` configuration default.
- `static/js/app.js`: Audio playback engine, volume fade-in, mute toggle, trailer pause/resume, and settings switch.
- `static/css/main.css`: Floating `.theme-music-pill` and animated `@keyframes eq-bounce` equalizer.
- `backend/tests/test_theme_music.py`: Unit and integration test suite.
- `docs/prd.md`, `docs/architecture.md`, `PROJECT-LOG.md`: Living documentation.

## 4. Changes Made
- Auto-detects local `theme.mp3`, `theme.ogg`, `theme.wav`, `theme.m4a`, `theme.flac` in movie folders and show root folders (Plex-standard).
- Integrated AnimeThemes.moe API for automatic fetching and local caching of anime opening themes.
- Built RFC 7233 partial streaming endpoints with Kids Mode security guards.
- Created floating glassmorphic soundwave pill on the Detail Page hero banner with animated visualizer bars.
- Implemented smooth 1.5s volume fade-in (15% ambient default), seamless looping, and auto-pause on trailer/video start.
- Added global user toggle in Settings -> Playback Defaults and persistent browser `localStorage` mute state.

## 5. Failed Attempts
- Direct `requests.head()` on AnimeThemes audio stream returned 403 Forbidden without browser user-agent and referer headers; resolved by sending standard browser headers.
- Pytest `client` fixture was not defined globally; resolved by using standard Flask test client pattern matching existing test suites.

## 6. Specific Next Steps
1. Ask user for confirmation before executing `git push`.
2. Commit changes using full conventional changelog message referencing issue `#26`.
3. Rebase onto `origin/main` (`d35cbea`).
4. Execute `git push` upon user approval and monitor automated CI release.
