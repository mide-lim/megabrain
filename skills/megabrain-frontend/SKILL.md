---
name: megabrain-frontend
description: Route MegaBrain frontend work to pinned local guidance.
version: 0.1.0
author: MegaBrain
license: Apache-2.0 AND MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [megabrain, frontend, nextjs, react, accessibility]
    related_skills: []
---

# MegaBrain Frontend Guidance

Use this skill as a router for work in `apps/web`. It provides pinned local references; it does not implement product behavior, change backend authority, or authorize authentication work.

## Prerequisites

Read the repository root `AGENTS.md` first. Treat FastAPI as the authority for backend, domain, and authentication behavior. Keep work within the approved milestone scope.

## Next.js Framework Facts

Before implementing any Next.js-specific behavior:

1. Inspect `apps/web/package.json`.
2. Resolve the installed Next.js version from `apps/web/node_modules/next/package.json`.
3. Discover the bundled documentation path in that installed package; for the current layout, inspect `apps/web/node_modules/next/dist/docs/` and the relevant App Router guide.
4. Prefer that version-matched local documentation over model memory, generic web examples, or a different Next.js release.

Do not vendor Next.js documentation here. Do not install MCP servers. If the package layout differs, discover the installed documentation rather than assuming a fixed path.

## Routing

Load only the smallest relevant subset; do not automatically load all references.

- New visual design, login surface, or new screen: load `references/frontend-design.md`.
- React or Next.js performance, rendering, or data fetching: load `references/react-best-practices.md`. Also use the installed-version Next.js documentation for framework-specific facts.
- Reusable component API or component architecture: load `references/composition-patterns.md`.
- Final UX, accessibility, interaction, or interface review: load `references/web-interface-guidelines.md`.

A task can require more than one reference only when its scope actually overlaps the routing categories. A login screen request does not authorize a change to the authentication architecture.

## Local References

`references/SOURCES.md` records the approved upstream organizations, repositories, immutable commits, paths, licenses, reviewed date, local destinations, and adaptation status. These references are pinned local copies. Updates are manual and human-reviewed; there is no `@latest`, runtime network fetch, or automatic upstream synchronization.

## Verification

Before completing frontend work:

- Confirm any Next.js behavior against the installed version's bundled documentation.
- Confirm the routing reference matches the task and no unrelated reference was loaded.
- Preserve Server Components first; use Client Components only for required interaction.
- Keep TypeScript strict and use semantic design tokens.
- Preserve FastAPI/domain/auth boundaries unless the milestone explicitly changes them.
