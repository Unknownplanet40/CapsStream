# CapsStream

**CapsStream** is a self-hosted, Netflix-style media server for your personal
movie, series, and anime collection. Point it at your own folders, and it
scans them, matches your files against TMDb (with TheTVDB/OMDb as optional
fallbacks), downloads artwork and metadata, and serves everything through a
polished web interface with a custom HTML5 player.

> ⚠️ CapsStream is for **your own media files only**. No content is bundled
> or provided — you supply the sources.

---

## Features

- Automatic library scanning & TMDb metadata matching (posters, backdrops, cast, ratings)
- Multi-episode series & anime support with per-episode manual skip markers (Recap / Intro / Outro / Preview) and optional AniSkip auto-detection
- Custom player with audio-track switching, subtitles (external + embedded), quality switching, resume, auto-advance
- Hardware-accelerated compatibility playback (Intel QSV / NVIDIA NVENC) for demanding codecs like 4K HEVC
- Multi-profile support with kids mode & PIN locks
- Watch progress, continue-watching, favorites, collections, and stats

---

## Requirements

| Requirement | Notes |
|---|---|
| **Windows** (recommended) | Developed and tested on Windows 10/11 |
| **Python 3.12+** | Any CPython build works (a portable WinPython also works — see below) |
| **FFmpeg + FFprobe** | Required for streaming, probing, subtitles, and transcoding |
| **TMDb API key** (free) | Required for metadata — [get one here](https://www.themoviedb.org/settings/api) |
| **OMDb API key** (optional, free) | Fallback provider — [get one here](https://www.omdbapi.com/apikey.aspx) |

---

## Installation

### 1. Clone the repository

```bat
git clone https://github.com/<your-user>/CapsStream.git
cd CapsStream
```

### 2. Create your `.env` (API keys)

Copy the example file and fill in your real keys:

```bat
copy .env.example .env
notepad .env
```

```
TMDB_API_KEY=your_real_tmdb_key
OMDB_API_KEY=your_real_omdb_key
```

> `.env` is gitignored — your keys never get committed.

### 3. Install Python dependencies

```bat
pip install -r requirements.txt
```

### 4. Install FFmpeg

Download a static Windows build (e.g. from
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or
[BtbN's builds](https://github.com/BtbN/FFmpeg-Builds/releases)) and either:

- **Recommended:** place `ffmpeg.exe` and `ffprobe.exe` inside a local
  `ffmpeg\bin\` folder (next to `app.py`), **or**
- Add FFmpeg to your system `PATH`.

### 5. Python launcher (optional but recommended)

`start.bat` looks for a portable Python at `winpython\python\python.exe`.
Either:

- Install [WinPython](https://winpython.github.io/) (or copy any portable
  Python) into `winpython\python\`, **or**
- Edit `start.bat` and point `PYTHON` to your installed Python executable.

If you skip this, run the app manually with `python app.py`.

### 6. Configuration

Copy the example config and adjust it:

```bat
copy config.example.json config.json
```

- `config.json` holds **non-secret settings only** (paths, UI preferences).
- API keys live in `.env` (see step 2).
- Set your media paths under `media_paths` — or do it later in the app under
  **Settings → Media Scanner Paths**.

### 7. Run

Double-click **`start.bat`** — or:

```bat
python app.py
```

Then open **http://127.0.0.1:8000** in your browser (Edge recommended for
native 4K HEVC / AC-3 decoding).

---

## Adding your media

1. Open **Settings → Media Scanner Paths**
2. Add the folders that contain your movies, series, or anime
   (e.g. `D:/Entertainment/Movies`)
3. Click **Save Settings**, then trigger a scan from the Home page

CapsStream scans those folders, matches files to TMDb, downloads artwork,
and builds your library. Re-scans only process new or changed files.

---

## Updates

CapsStream ships with a lightweight auto-updater (`update.bat` /
`_update_tmp` working folder). When an update is published, run the updater
and it will pull the latest source while preserving your `.env`,
`config.json`, and `data/` folder. You can also update manually with
`git pull` — your data and secrets are gitignored and will not be touched.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **Port already in use** | Change `port` in `config.json` (e.g. `8001`), or stop the other process using port 8000 |
| **"Python not found" from start.bat** | Install WinPython into `winpython\python\`, or edit the `PYTHON` path inside `start.bat` |
| **Missing FFmpeg errors** | Ensure `ffmpeg.exe` + `ffprobe.exe` exist in `ffmpeg\bin\`, or add FFmpeg to PATH |
| **No metadata / posters** | Check your `TMDB_API_KEY` in `.env` — it must be a valid TMDb key |
| **4K HEVC stutters or crashes** | Enable hardware acceleration in your browser, use Microsoft Edge, or click **"Play converted (1080p)"** in the player's advisory banner |
| **Wrong audio track after switching** | Hard-refresh the page (Ctrl+Shift+R) to load the latest player code |
| **Library empty after scan** | Verify the paths in Settings point to folders that actually contain video files and are mounted/accessible |

---

## Project layout

```
CapsStream/
├── app.py                  # Flask server (API + streaming)
├── backend/                # Scanner, matcher, DB, settings, streamer…
├── static/                 # Frontend (Vue 3 app, CSS, sfx)
├── templates/              # index.html (single-page app shell)
├── data/
│   ├── metadata/           # created at runtime (artwork, subtitles…)
│   └── templates/          # fresh template database
├── config.example.json     # example configuration (no secrets)
├── .env.example            # example secrets file (no values)
├── requirements.txt
├── start.bat               # double-click launcher
└── README.md
```

`data/`, `media/`, `winpython/`, `ffmpeg/`, `config.json`, and `.env` are
**not** committed — they are created/populated on your machine.

---

## License

See the repository license. Use only with media you legally own.
