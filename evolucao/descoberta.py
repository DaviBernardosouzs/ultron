"""Capability Discovery + Self-Diagnostics.

Descoberta: quando falta uma capacidade, registra a necessidade e procura, nesta
ordem: (1) ferramentas já instaladas, (2) skills, (3) plugins MCP do catálogo que
só precisam de configuração, (4) servidores MCP e bibliotecas conhecidas na web.
Só se nada servir propõe desenvolver algo novo.

Diagnóstico: lê os logs, a auditoria e as avaliações e aponta o que está falhando.
"""
import json
import math
import re
from collections import Counter

from core import cofre
from core.config import DADOS
from evolucao.base import agora, ler, novo_id, registrar, tabela


def registrar_necessidade(descricao, contexto=""):
    with tabela("necessidades") as d:
        for n in d:   # mesma necessidade aberta não duplica
            if n["estado"] == "aberta" and n["descricao"].lower() == descricao.lower():
                n["vezes"] = n.get("vezes", 1) + 1
                return n["id"]
        nid = novo_id("N")
        d.append({"id": nid, "descricao": descricao, "contexto": contexto[:500], "criado": agora(),
                  "estado": "aberta", "vezes": 1, "solucoes": []})
    registrar("necessidade", nome=nid, descricao=descricao)
    return nid


def necessidades():
    return ler("necessidades")


def _parecidas(consulta, docs, k=5):
    """BM25 curto: docs = [(id, texto)]."""
    q = cofre._tokens(consulta)
    toks = [(i, cofre._tokens(t)) for i, t in docs]
    n = len(toks) or 1
    df = Counter(w for _, d in toks for w in set(d))
    media = sum(len(d) for _, d in toks) / n or 1
    pont = []
    for i, d in toks:
        tf = Counter(d)
        s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2
                / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / media)) for w in q if w in tf)
        if s:
            pont.append((s, i))
    return [i for s, i in sorted(pont, reverse=True)[:k] if s > 1.5]


def investigar(nid, usar_web=True):
    from core import plugins, registro
    from evolucao import skills
    nec = next((n for n in necessidades() if n["id"] == nid), None)
    if not nec:
        raise KeyError(nid)
    alvo = nec["descricao"]
    solucoes = []
    ferramentas = [(f.nome, f"{f.nome} {f.descricao}") for f in registro.todas()]
    for nome in _parecidas(alvo, ferramentas, 3):
        solucoes.append({"tipo": "ferramenta instalada", "nome": nome, "acao": "já existe: use"})
    for s in _parecidas(alvo, [(x["nome"], f"{x['nome']} {x['descricao']}") for x in skills.instaladas()], 2):
        solucoes.append({"tipo": "skill instalada", "nome": s, "acao": "usar_skill"})
    try:
        cat = plugins.configuracao()
        for nome in _parecidas(alvo, [(n, f"{n} {c.get('descricao', '')}") for n, c in cat.items()], 3):
            falta = plugins.faltando(cat[nome])
            solucoes.append({"tipo": "plugin MCP do catálogo", "nome": nome,
                             "acao": f"configurar {', '.join(falta)} no .env" if falta else "já disponível"})
    except Exception:
        pass
    if usar_web and not solucoes:
        from ferramentas.web import pesquisar_web
        for consulta in (f"MCP server {alvo} github", f"python library {alvo}"):
            try:
                texto = pesquisar_web(consulta, 4)
                for bloco in texto.split("\n\n")[:4]:
                    linhas = bloco.splitlines()
                    if len(linhas) >= 2 and linhas[1].startswith("http"):
                        solucoes.append({"tipo": "na web", "nome": re.sub(r"^\d+\.\s*", "", linhas[0])[:100],
                                         "url": linhas[1], "acao": "avaliar (conteúdo externo, não confiável)"})
            except Exception:
                pass
    if not any(s["tipo"] != "na web" for s in solucoes):
        solucoes.append({"tipo": "desenvolver", "nome": alvo,
                         "acao": "criar_ferramenta ou criar_skill (vai para teste e aprovação)"})
    with tabela("necessidades") as d:
        for n in d:
            if n["id"] == nid:
                n["solucoes"] = solucoes
                n["investigado"] = agora()
    registrar("investigacao", nome=nid, descricao=alvo, resumo=f"{len(solucoes)} opções")
    return solucoes


def marcar(nid, estado):
    with tabela("necessidades") as d:
        for n in d:
            if n["id"] == nid:
                n["estado"] = estado


# ------------------------------------------------------------------ autodiagnóstico

def diagnostico(linhas=3000):
    achados = []
    log = DADOS / "ultron.log"
    if log.exists():
        erros = Counter()
        for l in log.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]:
            m = re.search(r"\b(ERROR|WARNING)\b\s+(\S+)?:?\s*(.*)", l)
            if m:
                msg = re.sub(r"\d+(\.\d+)?", "N", m.group(3))[:120]
                erros[(m.group(1), m.group(2) or "", msg)] += 1
        for (nivel, origem, msg), n in erros.most_common(8):
            achados.append({"fonte": "log", "nivel": nivel, "origem": origem, "problema": msg,
                            "vezes": n})
    aud = DADOS / "auditoria.log"
    if aud.exists():
        falhas = Counter()
        for l in aud.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]:
            try:
                e = json.loads(l)
            except Exception:
                continue
            if e.get("evento") == "erro":
                falhas[e.get("ferramenta")] += 1
        for nome, n in falhas.most_common(5):
            achados.append({"fonte": "auditoria", "nivel": "ERROR", "origem": nome,
                            "problema": "ferramenta com erros", "vezes": n})
    from evolucao import avaliacao
    for r in avaliacao.todas()[:20]:
        if not r["aprovado"]:
            achados.append({"fonte": "avaliação", "nivel": "WARNING", "origem": r["candidato"],
                            "problema": "; ".join(r["motivos"])[:150], "vezes": 1})
    from evolucao import capacidades
    _, falhas_cap = capacidades.resumo()
    for nome in falhas_cap:
        achados.append({"fonte": "inventário", "nivel": "WARNING", "origem": nome,
                        "problema": "capacidade indisponível", "vezes": 1})
    for a in achados:
        a["sugestao"] = _sugestao(a)
    registrar("diagnostico", resumo=f"{len(achados)} achados")
    return achados


def _sugestao(a):
    p = (a["problema"] + " " + a["origem"]).lower()
    if "429" in p or "quota" in p or "cota" in p or "limitado" in p:
        return "cota da API esgotada: espere, troque de modelo ou adicione outra chave"
    if "falta" in p and a["fonte"] == "inventário":
        return "configure a chave no .env para ativar"
    if "timeout" in p or "tempo" in p:
        return "aumente o tempo limite ou verifique se a máquina está ligada"
    if a["fonte"] == "avaliação":
        return "corrija o candidato e avalie de novo"
    if a["fonte"] == "auditoria":
        return "veja os argumentos usados; pode virar uma necessidade de correção"
    return "investigar"
