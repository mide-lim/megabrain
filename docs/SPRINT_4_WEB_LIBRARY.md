# Sprint 4 — Web Library

Status: Discovery concluído / implementação pendente

## 1. Objetivo

Transformar os Reels já capturados, armazenados e transcritos pelo
MegaBrain em uma biblioteca web pessoal para consulta e curadoria manual.

O objetivo principal não é classificar conteúdo automaticamente.

O usuário deverá conseguir:

- visualizar os Reels armazenados;
- reproduzir o vídeo;
- consultar a descrição original do autor;
- consultar a transcrição;
- pesquisar conteúdo textual;
- criar categorias;
- associar manualmente um Reel a uma ou mais categorias;
- remover associações de categorias.

A curadoria permanece humana.

---

## 2. Princípio do produto

O MegaBrain deve priorizar:

Capture
→ Storage
→ Transcription
→ Retrieval
→ Manual Curation
→ Reuse

A automação por IA para classificação, resumo, keywords, topics,
embeddings ou análise semântica não faz parte desta Sprint.

IA continua sendo utilizada para desenvolvimento e orquestração do
projeto por meio dos agentes de desenvolvimento.

Google Speech-to-Text permanece como serviço de transcrição.

---

## 3. Fontes de informação do Reel

O conteúdo textual deve permanecer separado por origem.

### Caption

Descrição original publicada pelo autor junto ao Reel.

É tratada como conteúdo original e não deve ser alterada pelo sistema.

### Transcript

Texto obtido a partir do áudio pelo pipeline de enrichment.

É armazenado separadamente da caption.

### Vídeo

Arquivo armazenado no Cloudflare R2.

O vídeo não deve ser armazenado novamente na aplicação Web.

---

## 4. Escopo da Web Library

### Biblioteca

A página principal deverá permitir:

- listar Reels;
- mostrar cards;
- visualizar creator;
- visualizar trecho da caption;
- visualizar categorias;
- visualizar data de captura;
- filtrar por categoria;
- pesquisar.

### Página do Reel

Deverá mostrar:

- player de vídeo;
- creator;
- data;
- duração;
- link para o Reel original;
- caption original;
- transcript;
- categorias associadas.

Também deverá permitir:

- copiar caption;
- copiar transcript;
- adicionar categoria;
- remover categoria;
- criar nova categoria.

---

## 5. Categorias

As categorias serão criadas manualmente pelo usuário.

Exemplos iniciais possíveis:

- Hands-on
- Culinária
- IoT
- Tech

A lista não será fixa no código.

Um Reel poderá pertencer a múltiplas categorias.

Exemplo:

Reel
├── IoT
├── Tech
└── Hands-on

---

## 6. Busca

A primeira versão utilizará somente pesquisa textual tradicional.

Campos pesquisáveis:

- creator;
- caption;
- transcript.

Não serão utilizados nesta Sprint:

- embeddings;
- busca vetorial;
- classificação por IA;
- busca semântica.

A primeira implementação poderá utilizar consultas simples no
PostgreSQL.

PostgreSQL Full Text Search poderá ser avaliado posteriormente se
necessário.

---

## 7. Arquitetura proposta

Browser
↓
Caddy
├── HTTPS
├── Basic Auth
└── Reverse Proxy
↓
MegaBrain Web
├── PostgreSQL
└── Cloudflare R2

### Serviço Web

Tecnologias propostas:

- FastAPI;
- Jinja2;
- HTML/CSS;
- HTMX somente onde interações parciais forem úteis.

Não será criada inicialmente uma SPA ou frontend separado.

Não fazem parte do MVP:

- React;
- Next.js;
- API pública separada;
- frontend/backend como projetos independentes.

---

## 8. Responsabilidades

### n8n

Ingestão e orquestração.

### Downloader

Download dos arquivos de mídia.

### Enricher

Metadata, processamento de áudio e transcrição.

### PostgreSQL

Dados estruturados e pesquisáveis:

- Reels;
- captions;
- transcripts;
- categorias;
- relacionamentos de categorias.

### Cloudflare R2

