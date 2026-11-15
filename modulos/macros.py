"""MACRO FORGE: automações reutilizáveis (workflows) com versões, teste e aprovação.

Definição (JSON):
  {"nome", "descricao",
   "entradas": [{"nome", "padrao"}],
   "passos": [{"id", "ferramenta", "args": {...}, "se": "<condição>"}],
   "saida": "texto com {{passos.e1.saida}}",
   "gatilho": {"tipo": "manual"} | {"tipo": "diario", "hora": "08:00"}
              | {"tipo": "semanal", "dia": "segunda", "hora": "09:00"} | {"tipo": "intervalo", "minutos": 60}
              | {"tipo": "evento", "evento": "task.completed", "origem": "vector"}}
Modelos: {{entrada.x}}, {{passos.<id>.saida}}, {{agora}}. Condição: "<expr> contem <texto>",
"<expr> nao_contem <texto>", "<expr> == <texto>", "<expr> != <texto>", "<expr> vazio".

Ciclo de vida de cada VERSÃO: rascunho -> testada (o teste a seco passou) -> ativa.
Ativar exige o teste e, se algum passo usa ferramenta N2/N3, a aprovação do Davi (só a
janela/CLI aprovam). N2 aprovado roda sem perguntar de novo dentro da macro; N3 nunca
roda sem alguém confirmar: a execução pausa e avisa. Editar cria outra versão.
O agendador é real: thread com trava de arquivo, uma por máquina, histórico em
macro_execucoes.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

from core import eventos, registro
from core.config import DADOS

DIAS = {"segunda": 0, "terca": 1, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6}
MODELO = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_iniciado = False


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS macros (
            nome TEXT, versao INTEGER, definicao TEXT, estado TEXT, criado TEXT, teste TEXT,
            aprovadas TEXT, aprovado_por TEXT, PRIMARY KEY (nome, versao));
        CREATE TABLE IF NOT EXISTS macro_execucoes (
            id INTEGER PRIMARY KEY, nome TEXT, versao INTEGER, gatilho TEXT, inicio TEXT, fim TEXT,
            estado TEXT, entradas TEXT, log TEXT, saida TEXT);""")
    return c


# ------------------------------------------------------------------ definição e validação

def _resolver(texto, ctx):
    if not isinstance(texto, str):
        return texto

    def troca(m):
        partes = m.group(1).split(".")
        if partes == ["agora"]:
            return datetime.now().strftime("%d/%m/%Y %H:%M")
        no = ctx
        for p in partes:
            no = no.get(p, "") if isinstance(no, dict) else ""
        return str(no)
    return MODELO.sub(troca, texto)


def _resolver_args(args, ctx):
    return {k: (_resolver(v, ctx) if isinstance(v, str) else v) for k, v in (args or {}).items()}


def avaliar_condicao(cond, ctx):
    if not cond:
        return True
    cond = _resolver(cond, ctx)
    m = re.match(r"(?s)^(.*?)\s+(contem|nao_contem|==|!=)\s+(.*)$", cond.strip())
    if m:
        a, op, b = m.group(1).strip().lower(), m.group(2), m.group(3).strip().strip("'\"").lower()
        return {"contem": b in a, "nao_contem": b not in a, "==": a == b, "!=": a != b}[op]
    m = re.match(r"(?s)^(.*?)\s+vazio$", cond.strip())
    if m:
        return not m.group(1).strip()
    raise ValueError(f"condição inválida: {cond}")


