"""Utilidades: hora, clima e memória."""
from datetime import datetime

import requests

from core import memoria
from core.config import ajuste
from core.registro import ferramenta

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@ferramenta("data_hora", "Data e hora atuais.")
def data_hora():
    a = datetime.now()
    return f"{DIAS[a.weekday()]}, {a:%d/%m/%Y}, {a:%H:%M}"


@ferramenta(
    "clima",
    "Previsão do tempo atual e de hoje. Sem cidade, usa a cidade do config.yaml.",
    {"type": "object", "properties": {"cidade": {"type": "string"}}})
def clima(cidade=None):
    cidade = cidade or ajuste("usuario.cidade", "São Paulo")
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": cidade, "count": 1, "language": "pt"}, timeout=10).json()
    if not geo.get("results"):
        return f"Não encontrei a cidade {cidade}."
    g = geo["results"][0]
    d = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": g["latitude"], "longitude": g["longitude"],
        "current": "temperature_2m,apparent_temperature,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1}, timeout=10).json()
    c, dia = d["current"], d["daily"]
    return (f"{g['name']}: {c['temperature_2m']}°C agora (sensação {c['apparent_temperature']}°C), "
            f"mín {dia['temperature_2m_min'][0]}°C, máx {dia['temperature_2m_max'][0]}°C, "
            f"chance de chuva {dia['precipitation_probability_max'][0]}%.")


@ferramenta(
    "lembrar",
    "Guarda no cérebro (cofre do Obsidian) um bloco de informação duradouro, quando o "
    "usuário pede explicitamente. Uma ideia por nota, com título curto e ligações.",
    {"type": "object", "properties": {
        "titulo": {"type": "string", "description": "nome curto do conceito, ex.: 'PC Windows'"},
        "texto": {"type": "string", "description": "1 a 3 frases na 3ª pessoa"},
        "tipo": {"type": "string", "enum": ["fato", "preferencia", "correcao", "rotina", "apelido",
                                           "pessoa", "projeto", "dispositivo", "conhecimento"]},
        "relacionados": {"type": "array", "items": {"type": "string"},
                         "description": "títulos de outras notas ligadas a esta"}},
     "required": ["titulo", "texto"]})
def lembrar(titulo, texto, tipo="fato", relacionados=None):
    t = memoria.adicionar(texto, tipo, peso=1.5, titulo=titulo, relacionados=relacionados,
                          origem="pedido explícito")
    return f"Guardado em [[{t}]]."


@ferramenta(
    "buscar_memoria",
    "Procura no cérebro (cofre do Obsidian) o que o Ultron sabe sobre um assunto, seguindo "
    "as ligações entre as notas.",
    {"type": "object", "properties": {"assunto": {"type": "string"}}, "required": ["assunto"]})
def buscar_memoria(assunto):
    from core import cofre
    achados = cofre.recuperar(assunto, k=8)
    if not achados:
        return "Nada no cérebro sobre isso."
    return "\n".join(f"[{m['tipo']}] {m['titulo']}: {m['texto']} (ligado a: {', '.join(m['links'][:6])})"
                     for m, _ in achados)


@ferramenta(
    "o_que_voce_sabe",
    "Mostra um panorama do que o Ultron aprendeu sobre o usuário, por categoria.")
def o_que_voce_sabe():
    itens = memoria.relevantes(limite=300)
    if not itens:
        return "Nada guardado ainda."
    from core import cofre
    partes = []
    for tipo, (nome, _d, _c) in cofre.TIPOS.items():
        dotipo = [i["titulo"] for i in itens if i["tipo"] == tipo]
        if dotipo:
            partes.append(f"{nome}: " + "; ".join(dotipo[:15]))
    return f"{len(itens)} memórias.\n" + "\n".join(partes)


@ferramenta(
    "esquecer",
    "Apaga da memória os itens que contenham o trecho informado.",
    {"type": "object", "properties": {"trecho": {"type": "string"}}, "required": ["trecho"]})
def esquecer(trecho):
    n = memoria.remover(trecho=trecho)
    return f"{n} lembrança(s) apagada(s)." if n else "Não achei nada com isso."


@ferramenta(
    "esquecer_tudo",
    "Apaga toda a memória de longo prazo do Ultron sobre o usuário.",
    nivel="N3",
    resumo=lambda a: "apagar TODA a minha memória sobre você")
def esquecer_tudo():
    n = len(memoria.carregar())
    memoria.salvar([])
    return f"{n} lembranças apagadas. Tabula rasa."
