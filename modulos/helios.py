"""HELIOS: energia e automação residencial pelo Home Assistant (REST, token de longa duração).

Configuração: casa.url no config.yaml e HOME_ASSISTANT_TOKEN no .env (hoje: NÃO configurado).
- Dispositivos autorizados: domínios em helios.dominios (luz, tomada, cena, sensor, mídia, ventilador,
  clima). Fechaduras, alarmes e portões (lock, alarm_control_panel, cover) são só leitura.
  Tomadas/interruptores com nome de risco (aquecedor, bomba, portão, fogão...) exigem N3.
- Consumo: sensores com device_class energy (kWh acumulado) e power (W instantâneo); o
  relatório por dia vem do histórico do próprio Home Assistant.
- Cenas: scene.create com o estado atual das entidades escolhidas (snapshot); ativar = scene.turn_on.
- Rotinas: ficam na Macro Forge (versão, teste e aprovação), usando estas ferramentas.
"""
import re
from datetime import datetime, timedelta

import requests

from core.config import ajuste, segredo

DOMINIOS_PADRAO = ["light", "switch", "scene", "sensor", "media_player", "fan", "climate"]
SO_LEITURA = {"lock", "alarm_control_panel", "cover"}
RISCO = re.compile(r"aquecedor|heater|bomba|pump|port[aã]o|gate|fog[aã]o|stove|forno|oven|ferro|caldeira|boiler", re.I)


class NaoConfigurado(RuntimeError):
    pass


def configurado():
    return bool(ajuste("casa.url")) and bool(segredo("HOME_ASSISTANT_TOKEN"))


def _api(metodo, caminho, **kw):
    if not configurado():
        raise NaoConfigurado("Home Assistant não configurado: defina casa.url no config.yaml e HOME_ASSISTANT_TOKEN no .env")
    r = requests.request(metodo, f"{ajuste('casa.url').rstrip('/')}/api/{caminho}", timeout=15,
                         headers={"Authorization": f"Bearer {segredo('HOME_ASSISTANT_TOKEN')}"}, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def dispositivos(dominio=None):
    permitidos = set(ajuste("helios.dominios", DOMINIOS_PADRAO) or DOMINIOS_PADRAO) | SO_LEITURA
    saida = []
    for s in _api("GET", "states"):
        dom = s["entity_id"].split(".")[0]
        if dom not in permitidos or (dominio and dom != dominio):
            continue
        nome = s["attributes"].get("friendly_name", s["entity_id"])
        saida.append({"id": s["entity_id"], "nome": nome, "dominio": dom, "estado": s["state"],
                      "classe": s["attributes"].get("device_class"), "unidade": s["attributes"].get("unit_of_measurement"),
                      "risco": "so_leitura" if dom in SO_LEITURA else ("alto" if RISCO.search(nome + s["entity_id"]) else "normal")})
    return saida


def nivel_acao(entidade):
    dom = entidade.split(".")[0]
    if dom in SO_LEITURA:
        return "bloqueado"
    return "N3" if RISCO.search(entidade) else "N1"


def acionar(entidade, acao, brilho=None):
    """acao: ligar | desligar | alternar. Brilho 0-100 para luzes."""
    dom = entidade.split(".")[0]
    if dom in SO_LEITURA:
        raise PermissionError(f"{entidade}: fechaduras, alarmes e portões são só leitura no Helios")
    if dom not in (ajuste("helios.dominios", DOMINIOS_PADRAO) or DOMINIOS_PADRAO):
        raise PermissionError(f"domínio {dom} não autorizado no Helios")
    servico = {"ligar": "turn_on", "desligar": "turn_off", "alternar": "toggle"}[acao]
    dados = {"entity_id": entidade}
    if brilho is not None and dom == "light" and acao == "ligar":
        dados["brightness_pct"] = max(0, min(100, int(brilho)))
    _api("POST", f"services/{dom}/{servico}", json=dados)
    return f"{entidade}: {acao}" + (f" ({dados.get('brightness_pct')}%)" if "brightness_pct" in dados else "")


def medidores():
    return [d for d in dispositivos("sensor") if d["classe"] in ("energy", "power")]


def consumo(dias=7):
    """kWh por dia de cada medidor de energia (diferença do acumulado), a partir do histórico do HA."""
    inicio = (datetime.now() - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
    resultado = {}
    for m in medidores():
        if m["classe"] != "energy":
            continue
        hist = _api("GET", f"history/period/{inicio.isoformat()}", params={"filter_entity_id": m["id"], "minimal_response": ""})
        por_dia = {}
        for ponto in (hist[0] if hist else []):
            try:
                v = float(ponto["state"])
            except (ValueError, KeyError):
                continue
            dia = ponto.get("last_changed", ponto.get("last_updated", ""))[:10]
            mn, mx = por_dia.get(dia, (v, v))
            por_dia[dia] = (min(mn, v), max(mx, v))
        resultado[m["nome"]] = {d: round(mx - mn, 3) for d, (mn, mx) in sorted(por_dia.items())}
    return resultado


def potencia_agora():
    return {m["nome"]: f"{m['estado']} {m['unidade'] or ''}".strip() for m in medidores() if m["classe"] == "power"}


def criar_cena(nome, entidades):
    for e in entidades:
        if e.split(".")[0] in SO_LEITURA:
            raise PermissionError(f"{e} não pode entrar em cena")
    sid = re.sub(r"\W+", "_", nome.lower()).strip("_")
    _api("POST", "services/scene/create", json={"scene_id": sid, "snapshot_entities": list(entidades)})
    return f"scene.{sid}"


def ativar_cena(cena):
    cena = cena if cena.startswith("scene.") else f"scene.{cena}"
    _api("POST", "services/scene/turn_on", json={"entity_id": cena})
    return cena


def relatorio_energia(dias=7):
    c = consumo(dias)
    linhas = [f"# Energia: últimos {dias} dias", "", "> Dados dos medidores do Home Assistant (observados).", ""]
    total = 0.0
    for nome, dias_ in c.items():
        soma = sum(dias_.values())
        total += soma
        linhas.append(f"## {nome}: {soma:.2f} kWh")
        linhas += [f"- {d}: {v:.2f} kWh" for d, v in dias_.items()]
    linhas.append(f"\n**Total medido:** {total:.2f} kWh")
    pot = potencia_agora()
    if pot:
        linhas.append("\nAgora: " + "; ".join(f"{k} {v}" for k, v in pot.items()))
    return "\n".join(linhas), total
