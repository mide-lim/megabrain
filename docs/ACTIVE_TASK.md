# MegaBrain — Active Task

## Tarefa atual

**F5.1 — Add Reel UX: production accepted / closeout recorded.**

F4 production cutover remains closed and sealed. Its frontend image is preserved
as the F5.1 rollback anchor.

F5.1 source implementation, remediation and CI completed through PR #44, merged
into `dev` at canonical source revision
`de3f59b03826ea23a51b7d07e035904dee653cbe`.

The immutable F5.1 frontend was explicitly authorized, deployed and accepted in
production on 2026-09-19. Production runs image
`sha256:9a8af64f45d6eff9b60a052f08e5043434abb49440eaf47f84b351b99c284c04`.

Human UI acceptance passed for Inbox, Library, Categories, Settings, Reel Detail
and the Add Reel dialog. The controlled Web ingestion created Reel #26
(`DdcX68ZRQun`) and executed MGB-015 #123, MGB-020 #124 and MGB-030 #125
successfully. The Reel reached `downloaded | inbox | failed`; the enrichment
attempt recorded the known `STT_SYNC_RECOGNIZE_UNSUPPORTED` transcription
limitation rather than an Add Reel failure.

Production acceptance evidence is sealed independently from F4 with SHA-256
`e7dc4b42ddab75f6da1e992afdef0000d3109e1092645aec8964c307d6347d9d`.

FastAPI remains the authority for authentication, session, CSRF, API,
registration, deduplication, lifecycle and dispatch. F5.1 changes only the
Next.js owner-facing Reel creation UX.

No F5.2 is approved. The next product step returns to discovery based on real
usage. Future production mutations remain separately human-gated.

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
