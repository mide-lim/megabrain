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

**Status:** substituída por D020

Esta foi a decisão do MVP original. A apresentação FastAPI/Jinja foi retirada em
C6 e substituída por Next.js conforme D020.

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

**Status:** substituída por D021

Caddy foi o ingresso HTTPS da Web e aplicou Basic Auth em todas as rotas no MVP.
Essa camada histórica, de usuário único, não substituía as proteções da
aplicação. D021 aposenta Basic Auth do fluxo Web atual e mantém Caddy somente
como fronteira de HTTPS e roteamento.

## D010 — CSRF obrigatório atrás de Basic Auth

**Status:** substituída e preservada historicamente por D021

POSTs de curadoria exigiam proteção CSRF mesmo quando a rota já exigia Basic
Auth. A autenticação HTTP não eliminava o risco de requisições forjadas em
contexto de navegador. D021 preserva o princípio de CSRF obrigatório para
requisições cookie-autenticadas que alteram estado.

## D011 — Web somente na rede Docker interna

**Status:** aceita

A Web não publica porta no host. Caddy é o único caminho externo para `web:8000`;
os demais serviços de runtime comunicam-se pela rede Docker interna conforme
necessário.

## D012 — Produção human-gated e agentes sem privilégios

**Status:** aceita; autoridade Git parcialmente superada por D017

Agentes trabalham em branches `agent/*`, sem sudo, Docker, segredos ou workspace
de produção. O Git central era a fonte de verdade nesta etapa; push, merge,
deploy e demais ações de produção ficavam sob revisão e aprovação humana.

D017 substitui apenas a definição de source of truth e publicação de branches.
As restrições de produção e privilégios desta decisão permanecem válidas.

## D013 — Governança de engenharia orientada a risco e evidência

**Status:** aceita; papel organizacional de Hermes parcialmente substituído por D022

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

## D017 — GitHub público como source of truth de desenvolvimento

**Status:** aceita

O repositório público `mide-lim/megabrain` passa a ser a fonte de verdade de
desenvolvimento a partir de uma baseline limpa e sanitizada. O histórico Git
privado anterior é preservado somente como arquivo de transição e não participa
do fluxo operacional.

Hermes utiliza um GitHub App limitado ao repositório. Essa identidade pode
publicar branches `agent/*` e abrir pull requests, mas os rulesets de `dev` e
`main` impedem atualização direta e merge pelo agente. Integração e promoção
nessas branches permanecem human-gated via pull request.

O transporte por Git bundle deixa de fazer parte do fluxo operacional. Esta
decisão não concede ao Hermes acesso, merge, deploy ou qualquer autoridade de
produção.

## D018 — Next.js como fundação gradual de frontend

**Status:** substituída nas decisões de roteamento e apresentação por D019 e D020

Esta decisão registra a fundação inicial do frontend. As decisões posteriores
D019 e D020 definem o roteamento e a propriedade de apresentação atuais.

## D019 — App Shell autenticado seletivo do Next.js

**Status:** substituída nas decisões de roteamento e apresentação por D020

Esta decisão registra o corte inicial para o App Shell. D020 completa a
propriedade de apresentação do Next.js e retira as rotas e assets Jinja legados.

## D020 — Next.js controla toda a apresentação pública

**Status:** aceita

Next.js é o único proprietário de apresentação pública, inclusive `/reels/*`.
FastAPI continua como autoridade de autenticação, sessões, OIDC, CSRF, APIs,
domínio, dados, mutações de categoria, assinatura R2 e `/health`. C6 remove as
rotas Jinja, os templates e o mount `/static` legados sem alterar os contratos
ativos de API ou as fronteiras de autorização.

## D021 — Google OIDC e sessão local opaca são a fronteira Web atual

**Status:** aceita

Google OIDC com sessão local opaca de proprietário único é a fronteira atual de
autenticação da Web. FastAPI permanece a autoridade de autenticação, sessão,
autorização, CSRF, APIs e domínio; Caddy termina HTTPS e roteia tráfego, sem
executar autenticação de aplicação.

Basic Auth foi uma fronteira MVP e está aposentada do fluxo Web atual. A
aplicação continua privada e de proprietário único: a política
`AUTH_OWNER_EMAIL` controla o bootstrap, e a identidade durável do proprietário
usa issuer + subject do Google. Esta decisão não torna a aplicação multiusuário
nem pública.

A sessão `__Host-mb_session` é local e opaca. CSRF continua obrigatório em toda
requisição cookie-autenticada que altere estado, incluindo mutações JSON de
categoria e logout. D009 e D010 são preservadas como decisões históricas e são
substituídas por esta decisão para a arquitetura atual.

