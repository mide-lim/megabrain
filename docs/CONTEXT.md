# Contexto de engenharia do MegaBrain

Data: 2026-10-01, America/Sao_Paulo.
Status: proposta de integração documental. O protocolo abaixo ainda não está automatizado no executor.
Esta página organiza referências; não substitui AGENTS.md, ADRs aceitos, schemas AP0 ou gates existentes.

## 1. Diagnóstico e objetivo

O projeto já possui arquitetura, decisões, Task Contract e contratos AP0 de checkpoints e recursos.
A lacuna é alinhar esses registros ao runtime atual e entregar um contexto verificável a cada execução.
Uma sessão nova deve conseguir retomar uma tarefa com repositório, Task Packet e checkpoint, sem histórico da IDE.
Isso preserva fatos, decisões, pendências e evidências relevantes; não exige carregar toda conversa em todo prompt.

Observações desta auditoria:
- AGENTS.md e CURRENT_STATE.md ainda descrevem principalmente Hermes; ACTIVE_TASK.md continua em F6.
- UI_SYSTEM.md é explicitamente uma baseline histórica de SSR/Jinja, aposentada.
- Paperclip está em uso; a MEG-4 foi implementada e entregue, mas sua expectativa visual precisa de novo discovery.
- Os serviços systemd megabrain-control-plane e megabrain-hermes-coordinator estão active/running.
- Os contratos AP0 já especificam Task IDs, leases e checkpoints; não criar um segundo registro concorrente.
- Ao localizar a MEG-4, o checkout de execução estava em outra branch. O vínculo tarefa/commit precisa ser explícito.
Atividade de serviço não prova integração entre todos esses caminhos nem execução duplicada da mesma tarefa.

## 2. Uma autoridade por assunto

| Assunto | Registro de referência | Regra |
|---|---|---|
| Código, documentação, decisões e plano de produto | GitHub | Referências de execução fixadas por commit; propostas separadas de decisões aceitas. |
| Objetivo, priorização e acompanhamento humano | Paperclip | Entrada recomendada para novas tarefas; vincular PR, pacote, checkpoint e evidências. |
| Recursos, permissões de execução, budgets e checkpoints AP0 | Control Plane existente, quando a tarefa usar AP0 | Preservar a API e a autoridade já declaradas; não escrever seu banco por fora. |
| Estado efetivo de produção | Recibo/manifesto de release + verificação runtime | Uma branch de desenvolvimento não comprova uma implantação. |
| Contexto recuperado | Busca textual; CocoIndex em piloto posterior | Cache reconstruível. Sempre devolver caminho e revisão da fonte. |
| Conteúdo da biblioteca | PostgreSQL/R2 e APIs do produto | Separado da memória de engenharia; nunca transferir todo o acervo ao executor. |

Há uma decisão de integração pendente: a relação Paperclip/AP0/Hermes precisa de um único caminho documentado.
Recomendação: Paperclip como entrada de planejamento e acompanhamento; AP0 como infraestrutura delimitada;
um coordenador responsável por cada tarefa. Hermes pode ser um executor/adaptador conforme a decisão aceita.
Não desligar serviços, migrar registros ou criar outra fila por causa deste documento.
Reconciliar D013/D014/D016 e os contratos AP0 em uma decisão explícita antes de alterar o runtime.

## 3. Referências mínimas e manutenção

| Referência | Conteúdo que deve manter |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Contexto e containers C4, responsabilidades, interfaces e implantação. arc42 apenas nas seções úteis. |
| [CURRENT_STATE.md](CURRENT_STATE.md) | Snapshot datado, capacidades comprovadas, release e bloqueios; distinguir observado de proposto. |
| [DECISIONS.md](DECISIONS.md) | Decisões com contexto, alternativas, consequências, status e vínculo de substituição. |
| [ROADMAP.md](ROADMAP.md) | Visão e marcos com critérios de saída; separar desejos futuros de capacidades disponíveis. |
| [TASK_CONTRACT.md](TASK_CONTRACT.md) | Contrato canônico de execução; o Task Packet é sua projeção compacta. |
| [UI_SYSTEM.md](UI_SYSTEM.md) | Histórico Jinja. Uma referência da UI Next atual e um design alvo precisam de discovery próprio. |

