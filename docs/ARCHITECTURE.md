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

## Ingresso público

```text
Internet
  -> Caddy (HTTPS)
       -> n8n
       -> Basic Auth -> MegaBrain Web
```

Caddy é o único serviço com portas publicadas no host. Ele termina HTTPS e
encaminha o tráfego para os serviços internos. Todas as rotas da Web, inclusive
`/health`, exigem Basic Auth. O endpoint e as credenciais operacionais não são
registrados neste repositório.

## Serviços internos

- **n8n:** valida entradas do Telegram e orquestra ingestão, download e fluxos
  relacionados.
- **downloader:** recupera vídeo de Reel público e grava a mídia no R2.
- **enricher:** lê mídia privada do R2 e persiste transcrições do Google
  Speech-to-Text no PostgreSQL.
- **PostgreSQL:** mantém metadados, estado, caption original, transcript e
  categorias/associações pesquisáveis.
- **Cloudflare R2:** mantém a mídia pesada em bucket privado.
- **MegaBrain Web:** aplicação SSR FastAPI/Jinja para biblioteca, busca e
  curadoria manual.

Downloader, enricher, PostgreSQL, n8n e Web usam a rede Docker interna.
A Web não publica porta no host; Caddy é sua única entrada de rede externa.

## Fluxo da biblioteca Web

```text
Browser autenticado
  -> Caddy / HTTPS / Basic Auth
  -> MegaBrain Web
       -> PostgreSQL (role Web de privilégio mínimo)
       -> R2 privado (URL assinada de curta duração)
  -> Browser baixa/reproduz vídeo diretamente do R2
```

A Web não mantém cópia de vídeo nem expõe credenciais R2 ao navegador. Ela cria
URLs assinadas temporárias para que o R2 entregue a mídia diretamente.

## Fronteiras de segurança

- R2 permanece privado; mídia é acessada pela Web com credenciais de runtime e
  pelo navegador apenas por URLs assinadas temporárias.
- A Web conecta ao PostgreSQL com role dedicada de menor privilégio, sem usar a
  credencial proprietária do banco.
- Basic Auth é a camada de acesso MVP para a Web pessoal e privada.
- CSRF continua obrigatório nos POSTs de curadoria, mesmo atrás de Basic Auth.
- Segredos, configuração de produção, Docker, banco e deployment permanecem
  fora do alcance dos agentes. Ações de produção exigem gate e aprovação humana.

## Limites atuais

A arquitetura atual não inclui classificação automática, embeddings, OCR,
visão computacional, resumos, busca semântica, multiusuário ou API pública da
Web. Essas capacidades não devem ser inferidas da existência da transcrição.
