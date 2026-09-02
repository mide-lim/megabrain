# Definition of Done

A Definition of Done (DoD) estabelece a evidência mínima para considerar uma tarefa pronta. Todo perfil inclui os critérios globais e o perfil específico aplicável. O Task Contract pode acrescentar requisitos conforme o risco.

## Checagens globais

- objetivo satisfeito;
- critérios de aceitação satisfeitos;
- escopo respeitado;
- nenhum segredo introduzido;
- evidência de validação disponível;
- documentação atualizada quando necessário;
- caminho de rollback ou reparo compreendido quando relevante.

## Perfil: Web feature

- critérios de aceitação;
- testes unitários quando aplicáveis;
- testes de integração;
- E2E quando a infraestrutura existir;
- comportamento desktop;
- comportamento mobile;
- estado de carregamento, se aplicável;
- estado vazio;
- estado de erro;
- baseline de acessibilidade;
- revisão de segurança;
- documentação;
- CI verde quando CI existir.

## Perfil: Backend feature

- contrato definido;
- testes unitários;
- testes de integração;
- caminhos de erro;
- idempotência quando relevante;
- revisão de segurança;
- consideração de observabilidade e logs;
- consideração de rollback ou compatibilidade;
- CI verde quando CI existir.

## Perfil: Database change

- migration revisada;
- compatibilidade considerada;
- validação de avanço;
- estratégia de rollback ou restore;
- validação em staging quando staging existir;
- requisito de backup identificado;
- execução em produção classificada como Red.

## Perfil: Infra / Security

- validação de configuração;
- nenhuma exposição de segredo;
- revisão de menor privilégio;
- plano de rollback;
- validação em staging quando possível;
- gate explícito para produção.

## Perfil: Documentation

- tecnicamente precisa;
- concisa;
- sem estado de projeto contraditório;
- sem segredos;
- `git diff --check` sem erros.

## Estado atual e requisitos futuros

As verificações documentadas só são exigíveis quando a capacidade correspondente existe no repositório e no ambiente de trabalho. Hoje, `git diff --check`, inspeção de diff e validações locais disponíveis são verificações atuais. CI isolada, staging e Playwright/E2E automatizado ainda não existem; referências a elas nos perfis descrevem o alvo futuro e não devem ser declaradas como evidência atual.

A ausência de uma capacidade futura não elimina requisitos que já podem ser verificados localmente nem os gates humanos definidos pela política de risco.