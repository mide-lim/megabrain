# Estado atual do MegaBrain

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

1. Um usuário envia manualmente um link público de Reel pelo Telegram.
2. O n8n valida e orquestra a ingestão; metadados e estado são registrados no
   PostgreSQL.
3. O downloader obtém o vídeo e o guarda permanentemente no Cloudflare R2
   privado; referências e metadados permanecem no PostgreSQL.
4. O enricher lê a mídia do R2, usa Google Speech-to-Text V2 / Chirp 3 em
   `pt-BR` e persiste a transcrição no PostgreSQL.
5. A MegaBrain Web privada permite recuperar e curar o conteúdo.

## Capacidades validadas da Web

- autenticação de proprietário por Google OIDC, identidade durável por issuer +
  subject e sessão local opaca `__Host-mb_session`;
- biblioteca paginada e página de detalhe de Reel em Next.js;
- caption original preservada separadamente do transcript;
- reprodução de vídeo do R2 por URL assinada de curta duração;
- categorias manuais muitos-para-muitos: criar, associar e remover via API JSON;
- CSRF obrigatório para mutações cookie-autenticadas e logout;
- busca PostgreSQL em creator, caption, transcript aceito e categoria;
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
- B4.2 — Autonomous PR Lifecycle: requer C7.2 para reconciliação da integridade
  do artefato instalado antes de qualquer uso autenticado de publicação.
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

- O caminho síncrono atual suporta mídia de aproximadamente até 60 segundos.
- Há pendências de falsos positivos de ausência de fala, timestamps/VAD,
  backfill e tratamento de tentativas obsoletas.

### Web

- A observabilidade ainda é mínima.
- A busca v1 usa `ILIKE` no PostgreSQL e aceita a semântica de curingas `%` e
  `_`.

### Operações

- Formalizar backup/restore, monitoramento/alertas, runbook de atualização e
  automação mais ampla de QA/regressão.

## Fora do escopo atual

Não há classificação automática por IA. OCR, visão computacional, embeddings,
resumos e classificação automática continuam fora do escopo. Google
Speech-to-Text é um serviço de processamento, não inteligência de produto.
