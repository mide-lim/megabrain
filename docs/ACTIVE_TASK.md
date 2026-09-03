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

B3 — CI Foundation: COMPLETE.

- B3.1 — GitHub Actions CI Foundation: COMPLETE.
- workflow inicial criado para validação de repositório, Enricher e Web;
- validação local concluída;
- execução real dos 3 checks no Pull Request #4 concluída com sucesso.

- B3.2 — Required Status Checks: COMPLETE / PROMOTED.
- ruleset independente `require-ci` ativo para `dev` e `main`;
- `Repository validation`, `Enricher tests` e `Web tests` obrigatórios;
- checks vinculados ao GitHub Actions integration ID `15368`;
- strict policy comprovada com Pull Request real;
- gate humano de merge e isolamento do Hermes preservados;
- rollback documentado, independente e sujeito a gate humano.

B4 — Hermes Autonomy Foundation: ACTIVE.

- B4.1 — GitHub Auth Bootstrap: `COMPLETE / HUMAN GATE FINAL`.
- checkpoint de Discovery, SDD e Task Contract versionado antes da instalação;
- fonte canônica versionada em `skills/megabrain-github-app-auth/`; a instalação
  em `~/.hermes/skills/megabrain/megabrain-github-app-auth` é somente artefato
  derivado, reconstruído pelo instalador sem ler/copiá-la como fonte;
- a instalação e reinstalação herméticas em destino temporário limpo passaram:
  12 testes validaram bytes SHA-256, modo executável `0700`, conjunto exato de
  artefatos e ausência de `.env`, `.pem` e `.key`, sem credencial, JWT, token,
  rede ou operação autenticada;
- a capability contém somente `probe-read-dev` de leitura; B4.2, escrita Git,
  push, PR, merge, ruleset, bypass, deploy e produção continuam excluídos;
- `--operational-gate-approved` é um guardrail de processo e não um limite de
  segurança técnico; toda operação autenticada futura ainda exige autorização
  humana nova e explícita;
- self-test operacional somente leitura da GitHub App concluído historicamente
  com sucesso; nenhuma nova operação autenticada é autorizada.
- a entrega canônica permanece parada para revisão e decisão humana de merge do
  Pull Request para `dev`; não há auto-merge.

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

## Trabalho atual de engenharia

A primeira foundation de CI isolada concluiu validação local e remota.

O Pull Request #4 executou com sucesso os jobs de validação do repositório,
Enricher e Web e foi integrado em `dev` após aprovação humana.

B3.1 está concluído.

B3.2 — Required Status Checks está `COMPLETE / PROMOTED`. O ruleset
`require-ci` está ativo para `dev` e `main`; os três checks da CI são
obrigatórios, vinculados ao GitHub Actions integration ID `15368`, e a política
strict foi comprovada por Pull Request real. O gate humano de merge e a ausência
de autoridade administrativa, de merge e de produção para Hermes foram
preservados.

Staging, Playwright e qualquer progressão automática adicional permanecem
entregas separadas e exigem seus próprios gates.

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
