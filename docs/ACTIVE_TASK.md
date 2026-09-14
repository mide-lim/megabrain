# MegaBrain — Active Task

## Tarefa atual

**F3.3 — Internal Orchestration Boundary: LOCAL IMPLEMENTATION / HUMAN-GATED
PUBLICATION.**

F3.2 — Source-Neutral Processing Core is COMPLETE / PROD VALIDATED. The
Telegram -> MGB-020 -> Downloader path and the MGB-030 trigger after successful
download were validated by the operator. The long-audio STT failure remains
separate backlog work.

F3.3 moves MGB-010 to a Telegram adapter, makes FastAPI the authority for Reel
registration/deduplication, and introduces an authenticated internal dispatcher
to MGB-020. Production secrets, n8n import/activation, Caddy/Compose changes,
deployment and production validation remain human-gated.

No public Web Add Reel flow exists yet.

A reconciliação de integridade não concede autorização operacional. Qualquer
operação autenticada continua sujeita à capability permitida, Task Contract,
Run Authorization, estado do lifecycle e demais gates aplicáveis.

C1–C7.3 estão implantados e validados por operador: Google OIDC e sessão local do
proprietário, App Shell/Library/Reel Detail do Next.js, mutações de categoria
JSON com CSRF, corte `/reels/*` e aposentadoria Jinja. FastAPI é a autoridade de
autenticação, sessão, API e domínio; Next.js é a autoridade de apresentação;
Caddy fornece HTTPS e roteamento. Basic Auth é histórico do MVP, não a fronteira
Web atual.

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
