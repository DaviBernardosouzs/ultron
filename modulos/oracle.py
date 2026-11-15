"""ORACLE: laboratório de simulações com premissas explícitas.

Cenário:
  variaveis: [{nome, origem: observado|estimado|hipotese, fonte, valor} ou distribuição:
              {tipo: uniforme, min, max} | {tipo: normal, media, desvio} | {tipo: triangular, min, moda, max}]
  formulas:  {"custo_mensal": "horas * preco_hora + fixo", ...}  (avaliadas em ordem; podem usar as anteriores)
  alternativas: {"Plano A": {"preco_hora": 50}, "Plano B": {...}}   (sobrescrevem variáveis)
  premissas: [frases]
Simula por Monte Carlo (numpy, semente fixa = reprodutível) e devolve, por alternativa e
fórmula, média, P10, P50, P90, mínimo e máximo. As fórmulas passam por um avaliador
seguro (AST com operações permitidas; nada de eval, atributos ou chamadas arbitrárias).
O relatório separa OBSERVADO (com fonte), HIPÓTESES/ESTIMATIVAS e RESULTADOS SIMULADOS, e
diz que é simulação, não previsão.
"""
import ast
import json
import math
import operator
from datetime import datetime

import numpy as np

from core import eventos

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
UNARIOS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCOES = {"min": np.minimum, "max": np.maximum, "abs": np.abs, "sqrt": np.sqrt, "log": np.log, "exp": np.exp,
           "round": np.round, "ceil": np.ceil, "floor": np.floor}
COMPARA = {ast.Gt: np.greater, ast.Lt: np.less, ast.GtE: np.greater_equal, ast.LtE: np.less_equal}


def _avaliar(no, amb):
    if isinstance(no, ast.Expression):
        return _avaliar(no.body, amb)
    if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)):
        return no.value
    if isinstance(no, ast.Name):
        if no.id not in amb:
            raise ValueError(f"variável desconhecida: {no.id}")
        return amb[no.id]
    if isinstance(no, ast.BinOp) and type(no.op) in OPS:
        return OPS[type(no.op)](_avaliar(no.left, amb), _avaliar(no.right, amb))
    if isinstance(no, ast.UnaryOp) and type(no.op) in UNARIOS:
        return UNARIOS[type(no.op)](_avaliar(no.operand, amb))
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id in FUNCOES and not no.keywords:
        args = [_avaliar(a, amb) for a in no.args]
        if no.func.id in ("min", "max") and len(args) == 2:
            return FUNCOES[no.func.id](*args)
        if no.func.id not in ("min", "max") and len(args) == 1:
            return FUNCOES[no.func.id](args[0])
        raise ValueError(f"{no.func.id}: número de argumentos inválido")
    if isinstance(no, ast.IfExp):
        return np.where(_avaliar(no.test, amb), _avaliar(no.body, amb), _avaliar(no.orelse, amb))
    if isinstance(no, ast.Compare) and len(no.ops) == 1 and type(no.ops[0]) in COMPARA:
        return COMPARA[type(no.ops[0])](_avaliar(no.left, amb), _avaliar(no.comparators[0], amb))
    raise ValueError(f"expressão não permitida: {ast.dump(no)[:80]}")


def avaliar(expr, amb):
    return _avaliar(ast.parse(expr, mode="eval"), amb)


def _amostrar(v, n, rng):
    if "valor" in v:
        return np.full(n, float(v["valor"]))
    t = v.get("tipo")
    if t == "uniforme":
        return rng.uniform(float(v["min"]), float(v["max"]), n)
    if t == "normal":
        return rng.normal(float(v["media"]), float(v["desvio"]), n)
    if t == "triangular":
        return rng.triangular(float(v["min"]), float(v["moda"]), float(v["max"]), n)
    raise ValueError(f"variável {v.get('nome')}: informe 'valor' ou uma distribuição (uniforme, normal, triangular)")


def validar(c):
    p = []
    nomes = set()
    for v in c.get("variaveis", []):
        if not str(v.get("nome", "")).isidentifier():
            p.append(f"nome de variável inválido: {v.get('nome')}")
        if v.get("origem") not in ("observado", "estimado", "hipotese"):
            p.append(f"{v.get('nome')}: origem deve ser observado, estimado ou hipotese")
        if v.get("origem") == "observado" and not v.get("fonte"):
            p.append(f"{v.get('nome')}: dado observado precisa de fonte")
        nomes.add(v.get("nome"))
    amb = {n: 1.0 for n in nomes}
    for nome, f in (c.get("formulas") or {}).items():
        try:
            avaliar(f, amb)
        except Exception as e:
            p.append(f"fórmula {nome}: {e}")
        amb[nome] = 1.0
    if not c.get("formulas"):
        p.append("o cenário não tem fórmulas")
    for alt, sub in (c.get("alternativas") or {}).items():
        for k in sub:
            if k not in nomes:
                p.append(f"alternativa {alt}: variável desconhecida {k}")
    return p


