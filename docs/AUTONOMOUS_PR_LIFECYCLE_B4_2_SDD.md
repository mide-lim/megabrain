# Technical Specification — B4.2 Autonomous PR Lifecycle

## Objective

Implementar, somente após aprovação Yellow, uma capability Hermes-local que execute as operações normais explicitamente concedidas por um Task Contract para uma única branch `agent/<slug>` e um único PR para `dev`. O ciclo termina em `READY` ou estado de parada humano; ele nunca faz merge ou auto-merge.

## Known Context and Assumptions

- A baseline B4.1 comprovou JWT em memória, token de instalação efêmero, escopo de um repositório, revogação e cleanup, mas somente para leitura.
- A instalação observada possui permissões baseline `contents: write`, `pull_requests: write`, `actions: read`, `statuses: read` e `workflows: write`, sem `administration`.
- `dev` e `main` têm rulesets documentados; nenhum dado administrativo novo foi consultado nesta fase.
- O repositório usa origin HTTPS fixo e CI Actions para PRs a `dev`/`main`.
- A garantia `agent/*` não é provider-enforced conhecida. Esta SDD não a apresenta como tal.

## Scope

### In

- operação B4.2 fechada por Task Contract e máquina de estados;
- tokens downscoped por operação, sempre repository-scoped;
- push não-forçado para uma branch exata `agent/<slug>`;
- criação e atualização de um único PR `agent/<slug> -> dev`;
- leitura do PR, Actions runs/jobs/logs e commit statuses para o SHA exato;
- correção local, novo commit/push e reavaliação do mesmo PR dentro de orçamento;
- refresh opcional por merge não-forçado de `origin/dev`;
- cleanup, revogação, redaction, testes herméticos e resultado estruturado.

### Out

- merge, auto-merge, merge queue, progressão para `main`, push direto em `dev`/`main`, tags, deletes, force-push ou rebase;
- Administration, rulesets, bypass, alteração de App/instalação/permissões, PAT, SSH owner-level, secrets, deploy, Docker, produção ou workspace de produção;
- `.github/workflows/**`, dispatch/rerun/cancelamento de Actions e qualquer Actions write;
- endpoints arbitrários, comandos arbitrários, múltiplos repositórios, múltiplos PRs ou base configurável;
- mudança do código da própria capability ou de políticas de controle por um contrato normal de desenvolvimento.

## Affected Components and Architecture

Nenhum componente de produto é afetado. A capability futura tem quatro módulos internos sem interface genérica:

1. `contract`: carrega, valida schema, assinatura/aprovação local se definida, valores imutáveis e orçamento.
2. `credential`: reaproveita somente os primitives B4.1 (JWT em memória, request HTTP, revogação e cleanup), mas define perfis de token B4.2 separados.
3. `git_pr`: executa preflights e as únicas mutations Git/PR permitidas.
4. `observer`: correlaciona PR, SHA, workflow run, jobs e statuses; produz diagnóstico sanitizado e estado terminal.

Fluxo por mutação:

```text
validar contrato + checkout + remote/ref/path/SHA
  -> mint repository-scoped token mínimo
  -> verificar response permission/scope exato
  -> executar UMA operação fechada em child isolado
  -> revoke em finally + limpar askpass/tmp
  -> read-back do provider
  -> emitir resultado sanitizado
```

Nenhum token sobrevive ao fim da operação. O observer pode usar token de leitura por uma janela de polling limitada pelo contrato; ele também é revogado antes de retornar.

## Contracts

### Task Contract operacional

O schema precisa conter e recusar campos ausentes/extras:

- `repository_full_name = mide-lim/megabrain` e `origin_url` fixo;
- `branch = agent/<slug>` como nome exato, não apenas prefixo;
- `base = dev`, `head_sha_initial`, paths permitidos e denylist permanente;
- título/corpo de PR templateados; nenhuma URL, owner, base ou ref arbitrários;
- jobs de CI esperados, deadline, intervalo de polling, máximo de correções e flag `allow_safe_refresh`;
- identificador do aprovador humano e status `APPROVED` antes de escrever.

