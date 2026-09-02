# Sprint 3 — Enriquecimento de Reels

**Status:** Pipeline síncrono de enriquecimento implementado.

## 1. Propósito deste documento

Este documento registra o checkpoint arquitetural aprovado nas Rodadas 1 e 2
da Discovery da Sprint 3 e a decisão do responsável sobre a implementação
inicial de STT. Ele descreve decisões de escopo, responsabilidades, persistência
e contratos antes da implementação.

O conteúdo não comprova execução ponta a ponta ou operação da Sprint 3. A
fundação HTTP, pipeline de mídia e integração de speech-to-text (STT) estão
implementados. Os limites operacionais concretos e a política de reconciliação
de tentativas ainda serão definidos antes da operação do pipeline.

## 2. Objetivo da Sprint 3

Transformar um Reel já armazenado no Cloudflare R2 em um resultado tecnicamente
inspecionado e transcrito, pronto para a futura fase de análise, com:

- validação da identidade e integridade do arquivo;
- metadados técnicos normalizados;
- extração temporária de áudio quando necessária;
- transcrição por um contrato independente de fornecedor;
- resultados e tentativas persistidos separadamente do download;
- falhas explícitas, observáveis e passíveis de retry controlado.

A Sprint 3 não inclui classificação, tags, resumos, embeddings, OCR, análise
visual, busca ou organização do conhecimento. Essas responsabilidades não devem
ser antecipadas no modelo desta Sprint.

## 3. Fronteira da Sprint

### 3.1 Início

A Sprint 3 começa para um Reel quando:

1. `app.reels.status` indica download concluído;
2. existem `reel_id`, `shortcode`, `object_key` e `sha256` do original;
3. o objeto armazenado pode ser localizado no bucket privado do R2;
4. o n8n determina que não existe resultado aplicável para o mesmo input e a
   versão solicitada do pipeline;
5. o n8n cria uma nova tentativa de enriquecimento.

### 3.2 Fim

A Sprint 3 termina para uma tentativa quando:

1. o enriquecedor validou o objeto e seu SHA-256;
2. a mídia foi inspecionada;
3. os metadados técnicos mínimos foram normalizados;
4. o áudio foi tratado conforme sua presença ou ausência;
5. a transcrição terminou legitimamente ou foi registrado um outcome legítimo
   sem transcrição;
6. o n8n persistiu atomicamente o resultado e concluiu a tentativa; ou
7. o n8n registrou uma falha terminal da tentativa sem alterar o estado de
   download do Reel.

Um Reel continua `downloaded` mesmo quando seu enriquecimento está em
`processing`, `completed` ou `failed`.

## 4. Responsabilidades

### 4.1 n8n

O n8n permanece como orquestrador do produto e é responsável por:

- verificar a elegibilidade do Reel;
- localizar ou reutilizar um resultado já aplicável;
- criar o `attempt_id` e persistir a tentativa;
- chamar o enriquecedor;
- controlar estados e transições;
- validar a correlação entre request, response e tentativa;
- persistir o resultado canônico e o histórico de tentativas;
- decidir quando um retry lógico pode ser criado;
- registrar falhas de orquestração;
- encadear etapas posteriores somente quando a Sprint 3 estiver concluída.

### 4.2 Enriquecedor

O enriquecedor é um serviço especializado responsável por:

- autenticar e validar a requisição;
- validar o prefixo e a referência do objeto;
- ler o original diretamente do R2;
- verificar tamanho e SHA-256 quando fornecidos;
- executar `ffprobe` e normalizar metadados técnicos;
- extrair e normalizar áudio temporário quando necessário;
- chamar um adaptador de STT;
- normalizar respostas específicas de fornecedor;
- retornar sucesso legítimo ou erro HTTP explícito;
- remover os arquivos temporários ao final.

O enriquecedor não:

- acessa PostgreSQL;
- altera estados do produto;
- acessa Telegram;
- decide retries lógicos;
- recebe credenciais do R2 no request;
- persiste permanentemente o vídeo ou o áudio extraído;
- executa responsabilidades da Sprint 4.

## 5. Acesso ao Cloudflare R2

O enriquecedor lê o original diretamente pela interface compatível com S3 do
Cloudflare R2.

