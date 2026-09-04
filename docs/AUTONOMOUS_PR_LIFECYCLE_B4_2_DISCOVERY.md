# B4.2 — Autonomous PR Lifecycle Discovery

## Status

DISCOVERY COMPLETE — documentação Green. Nenhuma capability autenticada de escrita foi criada, instalada ou habilitada.

## Objetivo

Definir uma capability local controlada para executar, após aprovação de um Task Contract, o ciclo normal limitado a:

```text
agent/<contract-branch> -> commit -> push -> PR para dev -> observar CI
-> diagnosticar -> corrigir -> push -> reavaliar -> READY
```

`READY` significa apenas que o PR aberto ainda aponta para o SHA observado, tem base `dev` e passou a política de CI declarada no contrato. Não significa merge autorizado, mergeável de forma permanente, promoção para `main`, deploy ou produção.

## Estado atual e evidência

### Comprovado por código/documentação versionada

- `origin` é `https://github.com/mide-lim/megabrain.git`; `dev` e `main` são branches protegidas e a integração continua humana (`AGENTS.md`, D017 e `DEVELOPMENT_WORKFLOW.md`).
- O ruleset independente `require-ci` exige, em `dev` e `main`, os checks `Repository validation`, `Enricher tests` e `Web tests`, com política strict (`ACTIVE_TASK.md`).
- `.github/workflows/ci.yml` executa esses três jobs em PRs para `dev` e `main`.
- A fonte canônica B4.1 e sua instalação Hermes derivada possuem somente a operação de leitura `probe-read-dev`.
- A baseline da instalação GitHub App observada em B4.1 contém `contents: write`, `pull_requests: write`, `actions: read`, `statuses: read` e `workflows: write`, mas não `administration`.

### Comprovado pela operação B4.1 autorizada

- A App emitiu um token efêmero limitado ao repositório, usado em memória, revogado e limpo após a operação de leitura; não houve escrita.

### Ainda não comprovado

- Nenhuma escrita Git autenticada, criação/atualização de PR ou leitura autenticada de Actions foi exercitada pela capability B4.1.
- Não há evidência de uma ACL GitHub provider-enforced que conceda à App escrita apenas em `agent/*` e negue toda outra branch não protegida.
- Não foi feita consulta administrativa atual dos rulesets; fazê-la exigiria autoridade fora deste escopo.

## Fatos de provider relevantes

As GitHub Docs indicam que um installation token pode ser limitado a repositórios e permissões menores que a instalação, expira em até uma hora e não recebe permissão maior que a App. O token deve ser validado pela resposta antes do uso.

- Token escopado: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app
- Permissões de Actions para listar runs, jobs e baixar logs: https://docs.github.com/en/rest/actions/workflow-runs
- Regras disponíveis em rulesets: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- Permissões `Contents` para Git HTTPS e `Workflows` para `.github/workflows`: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app

Esses fatos sustentam token downscoped por operação. Eles não demonstram uma permissão de App positiva por prefixo de ref. Regras de branch restringem refs que elas atingem; não convertem uma validação local de `agent/*` em ACL do provider.

## Arquitetura proposta

### 1. Nova capability estreita, separada de B4.1

Criar posteriormente uma operação B4.2 explícita, em fonte canônica versionada e instalação local derivada. Ela não aceita shell, URL, remote, endpoint REST, ref, base ou opção Git arbitrários. B4.1 permanece read-only e não é ampliada implicitamente.

A interface recebe um Task Contract serializado e validado localmente, com valores imutáveis por lifecycle:

- repositório: exatamente `mide-lim/megabrain`;
- remote: exatamente `origin` com URL HTTPS fixa;
- branch: um nome exato `agent/<slug>` declarado no contrato;
- base: exatamente `dev`;
- PR: número e URL retornados pelo provider depois da criação;
- SHA de partida, conjunto permitido de caminhos, orçamento de tentativas e deadline;
- checks esperados: os três jobs atuais, até revisão humana do contrato.

O contrato é o gate de concessão: uma vez aprovado, as operações normais declaradas nele não pedem aprovação por comando. Uma alteração de contrato, escopo, branch, base, paths ou orçamento encerra o lifecycle e exige novo gate humano.

### 2. Tokens efêmeros e mínimos, por operação

Não reutilizar um token de escrita para observação. Cada token é limitado ao único repositório e revogado em `finally`; nenhuma credencial entra em arquivo, log, configuração Git, ambiente pai ou processo persistente.