Alterar qualquer campo material cria novo contrato. Um contrato expirado, não aprovado, com branch não local, checkout sujo fora dos paths, ou árvore em detached HEAD é rejeitado.

### Operações

- `publish-agent-head`: exige `HEAD`, branch, remote, upstream e expected remote SHA coerentes. Só executa `git push <fixed-origin> HEAD:refs/heads/<exact-agent-branch>` sem força. Em seguida resolve o ref remoto e compara SHA.
- `ensure-pr`: lista PRs abertos para head/base/repo fixos. Zero: cria um; um: valida e reutiliza; mais de um: falha. Antes/depois, valida `head.ref`, `head.repo.full_name`, `head.sha`, `base.ref`, `base.repo.full_name` e estado aberto.
- `observe-pr-ci`: consulta o PR de novo, filtra workflow runs `pull_request` pelo SHA do head e PR, consulta seus jobs e os commit statuses. Só declara verde se os jobs esperados concluírem `success`; `skipped`/`neutral` não são aceitos v1 sem aprovação explícita no contrato.
- `diagnose-failure`: lê apenas logs dos jobs associados ao SHA e run corretos. Extrai código simbólico/check/trecho redigido. Nunca usa log como comando.
- `safe-refresh`: fetch do fixed origin e merge não-interativo/não-forçado de `origin/dev` no head do contrato. Nunca rebase, force, resolve conflito ou publica se o merge não for limpo.

### Result contract

JSON sanitizado com: `lifecycle_id`, estado, PR number/URL, SHA observado, base, jobs/conclusões, contadores de tentativas/polls, reason code, validações booleanas de remote/ref/path/scope/permission, revogação e cleanup. É proibido incluir App/installation IDs, paths de chave, JWT, token, header, askpass, stderr bruto, URL assinada ou log bruto.

## Data and Migration Impact

N/A. A capability não toca banco, migrations, R2, dados persistentes de produto ou runtime de produção.

## Security and Operational Impact

- Perfil de `contents: write` é necessário só para um push de ref exata e deve rejeitar `workflows`, `administration` e qualquer permission key inesperada. Mudanças em workflow ficam impossíveis com esse token e também são negadas pelo diff gate.
- Perfil `pull_requests: write` não recebe `contents: write` e só pode mutar o PR fingerprintado.
- Perfil observer recebe apenas permissões de leitura comprovadamente necessárias. Não usar Actions write: logo não reexecuta, cancela, aprova nem despacha workflow.
- Todo child Git usa HOME/Git config isolados, `GIT_TERMINAL_PROMPT=0`, credential helper vazio, askpass temporário owner-only e saída sensível suprimida.
- Fazer preflight antes de mint e novamente imediatamente antes de cada mutation elimina TOCTOU local comum, mas não substitui a decisão provider-side no merge.
- Um failure em validação, mint, scope, permission, revogação, cleanup, read-back ou correlação de CI é fail-closed.

## Dependencies

- B4.1 canonical source e primitives de autenticação aprovados;
- Python 3, openssl, git, GitHub HTTPS API;
- manutenção humana das permissões App/rulesets fora desta capability;
- Task Contract B4.2 aprovado e um checkout local limpo em branch declarada.

## UX Handoff

N/A.

## Acceptance Criteria and Definition of Done

