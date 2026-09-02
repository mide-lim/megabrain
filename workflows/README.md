# Workflows n8n

Este diretório contém exports sanitizados dos workflows do n8n para documentação, revisão e versionamento.

Os exports preservam topologia, tipos de nós, expressões, queries e comportamento documentável. Eles substituem IDs e nomes de credenciais, IDs de chat do Telegram, IDs de webhook, URLs de serviços internos e IDs de nós por placeholders explícitos. Não contêm payloads de credenciais nem são backup completo ou configuração pronta para deploy.

Para importar ou ativar um workflow, o operador deve restaurar/configurar os identificadores e credenciais no ambiente apropriado, fora deste repositório público, e revisar a configuração antes da ativação. A importação ou ativação requer revisão humana e não autoriza publicação nem ativação em qualquer ambiente.

## Convenção de placeholders

Todo placeholder é uma string inteira no formato `__[A-Z0-9_]+__`. Os exports usam:

- `__CREDENTIAL_ID__` e `__CREDENTIAL_NAME__` para referências de credenciais;
- `__TELEGRAM_CHAT_ID__` para o chat autorizado;
- `__WEBHOOK_ID__` para webhooks;
- `__SERVICE_URL__` para URLs internas;
- `__NODE_ID__` para IDs de nós.

Esses valores são marcadores não operacionais: devem ser substituídos pela configuração privada do operador, nunca por valores versionados neste diretório.

## Arquivos

- `MGB-001-entrada-telegram.json`: recebe mensagens do Telegram, valida a entrada e encaminha Reels para o workflow de registro.
- `MGB-010-entrada-reel.json`: normaliza e registra Reels, informa o resultado pelo Telegram e chama o workflow de download.
- `MGB-020-download-reel.json`: coordena o download, atualiza o PostgreSQL e envia mensagens de status pelo Telegram.
- `MGB-030-enrichment-reel.json`: recebe um Reel baixado, chama o Enricher e persiste tentativas, resultados ou falhas de enriquecimento.
