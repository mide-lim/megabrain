---
name: megabrain-storytelling
description: Transforma a evolução do MegaBrain em narrativa fiel e útil.
version: 1.0.0
author: MegaBrain
platforms: [linux]
metadata:
  hermes:
    tags: [megabrain, storytelling, communication, documentation]
    category: megabrain
---

# MegaBrain Storytelling

## Purpose

Transformar o desenvolvimento real do MegaBrain em uma narrativa compreensível,
interessante e fiel ao projeto.

A narrativa deve explicar principalmente:

- qual problema existia;
- por que determinada decisão foi tomada;
- como o projeto evoluiu;
- o que deu errado ou precisou ser revisto;
- o que foi aprendido;
- como a experiência influencia o próximo passo.

Storytelling não é propaganda.

Storytelling não deve esconder complexidade nem inventar sucesso.

## When to Use

Use esta skill quando o usuário quiser:

- contar a evolução do MegaBrain;
- transformar uma etapa técnica em história;
- escrever uma retrospectiva;
- preparar conteúdo para LinkedIn;
- preparar apresentação;
- explicar uma decisão arquitetural;
- registrar aprendizados;
- mostrar o processo de construção do projeto;
- comunicar uma Sprint ou marco técnico.

Também use quando o usuário explicitamente pedir "Storytelling".

## Sources of Truth

Antes de escrever, consulte conforme necessário:

1. `docs/ROADMAP.md`
2. `docs/DECISIONS.md`
3. `docs/CURRENT_STATE.md`
4. `docs/ARCHITECTURE.md`
5. workflows relevantes em `workflows/`
6. `git log`
7. diffs ou commits relevantes
8. contexto fornecido diretamente pelo usuário

Use `AGENTS.md` para respeitar as regras do projeto.

Não invente fatos para melhorar a narrativa.

## Evidence Rules

Diferencie sempre:

- o que foi implementado;
- o que foi declarado como concluído pelo responsável;
- o que foi validado;
- o que foi apenas planejado;
- o que continua sendo hipótese ou possibilidade futura.

Nunca apresente roadmap como funcionalidade existente.

Nunca apresente configuração versionada como prova de funcionamento em
produção.

## Narrative Principle

O foco principal não deve ser:

"qual ferramenta de IA foi utilizada?"

O foco deve ser:

"como o trabalho foi organizado e por que esse modo de trabalhar foi escolhido?"

Ao contar o MegaBrain, valorize quando relevante:

- autonomia sobre os dados;
- construção gradual do sistema;
- separação de responsabilidades;
- uso de agentes como parte de um processo de trabalho;
- humano como responsável por decisões e aprovação;
- IA como participante de um sistema, não como substituta do processo;
- criação de um modo próprio de trabalhar com IA;
- experimentação, validação e aprendizado.

Tecnologias devem aparecer como consequência das decisões, não como
protagonistas automáticas da narrativa.

## Story Structure

Não é obrigatório usar todas as etapas, mas a narrativa deve normalmente
seguir esta progressão:

### 1. Contexto

Onde estávamos.

### 2. Problema

Qual limitação, dúvida ou necessidade apareceu.

### 3. Decisão

Qual caminho escolhemos e por quê.

### 4. Construção

O que foi feito.

### 5. Atrito

Erro, limitação, descoberta ou trade-off relevante.

Não invente um problema caso não tenha existido.

### 6. Validação

Como verificamos que a etapa atingiu o objetivo.

### 7. Aprendizado

O que essa experiência ensinou sobre sistema, arquitetura ou processo.

### 8. Próximo passo

Como o aprendizado influencia a evolução seguinte.

## Core Story Arc

Quando fizer sentido, pense em:

Descobri
→ Estudei
→ Decidi
→ Construí
→ Errei ou questionei
→ Validei
→ Aprendi
→ Evoluí

A história não precisa conter explicitamente esses títulos.

Eles representam a progressão do raciocínio.

## Output Modes

Adapte o texto ao objetivo solicitado.

### Project Log

Registro técnico e cronológico.

Prioriza:
- decisões;
- implementação;
- validação;
- próximos passos.

### Retrospective

Prioriza:
- problema;
- decisões;
- erros;
- aprendizados;
- mudanças de entendimento.

### LinkedIn

Prioriza:
- uma ideia central;
- leitura fluida;
- contexto técnico suficiente;
- reflexão;
- aprendizado transferível para outras pessoas.

Evite excesso de detalhes operacionais.

Não use tom de propaganda ou frases genéricas sobre IA.

### Presentation

Prioriza:
- sequência lógica;
- problema;
- arquitetura;
- decisões;
- resultados;
- aprendizados.

### Technical Story

Prioriza o raciocínio arquitetural e mostra por que cada componente existe.

## Writing Style

Prefira:

- linguagem direta;
- raciocínio progressivo;
- poucos blocos significativos;
- exemplos concretos;
- reflexão técnica;
- primeira pessoa quando o usuário estiver contando sua própria experiência;
- termos técnicos apenas quando ajudam a compreensão.

Evite:

- hype;
- exageros;
- slogans vazios;
- "revolucionário";
- "game changer";
- afirmações de sucesso sem evidência;
- listas enormes;
- transformar a história em documentação de API;
- focar apenas nas ferramentas usadas.

## Handling Failures

Erros e tentativas não devem ser escondidos quando forem relevantes.

Mostre:

problema
→ hipótese
→ tentativa
→ resultado
→ aprendizado

Não dramatize falhas pequenas.

O objetivo é mostrar evolução de entendimento.

## Security and Privacy

Nunca publique ou reproduza em narrativas:

- tokens;
- senhas;
- API keys;
- IDs pessoais;
- IDs internos de produção desnecessários;
- conteúdo de `.env`;
- credenciais;
- dados privados.

Workflows sanitizados podem ser usados como evidência técnica.

## Procedure

1. Identifique qual momento ou decisão será contado.
2. Identifique público e formato quando isso afetar a narrativa.
3. Consulte as fontes relevantes.
4. Separe fatos, decisões, aprendizados e futuro.
5. Escolha uma única ideia central para a história.
6. Monte a progressão narrativa.
7. Escreva a primeira versão.
8. Remova detalhes que não contribuem para a ideia central.
9. Verifique fatos contra o contexto do projeto.
10. Termine com aprendizado ou direção, não com propaganda.

## Verification

Antes de entregar:

- toda afirmação importante possui suporte no projeto ou contexto do usuário;
- nenhuma intenção futura aparece como concluída;
- decisões técnicas possuem contexto;
- nenhum segredo ou identificador pessoal foi incluído;
- a narrativa explica "por quê", não apenas "o quê";
- existe uma linha de raciocínio clara;
- a voz do texto permanece humana e não promocional.
