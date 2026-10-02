# Task Packet — CTX-PILOT-001

## Identidade e autoridade

- Status: DISCOVERY; preparação pronta, issue/run real aguardam acesso autenticado.
- CTX-PILOT-001 é nome documental, não ID canônico fabricado.
- Origem de estado escolhida: Paperclip nativo; executor Codex MEGABRAIN existente.
- IDs existentes de referência: company 62eb0667-5669-408c-b8dc-74a1bc8b0757;
  executor c9487f45-02f6-4da4-9f85-dfe2c1154066. Conferir na API antes de admitir.
- Registro preparatório: https://github.com/mide-lim/megabrain/pull/90.
- Registrar issue_id/run_id reais antes de implementar e fixar revisão deste pacote.
- Um implementador ativo; reviewer em outra sessão. Nenhum novo agente permanente.
- AP0 não é a lane escolhida deste piloto; seus serviços e autoridade permanecem intactos.
- Instruções: AGENTS.md e apps/web/AGENTS.md; D022, D020/D021 e gates existentes.

## Objetivo e mudança proposta

Provar execução/pausa/retomada/QA rastreáveis em uma alteração pequena:
na página /development, substituir apenas o estado positivo “Paperclip online”
por “Paperclip disponível”. Estado “Indisponível”, layout, estilos, links,
botão, autenticação, API e significado do booleano permanecem iguais.
É esclarecimento textual reversível; não é redesign.

## Referências e Git

- Repo: mide-lim/megabrain; branch da implementação agent/context-pilot-001-20261002.
- Base preparatória: 4b7cec7ee3f9790b58716e5bd0129e26f052ee28.
- Base de execução: fixar o commit que contém esta preparação e o QA aprovado.
- Worktree nativo: identificar pela API e Git real depois do registro; não
  reutilizar o checkout de outra tarefa. O cwd precisa ser visível ao executor.
- Contrato: ../../TASK_CONTRACT_CTX_PILOT_001.md.
- Continuidade: ../../SESSION_CONTEXT.md; preview: ../../VISUAL_PREVIEW_QA.md.
- ADRs/arquitetura: ../../DECISIONS.md e ../../ARCHITECTURE.md no commit fixado.
- Baseline: screenshots /development online/offline desktop/mobile do QA da base.
- Anotação: comparar o texto role=status no cartão “Cockpit Paperclip”; todas
  as demais regiões, hierarquia e estados devem corresponder à baseline.
- Não tratar uma screenshot de commit antigo como evidência do candidato novo.

## Escopo de implementação

- apps/web/src/app/development/development-page-content.tsx.
- apps/web/tests/development.test.ts: atualizar somente expectativa pertinente.
- apps/web/e2e/visual-preview.spec.ts: atualizar expectativas do novo texto.
- Pacote, checkpoint e evidências do piloto com IDs/revisões reais.
- Exclui outras telas, lógica de status, deploy automático, dados reais,
  mudanças de permissões, migração AP0 e configuração produtiva.

## Fases e saídas

1. Board registra issue com idempotencyKey megabrain.ctx-pilot-001.20261002,
   inicialmente backlog e sem disparar executor. Vincula projeto/worktree/base,
   pacote completo e IDs reais. Confere ausência de execução concorrente.
2. Run A recebe o pacote pela tarefa, confere Git/instruções e prepara plano.
   Comita checkpoint, captura projeção e registra referência/digest no issue.
   Pausa sem implementar nem marcar a tarefa como concluída.
3. Run B em sessão nova recebe pacote/checkpoint, verifica a projeção, declara
   objetivo/limites/próximo passo e implementa a mudança. SHA divergente deve
   bloquear em caso negativo, preservando WIP; documentar resultado.
4. Comita candidato, roda lint/typecheck/tests/qa:visual, registra SHA/build,
   desktop/mobile e estados. O runner de QA inclui build real.
5. Reviewer em sessão distinta lê contrato, diff e evidências do SHA final,
   compara baseline/resultado e registra decisão; autor não se autoaprova.
6. PR e Paperclip mostram responsável, fase, checkpoint, blocker, preview/QA
   e review. Publicação/recibo são operações próprias pelos gates vigentes.

## Aceite

IDs reais e um caminho canônico; Git/worktree conferidos; outra sessão retoma
sem chat; negativo bloqueia sem reset; mudança limitada aos textos/testes;
QA passa e screenshot corresponde à intenção; CI e reviewer identificam
o mesmo candidato; estado não é declarado concluído apenas por resposta do autor.

## Limites e próximo passo

Fixtures; zero jobs/download/STT reais, zero API paga de inferência.
Python/Git/CI/Playwright fazem verificações repetíveis; modelo executa o escopo.
Registrar attempts e quota: duas hipóteses por blocker antes de checkpoint.
Próximo passo: concluir a autorização normal do CLI Paperclip e registrar o
piloto pela API. Não contornar auth com escrita de banco ou novo token por fora.