Quem muda comportamento atualiza o registro afetado no mesmo PR. Quem revisa confere essa correspondência.
Não editar todos os documentos em toda tarefa. Não usar ACTIVE_TASK.md como único checkpoint global de trabalhos paralelos.
Preservar o histórico: uma decisão substituída continua acessível e aponta para sua sucessora.

DDD entra na linguagem do produto: Reel, mídia, caption, transcrição, curadoria e categoria têm sentidos definidos.
Caption original e transcrição permanecem distintas, conforme D004.
Análise IA e materiais de outras fontes pertencem à visão futura enquanto não houver contrato implementado.
Não introduzir aggregates, event sourcing ou microserviços só para adotar DDD.

## 4. Task Packet: projeção curta do contrato

Este modelo é legível por humanos. O exportador deve respeitar o schema do sistema que executar a tarefa;
esta página não cria um novo schema AP0 ou uma segunda fonte de estado.

```yaml
task_id: <ID canônico; vincular o ID do Paperclip se houver IDs distintos>
packet_revision: <revisão/hash e referência ao Task Contract>
objective: <problema e resultado observável>
scope: <o que muda; o que deve permanecer>
repository: <repo, branch, worktree/cwd e base_commit>
production_reference: <release relevante ou N/A; não confundir com base_commit>
context_refs: <arquitetura, ADRs aceitos, contratos e arquivos pertinentes no commit>
ux_reference: <fluxo, mockup ou preview alvo e sua revisão; N/A quando aplicável>
acceptance: <critérios verificáveis para produto, técnica e visual>
validation: <comandos, checks runtime pertinentes e evidências esperadas>
dependencies: <tarefas e versões necessárias>
authority: <perfil/ferramentas já autorizados, limites e gates existentes>
open_questions: <incertezas que podem mudar a implementação>
checkpoint_ref: <checkpoint canônico atual; não copiar uma sessão inteira>
```

Contexto obrigatório: objetivo, aceite, limites e decisões pertinentes.
A busca acrescenta detalhes específicos; não pode omitir restrições aceitas porque sua similaridade foi baixa.
Sem base identificada, autoridade clara ou resposta a uma dúvida que altera o resultado, manter a tarefa em discovery/blocked.
Hipóteses reversíveis devem ser registradas com esse status, sem virarem requisitos silenciosamente.

## 5. Começo e retomada de sessão

1. Receber o Task Packet exato e localizar o worktree da tarefa.
2. Ler AGENTS.md e instruções locais; conferir repo, branch, HEAD, diff e checkpoint.
3. Ler esta página e somente as referências pertinentes da arquitetura/ADRs/contratos.
4. Conferir evidências contra o SHA atual e reconciliar recursos pela API responsável, quando aplicável.
5. Registrar um plano curto com resultado, arquivos e validação; continuar do próximo passo comprovado.

Se branch, HEAD ou diff não corresponderem ao checkpoint, registrar a divergência e reconciliar.
Não resetar, rebasear, adotar um checkout alheio ou presumir sucesso por memória.
Uma tarefa deve ter um worktree identificado; um único checkout mutável exige serialização explícita.

## 6. Checkpoint e encerramento

Reutilizar o mecanismo AP0 existente para tarefas AP0. Para tarefas nativas do Paperclip, definir o escritor responsável
e o vínculo/exportação antes de automatizar a retomada. Um resumo Markdown é uma projeção de leitura, não outro ledger.

Campos essenciais de um checkpoint:
- task_id, revisão do pacote e ID/revisão do checkpoint;
- repo, branch, base SHA, HEAD e diff/artefato WIP preservado, se houver;
- realizado com referências de evidência; decisões e hipóteses identificadas;
- pendências, perguntas abertas, bloqueio e próximo passo concreto;
- testes executados, resultado, horário e SHA ao qual se aplicam;
- recursos/preview da tarefa, proprietário e validade, quando existirem;
- PR, aprovação e release relacionados, quando aplicáveis.

