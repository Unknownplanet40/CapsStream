# UI/UX Redesign & Polish Workflow Guide

This guide describes how user interfaces are styled, audited, and redesigned in this repository using the workspace's specialized UI/UX skills.

---

## 🎯 Overview

Trigger this workflow anytime you want to improve interface styling, polish micro-interactions, or redesign a component:
- `/fix-ui`
- `/change-ui`
- `/redesign-ui`
- Or in chat: *"Redesign this component: [description]"*

---

## 💎 Foundation: The Vibe Coding Philosophy ([`AGENTS.md`](../AGENTS.md))

Every interface designed in this repository must strictly adhere to the 5 aesthetic pillars:
- **Typography:** Limited, purposeful type scale with clear hierarchy. Prefer system or high-quality sans-serif fonts. Avoid excessive weights or decorative styles.
- **Spacing & Layout:** Consistent, generous whitespace. Use a strict spacing system (4/8px grid). Layouts should feel airy, balanced, and scannable.
- **Color:** Restrained, harmonic palette—neutrals with one strong accent. High contrast for accessibility. Avoid gratuitous gradients, neon, or vibrant colors unless functionally justified.
- **Interaction:** Micro-interactions must be subtle, fast, and purposeful (150–200ms soft fades, precise transitions). No flashy or distracting animations.
- **Overall Feel:** Clean, modern, trustworthy, deliberate—never generic, cluttered, or "AI-generated."


## The 4-Phase Visual Quality Gate

```
1. Discovery Interview (/grill-me) ────► Probes aesthetic vibe, tokens & pain points (until satisfied)
      │
      ▼
2. 4-Layer UI Skill Orchestration:
   ├─ 1. Anti-Slop Audit ──────────────► design-taste-frontend, redesign-existing-projects
   ├─ 2. Tokens & Layout ──────────────► design-system, ui-styling
   ├─ 3. Polish & Micro-motion ────────► make-interfaces-feel-better, high-end-visual-design, better-icons
   └─ 4. Accessibility Check ──────────► web-design-guidelines
      │
      ▼
3. Verification Across Viewports ──────► Mobile (<640px), tablet, desktop & interactive states
      │
      ▼
4. Commit & Automated Release ─────────► style(...) or feat(...) conventional commit
```

---

### Phase 1: Interactive Discovery Interview (`/grill-me`)
The agent questions you to understand:
- **Visual vibe**: Corporate minimalism, sleek dashboard, dark-mode technical tool, or clean marketing page.
- **Pain points**: What feels generic, cluttered, misaligned, or cheap.
- **Tokens**: Palette adjustments (neutrals + 1 accent), typography scales, spacing grid.
- **Component states**: Hover, active, focus-visible, loading skeletons, and empty states.
*The interview runs across as many rounds as needed until you confirm complete satisfaction.*

---

### Phase 2: Systematic UI Skill Orchestration
The agent activates specialized project skills in `.agents/skills/`:
1. **Audit (`design-taste-frontend`, `redesign-existing-projects`)**: Blocks AI tropes (overused purple gradients, floaty unanchored cards, excessive glow).
2. **Tokens & Layout (`design-system`, `ui-styling`)**: Enforces token hierarchy and accessible component primitives (Radix UI / Tailwind).
3. **Polish & Motion (`make-interfaces-feel-better`, `high-end-visual-design`, `better-icons`)**: Implements precise 150–200ms transitions, optical alignment, and crisp Iconify SVG icons.
4. **Accessibility Check (`web-design-guidelines`)**: Verifies WCAG AA contrast, 44x44px touch targets, and focus indicators.

---

### Phase 3: Verification Across Viewports
- Verifies responsive layout scaling on mobile (<640px), tablet (768px), and desktop.
- Confirms zero horizontal overflow bugs.

---

### Phase 4: Commit & Release
- Formatted as `style(<scope>): ...` or `feat(<scope>): ...`.
- Logged in `PROJECT-LOG.md` and synced to `handoff.md`.
