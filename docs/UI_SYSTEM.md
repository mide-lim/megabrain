# MegaBrain UI System — Baseline atual

Este documento registra a baseline observada da Web privada do MegaBrain. Não é
um redesign, não cria tokens em código e não altera a implementação atual.

## Princípios observados

- **Conteúdo primeiro:** a biblioteca privilegia identificação, caption,
  metadados, transcrição e categorias do Reel.
- **Baixo ruído visual:** superfícies claras, uma cor de destaque e cards simples
  mantêm a interface de utilidade privada direta.
- **Interação previsível:** busca é um formulário GET, navegação usa links e a
  curadoria usa formulários POST explícitos.
- **Responsivo por padrão:** largura fluida, grid adaptativo e controles que
  podem quebrar linha evitam uma composição exclusivamente desktop.
- **Acessibilidade consciente:** templates usam landmarks, labels, headings,
  listas, definições e mensagens de erro/estado em HTML semântico.

## Baseline visual atual

### Tipografia e cores

- Fonte: `Inter, ui-sans-serif, system-ui, sans-serif`.
- Texto principal: `#202522`; fundo da página: `#f3f1eb`.
- Superfícies de cards, formulários e painéis: `#fff`.
- Bordas: `1px solid #d8d5cc`; raio aplicado: `.8rem`.
- Destaque de links e tags: `#28563b`; texto secundário usa `#526257`,
  `#536358`, `#5d655f` ou `#626a64` conforme o contexto.
- Tags de categoria: fundo `#e4eee7`, texto `#28563b`, raio `999px`.
- Erro de formulário: `#8a2727` e peso `700`.
- Título principal: `clamp(2.2rem, 5vw, 4rem)`; títulos e labels relevantes usam
  peso `700`.

### Espaçamento e layout

- Corpo: `2rem clamp(1rem, 5vw, 5rem) 4rem`.
- Cabeçalho e conteúdo: largura máxima `72rem`, centralizados.
- Cards, mensagens e painéis: `1.4rem` de padding; formulários de busca usam
  `1rem`.
- Grid da biblioteca: `repeat(auto-fit, minmax(min(18rem, 100%), 1fr))` com
  gap de `1rem`.
- Formulários de busca e categoria usam flex com quebra de linha; a mídia usa
  largura máxima de `48rem` e altura máxima de `72vh`.

Não há breakpoints CSS explícitos. A responsividade atual deriva de `clamp`,
`min`, `auto-fit`, `minmax`, largura fluida e `flex-wrap`.

## Tokens

### DOCUMENTED BASELINE

Os valores CSS acima são valores reutilizados observados em
`services/web/app/static/library.css`. Eles documentam a baseline, mas não
formam um sistema formal de design tokens em código.

### FUTURE TOKENIZATION

Variáveis CSS, escalas semânticas, nomenclatura de tokens e normalização de
componentes são candidatos futuros. Nenhum deles é implementado ou exigido por
este documento.

## Componentes e padrões atuais

### Page header

- **Purpose:** identifica a página; no detalhe também oferece retorno à
  biblioteca.
- **Content:** eyebrow “MegaBrain”, `h1`, subtítulo opcional e back link no
  detalhe.
- **Behavior:** o link de retorno navega para `/`.
- **States:** conteúdo do título depende da disponibilidade do Reel.
- **Reuse guidance:** usar para páginas de alto nível da biblioteca mantendo a
  hierarquia `eyebrow -> h1 -> subtitle` quando aplicável.

### Search input

- **Purpose:** buscar creator, caption, transcript ou categoria.
- **Content:** label visível, input `type=search`, botão e link Clear condicional.
- **Behavior:** GET em `/`; paginação preserva o parâmetro `q`.
- **States:** consulta vazia, resultados, sem resultados e erro de biblioteca.
- **Reuse guidance:** preservar label e comportamento determinístico de busca;
  não substituir por interação customizada sem necessidade.

### Reel card

- **Purpose:** resumir um Reel navegável na biblioteca.
- **Content:** creator/status, ID, título-link, caption, categorias e datas
  condicionais.
- **Behavior:** o título abre o detalhe do Reel.
- **States:** campos ausentes usam omissão ou placeholder de caption; a grade só
  aparece quando há resultados.
- **Reuse guidance:** preservar a prioridade título/identificação antes de
  metadados auxiliares.

### Category tag e categoria atribuída

