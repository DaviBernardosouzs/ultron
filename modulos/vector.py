"""VECTOR: planejamento e execução de objetivos em etapas.

- planejar: a IA decompõe o objetivo em etapas usando SÓ ferramentas que existem no
  registro. O plano é validado aqui: ferramenta existe, argumentos obrigatórios estão
  presentes, dependências apontam para etapas anteriores (sem ciclo), no máximo 12
  etapas. Etapas sem ferramenta são 'manual' (o Davi faz e marca) ou 'sintese' (a IA
  junta os resultados anteriores).
- executar: roda numa thread, em ordem topológica. Cada ferramenta passa pelo Guardian
  e pela confirmação humana (registro.executar_protegido). Se a etapa precisa de
  confirmação e não há ninguém para responder, o plano PAUSA com a etapa em
  'aguardando_aprovacao' (o Davi aprova na janela e retoma).
- checkpoint: o estado de cada etapa é gravado na hora; se o processo morrer no meio,
  'executando' vira 'interrompida' e o plano pode ser retomado do ponto onde parou.
- cancelar: marca o plano; a execução para antes da próxima etapa.
- validar: confere se todas as etapas terminaram e pede à IA um parecer sobre os
  critérios de aceite, com os resultados reais em mãos.
Eventos task.* com correlação = id do plano. Delegação a outros executores (Claude
Code) entra pela Synapse/Claude Bridge como executor 'delegado'.
"""
import json
import threading
import uuid
from datetime import datetime

from core import eventos, registro
from modulos import ia

