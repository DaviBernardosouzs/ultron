"""ATLAS: busca universal. Não tem índice próprio: consulta o que já existe.

Fontes:
  documentos   NEURALINK (Obsidian, pastas, PDFs, repositórios, páginas, conversas salvas)
  memorias     NEURALINK, só a pasta Memórias do cofre
  conversas    histórico de pedidos/respostas (dados/auditoria.log)
  atividades   Chronos (eventos, agenda, evolução, tarefas do desktop)
  arquivos     catálogo do Archive (nome, tipo, pasta)
Os resultados de todas as fontes são fundidos por Reciprocal Rank Fusion e cada um
diz de onde veio. Filtros: projeto, período (como no Chronos) e fontes.
Serviços MCP não entram: cada plugin tem uma API diferente e a busca neles fica
com a ferramenta usar_plugin (dito ao modelo em vez de fingir que foi buscado).
"""
import json
import re

from core import chronos, cofre
from core.config import DADOS

FONTES = ("documentos", "memorias", "conversas", "atividades", "arquivos")
RRF = 60


def _termos(t):
    return {cofre._sem_acento(x) for x in re.findall(r"[\wÀ-ú]{3,}", t.lower())} - cofre.STOP


def _pontuar(consulta, texto):
    q = _termos(consulta)
    if not q:
        return 0
    return len(q & _termos(texto)) / len(q)


def _conversas(consulta, ini, fim, k):
    pares, pedido = [], None
    try:
        linhas = (DADOS / "auditoria.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    for l in linhas:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if e.get("evento") == "pedido":
            pedido = e
        elif e.get("evento") == "resposta" and pedido:
            if (not ini or pedido["quando"] >= ini) and (not fim or pedido["quando"] <= fim):
                texto = f"Davi: {pedido.get('texto', '')}\nUltron: {e.get('texto', '')}"
                nota = _pontuar(consulta, texto)
                if nota >= 0.5:
                    pares.append((nota, pedido["quando"], texto))
            pedido = None
    pares.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [{"fonte": "conversas", "titulo": f"conversa de {q[:16].replace('T', ' ')}", "texto": t[:600],
             "origem": f"auditoria.log @ {q}", "quando": q, "projeto": None} for _, q, t in pares[:k]]


def buscar(consulta, projeto=None, periodo=None, fontes=None, k=12):
    fontes = [f for f in (fontes or FONTES) if f in FONTES]
    ini, fim = chronos.periodo(periodo) if periodo else (None, None)
    listas = {}
    if "documentos" in fontes or "memorias" in fontes:
        from neuralink import busca
        raiz_mem = str(cofre.raiz().resolve()) + "/Memórias/"
        achados = busca.buscar(consulta, k=k * 2, projetos=[projeto] if projeto else None, isolar=bool(projeto),
                               desde=ini, ate=fim, por_documento=1)
        for r in achados:
            fonte = "memorias" if r["caminho"].startswith(raiz_mem) else "documentos"
            if fonte in fontes:
                listas.setdefault(fonte, []).append(
                    {"fonte": fonte, "titulo": r["titulo"], "texto": r["texto"][:600], "origem": r["citacao"],
                     "quando": r["indexado"], "projeto": r["projeto"], "caminho": r["caminho"], "linha": r["linha"],
                     "como": r["encontrado_por"]})
    if "conversas" in fontes and not projeto:
        listas["conversas"] = _conversas(consulta, ini, fim, k)
    if "atividades" in fontes:
        i0, f0 = (ini, fim) if ini else chronos.periodo("últimos 90 dias")
        acts = [a for a in chronos.atividades(i0, f0, projeto=projeto, fontes=["eventos", "neuralink", "agenda",
                                                                              "evolucao", "desktop"])
                if _pontuar(consulta, a["titulo"] + " " + str(a["detalhe"])) >= 0.5]
        listas["atividades"] = [{"fonte": "atividades", "titulo": a["titulo"], "texto": str(a["detalhe"])[:300],
                                 "origem": f"{a['fonte']}/{a['tipo']} @ {a['quando'][:16]}", "quando": a["quando"],
                                 "projeto": a["projeto"]} for a in acts[:k]]
    if "arquivos" in fontes:
        from modulos import archive
        listas["arquivos"] = [{"fonte": "arquivos", "titulo": a["nome"], "texto": f"{a['categoria']} · {a['tamanho'] // 1024} KB",
                               "origem": a["caminho"], "quando": a["mtime_iso"], "projeto": None, "caminho": a["caminho"]}
                              for a in archive.buscar(consulta, limite=k)]
    # fusão por posição em cada lista (RRF)
    pontos, itens = {}, {}
    for fonte, lista in listas.items():
        for i, r in enumerate(lista):
            chave = (r["fonte"], r["origem"])
            pontos[chave] = pontos.get(chave, 0) + 1 / (RRF + i)
            itens[chave] = r
    ordem = sorted(pontos, key=pontos.get, reverse=True)[:k]
    return [itens[c] | {"relevancia": round(pontos[c] * 1000, 1)} for c in ordem]
