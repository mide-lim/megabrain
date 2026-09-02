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
- **Sprint 4 — Private Web Library:** FastAPI SSR/Jinja, biblioteca e detalhe
  de Reel, paginação, busca, categorias manuais, reprodução por URL R2 assinada
  e proteção de produção.

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
