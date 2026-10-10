# Handoff

## 1. Goal
Scaffold and validate a pure WinUI 3 (Windows App SDK) C# desktop prototype under `clients/windows/` with a 1:1 CapsStream home page layout (cinematic hero billboard and horizontal scrolling rails) and hardware-accelerated playback, while pausing active desktop client development for now.

## 2. Current State
- **Branch:** `main`
- **Commit:** `91c78bd` pushed successfully to `origin/main` (`5c2ed5d..91c78bd`).
- **Release CI:** GitHub Actions automated release pipeline triggered on push to `main` (will bump version and publish release assets).
- **Tests:** 439 backend unit and integration tests passing (`OK`), .NET solution compiles with 0 errors and 0 warnings.
- **Working Tree:** `PROJECT-LOG.md` and `handoff.md` updated for session transition.

## 3. Active Files
- `clients/windows/CapsStream.sln`: Visual Studio 2022 solution linking Core, Data, and WinUI projects.
- `clients/windows/src/CapsStream.Core/`: Domain models (`MediaItem.cs`, `MediaType.cs`, `Profile.cs`, `WatchProgress.cs`, `WatchHistoryItem.cs`).
- `clients/windows/src/CapsStream.Data/`: SQLite persistence (`CapsDb.cs`, `MediaRepository.cs`, `ProfileRepository.cs`).
- `clients/windows/src/CapsStream.WinUI/`: WinUI 3 presentation (`MainWindow.xaml`, `Pages/HomePage.xaml`, `Pages/PlayerPage.xaml`, `Pages/MoviesPage.xaml`, `Pages/SeriesPage.xaml`, `Pages/AnimePage.xaml`, `Pages/SettingsPage.xaml`, `Pages/AboutPage.xaml`).
- `PROJECT-LOG.md`: Permanent append-only project log.

## 4. Changes Made
- Scaffolded `.NET 8` WinUI 3 desktop client under `clients/windows/` with clean architecture.
- Added dynamic directory discovery in `CapsDb.cs` to resolve `data/capsstream.db` and artwork across unpackaged runtime directories.
- Enabled Dapper underscore column mapping (`DefaultTypeMap.MatchNamesWithUnderscores = true`) for SQLite schema parity.
- Designed 1:1 CapsStream Home page in XAML with a 500px Cinematic Hero Billboard (backdrop gradients, metadata chips, action buttons) and horizontal scrolling rails (Continue Watching, Recently Added, Top Rated Movies, Popular TV Shows, Anime Collection).
- Implemented `PlayerPage.xaml` using `MediaPlayerElement` with path normalization, lifecycle mounting fixes, and visual diagnostic notifications.
- Created `clients/windows/.gitignore` to prevent any .NET build binaries or user cache files from leaking into Git.
- Updated commit message to explicitly indicate the Windows desktop prototype is on hold/paused.
- Committed `91c78bd` and pushed to `origin/main`.

## 5. Failed Attempts
- Direct unpackaged launch initially exited silently due to a machine-level `$env:DOTNET_ROOT` pointing to `C:\Users\ryanj\.dotnet` (.NET 9 only) instead of `C:\Program Files\dotnet` (.NET 8). Solved by enabling `<WindowsAppSDKSelfContained>true</WindowsAppSDKSelfContained>` and `<RollForward>Major</RollForward>`.
- `Player.Source` set inside `OnNavigatedTo` failed silently before visual DirectX swapchain mounting. Solved by moving media player initialization into the `Loaded` page event.

## 6. Specific Next Steps
1. Verify CI release workflow publishes version bump and Android TV companion APK.
2. Resume primary focus on CapsStream Python server and web/Android TV clients.
3. If Windows desktop client work is ever resumed, consider integrating `LibVLCSharp.WinUI` to decode non-standard MKV/HEVC/DTS files without relying on Windows Media Foundation codec packs.
