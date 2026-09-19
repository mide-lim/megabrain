# MegaBrain — Active Task

## Tarefa atual

**F5.1 — Add Reel UX: production promotion preparation.**

F4 production cutover is closed and sealed.

F5.1 source implementation, remediation, CI and review are complete. PR #44 was
merged into `dev`; the canonical source revision is
`de3f59b03826ea23a51b7d07e035904dee653cbe`.

An immutable F5.1 frontend candidate has been built and validated. Production
still runs the sealed F4 frontend. No F5.1 production deployment has occurred.

The current work is limited to production-promotion documentation, immutable
artifact verification, rollback preparation and a human-gated deployment
preflight.

FastAPI remains the authority for authentication, session, CSRF, API,
registration, deduplication, lifecycle and dispatch. F5.1 changes only the
Next.js owner-facing Reel creation UX.

Production deployment remains a separate Red action requiring explicit human
authorization.

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
