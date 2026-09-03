# B3.2 — Required Status Checks Functional Validation

## Status

COMPLETE / PROMOTED

## Objective

Registrar a evidência de validação funcional e strict do ruleset `require-ci`.

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

## Functional Validation Result

O Pull Request controlado #7 foi aberto de
`agent/b3-2-functional-validation` para `dev`. Enquanto `Enricher tests`
estava em execução, o Pull Request permaneceu bloqueado; `Repository
validation` e `Web tests` já estavam aprovados. Os três checks foram emitidos
pelo GitHub Actions integration ID `15368` e concluíram com sucesso.

Com o rollup de checks em sucesso, a restrição de CI foi satisfeita sem merge
automático. Hermes não executou merge nem recebeu autoridade administrativa,
de merge ou de produção.

## Strict Validation Result

Após a integração humana do PR #8 em `dev`, os checks verdes anteriores do PR
#7 permaneceram no head antigo `132ec5c…`, mas o PR passou ao estado `BEHIND`.
Isso comprovou que a política strict não aceita a evidência de CI baseada na
base anterior.

A branch do PR #7 foi rebased com segurança sobre `dev` em
`c04d1ac6c68a32fac51d50f8515619cf3b1d7a2b` e publicada com
`--force-with-lease`. O novo head `6e7cf77847935669580eb8fa186dd7083b801d4c`
recebeu três novos checks, todos concluídos com sucesso pelo GitHub Actions
integration ID `15368`. O rollup voltou a `SUCCESS` apenas contra a base atual.

O PR #7 foi integrado em `dev` por ação humana, no commit
`576845c8299e38150d8dea72bd383b3a60b9c5d0`.

## Rollback Availability

O rollback permanece disponível somente por ação humana explícita: alterar
`require-ci` de `active` para `disabled`, verificar a configuração por API e
confirmar que `protect-dev` e `protect-main` permanecem ativos. Não foi
necessário executar rollback, e Hermes não possui autorização para fazê-lo.
