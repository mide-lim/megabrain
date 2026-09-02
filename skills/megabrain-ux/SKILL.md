---
name: megabrain-ux
description: Converte intenção de produto em especificação de UX implementável.
version: 1.0.0
author: MegaBrain
platforms: [linux]
metadata:
  hermes:
    tags: [megabrain, ux, product-design, web, accessibility]
    category: megabrain
---

# MegaBrain UX / Product Design

## Purpose

Traduzir intenção de produto em uma especificação de experiência objetiva e
pronta para implementação, preservando as convenções existentes do MegaBrain.

Esta skill não gera arte, não implementa frontend ou CSS, não substitui
Discovery nem SDD e não define arquitetura técnica.

## When to Use

Invoque quando o trabalho criar ou alterar páginas, telas, navegação, fluxos,
formulários, interações, componentes, comportamento responsivo, hierarquia de
informação ou estados visíveis ao usuário.

Normalmente não é necessária para mudanças somente de backend, banco,
infraestrutura, refactors internos ou documentação.

## Inputs

Inspecione, quando disponíveis e relevantes:

1. Task Contract;
2. resultado de Discovery;
3. restrições técnicas fornecidas por SDD;
4. `docs/UI_SYSTEM.md`;
5. templates, estilos, componentes e comportamento atual relacionados;
6. decisões e estado atual do produto.

Reutilize os padrões existentes antes de propor um componente novo. Não altere
convenções atuais sem exigência explícita da tarefa.

## Decision Boundaries

UX decide a experiência: objetivo do usuário, fluxo, hierarquia, layout,
interação, microcopy, estados e comportamento responsivo.

SDD decide arquitetura técnica: rota, query, contrato de dados, backend,
segurança e restrições operacionais. Se uma restrição técnica necessária estiver
indefinida, registre-a para SDD em vez de inventar uma solução. UX não redefine
contratos ou arquitetura silenciosamente.

## Output Contract

Produza somente as seções relevantes, mas trate todos os estados aplicáveis.
Use wireframes textuais/ASCII quando esclarecer a decisão; não exija geração de
imagem.

```markdown
# UX Specification — <task>

## User Goal
<o que a pessoa precisa alcançar>

## User Flow
<entrada -> ações -> resultado -> caminho de volta/escape>

## Information Hierarchy
- Primary: <informação ou ação>
- Secondary: <informação ou ação>
- Optional: <informação ou ação>

## Layout Intent
<wireframe textual, regiões e ordem de leitura>

## Components
- Reuse: <padrões existentes>
- New: <somente quando necessário, com justificativa>

## Interaction and Keyboard Behavior
- <cliques, formulários, navegação, feedback e teclado>

## States
- Default: <comportamento>
- Loading: <comportamento ou N/A>
- Empty: <comportamento ou N/A>
- Error: <comportamento ou N/A>
- Success: <comportamento ou N/A>
- Disabled: <comportamento ou N/A>

## Responsive Behavior
- Mobile: <prioridades e adaptação>
- Desktop: <prioridades e adaptação>
- Tablet: <somente se materialmente distinto>

## Accessibility Baseline
- <estrutura semântica, labels, foco, teclado, headings, contraste e erros>

## Content / Microcopy
- <rótulos ou mensagens relevantes>

## UX Acceptance Criteria
- <critérios observáveis>

## QA Notes
- E2E: <verificação futura, quando aplicável>
- Screenshot / responsive: <verificação futura, quando aplicável>
- Accessibility: <verificação futura, quando aplicável>

## Questions for SDD
- <restrição ou N/A>
```

Não use requisitos subjetivos como “moderno”, “bonito” ou “profissional” sem
traduzi-los em critérios observáveis. Prefira clareza à decoração, viabilidade
mobile a suposições desktop-only, HTML semântico a interação customizada e
especificação determinística a julgamentos estéticos vagos.

## Current Capability Boundary

Requisitos de acessibilidade e responsividade podem ser definidos antes de haver
automação. Não declare validação automatizada de acessibilidade, Playwright,
E2E, screenshots ou regressão visual como existentes; registre-os como QA futuro
quando apropriado.

## Handoff and Verification

Entregue a especificação ao SDD/Task Contract para compatibilização técnica e ao
Builder para implementação aprovada. Antes de concluir, verifique que:

- cada decisão respeita `docs/UI_SYSTEM.md` ou identifica uma inconsistência
  existente;
- componentes existentes foram considerados antes de novos;
- mobile e desktop foram considerados;
- estados, navegação por teclado, foco, labels e mensagens de erro foram
  considerados quando aplicáveis;
- critérios são observáveis;
- nenhuma decisão de arquitetura foi assumida sem SDD.