A credencial do enriquecedor deve:

- ser própria do serviço;
- permitir somente leitura;
- ser restrita ao bucket e ao prefixo necessários;
- não ser enviada pelo n8n no request.

O bucket é configuração do serviço. O request informa `object_key`, não um
bucket arbitrário. A chave deve estar no prefixo permitido e ser coerente com o
shortcode.

A identidade do input é vinculada a:

```text
object_key + expected_sha256
```

O enriquecedor calcula o SHA-256 do objeto lido e rejeita divergências. Isso
protege o processamento contra substituição do conteúdo sob uma chave
reutilizada.

## 6. Baseline de execução HTTP

A primeira versão usa HTTP síncrono.

Regras do baseline:

- o n8n mantém a chamada aberta até sucesso, erro ou timeout;
- o enriquecedor possui timeout interno explícito;
- o timeout do enriquecedor deve ser menor que o timeout do n8n;
- o cliente HTTP não deve fazer retry automático cego;
- cada execução lógica possui um `attempt_id`;
- erros técnicos ou contratuais usam HTTP não-2xx;
- resultados legítimos, inclusive sem áudio ou fala, usam HTTP 2xx;
- uma futura migração para jobs assíncronos permanece possível se o preflight
  técnico ou a operação demonstrarem que duração, limites do fornecedor ou
  confiabilidade tornam o modelo síncrono inadequado.

O valor concreto dos timeouts não está definido neste checkpoint.

## 7. Modelo conceitual de persistência

### 7.1 `app.reels`

#### Propósito

Representar a identidade do Reel e os fatos de captura, download e
armazenamento do original.

#### Campos relevantes para a Sprint 3

- `id`;
- `shortcode`;
- `status`;
- `storage_provider`;
- `storage_bucket`;
- `object_key`;
- `sha256`;
- `file_size_bytes`;
- `mime_type`;
- `downloaded_at`.

#### Relações

Um Reel pode possuir:

- zero ou mais resultados de enriquecimento;
- zero ou mais tentativas de enriquecimento.

#### Constraints relevantes

- `id` é a chave primária;
- `shortcode` deve permanecer coerente com a unicidade esperada pelo fluxo de
  entrada;
- um Reel só é elegível para enriquecimento quando `status = 'downloaded'`;
- `object_key` e `sha256` devem existir para um download concluído;
- SHA-256 deve ter 64 caracteres hexadecimais;
- `file_size_bytes`, quando presente, deve ser positivo.

#### Não pertence a `app.reels`

- estado ou retry count do enriquecimento;
- erro de enriquecimento;
- `attempt_id`;
- metadados técnicos da Sprint 3;
- transcrição;
- provider ou modelo de STT;
- `pipeline_version`;
- campos de classificação, embeddings, OCR ou análise visual.

### 7.2 `app.reel_enrichments`

#### Propósito

Guardar resultados concluídos e aceitos para uma combinação exata de Reel,
input e versão do pipeline.

A relação com `app.reels` é 1:N. Um Reel pode preservar resultados produzidos
para conteúdos ou versões de pipeline diferentes.

#### Identidade semântica

Existe no máximo um resultado para:

```text
reel_id
+ source_object_key
+ source_sha256
+ pipeline_version
```

O resultado aplicável é aquele cuja chave e hash correspondem ao input atual de
`app.reels` e cuja `pipeline_version` corresponde à versão solicitada pelo n8n.
Não é necessário um booleano `is_current`.

#### Campos necessários

Identidade e proveniência:

- `id` como chave primária gerada;
- `reel_id`;
- `source_attempt_id`;
- `source_object_key`;
- `source_sha256`;
- `source_size_bytes`;
- `pipeline_version`;
- `completed_at`.

Metadados técnicos:

- `container_format`;
- `media_duration_seconds`;
- `video_codec`;
- `video_width`;
- `video_height`;
- `audio_present`;
- `audio_codec`, quando houver áudio;
- `audio_sample_rate_hz`, quando houver áudio;
- `audio_channels`, quando houver áudio;
- `audio_duration_seconds`, opcional;
- `transcription_audio_format`, quando o STT for chamado;
- `transcription_audio_sample_rate_hz`, quando o STT for chamado;
- `transcription_audio_channels`, quando o STT for chamado;
- `transcription_audio_duration_seconds`, quando o STT for chamado.

