# Handoff

## 1. Goal
Fix Host PC Documents User Data Sync resurrection bug where clearing watch progress or watch history restored deleted items upon app restart.

## 2. Current State
- **Branch:** `main`
- **Remote Status:** Up to date with origin (will rebase on CI version bump commit `2fda6e9`).
- **Release CI:** Previous release workflow completed (`v2.81.0.0`). Next auto-release will cut patch release upon push.
- **Tests:** 19/19 tests passing across `test_host_sync` and `test_route_library`.
- **Working Tree:** Ready for commit and approval before push.

## 3. Active Files
- `backend/db/playback.py`: Added `delete_watch_history()` and updated `delete_progress(profile_id, media_id, clear_history=True)`.
- `backend/db/__init__.py`: Exported `delete_watch_history`.
- `backend/host_sync.py`: Added `delete_host_watch_history()` to purge matching entries from host Documents sync database(s).
- `backend/routes/library.py`: Updated `api_mark_unwatched` to purge series and episode history across local and host databases.
- `backend/tests/test_host_sync.py`: Added `test_delete_progress_syncs_with_host_and_prevents_resurrection`.
- `backend/tests/test_route_library.py`: Updated unit tests for `mark-unwatched` and `delete_progress`.
- `PROJECT-LOG.md`: Permanent append-only project log.

## 4. Changes Made
- Investigated why items deleted from Continue Watching / watch progress resurrected upon application restart when Host Sync was active.
- Isolated root cause: deleting from `watch_progress` left `watch_history` intact in both local DB and Documents sync database (`user_data.db`). On startup, `import_user_data_from_host()` restored progress from `watch_history`.
- Implemented `delete_watch_history` and enhanced `delete_progress` to also remove history and sync immediate deletion to host PC Documents sync database.
- Added automated unit tests reproducing and verifying fix.

## 5. Failed Attempts
- Initial test mock for `delete_progress` in `test_route_library.py` failed due to the new `clear_history=True` default argument; resolved cleanly.

## 6. Specific Next Steps
1. Ask user for confirmation to push commit to `origin/main`.
2. Rebase onto `origin/main` (`2fda6e9`) to incorporate the auto-release commit.
3. Push to `origin/main` and verify `auto-release.yml` cuts the next patch release.
