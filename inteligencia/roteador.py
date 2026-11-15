"""HIVE MIND: escolha do modelo e do esforço para cada pedido.

Modos (inteligencia.modo_modelos):
  automatico   Gemini com esforço ajustado à intenção; conteúdo sensível vai para o modelo
               local do desktop (ou o Ultron avisa em vez de enviar)
  avancado     como automático, com mais raciocínio nas tarefas complexas
  privacidade  (PRIVACY_FIRST) tudo que é sensível fica local; o resto vai ao Gemini
  local_only   nada sai do computador: só o modelo local (sem ferramentas)
A ordem das reservas do Gemini segue a taxa de sucesso observada (eventos), não o tamanho
do modelo. O modelo que respondeu de fato é registrado (evento task.progress etapa=modelo).
Claude Code continua sendo executor de tarefas (Claude Bridge), não um cérebro de conversa.
"""
import re
import statistics
import time

import requests

from core import eventos
from core.config import ajuste

MODOS = ("automatico", "avancado", "privacidade", "local_only")
SENSIVEL = re.compile(r"\b(senha|password|cpf|rg\b|cart[aã]o de cr[eé]dito|n[uú]mero do cart[aã]o|cvv|conta banc[aá]ria|"
                      r"ag[eê]ncia e conta|pix|sal[aá]rio|diagn[oó]stico|exame m[eé]dico|rem[eé]dio controlado|"
                      r"token|chave (de )?api|segredo|dados pessoais)\b", re.I)
ESFORCO = {"conversa": "minimal", "ferramenta": "minimal", "factual": "low", "memoria": "low",
           "pesquisa": "medium", "decisao": "medium", "multietapas": "medium", "delegacao": "medium"}
SUBIR = {"minimal": "low", "low": "medium", "medium": "high", "high": "high"}


def modo():
    m = ajuste("inteligencia.modo_modelos", "automatico")
    return m if m in MODOS else "automatico"


def local_disponivel():
    try:
        from ferramentas.computacao import _maquina, _no_ar
        return _no_ar(_maquina()[1])
    except Exception:
        return False


def decidir(pedido, classe):
    """-> {executor: gemini|local|bloqueado, esforco, motivo, sensivel}"""
    m = modo()
    sensivel = bool(SENSIVEL.search(pedido or ""))
    esforco = ESFORCO.get(classe, "low")
    if m == "avancado" and classe in ("pesquisa", "decisao", "multietapas", "delegacao"):
        esforco = SUBIR[esforco]
    if m == "local_only":
        if local_disponivel():
            return {"executor": "local", "esforco": None, "motivo": "modo LOCAL ONLY", "sensivel": sensivel}
        return {"executor": "bloqueado", "esforco": None, "sensivel": sensivel,
                "motivo": "modo LOCAL ONLY e o desktop (modelo local) está desligado"}
    if sensivel:
        if local_disponivel():
            return {"executor": "local", "esforco": None, "sensivel": True,
                    "motivo": "pedido com dado sensível: respondido pelo modelo local, nada saiu do computador"}
        return {"executor": "bloqueado", "esforco": None, "sensivel": True,
                "motivo": "o pedido parece ter dado sensível e o modelo local (desktop) está desligado; "
                          "não enviei à nuvem. Ligue o desktop ou reescreva sem o dado."}
    return {"executor": "gemini", "esforco": esforco, "sensivel": False,
            "motivo": f"intenção '{classe}' → esforço {esforco}" + (" (modo avançado)" if m == "avancado" else "")}


# ------------------------------------------------------------------ estatísticas observadas

def estatisticas(desde=None):
    """Por modelo: usos, falhas, latência mediana (dos eventos task.progress etapa=modelo)."""
    evs = [e for e in eventos.consultar(origem="hive_mind", desde=desde, limite=5000)]
    por = {}
    for e in evs:
        d = e["dados"]
        m = d.get("modelo") or "?"
        x = por.setdefault(m, {"usos": 0, "falhas": 0, "lat": []})
        x["usos"] += 1
        x["falhas"] += 0 if d.get("ok", True) else 1
        if d.get("ms"):
            x["lat"].append(d["ms"])
    return {m: {"usos": x["usos"], "falhas": x["falhas"],
                "sucesso": round(1 - x["falhas"] / x["usos"], 3) if x["usos"] else None,
                "latencia_ms_p50": round(statistics.median(x["lat"])) if x["lat"] else None} for m, x in por.items()}


def ordenar_modelos(modelos, minimo=5):
    """Reservas do Gemini pela taxa de sucesso observada (o principal fica à frente sem dados)."""
    est = estatisticas()
    def chave(par):
        i, m = par
        s = est.get(m)
        if not s or s["usos"] < minimo:
            return (0, i)
        return (-(s["sucesso"] or 0), i)
    principal, resto = modelos[0], modelos[1:]
    s = est.get(principal)
    if s and s["usos"] >= minimo and (s["sucesso"] or 0) < 0.6:      # principal falhando muito: entra na fila
        return [m for _, m in sorted(enumerate(modelos), key=chave)]
    return [principal] + [m for _, m in sorted(enumerate(resto), key=chave)]


def registrar(modelo, ok, ms, esforco, classe, motivo):
    eventos.emitir("task.progress", "hive_mind", {"etapa": "modelo", "modelo": modelo, "ok": ok, "ms": int(ms),
                                                  "esforco": esforco, "intencao": classe, "motivo": motivo})


# ------------------------------------------------------------------ modelo local (sem ferramentas)

def responder_local(historico_texto, pedido):
    from ferramentas.computacao import _ollama_url
    modelo = ajuste("inteligencia.modelo_local_chat", "dolphin3")
    msgs = [{"role": "system", "content": "Você é o Ultron, assistente do Davi. Responda em português do Brasil, "
             "curto. Você está rodando localmente, sem ferramentas: se o pedido exigir uma ação, diga que só "
             "consegue agir pelo modelo principal."}]
    msgs += historico_texto[-8:] + [{"role": "user", "content": pedido}]
    t0 = time.time()
    r = requests.post(_ollama_url() + "/api/chat", timeout=180,
                      json={"model": modelo, "messages": msgs, "stream": False, "keep_alive": "30m"})
    r.raise_for_status()
    return r.json()["message"]["content"].strip(), f"local:{modelo}", (time.time() - t0) * 1000
