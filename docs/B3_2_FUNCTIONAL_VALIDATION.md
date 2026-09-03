# B3.2 — Required Status Checks Functional Validation

## Status

VALIDATION_IN_PROGRESS

## Objective

Registrar o protocolo de validação funcional do ruleset `require-ci` antes da
integração de uma mudança em `dev`.

## Configuration Under Test

A configuração observada por API antes deste Pull Request é:

- ruleset: `require-ci` (ID `22210670`);
- enforcement: `active`;
- targets:
  - `refs/heads/dev`;
  - `refs/heads/main`;
- bypass actors: nenhum, conforme revisão administrativa externa;
- required status checks:
  - `Repository validation` — GitHub Actions integration ID `15368`;
  - `Enricher tests` — GitHub Actions integration ID `15368`;
  - `Web tests` — GitHub Actions integration ID `15368`;
- `strict_required_status_checks_policy = true`.

`protect-dev` e `protect-main` não fazem parte desta alteração nem devem ser
alterados durante a validação.

## Controlled Pull Request Protocol

Este documento é apresentado por um Pull Request controlado de
`agent/b3-2-functional-validation` para `dev`.

A validação deve coletar evidência de que:

1. o Pull Request recebe os três checks requeridos;
2. a integração fica bloqueada enquanto ao menos um check está pendente ou em
   execução;
3. os três checks precisam concluir com sucesso;
4. o sucesso da CI satisfaz somente a restrição de CI;
5. o Pull Request não é integrado automaticamente;
6. Hermes não executa merge nem altera rulesets.

## Strict Validation Boundary

A validação strict exige uma execução de CI baseada em uma versão anterior de
`dev`, seguida do avanço controlado dessa branch por uma ação humana
independente. Esse teste não deve criar commits artificiais em `dev` e só será
executado depois de um plano específico e de gate humano aplicável.
