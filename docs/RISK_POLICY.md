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

Comportamento alvo: depois de existir evidência automatizada, Hermes poderá planejar, implementar, validar e eventualmente progredir trabalho Green de modo autônomo.

Hoje essa automação ainda não existe. Green não significa auto-merge, push, deploy ou integração automática atual.

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

Comportamento alvo: implementação, validação automatizada e staging, seguidos inicialmente por um gate humano de promoção.

CI e staging ainda não existem no fluxo atual. Enquanto não existirem, suas exigências são alvo de entregas futuras, não evidência disponível.

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