# Task Contract — B3.2: Required Status Checks

## Status

- Status: PROMOTED
- Overall Execution Risk: RED
- Documentation Risk: GREEN

## Objective

Tornar os três checks existentes da CI do MegaBrain obrigatórios antes da
integração em `dev` e `main`, sem permitir que o bypass humano dos rulesets de
fluxo ignore a validação automatizada.

A implementação deve preservar:

- Pull Request como caminho de integração;
- decisão humana de merge;
- isolamento do Hermes;
- ausência de acesso administrativo do Hermes;
- ausência de mudanças em produção.

## Source Documents

Este contrato é baseado em:

- `docs/REQUIRED_STATUS_CHECKS_DISCOVERY.md`
- `docs/REQUIRED_STATUS_CHECKS_SDD.md`

## User / Engineering Context

B3.1 estabeleceu a primeira CI do MegaBrain em GitHub Actions.

Os Pull Requests destinados a `dev` e `main` executam atualmente:

1. `Repository validation`
2. `Enricher tests`
3. `Web tests`

Os checks já foram validados em execuções reais.

O ruleset independente `require-ci` torna esses checks obrigatórios antes da
integração em `dev` e `main`.

Os rulesets atuais:

- `protect-dev`
- `protect-main`

possuem bypass humano configurado no modo Pull Request.

B3.2 separa a proteção de CI da proteção de fluxo.

## Target State

Existem três rulesets com responsabilidades independentes:

### protect-dev

Permanece responsável pela proteção de fluxo de `dev`.

### protect-main

Permanece responsável pela proteção de fluxo de `main`.

### require-ci

Ruleset ativo responsável exclusivamente pelos required status checks.

Targets:

- `refs/heads/dev`
- `refs/heads/main`

Bypass:

- nenhum.

Required checks:

- `Repository validation`
- `Enricher tests`
- `Web tests`

Check provider:

- GitHub Actions
- integration ID `15368`

Policy:

- `strict_required_status_checks_policy = true`

## Scope

### In

- documentar a configuração final do ruleset `require-ci`;
- criar o ruleset inicialmente como `disabled`;
- não configurar bypass actors;
- limitar o ruleset a `dev` e `main`;
- configurar os três checks existentes;
- fixar `integration_id = 15368`;
- configurar strict policy;
- verificar a configuração por API após criação;
- verificar que `protect-dev` não mudou;
- verificar que `protect-main` não mudou;
- ativar `require-ci` somente após gate humano explícito;
- validar o comportamento usando Pull Request real;
- confirmar que checks pendentes ou falhos bloqueiam integração;
- confirmar que CI verde libera somente a restrição de CI;
- confirmar que o gate humano continua existindo;
- manter rollback previamente definido.

### Out

- alterar o workflow CI sem necessidade comprovada;
- staging;
- Playwright;
- auto-merge;
- deploy;
- promoção de `dev` para `main`;
- mudança em produção;
- mudança de Caddy;
- mudança de Docker;
- mudança de PostgreSQL;
- mudança de R2;
- mudança de Google Speech-to-Text;
- secrets;
- credenciais;
- mudança de permissões da GitHub App do Hermes;
- conceder `Administration: write` ao Hermes;
- remover proteções existentes;
- enfraquecer `protect-dev`;
- enfraquecer `protect-main`.

## Contracts Changed

B3.2 altera somente o contrato operacional de integração GitHub.

Antes:

CI produz evidência automática, mas não possui ruleset independente que torne
os três checks obrigatórios.

Depois:

um ruleset independente `require-ci` exige os três checks antes da integração
em branches protegidas.

Nenhum contrato de produto, API, banco ou runtime é alterado.

## Data / Migration Impact

N/A.

Nenhuma migration será criada ou executada.

## Production Impact

Nenhum.

B3.2 não acessa nem modifica a infraestrutura de produção.

## Security Impact

A mudança aumenta a proteção do fluxo de desenvolvimento.

Garantias obrigatórias:

