# Conferência de contexto entre sessões

`tools/session_context.py` automatiza a conferência Git da retomada de D022.
Usa Python e Git, sem modelo, API paga, daemon ou índice novo. O JSON gerado é
uma projeção de leitura ligada à tarefa/PR canônica; não é ledger, Task Packet,
checkpoint AP0, autorização, aprovação ou recibo de deploy.

## Preparar a pausa

1. Preencher o [Task Packet](templates/TASK_PACKET.md) e o
   [checkpoint](templates/SESSION_CHECKPOINT.md), com fatos e próximo passo.
2. Preservar WIP em commit da branch `agent/*`; conferir o diff antes de commitar.
3. Com árvore Git limpa, capturar referências no HEAD exato. Exemplo:

```sh
python3 tools/session_context.py capture --repo . \
  --task-ref https://github.com/mide-lim/megabrain/pull/90 \
  --base c510d5560ae1329e9e67407210d430784e6a650e \
  --packet docs/TASK_CONTRACT_CTX_PREFLIGHT.md \
  --checkpoint evidence/context-handoffs/orchestration-preflight-20261002.md \
  --next-step 'Conferir contrato e acesso à API de tarefas antes de admitir o piloto' \
  --output ../orchestration-session-context.json
```

O arquivo precisa estar fora do checkout; um arquivo existente nunca é
sobrescrito. Usar nome próprio por marco. Registrar sua referência/digest na
tarefa autorizada e armazená-lo com retenção junto às evidências. A cópia local
sozinha não garante recuperação após perda da VPS. O Git contém os documentos;
o snapshot apenas fixa suas revisões, o worktree e o próximo passo.

## Retomar

```sh
python3 tools/session_context.py verify --repo . \
  --task-ref https://github.com/mide-lim/megabrain/pull/90 \
  --snapshot ../orchestration-session-context.json
```

Código 0 confirma somente contexto Git compatível. Ler os documentos em
`read_before_execution`, incluindo contrato, instruções e decisões, e conferir
estado, autoridade, quota e recursos na API responsável. Código 2 bloqueia
essa retomada; preservar alterações e reconciliar, sem reset, checkout automático
ou reutilização de recurso alheio. Snapshot não é assinado: sua identidade deve
ser conferida pela referência/digest retida na tarefa, nunca por texto de aprovação.

O verificador exige o mesmo repositório, caminho de worktree, branch, base,
HEAD, árvore e blobs dos documentos, sem mudanças rastreadas ou não rastreadas.
Uma transferência de máquina/worktree exige nova conferência e projeção explícita.
Arquivos ignorados, variáveis, provider e serviços não são auditados por este
comando. Ele não lê `.env`, tokens, cookies, banco ou logs de execução.

## Integração com execução

Preparado e testado em processos novos, ainda sem ativação no adapter Paperclip.
Não equivale ao teste de retomada completa do CTX-PILOT-001 em outra sessão Codex.
O fork instalado já possui `instructionsFilePath`, contexto da tarefa e handoff
de sessão. A integração deve reutilizar esses pontos, com IDs/run e credencial
injetados pelo runtime; falha de contexto deve bloquear antes de implementar.
Não criar chave por fora, copiar credenciais nem escrever tabelas diretamente.

Para a lane AP0, checkpoint/lease/gates continuam na API AP0. Este JSON pode
referenciar a projeção documental, mas não substitui IDs/revisões canônicos.
Preview/QA e deploy são verificações próprias do mesmo candidato, conforme
[rollout](ORCHESTRATION_ROLLOUT.md). O comando não inicia esses recursos.

## Verificar o helper

`python3 -m unittest discover -s tools/tests -p 'test_*.py' -v`

Os testes usam repositórios temporários e processos separados. Cobrem retomada
compatível, HEAD/branch/tarefa/blob divergentes, WIP preservado, referências
ausentes, symlink, caminhos privados/externos, branch protegida, repo incorreto,
JSON inválido e preservação de um snapshot existente.