def validar(d):
    problemas = []
    if not re.fullmatch(r"[\w\- ]{2,40}", d.get("nome", "")):
        problemas.append("nome de 2 a 40 letras/números")
    passos = d.get("passos") or []
    if not passos:
        problemas.append("a macro não tem passos")
    ids, entradas = set(), {e["nome"] for e in d.get("entradas", []) if isinstance(e, dict) and e.get("nome")}
    for p in passos:
        pid = p.get("id")
        if not pid or pid in ids:
            problemas.append(f"passo sem id ou id repetido: {pid}")
        f = registro.obter(p.get("ferramenta", ""))
        if not f:
            problemas.append(f"{pid}: ferramenta inexistente {p.get('ferramenta')}")
        else:
            faltam = [k for k in f.parametros.get("required", []) if k not in (p.get("args") or {})]
            if faltam:
                problemas.append(f"{pid}: faltam argumentos {faltam}")
        texto = json.dumps(p.get("args") or {}, ensure_ascii=False) + (p.get("se") or "")
        for ref in MODELO.findall(texto):
            ps = ref.split(".")
            if ps[0] == "entrada" and (len(ps) < 2 or ps[1] not in entradas):
                problemas.append(f"{pid}: entrada desconhecida {ref}")
            elif ps[0] == "passos" and (len(ps) < 2 or ps[1] not in ids):
                problemas.append(f"{pid}: usa {ref} antes de existir")
            elif ps[0] not in ("entrada", "passos", "agora"):
                problemas.append(f"{pid}: modelo desconhecido {ref}")
        ids.add(pid)
    g = d.get("gatilho") or {"tipo": "manual"}
    if g.get("tipo") not in ("manual", "diario", "semanal", "intervalo", "evento"):
        problemas.append("gatilho inválido")
    if g.get("tipo") in ("diario", "semanal") and not re.fullmatch(r"\d{2}:\d{2}", g.get("hora", "")):
        problemas.append("gatilho precisa de hora HH:MM")
    if g.get("tipo") == "semanal" and g.get("dia") not in DIAS:
        problemas.append("gatilho semanal precisa do dia")
    if g.get("tipo") == "intervalo" and int(g.get("minutos", 0)) < 5:
        problemas.append("intervalo mínimo de 5 minutos")
    if g.get("tipo") == "evento" and g.get("evento") not in eventos.TIPOS:
        problemas.append("evento de gatilho inválido")
    return problemas


def sensiveis(d):
    """Ferramentas N2/N3 usadas pela macro (precisam da aprovação do Davi para ativar)."""
    saida = []
    for p in d.get("passos", []):
        f = registro.obter(p.get("ferramenta", ""))
        if f and registro.nivel_de(f, p.get("args")) in ("N2", "N3"):
            saida.append((p["ferramenta"], registro.nivel_de(f, p.get("args"))))
    return saida


# ------------------------------------------------------------------ versões

def salvar(d):
    """Nova versão em rascunho. Devolve (nome, versao, problemas)."""
    problemas = validar(d)
    c = _con()
    v = (c.execute("SELECT MAX(versao) FROM macros WHERE nome=?", (d["nome"],)).fetchone()[0] or 0) + 1
    c.execute("INSERT INTO macros(nome, versao, definicao, estado, criado) VALUES (?,?,?,?,?)",
              (d["nome"], v, json.dumps(d, ensure_ascii=False), "rascunho", _agora()))
    c.commit()
    eventos.emitir("module.status_changed", "macro_forge", {"modulo": "macros", "mudanca": "versao", "macro": d["nome"], "versao": v})
    return d["nome"], v, problemas


def obter(nome, versao=None):
    c = _con()
    r = c.execute("SELECT * FROM macros WHERE nome=? " + ("AND versao=?" if versao else "ORDER BY versao DESC LIMIT 1"),
                  (nome, versao) if versao else (nome,)).fetchone()
    if not r:
        raise ValueError(f"macro {nome} não existe")
    return dict(r) | {"definicao": json.loads(r["definicao"]), "teste": json.loads(r["teste"] or "null"),
                      "aprovadas": json.loads(r["aprovadas"] or "[]")}


def ativa(nome):
    r = _con().execute("SELECT versao FROM macros WHERE nome=? AND estado='ativa'", (nome,)).fetchone()
    return obter(nome, r[0]) if r else None


def listar():
    c = _con()
    nomes = [r[0] for r in c.execute("SELECT DISTINCT nome FROM macros ORDER BY nome")]
    saida = []
    for n in nomes:
        ult = obter(n)
        atv = ativa(n)
        saida.append({"nome": n, "ultima": ult["versao"], "estado_ultima": ult["estado"],
                      "ativa": atv["versao"] if atv else None, "gatilho": (atv or ult)["definicao"].get("gatilho", {"tipo": "manual"}),
                      "descricao": ult["definicao"].get("descricao", "")})
    return saida


