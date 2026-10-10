# Feature Workflow Guide

This guide describes how new features are planned, designed, and shipped in this workspace using AI pair programming.

---

## 🎯 Overview

Whenever you want to build a new feature, you can trigger this process by typing:
- `/new-feature`
- `/add-feature`
- Or simply asking: *"I want to add a new feature: [description]"*

The workflow follows a 6-phase quality gate ensuring nothing is built on assumptions or broken in production.

---

## The 6-Phase Lifecycle

```
[Feature Idea]
      │
      ▼
1. Discovery Interview (/grill-me) ────► Probes edge cases; runs until you explicitly approve
      │
      ▼
2. Technical Roadmap (/plan) ──────────► Formulates architecture, files, and self-checks
      │
      ▼
3. Issue & Living Docs ────────────────► gh issue create + updates docs/prd.md & architecture.md
      │
      ▼
4. Implementation ─────────────────────► Ponytail minimal-diff code + high-end UI design standards
      │
      ▼
5. Verification & Safety ──────────────► Automated self-checks + zero regressions + clean rollback
      │
      ▼
6. Commit & Automated Release ─────────► Conventional commit + CI release + handoff update
```

---

### Phase 1: Interactive Discovery Interview (`/grill-me`)
* **Goal**: Deeply explore requirements before any code is generated.
* **How it works**: The AI will ask targeted questions one at a time using interactive choice prompts.
* **Coverage**: User journeys, edge cases, permission checks, form validations, empty states, error feedback, mobile responsiveness, and data models.
* **The Satisfaction Guarantee**: **The interview does NOT stop after 1 or 2 shallow questions.** It continues iteratively across multiple probing rounds. Before exiting, the AI presents a structured summary and asks: *"Are you satisfied with this feature scope and ready to plan implementation?"* Only with your explicit approval does it proceed.

---

### Phase 2: Technical Execution Plan (`/plan`)
* Translates the discovery findings into an actionable technical plan.
* Identifies existing reusable utilities, types, and database models.
* Plans the file modifications and designs an automated verification self-check.

---

### Phase 3: Issues & Documentation Sync
* Creates an official GitHub issue via `gh issue create`.
* Updates [`docs/prd.md`](prd.md) with user stories, feature priorities, and acceptance criteria.
* Updates [`docs/architecture.md`](architecture.md) if new APIs, models, or data flows are introduced.
* Updates `.env.example` if the feature requires new environment variables.

---

### Phase 4: Implementation (The Ponytail & Vibe Coding Way)
* **Ponytail Protocol**: Only writes the minimum necessary code. Uses standard libraries and native platform APIs before adding dependencies.
* **High-End UI Standards**: Employs the project's design skills ([`ui-styling`](../.agents/skills/ui-styling/), [`high-end-visual-design`](../.agents/skills/high-end-visual-design/)) for tasteful typography, generous whitespace, accessible contrast, and subtle micro-interactions.

---

### Phase 5: Verification & Safety
* **Runnable Self-Check**: Every non-trivial feature leaves behind at least ONE automated test or assert-based verification check.
* **Zero Regressions**: Confirms existing tests and paths remain unbroken.
* **Clean Rollback**: If an experimental approach hits roadblocks, the AI runs `git restore .` to revert cleanly, logs the failure in [`handoff.md`](../handoff.md) under *Failed Attempts*, and re-enters `/grill-me` to pivot.

---

### Phase 6: Commit, Handoff & Automated Release
* The commit is formatted as a Conventional Commit (`feat(...)`), referencing the GitHub issue (`Closes #N`).
* Decisions are logged to [`PROJECT-LOG.md`](../PROJECT-LOG.md) and state is synced in [`handoff.md`](../handoff.md).
* Upon pushing to `main`, GitHub Actions automatically bumps semantic versions in [`VERSION`](../VERSION) and publishes a GitHub Release with formatted release notes.