- `require-ci` sem bypass;
- checks vinculados ao GitHub Actions;
- Hermes sem administração do repositório;
- Hermes sem autoridade de merge;
- Hermes sem acesso a produção;
- nenhum secret novo;
- nenhuma credencial nova;
- nenhum self-hosted runner;
- nenhuma exposição de Docker socket.

## GitHub Administration Boundary

Hermes pode:

- trabalhar em `agent/*`;
- criar commits de desenvolvimento;
- publicar sua branch conforme o fluxo já autorizado;
- abrir Pull Requests;
- observar configurações públicas/acessíveis por API;
- coletar evidência.

Hermes não pode:

- criar rulesets administrativamente;
- alterar rulesets;
- ativar rulesets;
- desativar rulesets;
- remover rulesets;
- conceder bypass;
- fazer merge em `dev`;
- fazer merge em `main`.

Qualquer ação administrativa de ruleset pertence ao responsável humano.

## Implementation Plan

### Phase 1 — Documentation

- Discovery versionado;
- SDD versionado;
- Task Contract versionado;
- atualização de `ACTIVE_TASK`;
- revisão;
- CI;
- Pull Request;
- merge humano para `dev`.

Resultado:

nenhuma configuração real alterada.

### Phase 2 — Create Disabled Ruleset

Gate humano administrativo.

Criar:

`require-ci`

Estado inicial:

`disabled`

Configuração esperada:

- target `branch`;
- include `refs/heads/dev`;
- include `refs/heads/main`;
- zero bypass actors;
- três required checks;
- integration ID `15368`;
- strict policy habilitada.

Após a ação humana, Hermes apenas coleta evidência.

### Phase 3 — Pre-activation Verification

Verificar por API:

- `require-ci` existe;
- enforcement está `disabled`;
- targets estão corretos;
- bypass está vazio;
- contexts estão corretos;
- integration IDs estão corretos;
- strict policy está correta;
- `protect-dev` permanece ativo e inalterado;
- `protect-main` permanece ativo e inalterado.

Qualquer divergência interrompe a tarefa.

### Phase 4 — Activation

Gate RED com aprovação humana explícita.

Alteração permitida:

`require-ci: disabled -> active`

Nenhuma outra configuração deve mudar.

### Phase 5 — Functional Validation

Criar Pull Request controlado de `agent/*` para `dev`.

Validar:

- CI inicia normalmente;
- merge permanece indisponível enquanto required checks não forem satisfeitos;
- os três checks aparecem;
- cada check precisa concluir com sucesso;
- CI verde satisfaz o ruleset de CI;
- gate humano continua necessário;
- Hermes continua incapaz de integrar o PR.

### Phase 6 — Strict Validation

Executar teste controlado da política strict.

O teste específico deverá ser preparado antes da execução para evitar alterações
artificiais desnecessárias em `dev`.

Objetivo:

confirmar que evidência de CI referente a uma base desatualizada não satisfaz
automaticamente a política quando a branch alvo avançar.

### Phase 7 — Closeout

Registrar:

- configuração final;
- evidência da API;
- evidência do Pull Request;
- resultado dos checks;
- comportamento do gate humano;
- resultado do strict mode;
- disponibilidade do rollback.

B3.2 foi marcado como COMPLETE / PROMOTED após o registro desta evidência.

## Closeout Evidence

- `require-ci` (ID `22210670`) está ativo para `refs/heads/dev` e
  `refs/heads/main`;
- os contexts `Repository validation`, `Enricher tests` e `Web tests` estão
  vinculados ao GitHub Actions integration ID `15368`;
- `strict_required_status_checks_policy = true` foi comprovada: checks verdes
  sobre a base anterior do PR #7 resultaram em estado `BEHIND` depois que `dev`
  avançou, e uma nova CI contra a base atual foi exigida e aprovada;
- o PR #7 permaneceu sem merge automático e foi integrado somente por ação
  humana;
- `protect-dev` e `protect-main` permaneceram inalterados;
- Hermes permaneceu sem autoridade administrativa, de merge ou de produção;
- rollback continua disponível mediante ação humana explícita que altere somente
  `require-ci` de `active` para `disabled`.