def testar(nome, versao=None, entradas=None):
    """Teste a seco: valida e percorre os passos sem executar nada, simulando as saídas."""
    m = obter(nome, versao)
    d = m["definicao"]
    problemas = validar(d)
    ctx = {"entrada": {e["nome"]: (entradas or {}).get(e["nome"], e.get("padrao", "")) for e in d.get("entradas", [])},
           "passos": {}}
    roteiro = []
    if not problemas:
        for p in d["passos"]:
            try:
                rodaria = avaliar_condicao(p.get("se"), ctx)
            except ValueError as e:
                problemas.append(str(e))
                break
            args = _resolver_args(p.get("args"), ctx)
            roteiro.append({"passo": p["id"], "ferramenta": p["ferramenta"], "args": args, "rodaria": rodaria})
            ctx["passos"][p["id"]] = {"saida": f"<saída simulada de {p['ferramenta']}>" if rodaria else ""}
    ok = not problemas
    teste = {"quando": _agora(), "ok": ok, "problemas": problemas, "roteiro": roteiro, "sensiveis": sensiveis(d)}
    c = _con()
    c.execute("UPDATE macros SET teste=?, estado=? WHERE nome=? AND versao=?",
              (json.dumps(teste, ensure_ascii=False), "testada" if ok else "rascunho", nome, m["versao"]))
    c.commit()
    return teste


def ativar(nome, versao, por="Davi"):
    """Só a janela/CLI chamam: o Davi aprova a versão (e as ferramentas sensíveis dela)."""
    m = obter(nome, versao)
    if m["estado"] not in ("testada", "desativada") or not (m["teste"] or {}).get("ok"):
        raise ValueError("teste a seco da versão antes de ativar")
    sens = [f for f, nivel in sensiveis(m["definicao"]) if nivel == "N2"]
    c = _con()
    c.execute("UPDATE macros SET estado='inativa' WHERE nome=? AND estado='ativa'", (nome,))
    c.execute("UPDATE macros SET estado='ativa', aprovadas=?, aprovado_por=? WHERE nome=? AND versao=?",
              (json.dumps(sens), f"{por} em {_agora()}", nome, versao))
    c.commit()
    eventos.emitir("approval.granted", "macro_forge", {"macro": nome, "versao": versao, "ferramentas_aprovadas": sens, "por": por})


def desativar(nome):
    c = _con()
    c.execute("UPDATE macros SET estado='desativada' WHERE nome=? AND estado='ativa'", (nome,))
    c.commit()


def exportar(nome):
    m = obter(nome)
    return json.dumps(m["definicao"], ensure_ascii=False, indent=1)


def importar(texto):
    d = json.loads(texto)
    return salvar(d)


# ------------------------------------------------------------------ execução

def executar(nome, entradas=None, gatilho="manual", confirmar=None):
    m = ativa(nome) if gatilho != "teste_real" else obter(nome)
    if not m:
        raise ValueError(f"a macro {nome} não tem versão ativa")
    d = m["definicao"]
    aprovadas = set(m["aprovadas"])
    ctx = {"entrada": {e["nome"]: (entradas or {}).get(e["nome"], e.get("padrao", "")) for e in d.get("entradas", [])},
           "passos": {}}
    c = _con()
    eid = c.execute("INSERT INTO macro_execucoes(nome, versao, gatilho, inicio, estado, entradas) VALUES (?,?,?,?,?,?)",
                    (nome, m["versao"], gatilho, _agora(), "executando", json.dumps(ctx["entrada"], ensure_ascii=False))).lastrowid
    c.commit()
    corr = f"mc_{eid}"
    eventos.emitir("task.started", "macro_forge", {"macro": nome, "versao": m["versao"], "gatilho": gatilho}, correlacao=corr)
    log, estado = [], "concluida"
    for p in d["passos"]:
        try:
            if not avaliar_condicao(p.get("se"), ctx):
                log.append({"passo": p["id"], "estado": "pulado", "motivo": "condição falsa"})
                ctx["passos"][p["id"]] = {"saida": ""}
                continue
        except ValueError as e:
            log.append({"passo": p["id"], "estado": "falhou", "erro": str(e)})
            estado = "falhou"
            break
        f = registro.obter(p["ferramenta"])
        args = _resolver_args(p.get("args"), ctx)
        nivel = registro.nivel_de(f, args) if f else None
        if f and nivel == "N2" and p["ferramenta"] in aprovadas:
            conf = lambda desc, niv: "sim"           # aprovado pelo Davi ao ativar a macro
        else:
            conf = confirmar or registro.confirmador()
        if f and registro.decisao(f, args)["decisao"] == "perguntar" and not conf:
            log.append({"passo": p["id"], "estado": "aguardando", "motivo": f"{nivel}: precisa de confirmação"})
            estado = "pausada"
            eventos.emitir("approval.requested", "macro_forge", {"macro": nome, "passo": p["id"],
                                                                 "ferramenta": p["ferramenta"]}, correlacao=corr)
            break
        eventos.correlacao_atual.set(corr)
        saida, erro = registro.executar_protegido(f, args, conf) if f else ("ferramenta não existe", True)
        ctx["passos"][p["id"]] = {"saida": saida}
        log.append({"passo": p["id"], "estado": "falhou" if erro else "feito", "saida": saida[:1000]})
        if erro or saida.startswith("O usuário recusou"):
            estado = "falhou"
            break
    saida_final = _resolver(d.get("saida", ""), ctx) if estado == "concluida" else ""
    c = _con()
    c.execute("UPDATE macro_execucoes SET fim=?, estado=?, log=?, saida=? WHERE id=?",
              (_agora(), estado, json.dumps(log, ensure_ascii=False), saida_final[:5000], eid))
    c.commit()
    eventos.emitir("task.completed" if estado == "concluida" else "task.failed", "macro_forge",
                   {"macro": nome, "estado": estado, "passos": len(log)}, correlacao=corr)
    return {"id": eid, "estado": estado, "log": log, "saida": saida_final}