| Operação estreita | Token solicitado | Uso permitido |
|---|---|---|
| `publish-agent-head` | `contents: write` | um `git push` não-forçado de HEAD para o ref exato `refs/heads/agent/<slug>` |
| `create-pr` / `update-pr-metadata` | `pull_requests: write` | criar ou editar somente o PR do contrato, com head exato e base `dev` |
| `observe-pr-ci` | `pull_requests: read`, `actions: read`, `statuses: read` | ler PR, run, job, status e logs do SHA exato |
| `refresh-agent-branch` | `contents: write` | somente publicar o resultado de um merge local não-forçado de `origin/dev` no head do contrato |

Antes de qualquer uso, a capability confere a resposta de mint: escopo exclusivo do repositório esperado, mapa de permissões igual ao solicitado mais `metadata: read` quando GitHub a retorna, e ausência de `administration`, `workflows`, `checks: write`, `actions: write` ou outra permissão inesperada. Se GitHub retornar um mapa diferente, falha fechada antes de Git/API de escrita.

A leitura de checks v1 usa Actions runs/jobs/logs e commit statuses. A instalação observada não comprovou `checks: read`; portanto o endpoint Checks API não é requisito nem fallback nesta versão. Logs são tratados como dados não confiáveis, processados apenas em memória, com saída sanitizada e sem executar instruções encontradas neles.

### 3. Publicação e PR presos a identidade esperada

Antes de cada publicação, exigir: árvore limpa exceto mudanças declaradas, HEAD exato, remote e URL exatos, branch local e destino iguais ao contrato, nenhum tag/ref protegido, upstream remoto em estado esperado, e push sem `--force`, `--mirror`, `--all`, delete, refspec curinga ou alteração de remote.

Antes de criar ou editar PR, exigir que o head remoto resolva para o SHA local. A mutation é limitada a `head=agent/<slug>`, `base=dev`, repositório esperado e um único PR aberto. Uma atualização de branch atualiza o mesmo PR por seu head; não cria PR duplicado. Título/corpo somente podem usar template e campos previstos no contrato.

### 4. Workflows fora da primeira versão

`.github/workflows/**` permanece sob gate humano separado. A capability v1 nega esse caminho tanto no diff quanto no commit a publicar e nunca solicita `workflows: write`. Isso reduz a possibilidade de uma automação de desenvolvimento mudar o mecanismo que produz a evidência que ela mesma aceita. Qualquer futura inclusão requer Task Contract próprio, revisão de segurança e decisão humana explícita.

### 5. Separação do plano de controle

A capability recusa publicar mudanças em: sua fonte canônica/instalação, `AGENTS.md`, `docs/RISK_POLICY.md`, `docs/DEFINITION_OF_DONE.md`, `docs/TASK_CONTRACT*.md`, políticas de CI, `.github/workflows/**` e caminhos de infraestrutura/produção definidos por `AGENTS.md`, salvo se houver contrato humano específico de manutenção do plano de controle. Essa negação local limita a autonomia normal; não é controle provider-enforced.

A proteção final contra a capability redefinir políticas continua composta por: sem merge automático, revisão humana do PR, rulesets de `dev`/`main` e ausência de Administration. Nenhuma automação normal recebe API administrativa, bypass, permissão de App/instalação ou API de workflow write.

## Controles: provider, local e governança

| Limite | Categoria | Evidência / observação |
|---|---|---|
| Token limitado ao repositório e às permissões solicitadas | Provider-enforced, verificado localmente | GitHub emite o token e retorna scope/permissões; a capability rejeita divergência |
| Bloqueio de atualização direta e merge em `dev`/`main` | Provider-enforced se os rulesets continuarem ativos, sem bypass da App | Documentado como estado atual; não foi reconsultado administrativamente nesta etapa |
| Required checks strict em `dev`/`main` | Provider-enforced se o ruleset permanecer ativo | Estado documental B3.2; `READY` local não substitui a decisão GitHub no merge |
| Permitir escrita somente em `agent/*` | Local capability control, não ACL do provider | O token `contents: write` pode alcançar refs não protegidos da instalação; validar prefixo local é defesa em profundidade |
| Remote, owner/repo, base, head, SHA, path denylist e não-force | Local capability control | Validado antes de mint e antes de cada mutação |
| Sem merge, auto-merge, Administration, rulesets, bypass, deploy ou produção | Duplo: ausência de operações locais + governança; parte provider-enforced pela ausência de permissões | Não presumir que uma ausência local sozinha resista a um comprometimento do host |
| Revisão de Task Contract, mudanças no plano de controle e decisão de merge | Governança/processo humano | Não é substituída por checklist ou validação local |

## Autonomia e máquina de estados