## Required Evidence

### Before activation

- snapshot de `protect-dev`;
- snapshot de `protect-main`;
- snapshot de `require-ci`;
- confirmação de enforcement `disabled`;
- confirmação de zero bypass actors;
- confirmação dos targets;
- confirmação dos três contexts;
- confirmação de integration ID `15368`;
- confirmação de strict policy.

### After activation

- snapshot de `require-ci` como `active`;
- confirmação de que os outros rulesets não mudaram.

### Functional

- Pull Request controlado;
- três checks identificados;
- evidência de estado pendente;
- evidência de sucesso;
- confirmação de enforcement;
- confirmação de que Hermes continua sem merge authority.

## Acceptance Criteria

B3.2 foi concluído; os critérios abaixo foram verificados:

- Discovery estiver integrado;
- SDD estiver integrado;
- Task Contract estiver integrado;
- `require-ci` existir;
- `require-ci` estiver ativo;
- `require-ci` não possuir bypass;
- `dev` estiver coberto;
- `main` estiver coberto;
- `Repository validation` for obrigatório;
- `Enricher tests` for obrigatório;
- `Web tests` for obrigatório;
- os três checks estiverem vinculados ao integration ID `15368`;
- strict policy estiver habilitada;
- PR real demonstrar bloqueio enquanto checks não forem satisfeitos;
- PR real demonstrar liberação da restrição de CI após sucesso;
- gate humano continuar existindo;
- Hermes continuar sem autoridade administrativa ou de merge;
- `protect-dev` permanecer inalterado;
- `protect-main` permanecer inalterado;
- rollback estiver disponível;
- evidência final estiver registrada.

## Failure Conditions

Interromper a execução se:

- um context esperado não existir;
- integration ID não corresponder ao GitHub Actions;
- ruleset apresentar bypass inesperado;
- target incluir branch não planejada;
- `protect-dev` sofrer alteração não planejada;
- `protect-main` sofrer alteração não planejada;
- Hermes ganhar permissão administrativa;
- required checks puderem ser ignorados pelo Hermes;
- merge puder ocorrer com check pendente ou falho;
- rollback não puder ser executado de forma independente.

## Rollback

Rollback é ação RED e requer aprovação humana explícita.

Se necessário:

1. alterar somente `require-ci` de `active` para `disabled`;
2. verificar por API o novo estado;
3. confirmar `protect-dev` ativo;
4. confirmar `protect-main` ativo;
5. interromper qualquer tentativa de integração relacionada ao teste;
6. registrar a causa;
7. investigar antes de nova ativação.

Não usar como rollback:

- remoção de `protect-dev`;
- remoção de `protect-main`;
- concessão de bypass ao Hermes;
- push direto;
- desativação geral das proteções do repositório.

## Risk Classification

### GREEN

- documentação;
- análise;
- leitura de API;
- coleta de evidência;
- criação de branches `agent/*`;
- testes locais;
- revisão.

### HUMAN ADMINISTRATIVE GATE

- criação inicial de `require-ci` como `disabled`.

### RED

- ativar `require-ci`;
- alterar enforcement;
- alterar required checks após ativação;
- alterar targets após ativação;
- executar rollback;
- qualquer mudança nos rulesets existentes.

## Definition of Done

B3.2 está DONE:

- documentação estiver integrada em `dev`;
- ruleset estiver configurado conforme especificação;
- required checks funcionarem em PR real;
- strict policy estiver comprovada;
- boundary de segurança estiver preservada;
- gate humano estiver preservado;
- rollback estiver documentado e disponível;
- evidência final estiver registrada;
- nenhuma alteração de produção tiver ocorrido.

## Current Execution Boundary

B3.2 está `COMPLETE / PROMOTED`. Nenhuma permissão foi alterada e Hermes
continua autorizado somente a publicar `agent/*`, abrir Pull Requests e coletar
evidência. Qualquer alteração futura de ruleset, incluindo rollback, continua
dependente de gate humano explícito. Merge, deploy e produção permanecem fora da
autoridade do Hermes.
