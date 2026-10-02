# Task Packet — CTX-PILOT-001

## Identidade e autoridade

- Status: BLOCKED; acesso aprovado, registro real criado, Run A sem entregável.
- CTX-PILOT-001 é o nome documental da issue canônica MEG-6.
- Issue: b89613a1-90cf-437f-8481-fec4941e4d81; owner megabrain-owner.
- Projeto: 6728591e-b875-4691-829e-6e68ae98210e (MegaBrain — Engenharia).
- Run A: e0813783-5ef9-4fe5-bef2-b5a4336fa618, bloqueado em 2026-10-02.
- Processo succeeded/exit0 não prova aceite: comandos e encerramento falharam.
- Origem de estado escolhida: Paperclip nativo; executor Codex MEGABRAIN existente.
- IDs existentes de referência: company 62eb0667-5669-408c-b8dc-74a1bc8b0757;
  executor c9487f45-02f6-4da4-9f85-dfe2c1154066. Conferir na API antes de admitir.
- Registro preparatório: https://github.com/mide-lim/megabrain/pull/90.
- Executor planejado permanece o existente; assignee atual null para suspender
  recuperações automáticas enquanto o executor está bloqueado.
- Fixar no issue o SHA exato que contém este pacote antes de novo wake.
- Checkpoint atual: ../../../evidence/context-handoffs/ctx-pilot-board-block-20261002.md.
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
- Base de execução e QA preparatório: 892d8b27c58d7c02669103081b3918a533c0b457.
- HEAD de entrada: obter o SHA documental fixado pelo board na issue, não
  assumir que o HEAD atual ainda é a base. Conferir Git real antes de executar.
- Worktree físico: /home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod/home/.paperclip/instances/default/projects/62eb0667-5669-408c-b8dc-74a1bc8b0757/6728591e-b875-4691-829e-6e68ae98210e/worktrees/agent/context-pilot-001-20261002.
- Project workspace: 82300bdd-d392-4da4-a80a-399e54c4ecf6, local_path;
  vínculo na issue conferido pela API. Execução nativa nesse vínculo não testada.
- O Run A anterior usou project_primary/shared e branch main/HEAD 2e80f59,
  apesar da policy isolada. Preservar esse checkout e o registro histórico.
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
Próximo passo: validar um executor compatível com workspace-write e um caminho
normal autorizado para registrar a disposição da tarefa; conferir cwd/Git antes
de repetir somente Run A em sessão nova. Corrigir a integração sem desativar
sandbox ou contornar rejeições. Run B, review e deploy continuam pendentes.
O sandbox direto no host passou; transporte Paperclip/host e permissões de
encerramento ainda não passaram. Detalhes e proposta no checkpoint atual.
