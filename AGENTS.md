# CapsStream Commit & Release Workflow Rules

## Project Overview

CapsStream is a portable, self-hosted personal media server for movies, TV series, and anime. It scans user-provided media folders, enriches the library with TMDb metadata and artwork, and serves a browser-based streaming experience with playback history, profiles, subtitles, achievements, and statistics. It is intended for personal, non-commercial use with media the user legally owns.

## Tech Stack

- Python 3.12+ application runtime.
- Flask HTTP server with Flask-Limiter request throttling.
- SQLite persistence accessed through the `backend/db/` package.
- FFmpeg/FFprobe for probing, subtitle extraction, transcoding, thumbnails, and hardware acceleration.
- Vue 3-style frontend JavaScript, HTML templates, CSS, and service-worker assets under `static/` and `templates/`.
- External integrations include TMDb, AniSkip, OpenSubtitles, and GitHub APIs.
- Windows-first portable launchers: `start.bat`, `Start CapsStream Silent.vbs`, and `silent_launcher.py`.

## Architecture

- `app.py` is the Flask application entry point: it initializes configuration, secrets, rate limiting, network inspection, database state, and blueprints.
- `backend/` contains domain services: media scanning/probing, matching, subtitles, intro detection, kids filtering, settings, updating, and shared utilities.
- `backend/db/` owns the SQLite schema, migrations, and repositories for media, playback, profiles, playlists, collections, statistics, and achievements.
- `backend/routes/` is the canonical blueprint implementation for admin, library, media, profiles, social, and streaming HTTP APIs. The top-level `routes/` package is retained as a compatibility/delegation surface.
- `static/` and `templates/` provide the single-page browser UI, service worker, styling, icons, sound effects, and HTML shell.
- `data/` holds per-install runtime state, the SQLite database, metadata/artwork, profiles, backups, and generated secrets; it is intentionally ignored by Git.
- Tests live primarily in `backend/tests/` and cover services, migrations, middleware, and route behavior.

## Conventions

- Preserve the existing Python style and small, focused modules; avoid unrelated reformatting.
- Keep user data, API keys, generated metadata, runtime logs, portable runtimes, and local tooling out of commits.
- Prefer the backend package paths in new code; maintain compatibility aliases only where existing imports require them.
- Use the existing database helpers and migration mechanisms rather than changing SQLite tables ad hoc.
- Validate route changes with the corresponding `backend/tests/test_route_*.py` suite and validate migration changes with `backend/tests/test_db_migrations.py`.
- Use the codebase-memory knowledge graph for structural discovery first, then read exact source ranges for implementation details and coverage gaps.

## Key Decisions

- CapsStream remains portable and Windows-first so it can run from removable storage without a complex installation.
- SQLite is the local source of truth for library and playback state; generated artwork and metadata remain filesystem-backed caches.
- Flask blueprints separate HTTP domains while keeping a single local server and browser client.
- A per-install generated secret key is stored in `data/secret_key` so sessions survive restarts without embedding a forgeable key in source.
- FFmpeg is invoked as an external bundled/system dependency to support broad media formats and optional GPU transcoding.
- `codebase-memory-mcp` is configured for Antigravity in `.gemini/config/mcp_config.json`; its persistent graph is stored outside the repository under the user cache.

## Known Pitfalls

- `config.json`, `.env`, and most `data/` contents are local-only; use the example files when documenting setup.
- FFmpeg/FFprobe and Python may be supplied by the portable `winpython/` and `ffmpeg/` folders, but those folders are ignored and may be absent in a clean checkout.
- The compatibility import setup in `app.py` maps `routes` to `backend.routes`; changing import paths can break deferred or legacy imports.
- Media paths, TMDb credentials, profile data, and generated artwork depend on the local installation and should not be assumed in tests.
- `static/js/player.js` currently has a small CBM parse-partial warning around lines 88, 173-182, and 239-240; use direct text inspection for those ranges.
- The knowledge graph intentionally excludes ignored secrets, runtime data, screenshots, and bundled runtimes. A clean graph coverage result does not prove those files were indexed.
- Never manually edit `VERSION` or `version.json`; release automation owns version bumps.

## Current Focus

- Recent work is centered on database history migration behavior, especially grouping duplicate movie-quality records, with the focused migration test passing.
- Modified files currently include database statistics/migration logic, admin and middleware routes, related tests, `app.py`, and frontend application JavaScript; inspect the working tree before extending that work.
- The codebase knowledge graph is indexed and ready under project name `C-Users-ryanj-OneDrive-Desktop-CapsStream` with 1,722 nodes and 7,812 edges.
- We are currently remaking the player.

Whenever the user asks to commit, release, or save changes in this project, follow this exact workflow:

1. **Sync With Remote First (Mandatory)**
   - Run `git fetch` and check whether `origin/main` has moved ahead (the other dev PC or CI may have pushed).
   - If it has, commit locally first, then `git rebase origin/main` and resolve any conflicts before pushing.

2. **Scan & Inspect Changes**
   - Run `git status` and `git diff` to thoroughly inspect all modified, staged, and untracked files.
   - Ensure temporary/scratch test files are removed or appropriately handled before committing.

3. **NEVER Update Version Files Manually**
   - Do NOT edit `VERSION` or `version.json`. Versions are managed automatically by `.github/workflows/auto-release.yml`, which runs on every push to `main`.
   - The workflow reads conventional-commit subjects since the last tag, bumps the version, commits `chore(release): ... [skip ci]`, tags it (`vX.Y.Z.W`), which triggers `release.yml` to build and publish the update zip.
   - Bump mapping:
     - `feat:` / `feat(...)` → minor bump
     - `fix:` / `fix(...)` → patch bump
     - breaking changes → major
   - Use these subjects to control the release type.
   - If local `VERSION` / `version.json` ever drift from origin, take origin’s copy (rebase resolves this).

4. **Generate Commit Message (Full Changelog Style)**
   - Formulate a conventional commit subject line (`feat(...)`, `fix(...)`, `refactor(...)`, `chore(...)`, etc.).
   - After the subject line, write a **complete changelog-style body** that fully documents the changes.
   - Structure the body like this:

     ```
     <type>(<scope>): <short summary>

     ## Summary
     <1–3 sentence overview of what this commit does and why>

     ## Added
     - ...

     ## Changed
     - ...

     ## Fixed
     - ...

     ## Removed
     - ...

     ## Performance
     - ...

     ## Security
     - ...

     ## Breaking Changes
     - ...
     ```

   - Only include sections that have actual content (omit empty ones).
   - Write clear, concise bullet points.
   - Focus on user-facing and developer-relevant changes.
   - Summarize related changes instead of listing every single file.
   - Mention important breaking changes explicitly.

5. **Commit the Changes**
   - Stage the relevant files.
   - Commit using the full conventional commit message generated above.

6. **Ask Before Push (Mandatory)**
   - **ALWAYS** ask the user for confirmation before executing `git push`.
   - Only run `git push` once the user explicitly approves.
   - After pushing, report:
     - the commit hash
     - push status
     - the release CI will cut (e.g. “next auto-release: v2.21.6.0”)
```