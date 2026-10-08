# Global Rules

## 1. Response Prefix
Start every reply with the exact word `Capsss` followed by a single space. Never omit it, never alter it, never put anything before it.

This is a best-effort check — the model cannot detect its own omissions with certainty. If you (the user) notice the prefix missing, treat it as a signal to start a new session.

## 2. Commit & Push Workflow

Whenever the user asks to commit, release, or save changes in this project, follow this exact workflow, in order.

> `CHANGELOG.md` is generated entirely by `release.yml` from commit history on push to `main` — this workflow never edits `CHANGELOG.md` directly. Step 4's changelog-style commit body exists only for readable git history; it's not written to any file by hand.

### Step 1 — Check Remote Status
- Run `git fetch` and check whether `origin/main` has moved ahead (the other dev PC or CI may have pushed).
- Just note the result for now — the actual sync (rebase) happens in Step 5, after the local commit exists.

### Step 2 — Scan & Inspect Changes
- Run `git status` and `git diff` to thoroughly inspect all modified, staged, and untracked files.
- Ensure temporary/scratch test files are removed or appropriately handled before committing.

### Step 3 — Check for Automated Versioning (Project-Dependent)
- Look for an existing CI release workflow in the project (e.g. `.github/workflows/*release*.yml` or similar).
- **If one exists:** do NOT manually edit version files (`VERSION`, `version.json`, `package.json`'s version field, etc.). Assume the workflow reads conventional-commit subjects since the last tag and bumps the version automatically:
  - `feat:` / `feat(...)` → minor bump
  - `fix:` / `fix(...)` → patch bump
  - breaking changes → major bump
  - If local version files ever drift from origin, take origin's copy (the Step 5 rebase resolves this).
- **If no such workflow exists:** ask the user how they want versioning handled before proceeding — don't assume a scheme or bump a version file unprompted.

### Step 4 — Generate Commit Message (Full Changelog Style)
- Formulate a conventional commit subject line (`feat(...)`, `fix(...)`, `refactor(...)`, `chore(...)`, etc.).
- Check whether this commit relates to an open GitHub issue (run `gh issue list` if unsure). If it does, add a reference line directly under the subject:
  - `Closes #N` / `Fixes #N` — if this commit fully resolves the issue (GitHub auto-closes it on push to the default branch).
  - `Refs #N` — if this commit is related but doesn't fully resolve it.
- After the subject line (and issue reference, if any), write a **complete changelog-style body**:

  ```
  <type>(<scope>): <short summary>

  Closes #N  <!-- or "Refs #N" — omit this line entirely if no related issue -->

  ## Summary
  <1–3 sentence overview of what this commit does and why>

  ## Added
  - ...

  ## Changed
  - ...

  ## Fixed
  - ...

  ## Removed
  - ...

  ## Performance
  - ...

  ## Security
  - ...

  ## Breaking Changes
  - ...
  ```

- Only include sections that have actual content (omit empty ones).
- Write clear, concise bullet points. Focus on user-facing and developer-relevant changes.
- Summarize related changes instead of listing every single file.
- Mention breaking changes explicitly.

### Step 5 — Commit the Changes
- Stage the relevant files.
- Commit using the full conventional commit message generated in Step 4.
- **PowerShell escaping**: Do NOT pass complex commit messages via `git commit -m "..."` in PowerShell. Backticks, dollar signs, and other metacharacters will cause parse failures. Instead:
  1. Write the message to a temporary `.commit_msg.txt` file.
  2. Run `git commit -F .commit_msg.txt`.
  3. Delete `.commit_msg.txt` after the commit succeeds.
- If `origin/main` had moved ahead (per Step 1), now run `git rebase origin/main` and resolve any conflicts.

### Step 6 — Ask Before Push (Mandatory)
- **ALWAYS** ask the user for confirmation before executing `git push`.
- Only run `git push` once the user explicitly approves.
- After pushing, report:
  - the commit hash
  - push status
  - what the release CI will do next, if this project has one (e.g. "next auto-release: v2.5.0")

### Step 7 — Run Handoff Mode & Sync Agent Context (`.agents`)
Immediately after a successful push:
1. **Run Handoff Mode (`.agents/rules/handoff-mode.md`)**:
   - Check whether `handoff.md` exists in the project root.
   - Create or update `handoff.md` in place with a fresh snapshot covering all 6 mandatory sections:
     - `## 1. Goal`: What was accomplished and what the next milestone is.
     - `## 2. Current State`: Exact state (branch, commit hash pushed, push status, automated CI release tag/workflow, server running status).
     - `## 3. Active Files`: List central files touched or queued for upcoming tasks.
     - `## 4. Changes Made`: Concrete summary of changes committed and pushed.
     - `## 5. Failed Attempts`: Approaches tried that did not work, errors observed, and why they were abandoned.
     - `## 6. Specific Next Steps`: Ordered, concrete actions for the next agent session.
   - Confirm to the user that `handoff.md` is ready and briefly list the six section headings.
2. **Inspect & Sync `.agents/` Context**:
   - Check [`.agents/rules/`](.agents/rules/) (e.g., [`check-server-running.md`](.agents/rules/check-server-running.md), [`ponytail.md`](.agents/rules/ponytail.md), [`commit-workflow.md`](.agents/rules/commit-workflow.md), [`handoff-mode.md`](.agents/rules/handoff-mode.md), [`project-log.md`](.agents/rules/project-log.md)) and relevant [`.agents/skills/`](.agents/skills/) (such as `decision-log`).
   - Ensure the documented next steps and future implementations strictly follow active rules and leverage available project skills.
   - This prevents hallucination and guarantees any new agent session can resume exactly where we left off.
3. **Append to [`PROJECT-LOG.md`](PROJECT-LOG.md) (Append-Only)**:
   - Append what the user asked for, what was decided and why, and what was shipped using the format defined in [`.agents/skills/decision-log/SKILL.md`](.agents/skills/decision-log/SKILL.md) and [`.agents/rules/project-log.md`](.agents/rules/project-log.md).
   - Never overwrite or delete existing entries so historical memory persists permanently.

## 3. GitHub Issue Creation & Implementation

**Trigger:** When the user's message contains **"create issue"** (case-insensitive), create a GitHub Issue, then immediately implement the requested feature or fix unless clarification is essential.

1. **Inspect templates and determine type**

   * Read the current repository templates before creating the issue:

     * `.github/ISSUE_TEMPLATE/bug_report.yml`
     * `.github/ISSUE_TEMPLATE/feature_request.yml`
   * Use **Bug** for broken, incorrect, failing, or unexpected behavior.
   * Use **Feature** for new functionality or improvements.
   * Follow the current template fields and structure. The repository templates are the source of truth.

2. **Build the issue**

   * Create a short, specific title.
   * Build a clear, self-contained issue from the user's request and relevant surrounding context. Do not copy the conversation verbatim.
   * Include any detail that materially helps someone understand, reproduce, implement, test, or review the issue, such as symptoms, errors, reproduction steps, expected/actual behavior, logs, affected components, environment details, constraints, acceptance criteria, UI/UX requirements, edge cases, dependencies, or behavior that must remain unchanged.
   * **Rule:** If removing a detail would make the issue harder to understand, reproduce, implement, test, or review, include it. Otherwise, leave it out.
   * Do not include irrelevant conversation, personal discussion, speculation, or unrelated information.

3. **Select a label**

   * Run `gh label list` and use the closest existing label.
   * Never assume or create a label unless explicitly requested.
   * If no label fits, create the issue without one.

4. **Create and report**

   * Create the issue using the appropriate repository Issue Form and assign it to `@me`.
   * Do not bypass the Issue Form or duplicate its fields unnecessarily.
   * If `gh` cannot directly populate the form, use a supported interactive/repository-compatible method that preserves the template structure.
   * Report the issue number, title, and URL, then remember the issue number for the current workflow.

5. **Implement and validate**

   * Inspect the relevant code and existing architecture first.
   * Make the smallest clean change that satisfies the issue and follows project conventions.
   * Avoid unrelated refactoring or behavior changes. Do not add mock data, placeholders, or temporary implementations unless requested.
   * Run relevant tests, lint/format checks, type checks, builds, and the application when practical.
   * Verify the requested behavior, inspect the final `git diff`, and remove temporary/debug artifacts.
   * Never claim validation passed unless it was actually run. State what could not be run and why.

6. **Issue, commit, and PR linkage**

   * When committing, follow Section 2 and reference the remembered issue correctly: `Closes #N` or `Fixes #N` if fully resolved; `Refs #N` if only related.
   * If creating a Pull Request, first read `.github/pull_request_template.md` and follow its current structure. Fill it only with actual implementation and validation details, including limitations or known issues when relevant.
   * Do not invent or guess issue numbers, labels, test results, or repository structure.

## 4. Session Start & Context Resumption

Whenever starting a new session or resuming work on CapsStream:
1. **Check [`handoff.md`](handoff.md) & [`PROJECT-LOG.md`](PROJECT-LOG.md)**:
   - Read `handoff.md` to restore verified active context (Goal, Current State, Active Files, Changes Made, Failed Attempts, and Specific Next Steps). Pick up work from the exact stopping point to avoid assumptions or hallucinations.
   - Review `PROJECT-LOG.md` to ground context in the project's permanent historical record of user requests, decisions (with rationale), and shipped features.
2. **Inspect [`.agents/`](.agents/)**: Review active project rules in [`.agents/rules/`](.agents/rules/) (e.g., [`check-server-running.md`](.agents/rules/check-server-running.md), [`ponytail.md`](.agents/rules/ponytail.md), [`project-log.md`](.agents/rules/project-log.md)) and relevant skills in [`.agents/skills/`](.agents/skills/) to ground all development within the repository's established conventions.

## 5. Session End & Historical Logging (`PROJECT-LOG.md`)

Before any session ends or after shipping a requested change:
- **Append-only rule**: Append an entry to [`PROJECT-LOG.md`](PROJECT-LOG.md) documenting what the user asked for, what was decided, why, and what shipped:

  ```markdown
  ## <Month Day at Hour:Minute AM/PM>
  ### Asked
  <what user asked for>

  ### Decision
  <what was decided>
  >why: <rationale>

  ### Shipped
  <what shipped>

  ---
  ```

- Never overwrite, delete, or truncate previous entries in `PROJECT-LOG.md` so that decisions outlive every session and nothing ever gets lost.