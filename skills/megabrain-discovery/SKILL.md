---
name: megabrain-discovery
description: Investiga contexto, alternativas e riscos antes de mudar o MegaBrain.
version: 1.0.0
author: MegaBrain
platforms: [linux]
metadata:
  hermes:
    tags: [megabrain, discovery, architecture, planning]
    category: megabrain
---

# MegaBrain Discovery

## Purpose

Usar esta skill para compreender um problema, uma ideia ou uma próxima etapa
do MegaBrain antes de transformar a discussão em implementação.

Discovery serve para descobrir, comparar, questionar e delimitar.

Discovery não é implementação.

## When to Use

Use esta skill quando o usuário quiser:

- entender uma próxima etapa do MegaBrain;
- investigar uma nova funcionalidade;
- compreender melhor arquitetura ou fluxo;
- comparar tecnologias ou caminhos;
- identificar riscos, dependências ou gargalos;
- verificar se uma ideia faz sentido antes de implementá-la;
- revisar onde o projeto parou;
- preparar contexto para uma futura implementação.

Também use quando o usuário explicitamente pedir "Discovery".

## Project Context

Antes da análise, consulte o contexto relevante do projeto.

Prioridade recomendada:

1. `AGENTS.md`
2. `docs/CURRENT_STATE.md`
3. `docs/ROADMAP.md`
4. `docs/DECISIONS.md`
5. `docs/ARCHITECTURE.md`
6. workflows relevantes em `workflows/`
7. código e configuração relacionados à questão

Não carregue arquivos sem relação com o problema apenas por existirem.

## Evidence Model

Sempre diferencie:

### Comprovado pelo código

Há lógica ou configuração versionada que sustenta a afirmação.

### Comprovado pelos workflows versionados

Há evidência nos exports sanitizados do n8n.

### Declarado pelo responsável

A informação aparece como decisão, objetivo, estado ou intenção registrada pelo
responsável do projeto.

### Ainda não comprovável

O repositório não contém evidência suficiente.

Não transforme intenção em implementação.

Não transforme configuração em evidência de execução em produção.

## Procedure

### 1. Definir a pergunta

Resuma o problema que está sendo investigado.

Identifique:

- objetivo;
- escopo;
- restrições;
- resultado esperado.

Se a pergunta já estiver suficientemente clara, não faça perguntas apenas por
formalidade.

### 2. Reconstruir o estado atual

Descubra o que já existe relacionado ao problema.

Use documentação, workflows, código e Git quando necessário.

Quando útil, Codex pode ser usado como worker somente de inspeção.

### 3. Identificar lacunas

Liste somente lacunas que realmente influenciam a decisão.

Diferencie:

- informação ausente;
- implementação ausente;
- decisão ainda não tomada;
- risco conhecido.

### 4. Explorar alternativas

Quando existirem caminhos relevantes, compare-os.

Para cada alternativa, considere conforme aplicável:

- complexidade;
- dependências;
- custo;
- segurança;
- manutenção;
- observabilidade;
- impacto na arquitetura existente;
- possibilidade de evolução futura;
- retrabalho provável.

Não crie alternativas artificiais apenas para preencher uma comparação.

### 5. Questionar decisões existentes com contexto

Decisões registradas em `docs/DECISIONS.md` são o baseline atual.

Elas podem ser reavaliadas quando houver uma razão concreta, mas não devem ser
silenciosamente substituídas.

Se recomendar mudança de uma decisão existente:

1. identifique a decisão;
2. explique o motivo da reavaliação;
3. mostre consequências;
4. aguarde decisão humana antes de tratar a mudança como aceita.

### 6. Produzir recomendação

Uma Discovery pode terminar com:

- caminho recomendado;
- opções ainda abertas;
- riscos;
- questões que exigem decisão humana;
- experimento ou prova de conceito recomendada;
- próximo passo sugerido.

Não implemente automaticamente a recomendação.

## Output Structure

Prefira uma estrutura simples:

### Objetivo

O que estamos tentando compreender.

### Estado atual

O que já existe e quais evidências sustentam isso.

### Pontos em aberto

Somente questões relevantes para a decisão.

### Caminhos possíveis

Alternativas reais, quando existirem.

### Riscos e trade-offs

Consequências importantes.

### Recomendação

O caminho que faz mais sentido e por quê.

### Próximo passo

Qual seria a menor próxima ação útil.

Não transforme a Discovery em um documento excessivamente longo quando o
problema for simples.

## Boundaries

Durante uma Discovery:

- não modificar código sem pedido explícito;
- não modificar workflows;
- não fazer commit;
- não fazer push;
- não executar Docker;
- não acessar produção;
- não acessar segredos;
- não alterar decisões oficiais silenciosamente.

Se uma implementação for solicitada depois da Discovery, trate isso como uma
nova fase do trabalho.

## Pitfalls

Evite:

- propor reescrever arquitetura sem entender o estado atual;
- sugerir nova tecnologia apenas porque é mais moderna;
- confundir hipótese com fato;
- assumir funcionamento de produção;
- ampliar o escopo prematuramente;
- gerar dezenas de etapas pequenas sem necessidade;
- repetir toda a documentação do projeto em cada análise.

## Verification

Antes de concluir:

- confirme que a recomendação respeita `AGENTS.md`;
- verifique decisões relevantes em `DECISIONS.md`;
- compare a proposta com `ROADMAP.md`;
- identifique claramente inferências;
- confirme que nenhuma alteração foi feita quando a tarefa era apenas Discovery.
