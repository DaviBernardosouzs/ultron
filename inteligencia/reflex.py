"""REFLEX: aprendizado operacional baseado em evidências (não mexe em pesos de modelo).

1. operacoes(): reconstrói cada pedido pelo barramento (correlação): objetivo, intenção,
   modelo, ferramentas, falhas, duração e resultado.
2. aprender(): para cada falha de ferramenta, classifica (permissao, argumentos, rede,
   cota, indisponivel, recusa, outro), agrupa por assinatura (ferramenta + classe + erro
   normalizado) na memória de falhas, com hipótese e correção sugerida e os ids dos eventos
   como evidência.
   - Uma assinatura que se repete (>= 3) vira proposta na Evolution Forge, uma única vez.
   - Uma falha só é dada como resolvida quando há sucessos reais da ferramenta DEPOIS da
     última falha (evidência, não suposição).
   - Sequências de ferramentas que dão certo de forma repetida (>= 3 vezes, mesma intenção)
     viram proposta de macro (memória procedural), uma única vez.
3. avisos(ferramentas): uma linha para o contexto quando uma ferramenta oferecida tem falha
   recorrente em aberto, para o modelo não repetir o mesmo erro.
Recusas do Davi não são falha do sistema: viram só estatística.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from core import eventos

CLASSES = [
    ("permissao", re.compile(r"negad|guardian|workspace|bloquead", re.I),
     "a ferramenta está bloqueada por política ou WorkSpace", "revise a política/WorkSpace ou peça permissão (pedir_permissao)"),
    ("argumentos", re.compile(r"argumento|typeerror|required|inválid|invalid", re.I),
     "o modelo passou argumentos errados: descrição ou schema ambíguos", "melhorar a descrição/schema da ferramenta"),
    ("cota", re.compile(r"429|cota|quota|rate.?limit", re.I),
     "limite de uso do serviço", "esperar, trocar de modelo/serviço ou reduzir chamadas"),
    ("rede", re.compile(r"timeout|tempo esgotado|connection|conex|não respondeu|unreachable|desligad", re.I),
     "máquina ou serviço fora do ar", "conferir se a máquina/serviço está ligado antes de chamar"),
    ("indisponivel", re.compile(r"não existe|not found|indispon|no such|falta ", re.I),
     "recurso ou dependência ausente", "instalar/configurar o recurso ausente"),
]
MIN_RECORRENTE = 3


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS reflex_falhas (
            assinatura TEXT PRIMARY KEY, ferramenta TEXT, classe TEXT, erro TEXT, contagem INTEGER,
            primeira TEXT, ultima TEXT, hipotese TEXT, correcao TEXT, estado TEXT, evidencias TEXT,
            proposta TEXT, resolvida_em TEXT, evidencia_resolucao TEXT, ultima_seq INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reflex_procedimentos (
            assinatura TEXT PRIMARY KEY, intencao TEXT, sequencia TEXT, sucessos INTEGER, exemplos TEXT,
            proposta TEXT, ultima TEXT);
        CREATE TABLE IF NOT EXISTS reflex_estado (chave TEXT PRIMARY KEY, valor TEXT);""")
    return c


def classificar_falha(erro):
    for nome, rx, hip, cor in CLASSES:
        if rx.search(erro or ""):
            return nome, hip, cor
    return "outro", "erro não classificado", "investigar os logs da operação"


def _normalizar(erro):
    t = re.sub(r"\d+(\.\d+)?", "N", (erro or "")[:160].lower())
    return re.sub(r"['\"`].*?['\"`]", "X", t)


GENERICAS = {"usar_plugin": ("plugin", "ferramenta"), "usar_skill": ("nome",), "executar_macro": ("nome",)}


def alvo(ferramenta, args):
    """Ferramentas genéricas são identificadas pelo alvo (ex.: usar_plugin:playwright.ler_pagina)."""
    chaves = GENERICAS.get(ferramenta)
    if not chaves or not isinstance(args, dict):
        return ferramenta
    return ferramenta + ":" + ".".join(str(args.get(k, "?")) for k in chaves)


def _iniciados(desde, limite):
    return {e["id"]: e["dados"].get("args") for e in eventos.consultar(tipo="tool.started", desde=desde, limite=limite)}


