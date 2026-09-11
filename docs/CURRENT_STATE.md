# Estado atual do MegaBrain

## Checkpoint pós-Sprint 4

Sprints 1 a 4 estão concluídas. A Sprint 4 foi implantada em produção e está
operacional; a validação real de HTTPS, Basic Auth, CSRF e acesso E2E ao R2 foi
concluída com sucesso.

## Fluxo de produto disponível

1. Um usuário envia manualmente um link público de Reel pelo Telegram.
2. O n8n valida e orquestra a ingestão; metadados e estado são registrados no
   PostgreSQL.
3. O downloader obtém o vídeo e o guarda permanentemente no Cloudflare R2
   privado; referências e metadados permanecem no PostgreSQL.
4. O enricher lê a mídia do R2, usa Google Speech-to-Text V2 / Chirp 3 em
   `pt-BR` e persiste a transcrição no PostgreSQL.
5. A MegaBrain Web privada permite recuperar e curar o conteúdo.

## Sprints concluídas

- **Sprint 1 — Intake / Telegram:** links públicos de Reels submetidos por
  Telegram, validados e orquestrados pelo n8n, com metadados registrados no
  PostgreSQL.
- **Sprint 2 — Download e armazenamento permanente:** downloader e R2 privado
  para mídia; referências e metadados persistidos no PostgreSQL.
- **Sprint 3 — Speech-to-Text:** transcrição por Google Speech-to-Text V2 /
  Chirp 3 em `pt-BR`, persistida no PostgreSQL.
- **Sprint 4 — Private Web Library:** biblioteca e detalhe de Reel, paginação,
  busca, categorias manuais, reprodução por URL R2 assinada e proteção de
  produção. A apresentação inicial FastAPI SSR/Jinja foi aposentada em C6.

## F0 — Next.js Frontend Foundation

- `apps/web` estabelece Next.js App Router, React, TypeScript strict, Tailwind
  CSS e uma fundação compatível com shadcn/ui usando tokens semânticos do
  MegaBrain.
- A imagem standalone do Next é preparada para self-hosting no serviço Docker
  interno `frontend` (porta 3000), com health endpoint próprio.
- Após C6, Next.js controla toda a apresentação pública. FastAPI continua
  responsável por autenticação, autorização, domínio, dados, R2 e APIs; Caddy e
  Basic Auth permanecem como definidos no roteamento atual.

## F1 — Authentication Foundation candidate

- O candidato local contém uma fundação Google OIDC controlada pela FastAPI,
  com `Authlib==1.8.0`, Authorization Code + PKCE S256 e transações OIDC
  server-side.
- A associação de proprietário usa identidade Google durável por issuer +
  subject; sessões locais opacas com persistência PostgreSQL suportam
  `/api/auth/session` e `/auth/logout`.
- A migration `003_f1_authentication_foundation.sql` foi escrita para
  `app.auth_users`, `app.auth_sessions` e `app.auth_transactions`.
- O hardening da configuração de produção para desativar access log do Uvicorn
  foi escrito, prevenindo registro de query strings de callback.

O candidato F1 não está implantado; a migration não foi aplicada; o cliente
Google OAuth não foi configurado. Basic Auth continua sendo a fronteira de
produção e Caddy permanece inalterado.

## C2 — Authenticated App Shell candidate

- O candidato local estabelece o App Shell autenticado do Next.js para `/`,
  `/login`, `/inbox`, `/library`, `/categories` e `/settings`.
- FastAPI continua a autoridade de sessão e autorização: `/api/reels` exige uma
  sessão opaca válida do proprietário e retorna JSON `401` sem ela; o bootstrap
  de sessão permanece em `/api/auth/session`.
- O Next consulta esse endpoint somente no servidor, encaminhando
  explicitamente o header `Cookie` e usando `cache: no-store`; não armazena
  sessão no navegador nem consulta o banco de dados diretamente.
- O Caddyfile versionado encaminha a apresentação pública, inclusive
  `/reels/*`, para Next.js e mantém `/api/*`, `/auth/*` e `/health` no FastAPI.
  C6 removeu as telas Jinja e o mount estático legado do FastAPI.
