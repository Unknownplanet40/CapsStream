# Implementation Plan: Player Logo Loading Screen

Status: finalized (aligned with codebase, no code written yet).

## 0. Ground rules
- Do not change playback, subtitle, or control logic. Existing `isBuffering` behavior and the spinner stay exactly as they are for everything except the initial load.
- No new runtime dependencies. Pure CSS glint. Playback start is never blocked or delayed by the logo.
- Do not edit `VERSION` / `version.json`.
- Note: `static/js/player.js` has a known parse-partial warning around lines 88, 173-182, 239-240; use direct text inspection there.

## 1. What already exists (reuse, do not rebuild)

| Area | Existing code | Implication |
|---|---|---|
| Spinner overlay | `player.js` ~L1042-1050: `<div v-if="isBuffering" class="player-buffering-overlay">` containing `.loading-spinner`, plus the transcode status card below it; CSS at `main.css` ~L30942 | The spinner is shared by ALL buffering (initial, `waiting` stalls, seeks, transcode). Only the initial-load case gets the logo |
| `isBuffering` | Starts `false`; set true by `@waiting` (L33), transcode seeks (~L3273/3282/3432); false in `onVideoPlaying` (~L4453) and `cleanupPlayback` (~L6991) | There is NO existing "initial load" state; add one |
| Logo data | `backend/matcher.py::_extract_logo` -> `_download_image(.., "w500")` -> `media.logo_path` (`images/<name>`), ensured in `backend/routes/media.py` ~L386 via `ensure_media_logo` | Reuse `logo_path`; no new download logic |
| Logo display | `player.js` L299 pause screen uses `imgUrl(media.logo_path)`; `app.js` hero/detail also | Same URL helper (`imgUrl` -> `/metadata/images/...`) |
| Image serving | `app.py` `/metadata/images/<path:filename>` (~L344) already normalizes and confines the path | Traversal already blocked at serve time |
| Reduced motion | Several `@media (prefers-reduced-motion: reduce)` blocks in `main.css` | Follow the same pattern |

## 2. Decisions

1. **Scope**: logo replaces the spinner only during the **initial load** (player open -> first `playing` event). Mid-playback stalls, seeks, and quality switches keep the plain spinner.
2. **Initial-load state**: new `isInitialLoad` ref in `player.js`.
   - Set `true` when the player opens / media changes (start of the media load).
   - Set `false` in `onVideoPlaying`, on player error, and in `cleanupPlayback`.
   - Existing `isBuffering` logic is untouched. The loader overlay shows when `isBuffering || isInitialLoad`; the logo variant shows only when `isInitialLoad` and the logo is ready.
3. **Logo source**: reuse the existing `logo_path` (English/language-less preferred, else first). **User-language preference is deferred** (logos are cached once per title; per-profile variants are out of scope). Note this deviation from the raw prompt.
4. **Transcode card**: unchanged. The logo only replaces the spinner element; the "Converting Stream" card still appears below it. Paused-info dimming rule is unchanged.
5. **Before metadata arrives** (logo URL not known yet): show the spinner so there is never a blank screen. This means the spinner can now also appear during the metadata fetch at open (small new visual).

## 3. Behavior (states)

Pure function `logoLoaderState({ logoPath, status, reducedMotion })` returns what to render. States:

| Condition | Render |
|---|---|
| `isInitialLoad` false | spinner (existing behavior) |
| No `logo_path` (or invalid) | spinner |
| Logo preloading (not decoded) | spinner |
| Logo decoded | logo centered with glint (no spinner), crossfade swap |
| Preload error / timeout (~5s) | spinner permanently for this load, `console.warn` |
| Reduced motion | static logo, no glint |
| `isInitialLoad` ends | loader hides the same way and at the same time as the spinner does now (same `v-if`/`fade` transition and the same `onVideoPlaying` trigger) |

- **Preload**: create an `Image()`, set `src`, await `decode()`; on success flip a `logoReady` flag. Reset per media change so a stale result never applies to the next title (guard with the same token/ID pattern used elsewhere in the file).
- Never render the `<img>` until decoded, so a broken image can never show.
- Playback is never gated on the logo.

