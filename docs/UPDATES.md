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

### Automatic (recommended) — conventional commits

Every push to `main` is analyzed by the **Semantic Version Auto Release**
workflow. It reads commit subjects since the last tag and bumps the version
automatically:

| Commit message | Bump |
|---|---|
| `feat: …` / `feat(scope): …` / `feature:` | **Minor** |
| `fix:` / `docs:` / `style:` / `refactor:` / `perf:` / `test:` / `chore:` | **Patch** |
| `BREAKING CHANGE` in body, `!:` suffix, or `+semver: major` | **Major** |
| anything else (no recognized prefix) | no release |

CapsStream's 4-part scheme maps as **Major.Minor.Build.Revision** — a minor
bump resets Build/Revision, a patch bump increments Build only.

The workflow then updates `VERSION` + `version.json`, commits as
`github-actions[bot]` with `[skip ci]`, tags `vX.Y.Z.W`, and pushes — which
chains into the **Release** workflow that builds the update zip and
publishes the GitHub Release with a commit-based changelog.

Just push with proper prefixes:

```bash
git commit -m "feat: add downloads page" && git push
```

That's it. ~1 minute later the release is live and clients see the update.

### Manual

Set your repository in **`backend/updater.py` → `GITHUB_REPO`**
(`"Unknownplanet40/CapsStream"`), then either run the Auto Release flow by
pushing a conventional commit, or tag manually:

```bash
./scripts/release.sh 2.0.1
```

### Version scheme

| Level | Meaning |
|---|---|
| Major | Breaking changes / major rewrites |
| Minor | New features or significant enhancements |
| Build | Updated source (incremented by `fix:`/`chore:`/etc.) |
| Revision | Hotfixes, patches, interchangeable adjustments |

### Client resolution order

1. `GET https://api.github.com/repos/<repo>/releases/latest` — gives the tag,
   changelog body, and zip asset URL.
2. Fallback: raw `version.json` from the default branch (the download URL is
   also constructed deterministically from the tag if missing).
