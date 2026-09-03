# B3.2 — Required Status Checks Discovery

## Status

DISCOVERY

## Objective

Definir uma arquitetura segura para tornar os checks da CI obrigatórios antes
da integração em branches protegidas, sem permitir que o bypass humano dos
rulesets atuais ignore silenciosamente a validação automatizada.

## Current State

O MegaBrain possui dois rulesets ativos:

- `protect-dev`
- `protect-main`

Eles protegem as branches com regras como:

- Pull Request obrigatório;
- bloqueio de deleção;
- bloqueio de non-fast-forward / force push;
- linear history;
- restrição de atualização.

Os dois rulesets possuem um bypass de `RepositoryRole` configurado como
`pull_request`.

Esse modelo preserva o gate humano e o audit trail do Pull Request, mas o ator
autorizado ainda pode escolher usar o bypass sobre as regras daquele ruleset.

## CI Available

O workflow `CI` executa em Pull Requests para `dev` e `main`.

Os jobs atuais são:

- `Repository validation`
- `Enricher tests`
- `Web tests`

Todos já foram validados em execuções reais do GitHub Actions durante B3.1.

## Risk Identified

Adicionar `required_status_checks` diretamente aos rulesets atuais criaria uma
ambiguidade de governança:

o mesmo ator autorizado a usar o bypass do ruleset poderia potencialmente
ignorar também os required checks definidos naquele ruleset.

Isso reduziria a garantia de que CI verde é realmente obrigatória antes do
merge.

## Proposed Architecture

Separar proteção de fluxo e proteção de CI em rulesets diferentes.

### Existing rulesets

`protect-dev` e `protect-main` continuam responsáveis por:

- Pull Request obrigatório;
- linear history;
- bloqueio de force push;
- bloqueio de deleção;
- gate humano via bypass de Pull Request.

### New CI ruleset

Criar posteriormente um ruleset independente para required status checks.

Características propostas:

- nenhum bypass actor;
- exigir:
  - `Repository validation`;
  - `Enricher tests`;
  - `Web tests`;
- `strict_required_status_checks_policy = true`;
- nenhuma mudança em produção;
- nenhuma mudança de credenciais;
- nenhuma capacidade adicional para Hermes.

Com múltiplos rulesets aplicáveis, as regras são agregadas.

Assim, mesmo que o responsável humano utilize o bypass permitido nos rulesets
de fluxo, o ruleset independente de CI continua aplicável.

## Strict vs Loose

Proposta inicial: `strict`.

Motivos:

- garante validação contra a versão atual da branch alvo;
- reduz risco de merge baseado em evidência de CI desatualizada;
- o conjunto atual de testes é pequeno;
- o custo de reexecução é aceitável neste estágio do projeto.

## Required Check Names

Os contexts esperados são os nomes dos jobs:

- `Repository validation`
- `Enricher tests`
- `Web tests`

## Resolved Validation

### REST shape

O novo ruleset utilizará a regra `required_status_checks`.

Parâmetros planejados:

- `required_status_checks`;
- `strict_required_status_checks_policy = true`;
- contexts fixados aos três jobs atuais da CI.

### Check source

Os checks reais do repositório são produzidos pelo GitHub App
`github-actions`.

Integration ID confirmado: `15368`.

Os required checks deverão fixar `integration_id = 15368` para que somente
checks produzidos pelo GitHub Actions satisfaçam a regra.

### Ruleset scope

Será utilizado inicialmente um único ruleset `require-ci` cobrindo:

- `refs/heads/dev`;
- `refs/heads/main`.

A política é atualmente idêntica para as duas branches e o workflow `CI`
executa para Pull Requests destinados a ambas.

Se as políticas divergirem futuramente, o ruleset poderá ser separado.

### Strict policy

`strict_required_status_checks_policy = true`.

A validação funcional do strict mode será feita posteriormente com Pull Request
real antes de considerar B3.2 concluído.

## Activation and Rollback

A ativação do ruleset será um gate humano separado.

Hermes não receberá permissão administrativa para criar, alterar, desabilitar
ou remover rulesets.

Os rulesets atuais `protect-dev` e `protect-main` não serão modificados durante
a introdução do required CI.

Rollback planejado:

1. desabilitar somente o novo ruleset `require-ci`;
2. confirmar que `protect-dev` e `protect-main` permanecem ativos e inalterados;
3. investigar a falha antes de qualquer nova ativação.

Nenhum bypass actor será configurado no `require-ci`.

## Out of Scope

Este discovery não:

- altera rulesets;
- altera branch protection;
- altera GitHub App permissions;
- altera workflows;
- promove `dev` para `main`;
- executa deploy;
- modifica produção.
