# CapsStream Update System

CapsStream updates itself from **GitHub Releases**. Update packages contain
**code only** — your configuration, secrets, database, and media are never
touched.

---

## For users

### Checking for updates

- Open **Settings → Updates** and press **Check for Updates**, or
- CapsStream quietly checks once after you log in and shows a banner when a
  new version is available.

### Installing

1. Press **Install Update** in Settings → Updates.
2. Depending on what changed:

   | Changed files | Result |
   |---|---|
   | Only the web interface (`static/`, `templates/`) | The page hard-reloads automatically — done. |
   | Server code (`app.py`, `backend/`, …) | You'll see *"Update installed. Please close CapsStream and run start.bat again."* |

3. Manual fallback: double-click **`update.bat`**.

### What is never overwritten

`config.json`, `.env`, everything in `data/`, your media folders,
`winpython/`, and `ffmpeg/`.

---

## For developers (publishing a release)

1. Set your repository in **`backend/updater.py` → `GITHUB_REPO`**
   (`"USERNAME/CapsStream"`).
2. Make sure the GitHub workflow files (`.github/workflows/`) are pushed and
   Actions are enabled for the repo.
3. Bump and publish in one step:

   ```bash
   ./scripts/release.sh 2.0.1
   ```

   This writes `VERSION`, commits, tags `v2.0.1`, and pushes. The tag
   triggers the **Release** workflow which:

   - Verifies `VERSION` matches the tag,
   - Builds `CapsStream-update-2.0.1.zip` (code only: `app.py`, `backend/`,
     `static/`, `templates/`, `requirements.txt`, `start.bat`, `update.bat`,
     `VERSION`),
   - Generates a changelog from commits,
   - Publishes the GitHub Release with the zip attached,
   - Updates `version.json` on `main` so clients see the new version.

### Version scheme

| Level | Meaning |
|---|---|
| Major | Breaking changes / major rewrites |
| Minor | New features or significant enhancements |
| Build | Recompilation of same/updated source |
| Revision | Hotfixes, patches, interchangeable adjustments |

### Client resolution order

1. `GET https://api.github.com/repos/<repo>/releases/latest` — gives the tag,
   changelog body, and zip asset URL.
2. Fallback: raw `version.json` from the default branch.