Arquivos pesados, principalmente vídeos.

### Web

Visualização e curadoria manual.

### Caddy

- entrada HTTP/HTTPS;
- TLS;
- autenticação;
- reverse proxy.

---

## 9. Acesso aos vídeos

O bucket R2 permanecerá privado.

O serviço Web não deverá transmitir o vídeo inteiro através da VPS.

Fluxo planejado:

Browser
↓
MegaBrain Web
↓
gera URL assinada temporária
↓
Browser
↓
Cloudflare R2

Assim, o R2 entrega diretamente o arquivo ao navegador.

As credenciais R2 nunca devem ser expostas ao browser.

---

## 10. Autenticação

A Web Library será inicialmente pessoal e privada.

A autenticação MVP será:

- Caddy Basic Auth;
- HTTPS obrigatório;
- usuário único.

A senha em texto puro não deve ser armazenada no Caddyfile.

Deverá ser utilizado somente o hash apropriado para autenticação.

Ficam fora do escopo:

- cadastro;
- multiusuário;
- OAuth;
- recuperação de senha;
- roles;
- sistema próprio de sessões.

---

## 11. Modelo de dados adicional

O modelo atual de Reels e enrichments será preservado.

A Sprint 4 deverá acrescentar conceitualmente:

### app.categories

- id
- name
- created_at

### app.reel_categories

- reel_id
- category_id
- created_at

O relacionamento deve permitir múltiplas categorias por Reel.

Deve existir unicidade para:

(reel_id, category_id)

---

## 12. Estados da interface

A aplicação deverá apresentar estados compreensíveis para o usuário.

### Processado

- vídeo disponível;
- caption disponível quando existente;
- transcript disponível.

### Sem fala/transcrição

A interface deverá informar que não existe transcrição disponível sem
expor detalhes internos do pipeline.

### Processando

A página poderá informar que o conteúdo ainda está sendo processado.

Não será necessário realtime ou WebSocket no MVP.

---

## 13. Fora do escopo

Não fazem parte da Sprint 4:

- classificação automática;
- análise de conteúdo por IA;
- summaries automáticos;
- keywords automáticas;
- embeddings;
- OCR;
- análise visual;
- edição da caption;
- edição do transcript;
- timestamps do transcript;
- recomendação automática;
- compartilhamento público;
- comentários;
- multiusuário;
- exclusão definitiva de Reel;
- WebSocket/realtime;
- dashboards;
- analytics.

---

## 14. Entregas planejadas

### Entrega 1 — Web Foundation

- serviço FastAPI;
- acesso ao PostgreSQL;
- health endpoint;
- Dockerfile;
- integração com Docker Compose.

### Entrega 2 — Library

- listagem de Reels;
- cards;
- paginação;
- dados básicos.

### Entrega 3 — Reel Detail

- detalhe do Reel;
- player;
- signed URL R2;
- caption;
- transcript;
- metadata útil.

### Entrega 4 — Manual Curation

- migration categories;
- migration reel_categories;
- criação de categorias;
- associação;
- remoção.

### Entrega 5 — Search

- creator;
- caption;
- transcript;
- filtro por categoria.

### Entrega 6 — Private Deploy

- Caddy;
- HTTPS;
- Basic Auth;
- serviço Web sem porta pública.

### Entrega 7 — E2E / Milestone QA

Validar:

Browser
→ Caddy/Auth
→ Web
→ PostgreSQL
→ R2

e:

Reel
→ visualizar
→ assistir
→ ler caption
→ ler transcript
→ categorizar
→ pesquisar

---

## 15. Critério de conclusão

Sprint 4 estará concluída quando o usuário conseguir:

1. abrir a Web Library de forma autenticada;
2. visualizar os Reels armazenados;
3. abrir um Reel;
4. reproduzir o vídeo diretamente do R2;
5. consultar caption e transcript separadamente;
6. criar categorias;
7. associar/remover categorias manualmente;
8. filtrar por categoria;
9. pesquisar creator, caption e transcript.

A Sprint deve entregar uma biblioteca utilizável antes de introduzir
novas camadas de automação.