Resultado de conteúdo:

- `outcome`;
- `transcript_text` completo, conforme o outcome;
- `transcript_language`, opcional.

Os campos consultáveis, filtráveis ou usados em regras de negócio permanecem
em colunas normais. O contrato não expõe granularidade por trecho ou palavra.
Timestamps, segmentação por palavra e segmentação semântica foram removidos do
escopo da Sprint 3. Somente `transcript_text` completo e
`transcript_language` serão armazenados; outras formas de segmentação poderão
ser estudadas no futuro.

#### Provider, modelo e versão do processador

Os campos abaixo pertencem à tentativa produtora, não são duplicados no
resultado:

- `enricher_version`;
- `stt_provider`;
- `stt_model`;
- `provider_request_id`.

O resultado obtém essa proveniência por `source_attempt_id`.

#### Chaves, relações e constraints

- PK em `id`;
- FK de `reel_id` para `app.reels.id`;
- FK de `source_attempt_id` para a tentativa;
- `UNIQUE(source_attempt_id)`;
- `UNIQUE(reel_id, source_object_key, source_sha256, pipeline_version)`;
- FK composta recomendada entre resultado e tentativa usando `attempt_id`,
  Reel, objeto, hash e pipeline;
- SHA-256 válido;
- tamanhos e durações não negativos;
- dimensões, sample rate e canais positivos;
- ausência de áudio exige campos de áudio original nulos;
- presença de áudio exige codec, sample rate e canais;
- os campos de áudio fornecido ao STT existem somente quando houve chamada ao
  STT;
- a coerência entre `outcome`, áudio e transcrição deve ser protegida por
  constraints.

A mesma transação deve inserir o resultado e alterar a tentativa para
`completed`. Assim, não deve existir resultado aceito cuja tentativa produtora
não tenha sido concluída.

#### Não pertence a `app.reel_enrichments`

- status de execução;
- erros e retryability;
- contador de tentativas;
- request options;
- logs ou stack traces;
- output bruto de `ffprobe`;
- payload bruto do fornecedor;
- vídeo ou áudio binário;
- campos da Sprint 4.

### 7.3 `app.reel_enrichment_attempts`

#### Propósito

Representar cada execução lógica e preservar seu input, configuração, estado,
proveniência operacional e eventual erro.

#### Campos necessários

- `attempt_id` como UUID e chave primária;
- `reel_id`;
- `source_object_key`;
- `expected_sha256`;
- `pipeline_version`;
- `contract_version`;
- `status`;
- `started_at`.

#### Campos opcionais ou condicionais

- `expected_size_bytes`;
- `language_hint`;
- `retry_of_attempt_id`;
- `finished_at` em estado terminal;
- `enricher_version`;
- `stt_provider`;
- `stt_model`;
- `provider_request_id`;
- `error_code` em `failed`;
- `error_stage` em `failed`;
- `error_message` em `failed`;
- `retryable` em `failed`.

Os parâmetros conhecidos do request permanecem em colunas normais. Não há um
campo genérico de request options em JSONB neste baseline.

#### Chaves, relações e constraints

- PK em `attempt_id`;
- FK de `reel_id` para `app.reels.id`;
- FK autorreferente em `retry_of_attempt_id`;
- um retry não aponta para si e deve pertencer ao mesmo Reel;
- SHA-256 válido;
- estados terminais exigem `finished_at`;
- `completed` não possui campos de erro;
- `failed` exige `error_code`, `error_stage`, `error_message` e `retryable`;
- uma tentativa terminal é imutável.

A menor unicidade ativa aprovada é:

```text
UNIQUE (
  reel_id,
  source_object_key,
  expected_sha256,
  pipeline_version
)
WHERE status = 'processing'
```

Essa constraint impede processamento simultâneo duplicado da mesma unidade
lógica sem bloquear versões diferentes do pipeline.

#### Não pertence a `app.reel_enrichment_attempts`