Gravar antes de troca de sessão, pausa por quota, handoff, bloqueio e conclusão de etapa.
Não gravar credenciais, cookies, URLs assinadas ou prompts/logs completos.
Evidência de um commit anterior fica histórica; avaliar o que precisa ser revalidado no novo candidato.
Contexto durável requer retenção e backup dos registros; um diretório de scratch ou cache de índice é insuficiente.

## 7. UI: resultado visual faz parte do contrato

A MEG-4 tinha critérios verificáveis de agrupamento de links. Eles foram atendidos tecnicamente,
mas não representaram suficientemente a experiência desejada pelo proprietário.
Testes e screenshots comprovam comportamento/renderização; aprovação do design exige comparação com a intenção.

Antes da próxima alteração:
1. Definir os problemas da tela, o usuário e os fluxos que precisam melhorar.
2. Preparar uma proposta visual concreta, desktop/mobile, com hierarquia e comportamento.
3. Resolver com o proprietário escolhas visuais relevantes que não podem ser inferidas.
4. Fixar a referência e os critérios no pacote; implementar esse escopo.
5. Comparar preview do SHA candidato com a referência; validar interações, estados e acessibilidade.
6. Registrar aceite de produto/visual separado de QA técnico e do gate de deploy.

Um review deve responder tanto "os testes passaram?" quanto "o resultado entregue atende ao pedido?".
Mudança de critério atualiza o pacote; não transformar aprovação técnica anterior em aprovação do novo design.
O protótipo de QA visual preparado nesta conversa ainda precisa de integração ao fluxo padrão.
Seu backend simulado valida frontend; não substitui a prova integrada quando a tarefa muda backend/autenticação.

## 8. Adoção sem acrescentar outra plataforma agora

| Ordem | Trabalho | Critério de saída |
|---|---|---|
| 1 | Reconciliar documentação e autoridade Paperclip/AP0/Hermes | Um caminho de tarefa, um escritor por registro, decisão com status explícito. |
| 2 | Entregar pacote e checkpoint no início da execução | Sessão vazia retoma uma tarefa sem consultar o chat anterior. |
| 3 | Integrar preview/QA existente e especificação visual | Evidências e referência do mesmo candidato; resultado visual revisável. |
| 4 | Executar um piloto pequeno | Handoff, review, release e registro final rastreáveis; nenhuma pergunta essencial perdida. |
| 5 | Avaliar CocoIndex | Busca recupera referências certas e atuais com custo/latência medidos; fallback textual funciona. |

O piloto de retomada deve reconstruir: objetivo, próximo passo, última decisão aceita, base/HEAD,
limites de mudança e evidências válidas. Também deve detectar um checkpoint com SHA incompatível.
Falha nesse teste exige corrigir integração/registro antes de iniciar o redesign.

CocoIndex começa por código e Markdown de um projeto, com escopo por branch/commit.
Excluir segredos, dumps, sessões, dados pessoais de produção, caches e binários.
Artefatos visuais ficam referenciados por metadados; busca textual não substitui a leitura da imagem.
Embeddings locais podem evitar cobrança de API, mas consomem recursos; não assumir instalação ou economia comprovada.
Não é requisito de disponibilidade do executor: falha do índice permite buscar/ler fontes diretamente.

## 9. Fontes e limites

- [AP0 runtime ownership](platform/autonomy/AP0_RUNTIME_OWNERSHIP_CONTRACT.md)
- [AP0 control plane](platform/autonomy/AP0_CONTROL_PLANE_CONTRACT.md)
- [AP0 coordinator design](platform/autonomy/AP0_HERMES_COORDINATOR_SERVICE_DESIGN.md)
- [C4 oficial](https://c4model.com/diagrams): contexto e containers bastam para a maioria dos times.
- [arc42 oficial](https://arc42.org/overview/): estrutura adaptável às necessidades do projeto.
- [CocoIndex Code oficial](https://github.com/cocoindex-io/cocoindex-code): recuperação de código e Markdown via CLI/MCP.

Auditoria: arquivos do GitHub/dev e estado systemd observados em 2026-10-01/02.
A integração de checkpoints entre IDE, Paperclip e AP0 não foi testada ponta a ponta.
Este trabalho é documental: nenhum redesign, novo serviço, corte de autoridade ou deploy foi executado.
