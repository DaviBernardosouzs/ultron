# NEURALINK — central de conhecimento do Ultron

Abrir: `ultron neuralink` (pede a senha) ou o botão **NEURALINK** no painel Evolução da janela.

## Arquitetura

| Componente | Arquivo | Papel |
|---|---|---|
| Banco | `neuralink/banco.py` | SQLite `dados/neuralink.db` (WAL): fontes, documentos, trechos, FTS5, vetores, entidades, relações, eventos, sugestões |
| Embeddings | `neuralink/embeddings.py` | `embeddinggemma` no Ollama do desktop (GPU), via túnel SSH; sem desktop, só palavras |
| Ingestão | `neuralink/ingestao.py` | fontes autorizadas, Markdown/PDF/texto/código/URL, trechos com seção e linha, incremental |
| Busca | `neuralink/busca.py` | híbrida: FTS5/BM25 + cosseno, fundidas por RRF; filtros; citação da origem |
| Memory Engine | `neuralink/memoria.py` | memórias = notas do cofre + escopo, confiabilidade, retenção; exclusão real; exportação; sugestões |
| Grafo | `neuralink/grafo.py` | entidades/relações (backlinks, tags, tecnologias, decisões, capacidades, tarefas) |
| Context Manager | `neuralink/contexto.py` | escolhe trechos para cada pedido, isola projetos, avisa contradições |
| Resumos | `neuralink/resumos.py` | resumo progressivo por projeto em `Resumos/<projeto>.md` |
| Serviço | `neuralink/servico.py` | reindexa o que mudou a cada 10 min; só um processo faz isso (trava) |
| Janela | `neuralink/janela.py` | grafo, explorador, busca, memória, linha do tempo, fontes |
| Ferramentas | `ferramentas/neuralink.py` | o que o orquestrador usa |

### Decisões

- **SQLite + numpy, sem Qdrant nem banco de grafos.** O volume é de milhares de trechos; a
  busca vetorial completa leva milissegundos e o grafo só precisa de 1–2 saltos.
- **Uma fonte da verdade para memórias:** as notas do Obsidian. O banco é índice derivado.
- **Embeddings locais na GPU do desktop**, porque a cota do Gemini acabava (erro 429) e o
  notebook não tem memória para um modelo.
- **Conteúdo recuperado é dado:** vai marcado `[CONTEUDO EXTERNO NAO CONFIAVEL]`, com aviso de
  nunca executar comandos dele; segredos óbvios são removidos na indexação.

## Contrato das ferramentas

| Contrato proposto | Ferramenta | Nível |
|---|---|---|
| remember_information | `lembrar_informacao` | N1 |
| search_memory | `buscar_memoria` | N1 |
| retrieve_project_context | `contexto_projeto` | N1 |
| search_documents | `buscar_documentos` | N1 |
| list_knowledge_sources | `listar_fontes_conhecimento` | N1 |
| get_related_entities | `entidades_relacionadas` | N1 |
| summarize_project | `resumir_projeto` | N1 |
| request_memory_update | `pedir_atualizacao_memoria` (só sugere) | N1 |
| request_memory_deletion | `pedir_exclusao_memoria` (só sugere) | N1 |
| get_recent_decisions | `decisoes_recentes` | N1 |
| — | `autorizar_fonte_conhecimento` | **N2** |
| — | `sincronizar_conhecimento`, `salvar_conversa`, `consolidar_memorias` | N1 |

Aplicar sugestões, excluir de vez e remover fontes só pela janela (decisão do Davi).

## Segurança

- Só fontes autorizadas; `~`, `/`, `/etc`, `~/.ssh`, `~/.config`, `~/.local`… são recusadas.
- `.env`, chaves, arquivos com "senha/credencial/token/segredo" no nome nunca entram.
- Excluir apaga nota, lixeira, trechos, FTS, vetores, entidades e o cache antigo de vetores.
- Memórias com escopo de projeto só entram no contexto quando o pedido é sobre o projeto.
- A auditoria registra o que mudou, sem guardar o conteúdo apagado.

## Testes

`uv run pytest` — 18 testes: recuperação com citação, palavras sem acento, persistência,
semântica (embedder de teste e modelo real se o desktop estiver ligado), isolamento de
projetos (documentos e memórias), contexto limitado, incremental, exclusão real (fonte e
memória), retenção, contradição vira sugestão + aviso, pedido do modelo não altera nada,
documento malicioso vira dado e segredo é removido, fontes sensíveis recusadas, grafo do
Obsidian (backlinks, tags, tecnologias) e notas originais intocadas.
