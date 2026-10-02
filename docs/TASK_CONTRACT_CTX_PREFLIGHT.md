# Task Packet — continuação do preflight de orquestração

## Identidade e autoridade

- Origem: manutenção autorizada por Michel nesta sessão; GitHub PR #90.
- Referência: https://github.com/mide-lim/megabrain/pull/90.
- Paperclip issue/run e AP0 task/checkpoint: não alocados; não fabricar IDs.
- Estado: preparação e verificações concluídas; integração ao executor pendente.
- Responsável/executor: manutenção Codex; reviewer independente ainda pendente.
- Risco: YELLOW para helper/CI; nenhuma operação de produção incluída.
- Instruções: AGENTS.md, D022 e políticas vigentes. Sem nova capability.

## Resultado e escopo

Preparar uma conferência determinística de contexto para outra sessão localizar
o contrato, checkpoint, decisões e próximo passo no mesmo candidato Git.
Inclui helper sem dependências externas, testes de bloqueio, integração no job
existente de CI, instruções e checkpoint desta retomada.

Exclui alteração visual, migração AP0, novo serviço/agente, dados reais,
configuração produtiva, criação de credenciais, deploy e admissão do piloto.
Uma verificação Git positiva não aprova execução, produto ou publicação.

## Git e referências

- Repo: mide-lim/megabrain.
- Worktree: /home/megabrain-hermes/workspace/orchestration-context-preflight-20261002.
- Branch local: agent/orchestration-context-preflight-20261002.
- Destino de publicação: agent/context-foundation-20261001, PR #90.
- Base: c510d5560ae1329e9e67407210d430784e6a650e.
- HEAD final: obter do candidato que contém este pacote; conferir PR e worktree.
- Checkout antigo: preservado com seu índice; não é o checkout desta continuação.
- Arquivos: tools/session_context.py, tools/tests/test_session_context.py,
  SESSION_CONTEXT.md, CONTEXT.md, ORCHESTRATION_ROLLOUT.md, este pacote,
  .github/workflows/ci.yml e handoff desta etapa.
- UX/release/preview desta alteração: N/A; é tooling de continuidade.
- Contexto: D022, [arquitetura](ARCHITECTURE.md), [rollout](ORCHESTRATION_ROLLOUT.md).
- Checkpoint: [retomada](../evidence/context-handoffs/orchestration-preflight-20261002.md).

## Aceite e validação

- Captura fixa documentos em commit e Git limpo, sem alterar Git.
- Outro processo recupera referências e próximo passo, sem conversa anterior.
- HEAD/branch/tarefa/blob divergentes e WIP bloqueiam, preservando o checkout.
- Snapshot existente permanece íntegro; referências obrigatórias são verificadas.
- Helper não lê segredos nem executa modelos, recursos ou operações produtivas.
- Testes stdlib passam na VPS; CI valida os testes no candidato publicado.
- Diff limitado ao escopo e checkpoint atualizado com evidências reais.

## Preparação do piloto — autorização de 2026-10-02

O escopo desta manutenção passa a incluir o preview já preparado: scripts
fixtures/run/serve, configuração Playwright, 12 casos E2E, scripts npm, lock
com Playwright pinado, worker de build condicionado ao QA e workflow visual.
Next/React e fontes do produto permanecem na baseline. Pacote do piloto e
checkpoint de preparação registram a lane nativa e a autorização board pendente.
Essa preparação não implementa o texto nem executa uma tarefa Paperclip sem IDs.

## Próximo passo e dependências

Revisar este candidato e habilitar acesso autorizado à API da tarefa Paperclip.
Depois registrar issue/run real, fixar pacote/base/lane e integrar entrega de
contexto no executor, seguindo o CTX-PILOT-001. O perfil AP0 incompleto permanece
fora deste escopo; só provisionar se essa lane for selecionada.
O preview anterior precisa de prova no candidato atual e ligação à tarefa.
Review independente, piloto completo e deploy ainda não estão concluídos.
