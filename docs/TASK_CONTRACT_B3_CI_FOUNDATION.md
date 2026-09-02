# Task Contract — B3.1: GitHub Actions CI Foundation

## Status

- Status: HUMAN_GATE
- Risk Level: GREEN

## Objective

Estabelecer a primeira CI determinística do MegaBrain em GitHub Actions para
validar o repositório e executar as suítes existentes de Enricher e Web em pull
requests.

## User / Product Context

O GitHub já é a fonte de verdade de desenvolvimento e o fluxo
`agent/* -> PR -> dev` está operacional. Os pull requests ainda apresentam zero
checks automáticos.

Esta tarefa cria evidência automática antes da decisão humana de merge.

## Scope

### In

- criar `.github/workflows/ci.yml`;
- executar CI em pull requests direcionados a `dev` e `main`;
- validar sintaxe JSON dos workflows versionados em `workflows/`;
- executar testes do `services/enricher`;
- executar testes do `services/web`;
- usar Python 3.12;
- disponibilizar `ffmpeg` para os testes do Enricher;
- manter permissões do workflow somente leitura;
- usar runners hospedados e efêmeros do GitHub;
- fixar ações externas por commit SHA completo.

### Out

- deploy;
- acesso à VPS;
- runner self-hosted;
- acesso a Docker socket;
- secrets de produção;
- PostgreSQL real;
- Cloudflare R2 real;
- Google Speech-to-Text real;
- testes do downloader enquanto não houver suíte própria;
- Playwright;
- staging;
- auto-merge;
- tornar checks obrigatórios nos rulesets nesta tarefa.

## Acceptance Criteria

- um PR para `dev` dispara a CI;
- workflow JSON validation termina com sucesso para os quatro exports atuais;
- suíte do Enricher executa sem credenciais externas;
- suíte Web executa sem banco real;
- nenhuma credencial de produção é fornecida ao runner;
- workflow possui permissões explícitas de somente leitura;
- nenhuma etapa acessa serviços de produção;
- falha de qualquer job aparece como check falho no Pull Request;
- sucesso de todos os jobs aparece como checks aprovados no Pull Request.

## Architecture / Technical Plan

Um workflow GitHub Actions com jobs independentes:

1. `repository-validation`
   - checkout;
   - Python 3.12;
   - parse dos JSONs usando biblioteca padrão.

2. `enricher-tests`
   - checkout;
   - Python 3.12;
   - instalação de ffmpeg;
   - instalação de `services/enricher/requirements.txt`;
   - execução de pytest no diretório do Enricher.

3. `web-tests`
   - checkout;
   - Python 3.12;
   - instalação de `services/web/requirements.txt`;
   - execução de pytest no diretório Web.

O workflow usa `pull_request`, não `pull_request_target`.

## UX Specification Reference

N/A.

## Contracts Changed

Novo contrato operacional de CI para Pull Requests. Nenhum contrato de produto,
API ou runtime é alterado.

## Data / Migration Impact

N/A.

## Security Impact

- workflow sem secrets;
- `permissions: contents: read`;
- runners hospedados e efêmeros;
- nenhuma rota privada ou endpoint de produção;
- nenhuma credencial Google, R2 ou PostgreSQL;
- sem `pull_request_target`;
- ações externas pinadas por SHA completo.

## Expected Files / Components

- `.github/workflows/ci.yml`
- `docs/TASK_CONTRACT_B3_CI_FOUNDATION.md`
- `docs/ACTIVE_TASK.md`

## Required Tests

- validar YAML/workflow estruturalmente;
- executar validação dos JSONs;
- executar suíte Enricher;
- executar suíte Web;
- observar execução real do GitHub Actions em PR.

## Required Evidence

- `git diff --check`;
- resultado dos testes;
- PR com jobs executados;
- nomes e estados dos checks;
- SHA do commit avaliado pela CI.

## Staging Requirements

N/A.

## Production Impact

Nenhum. Esta tarefa não executa deploy nem acessa produção.

## Rollback / Recovery

Remover ou reverter `.github/workflows/ci.yml` por novo PR.

Os rulesets ainda não dependerão desses checks nesta tarefa, portanto uma falha
da CI inicial não bloqueia permanentemente o fluxo de integração.

## Human Gates

Michel revisa e autoriza o merge do PR para `dev`.

A configuração futura de required status checks será uma tarefa separada após a
CI demonstrar execução estável.

## Dependencies

- GitHub Actions;
- Python 3.12;
- ffmpeg para testes do Enricher;
- requirements já versionados no repositório.

## Open Questions

- N/A.

## Final Evidence Summary

Evidência local coletada:

- Python 3.12 disponível;
- ffmpeg disponível;
- 4 workflows n8n validados como JSON;
- preflight de segurança do workflow aprovado;
- Enricher: 58 testes aprovados;
- Web: 42 testes aprovados;
- `git diff --check` aprovado.

Evidência remota coletada no Pull Request #4:

- workflow `CI` executado com sucesso;
- `Repository validation`: success;
- `Web tests`: success — 42 testes aprovados;
- `Enricher tests`: success — 58 testes aprovados;
- runner GitHub-hosted;
- `GITHUB_TOKEN` efetivo com `Contents: read`;
- actions externas executadas pelos SHAs pinados;
- checkout executado com `persist-credentials: false`.

A validação local e remota foi concluída.

O caminho de falha não foi injetado deliberadamente nesta tarefa; required status
checks continuam fora do escopo e serão tratados separadamente.

A tarefa está em `HUMAN_GATE`, aguardando decisão humana sobre a integração em
`dev`.
