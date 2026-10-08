# Handoff

## 1. Goal
Fix companion subtitle naming and organization in the Automated Media Renamer & File Organizer engine, ensuring scene-named subtitles (e.g. `Backrooms.2026.1080p...[YTS.GG].srt`) and forced variants (`.force.srt`, `.forced.srt`) are accurately standardized to Plex/CapsStream-compliant companion names (e.g. `Backrooms (2026).en.forced.srt`, `Backrooms (2026).en.srt`), and that `Subs/` folders are discovered and organized without leaving orphaned tracks.

## 2. Current State
- **Branch:** `main`
- **Commit:** `829a45c` pushed successfully to `origin/main` (`dbfe437..829a45c`).
- **Release CI:** GitHub Actions auto-release workflow triggered on push to `main` (cutting patch bump `v2.79.2.0`).
- **Tests:** 432 unit and integration tests passing (`OK`) across the entire repository.
- **Working Tree:** Clean, synchronized with `origin/main`.

## 3. Active Files
- `backend/sub_naming.py`: Flag parsing (`force`, `forced`, `foreign`), tag formatting, and ISO 639-2 / 639-1 language alias map expansions.
- `backend/organizer.py`: Content-aware subtitle language detection, companion subtitle identification, Plex/CapsStream standardized naming in `build_subtitle_destination_path`, multi-folder discovery and deduplication in `find_companion_subtitles`, and subtitle plan construction in `scan_incoming_for_preview`.
- `backend/tests/test_organizer.py`: Unit tests for scene subtitle renaming, forced subtitle detection, and Subs/ folder discovery/deduplication.
- `PROJECT-LOG.md`: Permanent append-only project log.

## 4. Changes Made
- Expanded `is_forced` regex in `backend/sub_naming.py` to match `force`, `forced`, and `foreign`.
- Added ISO 639-2 codes to `LANG_ALIASES` (`bul`, `hrv`, `ice`, `lav`, `lit`, `slo`, `slv`, `srp`, `est`, `nob`, `fa`) for international scene subtitle packs.
- Implemented `detect_subtitle_language()` in `backend/organizer.py` for script and stopword content inspection.
- Updated `parse_subtitle_details()` to recognize media companion tracks and default companion subtitles to English (`en`).
- Updated `build_subtitle_destination_path()` so companion subtitles are formatted as `<Media Title>.<lang>[.<flag>].<ext>`, while preserving original names for unrelated tracks like `Director_Commentary_Track.srt`.
- Removed the root-subtitle gate in `find_companion_subtitles()`, enabling `Subs/` folder discovery even if a file exists beside the media, with content-fingerprint deduplication of identical root scene copies.
- Added comprehensive unit tests in `backend/tests/test_organizer.py`.

## 5. Failed Attempts
- Keying deduplication purely on `(size, head)` without folder context initially collapsed different language files in unit tests where mock files shared identical placeholder byte strings. Solved by scoping deduplication to skip root torrent copies when an exact duplicate exists inside a `Subs/` subfolder.
- Calling `.lower()` directly on `_clean_name()` failed because `_clean_name` returns a `(title, year)` tuple. Solved by properly unpacking `_clean_name(...)[0]`.

## 6. Specific Next Steps
1. Verify the CI release pipeline publishes `v2.79.2.0` and Android TV companion APK.
2. In production testing, test scanning an incoming folder with YTS/RARBG releases containing both root `.srt` and `Subs/` directories to confirm one-click clean organization.
3. If users request non-English default fallback for companion subtitles, consider making default companion language inherit from user-configured profile `default_sub_lang`.