- A ação global “Adicionar Reel” é intencionalmente desabilitada e marcada “Em
  breve”; não existe endpoint ou ingestão correspondente neste slice.
- O healthcheck interno do frontend passa a usar `/healthz`, liberando `/api/*`
  para a arquitetura final do FastAPI.

O candidato C2 não foi implantado nem executou operações de produção.

## Capacidades validadas da Web

- biblioteca paginada e página de detalhe de Reel;
- caption original preservada separadamente do transcript;
- reprodução de vídeo do R2 por URL assinada de curta duração;
- categorias manuais muitos-para-muitos: criar, associar e remover;
- busca PostgreSQL em creator, caption, transcript aceito e categoria;
- HTTPS via Caddy e Basic Auth em todas as rotas Web;
- CSRF nos POSTs de curadoria;
- role PostgreSQL dedicada e de privilégio mínimo para a Web;
- serviço Web sem porta publicada no host.

## Limitações e dívida conhecida

### Engineering Enablement

- Engineering Enablement Phase A: `COMPLETE`.
- Engineering Enablement Phase B: `COMPLETE / PROMOTED`.
- B1 — Automation Architecture Discovery: `COMPLETE`.
- B2 — Public GitHub Foundation: `COMPLETE / PROMOTED`.
- B3 — CI Foundation: `COMPLETE / PROMOTED`.
- B4 — Hermes Autonomy Foundation: `COMPLETE / PROMOTED`.
- B4.1 — GitHub Auth Bootstrap: `COMPLETE / PROMOTED`.
- B4.2 — Autonomous PR Lifecycle: `COMPLETE / PROMOTED`.
- B4.3 — Bounded Run Authorization: `COMPLETE / PROMOTED`.

#### Evidência de fechamento B4.3

- Pull Request #20 foi integrado manualmente em `dev`; o candidato revisado foi
  `5856ffdb7ede157fb335cd5da05456c55029e717` e o commit resultante em `dev` é
  `32fe9751ef5f19e54d6fae4d5949dd2675a08b72`.
- O veredito final local foi `B4_3_R1_STAGE2F_R2_READY`.
- Foram validados snapshot coerente de CI, invalidação de publicação, precedência
  de terminal replay, separação de operações, READY para SHA exato e geração do
  relatório sem novo acesso de rede.
- A cobertura direta de timing de autorização P2/P3/P4, os testes direcionados
  R1, as regressões B4.2 e B4.1, a paridade do instalador, `py_compile` e
  `git diff --check` passaram; o worktree final permaneceu limpo.

Hermes agora suporta o lifecycle limitado: contrato de tarefa, implementação em
`agent/*`, Run Authorization limitado, publicação e criação de PR controladas,
observação de CI, autocorreção limitada, snapshot coerente de CI e READY para
SHA exato antes de revisão/merge humano. READY é evidência para um único SHA e
não concede autoridade de merge.

Hermes não tem autoridade para merge, auto-merge, force push, escrita direta em
`dev` ou `main`, mutação de workflows, rulesets ou permissões do GitHub App,
interfaces genéricas e irrestritas de Git/API/shell, acesso à produção ou deploy.
O merge humano permanece uma fronteira de autoridade separada.

### Downloader

- O tratamento de respostas HTTP 200 com `success:false` precisa de hardening.

### Enricher

- O caminho síncrono atual suporta mídia de aproximadamente até 60 segundos.
- Há pendências de falsos positivos de ausência de fala, timestamps/VAD,
  backfill e tratamento de tentativas obsoletas.

### Web

- Basic Auth é intencionalmente uma camada MVP de acesso para um único usuário.
- A observabilidade ainda é mínima.
- O aviso de formatação do Caddyfile é cosmético.
- A busca v1 usa `ILIKE` no PostgreSQL e aceita a semântica de curingas `%` e
  `_`.

### Operações

- Formalizar backup/restore, monitoramento/alertas, runbook de atualização e
  automação mais ampla de QA/regressão.

## Fora do escopo atual

Não há classificação automática por IA. OCR, visão computacional, embeddings,
resumos e classificação automática continuam fora do escopo. Google
Speech-to-Text é um serviço de processamento, não inteligência de produto.