- resultado técnico canônico;
- transcrição canônica;
- contador derivável de retries;
- payloads brutos;
- binários;
- segredos;
- estado de download;
- campos da Sprint 4.

## 8. Estados e transições

O baseline aprovado não usa `pending`.

### 8.1 `processing`

Significa que o n8n criou uma execução lógica e iniciou o procedimento de
chamada ao enriquecedor.

- entrada: o n8n insere a tentativa imediatamente antes do POST;
- saída: resposta aceita, erro, timeout ou reconciliação;
- responsável pelas transições: n8n.

### 8.2 `completed`

Significa que o processamento terminou legitimamente e o resultado foi
persistido.

- entrada: transação que insere o resultado e conclui a tentativa;
- saída: nenhuma;
- estado terminal;
- responsável pela transição: n8n.

Uma tentativa `completed` pode produzir os outcomes `transcribed`, `no_audio`
ou `empty_transcript`.

### 8.3 `failed`

Significa que a execução não produziu um resultado aceito por falha técnica,
contratual ou por resultado desconhecido após timeout.

- entrada: erro recebido, timeout ou reconciliação de tentativa órfã;
- saída: nenhuma;
- estado terminal;
- responsável pela transição: n8n.

### 8.4 Transições válidas

```text
processing ───> completed
     │
     └────────> failed
```

Tentativas finalizadas não voltam a `processing`. Ausência legítima de áudio,
fala ou texto não é `failed`.

## 9. Resultado por input e pipeline

A unidade lógica de processamento é:

```text
reel_id
+ source_object_key
+ expected_sha256
+ pipeline_version
```

Antes de criar uma tentativa, o n8n procura um resultado com a mesma identidade.
Se existir:

- não cria tentativa;
- não chama o enriquecedor;
- reutiliza o resultado.

Um resultado para outra versão do pipeline permanece preservado, mas não
satisfaz a versão solicitada.

## 10. Retry e `attempt_id`

O `attempt_id` identifica uma execução lógica e aparece:

- no PostgreSQL;
- no header de idempotência;
- no request;
- no response;
- no envelope de erro;
- nos logs de correlação.

Regras:

- uma tentativa finalizada é imutável;
- uma falha confirmada com retry permitido cria nova tentativa e novo UUID;
- `retry_of_attempt_id` referencia a tentativa anterior;
- o cliente HTTP não reenvia automaticamente a mesma chamada;
- somente uma tentativa `processing` pode existir para a mesma unidade lógica.

## 11. Idempotência e sua limitação aprovada

Dentro do mesmo processo ativo do enriquecedor:

- a mesma requisição e o mesmo `attempt_id` não iniciam processamento paralelo;
- se ainda estiver executando, o serviço responde `ATTEMPT_IN_PROGRESS` ou
  compartilha a execução;
- se estiver concluída e a resposta ainda estiver em cache, o serviço devolve a
  mesma resposta;
- o mesmo `attempt_id` com fingerprint diferente responde
  `ATTEMPT_CONFLICT`.

A garantia aprovada para esta Sprint é somente em memória. Ela não é durável
após:

- restart do enriquecedor;
- substituição da instância;
- perda do processo;
- expiração do cache.

Não será adicionado um ledger durável ao enriquecedor nesta Sprint. Essa
limitação deixa um risco residual de processamento ou custo duplicado quando a
resposta se perde e o registro em memória deixa de existir.

## 12. Contrato `POST /v1/enrichments`

### 12.1 Headers

| Campo | Tipo | Obrigatório | Origem | Finalidade |
| --- | --- | --- | --- | --- |
| `Content-Type` | `application/json` | sim | n8n | Formato do body |
| `X-MegaBrain-Key` | string | sim | credencial interna | Autenticação |
| `Idempotency-Key` | UUID | sim | `attempt_id` | Correlação e idempotência no processo ativo |

`Idempotency-Key` deve ser igual a `attempt_id`.

### 12.2 Request

