# Handoff

## 1. Goal
Audit CapsStream UI with `antislop`, establish design direction (`DESIGN.md`), add low-end performance optimizations (Low-Power Mode, gzip compression, Phosphor icon trim, non-blocking scripts), and provide a lightweight Rust WebView2 desktop viewer built via GitHub Actions CI.

## 2. Current State
- **Branch:** `main`
- **Pushed Commit Hash:** `7bb7655` (`fix(launcher): recognize capsstream-viewer to prevent duplicate windows on restart`)
- **Push Status:** Pushed to `origin/main` (`55bba21..7bb7655`).
- **Release CI:** `Semantic Version Auto Release` (`v2.91.4.0` patch bump) triggered on push to `main`.
- **Server Running Status:** Server idle / ready.

## 3. Active Files
- `DESIGN.md` (brand identity, palette, typography, and `ENERGY 2 / RHYTHM 2 / MOTION 1` dials)
- `app.py` (stdlib `gzip` `@app.after_request` response compression)
- `templates/index.html` (zoom-enabled viewport, `defer` on `driver.min.js`, `cs_low_power` early class, `__CAPS_VER__`)
- `static/css/main.css` (local fonts only, `#8a8aa6` muted text, global `:focus-visible`, `html.cs-low-power` rules)
- `static/ui2/ui2.css`, `static/ui2/ui2.js`, `static/ui2/ui2-shared.js`, `static/ui2/ui2-settings.js`, `static/ui2/ui2-details.js`, `static/ui2/ui2-views.js`
- `static/vendor/phosphor/icons.css` (trimmed unused `thin`, `light`, `duotone` weights)
- `silent_launcher.py` (prefers `capsstream-viewer.exe`, falls back to Edge/Chrome)
- `clients/desktop-rust/Cargo.toml`, `clients/desktop-rust/src/main.rs`
- `.github/workflows/build-desktop-rust.yml`

## 4. Changes Made
- Audited UI against `antislop` rules and fixed `R-02` (em dashes), `R-25` (WCAG AA contrast), `R-26` (removed placeholder `API Docs`/`Discord` buttons), `R-32` (`:focus-visible` outlines), `R-37` (`DESIGN.md`), `R-39` (removed `user-scalable=no`, added `alt`), and `R-40` (removed external Google Fonts `@import`, added `defer`, added image dimensions).
- Added stdlib `gzip` compression in `app.py` (measured: `main.css` 923 KB -> 145 KB, `app.js` 1.44 MB -> 295 KB).
- Trimmed unused Phosphor weights in `static/vendor/phosphor/icons.css` and replaced `Date.now()` cache-busting in `static/ui2/ui2.js`.
- Added Low-Power Mode (`cs_low_power`) toggle in `ui2-settings.js` and `html.cs-low-power` CSS overrides in `static/css/main.css`.
- Scaffolded `clients/desktop-rust/` (`tao` + `wry`), wired `silent_launcher.py`, and added `.github/workflows/build-desktop-rust.yml`.

## 5. Failed Attempts
- Local `cargo build --release` failed on this machine because `msvc` lacked Windows SDK (`kernel32.lib`), `gnu` lacked `libgcc.a`/`as.exe`, and `rustup toolchain install stable-x86_64-pc-windows-gnullvm` stalled downloading components. Resolved by adding `.github/workflows/build-desktop-rust.yml` (`windows-latest` MSVC).

## 6. Specific Next Steps
- Confirm `Build Desktop Rust Viewer` and `Semantic Version Auto Release` (`v2.90.0.0`) CI runs succeed.
- Download `CapsStream-Desktop-Viewer-Windows` (`capsstream-viewer.exe`) from GitHub Actions artifact if testing the Rust viewer locally.
- Run a live browser click-through (`R-35`) across `Home`, `Anime`, `Discover`, `Library`, and `Settings` (including `Low-Power Mode` toggle).