def operacoes(desde=None, limite=4000):
    evs = list(reversed(eventos.consultar(desde=desde, limite=limite)))
    args_de = _iniciados(desde, limite)
    ops = defaultdict(lambda: {"ferramentas": [], "falhas": [], "inicio": None, "fim": None, "objetivo": None,
                               "resultado": None, "intencao": None, "modelo": None, "recusas": []})
    for e in evs:
        c = e["correlacao"]
        if not c:
            continue
        o = ops[c]
        d = e["dados"]
        o["inicio"] = o["inicio"] or e["quando"]
        o["fim"] = e["quando"]
        if e["tipo"] in ("task.started", "task.created") and not o["objetivo"]:
            o["objetivo"] = d.get("pedido") or d.get("objetivo") or d.get("macro")
        elif e["tipo"] == "tool.completed":
            o["ferramentas"].append(alvo(d.get("ferramenta"), args_de.get(e["pai"])))
        elif e["tipo"] == "tool.failed":
            o["falhas"].append({"ferramenta": alvo(d.get("ferramenta"), args_de.get(e["pai"])), "erro": d.get("erro") or d.get("motivo") or "", "evento": e["id"],
                                "quando": e["quando"], "seq": e["seq"]})
        elif e["tipo"] == "approval.denied" and e["origem"] == "usuario":
            o["recusas"].append(d.get("ferramenta"))
        elif e["tipo"] == "task.progress" and d.get("etapa") == "contexto":
            o["intencao"] = d.get("intencao")
        elif e["tipo"] == "task.progress" and d.get("etapa") == "modelo":
            o["modelo"] = d.get("modelo")
        elif e["tipo"] in ("task.completed", "task.failed"):
            o["resultado"] = "ok" if e["tipo"] == "task.completed" and not o["falhas"] else "falha"
    return dict(ops)