## D022 — Orquestração com contexto durável e entrega verificável

**Status:** aceita como direção de arquitetura em 2026-10-01; adoção operacional pendente.
**Origem:** escolhas 1–14 de Michel e instrução para prosseguir com a fundação.
**Relação:** substitui o papel organizacional de coordenador exclusivo do Hermes em D013;
preserva D014, D015, separação SDD/UX de D016 e fronteiras atuais D012/D017/D020/D021.

### Contexto

Tarefas e expectativas ficaram distribuídas entre conversa, IDE, Paperclip,
docs históricas e runtime AP0. A MEG-4 mostrou que testes de agrupamento não
preservavam suficientemente a intenção visual. Modelos configurados não
comprovam retomada, revisão e publicação ponta a ponta.

### Decisão

| Escolha | Regra aceita |
|---|---|
| 1 A | Autonomia dentro do escopo/ADRs; propor mudanças materiais antes de adotá-las. |
| 2 A | Paperclip acompanha; Codex concentra código; Hermes integrações, pesquisa e automações. |
| 3 A | Uma implementação ativa inicialmente; review em outra sessão. |
| 4 A | Responsável escreve o pacote a partir da intenção; esclarecer dúvidas que alteram aceite. |
| 5 A+B | Contexto essencial + arc42 completo e C4 da arquitetura real, com detalhes proporcionais. |
| 6 A | CocoIndex após organizar fontes e medir lacunas de recuperação. |
| 7 A | Checkpoint em marcos, bloqueios/handoff e periodicamente no trabalho longo. |
| 8 A+B | Proposta navegável e imagens anotadas antes da implementação completa de UI. |
| 9 A | Preview separado na VPS, com capacidade/isolamento e URL verificados. |
| 10 A | Dados/serviços de teste; teste controlado para integração real. |
| 11 A | Automação e reviewer em outra sessão; referência visual integra o aceite. |
| 12 A | Publicação de baixo risco automática após um ciclo completo e política/capability validadas. |
| 13 A | Duas tentativas distintas por bloqueio; checkpoint e escalada; quota pausa a execução. |
| 14 A | Tarefa/PR mostram responsável, etapa, progresso, bloqueio, preview, evidências e release. |

GitHub preserva código, docs, decisões e evidências. Paperclip vincula essas
fontes à tarefa. Task Packet projeta TASK_CONTRACT.md e o contrato do executor;
não cria outro schema AP0. Cada checkpoint identifica escritor e fonte canônicos.
AP0 continua dono dos registros AP0 até cutover explícito e validado.

### Alternativas consideradas

- Hermes como coordenador organizacional exclusivo: aproveita o histórico,
  mas contraria o painel/fluxo escolhidos; seu componente AP0 fica preservado
  no escopo de infraestrutura durante a transição.
- Indexação e vários agentes permanentes desde o início: acrescentam dependências
  e consumo antes de medir gargalos; adiados.
- Vercel para preview inicial: reduz manutenção do frontend, mas acrescenta
  outro ambiente e condições de plano; escolhida a VPS.
- Apenas conversa, README ou testes do autor: insuficientes para retomada e
  comparação independente com intenção visual.
- Auto deploy imediato: rejeitado; validar primeiro identidade, review, capability,
  healthcheck e reversão de um ciclo inteiro.

### Consequências e transição

Criar templates de pacote, checkpoint e recibo; ligar arquitetura e estado à
entrada de contexto. Resolver integração/provisionamento com tasks próprias.
Uma tarefa piloto demonstra retomada sem chat, preview, revisão e publicação.

A escolha 12 não reclassifica toda publicação como Green nem concede merge,
Docker, sudo, segredos ou acesso a produção aos executores. Preparação e operação
de produção continuam distintas. Enquanto a capability/política substituta não
for validada e ativada, D012/D017, RISK_POLICY.md e gates existentes continuam
vigentes. A futura automação deve operar através de uma capability delimitada,
com regras explícitas, revisão do candidato, recibo e recuperação.

Nova direção visual, mudança material de arquitetura, permissões ou operação
destrutiva permanece sujeita à decisão humana aplicável. Approval de um candidato
não aprova outro SHA/artefato; executor ou reviewer não assume identidade humana.

### Evidência e status de adoção

- Escolhas registradas: concluído.
- Fontes, vistas arc42/C4, templates e piloto: esta alteração documental.
- Injeção automática no executor, preview padrão, review independente do piloto,
  publication policy e recibo runtime: pendentes de implementação/validação.
