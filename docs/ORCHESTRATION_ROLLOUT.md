# Adoção do modelo de orquestração — D022

Status: direção aceita; fundação documental preparada; fluxo completo pendente.
O objetivo é comprovar um caminho de tarefa sem depender do histórico da IDE.
[Arquitetura](ARCHITECTURE.md) e [D022](DECISIONS.md) descrevem responsabilidades.

## Autoridade por registro

| Registro | Autoridade | Vinculação |
|---|---|---|
| Código/docs/ADRs | GitHub | Commit e caminho. |
| Pedido, responsável, prioridade, links e runs nativos | Paperclip | Issue/run reais, associados ao contrato. |
| Task/lease/gate/budget/checkpoint AP0 | Control Plane AP0 | API canônica, IDs e revisões existentes; sem escrita direta de tabelas. |
| Progresso nativo exportado | Executor/responsável do run nativo | Snapshot Git e link/revisão registrados na tarefa. |
| Review | Reviewer em outra sessão | Critérios originais e candidato exato. |
| Produção | Capability/operador autorizados e runtime | Recibo, artefato/digest e leitura posterior. |

Cada execução escolhe sua origem canônica. Se atravessar o AP0, usar seu contrato.
Uma ponte futura precisa mapear IDs/revisões, idempotência e escritor; não cria
duas filas ou dois ledgers concorrentes. Nenhum cutover foi feito nesta PR.

## Ordem de trabalho

| Etapa | Trabalho | Critério de saída |
|---|---|---|
| 0 — esta fundação | D022, arc42/C4, contexto e templates | Fontes/links conferidos; direção aceita separada de capability instalada. |
| 1 — preflight | Identificar lane nativa/AP0, acesso à tarefa e perfil real | IDs, instruções, limites, APIs e autoridade comprovados; provisionar AP0 se necessário. |
| 2 — continuidade | Entregar pacote/checkpoint e preservar WIP | Sessão nova reconstrói o trabalho sem chat e detecta HEAD incompatível. |
| 3 — preview/QA | Padronizar preview isolado e evidências determinísticas | URL, candidato, identidade, limites, dados de teste, screenshots e resultados ligados. |
| 4 — piloto | Executar CTX-PILOT-001 com review e gates atuais | Candidato final revisado, recibo/runtime e fechamento rastreáveis. |
| 5 — publicação por risco | Definir e ativar capability/política de baixo risco | Regras objetivas, segurança/recuperação verificadas e ativação registrada. |
| 6 — ampliar | Medir concorrência e recuperação de contexto | Mais agentes/CocoIndex somente com benefício e capacidade demonstrados. |

## Começo de execução

1. Ler AGENTS.md, CONTEXT.md e o pacote exato; identificar a tarefa real.
2. Conferir repo, branch agent/*, worktree/cwd, base, HEAD e diff.
3. Ler somente arquitetura/ADRs/arquivos pertinentes, preservando restrições essenciais.
4. Carregar checkpoint; comparar revisões, evidências e WIP com Git.
5. Conferir autoridade e budgets pela fonte correta; registrar plano e próximo passo.

Checkpoint grava marcos, bloqueios e handoffs; tarefa longa define sua cadência.
Após duas hipóteses distintas para o mesmo bloqueio, persistir evidências e escalar.
Quota não causa tentativas indefinidas nem perda deliberada do progresso.

## Preview e revisão visual

Usar ambiente separado na VPS. Primeiro medir capacidade e definir limites de
processo/CPU/RAM, worktree, TTL, dados e conectividade. Loopback é a fronteira
inicial AP0; URL acessível requer autorização, autenticação e roteamento próprios.
Nunca reutilizar cookies, dados, buckets ou credenciais de produção para tornar
um mock mais conveniente.

Mudança importante de UI tem proposta navegável e imagens anotadas versionadas.
Screenshots cobrem desktop/mobile e estados relevantes; Playwright gera evidências
do comportamento. O reviewer lê o resultado visual, não apenas o código ou logs.
Dados simulados verificam frontend; integração real exige teste controlado próprio.

## Fechamento e painel

A tarefa inclui responsável, fase, último progresso, bloqueio, preview, PR,
evidências/review e versão de produção. Começar com registros/links existentes,
sem criar outro dashboard. Conferir o suporte do fork instalado ao fazer a integração.

Checks e revisão têm um candidato identificado. Depois de merge/rebuild, comparar
revisão e artefato; revalidar se houver mudança. Registrar operação e verificação
posterior no [recibo](templates/DEPLOY_RECEIPT.md). Healthcheck não comprova sozinho
todo o produto. Estado final de tarefa é registrado após esse fechamento.

## Pendências conhecidas para o primeiro ciclo

- API/painel Paperclip precisam de sessão/capability utilizável para vincular e
  registrar a tarefa sem recorrer a escrita direta de banco.
- Profile AP0 usa executável/HERMES_HOME separados e incompletos no snapshot;
  corrigir por tarefa autorizada se essa lane for usada.
- Encaminhamento MCP local_stdio de deploy precisa de prova; contorno anterior
  não comprova o caminho normal funcionando.
- Preview/QA prototipados precisam de integração ao fluxo padrão e identidade do candidato.
- Injeção/recuperação de pacote e checkpoint precisam de implementação e validação.
- Backup/restore, budgets e retenção reais devem ser conferidos, não presumidos.

## Métricas do piloto

Registrar tempo até preview, chamadas/uso de inferência quando disponível,
intervenções humanas, tentativas por bloqueio, recuperação em sessão nova e
divergências entre pedido, candidato e release. Não há metas numéricas de economia
comprovadas nesta etapa. CI e scripts executam comandos repetíveis dentro dos
limites existentes; o modelo recebe resumo e artefatos necessários.