def simular(c, n=5000, semente=42):
    problemas = validar(c)
    if problemas:
        raise ValueError("; ".join(problemas))
    alternativas = c.get("alternativas") or {"cenário base": {}}
    resultados = {}
    for alt, sub in alternativas.items():
        rng = np.random.default_rng(semente)
        amb = {}
        for v in c["variaveis"]:
            vv = dict(v)
            if v["nome"] in sub:
                novo = sub[v["nome"]]
                vv = ({k: x for k, x in v.items() if k not in ("valor", "tipo", "min", "max", "media", "desvio", "moda")}
                      | (novo if isinstance(novo, dict) else {"valor": novo}))
            amb[v["nome"]] = _amostrar(vv, n, rng)
        res = {}
        for nome, f in c["formulas"].items():
            val = np.broadcast_to(np.asarray(avaliar(f, amb), dtype=float), (n,))
            amb[nome] = val
            ok = val[np.isfinite(val)]
            res[nome] = {"media": float(ok.mean()) if ok.size else math.nan,
                         "p10": float(np.percentile(ok, 10)) if ok.size else math.nan,
                         "p50": float(np.percentile(ok, 50)) if ok.size else math.nan,
                         "p90": float(np.percentile(ok, 90)) if ok.size else math.nan,
                         "min": float(ok.min()) if ok.size else math.nan, "max": float(ok.max()) if ok.size else math.nan,
                         "invalidos": int(n - ok.size)}
        resultados[alt] = res
    return {"n": n, "semente": semente, "resultados": resultados}


def _con():
    c = eventos._con()
    c.execute("CREATE TABLE IF NOT EXISTS oracle_cenarios (id INTEGER PRIMARY KEY, nome TEXT, cenario TEXT, resultado TEXT, criado TEXT, projeto TEXT)")
    return c


def salvar_e_simular(nome, cenario, projeto=None, n=5000):
    r = simular(cenario, n)
    c = _con()
    cid = c.execute("INSERT INTO oracle_cenarios(nome, cenario, resultado, criado, projeto) VALUES (?,?,?,?,?)",
                    (nome, json.dumps(cenario, ensure_ascii=False), json.dumps(r), datetime.now().isoformat(timespec="seconds"),
                     projeto)).lastrowid
    c.commit()
    eventos.emitir("task.completed", "oracle", {"cenario": cid, "nome": nome, "alternativas": len(r["resultados"])})
    return cid, r


def listar(limite=50):
    return [dict(r) | {"cenario": json.loads(r["cenario"]), "resultado": json.loads(r["resultado"])}
            for r in _con().execute("SELECT * FROM oracle_cenarios ORDER BY id DESC LIMIT ?", (limite,))]


def estruturar(descricao):
    """IA propõe o cenário a partir de um texto; volta para revisão (nada é simulado sem validar)."""
    from modulos import ia
    dados, quem = ia.gerar_json(
        "Monte um cenário de simulação em JSON a partir da descrição. Chaves: variaveis (lista de {nome em snake_case, "
        "origem: observado|estimado|hipotese, fonte (obrigatória se observado), e 'valor' OU distribuição "
        "{tipo: uniforme(min,max)|normal(media,desvio)|triangular(min,moda,max)}}), formulas (objeto nome->expressão "
        "com + - * / ** min max abs sqrt round e comparações), alternativas (objeto nome->{variavel: valor}), "
        "premissas (lista). Não invente dados observados: o que não foi informado é hipótese ou estimativa.\n\n"
        f"DESCRIÇÃO: {descricao}")
    dados["gerado_por"] = quem
    return dados


def relatorio(nome, cenario, r):
    fmt = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    obs = [v for v in cenario["variaveis"] if v.get("origem") == "observado"]
    hip = [v for v in cenario["variaveis"] if v.get("origem") != "observado"]
    desc = lambda v: (f"{v['valor']}" if "valor" in v else
                      f"{v.get('tipo')}({', '.join(str(v[k]) for k in ('min', 'moda', 'max', 'media', 'desvio') if k in v)})")
    linhas = [f"# Simulação: {nome}", "", "> Resultado de simulação (Monte Carlo, "
              f"{r['n']} rodadas, semente {r['semente']}): mostra o que ACONTECERIA SE as premissas valerem. Não é previsão.", "",
              "## Dados observados"] + ([f"- {v['nome']} = {desc(v)} (fonte: {v['fonte']})" for v in obs] or ["(nenhum)"]) + \
             ["", "## Hipóteses e estimativas"] + [f"- {v['nome']} = {desc(v)} ({v.get('origem')})" for v in hip] + \
             ["", "## Premissas"] + [f"- {p}" for p in cenario.get("premissas", [])] + ["", "## Resultados simulados"]
    for alt, res in r["resultados"].items():
        linhas.append(f"### {alt}")
        for f, s in res.items():
            linhas.append(f"- {f}: média {fmt(s['media'])} · P10 {fmt(s['p10'])} · P50 {fmt(s['p50'])} · P90 {fmt(s['p90'])}"
                          + (f" · {s['invalidos']} rodadas inválidas" if s["invalidos"] else ""))
    return "\n".join(linhas)
