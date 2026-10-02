# Checkpoint — preparação do primeiro piloto organizado

Data: 2026-10-02, America/Sao_Paulo. Manutenção autorizada por Michel.
Origem preparatória: PR #90. Paperclip issue/run ainda não registrados.
Worktree: /home/megabrain-hermes/workspace/orchestration-context-preflight-20261002.
Branch local agent/orchestration-context-preflight-20261002; publicação PR #90
em agent/context-foundation-20261001. Base 4b7cec7ee3f9790b58716e5bd0129e26f052ee28.

## Realizado e escolhas

- Modelo do piloto: Paperclip nativo com Codex MEGABRAIN existente.
- Scope: label “Paperclip online” → “Paperclip disponível” após registro real.
- Pacote preparado em docs/tasks/CTX-PILOT-001/PACKET.md, com fases e critérios.
- Preview anterior reaproveitado na base atual sem atualizar Next/React.
- QA usa 12 casos desktop/mobile, um worker, heap de build 1536 MiB e fixtures.
- URL loopback, portas próprias, timeout e TTL; artifacts fixam commit/build.
- CI visual preparado para HEAD exato, leitura e retenção de sete dias.
- Nenhum texto ou comportamento do produto foi implementado nesta preparação.

## Acesso Paperclip comprovado

O /usr/bin/node do host é v18.19.1 e não executa o CLI atual (node:sqlite ausente).
O runtime existente /home/megabrain-hermes/.local/bin/node é v26.7.0 e executa
o CLI. auth whoami retornou API 401: Board authentication required.
Nenhuma sessão board armazenada/utilizável foi confirmada nesta execução.

O fork fornece auth login com challenge de autorização aprovado pelo usuário
no navegador; a solicitação indica a company e não pede instance_admin.
Permissões efetivas continuam dependentes da conta/memberships. Ele salva
a credencial pelo cliente oficial, com modo 0600, somente após aprovação.
URL/challenge/token de autorização não pertence ao Git ou ao checkpoint.
Modelos continuam pela assinatura; esse acesso é do Paperclip.

## Evidências e pendências

VPS: npm run lint e npm run typecheck passaram; npm test passou (71/71).
Sintaxe dos três scripts de preview conferida com o Node do QA.
Dependências instaladas: Next 16.3.4, Playwright 1.63.0; 29 links conferidos.

Resultados finais de QA, build e CI desta preparação devem ser lidos do
candidato exato no PR e da visual-evidence.json; não herdam aprovação de 4b7.
Depois de publicar, sincronizar o worktree por comparação da árvore e salvar
nova projeção. Snapshot 4b7 é histórico após avanço do HEAD.

Pendente: aprovação do challenge normal do CLI; registrar IDs reais;
conferir projeto/worktree/limites pelo runtime; Run A/Run B e reviewer;
upload/proxy autenticado no cockpit e eventual gate/deploy/recibo.
Não há execução AP0 nem provisionamento de seu profile nesta lane.
Preservar checkout anterior e seu índice. Novo contexto não autoriza reset,
adoção de recurso alheio, merge protegido ou publicação de produção.
