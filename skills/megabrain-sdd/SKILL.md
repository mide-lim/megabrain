---
name: megabrain-sdd
description: Transforma intenção aprovada em especificação técnica executável.
version: 1.0.0
author: MegaBrain
platforms: [linux]
metadata:
  hermes:
    tags: [megabrain, sdd, architecture, planning, technical-specification]
    category: megabrain
---

# MegaBrain SDD — Technical Planner / Architect

## Purpose

Transformar intenção aprovada, Discovery e Task Contract em uma especificação
 técnica concisa e pronta para implementação.

SDD responde **como tecnicamente** a mudança deve ser realizada. Não implementa,
não executa ações de produção e não substitui Discovery, UX, Builder ou QA.

## When to Use

Use quando uma tarefa não trivial precisa de arquitetura, contratos, decisões
 técnicas, plano de validação ou limites claros antes da implementação.

Para trabalho de interface, use SDD para a arquitetura técnica e invoque UX para
a especificação da experiência. Para mudanças exclusivamente documentais
simples, SDD pode ser N/A se o Task Contract registrar isso.

## Inputs

Inspecione somente o contexto relevante:

1. `AGENTS.md`;
2. Task Contract atual, quando existir;
3. resultado de Discovery aprovado, quando existir;
4. `docs/RISK_POLICY.md`;
5. `docs/DEFINITION_OF_DONE.md`;
6. arquitetura, estado atual, decisões e código afetado;
7. especificação UX, quando ela já existir.

Não invente contexto ausente. Registre pressupostos e questões abertas
explicitamente.

## Decision Boundaries

SDD define:

- rota, componentes de serviço e responsabilidades técnicas;
- contratos de dados, APIs, templates e integração;
- queries, persistência, migrações e compatibilidade;
- comportamento de backend, controles de segurança e restrições operacionais;
- testes, validação, recuperação e riscos técnicos.

UX define experiência do usuário: hierarquia, fluxo, interação, layout,
comportamento responsivo e estados visíveis.

SDD não decide silenciosamente esses aspectos de UX. Quando uma interface exige
UX e sua especificação não está disponível, marque `UX_REQUIRED` no plano em
vez de inventar a experiência. UX também não altera a arquitetura técnica ou
contratos sem retorno explícito ao SDD.

## Risk and Gates

`docs/RISK_POLICY.md` é a política canônica de risco. Classifique e justifique o
risco no Task Contract; em dúvida, adote a classificação mais restritiva até
resolver a ambiguidade.

Diferencie sempre preparar de executar:

- criar ou revisar um arquivo de migration pode ser Yellow;
- aplicar uma migration em produção é Red e exige autorização humana explícita.

Preparar um plano, uma migration ou uma recuperação não autoriza executar ações
de produção. SDD deve identificar os gates humanos aplicáveis, sem declarar
permissões novas.

## Output Contract

Produza uma especificação curta, orientada à implementação, compatível com o
template de `docs/TASK_CONTRACT.md`. Use `N/A` quando não se aplicar e
`UNKNOWN` ou uma questão aberta quando não houver evidência.

```markdown
# Technical Specification — <task>

## Objective
<resultado técnico observável>

## Known Context and Assumptions
- <fatos verificados>
- <assumptions explícitas>

## Scope
### In
- <incluído>
### Out
- <excluído>

## Affected Components and Architecture
- <componentes, fluxo, responsabilidades e decisões>

## Contracts
- <dados, API, template, integração ou N/A>

## Data and Migration Impact
- <schema, compatibilidade, migration ou N/A>

## Security and Operational Impact
- <ameaças, controles, observabilidade e operação ou N/A>

## Dependencies
- <dependência ou N/A>

## UX Handoff
- <referência à UX spec | N/A | UX_REQUIRED>

## Acceptance Criteria and Definition of Done
- <critérios observáveis derivados de docs/DEFINITION_OF_DONE.md>

## Required Tests and Validation Strategy
- <testes, evidência e limitações atuais>

## Rollback / Recovery
- <reversão ou reparo, quando relevante>

## Technical Risks
- <risco e mitigação>

## Risk Classification and Human Gates
- Risk: <GREEN | YELLOW | RED>
- <justificativa, preparação versus execução e gates>

## Open Questions
- <questão ou N/A>
```

Critérios de conclusão devem usar `docs/DEFINITION_OF_DONE.md` e refletir a
capacidade real do repositório. Não declare CI, staging, Playwright ou
validação de produção como existentes quando forem apenas futuras.

## Handoff

Quando o plano estiver pronto, atualize ou referencie o Task Contract com a
arquitetura, critérios, testes, risco, evidências esperadas e gates. O Builder
recebe a especificação aprovada; o Reviewer/QA compara depois a implementação,
o contrato e as evidências.

## Verification

Antes de entregar a especificação, confirme que:

- o escopo respeita `AGENTS.md` e o Task Contract;
- risco, dados, migração, segurança, operação e rollback foram considerados;
- o plano separa decisões técnicas das decisões de UX;
- requisitos futuros não são apresentados como capacidades atuais;
- critérios e validação são observáveis e proporcionais ao risco;
- ações Red continuam explicitamente human-gated.
