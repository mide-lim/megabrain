# Task Contract — CTX-PILOT-001: provar continuidade e entrega

## Status

- Status: DISCOVERY — contrato preparado; execução ainda não admitida.
- Risk Level: GREEN para preparação documental; YELLOW para tooling/dependências;
  operação de produção continua RED sob a política vigente.
- ID CTX-PILOT-001 é uma referência documental, não um task_id AP0/Paperclip inventado.
- Paperclip issue_id/run_id: pendentes de registro pela API/capability autorizada.
- Modelo de pacote: [templates/TASK_PACKET.md](templates/TASK_PACKET.md).

## Objective / User Context

Demonstrar uma tarefa pequena que outra sessão retoma sem chat anterior e que
produz preview, QA, review do candidato final e recibo de deploy. Validar esse
processo antes de reformular a UI ou habilitar publicação automática por risco.

## Scope

### In

Usar uma alteração reversível no conteúdo de estado da página /development como
piloto: somente após registrar o run real e fixar a base. Preservar layout,
autenticação, links e contratos de API. Texto positivo proposto: “Paperclip online” → “Paperclip disponível”. Testar
a apresentação com backend de teste, sem disparar jobs, STT ou integrações reais.

Criar checkpoint após preparação; outra sessão deve carregar apenas pacote,
checkpoint e fontes Git e continuar. Incluir um caso negativo com HEAD divergente,
sem reset ou alteração destrutiva. Depois publicar pela capability/gate atual e
registrar o artefato observado. Não executar essas ações nesta PR documental.

### Out

Redesign, novos agentes permanentes, migração AP0, mudanças de permissões/Git,
dados reais, ingestão em massa, correção de inglês, classificação IA, auto deploy
e modificações da configuração produtiva fora da operação explicitamente delimitada.

## Acceptance Criteria

- Issue/run real, responsável, origem canônica e referências ligados ao contrato.
- Branch agent/*, worktree/cwd, commit base e diff identificados.
- Sessão nova reconstrói objetivo, limites, ADRs, estado e próximo passo sem chat.
- Caso divergente é detectado e bloqueia continuação até reconciliação.
- Preview isolado tem URL utilizável, identidade, commit/build, limites e dados de teste.
- Fluxo/layout existentes preservados; screenshots desktop/mobile e estados pertinentes.
- Tests/lint/typecheck/build relevantes passam e identificam o candidato.
- Reviewer em sessão distinta avalia contrato, evidências e candidato final.
- Após gate/capability atuais, recibo identifica artefato publicado e leitura runtime.
- Task e PR registram evidências e estado final; nenhuma publicação é declarada
  antes da prova runtime.

## Architecture / UX / Contracts

D022, D020/D021, RISK_POLICY.md e contratos da lane escolhida.
Referência de UX: baseline atual da tela, capturada e anotada no commit base;
não introduzir nova direção visual no piloto. Proposta navegável reutiliza o
preview existente do candidato e cobre o comportamento do texto definido.

Contrato de API: inalterado. Data/Migration: N/A. Security: manter OIDC, sessão,
CSRF e fronteiras. Backend mock de teste não redefine autenticação de produção.

## Expected Files / Components

- [page](../apps/web/src/app/development/page.tsx)
- [conteúdo](../apps/web/src/app/development/development-page-content.tsx)
- [teste](../apps/web/tests/development.test.ts)
- [QA visual](../apps/web/e2e/visual-preview.spec.ts): expectativas do mesmo texto.
- [pacote detalhado](tasks/CTX-PILOT-001/PACKET.md), checkpoint/evidências da task; demais arquivos somente se registrados no escopo.

## Required Tests / Evidence

- Conferência Git inicial e após retomada; checkpoint e teste de divergência.
- npm run lint; npm run typecheck; npm test; npm run build em apps/web.
- Teste de browser da interação pertinente; screenshots em desktop/mobile.
- CI do candidato, review, identidade do build e recibo final.
- Tempo, inferência, tentativas e intervenções humanas registrados, sem credenciais.

## Staging / Production / Recovery

Preview em recursos/dados separados da VPS, sem URL fictícia ou cópia de dados
produtivos. Publicação é uma operação própria sob gate/capability vigentes.
Reversão aponta para o artefato anterior verificado; aplicar rollback não é
autorizado apenas por sua descrição neste contrato.

## Dependencies / Human Gates / Open Questions

Antes de SPEC_READY:
1. Registrar issue/run real e preencher pacote/revisão/base Git.
2. Confirmar lane e autoridade; provisionar AP0 se essa execução depender dele.
3. Padronizar acesso ao preview e artefatos, com limites/lease pertinentes.
4. Validar caminho de review/deploy e suas capabilities/gates.
5. Conferir o texto proposto e a baseline visual do commit que contém a preparação.

Lane proposta para este piloto: adapter Codex nativo do Paperclip, sem migração
AP0. O pacote detalhado define Run A/Run B e review em sessão distinta; IDs,
worktree real e base final seguem pendentes da autorização normal de acesso.

Mudanças relevantes de arquitetura, privilégio ou produto exigem decisão humana
aplicável. Execução de produção usa o gate atual; D022 não o suprime.

## Final Evidence Summary

Contrato preparado e fontes/links conferidos na fundação documental.
Piloto não executado; não há review independente, preview implantado, release
ou recibo produtivo deste candidato. Preencher esta seção com fatos após o ciclo.
