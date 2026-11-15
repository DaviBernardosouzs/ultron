"""Embeddings locais na GPU do desktop (Ollama, pelo túnel SSH de ferramentas/computacao).

O embeddinggemma é multilíngue (vai bem em pt-BR) e espera prefixos de tarefa
diferentes para consulta e documento. Se o desktop estiver desligado, devolve
None e quem chamou segue só com a busca por palavras.
"""
import logging
import time

import numpy as np
import requests

from core.config import ajuste

LOG = logging.getLogger("ultron.neuralink")
_falhou_em = 0.0
PAUSA_FALHA = 120   # segundos sem tentar de novo depois que o desktop não respondeu

_provedor_teste = None   # testes injetam um embedder determinístico aqui


def modelo():
    if _provedor_teste:
        return "teste"
    return ajuste("neuralink.modelo_embedding", "embeddinggemma")


def _prefixo(textos, consulta):
    if modelo() != "embeddinggemma":
        return textos
    if consulta:
        return [f"task: search result | query: {t}" for t in textos]
    return [f"title: none | text: {t}" for t in textos]


def gerar(textos, consulta=False, lote=32):
    """Lista de textos -> matriz float32 normalizada (n x d), ou None se indisponível."""
    global _falhou_em
    if not textos:
        return np.zeros((0, 1), dtype=np.float32)
    if _provedor_teste:
        m = np.array([_provedor_teste(t) for t in textos], dtype=np.float32)
    else:
        if time.time() - _falhou_em < PAUSA_FALHA:
            return None
        try:
            from ferramentas.computacao import _maquina, _no_ar, _ollama_url
            if not _no_ar(_maquina()[1]):
                raise ConnectionError("desktop desligado")
            url = _ollama_url() + "/api/embed"
            partes = []
            for i in range(0, len(textos), lote):
                # consulta não pode atrasar a resposta do Ultron; o modelo fica carregado 1 h
                r = requests.post(url, timeout=6 if consulta else 180, json={
                    "model": modelo(), "keep_alive": "60m",
                    "input": _prefixo([t[:6000] for t in textos[i:i + lote]], consulta)})
                r.raise_for_status()
                partes += r.json()["embeddings"]
            m = np.array(partes, dtype=np.float32)
        except Exception as e:
            _falhou_em = time.time()
            LOG.info("embeddings indisponíveis (%s); seguindo só com palavras", e)
            return None
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(normas, 1e-9)
