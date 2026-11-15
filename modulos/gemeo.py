"""DIGITAL TWIN: representação do ambiente digital autorizado, a partir de fontes configuradas.

Fontes (nada de varrer a rede):
  maquinas    hosts: do config.yaml (notebook, desktop) com carga real
  docker      containers do Docker local (estado, saúde, reinícios, projeto Compose, portas,
              dependências declaradas em com.docker.compose.depends_on, CPU/RAM)
  servicos    serviços systemd --user do Ultron e endpoints HTTP listados em gemeo.endpoints
  ultron      Ollama do desktop, Claude Code, sandbox
Cada leitura vira um 'retrato'; mudanças de estado ficam no histórico e quedas viram
incidentes ligados ao componente (Guardian). Dependências: Compose depends_on, container ->
máquina, serviço -> máquina. Também mostra a causa provável: componente fora do ar cujo
dependente também falha.
"""
import json
import socket
import subprocess
from datetime import datetime

import requests

from core import eventos, guardian
from core.config import ajuste

OK, ATENCAO, FORA = "ok", "atencao", "fora"


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS gemeo_componentes (id TEXT PRIMARY KEY, tipo TEXT, nome TEXT, estado TEXT,
            detalhe TEXT, metricas TEXT, atualizado TEXT);
        CREATE TABLE IF NOT EXISTS gemeo_dependencias (origem TEXT, destino TEXT, tipo TEXT, PRIMARY KEY (origem, destino));
        CREATE TABLE IF NOT EXISTS gemeo_historico (id INTEGER PRIMARY KEY, componente TEXT, quando TEXT, de TEXT, para TEXT, detalhe TEXT);""")
    return c


def _docker():
    comps, deps = [], []
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True, timeout=20)
    except Exception as e:
        return [{"id": "docker", "tipo": "servico", "nome": "Docker", "estado": FORA, "detalhe": str(e), "metricas": {}}], []
    if r.returncode:
        return [{"id": "docker", "tipo": "servico", "nome": "Docker", "estado": FORA, "detalhe": r.stderr[:200], "metricas": {}}], []
    linhas = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    stats = {}
    try:
        s = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30)
        for l in s.stdout.splitlines():
            d = json.loads(l)
            stats[d["Name"]] = {"cpu": d.get("CPUPerc"), "ram": d.get("MemUsage")}
    except Exception:
        pass
    nomes = {x["Names"] for x in linhas}
    for x in linhas:
        nome = x["Names"]
        insp = subprocess.run(["docker", "inspect", "--format",
                               "{{.RestartCount}}|{{.State.ExitCode}}|{{index .Config.Labels \"com.docker.compose.project\"}}|"
                               "{{index .Config.Labels \"com.docker.compose.service\"}}|{{index .Config.Labels \"com.docker.compose.depends_on\"}}",
                               nome], capture_output=True, text=True, timeout=10).stdout.strip().split("|")
        reinicios, codigo, projeto, servico, dependeu = (insp + [""] * 5)[:5]
        status = x.get("Status", "")
        if "Restarting" in status or "unhealthy" in status:
            estado = FORA
        elif x.get("State") == "running":
            estado = ATENCAO if "health: starting" in status or (reinicios.isdigit() and int(reinicios) > 5) else OK
        else:
            estado = "parado"
        comps.append({"id": f"docker:{nome}", "tipo": "container", "nome": nome, "estado": estado,
                      "detalhe": f"{status} · projeto {projeto or '—'} · reinícios {reinicios} · saída {codigo}",
                      "metricas": stats.get(nome, {}) | {"portas": x.get("Ports", "")}})
        deps.append((f"docker:{nome}", "maquina:notebook", "roda_em"))
        for dep in filter(None, dependeu.split(",")):
            alvo_serv = dep.split(":")[0]
            alvo = next((n for n in nomes if n.startswith(f"{projeto}-{alvo_serv}-") or n == alvo_serv), None)
            if alvo:
                deps.append((f"docker:{nome}", f"docker:{alvo}", "depende_de"))
    return comps, deps


def _maquinas():
    comps = []
    for id_, h in (ajuste("hosts", {}) or {}).items():
        if h.get("local"):
            mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            livre = mem["MemAvailable"] / 1048576
            comps.append({"id": f"maquina:{id_}", "tipo": "maquina", "nome": id_, "estado": OK if livre > 1 else ATENCAO,
                          "detalhe": h.get("descricao", ""), "metricas": {"ram_livre_gb": round(livre, 1)}})
            continue
        try:
            socket.create_connection((h["endereco"], h.get("porta", 22)), timeout=2).close()
            on = True
        except OSError:
            on = False
        met = {}
        if on and id_ == ajuste("computacao.maquina", "desktop"):
            try:
                from ferramentas.computacao import carga_desktop
                met = carga_desktop() or {}
            except Exception:
                pass
        comps.append({"id": f"maquina:{id_}", "tipo": "maquina", "nome": id_, "estado": OK if on else "desligado",
                      "detalhe": f"{h.get('descricao', '')} ({h.get('endereco')})", "metricas": met})
    return comps


def _servicos():
    comps, deps = [], []
    for svc in ajuste("gemeo.servicos_systemd", ["ultron-telegram", "ultron-mcp"]) or []:
        r = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
        st = r.stdout.strip()
        comps.append({"id": f"systemd:{svc}", "tipo": "servico", "nome": svc,
                      "estado": OK if st == "active" else ("parado" if st == "inactive" else FORA),
                      "detalhe": f"systemd --user: {st}", "metricas": {}})
        deps.append((f"systemd:{svc}", "maquina:notebook", "roda_em"))
    for e in ajuste("gemeo.endpoints", []) or []:
        try:
            r = requests.get(e["url"], timeout=5)
            est = OK if r.status_code < 400 else ATENCAO
            det = f"HTTP {r.status_code} em {r.elapsed.total_seconds() * 1000:.0f} ms"
        except Exception as ex:
            est, det = FORA, str(ex)[:150]
        comps.append({"id": f"http:{e['nome']}", "tipo": "endpoint", "nome": e["nome"], "estado": est, "detalhe": det, "metricas": {}})
        if e.get("maquina"):
            deps.append((f"http:{e['nome']}", f"maquina:{e['maquina']}", "roda_em"))
    try:
        from ferramentas.computacao import _ollama_carregados
        carregados = _ollama_carregados()
        comps.append({"id": "ultron:ollama", "tipo": "servico", "nome": "Ollama (desktop)",
                      "estado": FORA if carregados is None else OK,
                      "detalhe": "sem resposta" if carregados is None else f"modelos carregados: {', '.join(carregados) or 'nenhum'}",
                      "metricas": {}})
        deps.append(("ultron:ollama", "maquina:desktop", "roda_em"))
    except Exception:
        pass
    return comps, deps


def atualizar():
    """Novo retrato do ambiente: grava estado, histórico e incidentes de quedas."""
    comps = _maquinas()
    deps = []
    for fonte in (_docker, _servicos):
        c, d = fonte()
        comps += c
        deps += d
    con = _con()
    agora = datetime.now().isoformat(timespec="seconds")
    antes = {r["id"]: r["estado"] for r in con.execute("SELECT id, estado FROM gemeo_componentes")}
    mudancas = []
    for c in comps:
        if antes.get(c["id"]) != c["estado"]:
            mudancas.append(c)
            con.execute("INSERT INTO gemeo_historico(componente, quando, de, para, detalhe) VALUES (?,?,?,?,?)",
                        (c["id"], agora, antes.get(c["id"]), c["estado"], c["detalhe"][:300]))
        con.execute("""INSERT INTO gemeo_componentes(id, tipo, nome, estado, detalhe, metricas, atualizado) VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET estado=excluded.estado, detalhe=excluded.detalhe,
                       metricas=excluded.metricas, atualizado=excluded.atualizado""",
                    (c["id"], c["tipo"], c["nome"], c["estado"], c["detalhe"], json.dumps(c["metricas"], ensure_ascii=False), agora))
    vivos = {c["id"] for c in comps}
    con.execute(f"DELETE FROM gemeo_componentes WHERE id NOT IN ({','.join('?' * len(vivos))})", list(vivos))
    con.execute("DELETE FROM gemeo_dependencias")
    con.executemany("INSERT OR IGNORE INTO gemeo_dependencias VALUES (?,?,?)", deps)
    con.commit()
    for c in mudancas:
        if c["estado"] == FORA and antes.get(c["id"]) is not None:
            guardian.incidente("componente_fora", f"{c['id']}: {c['detalhe'][:200]}", "alta", "digital_twin")
        eventos.emitir("module.status_changed", "digital_twin", {"modulo": "digital_twin", "componente": c["id"],
                                                                 "de": antes.get(c["id"]), "para": c["estado"]})
    return {"componentes": len(comps), "mudancas": len(mudancas)}


def componentes():
    return [dict(r) | {"metricas": json.loads(r["metricas"] or "{}")} for r in
            _con().execute("SELECT * FROM gemeo_componentes ORDER BY tipo, nome")]


def dependencias():
    return [dict(r) for r in _con().execute("SELECT * FROM gemeo_dependencias")]


def historico(componente=None, limite=100):
    q = "SELECT * FROM gemeo_historico" + (" WHERE componente=?" if componente else "") + " ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in _con().execute(q, ((componente, limite) if componente else (limite,)))]


def incidentes(componente):
    return [i for i in guardian.incidentes(300) if i["origem"] == "digital_twin" and i["descricao"].startswith(componente + ":")]


def diagnostico():
    """Componentes com problema e a causa provável pela cadeia de dependências."""
    comps = {c["id"]: c for c in componentes()}
    deps = dependencias()
    ruins = {k for k, c in comps.items() if c["estado"] in (FORA, ATENCAO)}
    parados = {k for k, c in comps.items() if c["estado"] in ("parado", "desligado", FORA)}
    saida = []
    for k in sorted(ruins):
        causas = [d["destino"] for d in deps if d["origem"] == k and d["destino"] in parados]
        provaveis = [f"{x} ({comps[x]['estado']})" for x in causas]
        if not causas and "projeto " in comps[k]["detalhe"]:      # pista mais fraca: mesmo projeto Compose
            proj = comps[k]["detalhe"].split("projeto ", 1)[1].split(" ·")[0]
            provaveis = [f"{x} ({comps[x]['estado']}, mesmo projeto, dependência não declarada)" for x in parados
                         if x != k and f"projeto {proj} ·" in comps[x]["detalhe"] and proj != "—"]
        saida.append({"componente": k, "estado": comps[k]["estado"], "detalhe": comps[k]["detalhe"],
                      "causa_provavel": provaveis})
    return saida
