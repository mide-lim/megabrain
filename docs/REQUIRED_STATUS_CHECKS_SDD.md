# B3.2 — Required Status Checks SDD

## Status

PROMOTED

## Objective

Transformar os três checks existentes da CI do MegaBrain em requisitos
obrigatórios para integração em `dev` e `main`, preservando o gate humano e
sem conceder novas permissões administrativas ao Hermes.

## Source Discovery

Este SDD implementa as decisões registradas em:

- `docs/REQUIRED_STATUS_CHECKS_DISCOVERY.md`

## Current Architecture

Rulesets de fluxo existentes:

- `protect-dev`
- `protect-main`

Eles continuam responsáveis por proteção de fluxo:

- Pull Request obrigatório;
- linear history;
- bloqueio de deleção;
- bloqueio de force push / non-fast-forward;
- gate humano existente.

Eles não foram modificados por B3.2.

## Target Architecture

Foi criado um terceiro ruleset independente:

`require-ci`

Escopo:

- `refs/heads/dev`
- `refs/heads/main`

Bypass:

- nenhum.

Regra:

- `required_status_checks`

Required checks:

1. `Repository validation`
2. `Enricher tests`
3. `Web tests`

Expected source:

- GitHub Actions
- integration ID: `15368`

Policy:

- `strict_required_status_checks_policy = true`

## Separation of Responsibilities

### protect-dev / protect-main

Responsáveis por:

- fluxo de Pull Request;
- histórico linear;
- proteção contra deleção;
- proteção contra force push;
- gate humano.

### require-ci

Responsável exclusivamente por:

- garantir presença dos três checks;
- garantir sucesso dos três checks;
- aceitar somente checks emitidos pelo GitHub Actions;
- exigir validação contra a versão atual da branch alvo.

Nenhum bypass foi configurado neste ruleset, conforme revisão administrativa
externa e Task Contract.

## Execution Result

O `require-ci` foi criado inicialmente desabilitado e ativado somente após gate
humano administrativo. A API confirmou os targets, os três checks, o GitHub
Actions integration ID `15368` e a strict policy. Um Pull Request controlado
comprovou o bloqueio com checks pendentes e o sucesso dos três checks. A
validação strict comprovou que checks verdes contra uma base anterior deixam de
satisfazer a regra depois que `dev` avança e que uma nova CI contra a base atual
é exigida.

## Initial REST Representation

Representação técnica usada para a criação inicial desabilitada:

```json
{
  "name": "require-ci",
  "target": "branch",
  "enforcement": "disabled",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": [
        "refs/heads/dev",
        "refs/heads/main"
      ],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "required_status_checks": [
          {
            "context": "Repository validation",
            "integration_id": 15368
          },
          {
            "context": "Enricher tests",
            "integration_id": 15368
          },
          {
            "context": "Web tests",
            "integration_id": 15368
          }
        ],
        "strict_required_status_checks_policy": true
      }
    }
  ]
}
```

Este payload é documentação de arquitetura.

Hermes não executará chamadas administrativas de criação ou alteração de
rulesets.

## Activation Strategy

A implantação será dividida em gates independentes.

### Gate 1 — Documentation

- concluir Discovery;
- concluir SDD;
- criar Task Contract;
- revisar evidência;
- publicar por `agent/*`;
- CI;
- Pull Request;
- integração humana em `dev`.

Nenhuma configuração GitHub é alterada.

### Gate 2 — Disabled Ruleset

Ação humana administrativa:

- criar `require-ci`;
- enforcement inicial: `disabled`;
- confirmar targets;
- confirmar ausência de bypass;
- confirmar três contexts;
- confirmar integration ID;
- confirmar strict policy.

Depois da criação, Hermes apenas observa a configuração via API.

### Gate 3 — Pre-activation Verification

Confirmar que:

- `protect-dev` permanece inalterado;
- `protect-main` permanece inalterado;
- `require-ci` está `disabled`;
- os três checks continuam sendo emitidos normalmente;
- nenhum permission scope novo foi concedido ao Hermes.

### Gate 4 — Activation

Ação humana administrativa:

- alterar somente `require-ci` de `disabled` para `active`.

Nenhum outro ruleset será alterado.

### Gate 5 — Functional Validation

Criar Pull Request controlado de `agent/*` para `dev`.

Verificar:

1. PR aparece bloqueado enquanto checks estão pendentes;
2. os três jobs executam;
3. todos os três precisam ficar verdes;
4. após sucesso, o required CI deixa de bloquear o PR;
5. Hermes continua incapaz de fazer merge;
6. integração continua dependente de decisão humana.

## Strict Mode Validation

Além da validação normal, será realizado um teste controlado para confirmar a
política strict.

Objetivo:

demonstrar que uma evidência de CI referente a uma base antiga não é suficiente
quando `dev` avançar.

O teste será planejado separadamente antes da execução para evitar commits
artificiais ou alterações desnecessárias em `dev`.

A configuração API do strict mode será verificada antes desse teste.

## Rollback

Se `require-ci` bloquear incorretamente o fluxo:

1. responsável humano altera somente `require-ci` para `disabled`;
2. confirmar por API que o ruleset está desabilitado;
3. confirmar que `protect-dev` permanece ativo;
4. confirmar que `protect-main` permanece ativo;
5. interromper B3.2;
6. investigar causa;
7. nenhuma nova ativação sem novo gate humano.

Não remover ou enfraquecer `protect-dev` ou `protect-main` como mecanismo de
rollback.

## Security Boundary

Hermes:

- não recebe `Administration: write`;
- não cria rulesets;
- não altera rulesets;
- não desabilita rulesets;
- não remove rulesets;
- não recebe bypass;
- não faz merge em `dev`;
- não faz merge em `main`.

A GitHub App do Hermes continua limitada ao fluxo de desenvolvimento já
estabelecido.

## Acceptance Criteria

B3.2 somente poderá ser considerado concluído quando:

- Discovery estiver versionado;
- SDD estiver versionado;
- Task Contract estiver versionado;
- `require-ci` existir;
- `require-ci` não possuir bypass;
- `dev` estiver no escopo;
- `main` estiver no escopo;
- os três checks estiverem configurados;
- integration ID `15368` estiver fixado;
- strict policy estiver habilitada;
- os três checks forem obrigatórios em PR real;
- PR não puder integrar enquanto checks estiverem pendentes ou falhos;
- CI verde liberar somente a restrição de CI;
- gate humano de merge continuar existindo;
- Hermes continuar sem autoridade de merge ou administração;
- rollback estiver comprovadamente disponível.

## Out of Scope

B3.2 não inclui:

- staging;
- Playwright;
- auto-merge;
- deploy;
- promoção `dev -> main`;
- alteração de produção;
- alteração de Caddy;
- alteração de Docker;
- alteração de secrets;
- alteração de permissões do Hermes;
- mudança no workflow CI além do que for estritamente necessário para corrigir
  um problema descoberto durante a validação.

## Risk

Documentação e planejamento:

- GREEN.

Criação do ruleset desabilitado:

- HUMAN GATE administrativo.

Ativação ou alteração de branch enforcement:

- RED / explicit human approval.

Rollback:

- RED / explicit human approval.
