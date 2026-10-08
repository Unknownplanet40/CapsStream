# Implementation Plan: Local Region Routing, Subtitle Renaming, Player Subtitle Labels

Status: finalized (aligned with codebase, no code written yet).

## 0. Ground rules

- Extend the existing organizer (`backend/organizer.py`, `backend/routes/organizer.py`) and subtitles (`backend/subtitles.py`, `static/js/player.js`). Do not break current behavior; with new settings at their defaults, behavior is identical to today.
- Minimal new dependencies (none expected). Strong typing (type hints), path sanitization, traversal blocking, extension validation.
- Do not edit `VERSION` / `version.json`. Tests under `backend/tests/`.

## 1. What already exists (do NOT rebuild)

| Area | Existing code | Implication |
|---|---|---|
| Dry-run / preview | `scan_incoming_for_preview`, `POST /api/admin/organizer/preview`, CLI `--dry-run` | Extend payload only (route reason, subtitle renames, skip reasons) |
| Execute + history/undo | `execute_organization_plan`, `record_history`, `undo_batch` (subtitle ops already recorded) | Reuse; log skips with reasons |
| Collision handling | `execute_file_operation` returns `"collision"`; subtitles auto-suffix `.2`, `.3` in `build_subtitle_destination_path` | Add configurable policy for videos only |
| Subtitle detection | `parse_subtitle_details`, `find_companion_subtitles` (per-episode matching via `S01E01` token) | Refactor parsing into shared module; keep companion matching |
| Subtitle naming | `build_subtitle_destination_path` already emits `.en`, `.en.hi`, `.en.forced` | Extend, fix gaps (see section 3) |
| Player track list | `get_all_subtitles` -> `_parse_sub_label` + `LANG_NAMES` (Tagalog already present) feed `subtitles` in the player | Single backend source; player only displays |
| Player subtitle loading/switching | `player.js` (`selectSub`, track error handling, `subtitles` ref); default selection near `player.js:6805-6820` | Keep as is; only change default selection + label fields |
| Config | `organizer` block in config via `_get_organizer_config` / `api_save_organizer_config`; settings UI in `static/js/app.js` | Add new keys + dropdown here |

## 2. Feature 1: Local region routing

### Decisions
- **Scope**: Movies and TV only. **Anime is untouched** and always uses the anime root.
- **Config** (stored in `organizer` config block, exposed by the config GET/POST API):
  - `local_region`: ISO 3166-1 alpha-2 code; empty string = feature off (default).
  - `target_local_movies_path`, `target_local_series_path`: absolute paths, same pattern as existing `target_movies_path` / `target_series_path`. The "root `T:\`" is whatever the user types; nothing hardcoded. Example: `T:\Local\Movie`, `T:\Local\Series`.
  - `collision_policy`: `"skip"` (default) or `"suffix"`.
- **Region list**: one dict in the backend, e.g. `REGIONS: dict[str, str] = {"PH": "Philippines", ...}` (seed: Philippines + a few common ones). Served via the organizer config GET (`regions`) and rendered by the dropdown. Adding a region = one dict entry.
- **Library roots**: `_get_organizer_config()["library_roots"]` gains `local_movies`, `local_tv`. The same roots dict is built in three places that must stay in sync: `backend/routes/organizer.py::_get_organizer_config`, the watcher `_organizer_watcher_loop`, and the CLI `main()`. Prefer extracting a single builder instead of editing three copies.
- `_is_path_allowed` (webhook) must include the local roots in the allowed set.
- Inner folder structure is unchanged (`{root}/{Title} ({Year})/{file}` for movies, `{root}/{Title}/Season XX/...` for series); Local only swaps the root.

### Routing rules
| Item | Destination |
|---|---|
| Non-local movie | movies root (unchanged) |
| Non-local series | series root (unchanged) |
| Local movie | `target_local_movies_path` |
| Local series | `target_local_series_path` |
| Anime (any origin) | anime root (unchanged) |

### Local detection
- Capture origin during `resolve_canonical_item` (TMDb stage), country-first:
  - TV: TMDb search result `origin_country` (list of codes).
  - Movie: `production_countries` from one extra `GET /movie/{id}` call (search results do not include it). Only called when `local_region` is set and the item is a TMDb-resolved movie.
  - Language alone is NEVER used.
