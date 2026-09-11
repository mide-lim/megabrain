# Fluxo de desenvolvimento

Este documento descreve o ciclo de engenharia alvo e o fluxo de transição
implementado. Ele não altera permissões nem autoriza nova CI, staging, produção
ou promoção autônoma fora de um Task Contract aprovado.

## Ciclo alvo

```text
INTENT
  -> DISCOVERY
  -> TASK CONTRACT
  -> SDD / ARCHITECTURE
  -> UX SPEC (quando houver interface)
  -> IMPLEMENTATION
  -> VALIDATION
  -> INDEPENDENT REVIEW
  -> STAGING (quando necessário e disponível)
  -> DEFINITION OF DONE
  -> RISK GATE
  -> PROMOTION
  -> PRODUCTION (quando aprovada)
```

1. **Intent:** o Product Owner define objetivo, prioridade e contexto.
2. **Discovery:** explora problema, alternativas, restrições, riscos e escopo quando necessário.
3. **Task Contract:** registra objetivo, risco, escopo, critérios, evidências e gates.
4. **SDD / Architecture:** responde **como tecnicamente**, definindo solução,
   contratos, impactos, testes, risco e gates. Quando a experiência de interface
   é necessária e ainda não existe, SDD registra `UX_REQUIRED` em vez de
   inventá-la.
5. **UX spec:** quando houver interface, responde **como o usuário experiencia**
   a mudança: fluxo, hierarquia, layout, interação, estados e responsividade,
   dentro das restrições técnicas do SDD e do UI System.
6. **Implementation:** Builder/Codex responde **como a especificação é
   implementada**, mantendo o escopo aprovado.
7. **Validation:** produz evidências proporcionais ao contrato e ao risco.
8. **Independent review:** Reviewer/QA responde **se a implementação satisfaz o
   contrato**, comparando contrato, critérios, diff e evidências.
9. **Staging:** ocorre quando necessário e quando a capacidade existir.
10. **Definition of Done:** Hermes avalia a evidência contra o perfil aplicável.
11. **Risk gate e promotion:** Green, Yellow e Red seguem `RISK_POLICY.md`; produção só ocorre com aprovação humana explícita.

Hermes responde **qual papel roda a seguir e se a tarefa está pronta para
avançar**. Discovery responde **o quê e por quê**. As fronteiras detalhadas dos
papéis estão em `AGENT_ROLES.md`; este fluxo não cria novas permissões ou
capacidades de automação.

## Contrato de testes por serviço

A validação Python canônica é deliberadamente isolada por serviço; não existe um
contrato de `pytest` de repositório-raiz. Execute os testes em seus diretórios de
serviço e nos ambientes correspondentes:

```text
cd services/web && .venv/bin/python -m pytest -q
cd services/enricher && .venv/bin/python -m pytest -q
```

O frontend é validado em `apps/web` com `npm test`, `npm run lint`,
`npm run typecheck` e `npm run build`. Não altere imports ou crie um contrato
falso de pytest na raiz para coletar serviços independentes.

## Fluxo de transição atual

Hoje:

- o repositório público GitHub `mide-lim/megabrain` é a fonte de verdade de desenvolvimento;
- Hermes trabalha em branches `agent/*`;
- Hermes usa um GitHub App limitado ao repositório para publicar `agent/*` e abrir pull requests;
- `dev` e `main` são protegidas por rulesets;
- o GitHub App do Hermes não pode atualizar diretamente nem fazer merge em `dev` ou `main`;
- integração e promoção acontecem por pull request com ação humana autorizada;
- o antigo Git central privado e o workspace arquivado permanecem apenas como histórico de transição;
- bundles estão aposentados do fluxo operacional;
- CI isolada existe para Pull Requests destinados a `dev` e `main`; staging ainda não existe;
- produção continua operada e aprovada por humanos.

Assim, o ciclo alvo é aplicado até onde houver capacidade real. A validação atual
usa CI disponível, evidência local, inspeção, pull requests e gates humanos. A
existência do GitHub App não concede autoridade de produção, merge ou deploy.

A discrepância de integridade do artefato B4.2 instalado impede publicação
autenticada durante C7.1. C7.2 é necessário para reconciliar esse artefato antes
de qualquer uso posterior dessa capability.

### Lifecycle Hermes implementado

```text
INTENT / TASK CONTRACT
  -> agent/* implementation
  -> bounded Run Authorization
  -> controlled publish
  -> controlled PR creation
  -> CI observation
  -> bounded self-correction
  -> coherent CI snapshot
  -> exact-SHA READY
  -> HUMAN REVIEW / MERGE
```

`READY` é evidência limitada a um SHA exato; não concede autoridade de merge.
Hermes não tem autoridade para merge, auto-merge, force push, escrita direta em
`dev` ou `main`, mutação de workflows, rulesets ou permissões do GitHub App,
interfaces genéricas e irrestritas de Git/API/shell, acesso à produção ou deploy.
O merge humano permanece uma fronteira separada.

## Direção futura

A CI isolada e o lifecycle Hermes limitado estão implementados. B4.1 — GitHub
Auth Bootstrap, B4.2 — Autonomous PR Lifecycle e B4.3 — Bounded Run
Authorization estão `COMPLETE / PROMOTED`; as provas autenticadas limitadas e a
promoção confirmaram publicação controlada, criação de PR, observação de CI e
autocorreção limitada até o estado READY de SHA exato.

A concessão continua vinculada ao Task Contract aprovado, sem auto-merge, deploy
automático ou promoção autônoma para `dev`, `main` ou produção. A validação local
de `agent/*` é defesa em profundidade e não ACL provider-enforced. Staging ainda
não está implementado; Sprint 5 continua não aprovada e Engineering Enablement
permanece separado do roadmap de produto.
