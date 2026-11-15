"""SELF AUDIT: auditoria operacional do Ultron, com evidências.

Verifica:
  servicos       serviços do Ultron (systemd --user), desktop, Ollama, sandbox
  configuracao   config.yaml legível, seções essenciais, caminhos que existem, valores válidos
  mcp            plugins MCP configurados (chaves faltando)
  skills         cada skill instalada passa no validador da Forja
  falhas         ferramentas/tarefas que falham repetidamente (barramento de eventos, 7 dias)
  dependencias   uv pip check
  testes         último resultado da suíte (ou roda, se pedido)
  recursos       processos do Ultron com consumo anormal de CPU/RAM; RAM livre do notebook
Cada achado traz 'evidencia' (o comando, a linha do log ou os eventos que o sustentam).
O relatório fica em auditorias (dados/ultron.db) e numa nota do Scribe; gera audit.completed.
Correções só são PROPOSTAS (viram necessidade na Evolution Forge); nada é alterado aqui.
"""
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from core import eventos
from core.config import RAIZ, ajuste


def _con():
    c = eventos._con()
    c.execute("CREATE TABLE IF NOT EXISTS auditorias (id INTEGER PRIMARY KEY, quando TEXT, resumo TEXT, achados TEXT)")
    return c


def _a(area, nivel, item, problema, evidencia, sugestao=""):
    return {"area": area, "nivel": nivel, "item": item, "problema": problema, "evidencia": str(evidencia)[:600],
            "sugestao": sugestao}


def servicos():
    achados = []
    for svc in ajuste("self_audit.servicos", ["ultron-telegram", "ultron-mcp"]) or []:
        r = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
        if r.stdout.strip() != "active":
            nivel = "WARNING" if svc != "ultron-telegram" else "ERROR"
            achados.append(_a("servicos", nivel, svc, f"serviço {r.stdout.strip() or 'parado'}",
                              f"systemctl --user is-active {svc} -> {r.stdout.strip()}",
                              f"systemctl --user restart {svc}"))
    from evolucao import autodiagnostico
    for x in autodiagnostico.integracoes():
        achados.append(_a("servicos", x["nivel"], x["origem"], x["problema"], f"verificação de integração ({x['fonte']})",
                          x["sugestao"]))
    return achados


def configuracao():
    achados = []
    arq = RAIZ / "config.yaml"
    try:
        cfg = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return [_a("configuracao", "ERROR", "config.yaml", "não é um YAML válido", e, "corrija a sintaxe")]
    for secao in ("usuario", "ia", "voz", "hosts", "seguranca", "memoria"):
        if secao not in cfg:
            achados.append(_a("configuracao", "WARNING", secao, "seção ausente", f"config.yaml sem '{secao}:'"))
    cofre = Path(str((cfg.get("memoria") or {}).get("cofre", ""))).expanduser()
    if not cofre.exists():
        achados.append(_a("configuracao", "ERROR", "memoria.cofre", "o cofre do Obsidian não existe", cofre))
    prov = (cfg.get("ia") or {}).get("provedor")
    if prov not in ("gemini", "claude"):
        achados.append(_a("configuracao", "ERROR", "ia.provedor", f"provedor inválido: {prov}", f"ia.provedor = {prov}"))
    seg = cfg.get("seguranca") or {}
    if not seg.get("senha_ao_abrir", True):
        achados.append(_a("configuracao", "WARNING", "seguranca.senha_ao_abrir", "o painel abre sem senha",
                          "seguranca.senha_ao_abrir = false"))
    for nome, h in (cfg.get("hosts") or {}).items():
        if not h.get("local") and h.get("chave") and not Path(str(h["chave"])).expanduser().exists():
            achados.append(_a("configuracao", "ERROR", f"hosts.{nome}.chave", "chave SSH não existe", h["chave"]))
    from core import guardian
    for d in ajuste("guardian.diretorios", guardian.DIRETORIOS_PADRAO) or []:
        if not Path(d).expanduser().exists():
            achados.append(_a("configuracao", "INFO", "guardian.diretorios", f"diretório autorizado não existe: {d}", d))
    return achados


def mcp():
    achados = []
    try:
        from core import plugins
        for nome, c in plugins.configuracao().items():
            falta = plugins.faltando(c)
            if falta:
                achados.append(_a("mcp", "INFO", f"plugin:{nome}", f"inativo: falta {', '.join(falta)}",
                                  f"plugins.yaml requer {falta}", "adicione a chave ao .env se quiser usar"))
    except Exception as e:
        achados.append(_a("mcp", "WARNING", "plugins.yaml", "não consegui ler", e))
    return achados


def skills():
    achados = []
    try:
        from evolucao import skills as sk
        from evolucao.base import SKILLS
        for pasta in sorted(Path(SKILLS).glob("*")) if Path(SKILLS).exists() else []:
            if pasta.is_dir():
                problemas = sk.validar(pasta)
                if problemas:
                    achados.append(_a("skills", "WARNING", pasta.name, "skill inválida", "; ".join(problemas),
                                      "corrija o SKILL.md ou remova pela Forja"))
    except Exception as e:
        achados.append(_a("skills", "WARNING", "skills", "não consegui validar", e))
    return achados


