# Handoff

## 1. Goal
Implement graceful player recovery loop exit (navigating back to Media Details with external player recommendation modal upon repeated playback stalls) and modernize Media Organizer with a dedicated review modal and SSE progress telemetry.

## 2. Current State
- **Branch:** `main`
- **Pushed Commit:** `79e854a` (`feat(player): auto-redirect to details on playback stalls with external player recommendation`)
- **Push Status:** Successfully pushed to `origin/main` (`f674fad..79e854a`).
- **Release CI:** GitHub Actions `.github/workflows/auto-release.yml` triggered for auto-bump to `v2.84.0.0` with release update zip and Android TV APK.
- **Server Running Status:** Server verified on port `8700`.
- **Tests:** All 39 relevant test suites passing (`test_route_media.py`, `test_route_organizer.py`, `test_sub_naming.py`).

## 3. Active Files
- `static/js/player.js`: FreezeGuard recovery loop logic (`executeFreezeRecovery`, `triggerRecoveryFailureExit`, `swapStream`, `enableCompatPlayback`, `checkPlaybackStall`).
- `static/js/app.js`: `MediaDetailsPage` recovery failure modal lifecycle check (`checkPlaybackRecoveryFailure`) and external player launcher integration (`launchExternalFromRecovery`). Organizer Review modal with filter tabs.
- `static/css/main.css`: Styles for `.recovery-recommend-modal-*` and organizer review modal.
- `backend/external_player.py`: Win32 window minimization and external player process lifecycle management.
- `backend/organizer.py`: SSE telemetry stream and review scan isolation.
- `PROJECT-LOG.md`: Permanent historical session record.

## 4. Changes Made
- Added `triggerRecoveryFailureExit()` in `static/js/player.js` to tear down the HTML5 video element cleanly, set `capsstream_playback_recovery_failed` in `sessionStorage`, and call `goBack()`.
- Fixed counter reset regression in `swapStream()` and `enableCompatPlayback()` by introducing `preserveRecoveryCounter`, ensuring FreezeGuard reaches `MAX_RECOVERY_ATTEMPTS` without getting trapped in an infinite retry loop.
- Added "Playback Issue Detected" modal in `MediaDetailsPage` on `static/js/app.js` with 1-click external player launch (`Open with VLC` / `Open in Default Player`).
- Activated VLC live sync tracking modal and native window minimization via `/api/system/minimize-window`.
- Upgraded Media Organizer to separate preview scans from execution, preventing premature auto-renaming, and isolated scrollbars to `.organizer-items-log-scroll`.
- Cleaned up temporary corrupt test files and verified zero regressions.

## 5. Failed Attempts
- Resetting `consecutiveRecoveryAttempts` inside `swapStream()` and `enableCompatPlayback()` reset the retry count during recovery, creating an endless "Stream buffer stalled — auto-recovering..." toast loop. Fixed by adding `preserveRecoveryCounter: true` to recovery callers.
- In-page player error banner did not automatically guide the user to external players. Solved by returning to Media Details and rendering the centered recommendation modal with 1-click VLC launch.

## 6. Specific Next Steps
1. Verify GitHub Actions auto-release workflow run for `v2.84.0.0`.
2. Test real unplayable/corrupted media or network stream drops in production.
3. Verify Android TV companion client playback fallback on unplayable codecs.
