"""NEURALINK: central de conhecimento do Ultron.

Decisões de arquitetura (veja também docs/NEURALINK.md):

- Um único SQLite (dados/neuralink.db, modo WAL). FTS5 faz a busca por palavras;
  vetores ficam como BLOB float32 na tabela 'vetores' e a similaridade é calculada
  com numpy. Para alguns milhares de trechos isso responde em milissegundos e evita
  instalar Qdrant ou um banco de grafos.
- Memórias persistentes continuam sendo notas do cofre do Obsidian (core/cofre.py):
  o Davi as vê e edita lá. O NEURALINK espelha as notas no banco (busca, grafo,
  linha do tempo) e grava de volta pelo cofre. Uma fonte da verdade, não duas.
- Documentos só entram por fontes autorizadas explicitamente (tabela 'fontes').
  Nada varre o computador sozinho.
- Embeddings locais na GPU do desktop (Ollama, modelo neuralink.modelo_embedding).
  Sem desktop, a busca por palavras continua; os vetores ficam pendentes.
- Conteúdo de documentos é DADO: chega ao modelo marcado como não confiável e
  nunca é executado.

Módulos: banco (esquema), embeddings, ingestao (fontes e indexação), memoria
(Memory Engine + retenção + consolidação), busca (híbrida), grafo, contexto
(Context Manager), janela (interface).
"""
