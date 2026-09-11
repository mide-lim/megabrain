# MegaBrain — Active Task

## Tarefa atual

**C7.1 — Runtime Contract & Live-State Remediation: READY / HUMAN-GATED
PUBLICATION.**

O candidato C7.1 foi validado localmente e revisado pelo operador. Sua
publicação permanece human-gated e não deve usar a capability B4.2 instalada
enquanto a discrepância de integridade estiver pendente de C7.2. Este estado
não autoriza deploy, produção, mudança de Caddy, configuração de segredos,
migração ou reconciliação automática do artefato B4.2 instalado.

C1–C6 estão implantados e validados por operador: Google OIDC e sessão local do
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
- B4.2 — Autonomous PR Lifecycle: instalado, mas com discrepância de integridade
  identificada; C7.2 permanece necessário antes de uso de publicação
  autenticada.
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
