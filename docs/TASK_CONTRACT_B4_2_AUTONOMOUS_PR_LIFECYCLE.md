# Task Contract — B4.2 Autonomous PR Lifecycle

## Status

- Status: DRAFT / ACTIVE DISCOVERY — não aprovado para implementação ou operação autenticada de escrita.
- Risk Level: YELLOW para qualquer implementação/instalação de capability de escrita; documentação atual é GREEN.
- Stop condition: parar antes de criar, instalar, habilitar ou executar o primeiro caminho autenticado de escrita.

## Objective

Definir uma capability controlada que, depois de um Task Contract operacional aprovado, possa conduzir autonomamente o lifecycle normal de uma única branch `agent/<slug>` até `READY`:

```text
commit -> push -> PR para dev -> observar CI -> diagnosticar -> corrigir
-> push -> reavaliar -> READY
```

O gate fica na aprovação do contrato/capability, não em cada comando normal. Merge em `dev` permanece exclusivamente humano.

## Source Documents

- `docs/AUTONOMOUS_PR_LIFECYCLE_B4_2_DISCOVERY.md`
- `docs/AUTONOMOUS_PR_LIFECYCLE_B4_2_SDD.md`
- `docs/GITHUB_APP_AUTH_BOOTSTRAP_DISCOVERY.md`
- `docs/GITHUB_APP_AUTH_BOOTSTRAP_SDD.md`
- `docs/RISK_POLICY.md`
- `docs/DEFINITION_OF_DONE.md`
- `AGENTS.md`

## Scope

### In

- design, implementação hermética futura e validação progressiva de tokens efêmeros e downscoped;
- publicação não-forçada de uma ref exata `agent/<slug>`;
- criação/atualização de um único PR dessa branch para `dev`;
- leitura de PR/CI/jobs/logs para SHA exato;
- até o orçamento do contrato: correção, novo commit, nova publicação e mesma PR;
- tratamento fechado de behind, failure, timeout, PR fechado e drift;
- revogação/cleanup e registros sanitizados.

### Out — limites permanentes

- merge, auto-merge, merge queue ou progressão automática para `main`;
- push direto para `dev` ou `main`, force-push, rebase, tag, delete ou alteração de remote;
- criação/alteração/desativação de rulesets, bypass, Administration ou alteração de App/instalação/permissões;
- PAT, SSH owner-level, secrets, produção, deploy, Docker, workspace de produção ou dados persistentes;
- re-run, cancel, approve ou dispatch de GitHub Actions;
- `.github/workflows/**` na primeira versão;
- mudanças no plano de controle/capability/políticas em Task Contracts normais de desenvolvimento.

## Initial Operational Contract Template

Cada uso futuro deve preencher e receber aprovação humana explícita antes de escrita:

```text
lifecycle_id: <immutable>
status: APPROVED | EXPIRED | REVOKED
repository: mide-lim/megabrain
origin_url: https://github.com/mide-lim/megabrain.git
branch: agent/<approved-slug>
base: dev
head_sha_initial: <40-char SHA>
allowed_paths: <explicit glob list>
forbidden_paths: .github/workflows/**, skills/**, AGENTS.md, docs/RISK_POLICY.md,
                 docs/DEFINITION_OF_DONE.md, docs/TASK_CONTRACT*.md, infra/**
expected_ci_jobs: Repository validation, Enricher tests, Web tests
allow_safe_refresh: false | true
max_corrections: <small fixed integer>
poll_deadline_utc: <fixed timestamp>
owner_human: <named role/person>
approval_reference: <human decision reference>
```

A capability deve recusar valores vazios, curingas em branch/base/repository, fields extras, contrato não aprovado/expirado, ou qualquer alteração material depois da aprovação. `allowed_paths` não reduz permissões GitHub; é somente controle local de defesa em profundidade.

## Operation / Permission / Gate Matrix

| Operação | Token mínimo solicitado | Provider-enforced | Controle local obrigatório | Gate |
|---|---|---|---|---|
| Preflight local | nenhum | N/A | remote/origin, branch/ref, SHA, paths, checkout e contrato exatos | automático após contrato aprovado |
| Publicar HEAD | `contents: write` | scope/permissão do token; rulesets de refs atingidas | somente `HEAD:refs/heads/agent/<slug>`, non-force, read-back SHA | Yellow contract aprovado |
| Criar/reutilizar PR | `pull_requests: write` | permission do token | repo/head/base/PR fingerprint exatos; somente `agent/<slug> -> dev` | Yellow contract aprovado |
| Atualizar metadata do mesmo PR | `pull_requests: write` | permission do token | PR único e template permitido | Yellow contract aprovado |
| Observar PR/CI/jobs/logs | `pull_requests: read`, `actions: read`, `statuses: read` | permission do token | SHA/run/PR correlation; logs em memória/sanitizados | Yellow contract aprovado |
| Safe refresh | `contents: write` | scope/permissão do token | merge não-forçado de `origin/dev`, sem conflito/rebase | flag explícita no contrato |
| Corrigir e republish | perfis anteriores, separados | scope/permissão do token | paths, orçamento, mesmo PR/SHA lifecycle | automático dentro do orçamento aprovado |
| Declarar READY | read-only | GitHub decide proteção no merge, não a capability | PR open + head/base/SHA + três jobs success | automático; merge humano |
| Merge/auto-merge | proibido | rulesets se ativos | sem endpoint/comando | HUMAN GATE permanente |
| Rulesets/App/workflows/produção | proibido | Administration/App settings provider-side | denylist e ausência de operações | HUMAN GATE permanente |