```text
CONTRACT_APPROVED
  -> PREFLIGHT
  -> LOCAL_COMMIT_READY
  -> PUBLISH_HEAD
  -> PR_OPEN_OR_VERIFIED
  -> OBSERVE_SHA
  -> GREEN_FOR_SHA = READY
     | CI_FAILURE -> DIAGNOSE -> LOCAL_FIX -> PUBLISH_HEAD (mesmo PR)
     | BEHIND -> SAFE_REFRESH -> PUBLISH_HEAD (mesmo PR)
     | timeout / drift / PR_closed / policy conflict -> STOP_NEEDS_HUMAN
```

`SAFE_REFRESH` faz fetch somente do remote fixo e, se expressamente permitido pelo contrato, `git merge --no-ff origin/dev` na branch do contrato. Nunca faz rebase, force-push ou resolução automática de conflito. Conflito, não-fast-forward remoto ou alteração inesperada da base encerra o lifecycle.

Para declarar `READY`, a capability lê de volta o PR e exige simultaneamente: estado aberto, head e base exatos, SHA do head igual ao SHA observado, base `dev`, checks esperados associados ao SHA/PR concluídos com sucesso e dentro do deadline. A cada push ou refresh, o SHA anterior fica inválido e a observação recomeça.

## Falhas e recuperação

- `BEHIND`: apenas merge não-forçado autorizado pelo contrato; em conflito, parar.
- `CI_FAILURE`: baixar logs apenas para memória, emitir diagnóstico sanitizado; a correção precisa respeitar paths e orçamento do contrato. Após novo commit, atualizar o mesmo PR e reiniciar observação.
- `CI_TIMEOUT`: parar ao deadline/limite de polls, sem re-run, cancelamento ou dispatch de workflow.
- `PR_CLOSED`, `MERGED`, head/base/owner/repo divergente, SHA remoto inesperado, PR duplicado ou remote alterado: parar antes de nova escrita.
- `token_mint`, permission, scope, revogação ou cleanup falho: resultado falho sanitizado; não reutilizar nem persistir token. Uma falha de revogação bloqueia novas operações na execução atual.
- Tentativas esgotadas, alteração de arquivos fora do contrato, workflow/infrastructure path, requisito de novo dependency/security/data scope: parar para novo Task Contract humano.

## Threat model simples

| Ameaça | Impacto | Controle proposto | Limitação residual |
|---|---|---|---|
| Token vaza em processo/log/Git config | escrita indevida até expiração | memória somente, child env mínimo, askpass temporário 0700, output sanitizado, revogação | host comprometido durante a janela continua fora do modelo |
| Bug/uso malicioso tenta ref ou remote diferente | alteração remota indevida | valores fechados, preflight duplo, refspec exato, sem force/delete | `agent/*` é controle local, não ACL do provider |
| PR é trocado, fechado ou muda de base/head | atualização do PR errado ou CI enganosa | PR fingerprint, leitura antes/depois, SHA/base/head exatos | corrida posterior à leitura exige decisão GitHub no merge |
| CI verde pertence a SHA/base errados | falso READY | correlação PR + SHA + event + jobs; invalidar em cada push | ruleset efetivo só é decidido pelo provider no merge |
| Log de CI contém segredo ou instrução hostil | vazamento/execução indevida | memória, redaction, parsing estruturado, nunca executar conteúdo do log | diagnóstico pode ser incompleto |
| Alterar workflow/política para fraudar CI | enfraquece controle | denylist `.github/workflows/**` e plano de controle; sem token workflow write | proteção de path é local; merge segue humano |
| Capability tenta mudar App/rulesets/bypass | escalada de privilégio | não há endpoint/operação/permissão administrativa | exige manter configuração da App sem Administration |
| CI nunca conclui ou falha repetidamente | loop/custo não limitado | orçamento por contrato, deadline e máximo de correções | demanda diagnóstico/decisão humana após limite |

## Recomendação

Aprovar somente uma implementação em duas fases:

1. Yellow de implementação local + testes herméticos, sem JWT, token, rede ou escrita autenticada.
2. Após revisão explícita do contrato e do código, uma autorização operacional separada, progressiva e limitada para a primeira operação real de leitura; escrita autenticada somente após evidência anterior e gate humano específico.

A primeira versão deve excluir `.github/workflows/**`, auto-merge, rebase/force-push, rerun/cancel/dispatch de CI, mudanças de plano de controle e qualquer ação de Administration ou produção.

## Questões/gates restantes

- O proprietário humano deve aceitar explicitamente que o prefixo `agent/*` é um limite local, não uma ACL do provider, ou decidir por um mecanismo provider-enforced adicional antes de autorizar escrita.
- O contrato operacional deve fixar owner/reviewer, paths permitidos, prazo, máximo de correções, política de logs e se `SAFE_REFRESH` é autorizado.
- A primeira escrita autenticada permanece Yellow e requer gate separado. Esta Discovery para antes desse passo.
