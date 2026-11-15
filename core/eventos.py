"""Barramento de eventos operacionais do Ultron (dados/ultron.db, tabela eventos).

Formato único para todos os módulos:
  {id, tipo, quando, origem, correlacao, pai, dados}
Tipos padronizados (TIPOS): task.*, tool.*, approval.*, memory.updated,
module.status_changed, audit.completed.

- correlacao liga tudo o que aconteceu por causa de um mesmo pedido/tarefa. Ela vem
  de um ContextVar: o cérebro abre uma ao receber o pedido e cada ferramenta herda.
- 'dados' passa por um filtro antes de gravar: chaves sensíveis somem, segredos
  conhecidos são trocados por [segredo removido] e textos longos são cortados.
- Outros processos (janelas) leem pelo id crescente (consultar(apos=...)): não há
  servidor nem socket para expor.
"""
import contextvars
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from core.config import DADOS

ARQUIVO = DADOS / "ultron.db"
TIPOS = {
    "task.created", "task.started", "task.progress", "task.completed", "task.failed",
    "tool.started", "tool.completed", "tool.failed",
    "approval.requested", "approval.granted", "approval.denied",
    "memory.updated", "module.status_changed", "audit.completed",
}
CHAVES_SENSIVEIS = re.compile(r"senha|password|token|secret|segredo|chave|api[_-]?key|pin|cookie", re.I)
SEGREDO = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|"
                     r"xox[baprs]-[A-Za-z0-9-]{10,}|\b\d{8,10}:[A-Za-z0-9_-]{30,}\b)")
MAX_TEXTO = 400

correlacao_atual = contextvars.ContextVar("correlacao", default=None)
_local = threading.local()
_assinantes = []
_trava = threading.Lock()


def _con():
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "arq", None) != ARQUIVO:
        Path(ARQUIVO).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(ARQUIVO, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS eventos (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, tipo TEXT NOT NULL, quando TEXT NOT NULL,
                origem TEXT NOT NULL, correlacao TEXT, pai TEXT, dados TEXT);
            CREATE INDEX IF NOT EXISTS ix_ev_quando ON eventos(quando);
            CREATE INDEX IF NOT EXISTS ix_ev_corr ON eventos(correlacao);
            CREATE INDEX IF NOT EXISTS ix_ev_tipo ON eventos(tipo);""")
        _local.c, _local.arq = c, ARQUIVO
    return c


def limpar(v, profundidade=0):
    """Remove segredos e corta textos longos (recursivo)."""
    if profundidade > 4:
        return "…"
    if isinstance(v, dict):
        return {k: ("[omitido]" if CHAVES_SENSIVEIS.search(str(k)) else limpar(x, profundidade + 1))
                for k, x in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [limpar(x, profundidade + 1) for x in list(v)[:30]]
    if isinstance(v, str):
        v = SEGREDO.sub("[segredo removido]", v)
        return v if len(v) <= MAX_TEXTO else v[:MAX_TEXTO] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return limpar(str(v), profundidade + 1)


def nova_correlacao(prefixo="pd"):
    cid = f"{prefixo}_{uuid.uuid4().hex[:12]}"
    correlacao_atual.set(cid)
    return cid


def emitir(tipo, origem, dados=None, correlacao=None, pai=None):
    if tipo not in TIPOS:
        raise ValueError(f"tipo de evento fora do padrão: {tipo}")
    ev = {"id": f"ev_{uuid.uuid4().hex[:16]}", "tipo": tipo,
          "quando": datetime.now().isoformat(timespec="milliseconds"), "origem": origem,
          "correlacao": correlacao or correlacao_atual.get(), "pai": pai,
          "dados": limpar(dados or {})}
    try:
        with _trava:
            c = _con()
            c.execute("INSERT INTO eventos(id, tipo, quando, origem, correlacao, pai, dados) VALUES (?,?,?,?,?,?,?)",
                      (ev["id"], tipo, ev["quando"], origem, ev["correlacao"], pai,
                       json.dumps(ev["dados"], ensure_ascii=False)))
            c.commit()
    except sqlite3.Error:
        return ev     # o evento nunca derruba a ação que o gerou
    for f in list(_assinantes):
        try:
            f(ev)
        except Exception:
            pass
    return ev


def assinar(funcao):
    _assinantes.append(funcao)
    return lambda: _assinantes.remove(funcao)


def consultar(apos=None, desde=None, ate=None, tipo=None, origem=None, correlacao=None, texto=None, limite=500):
    cond, args = ["seq > ?"], [apos or 0]
    for campo, valor, op in (("quando", desde, ">="), ("quando", ate, "<="), ("origem", origem, "="),
                             ("correlacao", correlacao, "=")):
        if valor:
            cond.append(f"{campo} {op} ?")
            args.append(valor)
    if tipo:
        cond.append("tipo LIKE ?")
        args.append(tipo.replace("*", "%"))
    if texto:
        cond.append("dados LIKE ?")
        args.append(f"%{texto}%")
    linhas = _con().execute(f"SELECT * FROM eventos WHERE {' AND '.join(cond)} ORDER BY seq "
                            f"{'DESC' if apos is None else 'ASC'} LIMIT ?", args + [limite]).fetchall()
    return [dict(r) | {"dados": json.loads(r["dados"] or "{}")} for r in linhas]