## Acceptance Criteria

- A interface futura é fechada: nenhum shell, endpoint, remote, ref, base, PR ou opção Git arbitrária.
- Todo token é de um repositório, possui apenas o perfil de permission da operação e é revogado/removido em todos os paths; uma falha de cleanup/revogação é falha fechada.
- A capability não tenta escrita sem contrato aprovado e não expirado.
- O único destino de push possível é o nome exato da branch declarada, iniciado por `agent/`; nenhuma validação local é descrita como ACL provider-enforced.
- O único PR possível usa repositório esperado, head exato e base `dev`; correções atualizam esse mesmo PR.
- Nenhuma mutation ocorre se PR/head/base/SHA/remote/repo divergir, se houver PR duplicado, se o PR estiver fechado/merged ou se a branch não for fast-forward para publicação.
- CI é aceita somente para SHA atual, PR atual e os três jobs esperados com conclusão `success`; timeout, status faltante, failure e run ambíguo não são READY.
- `BEHIND` só pode usar safe refresh quando a flag foi aprovada; conflito, rebase, force push e resolução automática são recusados.
- `.github/workflows/**` e plano de controle são bloqueados v1; nenhuma Actions write é solicitada.
- Nenhuma funcionalidade B4.2 muda rulesets, permissões/instalação App, segredos, produção, deploy ou merge.
- Todos os testes herméticos definidos na SDD passam antes de qualquer token real.

## Required Evidence

- revisão do código e diff da capability contra este contrato;
- testes herméticos de schema, permission/scope, Git ref, PR drift, CI correlation, timeout, log redaction e cleanup;
- inspeção confirmando ausência de `.env`, chave, token, JWT, config persistente ou credencial em logs;
- para cada gate operacional futuro: resultado sanitizado, permission/scope validation, read-back do provider e cleanup/revocation outcome;
- `git diff --check` para documentação/código versionado.

## Progressive Operational Validation Plan

Nenhuma destas fases está autorizada por este documento rascunho. Cada fase exige decisão humana explícita e somente avança se a anterior produzir evidência sanitizada e cleanup íntegro.

1. `P0` — testes herméticos, sem key/JWT/token/rede: validar recusa e cleanup injetado.
2. `P1` — leitura autenticada: mint observer downscoped, verificar mapa/scope e ler PR/CI de alvo inócuo; revogar. Sem escrita.
3. `P2` — publicação controlada: um commit Green previamente revisado, push único para branch `agent/*` exata e read-back SHA. Sem PR mutation.
4. `P3` — criar/reutilizar um PR controlado `agent/* -> dev`, read-back de head/base/estado; parar antes de merge.
5. `P4` — observar uma execução CI desse PR e correlacionar SHA/jobs; somente leitura de logs falhos se houver; parar em READY/terminal.
6. `P5` — uma correção deliberada de baixo risco dentro do contrato, atualizar o mesmo PR e reavaliar CI. Safe refresh só após decisão separada.
7. `P6` — avaliação humana das evidências para decidir se o lifecycle completo pode ser concedido a contratos futuros com limites equivalentes.

## Security / Threat Boundary

O provider impõe o escopo/permissões do token e, enquanto mantidos, os rulesets sobre `dev`/`main`. A capability impõe localmente ref, remote, base, paths, PR e loop. A revisão/aprovação humana impõe a concessão de contrato e a promoção. Esses três níveis não são equivalentes; a falha do controle local não deve ser apresentada como falha do provider.

## Rollback / Recovery

- Antes de operação real: remover somente a instalação derivada futura, após confirmar que não há processo/temp/token, e reverter o código via PR humano.
- Após push: não apagar nem force-pushar; corrigir com novo commit dentro do contrato ou parar para decisão humana.
- Revogação/cleanup falho, timeout, drift ou PR fechado: parar e não reter token para retry.

## Human Gates

1. Aprovar esta Discovery/SDD/Task Contract e decidir se o limite local `agent/*` é aceitável para uma primeira escrita.
2. Aprovar implementação e instalação Yellow, limitada a testes herméticos.
3. Aprovar cada fase P1–P5 de operação real, em separado, com alvo e limite explícitos.
4. Aprovar cada Task Contract operacional que concede autonomia normal futura.
5. Decidir merge em `dev` e qualquer progressão posterior. Este gate é permanente.

## Open Questions

- Há um mecanismo provider-enforced adicional desejado para restringir escrita em refs não protegidas antes de P2?
- Quem é o owner humano nomeado para aprovar contratos e receber estados `STOP_NEEDS_HUMAN`?
- A primeira concessão de lifecycle deve incluir safe refresh ou limitar-se a publish/PR/observe/fix?