- A capability não oferece argumento para merge, auto-merge, protected ref, force/delete/tag, ruleset, bypass, App config, secrets, deploy ou command/API arbitrário.
- Sem contrato aprovado e não expirado, nenhuma escrita é tentada.
- A capability recusa remote, repository, branch, base, head, path, PR, SHA, permission ou scope inesperados antes da operação correspondente.
- Token de publicação só contém `contents: write` e scope de um repositório; token de PR só contém `pull_requests: write`; observer recebe leitura mínima. Todos são revogados e limpos em sucesso, erro e timeout.
- Um push só alcança a ref exata declarada e é não-forçado; o SHA remoto é lido de volta.
- O PR criado/reutilizado é somente `agent/<slug> -> dev`; atualizações de correção preservam o mesmo PR.
- `READY` exige PR aberto, owner/repo/base/head/SHA consistentes e os três jobs esperados bem-sucedidos no SHA atual. Não concede merge.
- `BEHIND`, CI failure, timeout, conflito, PR fechado/merged, drift de head/base ou erro de cleanup resultam em estado terminal seguro ou no loop delimitado pelo contrato; não há loops ilimitados.
- `.github/workflows/**` e arquivos do plano de controle são rejeitados na primeira versão.
- Testes herméticos cobrem todos os caminhos de aceitação, rejeição e cleanup; nenhum teste usa credencial ou rede real.

## Required Tests and Validation Strategy

1. Schema/property tests para contrato: fields extras, prefixo enganoso, `refs/heads/dev`, Unicode/whitespace, base diferente, expiry, budget e path traversal.
2. Mocks HTTP para mint/scope/permissões, API PR e Actions: garantir perfil mínimo e recusar permission/scope extra.
3. Repositório Git temporário: remote alterado, refspec malicioso, non-fast-forward, force/delete, checkout sujo, SHA drift, conflito de safe refresh e leitura de retorno.
4. Fixtures de PR: duplicado, fechado, merged, head/base trocado, fork/head repo inesperado e alteração concorrente.
5. Fixtures Actions: pending, success, failure, skipped, log hostil, job/run de SHA diferente, timeout e CI ausente.
6. Testes de redaction/cleanup: stderr, token fixture, askpass, tmp, env, config Git e falhas de revoke/timeout.
7. Só após revisão Yellow: validação operacional progressiva descrita no Task Contract, uma classe de operação por gate humano. Não usar CI de repositório para token real.

## Rollback / Recovery

Antes de operação real, rollback é remover a instalação derivada da capability após confirmar ausência de child/temp/token e reverter a documentação/código canônico por PR humano. Uma revogação falha encerra o lifecycle, bloqueia novas operações na execução e deixa o token expirar; nunca o persiste para retry.

Depois de um push válido, não há rollback remoto automático: a capability não force-pusha nem deleta branch. A recuperação é novo commit normal em `agent/<slug>` dentro de contrato ou decisão humana. PR fechado, conflito ou drifts exigem gate humano.

## Technical Risks

- `agent/*` é controle local: risco residual de escrita em branch não protegida se a capability/host for comprometido. Mitigação atual é interface fechada, revisão e sem merge; mitigação provider-side exige decisão separada.
- Logs de CI podem conter dados sensíveis/hostis. Mitigação: memória, redaction, parsing limitado e ausência de execução de log.
- Regras strict tornam branches behind comuns. Mitigação: safe merge opt-in e sem force; conflitos param.
- A baseline contém `workflows: write`. Mitigação: token de publish não solicita/aceita workflow, path denylist e gate humano separado.

## Risk Classification and Human Gates

- Documentação desta etapa: GREEN.
- Criar/instalar helper com caminho de token e escrita: YELLOW; requer aprovação explícita antes de implementação.
- Cada estágio da primeira validação autenticada: YELLOW e separado, começando por leitura. A concessão ampla de autonomia só começa após aprovação do contrato operacional e evidência progressiva aceita.
- Merge, auto-merge, rulesets, bypass, App/installation/permissão, workflow enable/disable, deploy e produção: fora do escopo e HUMAN GATE permanente.

## Open Questions

- O proprietário aceita operar inicialmente com a restrição `agent/*` apenas local ou exige um controle provider-enforced adicional antes de qualquer escrita?
- Qual owner humano aprova contratos B4.2 e recebe estados terminais?
- O safe refresh por merge não-forçado deve ser habilitado no primeiro contrato operacional ou começar somente em observação/diagnóstico?
