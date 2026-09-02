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

- Hermes trabalha em branches `agent/*`;
- o Git central é a fonte de verdade;
- Hermes não escreve diretamente em produção ou em `dev`;
- bundle, revisão e integração manual ainda existem;
- CI e staging ainda não existem;
- produção é operada por humanos.

Assim, o ciclo alvo é aplicado até onde houver capacidade real. A validação atual usa evidência local disponível, inspeção e gates humanos; não deve simular CI, staging ou promoção automática.

## Direção futura

O alvo é criar um caminho de escrita em branches de agentes, CI isolada, evidências, staging, gates baseados em risco e eventual progressão autônoma de trabalho de baixo risco. Essas capacidades são entregas futuras. Não há hoje auto-merge, deploy automático, capacidade de push por Hermes ou promoção autônoma.