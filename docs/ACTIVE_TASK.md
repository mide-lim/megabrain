# MegaBrain — Active Task

## Tarefa atual

**Nenhum novo milestone de engenharia ou produto está selecionado.**

## Estado

Engineering Enablement Phase A: COMPLETE.

Engineering Enablement Phase B: COMPLETE / PROMOTED.

B1 — Automation Architecture Discovery: COMPLETE.

B2 — Public GitHub Foundation: COMPLETE / PROMOTED.

- B2.1 — Public Repository Preflight: COMPLETE.
- B2.2 — Public Repository Remediation: COMPLETE.
- B2.3 — Clean Public Baseline + Publication: COMPLETE.
- B2.4 — GitHub identity, protected branches e source-of-truth cutover: COMPLETE com esta mudança.

B3 — CI Foundation: COMPLETE / PROMOTED.

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

B4 — Hermes Autonomy Foundation: COMPLETE / PROMOTED.

- B4.1 — GitHub Auth Bootstrap: `COMPLETE / PROMOTED`.
- checkpoint de Discovery, SDD e Task Contract versionado antes da instalação;
- fonte canônica versionada em `skills/megabrain-github-app-auth/`; a instalação
  em `~/.hermes/skills/megabrain/megabrain-github-app-auth` é somente artefato
  derivado, reconstruído pelo instalador sem ler/copiá-la como fonte;
- a instalação e reinstalação herméticas em destino temporário limpo passaram:
  12 testes validaram bytes SHA-256, modo executável `0700`, conjunto exato de
  artefatos e ausência de `.env`, `.pem` e `.key`, sem credencial, JWT, token,
  rede ou operação autenticada;
- a capability B4.1 contém somente `probe-read-dev` de leitura; escrita Git,
  push, PR, merge, ruleset, bypass, deploy e produção permanecem excluídos do
  seu escopo;
- `--operational-gate-approved` é um guardrail de processo e não um limite de
  segurança técnico; toda operação autenticada futura ainda exige autorização
  humana nova e explícita;
- probe final da capability corrigida e instalada, explicitamente reautorizado,
  passou: GitHub provider-validou token read-only restrito a `contents: read`,
  sem write ou `administration`; escopo exclusivo `mide-lim/megabrain`; leitura
  de `refs/heads/dev`; revogação e cleanup confirmados. Não há nova operação
  autenticada autorizada sob B4.1.
- Pull Request #10 integrado manualmente em `dev`; B4.1 está promovida. A
  capability B4.1 permanece limitada à sua única operação read-only e não
  autoriza nenhuma nova operação autenticada sob B4.1.

- B4.2 — Autonomous PR Lifecycle: `COMPLETE / PROMOTED`.
- B4.3 — Bounded Run Authorization: `COMPLETE / PROMOTED`.
- Pull Request #20 foi integrado manualmente em `dev`. O candidato revisado
  `5856ffdb7ede157fb335cd5da05456c55029e717` resultou no commit de `dev`
  `32fe9751ef5f19e54d6fae4d5949dd2675a08b72`; o veredito final local foi
  `B4_3_R1_STAGE2F_R2_READY`.

A implementação de produto da Sprint 5 permanece não aprovada e adiada.
Engineering Enablement permanece separado do roadmap de produto; este closeout
não seleciona nem autoriza o próximo milestone de engenharia ou produto.

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

## Próximo trabalho

Nenhum próximo milestone de engenharia ou produto foi selecionado por este
closeout. Staging, Playwright, observabilidade, backup/restore, monitoramento,
automação de deploy e funcionalidades de produto permanecem fora deste escopo e
exigem aprovação e gates próprios.

## Restrições permanentes

- Seguir `AGENTS.md`.
- Agentes não acessam produção, Docker, segredos, `.env` de produção, banco real,
  n8n real ou o workspace de produção.
- GitHub é a fonte de verdade de desenvolvimento.
- Hermes trabalha em `agent/*` e pode publicar essas branches e abrir PRs.
- Hermes não tem autoridade para merge, auto-merge, force push, escrita direta
  em `dev` ou `main`, mutação de workflows, rulesets ou permissões do GitHub App,
  nem interfaces genéricas e irrestritas de Git, API ou shell.
- Sem auto-merge, acesso à produção ou deploy automático. Merge humano permanece
  uma fronteira de autoridade separada.
- Toda ação de produção permanece human-gated.
- A implementação de produto da Sprint 5 permanece não aprovada.