| Campo | Tipo | Obrigatório | Origem | Finalidade |
| --- | --- | --- | --- | --- |
| `contract_version` | string | sim | configuração do n8n | Versão do contrato |
| `attempt_id` | UUID | sim | tentativa | Identidade da execução |
| `reel_id` | inteiro positivo de 64 bits | sim | `app.reels.id` | Identidade interna |
| `shortcode` | string validada | sim | `app.reels.shortcode` | Correlação e validação da chave |
| `object_key` | string não vazia | sim | `app.reels.object_key` | Localizar o original |
| `expected_sha256` | hex lowercase com 64 caracteres | sim | `app.reels.sha256` | Verificar integridade |
| `expected_size_bytes` | inteiro positivo de 64 bits | não | `app.reels.file_size_bytes` | Verificação antecipada |
| `pipeline_version` | string não vazia | sim | configuração do n8n | Identidade semântica do pipeline |
| `language_hint` | string | não | política do produto | Sugerir idioma |

O request não contém bucket, endpoint, credenciais, provider, modelo, `force`,
Telegram, estado do banco ou booleano `success`.

### 12.3 Response HTTP 2xx

HTTP 2xx significa que o processamento terminou legitimamente. Isso inclui
`no_audio` e `empty_transcript`.

| Campo | Tipo | Obrigatório | Finalidade |
| --- | --- | --- | --- |
| `contract_version` | string | sim | Versão efetiva |
| `attempt_id` | UUID | sim | Correlação |
| `reel_id` | inteiro | sim | Correlação |
| `shortcode` | string | sim | Correlação humana |
| `pipeline_version` | string | sim | Pipeline executado |
| `processor_version` | string | sim | Versão do enriquecedor |
| `source.object_key` | string | sim | Objeto efetivamente lido |
| `source.sha256` | string | sim | Hash calculado |
| `source.size_bytes` | inteiro | sim | Tamanho calculado |
| `media.container_format` | string | sim | Container normalizado |
| `media.duration_seconds` | número não negativo | sim | Duração total |
| `media.video.codec` | string | sim | Codec de vídeo |
| `media.video.width` | inteiro positivo | sim | Largura |
| `media.video.height` | inteiro positivo | sim | Altura |
| `media.audio` | objeto ou `null` | sim | Stream de áudio original |
| `media.audio.codec` | string | condicional | Codec original |
| `media.audio.sample_rate_hz` | inteiro positivo | condicional | Sample rate original |
| `media.audio.channels` | inteiro positivo | condicional | Canais originais |
| `media.audio.duration_seconds` | número ou `null` | não | Diagnóstico |
| `transcription_input` | objeto ou `null` | sim | Input efetivo do STT |
| `transcription_input.format` | string | condicional | Formato enviado ao STT |
| `transcription_input.sample_rate_hz` | inteiro positivo | condicional | Sample rate enviado |
| `transcription_input.channels` | inteiro positivo | condicional | Canais enviados |
| `transcription_input.duration_seconds` | número não negativo | condicional | Duração enviada |
| `transcription.outcome` | enum | sim | Resultado do conteúdo |
| `transcription.transcript_text` | string ou `null` | sim | Texto completo quando aplicável |
| `transcription.transcript_language` | string ou `null` | sim | Idioma quando disponível |
| `transcription.engine.provider` | string ou `null` | sim | Provider efetivo |
| `transcription.engine.model` | string ou `null` | sim | Modelo efetivo |
| `transcription.engine.request_id` | string ou `null` | sim | Correlação externa |
| `processing.started_at` | timestamp UTC | sim | Início interno |
| `processing.completed_at` | timestamp UTC | sim | Fim interno |
| `warnings` | array de strings | sim | Avisos não fatais |

Não existe booleano `success`. A semântica é:

- HTTP 2xx: processamento concluído legitimamente;
- HTTP não-2xx: falha técnica ou contratual.

Depois de autenticar, validar o body e confirmar que `Idempotency-Key` é igual a
`attempt_id`, o endpoint executa leitura verificada do R2, inspeção, extração
temporária quando existe áudio e transcrição.

### 12.4 Erro HTTP não-2xx

Todo erro usa o envelope:

| Campo | Tipo | Obrigatório | Finalidade |
| --- | --- | --- | --- |
| `error_code` | string estável | sim | Classificação programática |
| `stage` | string estável | sim | Etapa da falha |
| `message` | string sanitizada | sim | Diagnóstico sem segredo ou stack trace |
| `retryable` | boolean | sim | Orientação técnica, sem retry automático |
| `attempt_id` | UUID ou `null` | sim | Correlação quando extraível |

