# Roadmap do MegaBrain

## Objetivo do projeto

Construir uma biblioteca pessoal para capturar, processar, organizar e recuperar
conhecimento a partir de conteúdo digital, começando por Reels públicos do
Instagram enviados manualmente pelo Telegram.

## Princípios de evolução

- Evoluir incrementalmente, uma responsabilidade por vez.
- Preservar mídia pesada no R2 e dados pesquisáveis no PostgreSQL.
- Não adicionar automação de classificação por IA à fase atual.
- Validar e observar a etapa atual antes de ampliar escopo ou autonomia.
- Manter ações de produção sob aprovação humana.

## Estado concluído

As Sprints 1 a 4 estão concluídas; a Sprint 4 está implantada e operacional.
O produto atual oferece ingestão por Telegram, download e armazenamento privado,
transcrição em `pt-BR` e uma Web Library privada para recuperação e curadoria
manual. Consulte `CURRENT_STATE.md` para as capacidades e limitações atuais.

### Sprint 1 — Intake / Telegram

Concluída: entrada manual de links públicos de Reels, validação/orquestração no
n8n e registro no PostgreSQL.

### Sprint 2 — Download e armazenamento permanente

Concluída: recuperação de mídia pelo downloader, armazenamento privado no R2 e
referências persistidas no PostgreSQL.

### Sprint 3 — Speech-to-Text

Concluída: processamento pelo enricher com Google Speech-to-Text V2 / Chirp 3
em `pt-BR`, com transcript persistido no PostgreSQL.

### Sprint 4 — Private Web Library

Concluída e implantada: biblioteca SSR, paginação, detalhe, busca, categorias
manuais, URLs R2 assinadas, role Web de privilégio mínimo, CSRF, HTTPS e Basic
Auth.

## Sprint 5 — Productização da experiência

Status: F5.1 concluído; F5 Categories deferred, not cancelled.

### F5.1 — Add Reel UX

Implementado, revisado, mergeado em `dev`, implantado e aceito em produção
em 2026-09-19.

F5.1 adiciona ao App Shell autenticado uma entrada Web para registrar um Reel
público do Instagram através do contrato FastAPI já existente.

O fluxo preserva as fronteiras estabelecidas nas fases anteriores:

- sessão do proprietário continua sob autoridade do FastAPI;
- CSRF permanece obrigatório;
- FastAPI continua responsável por normalização, registro, deduplicação,
  lifecycle e dispatch;
- Next.js continua sendo a autoridade de apresentação e interação do
  proprietário;
- nenhum novo contrato de backend, schema ou workflow é introduzido pelo F5.1.

O frontend F5.1 foi promovido a partir do artefato imutável e permanece
saudável em produção. A aceitação autenticada da interface e um E2E real de
ingestão Web foram concluídos com sucesso.

O Reel de aceitação #26 (`DdcX68ZRQun`) percorreu MGB-015, MGB-020 e MGB-030,
teve mídia persistida no R2 e a tentativa histórica original terminou em
`downloaded | inbox | failed` com `STT_SYNC_RECOGNIZE_UNSUPPORTED`. Essa
tentativa continua sendo histórico válido e não uma falha do fluxo Add Reel.
Posteriormente, F6 o processou por um novo claim normal, com
`retry_of_attempt_id = NULL`, e o Reel terminou `completed`; a tentativa
histórica foi preservada.

A evidência de produção F5.1 foi selada separadamente da evidência F4 com
SHA-256 `e7dc4b42ddab75f6da1e992afdef0000d3109e1092645aec8964c307d6347d9d`.

### F6 — Transcript on Demand

Status: COMPLETE / PRODUCTION ACCEPTED / OPERATIONAL.

F6 foi antecipado antes de F5 Categories por prioridade de produto, sem
renumerar o roadmap. Em produção, Add Reel termina em
`downloaded | not_requested`; o proprietário autenticado solicita
explicitamente `Transcrever`, Web/FastAPI enfileira somente
`not_requested|failed -> queued`, e MGB-030 periódico processa
`queued -> processing -> completed|failed`.

O TC5 real E2E passou para o Reel #28 (`DbW1ECDMAyj`): BatchRecognize real,
transcript `pt-BR` visível na Web e cleanup de GCS confirmado. A fila final
ficou vazia, não restou Reel em `processing`, e MGB-030 permaneceu ACTIVE com
três execuções periódicas bem-sucedidas no smoke final. A versão ativa aceita
de MGB-030 é `7cd5819c-83c8-41ea-ab07-1c86099de886`.

### F5 Categories — deferred, not cancelled

F5 Categories foi adiado, não cancelado. O roadmap não foi renumerado: F6 foi
executado antes somente por prioridade de produto. Após este fechamento
documental, o próximo passo de produto volta para discovery/reassessment de F5
Categories baseada em uso real. Nenhum próximo incremento, incluindo F7 ou
outra feature, fica automaticamente aprovado.

## Fora do escopo até nova decisão

Classificação automática por IA, OCR, visão computacional, embeddings, resumos,
busca semântica, compartilhamento público e mudanças de produção sem aprovação
humana não fazem parte do próximo trabalho por padrão.
