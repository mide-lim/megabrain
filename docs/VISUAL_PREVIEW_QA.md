# Preview e QA visual na VPS

O comando usa o Next real do candidato e uma API de dados sintéticos em
processos próprios. O browser e esses servidores executam no mesmo namespace.
Os fixtures não acessam PostgreSQL, OIDC, R2, n8n ou STT reais.

## Executar

No checkout isolado, usando Node compatível e sem arquivos .env de produção:

```sh
cd apps/web
npm ci
npx playwright install chromium
npm run qa:visual
```

Em uma imagem nova, instalar as bibliotecas do Chromium na preparação do
runtime. A ferramenta exige mudanças commitadas e Git limpo. Ela compila com
um worker e heap V8 de 1536 MiB; são limites de build/heap, não um cgroup.
Build e testes têm timeout de dez minutos cada; CI limita o job a quinze minutos.
Não executar outro build em paralelo no piloto.

Os 12 casos desktop/mobile verificam login sintético, navegação, conteúdo,
estados da biblioteca/transcrição e disponibilidade do Paperclip. Transcrição
em fixtures apenas muda um objeto em memória; não gera jobs nem custo de STT.
Screenshots cobrem também /development online e indisponível.

Portas padrão 38000–38002, somente em 127.0.0.1; VISUAL_PREVIEW_PORT escolhe a
porta inicial. Porta ocupada falha, sem reutilizar outro processo. Servidores
encerram após os testes; preview manual encerra após quinze minutos.

## Evidências

- apps/web/test-results/visual-evidence.json: SHA, branch, estado Git, build ID,
  hash do entrypoint, escopo e resultado.
- apps/web/test-results/visual-results.json: detalhes dos casos.
- apps/web/test-results/visual/: screenshots e traces.
- apps/web/playwright-report/index.html: relatório navegável.

O hash do entrypoint identifica esse arquivo, não todo um artefato de produção.
workingTreeDirty=false e identityStable=true fixam o snapshot de código.
productionEligible=false: fixtures não comprovam auth/backend/integrações reais.
Ler JSON, screenshots pertinentes e falhas; repetir somente quando candidato,
critério ou falha justificar nova execução.

Depois de QA aprovado, inspecionar o mesmo build:

```sh
npm run preview:visual
```

A URL é http://127.0.0.1:38000/login no namespace do processo ou por túnel
autorizado. Não publicar a porta do servidor de fixtures na internet.
O build precisa corresponder ao commit limpo que produziu a evidência aprovada.

## GitHub Actions e Paperclip

Visual QA roda em PRs de frontend/tools para dev/main e por workflow_dispatch.
Checkout fixa o HEAD do PR; actions ficam pinadas por SHA, com permissão de
leitura, um worker, cancelamento por PR e artifacts retidos por sete dias.
Minutos e armazenamento seguem as cotas GitHub. Nenhum modelo ou deploy é chamado.

O próximo run nativo Paperclip recebe pacote, commit e comandos na descrição
da tarefa e usa o worktree próprio. Capturar checkpoint após WIP commitado;
retomar com [session_context](SESSION_CONTEXT.md) e a referência canônica real.
Acesso à API deve vir da sessão/credencial normal, sem copiar tokens para arquivos
versionados ou criar um ledger. Upload de HTML/JSON/PNG e preview no cockpit
exigem registro real e caminho autenticado ainda a comprovar no piloto.
O loopback da VPS e o do container são distintos; validar browser/serviços juntos.

## Piloto e produção

A preparação não altera o texto do produto. CTX-PILOT-001 trocará apenas
“Paperclip online” por “Paperclip disponível” após registro real e base fixada.
Baseline visual e critérios estão no [pacote](tasks/CTX-PILOT-001/PACKET.md).
Review independente compara esse candidato e a referência visual.
Merge, gates e capability de produção continuam os existentes; QA de fixtures
não constitui autorização nem recibo de deploy.
