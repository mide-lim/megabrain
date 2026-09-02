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

## Sprint 5 — Discovery pending

Não existe implementação de Sprint 5 aprovada. A próxima etapa é discovery:
revisar uso real, limitações e riscos antes de escolher escopo, ordem ou
tecnologia.

Possíveis dimensões para investigação, sem compromisso de implementação:

- organização e UX da biblioteca;
- expansão de ingestão;
- melhorias de processamento;
- operações e observabilidade;
- suporte a vídeos longos.

## Fora do escopo até nova decisão

Classificação automática por IA, OCR, visão computacional, embeddings, resumos,
busca semântica, compartilhamento público e mudanças de produção sem aprovação
humana não fazem parte do próximo trabalho por padrão.
