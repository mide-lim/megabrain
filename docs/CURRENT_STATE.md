# Estado atual do MegaBrain

## Snapshot de engenharia — 2026-10-01

Este snapshot complementa o estado de produto abaixo. Registra observações desta
auditoria; não concede nova autoridade nem comprova integração completa.

- Paperclip está em uso para tarefas de desenvolvimento, incluindo MEG-4.
- Na verificação systemd, `megabrain-control-plane.service` e
  `megabrain-hermes-coordinator.service` estavam `active/running`.
  Isso não prova que ambos coordenam a mesma tarefa.
- A MEG-4 foi entregue na conversa desta auditoria: source commit
  `a863ae0564090d5abd6f43f7b72698cb68d72a0a`; production commit
  `8c635f319564c16ba0e7e3c6a837d1fe44d6020e`. A árvore publicada foi
  comparada ao candidato aprovado e era idêntica.
- A integração GitHub `dev` observada está em
  `b788e004744bf44ba2177f1416562af589c56bf0` (PR #89).
  SHA de integração e SHA de release têm finalidades distintas; não presumir
  paridade da pilha inteira a partir da equivalência da mudança frontend.
- O status MEG-4 observado no Paperclip permaneceu `in_review`; faltou registrar
  o recibo/conclusão pelo painel. O proprietário pediu novo discovery visual,
  pois a experiência entregue não correspondeu ao que pretendia.
- O caminho `local_stdio` da ação aprovada de deploy no Paperclip falhou antes
  da capability. O deploy foi concluído por uma única chamada à capability
  existente, que verificou o gate humano do SHA exato. O encaminhamento MCP
  continua pendente.
- `UI_SYSTEM.md` descreve a baseline Jinja histórica. A referência Next atual e
  o design alvo precisam de discovery.
- O QA visual foi exercitado em uma branch isolada nesta conversa; sua ativação
  como fluxo padrão e a retomada IDE/Paperclip/AP0 permanecem pendentes.

[CONTEXT.md](CONTEXT.md) organiza as lacunas, as referências e a proposta mínima
de adoção. Os registros anteriores de Hermes/AP0 e decisões aceitas continuam
vigentes nos seus escopos até reconciliação explícita.

## Estado operacional atual

As capacidades C1–C6 abaixo foram implantadas em produção e validadas por
operador. Esta seção registra o estado aceito; ela não concede nova autoridade
de deploy, acesso a produção ou mudança de configuração.

- fundação de autenticação do proprietário por Google OIDC;
- App Shell autenticado do Next.js;
- fronteira privada de proprietário único;
- Next Library;
- Next Reel Detail;
- API JSON de mutação de categorias com CSRF;
- corte de roteamento C5 de `/reels/*` para Next.js;
- aposentadoria C6 de Jinja;
- FastAPI como autoridade de backend;
- Next.js como autoridade de apresentação.

O fluxo Web atual é privado, de proprietário único e autenticado pela sessão
local opaca emitida pelo FastAPI após Google OIDC. Caddy fornece HTTPS e
roteamento, não autenticação de aplicação. Basic Auth foi a fronteira MVP da
Sprint 4 e não protege o fluxo Web atual.

## Fluxo de produto disponível

```text
Add Reel
  -> download
  -> R2
  -> downloaded/not_requested
  -> STOP

Transcrever (solicitação explícita do proprietário autenticado)
  -> queued
  -> MGB-030 periódico
  -> processing
  -> Google Speech-to-Text
  -> completed|failed
  -> transcript Web
```

Um usuário envia manualmente um link público de Reel pelo Telegram ou o registra
na Web autenticada. O n8n valida e orquestra a ingestão; o downloader guarda a
mídia no R2 privado e PostgreSQL mantém as referências e o estado. O download
não solicita transcrição automaticamente: novos Reels terminam em
`downloaded | not_requested`.

Somente depois de o proprietário autenticado escolher `Transcrever`,
Web/FastAPI pode enfileirar `not_requested|failed -> queued`. MGB-030, ativo em
produção como consumidor periódico, é a autoridade de processamento para
`queued -> processing -> completed|failed`.

## Capacidades validadas da Web

- autenticação de proprietário por Google OIDC, identidade durável por issuer +
  subject e sessão local opaca `__Host-mb_session`;
- biblioteca paginada e página de detalhe de Reel em Next.js;
- caption original preservada separadamente do transcript;
- reprodução de vídeo do R2 por URL assinada de curta duração;
- categorias manuais muitos-para-muitos: criar, associar e remover via API JSON;
- CSRF obrigatório para mutações cookie-autenticadas e logout;
- busca PostgreSQL em creator, caption, transcript aceito e categoria;
- Transcript on Demand: o proprietário autenticado solicita `Transcrever`, a
  Web somente enfileira a intenção e o transcript `pt-BR` concluído fica visível
  na Web;
- HTTPS e roteamento via Caddy;
- FastAPI como autoridade de autenticação, autorização, domínio, dados, R2 e
  API, sem apresentação Jinja;
- serviços frontend e Web sem portas publicadas no host.

## Histórico relevante

A Sprint 4 foi implantada e validada com Basic Auth como seu controle MVP
histórico. C1–C6 substituíram esse fluxo pela fronteira atual de Google OIDC e
sessão local do proprietário. Essa evolução não torna a aplicação multiusuário
nem pública.

## Engenharia e limites conhecidos

- Engineering Enablement Phase A: `COMPLETE`.
- Engineering Enablement Phase B: `COMPLETE / PROMOTED`.
- B3 — CI Foundation: `COMPLETE / PROMOTED`.
- B4 — Hermes Autonomy Foundation: `COMPLETE / PROMOTED`.
- B4.1 — GitHub Auth Bootstrap: `COMPLETE / PROMOTED`.
- B4.2 — Autonomous PR Lifecycle: instalação ativa reconciliada com a fonte
  canônica v1.1.0, com paridade byte a byte; nenhuma nova autoridade foi
  concedida pela reconciliação.
- B4.3 — Bounded Run Authorization: `COMPLETE / PROMOTED`.

Hermes suporta o lifecycle limitado somente dentro de uma autorização aprovada:
implementação em `agent/*`, publicação e criação de PR controladas, observação
de CI, autocorreção limitada e READY para SHA exato antes de revisão/merge
humano. READY não concede autoridade de merge. Hermes não tem autoridade para
merge, auto-merge, force push, escrita direta em `dev` ou `main`, mutação de
workflows, rulesets ou permissões do GitHub App, acesso à produção ou deploy.

### Downloader

- O tratamento de respostas HTTP 200 com `success:false` precisa de hardening.

### Enricher

- Google Speech-to-Text V2 / Chirp 3 processa em `pt-BR`.
- O caminho síncrono é usado somente dentro do contrato seguro; mídia fora desse
  contrato usa BatchRecognize.
- BatchRecognize usa GCS temporário, persiste a provider operation e é
  reconciliado de forma durável pelo consumidor periódico.
- O cleanup temporário ocorre somente após persistência terminal
  `completed|failed`.

### Web

- A observabilidade ainda é mínima.
- A busca v1 usa `ILIKE` no PostgreSQL e aceita a semântica de curingas `%` e
  `_`.

### Operações

- MGB-030 permanece ativo em produção como consumidor periódico de
  transcrição. O smoke final com a fila vazia não criou attempts ou enrichments
  indevidos.
- Formalizar backup/restore, monitoramento/alertas, runbook de atualização e
  automação mais ampla de QA/regressão.

## Fora do escopo atual

Não há classificação automática por IA. OCR, visão computacional, embeddings,
resumos e classificação automática continuam fora do escopo. Google
Speech-to-Text é um serviço de processamento, não inteligência de produto.