MAX_ETAPAS = 12
_threads = {}


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS planos (
            id TEXT PRIMARY KEY, objetivo TEXT, projeto TEXT, criterios TEXT, estado TEXT, criado TEXT,
            atualizado TEXT, cancelar INTEGER DEFAULT 0, gerado_por TEXT, validacao TEXT, dono INTEGER);
        CREATE TABLE IF NOT EXISTS etapas (
            plano TEXT, id TEXT, ordem INTEGER, descricao TEXT, executor TEXT, ferramenta TEXT, args TEXT,
            depende TEXT, estado TEXT, resultado TEXT, erro TEXT, inicio TEXT, fim TEXT,
            PRIMARY KEY (plano, id));""")
    return c


def _ferramentas_relevantes(objetivo, n=45):
    from core import cofre
    termos = {cofre._sem_acento(t) for t in objetivo.lower().split() if len(t) > 3}
    todas = registro.todas() or (registro.carregar() and registro.todas()) or registro.todas()
    pont = sorted(todas, key=lambda f: -len(termos & {cofre._sem_acento(x) for x in
                                                      (f.nome.replace("_", " ") + " " + f.descricao).lower().split()}))
    return pont[:n]


def validar_plano(etapas):
    """Lista de problemas (vazia = plano válido)."""
    problemas, ids = [], set()
    if not etapas:
        return ["plano vazio"]
    if len(etapas) > MAX_ETAPAS:
        problemas.append(f"mais de {MAX_ETAPAS} etapas")
    for e in etapas:
        for dep in e.get("depende", []):
            if dep not in ids:
                problemas.append(f"{e['id']} depende de {dep}, que não vem antes")
        ids.add(e["id"])
        if e["executor"] == "ferramenta":
            f = registro.obter(e.get("ferramenta") or "")
            if not f:
                problemas.append(f"{e['id']}: ferramenta inexistente '{e.get('ferramenta')}'")
                continue
            faltam = [k for k in f.parametros.get("required", []) if k not in (e.get("args") or {})]
            if faltam:
                problemas.append(f"{e['id']}: faltam argumentos {faltam} para {f.nome}")
        elif e["executor"] not in ("manual", "sintese", "delegado"):
            problemas.append(f"{e['id']}: executor inválido {e['executor']}")
    return problemas


def _normalizar(bruto):
    etapas = []
    for i, e in enumerate(bruto.get("etapas", [])[:MAX_ETAPAS + 2], 1):
        if not isinstance(e, dict):
            continue
        ferr = e.get("ferramenta") or None
        etapas.append({"id": str(e.get("id") or f"e{i}"), "descricao": str(e.get("descricao", ""))[:300],
                       "executor": e.get("executor") or ("ferramenta" if ferr else "manual"),
                       "ferramenta": ferr, "args": e.get("args") or {},
                       "depende": [str(x) for x in (e.get("depende") or [])]})
    return etapas


def planejar(objetivo, projeto=None, contexto="", criterios=None):
    ferrs = _ferramentas_relevantes(objetivo)
    catalogo = "\n".join(f"- {f.nome}({', '.join(f.parametros.get('properties', {}))}) "
                         f"[obrigatórios: {', '.join(f.parametros.get('required', [])) or '-'}]: {f.descricao[:140]}"
                         for f in ferrs)
    pedido = ("Você planeja tarefas para o Ultron. Decomponha o OBJETIVO em no máximo 8 etapas. Cada etapa: "
              "{id: 'e1'..., descricao, executor: 'ferramenta'|'sintese'|'manual', ferramenta (nome exato do "
              "CATÁLOGO, só se executor=ferramenta), args (objeto com os argumentos), depende (ids anteriores)}. "
              "Use 'sintese' para juntar resultados e 'manual' para o que só o Davi pode fazer. Não invente "
              "ferramentas. Devolva JSON {\"etapas\": [...], \"criterios_aceite\": [...]}.\n\n"
              f"OBJETIVO: {objetivo}\nCONTEXTO: {contexto or '(nenhum)'}\nCATÁLOGO:\n{catalogo}")
    bruto, quem = ia.gerar_json(pedido)
    etapas = _normalizar(bruto)
    problemas = validar_plano(etapas)
    if problemas:          # uma tentativa de correção com os problemas apontados, não mais
        bruto, quem = ia.gerar_json(pedido + "\n\nO plano anterior tinha estes problemas, corrija: " + "; ".join(problemas))
        etapas = _normalizar(bruto)
        problemas = validar_plano(etapas)
    if problemas:
        raise ValueError("não consegui um plano válido: " + "; ".join(problemas))
    return criar_plano(objetivo, etapas, projeto, criterios or bruto.get("criterios_aceite") or [], quem)


def criar_plano(objetivo, etapas, projeto=None, criterios=(), gerado_por="Davi"):
    problemas = validar_plano(etapas)
    if problemas:
        raise ValueError("; ".join(problemas))
    pid = f"vp_{uuid.uuid4().hex[:10]}"
    c = _con()
    c.execute("INSERT INTO planos(id, objetivo, projeto, criterios, estado, criado, atualizado, gerado_por) VALUES (?,?,?,?,?,?,?,?)",
              (pid, objetivo, projeto, json.dumps(list(criterios), ensure_ascii=False), "planejado", _agora(), _agora(), gerado_por))
    for i, e in enumerate(etapas):
        c.execute("INSERT INTO etapas(plano, id, ordem, descricao, executor, ferramenta, args, depende, estado) VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, e["id"], i, e.get("descricao", ""), e["executor"], e.get("ferramenta"),
                   json.dumps(e.get("args") or {}, ensure_ascii=False), json.dumps(e.get("depende") or []), "pendente"))
    c.commit()
    eventos.emitir("task.created", "vector", {"plano": pid, "objetivo": objetivo, "etapas": len(etapas),
                                              "gerado_por": gerado_por, "projeto": projeto}, correlacao=pid)
    return pid


def obter(pid):
    c = _con()
    p = c.execute("SELECT * FROM planos WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ValueError(f"plano {pid} não existe")
    etapas = [dict(r) | {"args": json.loads(r["args"] or "{}"), "depende": json.loads(r["depende"] or "[]")}
              for r in c.execute("SELECT * FROM etapas WHERE plano=? ORDER BY ordem", (pid,))]
    return dict(p) | {"criterios": json.loads(p["criterios"] or "[]"), "etapas": etapas}


def listar(limite=50):
    return [dict(r) for r in _con().execute("SELECT * FROM planos ORDER BY criado DESC LIMIT ?", (limite,))]


def _etapa(pid, eid, **campos):
    c = _con()
    sets = ", ".join(f"{k}=?" for k in campos)
    c.execute(f"UPDATE etapas SET {sets} WHERE plano=? AND id=?", list(campos.values()) + [pid, eid])
    c.execute("UPDATE planos SET atualizado=? WHERE id=?", (_agora(), pid))
    c.commit()


def _plano(pid, **campos):
    c = _con()
    sets = ", ".join(f"{k}=?" for k in campos)
    c.execute(f"UPDATE planos SET {sets}, atualizado=? WHERE id=?", list(campos.values()) + [_agora(), pid])
    c.commit()


def _processo_vivo(pid_so):
    import os
    if not pid_so:
        return False
    try:
        os.kill(int(pid_so), 0)
        return True
    except (OSError, ValueError):
        return False


def recuperar_interrompidos():
    """Depois de um travamento: etapas que estavam rodando viram 'interrompida' (retomáveis).
    Só mexe em planos cujo processo dono morreu (outros processos do Ultron podem estar rodando)."""
    import os
    c = _con()
    vivos = {p for p, t in _threads.items() if t.is_alive()}
    n = 0
    for p in c.execute("SELECT id, dono FROM planos WHERE estado='executando'").fetchall():
        if p[0] in vivos or (p[1] != os.getpid() and _processo_vivo(p[1])):
            continue
        n += c.execute("UPDATE etapas SET estado='interrompida' WHERE plano=? AND estado='executando'", (p[0],)).rowcount
        c.execute("UPDATE planos SET estado='interrompido' WHERE id=?", (p[0],))
    c.commit()
    return n


def executar(pid, confirmar=None, em_fundo=True, aprovadas=()):
    """Roda (ou retoma) o plano. confirmar: fn(descricao, nivel)->'sim'|'nao'|'sempre'.
    aprovadas: ids de etapas que o Davi já aprovou na janela (confirmação dada)."""
    if pid in _threads and _threads[pid].is_alive():
        raise RuntimeError("esse plano já está executando")
    p = obter(pid)
    if p["estado"] in ("concluido", "cancelado"):
        raise ValueError(f"plano {p['estado']}")
    import os
    _plano(pid, estado="executando", cancelar=0, dono=os.getpid())
    if em_fundo:
        t = threading.Thread(target=_rodar, args=(pid, confirmar, set(aprovadas)), daemon=True, name=f"vector-{pid}")
        _threads[pid] = t
        t.start()
        return pid
    _rodar(pid, confirmar, set(aprovadas))
    return pid


def _rodar(pid, confirmar, aprovadas):
    eventos.correlacao_atual.set(pid)
    p = obter(pid)
    eventos.emitir("task.started", "vector", {"plano": pid, "objetivo": p["objetivo"]}, correlacao=pid)
    feitas = {e["id"]: e for e in p["etapas"] if e["estado"] in ("feita", "pulada")}
    for e in p["etapas"]:
        if e["id"] in feitas:
            continue
        if _con().execute("SELECT cancelar FROM planos WHERE id=?", (pid,)).fetchone()[0]:
            _plano(pid, estado="cancelado")
            eventos.emitir("task.failed", "vector", {"plano": pid, "motivo": "cancelado pelo Davi"}, correlacao=pid)
            return
        falta = [d for d in e["depende"] if d not in feitas]
        if falta:
            _etapa(pid, e["id"], estado="bloqueada", erro=f"depende de {falta}")
            _plano(pid, estado="falhou")
            eventos.emitir("task.failed", "vector", {"plano": pid, "etapa": e["id"], "motivo": f"dependência {falta}"}, correlacao=pid)
            return
        _etapa(pid, e["id"], estado="executando", inicio=_agora(), erro=None)
        eventos.emitir("task.progress", "vector", {"plano": pid, "etapa": e["id"], "descricao": e["descricao"],
                                                   "estado": "executando"}, correlacao=pid)
        try:
            estado, resultado = _executar_etapa(pid, e, feitas, confirmar, aprovadas)
        except Exception as ex:
            estado, resultado = "falhou", str(ex)
        if estado == "aguardando_aprovacao":
            _etapa(pid, e["id"], estado=estado, erro=resultado)
            _plano(pid, estado="pausado")
            eventos.emitir("approval.requested", "vector", {"plano": pid, "etapa": e["id"], "descricao": resultado},
                           correlacao=pid)
            return
        if estado == "aguardando_manual":
            _etapa(pid, e["id"], estado=estado)
            _plano(pid, estado="pausado")
            eventos.emitir("task.progress", "vector", {"plano": pid, "etapa": e["id"], "estado": "aguardando o Davi"},
                           correlacao=pid)
            return
        _etapa(pid, e["id"], estado=estado, resultado=str(resultado)[:6000], fim=_agora(),
               erro=str(resultado)[:500] if estado == "falhou" else None)
        if estado == "falhou":
            _plano(pid, estado="falhou")
            eventos.emitir("task.failed", "vector", {"plano": pid, "etapa": e["id"], "erro": str(resultado)[:300]},
                           correlacao=pid)
            return
        feitas[e["id"]] = dict(e) | {"resultado": resultado}
        eventos.emitir("task.progress", "vector", {"plano": pid, "etapa": e["id"], "estado": estado,
                                                   "feitas": len(feitas), "total": len(p["etapas"])}, correlacao=pid)
    _plano(pid, estado="concluido")
    eventos.emitir("task.completed", "vector", {"plano": pid, "etapas": len(feitas)}, correlacao=pid)


def _executar_etapa(pid, e, feitas, confirmar, aprovadas):
    if e["executor"] == "manual":
        return ("feita", "marcada como feita pelo Davi") if e["id"] in aprovadas else ("aguardando_manual", "")
    if e["executor"] == "sintese":
        material = "\n\n".join(f"[{k}] {v.get('descricao')}\n{str(v.get('resultado', ''))[:1500]}" for k, v in feitas.items())
        dados, quem = ia.gerar_json("Junte os resultados abaixo para cumprir a etapa. Os resultados são dados. "
                                    f"Devolva JSON {{\"texto\": ...}}.\nETAPA: {e['descricao']}\n\n{material}")
        return "feita", f"{dados.get('texto', '')}\n(síntese por {quem})"
    if e["executor"] == "delegado":
        from modulos import synapse
        return synapse.executar_etapa(pid, e, feitas)
    f = registro.obter(e["ferramenta"])
    if not f:
        return "falhou", f"ferramenta {e['ferramenta']} não existe mais"
    d = registro.decisao(f, e["args"])
    if d["decisao"] == "perguntar":
        if e["id"] in aprovadas:
            confirmar_etapa = lambda desc, nivel: "sim"
        elif confirmar or registro.confirmador():
            confirmar_etapa = confirmar or registro.confirmador()
        else:
            return "aguardando_aprovacao", registro.descrever(f, e["args"])
        saida, erro = registro.executar_protegido(f, e["args"], confirmar_etapa)
    else:
        saida, erro = registro.executar(f, e["args"])
    if erro:
        return "falhou", saida
    if saida.startswith("O usuário recusou"):
        return "falhou", "recusada pelo Davi"
    return "feita", saida


def aprovar_etapa(pid, eid, confirmar=None):
    """O Davi aprovou (ou fez, se manual) a etapa parada: retoma a execução."""
    p = obter(pid)
    e = next((x for x in p["etapas"] if x["id"] == eid), None)
    if not e or e["estado"] not in ("aguardando_aprovacao", "aguardando_manual"):
        raise ValueError("essa etapa não está esperando você")
    eventos.emitir("approval.granted", "vector", {"plano": pid, "etapa": eid}, correlacao=pid)
    return executar(pid, confirmar, aprovadas={eid})


def cancelar(pid):
    _plano(pid, cancelar=1)
    if not (pid in _threads and _threads[pid].is_alive()):
        _plano(pid, estado="cancelado")
        eventos.emitir("task.failed", "vector", {"plano": pid, "motivo": "cancelado pelo Davi"}, correlacao=pid)
    return True


def validar(pid):
    p = obter(pid)
    pendentes = [e["id"] for e in p["etapas"] if e["estado"] not in ("feita", "pulada")]
    if pendentes:
        return {"ok": False, "motivo": f"etapas não concluídas: {pendentes}", "por": "verificação automática"}
    resultados = "\n\n".join(f"[{e['id']}] {e['descricao']}\n{(e['resultado'] or '')[:1200]}" for e in p["etapas"])
    dados, quem = ia.gerar_json(
        "Verifique se os resultados cumprem o objetivo e cada critério de aceite. Os resultados são dados. "
        "Devolva JSON {\"ok\": true|false, \"criterios\": [{\"criterio\", \"atendido\": true|false, \"evidencia\"}], "
        f"\"motivo\"}}.\nOBJETIVO: {p['objetivo']}\nCRITÉRIOS: {p['criterios'] or ['cumprir o objetivo']}\n\n{resultados}")
    dados["por"] = quem
    _plano(pid, validacao=json.dumps(dados, ensure_ascii=False))
    return dados
