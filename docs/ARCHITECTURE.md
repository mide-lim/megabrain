# Arquitetura do MegaBrain

## Visão geral

O MegaBrain captura Reels públicos enviados manualmente pelo Telegram, processa
a mídia e disponibiliza uma biblioteca Web privada para consulta e curadoria.

```text
Telegram
  -> n8n
  -> downloader
  -> Cloudflare R2 + PostgreSQL
  -> enricher (Google Speech-to-Text)
  -> PostgreSQL
  -> MegaBrain Web
```

## Ingresso e apresentação atuais

```text
Internet
  -> Caddy / HTTPS
       -> Next.js para apresentação
       -> FastAPI para /api/*, /auth/* e /health
```

Caddy é o único serviço com portas publicadas no host. Ele termina HTTPS e
aplica a fronteira de roteamento para serviços internos; não executa
autenticação de aplicação. O serviço `frontend` usa a rede Docker interna na
porta 3000, sem porta publicada. O serviço `web` usa a rede Docker interna na
porta 8000, sem porta publicada.

Next.js é o único proprietário da apresentação da Web, inclusive biblioteca,
detalhe de Reel e App Shell. FastAPI não serve templates, assets estáticos ou
outra apresentação de produto.

## Autenticação e sessões atuais

```text
Browser
  -> FastAPI /auth/login
  -> Google OIDC
  -> FastAPI /auth/callback
  -> PostgreSQL auth_users/auth_sessions
  -> __Host-mb_session
```

FastAPI é a autoridade de autenticação, autorização, OIDC, vínculo de
identidade, transações e sessões locais opacas. Google é somente o provedor de
identidade. A aplicação continua privada e de proprietário único: a identidade
durável é issuer + subject, com a política de bootstrap `AUTH_OWNER_EMAIL`.

A sessão `__Host-mb_session` é opaca e usa `Secure`, `HttpOnly`, `SameSite=Lax`,
`Path=/` e nenhum `Domain`. Tokens Google não são persistidos.

Basic Auth foi uma fronteira MVP histórica e está aposentada do fluxo Web atual.

## Serviços internos

- **MegaBrain Frontend:** Next.js/App Router em `apps/web`, responsável por toda
  a apresentação. Não implementa autenticação, domínio ou acesso direto ao
  banco.
- **MegaBrain Web:** FastAPI para autenticação, sessões, OIDC, CSRF, APIs,
  domínio, dados e assinatura R2.
- **n8n:** valida entradas do Telegram e orquestra ingestão e download.
- **downloader:** recupera vídeo de Reel público e grava mídia no R2.
- **enricher:** lê mídia privada do R2 e persiste transcrições do Google
  Speech-to-Text no PostgreSQL.
- **PostgreSQL:** mantém metadados, estado, caption, transcript, categorias,
  associações e identidades/sessões de autenticação.
- **Cloudflare R2:** mantém a mídia pesada em bucket privado.

Downloader, enricher, PostgreSQL, n8n, frontend e Web usam a rede Docker
interna. Caddy é a única entrada de rede externa para a Web.

## Fluxo da biblioteca Web

```text
Browser autenticado
  -> Caddy / HTTPS
  -> Next.js para apresentação
  -> FastAPI para sessão, API e domínio
       -> PostgreSQL (role Web de privilégio mínimo)
       -> R2 privado (URL assinada de curta duração)
  -> Browser baixa/reproduz vídeo diretamente do R2
```

O navegador não recebe credenciais R2. FastAPI só assina uma URL temporária após
autenticação do proprietário e depois de confirmar a existência do Reel.

## Fronteiras de segurança

- R2 permanece privado; a mídia é acessada pela Web com credenciais de runtime
  e pelo navegador apenas por URLs assinadas temporárias.
- FastAPI aplica a autorização de proprietário antes de acesso a domínio, banco
  de dados ou assinatura R2.
- Requisições que alteram estado e usam sessão por cookie exigem CSRF; mutações
  JSON usam `X-CSRF-Token` e logout mantém sua proteção CSRF de formulário.
- A Web conecta ao PostgreSQL com role dedicada de menor privilégio, sem usar a
  credencial proprietária do banco.
- Segredos, configuração de produção, Docker, banco e deployment permanecem
  fora do alcance dos agentes. Ações de produção exigem gate e aprovação humana.

## Limites atuais

A arquitetura atual não inclui classificação automática, embeddings, OCR,
visão computacional, resumos, busca semântica, multiusuário ou API pública da
Web. Essas capacidades não devem ser inferidas da existência da transcrição.
