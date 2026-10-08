# Implementation Plan: First-Run Setup Wizard & System Check

Status: finalized (aligned with CapsStream codebase, no code modified yet).

## 0. Ground Rules & Principles
- Do not break existing behavior for users with already existing profiles or active setups.
- Maintain existing architecture: Flask Python backend, Vue 3 SPA frontend (`static/js/app.js`), SQLite persistence (`backend/db/`).
- Reuse existing components where possible: Driver.js tour (`startOnboardingTour`), profile creation API (`/api/profiles`), path validation (`/api/system/validate-paths`), folder browser dialog (`/api/system/browse-folder`), and library scan trigger (`/api/admin/scan`).
- Adhere to the "ponytail" rule: fewest files possible, clean diffs, no redundant abstractions or new heavy external dependencies.
- Never edit `VERSION` or `version.json` manually (automated CI handles releases).

## 1. What Already Exists vs. What We Are Building

| Component | Current State | Setup Wizard Extension |
|---|---|---|
| **Setup Route** (`#/setup`) | Single profile form (`SetupPage` in `app.js:16911`) used when `profiles.length === 0`. | Expand `SetupPage` into a multi-step wizard (Steps 1–4) with step indicator, back/next controls, and persistent state. |
| **Profile Creation & Auth** | `POST /api/profiles` creates profile with PIN hashing; auto-logins via `/api/profiles/auth`. | Keep existing logic in Step 1; upon creation, auto-advance to Step 2 without navigating away to Home immediately. |
| **System Diagnostics** | Admin-only `/api/system/diagnostics` and `/api/system/info`. | Add public/setup-accessible helper endpoint `GET /api/setup/system-check` for server CPU cores, RAM, free disk space, and FFmpeg capability. |
| **Client Media Capabilities** | None currently for browser capabilities. | Add browser-side checks using `navigator.hardwareConcurrency`, `navigator.deviceMemory`, `navigator.mediaCapabilities.decodingInfo()`, WebGL renderer, and screen resolution. |
| **Media Paths Validation** | `POST /api/system/validate-paths` validates paths and counts video files. Folder picker at `/api/system/browse-folder`. | Reuse these APIs in Step 3 for Movie, TV Series, and Anime folders. |
| **Library Scanner** | Background scanner triggered via `POST /api/admin/scan`, progress reported in `store.scanProgress`. | Step 3 triggers the scan and provides cancel/continue controls and file count summaries. |
| **Onboarding Tour** | Driver.js bundled locally (`startOnboardingTour()` at `app.js:1278`). | Step 4 transitions to Home and triggers `startOnboardingTour(true)` upon completion. Add a "Replay Setup Wizard" button in Settings. |
| **Setup State Persistence** | Derived only by `profiles.length === 0`. | Add `setup_completed: bool` to `config.json` and `sessionStorage.getItem("cs_setup_step")` for resume-after-refresh. |

---

## 2. Step-by-Step Architecture & Design

### Step 1: Create Administrator Profile
- **Fields**: Profile Name (required, sanitized, length 1–30), Avatar icon picker, Accent color picker, Optional 4-digit numeric PIN.
- **Security**: PIN hashed using existing scrypt/PBKDF2 logic in `backend/db/profiles.py`. Never stored plaintext.
- **Behavior**: Calls `POST /api/profiles` (with `is_admin: true`), then `POST /api/profiles/auth` to set up session.
- **Transition**: Instead of routing to `/`, advances active wizard step to Step 2 (`system_check`). Persists step in `sessionStorage.setItem("cs_setup_step", "2")`.

### Step 2: System Requirements Check (Hybrid Model)
- **Checklist UI**:
  - Columns: **Component** | **Your Device** | **Recommended** | **Status** (Pass / Warn / Fail / Unknown).
- **Checks Config Object** (easily editable on frontend):
  - **Server CPU Cores**: Recommended >= 4 cores (Warn if 2, Fail if 1).
  - **Server RAM**: Recommended >= 4 GB (Warn if 2–3 GB, Fail if < 2 GB).
  - **Server Free Disk Space**: Recommended >= 20 GB free space on media drive.
  - **Hardware Video Acceleration**: Checks if FFmpeg has NVENC, QSV, or VAAPI hardware encoders available.
  - **Client Browser / Engine**: Modern Chromium, Firefox, or Safari version check.
  - **Client Display Resolution**: Recommended >= 1080p (Warn if < 720p).
  - **Client Codec Decode Support**: Probed via `navigator.mediaCapabilities.decodingInfo()` for:
    - H.264 (AVC) Baseline / High
    - H.265 (HEVC) Main 10
    - VP9
    - AV1
    - AAC Audio
- **Non-blocking Policy**: Fails and warnings display informative badges and helpful hints (e.g. "Software transcoding will be used for AV1"), with an enabled "Continue" button and a "Re-check" button.