def falhas(dias=7, minimo=3):
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    evs = [e for e in eventos.consultar(desde=desde, tipo="%.failed", limite=5000)]
    cont = Counter((e["origem"], e["dados"].get("ferramenta") or e["dados"].get("macro") or e["dados"].get("plano") or "?")
                   for e in evs)
    achados = []
    for (origem, item), n in cont.most_common(10):
        if n >= minimo:
            exemplo = next(e for e in evs if (e["origem"], e["dados"].get("ferramenta") or e["dados"].get("macro")
                                             or e["dados"].get("plano") or "?") == (origem, item))
            achados.append(_a("falhas", "ERROR" if n >= 10 else "WARNING", item, f"{n} falhas em {dias} dias ({origem})",
                              f"último: {exemplo['quando'][:16]} {exemplo['dados'].get('erro') or exemplo['dados']}",
                              "veja os argumentos e o erro; pode virar correção na Forja"))
    return achados


def dependencias():
    from evolucao import autodiagnostico
    return [_a("dependencias", x["nivel"], x["origem"], x["problema"], "uv pip check", x["sugestao"])
            for x in autodiagnostico.dependencias()]


def testes(rodar=False):
    from evolucao import autodiagnostico
    t = autodiagnostico.rodar_testes() if rodar else autodiagnostico.ultimo_teste()
    if not t:
        return [_a("testes", "WARNING", "suíte", "os testes nunca rodaram", "sem dados/evolucao/testes_nucleo.json",
                   "rode a auditoria com testes")]
    if not t["ok"]:
        return [_a("testes", "ERROR", f, "teste falhando", t["resumo"], "corrija antes de novas versões") for f in t["falhas"] or ["suíte"]]
    idade = datetime.now() - datetime.fromisoformat(t["quando"])
    if idade > timedelta(days=7):
        return [_a("testes", "INFO", "suíte", f"último resultado tem {idade.days} dias", t["resumo"])]
    return []


def recursos():
    achados = []
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    livre_gb = mem["MemAvailable"] / 1048576
    if livre_gb < 1.2:
        achados.append(_a("recursos", "WARNING", "notebook", f"pouca RAM livre ({livre_gb:.1f} GB)",
                          f"MemAvailable={mem['MemAvailable']} kB", "mande trabalho pesado ao desktop"))
    r = subprocess.run(["ps", "-eo", "pid,%cpu,rss,args", "--sort=-rss"], capture_output=True, text=True)
    for l in r.stdout.splitlines()[1:]:
        pid, cpu, rss, args = l.split(None, 3)
        if "ultron" not in args or "pytest" in args:
            continue
        rss_mb, cpu = int(rss) // 1024, float(cpu)
        lim_ram = int(ajuste("self_audit.ram_max_mb", 900))
        lim_cpu = float(ajuste("self_audit.cpu_max", 60))
        if rss_mb > lim_ram or cpu > lim_cpu:
            achados.append(_a("recursos", "WARNING", f"pid {pid}", f"processo do Ultron com {rss_mb} MB e {cpu}% de CPU (média)",
                              args[:200], "reinicie o processo; se repetir, investigue vazamento"))
    return achados


AREAS = {"servicos": servicos, "configuracao": configuracao, "mcp": mcp, "skills": skills, "falhas": falhas,
         "dependencias": dependencias, "recursos": recursos}


def auditar(rodar_testes=False):
    achados = []
    for nome, fn in AREAS.items():
        try:
            achados += fn()
        except Exception as e:
            achados.append(_a(nome, "WARNING", nome, "a verificação falhou", e))
    achados += testes(rodar_testes)
    ordem = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    achados.sort(key=lambda a: ordem.get(a["nivel"], 3))
    cont = Counter(a["nivel"] for a in achados)
    resumo = f"{cont.get('ERROR', 0)} erros, {cont.get('WARNING', 0)} avisos, {cont.get('INFO', 0)} informações"
    c = _con()
    aid = c.execute("INSERT INTO auditorias(quando, resumo, achados) VALUES (?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), resumo, json.dumps(achados, ensure_ascii=False))).lastrowid
    c.commit()
    try:
        from modulos import scribe
        corpo = (f"# Auditoria {datetime.now():%Y-%m-%d %H:%M}\n\n**{resumo}**\n\n"
                 + "\n".join(f"## [{a['nivel']}] {a['area']} · {a['item']}\n{a['problema']}\n\n> evidência: `{a['evidencia']}`\n"
                             + (f"\nSugestão: {a['sugestao']}\n" if a["sugestao"] else "") for a in achados))
        scribe.gravar("Auditorias", f"Auditoria {datetime.now():%Y-%m-%d %H%M}", corpo, {"tipo": "auditoria", "retencao": "90d"})
    except Exception:
        pass
    eventos.emitir("audit.completed", "self_audit", {"auditoria": aid, "resumo": resumo})
    return {"id": aid, "resumo": resumo, "achados": achados}


def ultimas(limite=20):
    return [dict(r) | {"achados": json.loads(r["achados"])} for r in
            _con().execute("SELECT * FROM auditorias ORDER BY id DESC LIMIT ?", (limite,))]


def propor(achado):
    from evolucao import autodiagnostico
    return autodiagnostico.propor_correcao({"fonte": achado["area"], "nivel": achado["nivel"], "origem": achado["item"],
                                            "problema": achado["problema"], "sugestao": achado["sugestao"] or "investigar",
                                            "vezes": 1})
