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
- `MGB-010-entrada-reel.json`: adapter Telegram que transporta URL bruta e metadata para `POST http://web:8000/internal/reels`; não acessa PostgreSQL nem chama MGB-020 diretamente.
- `MGB-015-internal-dispatch-reel.json`: webhook interno POST autenticado que valida apenas `reel_id` e entrega MGB-020 para execução assíncrona.
- `MGB-020-download-reel.json`: shared source-neutral processing core.
- `MGB-030-enrichment-reel.json`: recebe um Reel baixado, chama o Enricher e persiste tentativas, resultados ou falhas de enriquecimento.

## MGB-020 — Source-Neutral Processing Core

MGB-020 recebe `reel_id` como entrada canônica e aceita `id` temporariamente
para compatibilidade com MGB-010. O Downloader recebe somente `item_id`,
`shortcode` e `url`; nenhuma metadata Telegram faz parte do request canônico.

O workflow reivindica atomicamente apenas Reels com
`download_status` em `received` ou `failed`. As transições de download são:

```text
received/failed
    -> downloading
    -> downloaded

ou

    -> failed
```

MGB-020 permanece o único writer de `download_status`. MGB-030 é acionado
diretamente após a persistência bem-sucedida de `downloaded`; MGB-020 não
escreve estado de transcrição. Na entrada elegível, MGB-030 é o único writer de
`transcription_status`: aceita `not_requested` ou `failed` para `queued`, cria
atomicamente a tentativa atual ao avançar `queued -> processing`, e só finaliza
`completed` ou `failed` quando o UUID da tentativa ainda é o lifecycle atual.
Consulte `docs/F4_3_REEL_LIFECYCLE_AUTHORITY.md` para a regra de concorrência,
retry e handoff.

## F3.3 — Internal Orchestration Boundary

MGB-010 envia `url` e metadata Telegram ao FastAPI com uma credential Header
Auth configurada pelo operador. A credencial contém o valor correspondente a
`N8N_TO_WEB_INGESTION_KEY`; esse valor não precisa ser injetado como environment
variable no container n8n e nunca é versionado.

O FastAPI registra/deduplica o Reel e pode solicitar dispatch. Para Reels com
`download_status` em `received` ou `failed`, ele chama o path lógico interno
`megabrain-internal-dispatch` com `WEB_TO_N8N_DISPATCH_KEY`. MGB-015 recebe
somente `{ "reel_id": <positive safe integer> }`, valida Header Auth, entrega
MGB-020 com `waitForSubWorkflow=false` e só então responde HTTP 202. O 202
confirma o handoff assíncrono ao processing core, não download ou enrichment.

Exports F3.3 continuam sanitizados: IDs reais de credentials/workflows/nós,
nomes privados de credentials, webhook IDs gerados, instance IDs e qualquer
segredo permanecem placeholders. O path lógico não é segredo; Header Auth é a
fronteira de autenticação.

O runtime de produção foi identificado pelo operador como n8n 2.32.5. Antes da
ativação humana, validar o comportamento contra essa versão e o image digest
exato em uso: o handoff deve ser aceito antes do `Respond to Webhook` retornar
202, sem aguardar Download ou Enrichment. Essa prova de runtime não é fornecida
por este export sanitizado nem por testes locais.
