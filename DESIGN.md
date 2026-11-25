# CapsStream Design Direction

> Reference document for CapsStream UI work. Read before editing `templates/`, `static/css/`, or `static/ui2/`.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 1

## Identity & Mood

- **Product:** Portable, self-hosted personal cinema server for movies, TV series, and anime.
- **Personality:** Focused darkroom theater. High-contrast poster art carries the visual weight; chrome stays quiet.
- **Identity Motif:** Bracketed `[capsStream]` wordmark (Adult Swim-inspired), paired with crisp 1px hairline borders and crimson focus/action cues.
- **Theme Rationale (R-21):** Dark canvas (`#050508` / `#07070A`) is intentional for media viewing and poster legibility, not a generic "tech" default.

## Color Palette (R-29)

- **Canvas (Core 1):** `#050508` (legacy) / `#07070A` (UI 2.0)
- **Elevated Surface (Core 2):** `#0D0D14` / `#12121C`
- **Text (Core 3):** `#FFFFFF` primary, `#9494A8` secondary, `#8A8AA6` muted (`>= 5.55:1` WCAG AA on dark surfaces)
- **Deliberate Accent:** `#E50914` (Cinema Crimson) reserved for primary Play CTAs, active playback progress, and `:focus-visible` rings.
- **Active Pill Contrast:** `#F5F2EA` surface with `#0B0B0E` text for active navigation pills.

## Typography (R-06)

- **Display:** `Cabinet Grotesk` for hero titles.
- **UI Sans:** `Geist`, `Plus Jakarta Sans` for clean legibility across desktop and 10-foot TV distances.
- **Mono:** `JetBrains Mono`, `Geist Mono` for technical metadata (resolution, codec, keyboard shortcuts).
- **Self-Hosting (R-40):** All fonts are bundled locally in `/static/fonts/fonts.css`. Never add external font `@import` URLs.

## Layout, Motion & Restraint

- **Focal Point:** One hero showcase or active media detail per screen; supporting rows defer to it.
- **Glassmorphism Cap (R-10):** Reserve `backdrop-filter` for floating navigation pills and modal backdrops only (1-2 active layers).
- **Motion (R-19, MOTION 1):** Fast `150ms-250ms` hover/focus transitions and session-once startup splash. No endless pulsing loops. Respect `prefers-reduced-motion: reduce`.
- **Accessibility & Copy (R-02, R-25, R-32, R-39):** Zero em dashes (`—`) in UI copy; maintain >= 4.5:1 text contrast; preserve `:focus-visible` outlines and pinch-zoom.
