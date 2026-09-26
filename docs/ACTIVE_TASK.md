# MegaBrain — Active Task

## Tarefa atual

**F6 — Transcript on Demand: COMPLETE / PRODUCTION ACCEPTED / OPERATIONAL.**

O fechamento operacional em produção foi aceito em 2026-09-26. F6 foi
priorizado antes de F5 Categories por decisão de produto; F5 Categories foi
adiado, não cancelado.

Capture != transcription. Salvar um Reel não solicita transcrição
automaticamente: depois do download, novos Reels permanecem em
`downloaded | not_requested`. O proprietário autenticado solicita
explicitamente `Transcrever`.

FastAPI/Web somente aplica a transição de intenção limitada
`not_requested|failed -> queued`. MGB-030 continua como a autoridade exclusiva
de processamento para `queued -> processing -> completed|failed` e permanece
ativo em produção como consumidor periódico. A versão ativa aceita de MGB-030
é `7cd5819c-83c8-41ea-ab07-1c86099de886`.

O TC5 real E2E passou. O Reel #28 (`DbW1ECDMAyj`) percorreu Add Reel,
`downloaded | not_requested`, clique humano em `Transcrever`, `queued`, claim
periódico normal de MGB-030, `processing`, Google BatchRecognize e `completed`;
o transcript `pt-BR` ficou visível na Web e o cleanup temporário no GCS foi
confirmado.

F5.1 — Add Reel UX permanece como histórico aceito em produção. O Reel #26
(`DdcX68ZRQun`) preserva sua tentativa histórica original com
`STT_SYNC_RECOGNIZE_UNSUPPORTED`; posteriormente foi resolvido por um novo claim
normal do F6, com `retry_of_attempt_id = NULL`, e terminou `completed` sem
alterar a tentativa histórica.

A fila final ficou vazia, sem Reel em `processing` pendente. O smoke final
observou três execuções periódicas MGB-030 bem-sucedidas, e o workflow permaneceu
ACTIVE. O próximo passo de produto é discovery/reassessment de F5 Categories;
nenhuma F7 ou outra feature fica aprovada implicitamente. Futuras mutações de
produção continuam separadamente human-gated.

## Estado

Engineering Enablement Phase A: COMPLETE.

Engineering Enablement Phase B: COMPLETE / PROMOTED.

B3 — CI Foundation: COMPLETE / PROMOTED.

B4 — Hermes Autonomy Foundation: COMPLETE / PROMOTED.

- B4.1 — GitHub Auth Bootstrap: `COMPLETE / PROMOTED`.
- B4.2 — Autonomous PR Lifecycle: fonte canônica v1.1.0 e instalação ativa
  reconciliadas com paridade byte a byte; o uso operacional continua limitado
  às autorizações normais do lifecycle.
- B4.3 — Bounded Run Authorization: `COMPLETE / PROMOTED`.

CI isolada existe para Pull Requests destinados a `dev` e `main`. Staging ainda
não existe.

## Restrições permanentes

- Seguir `AGENTS.md`.
- Agentes não acessam produção, Docker, segredos, `.env` de produção, banco real,
  n8n real ou o workspace de produção.
- GitHub é a fonte de verdade de desenvolvimento.
- Hermes trabalha em `agent/*`.
- Hermes não tem autoridade para merge, auto-merge, force push, escrita direta
  em `dev` ou `main`, mutação de workflows, rulesets ou permissões do GitHub App,
  nem interfaces genéricas e irrestritas de Git, API ou shell.
- Sem acesso à produção ou deploy automático. Merge humano permanece uma
  fronteira de autoridade separada.
- Toda ação de produção permanece human-gated.
