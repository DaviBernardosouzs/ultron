# Livros do Ultron (08/11/2026)

Conhecimento vindo de livros e textos reais, com fonte e licença, fragmentado por seção e
indexado no NEURALINK (palavras + vetores na GPU do desktop).

## Como funciona

```
conhecimento/catalogo.yaml   61 obras (área, título, autor, fonte, licença)
conhecimento/importar.py     baixa, converte, fragmenta e grava no cofre
conhecimento/openstax.py     livros-texto da OpenStax pelo código-fonte (CNXML + MathML)
```

```
uv run python -m conhecimento.importar              # importa o que falta
uv run python -m conhecimento.importar --obra "On War" --refazer
```

Cofre: `Livros/<Área>/<Obra>/NNN - <seção>.md` (um fragmento por capítulo/seção; seções
longas viram partes de até ~14 mil caracteres), `Livros/<Área>/<Obra>.md` (ficha com sumário),
`Livros/<Área>/<Área>.md` e `Livros/Índice dos Livros.md`. O NEURALINK divide cada fragmento em
trechos de ~1.100 caracteres. Downloads ficam em `dados/livros/` (cache; reimportar não baixa de novo).

Divisão em fragmentos:
- livros-texto (OpenStax): a ordem e os títulos vêm da coleção oficial do livro; uma seção por
  fragmento ("3.6 The Chain Rule"); a matemática vira notação linear (`h′(x) = f′(g(x))g′(x)`,
  `∫_a^b f(x)dx`, `dy/dx`). O PDF da OpenStax desenha as fórmulas como vetores; extraído com
  pdftotext, ele perde toda a matemática. Por isso o fonte.
- Gutenberg: capítulos pelos cabeçalhos (CHAPTER/BOOK/PART/CANTO...); o sumário é reconhecido
  (cabeçalhos em fila) e descartado; romances com capítulo só em numeral romano também.
- Wikipédia (pt): uma seção `##` por fragmento, sem referências/ligações externas.

Uso pelo Ultron:
- pergunta factual: o contexto automático do NEURALINK já traz trechos relevantes, e a ferramenta
  `consultar_livros` (obra, autor, seção, licença; filtro por área) entra nas ferramentas do pedido;
- busca por significado é multilíngue (embeddinggemma): pergunta em português acha trecho em inglês.

## Acervo (61 obras, ~3.240 fragmentos, ~28,6 mil trechos)

| Área | Obras |
|---|---|
| Física | University Physics 1–3 (OpenStax); Einstein, *Relativity: The Special and General Theory*; Carroll, *Lecture Notes on General Relativity* (arXiv); Wikipédia: Relatividade geral, Mecânica quântica |
| Cálculo | Calculus 1–3 (OpenStax: limites, derivadas, integrais, séries, cálculo vetorial/multivariável = "cálculo 3"); Thompson, *Calculus Made Easy*; Wikipédia: Limite, Derivada, Integral, Cálculo vetorial |
| Programação | Introduction to Python Programming (OpenStax, com código); Introduction to Computer Science (OpenStax, PDF) |
| Inteligência Artificial | Principles of Data Science (OpenStax); Wikipédia: IA, Aprendizado de máquina, Rede neural artificial, Aprendizagem profunda |
| Sociologia | Introduction to Sociology 3e (OpenStax); Durkheim, *Elementary Forms of the Religious Life*; Veblen, *Theory of the Leisure Class*; Tocqueville, *Democracy in America* I; Wikipédia: Sociologia |
| Militarismo | Clausewitz, *On War*; Sun Tzu, *The Art of War*; Jomini, *The Art of War*; *Lectures on Land Warfare* (1922); Wikipédia: Militarismo, História militar |
| Armas | Wikipédia: Arma de fogo, Pólvora, Artilharia, Carro de combate (história e tecnologia) |
| Aviação | Irmãos Wright, *The Early History of the Airplane*; Zerbe, *Aeroplanes*; Talbot, *Aeroplanes and Dirigibles of War*; FAA, *Airplane Flying Handbook*; Wikipédia: Avião, Motor a jato, Avião de caça, História da aviação |
| Culturas | Brasil: Wikipédia + *Dom Casmurro*, *Memórias Póstumas de Brás Cubas*, *Iracema*. Alemanha: Wikipédia + Tácito, *Germania*; Goethe, *Faust I*. França: Wikipédia + Voltaire, *Candide*. Itália: Wikipédia + Dante, *Inferno* (trad. Longfellow); Maquiavel, *O Príncipe* |
| Xadrez | Capablanca, *Chess Fundamentals*; Edward Lasker, *Chess Strategy*; Wikipédia: Xadrez, Abertura |

## Licenças e limites

- Só entra o que pode ser copiado: domínio público (Gutenberg, governo dos EUA/FAA), CC BY-SA
  (Wikipédia) e CC BY-NC-SA (OpenStax: uso pessoal, não comercial, com atribuição; se o Ultron
  virar produto, retirar). As notas de Carroll são distribuídas pelo autor no arXiv (uso pessoal).
  Livros comerciais com direitos autorais não foram baixados.
- Armas: só história e tecnologia geral; nada de fabricação.
- A maior parte dos livros é em inglês; as respostas são em português com a obra citada.
- Obras curtas sem capítulos marcados (Fausto, Germania, palestras, Early History) ficam em blocos.
- O PDF de Computer Science e o manual da FAA perdem tabelas/figuras (só texto).
- Os vetores precisam do desktop (Ollama). Sem ele, a busca por palavras continua funcionando,
  mas uma pergunta em português não encontra texto em inglês.
- Acrescentar obra: uma linha no catálogo + `importar --obra`.
