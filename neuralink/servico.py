"""Serviço de fundo do NEURALINK: mantém o índice em dia sem ninguém pedir.

Ao abrir: garante o cofre como fonte, sincroniza, espelha as capacidades no grafo
e aplica a retenção. Depois, a cada neuralink.intervalo_minutos, reindexa só o que
mudou (mtime/tamanho) e vetoriza o que ficou pendente (ex.: desktop estava
desligado). Vários processos do Ultron podem importar isto (janela, Telegram,
MCP); uma trava de arquivo garante que só um deles faz o trabalho.
"""
import fcntl
import logging
import os
import threading
import time

from core.config import DADOS, ajuste

LOG = logging.getLogger("ultron.neuralink")
_iniciado = False
_trava_arq = None


def _ciclo(primeiro):
    from neuralink import grafo, ingestao, memoria
    ingestao.garantir_cofre()
    r = ingestao.sincronizar()
    if primeiro:
        grafo.sincronizar_capacidades()
        apagadas = memoria.aplicar_retencao()
        if apagadas:
            LOG.info("retenção venceu: %s", apagadas)
    LOG.info("NEURALINK sincronizado: %s", "; ".join(r))
    try:
        from inteligencia import reflex
        LOG.info("Reflex: %s", reflex.aprender())
    except Exception as e:
        LOG.warning("Reflex falhou: %s", e)


def _laco():
    global _trava_arq
    _trava_arq = open(DADOS / "neuralink.lock", "w")
    try:
        fcntl.flock(_trava_arq, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return          # outro processo do Ultron já cuida do índice
    primeiro = True
    while True:
        try:
            _ciclo(primeiro)
        except Exception as e:
            LOG.warning("sincronização do NEURALINK falhou: %s", e, exc_info=True)
        primeiro = False
        time.sleep(max(60, int(ajuste("neuralink.intervalo_minutos", 10)) * 60))


def iniciar():
    global _iniciado
    if _iniciado or os.environ.get("NEURALINK_SEM_SERVICO"):
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True, name="neuralink").start()
