"""Chronos: inteligência temporal do Ultron.

Não cria outro armazenamento: lê e junta o que já é registrado de verdade.
  barramento de eventos (core/eventos)        tarefas, ferramentas, aprovações
  NEURALINK (eventos)                          documentos, memórias, decisões, resumos
  agenda (core/agenda)                         compromissos e lembretes (agendador real)
  evolução (historico.jsonl)                   forja, testes, aprovações de extensões
  desktop (computacao/tarefas.json)            tarefas pesadas enviadas
  auditoria (pedidos)                          o que o Davi pediu
Cada item: {quando, fonte, tipo, titulo, detalhe, projeto, correlacao}.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta

from core.config import DADOS

DIAS = {"segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5,
        "sabado": 5, "domingo": 6}


def periodo(texto=None, agora=None):
    """'hoje', 'ontem', 'semana passada', 'últimos 3 dias', 'este mês', 'AAAA-MM-DD' ou
    'AAAA-MM-DD a AAAA-MM-DD' -> (inicio, fim) em ISO."""
    agora = agora or datetime.now()
    fim_aberto = agora + timedelta(minutes=1)      # inclui o que acabou de acontecer
    t = (texto or "hoje").strip().lower()
    dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    datas = re.findall(r"\d{4}-\d{2}-\d{2}", t)
    if len(datas) == 2:
        ini, fim = datetime.fromisoformat(datas[0]), datetime.fromisoformat(datas[1]) + timedelta(days=1)
    elif len(datas) == 1:
        ini = datetime.fromisoformat(datas[0])
        fim = ini + timedelta(days=1)
    elif t in ("hoje",):
        ini, fim = dia, fim_aberto
    elif t == "ontem":
        ini, fim = dia - timedelta(days=1), dia
    elif t in ("anteontem",):
        ini, fim = dia - timedelta(days=2), dia - timedelta(days=1)
    elif m := re.search(r"(?:últim|ultim)[oa]s?\s+(\d+)\s+(dia|hora|semana)", t):
        n, un = int(m.group(1)), m.group(2)
        ini = agora - {"dia": timedelta(days=n), "hora": timedelta(hours=n), "semana": timedelta(weeks=n)}[un]
        fim = fim_aberto
    elif "semana passada" in t:
        seg = dia - timedelta(days=dia.weekday())
        ini, fim = seg - timedelta(days=7), seg
    elif "esta semana" in t or "essa semana" in t or t == "semana":
        ini, fim = dia - timedelta(days=dia.weekday()), fim_aberto
    elif "mês passado" in t or "mes passado" in t:
        primeiro = dia.replace(day=1)
        ini, fim = (primeiro - timedelta(days=1)).replace(day=1), primeiro
    elif "este mês" in t or "esse mês" in t or "este mes" in t or t == "mês":
        ini, fim = dia.replace(day=1), fim_aberto
    elif t in DIAS:
        atras = (dia.weekday() - DIAS[t]) % 7 or 7
        ini = dia - timedelta(days=atras)
        fim = ini + timedelta(days=1)
    else:
        raise ValueError(f"não entendi o período '{texto}'. Use hoje, ontem, semana passada, "
                         "últimos N dias, este mês ou datas AAAA-MM-DD")
    return ini.isoformat(timespec="seconds"), fim.isoformat(timespec="seconds")


def _jsonl(caminho):
    try:
        for l in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                yield json.loads(l)
            except ValueError:
                continue
    except FileNotFoundError:
        return


def atividades(inicio, fim, projeto=None, fontes=None, texto=None, limite=500):
    itens = []
    quer = lambda f: not fontes or f in fontes
    if quer("eventos"):
        from core import eventos
        for e in eventos.consultar(desde=inicio, ate=fim, limite=2000):
            if e["tipo"] in ("tool.started", "approval.requested"):
                continue          # o par completed/granted já conta a história
            d = e["dados"]
            titulo = d.get("ferramenta") or d.get("pedido") or d.get("resposta") or d.get("mudanca") or ""
            itens.append({"quando": e["quando"][:19], "fonte": "eventos", "tipo": e["tipo"], "titulo": str(titulo)[:160],
                          "detalhe": d.get("erro") or d.get("motivo") or "", "projeto": d.get("projeto"),
                          "correlacao": e["correlacao"]})
    if quer("neuralink"):
        try:
            from neuralink import banco
            for r in banco.conexao().execute(
                    "SELECT * FROM eventos WHERE quando BETWEEN ? AND ?" + (" AND projeto=?" if projeto else ""),
                    (inicio, fim, projeto) if projeto else (inicio, fim)):
                itens.append({"quando": r["quando"], "fonte": "neuralink", "tipo": r["tipo"], "titulo": r["titulo"],
                              "detalhe": r["detalhe"] or "", "projeto": r["projeto"], "correlacao": None})
        except Exception:
            pass
    if quer("agenda"):
        try:
            from core import agenda
            for a in agenda.ler():
                q = a["quando"] + ":00"
                if inicio <= q <= fim:
                    itens.append({"quando": q, "fonte": "agenda", "tipo": a.get("tipo", "evento"),
                                  "titulo": a["titulo"], "detalhe": "concluído" if a.get("feito") else "",
                                  "projeto": None, "correlacao": None})
        except Exception:
            pass
    if quer("evolucao"):
        for h in _jsonl(DADOS / "evolucao" / "historico.jsonl"):
            if inicio <= h.get("quando", "") <= fim:
                itens.append({"quando": h["quando"], "fonte": "evolucao", "tipo": h.get("evento", ""),
                              "titulo": h.get("nome", "") or h.get("resumo", ""), "detalhe": h.get("resumo", ""),
                              "projeto": None, "correlacao": None})
    if quer("desktop"):
        try:
            for tid, t in json.loads((DADOS / "computacao" / "tarefas.json").read_text()).items():
                if inicio <= t["inicio"] <= fim:
                    itens.append({"quando": t["inicio"], "fonte": "desktop", "tipo": "tarefa_desktop",
                                  "titulo": t["nome"], "detalhe": tid, "projeto": None, "correlacao": None})
        except Exception:
            pass
    if quer("conversa"):
        for a in _jsonl(DADOS / "auditoria.log"):
            if a.get("evento") == "pedido" and inicio <= a.get("quando", "") <= fim:
                itens.append({"quando": a["quando"], "fonte": "conversa", "tipo": "pedido",
                              "titulo": a.get("texto", "")[:160], "detalhe": "", "projeto": None, "correlacao": None})
    if projeto:
        itens = [i for i in itens if i["projeto"] == projeto]
    if texto:
        t = texto.lower()
        itens = [i for i in itens if t in (i["titulo"] + " " + str(i["detalhe"])).lower()]
    # sem duplicar: um pedido aparece pela conversa e pelo barramento
    vistos, unicos = {}, []
    for i in sorted(itens, key=lambda x: x["quando"], reverse=True):
        chave = (i["quando"][:19], i["titulo"][:60])
        if chave in vistos and vistos[chave] != i["fonte"]:
            continue          # mesmo fato visto por outra fonte
        vistos[chave] = i["fonte"]
        unicos.append(i)
    return unicos[:limite]


def resumo(itens):
    por_tipo = Counter(i["tipo"] for i in itens)
    ferramentas = Counter(i["titulo"] for i in itens if i["tipo"] == "tool.completed")
    falhas = [i for i in itens if i["tipo"] in ("tool.failed", "task.failed", "erro_sincronizacao")]
    return {"total": len(itens), "por_tipo": dict(por_tipo.most_common()),
            "ferramentas": dict(ferramentas.most_common(10)), "falhas": len(falhas),
            "pedidos": por_tipo.get("pedido", 0) + por_tipo.get("task.started", 0) // 2}


def comparar(periodo_a, periodo_b, projeto=None):
    """O que mudou entre dois períodos (contagens reais por tipo)."""
    a = resumo(atividades(*periodo(periodo_a), projeto=projeto))
    b = resumo(atividades(*periodo(periodo_b), projeto=projeto))
    tipos = sorted(set(a["por_tipo"]) | set(b["por_tipo"]))
    dif = {t: (a["por_tipo"].get(t, 0), b["por_tipo"].get(t, 0)) for t in tipos}
    return {"a": a, "b": b, "diferenca": {t: v for t, v in dif.items() if v[0] != v[1]}}
