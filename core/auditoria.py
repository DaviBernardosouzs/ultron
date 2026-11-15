"""Registro de tudo que o Ultron executa (dados/auditoria.log)."""
import json
import logging
from datetime import datetime

from core.config import DADOS

ARQ = DADOS / "auditoria.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(DADOS / "ultron.log", encoding="utf-8")],
)


def registrar(evento, **campos):
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "evento": evento, **campos}
    with ARQ.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    # pedido/resposta do usuário também são eventos de tarefa no barramento
    if evento in ("pedido", "resposta"):
        try:
            from core import eventos
            if evento == "pedido":
                eventos.nova_correlacao()
                eventos.emitir("task.started", "cerebro", {"pedido": campos.get("texto", "")})
            else:
                eventos.emitir("task.completed", "cerebro", {"resposta": campos.get("texto", "")})
        except Exception:
            pass
