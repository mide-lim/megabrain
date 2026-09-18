# MegaBrain — Active Task

## Tarefa atual

**F5.1 — Add Reel UX: H2 remediation / QA.**

F4 production cutover is closed. F5.1 is the active frontend-only candidate:
branch candidate and Draft PR #44 exist. It is unmerged and undeployed. The
production baseline remains F4; this record does not assert any F5.1 production
state.

F5.1 H2 is reconciling governance and H1 findings under
`AUTORIZO_F5_1_H2_GOVERNANCE_AND_REMEDIATION`. The candidate remains limited to
the Next.js presentation boundary and its local validation. FastAPI remains the
authority for authentication, session, CSRF, API, registration, deduplication,
lifecycle, and dispatch. No backend, workflow, database, R2, Caddy, Compose, or
production-runtime change is part of this remediation.

Merge is separately human-gated. Production and deployment are separately
human-gated Red actions. Staging does not exist.

## Estado

Engineering Enablement Phase A: COMPLETE.

Engineering Enablement Phase B: COMPLETE / PROMOTED.

B3 — CI Foundation: COMPLETE / PROMOTED.

B4 — Hermes Autonomy Foundation: COMPLETE / PROMOTED.

- B4.1 — GitHub Auth Bootstrap: `COMPLETE / PROMOTED`.
- B4.2 — Autonomous PR Lifecycle: fonte canônica v1.1.0 e instalação ativa
  reconciliadas com paridade byte a byte; o uso operacional continua limitado
  às autorizações normais do lifecycle.
- B4.3 — Bounded Run Authorization: `COMPLETE / PROMOTED`.

CI isolada existe para Pull Requests destinados a `dev` e `main`. Staging ainda
não existe.

## Restrições permanentes

- Seguir `AGENTS.md`.
- Agentes não acessam produção, Docker, segredos, `.env` de produção, banco real,
  n8n real ou o workspace de produção.
- GitHub é a fonte de verdade de desenvolvimento.
- Hermes trabalha em `agent/*`.
- Hermes não tem autoridade para merge, auto-merge, force push, escrita direta
  em `dev` ou `main`, mutação de workflows, rulesets ou permissões do GitHub App,
  nem interfaces genéricas e irrestritas de Git, API ou shell.
- Sem acesso à produção ou deploy automático. Merge humano permanece uma
  fronteira de autoridade separada.
- Toda ação de produção permanece human-gated.
