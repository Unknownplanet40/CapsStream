# CapsStream Commit & Release Workflow Rules

Whenever the user asks to commit, release, or save changes in this project, follow this exact workflow:

1. **Scan & Inspect Changes**:
   - Run `git status` and `git diff` to thoroughly inspect all modified, staged, and untracked files.
   - Ensure temporary/scratch test files are removed or appropriately handled before committing.

2. **Sync With Remote First (Mandatory)**:
   - Run `git fetch` and check whether `origin/main` has moved ahead (the other dev PC or CI may have pushed).
   - If it has, commit locally first, then `git rebase origin/main` and resolve any conflicts before pushing.

3. **NEVER Update Version Files Manually**:
   - Do NOT edit `VERSION` or `version.json`. Versions are managed automatically by
     `.github/workflows/auto-release.yml`, which runs on every push to `main`.
   - The workflow reads conventional-commit subjects since the last tag, bumps the version,
     commits `chore(release): ... [skip ci]`, tags it (`vX.Y.Z.W`), which triggers
     `release.yml` to build and publish the update zip.
   - Bump mapping: `feat:`/`feat(...)` → minor bump; `fix:`/`fix(...)` → patch bump;
     breaking changes → major. Use these subjects to control the release type.
   - If local VERSION/version.json ever drift from origin, take origin's copy (rebase resolves).

4. **Generate Commit Message**:
   - Formulate a clear, structured conventional commit message (`feat(...)`, `fix(...)`, `refactor(...)`, `chore(...)`).
   - Include a concise title and bullet points summarizing key enhancements, fixes, and affected components.

5. **Stage & Commit**:
   - Stage all relevant files (`git add`).
   - Commit using the generated commit message (`git commit`).

6. **Ask Before Push (Mandatory)**:
   - **ALWAYS** ask the user for confirmation before executing `git push`.
   - Only run `git push` once the user explicitly approves.
   - Report the commit hash, push status, and the release CI will cut (e.g., "next auto-release: v2.21.6.0").
