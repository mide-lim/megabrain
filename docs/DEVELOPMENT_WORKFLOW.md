# Fluxo de desenvolvimento

Este documento descreve o ciclo de engenharia alvo e o fluxo de transição que vale hoje. Ele não altera permissões nem cria CI, staging, Git write access ou promoção autônoma.

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
## Direção futura

A CI isolada e as primeiras evidências determinísticas já existem. B4.2
Autonomous PR Lifecycle está `IMPLEMENTED / HUMAN_GATE`: a capability local foi
validada hermeticamente e instalada como artefato derivado, mas nenhuma operação
GitHub autenticada foi executada. B4.1 está `COMPLETE / PROMOTED` e fornece
somente autenticação GitHub App read-only comprovada; não habilita escrita nova.
B4.2 mantém a concessão no Task Contract aprovado, sem auto-merge, deploy
automático ou promoção autônoma para `dev`, `main` ou produção. A validação local
de `agent/*` é defesa em profundidade e não ACL provider-enforced.