def aprender(desde=None):
    """Atualiza a memória de falhas e de procedimentos. Devolve um resumo do que mudou."""
    c = _con()
    if desde is None:
        r = c.execute("SELECT valor FROM reflex_estado WHERE chave='ultima_analise'").fetchone()
        desde = r[0] if r else (datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")
    ops = operacoes(desde)
    agora = datetime.now().isoformat(timespec="seconds")
    novas, propostas, resolvidas, procs = 0, [], [], []
    for o in ops.values():
        for f in o["falhas"]:
            classe, hip, cor = classificar_falha(f["erro"])
            ass = hashlib.sha1(f"{f['ferramenta']}|{classe}|{_normalizar(f['erro'])}".encode()).hexdigest()[:16]
            r = c.execute("SELECT contagem, evidencias, estado FROM reflex_falhas WHERE assinatura=?", (ass,)).fetchone()
            if r:
                ev = json.loads(r["evidencias"])[-9:] + [f["evento"]]
                c.execute("UPDATE reflex_falhas SET contagem=contagem+1, ultima=?, ultima_seq=?, evidencias=?, "
                          "estado=CASE WHEN estado='resolvida' THEN 'aberta' ELSE estado END WHERE assinatura=?",
                          (f["quando"], f["seq"], json.dumps(ev), ass))
            else:
                novas += 1
                c.execute("""INSERT INTO reflex_falhas(assinatura, ferramenta, classe, erro, contagem, primeira, ultima,
                             hipotese, correcao, estado, evidencias, ultima_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (ass, f["ferramenta"], classe, f["erro"][:300], 1, f["quando"], f["quando"], hip, cor, "aberta",
                           json.dumps([f["evento"]]), f["seq"]))
        # memória procedural: sequência que deu certo
        if o["resultado"] == "ok" and len(o["ferramentas"]) >= 2 and o["intencao"]:
            seq = [x for x in o["ferramentas"] if x and x != "buscar_ferramentas"]
            if len(seq) >= 2:
                ass = hashlib.sha1(f"{o['intencao']}|{'>'.join(seq)}".encode()).hexdigest()[:16]
                c.execute("""INSERT INTO reflex_procedimentos(assinatura, intencao, sequencia, sucessos, exemplos, ultima)
                             VALUES (?,?,?,1,?,?) ON CONFLICT(assinatura) DO UPDATE SET sucessos=sucessos+1,
                             exemplos=json_insert(exemplos, '$[#]', ?), ultima=?""",
                          (ass, o["intencao"], json.dumps(seq), json.dumps([o["objetivo"]]), o["fim"], o["objetivo"], o["fim"]))
    c.commit()
    # resolução por evidência: sucessos do MESMO alvo depois da última falha
    args_de = _iniciados(None, 5000)
    for r in c.execute("SELECT * FROM reflex_falhas WHERE estado IN ('aberta','proposta')").fetchall():
        depois = [e for e in eventos.consultar(tipo="tool.completed", apos=r["ultima_seq"] or 0, limite=500)
                  if alvo(e["dados"].get("ferramenta"), args_de.get(e["pai"])) == r["ferramenta"]]
        if len(depois) >= 2:
            c.execute("UPDATE reflex_falhas SET estado='resolvida', resolvida_em=?, evidencia_resolucao=? WHERE assinatura=?",
                      (agora, f"{len(depois)} sucessos depois da última falha ({depois[-1]['id']})", r["assinatura"]))
            resolvidas.append(r["ferramenta"])
    # recorrentes viram proposta (uma vez)
    for r in c.execute("SELECT * FROM reflex_falhas WHERE estado='aberta' AND contagem>=? AND proposta IS NULL",
                       (MIN_RECORRENTE,)).fetchall():
        if r["classe"] in ("permissao", "cota"):
            continue            # decisão do Davi ou limite externo: só aparece no painel
        try:
            from evolucao import descoberta
            nid = descoberta.registrar_necessidade(
                f"Falha recorrente em {r['ferramenta']} ({r['classe']}, {r['contagem']}x)",
                f"Reflex: {r['hipotese']}. Correção sugerida: {r['correcao']}. Erro: {r['erro'][:200]}. "
                f"Evidências: {r['evidencias']}")
        except Exception as e:
            nid = f"erro: {e}"
        c.execute("UPDATE reflex_falhas SET proposta=?, estado='proposta' WHERE assinatura=?", (str(nid), r["assinatura"]))
        propostas.append(r["ferramenta"])
    for r in c.execute("SELECT * FROM reflex_procedimentos WHERE sucessos>=? AND proposta IS NULL", (MIN_RECORRENTE,)).fetchall():
        seq = json.loads(r["sequencia"])
        try:
            from evolucao import descoberta
            nid = descoberta.registrar_necessidade(
                f"Virar macro: {' → '.join(seq)}",
                f"Reflex: a sequência deu certo {r['sucessos']}x para pedidos '{r['intencao']}'. Exemplos: {r['exemplos']}")
        except Exception as e:
            nid = f"erro: {e}"
        c.execute("UPDATE reflex_procedimentos SET proposta=? WHERE assinatura=?", (str(nid), r["assinatura"]))
        procs.append(" → ".join(seq))
    c.execute("INSERT OR REPLACE INTO reflex_estado VALUES ('ultima_analise', ?)", (agora,))
    c.commit()
    return {"operacoes": len(ops), "falhas_novas": novas, "propostas": propostas, "resolvidas": resolvidas,
            "procedimentos_propostos": procs}


def falhas(estado=None, limite=100):
    q = "SELECT * FROM reflex_falhas" + (" WHERE estado=?" if estado else "") + " ORDER BY ultima DESC LIMIT ?"
    return [dict(r) | {"evidencias": json.loads(r["evidencias"])} for r in _con().execute(q, ((estado, limite) if estado else (limite,)))]


def procedimentos(limite=50):
    return [dict(r) | {"sequencia": json.loads(r["sequencia"]), "exemplos": json.loads(r["exemplos"])}
            for r in _con().execute("SELECT * FROM reflex_procedimentos ORDER BY sucessos DESC LIMIT ?", (limite,))]


def avisos(nomes_ferramentas):
    """Linhas de contexto para ferramentas oferecidas que têm falha recorrente em aberto."""
    if not nomes_ferramentas:
        return ""
    marcas = ",".join("?" * len(nomes_ferramentas))
    linhas = [f"[Reflex: {r['ferramenta']} falhou {r['contagem']}x ({r['classe']}: {r['hipotese']}). {r['correcao'].capitalize()}.]"
              for r in _con().execute(f"""SELECT * FROM reflex_falhas WHERE estado IN ('aberta','proposta') AND contagem>=2
                                          AND (ferramenta IN ({marcas}) OR substr(ferramenta, 1, instr(ferramenta || ':', ':') - 1) IN ({marcas}))
                                          ORDER BY contagem DESC LIMIT 3""", list(nomes_ferramentas) * 2)]
    return "\n".join(linhas) + ("\n" if linhas else "")


def comparar_periodos(dias=7):
    """Taxa de sucesso das operações: últimos N dias × N dias anteriores (linha de base)."""
    agora = datetime.now()
    def taxa(ini, fim):
        ops = [o for o in operacoes(ini.isoformat(timespec="seconds")).values() if o["resultado"] and o["fim"] <= fim.isoformat()]
        ok = sum(o["resultado"] == "ok" for o in ops)
        return {"operacoes": len(ops), "sucesso": round(ok / len(ops), 3) if ops else None}
    return {"atual": taxa(agora - timedelta(days=dias), agora),
            "anterior": taxa(agora - timedelta(days=2 * dias), agora - timedelta(days=dias))}
