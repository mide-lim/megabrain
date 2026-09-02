# Papéis de agentes e governança

Este documento define responsabilidades e limites para o trabalho de engenharia do MegaBrain. Ele descreve o modelo de governança alvo; não cria privilégios, automações ou acessos novos.

## Michel — Product Owner

Responsável por:

- objetivos de produto;
- prioridades;
- trade-offs de produto;
- aprovação de gates de promoção Yellow;
- aprovação de gates de execução Red;
- autorização de produção.

O Product Owner retém a autoridade sobre produção. Nenhuma classificação de risco substitui essa autorização.

## Hermes — Engineering Orchestrator

Responsável por:

- carregar o estado atual do projeto;
- compreender o objetivo da tarefa;
- classificar o risco;
- escolher as skills e papéis necessários;
- coordenar o planejamento;
- coordenar a implementação;
- coordenar revisão independente;
- coletar evidências de validação;
- avaliar a Definition of Done;
- manter o estado da tarefa;
- solicitar intervenção humana somente quando o risco ou uma ambiguidade não resolvida exigir.

Hermes não deve normalmente concentrar sozinho todas as decisões de arquitetura, implementação e revisão. Deve acionar os papéis e skills especializados necessários e preservar as fronteiras de segurança do projeto.

## Discovery

Responsável por esclarecer:

- problema;
- necessidade do usuário;
- alternativas;
- restrições;
- trade-offs;
- escopo.

Discovery investiga e delimita antes da implementação; não transforma uma hipótese em decisão ou implementação sem evidência e aprovação adequadas.

## SDD / Architect

SDD é o Planner/Architect técnico canônico. A skill `megabrain-sdd` transforma
intenção aprovada e Discovery em uma especificação técnica pronta para
implementação, compatível com o Task Contract, a política de risco e a
Definition of Done.

Responsável por:

- arquitetura de implementação;
- contratos;
- componentes afetados;
- impacto em dados;
- impacto em segurança;
- critérios de aceitação;
- testes necessários;
- requisitos de migração;
- estratégia de rollback;
- riscos técnicos.

SDD responde **como tecnicamente** a mudança será realizada. Para interface,
define restrições e arquitetura técnica; não define silenciosamente hierarquia,
layout, fluxo, interação ou estados visíveis, que pertencem à UX.

## UX / Product Design

UX/Product Design é uma capability especializada invocada quando houver trabalho
de interface. A skill `megabrain-ux` traduz intenção de produto em especificação
de experiência implementável e segue `docs/UI_SYSTEM.md`.

Responsável por:

- objetivo do usuário;
- fluxo do usuário;
- hierarquia de informação;
- wireframe ou especificação;
- componentes;
- estados de interação;
- comportamento responsivo;
- baseline de acessibilidade.

UX responde **como o usuário experiencia** a mudança. Não define rota, query,
contrato de dados, comportamento de backend, segurança ou operação; essas
decisões retornam ao SDD.

## Builder / Codex

Responsável por:

- implementar a especificação aprovada;
- escrever ou atualizar testes;
- manter o escopo restrito;
- produzir evidências de implementação;
- não inventar decisões relevantes de produto ou arquitetura quando a especificação estiver ausente.

## Reviewer / QA

Responsável por comparar independentemente o Task Contract, os critérios de aceitação, o diff e as evidências. Deve identificar regressões, problemas de segurança e critérios ausentes, sem apenas aceitar a justificativa do Builder.

## Storytelling

Mantém sua finalidade de comunicação e narrativa do projeto. Storytelling não é gate de engenharia e não substitui Discovery, SDD, QA ou a Definition of Done.

## Skills especializadas

Segurança e banco de dados devem ser tratados principalmente como checklists ou skills especializadas quando relevantes, e não como agentes permanentes na escala atual do projeto. Outros papéis especializados seguem o mesmo princípio: são invocados conforme o risco e o escopo da tarefa.

## Limites permanentes

Todos os papéis respeitam `AGENTS.md`: sem sudo, Docker de produção, segredos, `.env` de produção, acesso ou ação direta em produção. Produção continua sob gate humano.