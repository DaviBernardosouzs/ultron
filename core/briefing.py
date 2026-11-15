"""Briefing do dia: na primeira vez que o Ultron abre no dia, ele resume clima,
agenda, lembretes, e-mails e o estado das máquinas."""
import json
import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from core.config import DADOS, ajuste

LOG = logging.getLogger("ultron.briefing")

ESTADO = DADOS / "briefing.json"


def pendente():
    """True se ainda não houve briefing hoje."""
    if not ajuste("briefing.ativo", True):
        return False
    try:
        ultimo = json.loads(ESTADO.read_text())["data"]
    except Exception:
        ultimo = None
    return ultimo != datetime.now().date().isoformat()


def marcar_feito():
    ESTADO.write_text(json.dumps({"data": datetime.now().date().isoformat()}))


def _clima():
    from ferramentas.utilidades import clima
    return clima()


def _agenda():
    from core import agenda
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    itens = agenda.do_periodo(hoje, hoje + timedelta(days=1))
    if not itens:
        return "nada marcado hoje"
    return "; ".join(f"{x['quando'][11:]} {x['titulo']}" for x in itens)


def _emails():
    if not ajuste("email.endereco"):
        return None
    from ferramentas.comunicacao import ler_emails
    return ler_emails(quantidade=5, apenas_nao_lidos=True)


def _maquinas():
    partes = []
    for id_, h in (ajuste("hosts", {}) or {}).items():
        if h.get("local") or not h.get("endereco"):
            continue
        # O Windows bloqueia ping por padrão; a porta do SSH responde se a máquina está ligada.
        try:
            socket.create_connection((h["endereco"], h.get("porta", 22)), timeout=1.5).close()
            ligado = True
        except OSError:
            ligado = False
        partes.append(f"{id_} {'ligado' if ligado else 'desligado'}")
    return ", ".join(partes) or None


def coletar():
    """Junta os dados em paralelo; o que falhar fica de fora."""
    fontes = {"clima": _clima, "agenda de hoje": _agenda, "e-mails não lidos": _emails,
              "máquinas": _maquinas}
    dados = {}
    with ThreadPoolExecutor(len(fontes)) as ex:
        futuros = {nome: ex.submit(f) for nome, f in fontes.items()}
        for nome, fut in futuros.items():
            try:
                valor = fut.result(timeout=20)
                if valor:
                    dados[nome] = valor
            except Exception as e:
                LOG.warning("briefing: %s falhou: %s", nome, e)
    return dados


def gerar(cerebro):
    """Texto do briefing na voz do Ultron (ou um resumo simples se o modelo falhar)."""
    dados = coletar()
    hora = datetime.now().hour
    saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    bruto = "\n".join(f"- {k}: {v}" for k, v in dados.items())
    pedido = (f"[BRIEFING AUTOMÁTICO — o Davi acabou de te abrir pela primeira vez hoje]\n"
              f"Comece com '{saudacao}' e faça um briefing falado curto (4 a 6 frases, sem "
              f"listas nem markdown) com estes dados. Não chame ferramentas.\n{bruto}")
    try:
        texto = cerebro.responder(pedido)
    except Exception as e:
        LOG.warning("briefing pelo modelo falhou: %s", e)
        texto = ""
    falhas = ("Não consigo", "Estou sendo limitado", "Estou sem conexão", "Os servidores",
              "A API respondeu", "Parei aqui", "Prefiro não")
    if not texto or texto.startswith(falhas):
        texto = f"{saudacao}, {ajuste('usuario.nome', 'chefe')}. " + " ".join(
            f"{k.capitalize()}: {v}." for k, v in dados.items() if k != "e-mails não lidos")
    marcar_feito()
    return texto