Stages do enriquecedor:

- `input`;
- `r2_download`;
- `integrity`;
- `probe`;
- `audio_extract`;
- `transcription`;
- `internal`.

`orchestration` pode ser persistido pelo n8n para falhas externas ao serviço,
mas não é retornado pelo enriquecedor.

Códigos arquiteturalmente previsíveis:

- `INVALID_REQUEST`;
- `UNAUTHORIZED`;
- `ATTEMPT_IN_PROGRESS`;
- `ATTEMPT_CONFLICT`;
- `OBJECT_NOT_FOUND`;
- `OBJECT_ACCESS_DENIED`;
- `OBJECT_READ_FAILED`;
- `INTEGRITY_MISMATCH`;
- `UNSUPPORTED_MEDIA`;
- `VIDEO_STREAM_MISSING`;
- `PROBE_FAILED`;
- `AUDIO_EXTRACTION_FAILED`;
- `STT_AUTH_FAILED`;
- `STT_RATE_LIMITED`;
- `STT_TIMEOUT`;
- `STT_UNAVAILABLE`;
- `STT_REQUEST_REJECTED`;
- `STT_SYNC_RECOGNIZE_UNSUPPORTED`;
- `STT_FAILED`;
- `PROCESSING_TIMEOUT`;
- `INTERNAL_ERROR`.

`RESULT_UNKNOWN` é um código de orquestração persistido pelo n8n quando não é
possível confirmar o resultado após timeout. Ele não é retornado pelo
serviço.

## 13. Metadados técnicos aprovados

Os dados persistidos têm utilidade concreta para integridade, transcrição,
diagnóstico ou decisões futuras de processamento:

- chave, SHA-256 e tamanho efetivamente verificados;
- container;
- duração total;
- codec, largura e altura do vídeo;
- presença do áudio;
- codec, sample rate e canais do áudio original;
- duração do áudio original, quando disponível;
- formato, sample rate, canais e duração do áudio normalizado enviado ao STT.

Não são persistidos neste baseline:

- dump bruto do `ffprobe`;
- bitrate;
- frame rate;
- pixel format;
- aspect ratio;
- rotation;
- tags do container;
- thumbnails;
- metadata visual;
- payload bruto do fornecedor.

## 14. Outcomes do conteúdo

O status da tentativa e o outcome do conteúdo são dimensões distintas:

```text
attempt.status:
  processing
  completed
  failed

completed result.outcome:
  transcribed
  no_audio
  empty_transcript
```

### 14.1 `transcribed`

- há áudio;
- o STT terminou com sucesso;
- o texto normalizado é não vazio;
- a tentativa termina `completed`.

### 14.2 `no_audio`

- o vídeo é válido;
- não existe stream de áudio;
- extração de áudio e STT não são executados;
- texto e idioma são nulos;
- provider e modelo são nulos;
- a tentativa termina `completed`.

### 14.3 `empty_transcript`

- existe áudio;
- o STT terminou tecnicamente com sucesso;
- o texto normalizado é vazio;
- não existe evidência suficiente para afirmar ausência de fala;
- não é falha técnica;
- provider e modelo permanecem registrados;
- a tentativa termina `completed`.

`no_speech` não é inferido nem retornado nesta versão. Distinguir silêncio,
música e fala exige evidência adicional; VAD e heurísticas permanecem fora do
escopo atual.

### 14.4 Falhas técnicas

Erro de extração:

- `status = failed`;
- `error_code = AUDIO_EXTRACTION_FAILED`;
- `error_stage = audio_extract`;
- nenhum resultado é inserido.

Erro de STT:

- `status = failed`;
- `error_stage = transcription`;
- código de erro normalizado;
- nenhum resultado é inserido.

Um resultado anterior permanece preservado quando uma nova tentativa falha.

## 15. Caso ainda a fechar antes da implementação

### Reconciliação de tentativas processing órfãs/stale

O n8n pode persistir uma tentativa como `processing` e falhar antes ou durante o
`POST /v1/enrichments`. Nesse cenário, o PostgreSQL pode manter uma tentativa
ativa sem conhecimento suficiente para determinar se:

