# CapsStream Commit & Release Workflow Rules

Whenever the user asks to commit, release, or save changes in this project, follow this exact workflow:

1. **Scan & Inspect Changes**:
   - Run `git status` and `git diff` to thoroughly inspect all modified, staged, and untracked files.
   - Ensure temporary/scratch test files are removed or appropriately handled before committing.

2. **Update Project Version**:
   - Determine the appropriate semantic version increment based on the scope of changes (patch/minor/major).
   - Update `VERSION` file with the new version string (e.g., `2.13.0.0`).
   - Update `version.json` with the matching `"version"` and `"download_url"`.

3. **Generate Commit Message**:
   - Formulate a clear, structured conventional commit message (`feat(...)`, `fix(...)`, `refactor(...)`, `chore(...)`).
   - Include a concise title and bullet points summarizing key enhancements, fixes, and affected components.

4. **Stage, Commit & Push**:
   - Stage all relevant files (`git add`).
   - Commit using the generated commit message (`git commit`).
   - Push the committed changes to the remote repository (`git push`).
   - Report the new version number, commit hash, and push confirmation to the user.