- Local = selected region code is in the item's country list.
- Not determinable (no TMDb key, TMDb failed, matched only via `requests.json`/parsed fallback, empty country list): use the normal Movies/Series route and log `"origin unknown, routed normally"`. Never guess.
- Resolved item gets `origin_countries` and `route_reason` (`local`, `non-local`, `origin-unknown`, `region-off`) so preview can show why.
- `build_destination_path` stays the single place computing destinations; it accepts the region/local roots from the roots dict and the resolved item.

### Collisions (videos)
- `skip` (default; today's behavior): item fails with reason "destination exists", logged, not overwritten.
- `suffix`: ` (2)`, ` (3)` appended to the file name until free. Never overwrite.
- Subtitles keep their own numeric suffix logic (section 3).
- Missing folders are already created by `execute_file_operation` (`os.makedirs`).

## 3. Feature 2: Subtitle renaming

Pattern: `<Media Name>.<lang>[.<flag>].<ext>` where `<Media Name>` is the destination video's base name.

### New shared module `backend/sub_naming.py` (single source of truth)
- Language table: ISO 639-1 code -> display name, plus aliases (639-2/B/T codes like `eng`, `spa`, `fre`/`fra`, `tgl`/`tag`, English names like `english`). One table, one normalizer to 639-1 (`en`, `tl`, `es`, ...). Extends the current `LANG_NAMES` in `subtitles.py` and the inline list in `parse_subtitle_details`.
- Flags: `forced`; `hi` (also detects `sdh`, `cc`, `hearing impaired`, `hi`).
- Functions (typed): `normalize_lang(token) -> str | None`, `parse_filename(name) -> ParsedSub` (lang, flag(s), numeric suffix, ok), `format_filename_tag(...)`, `display_label(parsed, raw_name) -> str`.
- `backend/organizer.py` and `backend/subtitles.py` import from it; the duplicated tables/regexes are removed (not copied).

### Behavior
- Detect language/flag from the original filename (and its parent folder like `Subs/English/`, as today) before renaming.
- Match to video: parent directory, then `Subs/Subtitles/sub/eng/english` subfolders; for series, per episode (`S01E01` / `1x01` token) — keep existing `find_companion_subtitles` logic.
- Subtitles move together with their video (existing flow) and keep their original extension. Supported: `.srt .ass .sub .vtt` (existing set also has `.idx`; keep as is). Validate extension.
- Duplicates (same lang+flag): numeric suffix, never overwrite: `Movie (2020).en.srt`, `Movie (2020).en.2.srt`, `Movie (2020).en.forced.2.srt`.
- **Unknown language**: the subtitle still moves with its video but **keeps its original filename** (not renamed to the video base name); log `"unknown language"` with the filename. This replaces today's behavior of renaming unknown-language files.
- Existing quirk to fix during the move to the shared module: `parse_subtitle_details` is English-biased (e.g. `is_hi` forces English when no other language word is present). The shared parser must not assume English.

## 4. Feature 3: Player subtitle labels

### Decisions
- Python is the only parser. **The player JS does no filename parsing**; it displays fields served by `get_all_subtitles` (`backend/subtitles.py`), which already feeds the track list.
- `_parse_sub_label` is reimplemented on top of `backend/sub_naming.py`; `LANG_NAMES` duplicate is removed (keep a re-export name if other code imports it; check with grep).
- Each external subtitle item exposes: `label`, `language` (639-1), `forced` (bool), `hi` (bool), plus existing fields.
- Scope: **external subtitles only**. Embedded tracks keep their current `Embedded: ... [SDH]` labels. Online-downloaded subs (`(Online)` label) unchanged.

### Labels (external)
- `en` -> `English`; `en.forced` -> `English (Forced)`; `en.hi` -> `English (HI)`; duplicates -> `English (2)`, `English (Forced) (2)` style from the numeric suffix.
- Legacy / unrenamed files that still contain a recognizable language token get the same clean label.
- Unparseable names: show the raw filename; must never throw.
- Note: the external-sub label uses `(HI)`; the legacy ` [SDH]` suffix remains only on embedded tracks.

### Default track auto-selection (changes `player.js` near lines 6805-6820)
Current: pick the first track matching preferred language, else index 0. New:
- Preferred language still resolved as today (profile `default_sub_lang`, then `playerSettings.subtitles.preferred_language`, `auto` -> `en`; `off` -> no subtitle).
- If the audio language == preferred subtitle language: select the **Forced** track in that language if present, else fall back to the full track.
- If the audio language != preferred: select the **full (non-forced)** track in that language, else fall back to current behavior.
- Audio language must be known when choosing. Today `audioTracks` / `targetAudio` are resolved AFTER the subtitle block (around line 6827-6842), so the selection needs to run after audio is resolved (reorder or re-run selection once audio is known). Existing `selectSub`, loading, switching, error handling are untouched.
- Heads up: for English-audio titles that have both a Forced and a full English track, the default changes from full to Forced. This is intentional per the decision (note it deviates from the raw prompt wording, which was inverted vs. convention).

## 5. Preview, logging, validation

- **Preview/dry-run**: extend the existing preview items with `route_reason`, `origin_countries`, and a `subtitle_plan` list (`source`, `destination`, `parsed lang/flag`, `action`, `skipped_reason`). Surface in the existing organizer preview UI in `static/js/app.js`, and in CLI `--dry-run` output. No writes during preview.
- **Logging**: use the existing `media_organizer` logger. Log every move/rename, every skip with a reason (collision, locked file, unknown language, unknown origin). Execution results also return skip reasons (`failures`); moves/renames keep landing in `data/organizer_history.json` for undo.
- **Validation**: sanitize new path settings (absolute path, `os.path.abspath`, reject `..` traversal), validate `local_region` against `REGIONS`, `collision_policy` against allowed values, subtitle extension against the allowed set. Subtitle destinations must stay inside the video's destination directory.
- **Webhook/watcher**: both go through the same plan/execute functions, so they get the new behavior automatically once the shared roots builder is used.

## 6. Settings UI (`static/js/app.js`)
- Organizer config panel: "Local region" dropdown (options from API; blank = off), local movies/series path inputs (disabled/hidden when no region), collision policy select. Save through the existing `POST /api/admin/organizer/config`.

## 7. Tests (extend `backend/tests/test_organizer.py`, `test_route_organizer.py`, `test_subtitles.py`; add `test_sub_naming.py`)
- Local vs non-local routing; movie vs series; anime never routed to Local.
- Region off (default) = identical destinations to today.
- Missing metadata / no TMDb key / empty countries -> normal route + log.
- Collision policy `skip` and `suffix` for videos; subtitle numeric suffix without overwrite.
- Language/flag parsing: `eng`, `English`, `tgl`, `forced`, `SDH`/`CC`/`HI` -> `hi`; 639-2 normalizes to 639-1.
- Label parsing: `en`, `en.forced`, `en.hi`, numeric suffix, unknown name (raw filename, no crash), legacy names.
- Unknown-language subtitle keeps original name.
- Series per-episode subtitle matching (`S01E01`).
- Config validation (bad region, traversal path, bad policy) via route tests.
- Player default-track logic is JS; verify manually (checklist below) unless a JS test harness already exists.

### Manual player checklist
1. English audio + `en` and `en.forced` present -> Forced selected.
2. Japanese audio + English preferred -> full English selected.
3. Only one subtitle present -> it is selected (existing fallback).
4. Legacy `English.srt`, odd name `random.srt` -> clean label / raw filename, no errors.
5. Profile `default_sub_lang = off` -> no subtitle.

## 8. Assumptions to verify at implementation time
- `requests.json`-matched or parsed-only items have no country data and therefore route normally (accepted).
- `LANG_NAMES` / `_parse_sub_label` are not imported elsewhere besides `subtitles.py` (grep before removing).
- Existing history ops for renamed subtitles remain undoable (they use `type: "subtitle"` operations).
- `static/js/player.js` has a known parse-partial warning around lines 88, 173-182, 239-240; use direct text inspection.

## 9. Out of scope
- Anime Local routing; library re-organization of already-organized files; embedded track relabeling; multi-region selection; language-only local detection.