- **Purpose:** mostrar categorias associadas e, no detalhe, permitir removê-las.
- **Content:** nome em tag; categoria atribuída combina tag e formulário Remove.
- **Behavior:** remoção é POST protegido por CSRF.
- **States:** categorias presentes, nenhuma categoria atribuída e categorias
  disponíveis para adicionar.
- **Reuse guidance:** usar tags para classificação curta; manter ações de
  curadoria explícitas em formulários.

### Buttons and form controls

- **Purpose:** enviar busca e ações de curadoria.
- **Content:** inputs, select e botões nativos com padding local de `.5rem .7rem`
  ou `.6rem .75rem`.
- **Behavior:** formulários de categoria exigem seleção ou nome; falha de nome
  vazio e falha de persistência são comunicadas.
- **States:** controles nativos; `required` está presente onde aplicável.
- **Reuse guidance:** preferir controles HTML nativos e labels visíveis.

### Alert/message and empty state

- **Purpose:** comunicar indisponibilidade, resultados vazios e ausência de mídia
  ou conteúdo.
- **Content:** `section.message` com heading e texto, ou variante compacta para
  mídia indisponível.
- **Behavior:** erro da biblioteca usa `aria-live="polite"`; erros de curadoria
  usam `role="alert"`.
- **States:** biblioteca indisponível, sem resultados, biblioteca vazia, Reel
  inexistente/indisponível, vídeo/transcrição/caption/categorias ausentes.
- **Reuse guidance:** comunicar causa e próximo passo sem expor detalhes de
  infraestrutura.

### Pagination

- **Purpose:** navegar resultados da biblioteca.
- **Content:** links Previous/Next condicionais e página atual.
- **Behavior:** conserva `q` quando há busca.
- **States:** primeiro resultado não mostra Previous; ausência de próxima página
  não mostra Next.
- **Reuse guidance:** preservar a query atual e rótulo acessível de navegação.

### Video container and metadata block

- **Purpose:** apresentar mídia assinada e atributos do Reel no detalhe.
- **Content:** `video` com controls e `dl` de metadados; caption e transcrição em
  painéis próprios.
- **Behavior:** vídeo pode estar temporariamente indisponível; texto longo mantém
  quebras e pode quebrar palavras extensas nos metadados.
- **States:** vídeo, duração, campos e transcript podem estar ausentes.
- **Reuse guidance:** manter mídia, metadados e conteúdo longo em regiões
  separadas.

## Estados: atual versus expectativa

A aplicação SSR implementa estados de dados e erro visíveis, mas não apresenta
um estado de loading client-side. Para trabalho novo, considere conforme
aplicável: default, loading, empty, error, success e disabled. Isso é uma
expectativa de UX; não afirma que todos esses estados já existam em cada
componente.

## Responsividade

A baseline atual suporta composições mobile e desktop pela estrutura fluida
observada, sem breakpoints formalizados. Novas funcionalidades Web devem
considerar os dois contextos e explicar qualquer comportamento tablet apenas
quando ele diferir materialmente. Não introduzir breakpoints ou layouts novos
como se já fossem convenções existentes sem decisão de produto/UX.

## Acessibilidade baseline

Expectativas de engenharia para novas mudanças incluem estrutura semântica,
labels visíveis, navegação por teclado, foco visível, hierarquia de headings,
contraste suficiente e comunicação de erro.

**CURRENT INCONSISTENCY:** o CSS atual não define um estilo de foco explícito;
a visibilidade de foco depende do navegador. Antes de remover ou customizar o
foco nativo, uma mudança futura deve especificar e validar um foco visível.

**FUTURE NORMALIZATION CANDIDATE:** mensagens e estados usam padrões semânticos
úteis, mas `aria-live` não é aplicado de forma uniforme a todas as mensagens.
A normalização deve ocorrer somente quando houver uma tarefa aprovada.

Não há evidência neste repositório de validação automática de acessibilidade.

## FUTURE ENGINEERING ENABLEMENT

A automação de UX ainda é futura. Quando a capacidade existir, a integração
esperada pode incluir:

- Playwright como base inicial de regressão de navegador;
- E2E responsivo;
- screenshots e regressão visual;
- automação de acessibilidade.

Esses itens não estão instalados, configurados ou validados atualmente. Ferramentas
baseadas em agente de navegador podem complementar QA exploratório no futuro,
mas não substituem uma base de regressão determinística.
