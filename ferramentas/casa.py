"""Casa inteligente via Home Assistant (luzes, tomadas, TV, ar, sensores...).

O Home Assistant é a forma mais simples de falar com quase todo dispositivo
inteligente (Tuya/Smart Life, Xiaomi, Philips Hue, Chromecast, TVs, Alexa...).
Configure casa.url no config.yaml e HOME_ASSISTANT_TOKEN no .env.
"""
import requests

from core.config import ajuste, segredo
from core.registro import NAO_CONFIAVEL, ferramenta

DOMINIOS = ("light", "switch", "fan", "climate", "media_player", "cover", "lock", "sensor",
            "binary_sensor", "vacuum", "scene", "script")


def _api(metodo, caminho, **kw):
    url, token = ajuste("casa.url"), segredo("HOME_ASSISTANT_TOKEN")
    if not url or not token:
        raise RuntimeError("Home Assistant não configurado (casa.url e HOME_ASSISTANT_TOKEN).")
    r = requests.request(metodo, f"{url.rstrip('/')}/api/{caminho}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10, **kw)
    r.raise_for_status()
    return r.json()


@ferramenta(
    "listar_casa",
    "Lista os dispositivos da casa inteligente e o estado de cada um. Opcionalmente "
    "filtra por tipo (light, switch, climate, media_player, sensor...) ou nome.",
    {"type": "object", "properties": {"filtro": {"type": "string"}}})
def listar_casa(filtro=None):
    linhas = []
    for e in _api("GET", "states"):
        dom = e["entity_id"].split(".")[0]
        if dom not in DOMINIOS:
            continue
        nome = e["attributes"].get("friendly_name", e["entity_id"])
        if filtro and filtro.lower() not in (e["entity_id"] + nome).lower():
            continue
        unid = e["attributes"].get("unit_of_measurement", "")
        linhas.append(f"{e['entity_id']} | {nome} | {e['state']}{unid}")
    return NAO_CONFIAVEL + ("\n".join(linhas[:150]) or "Nada encontrado.")


@ferramenta(
    "controlar_casa",
    "Controla um dispositivo do Home Assistant. acao: turn_on, turn_off, toggle, ou "
    "outro serviço do domínio (ex.: set_temperature, volume_set). Use o entity_id de "
    "listar_casa; dados extras (brilho, temperatura...) vão em 'dados'.",
    {"type": "object", "properties": {
        "entity_id": {"type": "string"},
        "acao": {"type": "string"},
        "dados": {"type": "object"}}, "required": ["entity_id", "acao"]})
def controlar_casa(entity_id, acao, dados=None):
    dominio = entity_id.split(".")[0]
    if dominio == "lock" and acao == "unlock":
        return "Destrancar fechaduras por voz está bloqueado por segurança."
    _api("POST", f"services/{dominio}/{acao}", json={"entity_id": entity_id, **(dados or {})})
    return f"{acao} em {entity_id}: ok."
