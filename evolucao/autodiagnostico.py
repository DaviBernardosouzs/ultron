"""Self-Diagnostics da Evolution Forge.

Junta o diagnóstico de log/auditoria/avaliações/inventário (descoberta.diagnostico)
com verificações reais do sistema:
  inicializacao  ferramentas que não carregaram (registro.carregar)
  testes         suíte pytest do núcleo (só quando pedido: leva alguns segundos)
  dependencias   uv pip check
  integracoes    desktop, Ollama, sandbox bwrap, plugins MCP, fontes do NEURALINK
  desempenho     latência real das respostas (pedido -> resposta na auditoria)
Cada achado pode virar uma proposta de correção: ela entra como necessidade e segue
o mesmo caminho de sempre (investigar, desenvolver, testar no sandbox, aprovação).
"""
import json
import re
import shutil
import statistics
import subprocess
import time
from datetime import datetime

from core.config import DADOS, RAIZ
from evolucao.base import PASTA, registrar

TESTES = PASTA / "testes_nucleo.json"


def _achado(fonte, nivel, origem, problema, sugestao, vezes=1):
    return {"fonte": fonte, "nivel": nivel, "origem": origem, "problema": problema,
            "sugestao": sugestao, "vezes": vezes}


def inicializacao():
    from core import registro
    falhas = registro.carregar()
    return [_achado("inicialização", "ERROR", f"ferramentas.{m}", "módulo não carregou",
                    "veja o traceback no ultron.log") for m in falhas]


def rodar_testes():
    """Roda a suíte do núcleo e guarda o resultado (usado também no registro de capacidades)."""
    t = time.time()
    r = subprocess.run(["uv", "run", "--quiet", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                       cwd=RAIZ, capture_output=True, text=True, timeout=600,
                       env={**__import__("os").environ, "NEURALINK_SEM_SERVICO": "1"})
    saida = (r.stdout + r.stderr).strip()
    ultima = saida.splitlines()[-1] if saida else ""
    num = lambda chave: int(m.group(1)) if (m := re.search(rf"(\d+) {chave}", ultima)) else 0
    res = {"quando": datetime.now().isoformat(timespec="seconds"), "ok": r.returncode == 0,
           "passaram": num("passed"), "falharam": num("failed") + num("error"), "pulados": num("skipped"),
           "segundos": round(time.time() - t, 1), "resumo": ultima[:200],
           "falhas": re.findall(r"^FAILED (\S+)", saida, re.M)[:20]}
    TESTES.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    registrar("testes_nucleo", resumo=ultima[:120])
    return res


def ultimo_teste():
    try:
        return json.loads(TESTES.read_text())
    except Exception:
        return None


def dependencias():
    try:
        r = subprocess.run(["uv", "pip", "check"], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    except Exception as e:
        return [_achado("dependências", "WARNING", "uv", f"não consegui verificar: {e}", "instale o uv")]
    if r.returncode == 0:
        return []
    return [_achado("dependências", "ERROR", "uv pip check", l.strip()[:160], "ajuste a versão no pyproject")
            for l in r.stdout.splitlines() if l.strip()][:10]


def integracoes():
    achados = []
    from evolucao import sandbox
    if not sandbox.disponivel():
        achados.append(_achado("integração", "ERROR", "sandbox", "bubblewrap indisponível",
                               "instale o pacote bubblewrap; sem ele nada novo pode ser testado"))
    try:
        from ferramentas.computacao import _maquina, _no_ar, _ollama_carregados
        nome, h = _maquina()
        if not _no_ar(h):
            achados.append(_achado("integração", "WARNING", nome, "desktop desligado",
                                   "IA local, embeddings e tarefas pesadas esperam o desktop"))
        elif _ollama_carregados() is None:
            achados.append(_achado("integração", "WARNING", "ollama", "Ollama do desktop não respondeu",
                                   "abra o Ollama no desktop"))
    except Exception as e:
        achados.append(_achado("integração", "WARNING", "computacao", str(e)[:120], "investigar"))
    try:
        from core import plugins
        for nome, c in plugins.configuracao().items():
            falta = plugins.faltando(c)
            if falta:
                achados.append(_achado("integração", "INFO", f"plugin:{nome}", f"falta {', '.join(falta)}",
                                       "configure a chave no .env para ativar"))
    except Exception:
        pass
    try:
        from neuralink import ingestao
        for f in ingestao.fontes():
            if f["erro"]:
                achados.append(_achado("integração", "WARNING", f"neuralink:{f['nome']}", f["erro"][:150],
                                       "confira se a pasta ainda existe"))
    except Exception:
        pass
    return achados


def latencias(n=200):
    """Segundos entre cada pedido e a resposta, lidos da auditoria (dados reais)."""
    pares, aberto = [], None
    try:
        linhas = (DADOS / "auditoria.log").read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
    except FileNotFoundError:
        return []
    for l in linhas:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if e.get("evento") == "pedido":
            aberto = e.get("quando")
        elif e.get("evento") == "resposta" and aberto:
            try:
                dt = (datetime.fromisoformat(e["quando"]) - datetime.fromisoformat(aberto)).total_seconds()
                if 0 <= dt < 600:
                    pares.append(dt)
            except Exception:
                pass
            aberto = None
    return pares[-n:]


def desempenho():
    lat = latencias()
    if len(lat) < 5:
        return [], None
    med = statistics.median(lat)
    p90 = sorted(lat)[int(len(lat) * 0.9) - 1]
    info = {"mediana": round(med, 1), "p90": round(p90, 1), "amostras": len(lat)}
    achados = []
    if med > 12:
        achados.append(_achado("desempenho", "WARNING", "respostas", f"mediana de {med:.1f} s por resposta",
                               "use ia.esforco: low, um modelo mais rápido ou menos ferramentas por pedido"))
    return achados, info


def completo(com_testes=False):
    from evolucao import descoberta
    achados = []
    for fn in (inicializacao, dependencias, integracoes):
        try:
            achados += fn()
        except Exception as e:
            achados.append(_achado("diagnóstico", "WARNING", fn.__name__, str(e)[:150], "investigar"))
    try:
        achados += descoberta.diagnostico()
    except Exception as e:
        achados.append(_achado("diagnóstico", "WARNING", "log", str(e)[:150], "investigar"))
    teste = rodar_testes() if com_testes else ultimo_teste()
    if teste and not teste["ok"]:
        for f in teste["falhas"] or ["(veja a saída do pytest)"]:
            achados.append(_achado("testes", "ERROR", f, "teste quebrado", "corrigir antes de qualquer nova versão"))
    perf, lat = desempenho()
    achados += perf
    ordem = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    achados.sort(key=lambda a: (ordem.get(a["nivel"], 3), -a.get("vezes", 1)))
    registrar("autodiagnostico", resumo=f"{len(achados)} achados")
    return {"achados": achados, "testes": teste, "latencia": lat}


def propor_correcao(achado):
    """O achado vira uma necessidade; a correção segue o processo normal com aprovação."""
    from evolucao import descoberta
    return descoberta.registrar_necessidade(
        f"Corrigir: {achado['problema']} ({achado['origem']})",
        f"Achado pelo autodiagnóstico ({achado['fonte']}, {achado['nivel']}, {achado.get('vezes', 1)}x). "
        f"Sugestão inicial: {achado['sugestao']}")
