# Motor cognitivo do Ultron — auditoria, benchmark e Fase 2 (08/11/2026)

## 1. Estado real dos recursos

| Recurso | Estado | Evidência |
|---|---|---|
| Cérebro Gemini (`core/cerebro_gemini.py`) | **Funcional** | conversa real respondida no teste ao vivo |
| Cérebro Claude (`core/cerebro.py`) | Parcial | código pronto, `ANTHROPIC_API_KEY` vazia |
| Registro de ferramentas + Guardian | **Funcional** | 127 ferramentas; testes 1 e 5 |
| NEURALINK (busca híbrida, grafo, memória) | **Funcional** | Recall@5 100% no cofre real (só palavras com desktop desligado) |
| Atlas, Archive, Scribe, Chronos | **Funcional** | testes das fases 1–2 |
| Cortex (decisão), Vector (planos) | **Funcional**, IA via Ollama/nuvem | testes da fase 3 |
| Claude Code Bridge | Parcial | testado com executor simulado; nenhuma execução paga real |
| WorkSpaces, Sentinel, Macro Forge, Self Audit, Oracle, Synapse | **Funcional** | testes das fases 5–7 |
| Digital Twin | Parcial | lógica pronta e rodada no ambiente real; falta ferramenta/aba/teste |
| Prism, Helios | Planejado | Helios depende de Home Assistant (não configurado) |
| Classificação de intenção | **Novo** | 100% em dev/validação/teste |
| Seleção progressiva de ferramentas | **Novo** | abaixo |
| World Observation (God's Eye) | Somente projeto clonado | Node 24 ausente no desktop |

Duplicações encontradas: `lembrar` × `lembrar_informacao`; `diagnostico_ultron` × `auditar_ultron`;
duas buscas de memória (cofre Gemini-embeddings × NEURALINK). Ficam para consolidação.

## 2. Benchmark (`avaliacao/`)

`uv run python -m avaliacao.rodar [--validacao | --teste]`. 66 casos de desenvolvimento,
25 de validação e 25 de teste final, todos com verificação determinística (sem API paga).
Resultados em `avaliacao/resultados/`.

| Métrica | Linha de base | Depois (dev) | Validação | Teste final |
|---|---|---|---|---|
| Ferramentas enviadas por pedido | 127 | 12,3 | 19,5 | 18,9 |
| Tokens de schemas por pedido | ~10.984 | ~1.160 (−89%) | ~1.803 | ~1.718 (−84%) |
| Ferramenta certa incluída | 100% (todas) | 100% | 100% | **87%** |
| MRR da ferramenta certa | — | 0,96 | 0,76 | 0,53 |
| Intenção (acurácia) | inexistente | 100% | 100% | 100% |
| Recuperação Recall@5 / MRR | 100% / 0,917 | igual | — | — |
| Segurança / planejamento | 100% / 100% | igual | — | — |

Integridade da avaliação: as regras foram ajustadas vendo dev e, depois, a validação
(registrada antes da correção em `20261108-0236-validacao-ANTES-da-correcao.json`). O
**teste final foi escrito depois dos ajustes** e deu 80% de inclusão na primeira e única rodada
"cega". O mecanismo de confiança (limiar escolhido só com dev/validação) levou a 87%. Os
dois casos que ainda falham pedem compreensão semântica; a descoberta progressiva cobre isso
no uso real (o modelo procura com as próprias palavras).

Teste ao vivo com o Gemini real (2 pedidos): ferramentas reduzidas, escolha correta do caminho
(plugin Playwright para ler um site), Guardian pediu aprovação. Problema observado: com a ação
negada, o modelo afirmou o título da página de memória como se tivesse lido. Limitação do
modelo a tratar no prompt/Reflex.

## 3. O que mudou (Fase 2 — Context Engineering)

- `inteligencia/ferramentas.py` (Tool Intelligence): BM25 sobre nome/descrição/módulo/parâmetros,
  stopwords e radicais do português, sinônimos indexados por radical, limiar de confiança (sem
  confiança → todas), filtro do WorkSpace ativo, perfil observado de cada ferramenta (usos,
  falhas, latência). Meta-ferramenta `buscar_ferramentas` para descoberta progressiva.
- `inteligencia/intencao.py` (Cortex): conversa, factual, memória, ferramenta, pesquisa,
  multietapas, delegação, decisão, com os sinais que decidiram.
- Context Budget Manager (`_com_memoria`): fontes escolhidas pela intenção, orçamento de
  caracteres (`inteligencia.orcamento_contexto`), evento `task.progress` com intenção, fontes,
  tamanho do contexto e ferramentas enviadas.
- Os dois cérebros declaram: seleção do pedido + ferramentas já usadas no histórico + descobertas.
- Desligar: `inteligencia.selecao_ferramentas: false` volta ao comportamento anterior.

## 4. Tecnologias sugeridas: decisão

| Tecnologia | Decisão | Por quê |
|---|---|---|
| Qdrant | não agora | SQLite FTS5 + numpy responde em ~20 ms com o volume atual; reavaliar acima de ~100 mil trechos |
| mem0 | não | duplicaria o NEURALINK (memória com escopo, retenção, consolidação já existem) |
| Graphiti | não agora | relações temporais simples já cabem em `eventos`/`historico`; sem métrica que peça grafo temporal |
| Docling | candidato | pode melhorar PDFs com tabelas; medir contra `pdftotext` antes de adotar |
| LangGraph | não | o Vector já tem plano, dependências, checkpoint, retomada e cancelamento |
| LiteLLM | não agora | só Gemini tem chave; o roteador próprio (Claude Bridge) cobre a escolha atual |
| DSPy | adiado | os componentes otimizáveis viraram determinísticos e medidos; DSPy entra quando houver dataset de chamadas reais do modelo |
| promptfoo / inspect / deepeval / ragas | não | o benchmark próprio é determinístico e sem custo; um avaliador por LLM entra só onde regras não bastam |
| Phoenix / OpenTelemetry | adiado | o barramento de eventos já correlaciona pedido → ferramentas; exportar para OTel quando houver painel externo |

## 5. Próximas fases

Hive Mind (roteador de modelos com taxa de sucesso observada), Reflex (falhas → hipóteses →
correção testada → procedimento), Cognitive Intelligence Center (painel), embeddings das
descrições de ferramentas na GPU do desktop (para os casos semânticos), consolidação das
duplicações.

## 6. Fases seguintes (08/11/2026, mesma sessão)

**Hive Mind** (`inteligencia/roteador.py`): modos automatico / avancado / privacidade / local_only
(`inteligencia.modo_modelos`, também no painel COGNIÇÃO). Esforço de raciocínio por intenção
(conversa/ferramenta: minimal; factual/memória: low; decisão/pesquisa/multietapas: medium; avançado
sobe um nível). Reservas do Gemini reordenadas pela taxa de sucesso observada. Pedido com dado
sensível (senha, CPF, cartão, conta, saúde, token...) vai ao modelo local do desktop ou é recusado
com aviso; nunca vai à nuvem. O modelo que respondeu de fato é registrado e aparece no HUD
("RESPONDEU · gemini-3.1-flash-lite"). Achado real: o principal e a 1ª reserva estavam sem cota e
as respostas vinham do flash-lite em 20–30 s.

**Reflex** (`inteligencia/reflex.py`): memória de falhas por assinatura (ferramenta genérica identificada
pelo alvo, ex. `usar_plugin:filesystem.list_dir`), classe, hipótese, correção sugerida e ids dos
eventos; resolução só com 2 sucessos do mesmo alvo depois da falha (ordem pelo `seq` do evento);
recorrente (≥3) vira necessidade na Forja uma vez; sequência de sucesso repetida vira proposta de
macro; avisos no contexto para não repetir o erro. Roda a cada ciclo do serviço do NEURALINK.
Achado real: o modelo chamou `filesystem.list_dir`, que não existe (a certa é `list_directory`).

**Cognitive Intelligence Center**: aba COGNIÇÃO na janela de módulos (último pedido com intenção,
modelo, esforço, contexto e ferramentas; memória; execução; benchmark dos três conjuntos; Reflex;
modelos com sucesso/latência; evolução).

**Benchmark depois das fases 6–8** (137 ferramentas): dev 100% / MRR 0,96 / ~1.188 tokens;
validação 100% / 0,76; teste 93% / 0,56. O teste deixou de ser cego: a correção de "site/url/link"
foi motivada por uma falha vista nele.

Bugs encontrados por repetição da suíte (8×) e corrigidos: corrida de milissegundos na resolução do
Reflex; hash de commit só com dígitos lido errado pelo changelog do Scribe.
