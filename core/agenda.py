"""Agenda e lembretes do Ultron (dados/agenda.json) e o agendador que avisa no Telegram.

Cada item:
  {id, titulo, quando: "AAAA-MM-DDTHH:MM", tipo: "lembrete"|"evento",
   aviso_min: minutos antes para avisar (None = não avisa), repetir: None|"diario"|"semanal"|"mensal",
   avisado: bool}

Vários processos (voz, texto, Telegram) usam o mesmo arquivo; o agendador roda só
no processo que conseguir a trava dados/agendador.lock, então ninguém recebe aviso
em dobro.
"""
import contextlib
import fcntl
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from core.config import DADOS

LOG = logging.getLogger("ultron.agenda")

ARQUIVO = DADOS / "agenda.json"
TRAVA = DADOS / "agenda.json.lock"
FORMATO = "%Y-%m-%dT%H:%M"


@contextlib.contextmanager
def _aberta():
    """Lê a agenda com trava exclusiva e grava ao sair."""
    with open(TRAVA, "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        itens = ler()
        yield itens
        # Grava num temporário e troca: um travamento no meio não deixa o arquivo vazio.
        tmp = ARQUIVO.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ARQUIVO)


def ler():
    if not ARQUIVO.exists() or not ARQUIVO.read_text(encoding="utf-8").strip():
        return []
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))


def interpretar_quando(quando=None, em_minutos=None):
    if em_minutos is not None:
        return (datetime.now() + timedelta(minutes=float(em_minutos))).replace(second=0, microsecond=0)
    if not quando:
        raise ValueError("informe quando (AAAA-MM-DDTHH:MM) ou em_minutos")
    try:
        q = datetime.fromisoformat(quando.strip())
    except ValueError:
        raise ValueError(f"data inválida: {quando!r} (use AAAA-MM-DDTHH:MM)") from None
    return q.replace(tzinfo=None, second=0, microsecond=0)


def adicionar(titulo, quando, tipo="lembrete", aviso_min=0, repetir=None):
    item = {"id": uuid.uuid4().hex[:6], "titulo": titulo.strip(), "quando": quando.strftime(FORMATO),
            "tipo": tipo, "aviso_min": aviso_min, "repetir": repetir, "avisado": False}
    with _aberta() as itens:
        itens.append(item)
        itens.sort(key=lambda x: x["quando"])
    return item


def remover(id_ou_titulo):
    alvo = id_ou_titulo.strip().lower()
    with _aberta() as itens:
        achados = [x for x in itens if x["id"] == alvo] or \
                  [x for x in itens if alvo in x["titulo"].lower()]
        for x in achados:
            itens.remove(x)
    return achados


def do_periodo(inicio, fim):
    return sorted((x for x in ler() if inicio <= datetime.strptime(x["quando"], FORMATO) < fim),
                  key=lambda x: x["quando"])


def _proxima(quando, repetir):
    if repetir == "diario":
        return quando + timedelta(days=1)
    if repetir == "semanal":
        return quando + timedelta(weeks=1)
    if repetir == "mensal":
        mes = quando.month % 12 + 1
        ano = quando.year + (quando.month == 12)
        for dia in (quando.day, 30, 29, 28):
            try:
                return quando.replace(year=ano, month=mes, day=dia)
            except ValueError:
                continue
    return None


def mensagem(item):
    q = datetime.strptime(item["quando"], FORMATO)
    if item["tipo"] == "evento" and item.get("aviso_min"):
        return f"⏰ Daqui a {item['aviso_min']} min ({q:%H:%M}): {item['titulo']}"
    return f"⏰ Lembrete: {item['titulo']}"


def pendentes(agora=None):
    """Itens cujo aviso já venceu; marca como avisados (ou reagenda os repetidos)."""
    agora = agora or datetime.now()
    saida = []
    with _aberta() as itens:
        for x in list(itens):
            if x.get("avisado") or x.get("aviso_min") is None:
                continue
            q = datetime.strptime(x["quando"], FORMATO)
            if agora < q - timedelta(minutes=x["aviso_min"] or 0):
                continue
            saida.append(dict(x))
            prox = _proxima(q, x.get("repetir"))
            while prox and prox <= agora:   # PC ficou desligado: pula as vezes perdidas
                prox = _proxima(prox, x["repetir"])
            if prox:
                x["quando"] = prox.strftime(FORMATO)
            elif x["tipo"] == "lembrete":
                itens.remove(x)            # lembrete único some depois de avisado
            else:
                x["avisado"] = True        # evento continua na agenda
        # limpa eventos que já passaram há mais de 7 dias
        limite = (agora - timedelta(days=7)).strftime(FORMATO)
        itens[:] = [x for x in itens if x["quando"] >= limite or x.get("repetir")]
    return saida


# ---------------------------------------------------------------- agendador

_trava_processo = None


def iniciar_agendador(intervalo=20):
    """Liga o agendador neste processo, se nenhum outro já estiver com ele."""
    global _trava_processo
    if _trava_processo:
        return True
    f = open(DADOS / "agendador.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return False  # outro processo (ex.: serviço do Telegram) já cuida disso
    _trava_processo = f
    threading.Thread(target=_laco, args=(intervalo,), daemon=True, name="agendador").start()
    LOG.info("agendador ligado")
    return True


def _laco(intervalo):
    tg = None
    while True:
        try:
            itens = pendentes()
            if itens:
                if tg is None:
                    from core.telegram import Telegram
                    tg = Telegram()
                for x in itens:
                    tg.enviar(mensagem(x))
                    LOG.info("aviso enviado: %s", x["titulo"])
        except Exception as e:
            LOG.warning("agendador: %s", e)
        time.sleep(intervalo)
