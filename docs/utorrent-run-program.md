# µTorrent – Run Program

**Source:** Preferences → Advanced → Run Program  
**Manual path:** µTorrent User Manual → Appendix A: The µTorrent Interface → Preferences → Advanced

---

## Overview

The **Run Program** dialog lets you specify a program or batch file that µTorrent will execute:

- when any torrent finishes downloading, **or**
- on any state change while downloading or seeding.

### Example

```cmd
"d:\program files\utorrent\run-program.cmd" "%D"
```

This runs `run-program.cmd` and passes the download directory path as a parameter.

---

## Fields

| Field | Description |
|-------|-------------|
| **Run this program when a torrent finishes** | Command line executed when a download completes. |
| **Run this program when a torrent changes state** | Command line executed on any torrent state change. |

---

## Available Parameters

| Parameter | Description |
|-----------|-------------|
| `%F` | Name of the downloaded file (single-file torrents only) |
| `%D` | Directory where the files are saved |
| `%N` | Title of the torrent |
| `%P` | Previous state of the torrent |
| `%L` | Label |
| `%T` | Tracker |
| `%M` | Status message string (same as the Status column) |
| `%I` | Hex-encoded info-hash |
| `%S` | Current state of the torrent |
| `%K` | Kind of torrent (`single` or `multi`) |

---

## Torrent States (`%S` / `%P`)

| State | Code |
|-------|------|
| Error | 1 |
| Checked | 2 |
| Paused | 3 |
| Super seeding | 4 |
| Seeding | 5 |
| Downloading | 6 |
| Super seed [F] | 7 |
| Seeding [F] | 8 |
| Downloading [F] | 9 |
| Queued seed | 10 |
| Finished | 11 |
| Queued | 12 |
| Stopped | 13 |
| Preallocating | 17 |
| Downloading Metadata | 18 |
| Connecting to Peers | 19 |
| Moving | 20 |
| Flushing | 21 |
| Need DHT | 22 |
| Finding Peers | 23 |
| Resolving | 24 |
| Writing | 25 |

> **Note:** States marked `[F]` indicate a forced state.

---

## Usage Notes

- You can use any combination of the parameters above in either command field.
- Paths containing spaces should be quoted (as shown in the example).
- The full list of events and parameters is also shown in the Run Program dialog itself.

---

## CapsStream Requests Automation Setup

CapsStream includes a standalone automation hook (`scripts/utorrent_request_updater.bat` and `backend/utorrent_hook.py`) that matches downloaded torrents with requested media items and automatically transitions their status in `data/requests.json` and Supabase cloud sync.

### How it works:
- **Standalone execution**: Operates directly on `data/requests.json` and Supabase even if the CapsStream web server is **not open or running**.
- **State transitions**:
  - Torrent starts downloading (State 6, 9) $\rightarrow$ marks active request as `in_progress`.
  - Torrent finishes or seeds (State 11, 5, 8, etc.) $\rightarrow$ marks active request as `completed`, attaches completion timestamp.
  - Automatically queries the local CapsStream database (`data/capsstream.db`) and links the media ID if the file is in your library.
  - If the CapsStream server is currently running, it triggers a live library sync exclusively on port **8700** (`http://127.0.0.1:8700/api/requests/sync-library`) without needing a server restart.
- **Native Windows Notifications**: Automatically pops up a native Windows desktop banner when downloads start (`In Progress`) and complete (`Added to Library`).
- **Silent & Windowless**: Runs completely in the background without any command prompt or terminal window popping up.
- **Log file**: Detailed logs are written to `logs/utorrent_updater.log`.

### µTorrent Configuration:

1. Open µTorrent and press **Ctrl+P** (or click **Options** $\rightarrow$ **Preferences**).
2. On the left sidebar, click **Advanced** $\rightarrow$ **Run Program**.

#### Scenario 1: You ONLY want to run when a download finishes (Simplest)
Leave *"Run this program when a torrent changes state"* **BLANK**, and in **"Run this program when a torrent finishes"**, paste:

**Option A (Direct Pythonw — 100% Invisible, Fastest):**
```cmd
"C:\Users\ryanj\OneDrive\Desktop\CapsStream\winpython\python\pythonw.exe" "C:\Users\ryanj\OneDrive\Desktop\CapsStream\backend\utorrent_hook.py" --finish "%N" "%S" "%D" "%F"
```

**Option B (VBScript Launcher — 100% Invisible):**
```cmd
wscript.exe "C:\Users\ryanj\OneDrive\Desktop\CapsStream\scripts\utorrent_finish.vbs" "%N" "%S" "%D" "%F"
```

---

#### Scenario 2: You want to use "Run this program when a torrent changes state"
To get 100% accurate state tracking (auto-transitions to `in_progress` when downloading, and auto-transitions to `completed` when seeding/finished), pass the status message `%M` as well:

**In "Run this program when a torrent changes state":**

**Option A (Direct Pythonw — Recommended):**
```cmd
"C:\Users\ryanj\OneDrive\Desktop\CapsStream\winpython\python\pythonw.exe" "C:\Users\ryanj\OneDrive\Desktop\CapsStream\backend\utorrent_hook.py" "%N" "%S" "%D" "%F" "%M" "%P"
```

**Option B (VBScript Launcher):**
```cmd
wscript.exe "C:\Users\ryanj\OneDrive\Desktop\CapsStream\scripts\utorrent_state_change.vbs" "%N" "%S" "%D" "%F" "%M" "%P"
```

*(Note: You can leave "Run this program when a torrent finishes" BLANK, or configure both. The built-in cross-process file lock and status resolver will prevent any race conditions or duplicate notifications).*

3. Click **Apply** and **OK**.

### Testing the Automation Manually:

You can test matching without waiting for a download using dry-run mode:

```powershell
.\winpython\python\python.exe backend\utorrent_hook.py --dry-run --name "Runner.2026.1080p.WEBRip" --finish
```