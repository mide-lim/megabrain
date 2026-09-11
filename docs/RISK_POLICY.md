# Política de risco

Esta é a classificação canônica de risco para trabalho de engenharia. A classificação define o fluxo e os gates necessários; ela não concede acesso a produção nem altera as restrições de `AGENTS.md`.

## Green

Exemplos:

- documentação;
- testes;
- CSS dentro do sistema visual estabelecido;
- templates sem mudança comportamental sensível;
- pequenos refactors com contratos inalterados;
- tooling de desenvolvimento não produtivo.

Comportamento atual: CI isolada e bounded autonomy já existem. Hermes pode planejar, implementar e validar trabalho Green e, quando existir capability permitida, Task Contract válido e Run Authorization válido, progredir somente pelas operações explicitamente autorizadas do lifecycle.

Green não concede merge, auto-merge, escrita direta em `dev` ou `main`, bypass de proteção, acesso à produção ou deploy. A existência de automação não amplia autoridade além das capacidades e autorizações vigentes.

## Yellow

Exemplos:

- nova funcionalidade de aplicação;
- novo endpoint interno;
- nova query de leitura;
- novo fluxo de UX;
- adição de dependência;
- novo código de serviço;
- criação de arquivo de migration;
- alteração relevante de contrato.

Comportamento atual: implementação e validação automatizada podem usar a CI existente, permanecendo sujeitas às capacidades, ao Task Contract, ao Run Authorization e aos gates aplicáveis para promoção.

Staging ainda não existe no fluxo atual. A existência de CI não deve ser interpretada como evidência de staging nem como autorização de produção.

## Red

Exemplos:

- aplicar migrations em produção;
- mudança de fronteira de autenticação ou segurança em produção;
- segredos;
- grants ou roles PostgreSQL em produção;
- DNS;
- reload ou mudança de Caddy em produção;
- operação destrutiva de dados;
- deployment de produção;
- execução de rollback em produção;
- mudança de privilégios de infraestrutura.

Comportamento: exige aprovação humana explícita antes da execução. A autorização de produção é do Product Owner.

## Preparar não é executar

A classificação diferencia a preparação de uma mudança de sua execução em produção. Preparar pode exigir revisão e evidência; executar uma ação de produção continua Red.

Exemplo:

- escrever um arquivo de migration é Yellow;
- aplicar essa migration em produção é Red.

Da mesma forma, preparar um plano de rollback não autoriza sua execução em produção.

## Como aplicar

A classificação inicial é registrada no Task Contract e deve ser revisada quando o escopo mudar. Em caso de dúvida, usa-se o nível mais restritivo até que a ambiguidade seja resolvida. Um item Green que introduza mudança sensível de contrato, segurança, dados ou runtime deve ser reclassificado.