# Checkpoint — retomada e preflight da orquestração

Data: 2026-10-02, America/Sao_Paulo. Escritor: manutenção Codex autorizada.
Origem: [PR #90](https://github.com/mide-lim/megabrain/pull/90).
Nenhum issue/run Paperclip ou task/checkpoint AP0 foi admitido nesta manutenção.
Contrato: [pacote](../../docs/TASK_CONTRACT_CTX_PREFLIGHT.md).

## Ponto de parada reconstruído

- PR #90 estava aberta, pronta para review, base dev, HEAD c510d5560ae1329e9e67407210d430784e6a650e.
- CI desse HEAD: run 36993612172, concluído com success.
- Checkout anterior: /home/megabrain-hermes/workspace/orchestration-foundation-20261002.
- HEAD local b38458d9845b0cda4dea65dcf618750b6cc4cbec; 14 arquivos staged.
- Índice ce37e73a726f5d07ef040685cb10e9eeab81036d, igual à árvore do HEAD GitHub.
- git diff --check e git diff --cached --check passaram; sem edições unstaged.
- O handoff anterior identifica a fundação publicada e o piloto ainda pendente.

Esse checkout/índice foi preservado integralmente. A continuação usa worktree
limpo próprio, criado do commit publicado após comparação das árvores.

## Preflight observado na VPS

| Verificação | Observação e limite |
|---|---|
| Conexão | Remote Desktop Commander executou processos e leituras em srv1862594. |
| Serviços AP0 | Control Plane e Hermes coordinator active/running, ExecMainStatus=0, NRestarts=0. |
| Journal | Último início em 2026-10-01 20:37 UTC; nenhum registro novo na janela de 2026-10-02 consultada. |
| Erro histórico | Control Plane em 2026-09-30 11:56 UTC: REGISTRY_UNAVAILABLE / invalid migration set; não é prova de falha atual. |
| Perfil AP0 | /opt/megabrain/hermes/bin/hermes e o config.yaml do HERMES_HOME do coordinator continuam ausentes. |
| Paperclip health | HTTP 200, authenticated/public, bootstrap ready; commit c580cd4916df605a5fcaf73b6e47f05b5f7ef54f. |
| API de tarefas | GET de issues retornou 401 sem credencial nesta execução. Nenhuma escrita foi tentada. |
| Adapter nativo | Código possui instructionsFilePath, taskContextNote, sessionHandoff e credencial por run; existe ponto de integração. |
| Preview/QA | visual-qa-preview e meg4-release-validation preservados e limpos. QA antigo não valida o HEAD atual. |
| Capacidade | VPS: 7.940 MiB RAM total, 5.166 MiB disponíveis, ~39.670 MiB de disco disponíveis no snapshot. Não houve benchmark de build. |

Logs foram lidos de forma delimitada; não foram exportados prompts, cookies,
segredos, dump de ambiente, credenciais ou banco. Serviço ativo não comprova
admissão/execução AP0. Health do Paperclip não concede acesso à API de tarefas.

## Continuação preparada

- Helper session_context captura/verifica identidade Git e referências pinadas.
- VPS, processo 851451: 11 testes stdlib passaram (2,542 s, código 0).
- Testes em processos novos validam retomada compatível e bloqueios de divergência.
- Instruções e pacote desta manutenção permitem repetir a conferência sem chat.
- Testes foram adicionados ao job Repository validation existente.
- Não foram alterados frontend, backend, deploy, auth ou configuration runtime.
- HEAD final/CI desta continuação devem ser obtidos do PR e do worktree exatos;
  o CI de c510d55 acima é histórico e não aprova automaticamente o novo candidato.

## Retomada permitida

Worktree: /home/megabrain-hermes/workspace/orchestration-context-preflight-20261002.
Branch local: agent/orchestration-context-preflight-20261002.
Publicação: branch agent/context-foundation-20261001 do PR #90; mesma revisão candidata.
Base: c510d5560ae1329e9e67407210d430784e6a650e.
Depois de publicar, capturar/verificar a projeção descrita em
[SESSION_CONTEXT.md](../../docs/SESSION_CONTEXT.md), conservando o snapshot e sua identidade.

Próximo passo: review do candidato e acesso autorizado à API Paperclip; admitir
o piloto real, entregar contexto ao executor e comprovar preview/QA do mesmo SHA.
API 401 foi uma verificação de acesso, não um loop de correção; não criar tokens
por fora nem escrever o banco. Perfil AP0 precisa de tarefa própria se utilizado.

Pendente: integração automática, retomada em nova sessão Codex do piloto,
preview atual acessível, reviewer em sessão separada, gate/deploy/recibo reais.
Somente depois considerar a publicação automática delimitada de D022.
