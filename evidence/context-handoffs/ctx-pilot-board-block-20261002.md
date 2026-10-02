# Checkpoint do board — MEG-6 bloqueada no executor

Data: 2026-10-02, America/Sao_Paulo. Registro de diagnóstico, não aceite.
Referência Git: https://github.com/mide-lim/megabrain/pull/90.
Pacote: [CTX-PILOT-001](../../docs/tasks/CTX-PILOT-001/PACKET.md).
Este é o handoff do board; o executor não gerou o checkpoint de Run A.

## Identidade e estado conferidos

- Company: 62eb0667-5669-408c-b8dc-74a1bc8b0757.
- Projeto MegaBrain — Engenharia: 6728591e-b875-4691-829e-6e68ae98210e.
- Issue MEG-6: b89613a1-90cf-437f-8481-fec4941e4d81.
- Responsável: megabrain-owner. Estado blocked; assigneeAgentId null.
- Executor planejado: MEGABRAIN c9487f45-02f6-4da4-9f85-dfe2c1154066,
  codex_local, gpt-6.1-sol. Nenhum agente permanente novo.
- Auth normal do CLI aprovada; chamadas board do cliente oficial funcionam.
- Última conferência da API: nenhuma execução ativa. Sem novo wake após pausa.
- Zero alteração de produto, review, merge protegido ou deploy neste piloto.

## Execuções observadas

Run A e0813783-5ef9-4fe5-bef2-b5a4336fa618:
2026-10-02T13:06:34.357Z–13:07:17.928Z (10:06–10:07 São Paulo).
Processo succeeded/exit0; resultado funcional BLOCKED.
Sessão anterior null; sessão criada 01a0fcb9-4f7a-7633-9763-912067a193e7.
Não conseguiu conferir Git, criar plano/commit/projeção nem alterar a aplicação.

Cinco execuções automáticas de recuperação/encerramento seguiram o bloqueio:

| Run | Início UTC | Resultado funcional |
|---|---|---|
| c33d02ae-7d4c-4f1b-af11-5f4310fbf54e | 13:07:18.983 | Bloqueado |
| 68a42249-d7e7-45d1-8f82-029a73a4e798 | 13:09:16.882 | Bloqueado |
| a496748b-52dd-447f-8dd2-de6527290a2b | 13:10:17.894 | Bloqueado |
| d3b30bf8-5e52-4c41-85d0-f6c213a4fbdc | 13:10:45.106 | Bloqueado |
| 2f966466-2f00-4ac3-b45b-15231dd3a7f9 | 13:12:17.315 | Bloqueado |

Os comentários nativos preservam bwrap/approval=never e ausência de mudanças.
O board retirou o assignee e gravou blocked para interromper as repetições.
Não contar essas execuções como tarefas concluídas nem iniciar Run B.

## Três falhas distintas

1. Sandbox: comandos nativos falharam com
   `bwrap: No permissions to create a new namespace`.
2. Aprovação: tools Paperclip, inclusive disposição/resolve, foram rejeitados
   porque exigiam aprovação e a sessão usava `approval=never`.
3. Workspace: opções de isolamento da issue retornaram null em create/patch.
   Policy git_worktree do projeto persistiu, mas o Run A selecionou o primary.

O perfil restrito aplicado pelo board ao piloto exigiu sandbox e approval=never;
esse último ponto não era compatível com os tools de encerramento disponíveis.
A configuração global do agente não foi ampliada nem reescrita. Resolver essa
incompatibilidade requer o caminho normal de autorização, não raw API como
substituto para um tool negado ao executor.

## Git e workspace preservados

Base e QA preparatório: 892d8b27c58d7c02669103081b3918a533c0b457.
Execução histórica: workspace 2f74a96a-5967-447e-97fa-bb8b44e051ff,
shared_workspace/project_primary; cwd /home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod/home/.paperclip/instances/default/projects/62eb0667-5669-408c-b8dc-74a1bc8b0757/6728591e-b875-4691-829e-6e68ae98210e/megabrain.
Git real do primary: branch main, HEAD 2e80f59f943f6fc9cb904dc4f889db906f77849b, limpo.

Worktree de tarefa criado fisicamente pelo board:
/home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod/home/.paperclip/instances/default/projects/62eb0667-5669-408c-b8dc-74a1bc8b0757/6728591e-b875-4691-829e-6e68ae98210e/worktrees/agent/context-pilot-001-20261002.
Branch agent/context-pilot-001-20261002; conferido limpo em 892d8b2 antes
desta publicação documental. Nova revisão deve avançar somente por fast-forward
após conferir que não surgiram execuções ou WIP.
Project workspace 82300bdd-d392-4da4-a80a-399e54c4ecf6, local_path, vinculado
à MEG-6 pela API e lido de volta. Novo wake nesse vínculo ainda não foi testado.
Primary d0d781aa-2bf8-4c59-a5ae-01ed81d97778 e seu histórico ficam preservados.

Manutenção local: agent/orchestration-context-preflight-20261002.
Checkout antigo orchestration-foundation-20261002 permanece em b38458d,
com 14 arquivos staged e árvore de índice ce37e73a726f5d07ef040685cb10e9eeab81036d.
Não resetar/rebasear/usar esse WIP para o piloto.

## Teste sem modelo no host

Codex 0.160.0, usuário de desenvolvimento megabrain-hermes uid1001.
Sandbox padrão workspace-write, network_access=false, fixtures temporárias.
Probe corrigido: exit0, inside_allowed=true, outside_blocked=true;
escrita externa recusada com EROFS, arquivo externo não criado.
Fixtures removidas. Zero chamadas de modelo/API paga e zero escrita produtiva.
O primeiro probe esperava PermissionError, recebeu EROFS e foi corrigido para
validar errno 1/13/30. Não era falha do bloqueio de escrita externa.

Tentativa local de diagnóstico com use_legacy_landlock não resolveu:
filesystem-restricted execution requires bubblewrap to isolate app-server sockets.
Nenhuma configuração/flag de diagnóstico foi persistida.
Não houve alteração de kernel, AppArmor, Docker ou permissões de produção.
O probe do host não prova transporte, autenticação remota ou tools do Paperclip.

## Próximo passo e critério para retomada

Proposta: validar execução nativa no mesmo host sob usuário de desenvolvimento,
mantendo sandbox e worktree da tarefa. O driver SSH consta supported na API;
não existe ambiente SSH provisionado e nenhum novo acesso/chave foi criado.
Transporte e autorização de tools devem ser definidos antes de novo wake.

Preferir recuperar/reconstruir somente o ambiente de execução dos agentes,
com versões e configuração reproduzíveis. Reset total da VPS não foi aprovado
ou realizado; decisão exige inventário, backup com restauração testada e plano
de preservação de produção/dados. Uma imagem sozinha não prova restauração.

Antes de novo Run A: conferir executor/sandbox sem modelo, workspace/HEAD/cwd,
canal autorizado de encerramento e ausência de concorrência/auto-repetições.
Depois fixar SHA do pacote e emitir somente Run A em sessão nova.
Run B, negativo de SHA, implementação, QA do candidato e reviewer continuam
pendentes. QA anterior (71 testes e 12 casos visuais/CI) vale para a base 892d8b2.

Relato upstream semelhante, não prova de causa idêntica nem de correção:
https://github.com/paperclipai/paperclip/issues/14519.
Não aplicar a sugestão de desligar sandbox contida nesse relato.
