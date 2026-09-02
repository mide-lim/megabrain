# MegaBrain — Active Task

## Tarefa atual

**MegaBrain Engineering Enablement — Phase B**

## Estado

Engineering Enablement Phase A: COMPLETE.

Phase B: ACTIVE.

B1 — Automation Architecture Discovery: COMPLETE.

B2 — Public GitHub Foundation: COMPLETE com a integração deste cutover.

- B2.1 — Public Repository Preflight: COMPLETE.
- B2.2 — Public Repository Remediation: COMPLETE.
- B2.3 — Clean Public Baseline + Publication: COMPLETE.
- B2.4 — GitHub identity, protected branches e source-of-truth cutover: COMPLETE com esta mudança.

A implementação de produto da Sprint 5 permanece não aprovada e adiada.
Engineering Enablement continua separado do roadmap de produto.

## Resultado da Phase A

- engineering roles defined;
- risk policy defined;
- Definition of Done defined;
- Task Contract defined;
- SDD established as Planner/Architect;
- UX capability established;
- UI System baseline established.

## Resultado da Public GitHub Foundation

- `mide-lim/megabrain` público é a fonte de verdade de desenvolvimento;
- o histórico público iniciou por uma baseline limpa e sanitizada;
- `main` e `dev` são protegidas por rulesets;
- Hermes usa GitHub App limitado ao repositório;
- Hermes pode publicar `agent/*` e abrir pull requests;
- Hermes não pode atualizar diretamente nem fazer merge em `dev` ou `main`;
- credencial SSH owner-level foi removida do alcance do Hermes;
- o Git privado anterior e o workspace arquivado permanecem somente como histórico;
- bundles estão aposentados do fluxo operacional;
- produção continua human-gated.

## Próxima fase de engenharia

O próximo candidato é a foundation de CI isolada e evidência determinística.

CI, staging, Playwright e qualquer progressão automática adicional ainda exigem
Task Contract, classificação de risco, validação e gates aplicáveis antes de
serem considerados capacidades disponíveis.

## Restrições permanentes

- Seguir `AGENTS.md`.
- Agentes não acessam produção, Docker, segredos, `.env` de produção, banco real,
  n8n real ou o workspace de produção.
- GitHub é a fonte de verdade de desenvolvimento.
- Hermes trabalha em `agent/*` e pode publicar essas branches e abrir PRs.
- Hermes não faz merge nem atualiza diretamente `dev` ou `main`.
- Sem auto-merge ou deploy automático.
- Toda ação de produção permanece human-gated.
- A implementação de produto da Sprint 5 permanece não aprovada.