### Step 3: Media Setup + Live Scan
- **Inputs**: Folder selectors for **Movies**, **TV Series**, and **Anime** (categorized, matching CapsStream's schema).
- **Folder Browser**: If accessed on localhost/host PC, allows clicking "Browse..." to launch the native folder selection dialog (`/api/system/browse-folder`). Also permits typing absolute paths manually.
- **Validation**:
  - Rejects empty non-existent paths, file paths (must be directory), duplicates, and path traversal (`..`).
  - Calls `/api/system/validate-paths` to report video file count per folder.
- **Execution & Scan**:
  - Saves paths to `media_paths` in `config.json`.
  - Initiates scan via `/api/admin/scan`.
  - Displays live animated scanning state (`store.scanProgress` / files discovered).
  - Provides a "Skip Scan for Now" / "Cancel" option.
  - On scan completion: displays a summary card (e.g. "Found 42 movies, 12 series").
  - Zero results: shows an amber notice letting user re-check the path, retry, or proceed anyway.

### Step 4: Home Transition & Guided Tour
- **Completion**: Marks `setup_completed = true` in server `config.json` and marks profile flag.
- **Redirection**: Directs user to `/` (Home).
- **Tour**: Calls `startOnboardingTour(true)` automatically via Driver.js.
  - Spotlight covers: `#nav-logo`, `.nav-links`, `#nav-search`, `#nav-profile`, and `#nav-scan`.
  - Next, Back, Skip, Esc to dismiss.
  - Persists tour completion in profile database and localStorage so it never auto-triggers again.
- **Settings Replay**: Adds "Replay Setup Wizard" and "Replay Tour" under Settings -> Interactive Onboarding & Guide.

---

## 3. Route Guarding & State Persistence

- **Route Guard (`router.beforeEach`)**:
  - If `profiles.length === 0`: redirect to `#/setup` automatically.
  - If `profiles.length > 0` and `config.setup_completed` is true: block access to `#/setup` and redirect to `/`, **unless** the user explicitly clicks "Run Setup Wizard" from Settings.
- **Step Resumption**:
  - Active step (`currentStep: 1 | 2 | 3 | 4`) saved in `sessionStorage.getItem("cs_setup_step")`.
  - If a user refreshes their browser during Step 2 or Step 3, the wizard restores at that exact step with existing entered data preserved.
  - "Back" button allows navigating back to review or edit previous steps without resetting profile or selections.

---

## 4. API Endpoints Plan

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/setup/status` | GET | Public | Returns `{ setup_completed: bool, has_profiles: bool }`. |
| `/api/setup/system-check` | GET | Session / Admin / Setup-token | Returns server hardware info (CPU cores, RAM total/available, disk space, FFmpeg encoders). |
| `/api/setup/complete` | POST | Active Profile Session | Sets `setup_completed = true` in `config.json`. |
| `/api/system/validate-paths` | POST | Active Profile Session | Existing endpoint to validate folder accessibility and count video files. |
| `/api/system/browse-folder` | POST | Active Profile Session (Localhost) | Existing endpoint to open native folder dialog. |

---

## 5. Accessibility & UI Polish

- Step indicator header: e.g. `Step 1 of 4: Administrator Profile`, with clickable past steps for easy back-navigation.
- Proper ARIA attributes: `aria-current="step"`, `role="status"` on system check results, accessible keyboard focus on form elements.
- Motion: Respects `prefers-reduced-motion` for step transitions and scanner spinner animations.
- Theming: Uses CapsStream's standard glassmorphic dark design tokens (`--bg-primary`, `--accent`, `--border-subtle`, `--radius-lg`).

---

## 6. Testing Strategy

1. **Backend Unit / Integration Tests (`backend/tests/test_setup_wizard.py`)**:
   - Verify `/api/setup/status` returns correct status before and after setup.
   - Verify `/api/setup/system-check` returns valid hardware info structure.
   - Verify path validation rejects invalid/traversal paths and accepts valid directories.
   - Verify `/api/setup/complete` sets `setup_completed: true` in config.
2. **Frontend End-to-End / Flow Verification**:
   - Fresh instance with no profiles redirects to `#/setup`.
   - Creating profile auto-advances to Step 2.
   - System Check performs both server and browser capability queries and renders Pass/Warn/Fail badges.
   - Media Setup correctly validates folders and triggers scan.
   - Step 4 routes to Home and launches Driver.js tour.
   - Browser refresh mid-flow resumes at current step.
   - Subsequent visits to `#/setup` redirect back to Home when setup is completed.

---

## 7. Out of Scope
- Rewriting Driver.js with a separate tour library (Driver.js works reliably and is already bundled).
- Hard-blocking server startup if hardware specs are low (all checks must remain advisory).
- Automatic cloud sync or external downloader setup in the initial wizard.