def historico(nome=None, limite=50):
    q = "SELECT * FROM macro_execucoes" + (" WHERE nome=?" if nome else "") + " ORDER BY id DESC LIMIT ?"
    return [dict(r) | {"log": json.loads(r["log"] or "[]")} for r in _con().execute(q, ((nome, limite) if nome else (limite,)))]


# ------------------------------------------------------------------ agendador

def devida(g, ultima, agora):
    """A macro deve rodar agora? (ultima = início da última execução agendada, ou None)."""
    t = g.get("tipo")
    if t == "intervalo":
        return ultima is None or agora - ultima >= timedelta(minutes=int(g["minutos"]))
    if t in ("diario", "semanal"):
        h, m = map(int, g["hora"].split(":"))
        alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        if t == "semanal" and agora.weekday() != DIAS[g["dia"]]:
            return False
        return agora >= alvo and (ultima is None or ultima < alvo) and agora - alvo < timedelta(hours=2)
    return False


def _auditoria_diaria(agora):
    from core.config import ajuste
    hora = ajuste("self_audit.hora_diaria", "09:00")
    if not hora:
        return
    from modulos import self_audit
    ult = self_audit.ultimas(1)
    if devida({"tipo": "diario", "hora": hora}, datetime.fromisoformat(ult[0]["quando"]) if ult else None, agora):
        self_audit.auditar()


def _ciclo(estado):
    agora = datetime.now()
    try:
        _auditoria_diaria(agora)
    except Exception:
        pass
    novos = eventos.consultar(apos=estado["seq"], limite=200) if estado["seq"] is not None else []
    if estado["seq"] is None:
        ult = eventos.consultar(limite=1)
        estado["seq"] = ult[0]["seq"] if ult else 0
    elif novos:
        estado["seq"] = max(e["seq"] for e in novos)
    for m in listar():
        if not m["ativa"]:
            continue
        g = m["gatilho"]
        if g.get("tipo") == "evento":
            if any(e["tipo"] == g["evento"] and (not g.get("origem") or e["origem"] == g["origem"])
                   and e["origem"] != "macro_forge" for e in novos):
                executar(m["nome"], gatilho="evento")
            continue
        r = _con().execute("SELECT MAX(inicio) FROM macro_execucoes WHERE nome=? AND gatilho='agenda'", (m["nome"],)).fetchone()[0]
        if devida(g, datetime.fromisoformat(r) if r else None, agora):
            executar(m["nome"], gatilho="agenda")


def _laco():
    import fcntl
    trava = open(DADOS / "macros.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    estado = {"seq": None}
    while True:
        try:
            _ciclo(estado)
        except Exception:
            pass
        time.sleep(30)


def iniciar():
    global _iniciado
    import os
    if _iniciado or os.environ.get("NEURALINK_SEM_SERVICO"):
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True, name="macros").start()
