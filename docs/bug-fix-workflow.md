# Bug Fixing Workflow Guide

This guide details the root-cause bug resolution process used in this repository.

---

## 🎯 Overview

Trigger this workflow anytime something behaves unexpectedly or breaks:
- `/fix-bug`
- `/debug`
- Or in chat: *"Fix this bug: [description]"*

---

## The 6-Phase Root-Cause Lifecycle

```
1. Discovery Interview (/grill-me) ────► Clarifies repro steps & logs until you are satisfied
      │
      ▼
2. Root-Cause Analysis ────────────────► Isolates core defect, greps all callers
      │
      ▼
3. Failing Test Reproduction ──────────► Writes a test that fails before code changes
      │
      ▼
4. Minimal Root Fix ───────────────────► Ponytail minimal diff at the shared source
      │
      ▼
5. Verification & Zero Regressions ────► Reproduction test passes + no broken neighbors
      │
      ▼
6. Commit & Automated Release ─────────► fix(...) conventional commit + patch release
```

---

### Phase 1: Interactive Discovery Interview (`/grill-me`)
The agent asks targeted questions to isolate:
- **Reproduction steps**: Precise sequence of clicks, inputs, or API calls.
- **Expected vs. actual result**: What was supposed to happen vs. what occurred.
- **Console/Terminal errors**: Exact error messages, stack traces, and network logs.
- **Environment**: Browser, OS, device, or deployment environment.
- **Regression status**: When did this break? Did a recent commit trigger it?
*The interview runs across as many rounds as needed until you confirm complete satisfaction.*

---

### Phase 2: Root-Cause Analysis (No Band-Aids)
Following our Lazy Senior Dev (`ponytail.md`) philosophy:
- We never patch downstream callers with band-aids.
- We locate the underlying function causing the bad state, grep all callers across the repository, and fix the root problem.

---

### Phase 3: Failing Test Reproduction
Before touching source files, the agent writes ONE runnable check (unit test or assert script) that reproduces the issue and fails.

---

### Phase 4: Minimal Root Fix
The agent writes the shortest working diff directly at the root cause. No unrequested rewrites.

---

### Phase 5: Verification & Zero Regressions
- The failing test from Phase 3 must now pass.
- Existing tests must remain green.
- The test remains in the repository permanently to prevent future regressions.

---

### Phase 6: Commit & Automated Patch Release
- Uses conventional commit format (`fix(...)`), linking to any related issue (`Fixes #N`).
- Automatically triggers a patch version bump (e.g. `0.1.0` ➔ `0.1.1`) upon push to `main`.
