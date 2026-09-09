# apps/web Agent Guidance

The repository root `AGENTS.md` remains authoritative.

- FastAPI remains the backend, domain, and authentication authority.
- Use Server Components first; add Client Components only when interaction requires them.
- Keep TypeScript strict and use semantic design tokens.
- Before Next.js-specific work, inspect `package.json`, resolve the installed version, and consult its bundled documentation in `node_modules/next`.
- Use the task-specific routing in `skills/megabrain-frontend/SKILL.md`.
- Do not add Redux, Zustand, or TanStack Query without a concrete need.
- Do not move domain logic into Next.js.
- Do not change the authentication architecture without explicit milestone scope.
