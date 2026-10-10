# Product Requirements Document (PRD): CapsStream Moments

## 1. Executive Summary
CapsStream Moments is an interactive scene bookmarking, note annotation, and seekbar timeline marker system. It empowers users to capture iconic scenes, hilarious lines, memorable quotes, and plot twists while streaming movies, anime, and TV episodes. Bookmarks feature thumbnail previews, custom notes, preset category chips, and seeking controls integrated directly into the video player, media detail pages, and profile views.

## 2. Core User Stories & Workflows
- **Instant In-Player Capture**:
  - Pressing keyboard shortcut `B` or tapping the Bookmark icon in the player HUD immediately records the current playback timestamp (`01:24:18`).
  - Playback continues uninterrupted while a subtle 3-second glassmorphic action toast appears with options to dismiss or tap "Add Note".
- **Category Tagging & Note Annotation**:
  - Users can select quick category tags:
    - 💥 Action / Sakuga (`#e50914`)
    - 😂 Funny (`#f59e0b`)
    - 💬 Quote (`#10b981`)
    - ⚡ Plot Twist (`#8b5cf6`)
    - 🎵 Music / OST (`#06b6d4`)
  - Free-form text note input for custom descriptions.
- **Glowing Seekbar Pins**:
  - Interactive diamond/jewel glowing pins render directly on the player timeline scrubber bar at the exact bookmark percentage.
  - Hovering a pin displays a tooltip card with the captured frame thumbnail, note, timestamp, and author tag.
  - Clicking the pin seeks instantly to the exact timestamp.
- **In-Player Moments Drawer**:
  - A slide-out panel accessible from the player settings/HUD displaying all saved moments for the active video in chronological order.
  - Provides 1-click jump to timestamp, inline note editing, and deletion with confirmation toast.
- **Profile Privacy & Family Sharing**:
  - Moments are tied to the active user profile by default.
  - Standard/Adult profiles can toggle an optional "Share with Family" switch to surface specific scene pins for other household members.
- **Cross-App Surfaces**:
  - **Media Detail Page**: A dedicated "Moments" tab alongside Cast and Episodes showing cards with timestamps, thumbnails, and quick play buttons.
  - **Profile Page**: A "Saved Moments" gallery tab alongside Favorites and Watch History allowing users to browse and replay their personal moments collection across the entire library.

## 3. Non-Functional Requirements & Performance
- **Zero Playback Disruption**: Instant canvas snapshot (`<canvas>.drawImage(video, ...)`) captures the frame in <5ms without stalling the media pipeline.
- **Transcode Fallback**: If browser Canvas is tainted due to CORS/HLS streaming, on-demand server thumbnail generation via FFmpeg provides a reliable fallback.
- **Zero Foreign Key Violations**: Cascading SQLite deletes when media or profiles are removed.
- **Responsive Layout**: Designed for mobile touch screens (<640px), tablets (768px), desktop displays (1024px+), and TV Leanback remote navigation.

---

# Product Requirements Document (PRD): Plex-Style Theme Audio Previews

## 1. Executive Summary
Plex-Style Theme Audio Previews bring ambient audio immersion to CapsStream. When browsing a TV show, anime, or movie detail page, iconic opening theme songs play softly in the background with ambient ducking, smooth volume fade-in, and interactive glassmorphic soundwave controls.

## 2. Audio Source Resolution Hierarchy
1. **Local Media Asset Standard (Plex Compatibility)**: Detects `theme.mp3`, `theme.ogg`, `theme.wav`, `theme.m4a`, or `theme.flac` located in the movie directory or show root folder (e.g. `<show_dir>/theme.mp3`).
2. **Server Metadata Cache**: Checks `data/metadata/theme_music/{key}.{ext}` for previously fetched audio.
3. **AnimeThemes.moe Auto-Fetch**: For anime series, automatically looks up the opening theme (OP1) audio track via AnimeThemes.moe API, streams it, and caches it locally.

## 3. Playback & UI Behavior
- **Ambient Default Volume**: 15% volume with smooth 1.5-second fade-in to prevent sudden jarring audio.
- **Seamless Looping**: Seamless loop while user browses episodes, cast, and franchise details.
- **Auto-Ducking & Pause**: Instantly pauses audio when trailer video or media playback starts; resumes smoothly on modal close.
- **Floating Soundwave Pill**: Glassmorphic pill in hero banner displaying animated 4-bar equalizer, mute indicator, and click-to-mute toggle.
- **Global & Local Preferences**: Global toggle in Settings -> Playback Defaults; persistent mute state remembered in browser `localStorage`.

