# Decisões do MegaBrain

Este documento registra decisões arquiteturais e de produto duráveis. Decisões
não substituem validação por código, testes ou operação.

## D001 — Reels públicos como primeiro conteúdo

**Status:** aceita

O fluxo inicial trata somente links públicos de Reels do Instagram enviados
manualmente, sem depender da API oficial. Isso mantém a evolução incremental e
deixa outras fontes e vídeos longos para decisão futura.

## D002 — n8n como orquestrador do produto

**Status:** aceita

n8n orquestra os workflows de ingestão e processamento; serviços especializados
executam download e enrichment.

## D003 — R2 privado para mídia e PostgreSQL para dados consultáveis

**Status:** aceita

Cloudflare R2 armazena mídia pesada em bucket privado. PostgreSQL mantém
metadados, estado, caption, transcript, categorias e relacionamentos
pesquisáveis. A mídia não é persistida como cópia na Web.

## D004 — Caption original e transcript são dados distintos

**Status:** aceita

A caption do autor é preservada separadamente da transcrição. Nenhuma delas é
editada pelo produto atual.

## D005 — Sem classificação automática na fase atual

**Status:** aceita

Categorias são criadas e atribuídas manualmente. Agentes de IA servem ao
desenvolvimento/orquestração, e Google Speech-to-Text é processamento de
runtime; nenhum deles classifica o conteúdo do produto. OCR, visão, embeddings,
resumos e classificação automática permanecem fora do escopo.

## D006 — Web SSR com FastAPI e Jinja

**Status:** aceita

A Web Library é uma aplicação SSR FastAPI/Jinja, sem SPA ou frontend separado
no MVP. Isso reduz superfície e complexidade para a biblioteca pessoal.

## D007 — R2 privado com URLs assinadas curtas

**Status:** aceita

A Web gera URLs R2 assinadas de curta duração para reprodução direta pelo
navegador. Credenciais R2 não chegam ao browser e a VPS não transmite o vídeo
inteiro.

## D008 — Role PostgreSQL Web de privilégio mínimo

**Status:** aceita

A Web usa credenciais próprias com apenas os privilégios necessários para ler a
biblioteca e executar a curadoria permitida. Não usa a credencial proprietária
do banco.

## D009 — Caddy HTTPS e Basic Auth como acesso MVP

**Status:** aceita

Caddy é o ingresso HTTPS da Web e aplica Basic Auth em todas as rotas. É uma
camada intencionalmente MVP, de usuário único, e não substitui as proteções da
aplicação.

## D010 — CSRF obrigatório atrás de Basic Auth

**Status:** aceita

POSTs de curadoria exigem proteção CSRF mesmo quando a rota já exige Basic Auth.
A autenticação HTTP não elimina o risco de requisições forjadas em contexto de
navegador.

## D011 — Web somente na rede Docker interna

**Status:** aceita

A Web não publica porta no host. Caddy é o único caminho externo para `web:8000`;
os demais serviços de runtime comunicam-se pela rede Docker interna conforme
necessário.

## D012 — Produção human-gated e agentes sem privilégios

**Status:** aceita

Agentes trabalham em branches `agent/*`, sem sudo, Docker, segredos ou workspace
de produção. O Git central é fonte de verdade; push, merge, deploy e demais
ações de produção ficam sob revisão e aprovação humana.

## D013 — Governança de engenharia orientada a risco e evidência

**Status:** aceita

Hermes evolui para Engineering Orchestrator: coordena o estado, o planejamento,
a implementação, a revisão independente e as evidências, sem concentrar
normalmente todas as decisões especializadas. Os gates de desenvolvimento são
baseados em risco; progressão autônoma só pode ocorrer com evidência proporcional
ao risco. O Product Owner retém a autoridade de produção.

## D014 — Papéis especializados acionados como skills quando necessários

**Status:** aceita

Na escala atual, segurança, banco de dados e outras especialidades devem ser
acionados principalmente como skills ou checklists conforme o escopo e o risco,
em vez de manter muitos agentes permanentes.

## D015 — Engineering Enablement é paralelo ao roadmap de produto

**Status:** aceita

O projeto distingue roadmap de produto de Engineering Enablement. A melhoria do
processo de desenvolvimento não constitui Sprint 5 nem aprova implementação de
produto; a Sprint 5 continua dependente de discovery e decisão humana.

## D016 — SDD, UX e UI System estruturam mudanças de interface

**Status:** aceita

SDD é o Planner/Architect técnico canônico e produz a especificação técnica
compatível com o Task Contract, a política de risco e a Definition of Done.
UX/Product Design é uma capability especializada, invocada somente quando a
tarefa envolver experiência de interface. SDD decide arquitetura, contratos,
dados, backend, segurança e operação; UX decide fluxo, hierarquia, layout,
interação, estados e responsividade. Nenhuma disciplina substitui silenciosamente
a outra.

Mudanças frontend devem seguir a baseline documentada em `UI_SYSTEM.md`, sem
tratar documentação como redesign automático. Automação de UI deve ser
determinística quando possível; Playwright é a base inicial planejada para
regressão de navegador. Playwright não está instalado, e ferramentas de agente
de navegador podem futuramente complementar QA exploratório, mas não são a base
de regressão do projeto.