## 4. Glint + layout (CSS in `static/css/main.css`, near `.player-buffering-overlay`)
- Logo wrapper sized `max-width: 40%` of player width, `max-height: 30%` of player height, `object-fit: contain`, aspect ratio preserved, never cropped. Dark background friendly (transparent PNG/SVG/WebP).
- Glint: an overlay element masked by the logo itself (`mask-image: url(<logo>)`, `mask-size: contain`, `mask-repeat: no-repeat`, `mask-position: center`, with `-webkit-` prefixes) containing a diagonal soft gradient (`linear-gradient` ~110deg) whose `background-position` is animated.
- Timing: ~2s sweep with a pause between loops (keyframes spend the last portion idle, so the total cycle is ~3.5s). Subtle opacity.
- Mask URL is passed via a CSS custom property set inline. Same-origin, so no CORS issue.
- `@media (prefers-reduced-motion: reduce)`: `animation: none` and hide the glint layer; static logo remains.
- The spinner element itself is unchanged (existing inline style).

## 5. Validation and security
- **Server (one helper, e.g. in `backend/utils` or `backend/matcher.py`)**: `safe_logo_path(path) -> str | None` — requires the `images/` prefix, extension in `{png, svg, webp}`, no `..`/absolute/backslash segments, and the file exists under `IMAGES_DIR`. Applied where media is served to the player (`backend/routes/media.py` media detail). Invalid or missing -> `logo_path: null` plus a single server log line.
  - Side effect (accepted): hero/detail/paused-logo also stop showing an invalid logo, which is the safe outcome.
  - Assumption: TMDb logos are png/svg (TMDb `file_path` extension); a title with a `.jpg` logo would fall back to the spinner. Verify against existing cached files in `data/metadata/images` before enabling.
- **Client**: use `imgUrl()` only; only accept URLs starting `/metadata/images/` with an allowed extension before preloading. The existing serving route remains the traversal guard.

## 6. Logging
- Client `console.warn` when a logo fails to load or times out and the spinner is used. A missing logo (the normal default) is logged at debug level only.
- Server logs once when a `logo_path` is dropped as invalid or the file is missing on disk.
- No new server endpoint for client logs.

## 7. Tests

**Python** (`backend/tests/`, e.g. `test_logo_path.py` and route test in `test_route_media.py`):
- Valid `images/x.png|svg|webp` accepted.
- Traversal (`../`, `images/../../x.png`), absolute path, backslashes, wrong extension, `http://` URL, non-existent file -> rejected (`None`).
- Media detail returns `logo_path: null` for an invalid path and passes a valid one through.

**JS** (`node --test`, no new dependency; pure `logoLoaderState` in a small module, e.g. `static/js/logo-loader.js`, importable from the player and from the test):
- Logo present and decoded -> logo shown, spinner hidden.
- No logo -> spinner.
- Logo load failure -> spinner fallback.
- Slow logo -> spinner first, then swap when ready; timeout -> stays spinner.
- Reduced motion -> glint disabled flag.
- Not initial load -> spinner regardless of logo.

**Manual checklist**:
1. Open a title with a logo -> logo with glint until first frame, then the loader hides with the same fade as before.
2. Seek/stall mid-playback -> normal spinner (no logo).
3. Throttle the network (slow logo) -> spinner, then swap, no blank flash.
4. Delete the logo file -> spinner, one console warning, no broken image.
5. OS reduced-motion on -> static logo, no sweep.
6. Transcoded stream -> logo plus the Converting Stream card below it.
7. Switch titles quickly -> no stale logo from the previous title.

## 8. Files expected to change
- `static/js/player.js` (template block ~L1042, `isInitialLoad` ref, preload, exposed refs/return list ~L7261).
- `static/js/logo-loader.js` (new, pure state function; check how `player.js` is loaded before choosing import vs. global, since it is a classic script setup).
- `static/css/main.css` (logo wrapper, glint, reduced-motion).
- `backend/routes/media.py` + one validation helper.
- Tests as above.

## 9. Assumptions to verify at implementation time
- `player.js` / `index` template loads scripts as classic (non-module) scripts, so the pure helper may need a `window` global plus a CommonJS export guard for `node --test`.
- The media detail response used by the player contains `logo_path` before the first video event (it is used by the pause screen today).
- Service worker caching (`static/sw.js`) of `/metadata/images/` does not interfere with the preload.

## 10. Out of scope
- Per-user language logos; changing mid-playback buffering visuals; client-to-server log endpoint; new JS test framework; restyling the transcode card.