- o enriquecedor nunca recebeu a chamada;
- o enriquecedor ainda está processando;
- o enriquecedor terminou, mas a resposta foi perdida;
- o processo do enriquecedor foi interrompido;
- houve chamada ao fornecedor de STT e possível custo externo.

Enquanto a tentativa permanecer `processing`, a constraint de unicidade ativa
impede outra execução para a mesma combinação de Reel, objeto, hash e pipeline.

Antes da implementação, deve ser definida uma política de reconciliação que
estabeleça:

- como identificar uma tentativa stale;
- qual componente executa a reconciliação;
- qual margem existe entre o timeout interno e a classificação como stale;
- quando `processing` pode ser concluído como `failed`;
- qual código e stage registrar, incluindo o uso de `RESULT_UNKNOWN` e
  `orchestration`;
- quando um novo retry lógico pode ser criado;
- como reduzir o risco de processamento ou custo duplicado.

O timeout concreto não é definido neste documento. A política de reconciliação
deve ser aprovada antes da implementação.

## 16. Decisão inicial de STT e preflight técnico

### 16.1 Implementação inicial escolhida

Por decisão do responsável, a implementação inicial da Sprint 3 será o Google
Cloud Speech-to-Text V2 com o modelo Chirp 3.

A escolha é motivada pela intenção de criar uma nova conta Google Cloud
elegível a trial ou crédito promocional e utilizar esses créditos iniciais para
desenvolver e validar a transcrição do MegaBrain. Créditos promocionais são
somente uma motivação para a escolha inicial: não constituem propriedade,
premissa permanente ou dependência da arquitetura.

O benchmark competitivo entre múltiplos fornecedores foi removido do escopo da
Sprint 3. Outros provedores não serão avaliados no escopo inicial.
`faster-whisper` também fica fora do desenho operacional atual: embora possa
executar em CPU, não é considerado adequado para compartilhar os recursos do
KVM2 com os demais serviços do MegaBrain.

Essa decisão não cria dependência arquitetural permanente com o Google. A
arquitetura aprovada permanece:

```text
MegaBrain
→ STT Adapter
→ Google Cloud Speech-to-Text
```

O contrato interno e a normalização do adaptador permanecem independentes do
fornecedor, permitindo substituição futura caso surja uma necessidade real. O
fornecedor e o modelo efetivamente usados continuam registrados em cada
tentativa por `stt_provider` e `stt_model`, preservando a proveniência.

### 16.2 Preflight técnico realizado

O preflight real confirmou:

- autenticação com Service Account;
- Google Cloud Speech-to-Text V2;
- modelo Chirp 3 com `pt-BR`;
- disponibilidade de `ffmpeg` e `ffprobe` no fluxo testado;
- transcrição clara de uma amostra falada de 45 segundos.

Uma amostra contendo somente música gerou texto, caracterizando um falso
positivo conhecido. Por isso, resposta vazia continua insuficiente para afirmar
ausência de fala, e texto retornado pelo fornecedor também não comprova sozinho
que havia fala. VAD não será implementado nesta etapa.

A implementação inicial usa somente `Recognize` síncrono. Processamentos cuja
mídia exceda os limites dessa operação devem falhar com erro explícito e
estável (`STT_SYNC_RECOGNIZE_UNSUPPORTED`, stage `transcription`, não
retryable), sem fallback silencioso. O adapter aplica os limites atuais de 10 MB
ou 60 segundos, o que ocorrer primeiro; a duração deverá ser fornecida pelo
futuro estágio de inspeção da mídia. `BatchRecognize` fica fora desta fundação e
deve ser objeto de decisão posterior, inclusive quanto ao uso de armazenamento
temporário no fornecedor.

Permanecem aprovados:

- n8n como orquestrador e responsável pela persistência;
- enriquecedor sem acesso ao PostgreSQL;
- leitura direta e read-only do R2;
- identidade do input por chave e hash;
- separação entre resultados e tentativas;
- tentativa nova para cada retry lógico;
- estados `processing`, `completed` e `failed`;
- semântica HTTP sem booleano `success`;
- outcomes definidos neste documento.
