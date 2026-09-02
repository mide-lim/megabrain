# Task Contract

O Task Contract é o registro operacional de uma tarefa de engenharia. Ele conecta intenção, escopo, risco, especificação, evidência e gates humanos, permitindo que os papéis trabalhem com uma definição comum de pronto.

O contrato deve ser criado ou atualizado antes de implementação que não seja trivial. Ele deve refletir o estado real: campos não aplicáveis podem ser marcados como `N/A`, e questões não resolvidas devem permanecer explícitas.

## Estados

Os estados disponíveis são:

- `DISCOVERY`
- `SPEC_READY`
- `IMPLEMENTING`
- `VALIDATING`
- `QA`
- `STAGING`
- `READY`
- `HUMAN_GATE`
- `PROMOTED`
- `BLOCKED`

Nem toda tarefa usa todos os estados. Trabalho Green somente documental, por exemplo, não exige `STAGING`. Uma tarefa pode ir diretamente de `VALIDATING` para `READY` quando não há revisão adicional exigida pelo contrato, mas não pode ignorar um gate humano aplicável.

## Template reutilizável

```markdown
# Task Contract — <ID>: <Title>

## Status

- Status: <DISCOVERY | SPEC_READY | IMPLEMENTING | VALIDATING | QA | STAGING | READY | HUMAN_GATE | PROMOTED | BLOCKED>
- Risk Level: <GREEN | YELLOW | RED>

## Objective

<Resultado que a tarefa deve alcançar.>

## User / Product Context

<Problema, necessidade e prioridade.>

## Scope

### In

- <Item incluído>

### Out

- <Item explicitamente excluído>

## Acceptance Criteria

- <Critério verificável>

## Architecture / Technical Plan

<Abordagem, componentes e decisões técnicas.>

## UX Specification Reference

<Referência ou N/A.>

## Contracts Changed

<APIs, interfaces, templates, comportamento ou N/A.>

## Data / Migration Impact

<Impacto, migration, compatibilidade ou N/A.>

## Security Impact

<Impacto, ameaças e controles ou N/A.>

## Expected Files / Components

- `<path ou componente>`

## Required Tests

- <Teste ou validação necessária>

## Required Evidence

- <Comando, resultado, diff ou evidência esperada>

## Staging Requirements

<Requisito de staging, quando disponível, ou N/A.>

## Production Impact

<Impacto e classificação; execução em produção é Red.>

## Rollback / Recovery

<Como reverter ou reparar, quando relevante.>

## Human Gates

<Quem deve aprovar e antes de qual ação.>

## Dependencies

- <Dependência ou N/A>

## Open Questions

- <Questão em aberto ou N/A>

## Final Evidence Summary

<Evidência realmente coletada, limitações e decisão de DoD.>
```

O `Final Evidence Summary` registra o que foi efetivamente validado, não o que se espera validar no futuro. O estado `PROMOTED` não implica execução em produção; para trabalho Red, a execução depende da autorização humana explícita.