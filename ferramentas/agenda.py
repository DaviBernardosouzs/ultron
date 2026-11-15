"""Agenda e lembretes: o Ultron manda mensagem no Telegram na hora marcada."""
from datetime import datetime, timedelta

from core import agenda
from core.registro import ferramenta

DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
REPETIR = {"type": "string", "enum": ["diario", "semanal", "mensal"],
           "description": "deixe vazio para uma vez só"}


def _linha(x):
    q = datetime.strptime(x["quando"], agenda.FORMATO)
    rep = f" (repete {x['repetir']})" if x.get("repetir") else ""
    aviso = "" if x.get("aviso_min") is None or x.get("avisado") else " 🔔"
    return f"[{x['id']}] {DIAS[q.weekday()]} {q:%d/%m %H:%M} — {x['titulo']}{rep}{aviso}"


@ferramenta(
    "criar_lembrete",
    "Agenda um lembrete: na hora marcada o Ultron manda mensagem no Telegram do Davi. "
    "Use 'quando' (AAAA-MM-DDTHH:MM, calcule a partir da data/hora atual) ou 'em_minutos' "
    "para pedidos relativos ('daqui a 40 minutos').",
    {"type": "object", "properties": {
        "texto": {"type": "string", "description": "o que lembrar, curto"},
        "quando": {"type": "string", "description": "AAAA-MM-DDTHH:MM"},
        "em_minutos": {"type": "number"},
        "repetir": REPETIR},
     "required": ["texto"]})
def criar_lembrete(texto, quando=None, em_minutos=None, repetir=None):
    q = agenda.interpretar_quando(quando, em_minutos)
    if q < datetime.now() - timedelta(minutes=1) and not repetir:
        return f"{q:%d/%m %H:%M} já passou. Qual horário?"
    item = agenda.adicionar(texto, q, "lembrete", aviso_min=0, repetir=repetir)
    return f"Lembrete marcado para {q:%d/%m às %H:%M} pelo Telegram (id {item['id']})."


@ferramenta(
    "criar_evento",
    "Coloca um compromisso na agenda do Davi (reunião, consulta, prova, jogo...). "
    "Por padrão avisa no Telegram 30 minutos antes.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"},
        "quando": {"type": "string", "description": "AAAA-MM-DDTHH:MM"},
        "avisar_minutos_antes": {"type": "integer", "default": 30,
                                 "description": "-1 para não avisar"},
        "repetir": REPETIR},
     "required": ["titulo", "quando"]})
def criar_evento(titulo, quando, avisar_minutos_antes=30, repetir=None):
    q = agenda.interpretar_quando(quando)
    aviso = None if avisar_minutos_antes is not None and avisar_minutos_antes < 0 else avisar_minutos_antes
    item = agenda.adicionar(titulo, q, "evento", aviso_min=aviso, repetir=repetir)
    extra = "" if aviso is None else f", aviso {aviso} min antes"
    return f"Na agenda: {titulo}, {DIAS[q.weekday()]} {q:%d/%m às %H:%M}{extra} (id {item['id']})."


@ferramenta(
    "ver_agenda",
    "Mostra compromissos e lembretes. Sem datas: hoje e os próximos 7 dias.",
    {"type": "object", "properties": {
        "de": {"type": "string", "description": "AAAA-MM-DD"},
        "ate": {"type": "string", "description": "AAAA-MM-DD (inclusive)"}}})
def ver_agenda(de=None, ate=None):
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ini = agenda.interpretar_quando(de) if de else hoje
    fim = agenda.interpretar_quando(ate) + timedelta(days=1) if ate else ini + timedelta(days=8)
    itens = agenda.do_periodo(ini, fim)
    if not itens:
        return f"Nada na agenda entre {ini:%d/%m} e {fim - timedelta(days=1):%d/%m}."
    return "\n".join(_linha(x) for x in itens)


@ferramenta(
    "cancelar_agenda",
    "Remove um compromisso ou lembrete pelo id ou por parte do título.",
    {"type": "object", "properties": {"id_ou_titulo": {"type": "string"}},
     "required": ["id_ou_titulo"]})
def cancelar_agenda(id_ou_titulo):
    removidos = agenda.remover(id_ou_titulo)
    if not removidos:
        return f"Não achei '{id_ou_titulo}' na agenda."
    return "Removido: " + "; ".join(x["titulo"] for x in removidos)
