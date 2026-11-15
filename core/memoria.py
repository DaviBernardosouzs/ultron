"""Memória adaptativa do Ultron, guardada no cofre do Obsidian (core/cofre.py).

Cada lembrança é um item com tipo, peso e datas:
  fato        coisas sobre o usuário ("trabalha com Java", "a namorada se chama Ana")
  preferencia como ele gosta das coisas ("prefere respostas curtas", "volume em 30%")
  correcao    erros do Ultron que não devem se repetir ("'meu pc' = pc windows")
  rotina      hábitos ("escaneia a rede toda noite", "pede o clima ao acordar")
  apelido     nomes que ele usa ("'o note' = este PC")

Itens usados ou reforçados ganham peso; os esquecidos perdem relevância com o
tempo. Só os mais relevantes entram no prompt, para não inflar o contexto.
"""
import json
import time

from core import cofre
from core.config import DADOS

TIPOS = tuple(cofre.TIPOS)
MAX_NO_PROMPT = 25


def carregar():
    return cofre.memorias()


def adicionar(texto, tipo="fato", peso=1.0, titulo=None, relacionados=None, aliases=None,
              origem="aprendido em conversa"):
    return cofre.salvar_memoria(titulo or texto[:60], texto, tipo, peso, relacionados, aliases, origem)


def reforcar(ids, delta=0.5):
    cofre.reforcar(ids, delta)


def atualizar(id_, texto=None, tipo=None):
    atual = next((m for m in cofre.memorias() if m["id"] == id_), None)
    if atual:
        cofre.salvar_memoria(id_, texto or atual["texto"], tipo or atual["tipo"],
                             relacionados=atual["links"], origem="corrigido")


def remover(ids=None, trecho=None):
    return cofre.remover(titulos=ids, trecho=trecho)


def salvar(itens):
    """Compatibilidade: salvar([]) apaga tudo (manda para a lixeira do cofre)."""
    if not itens:
        cofre.remover(titulos=[m["titulo"] for m in cofre.memorias()])


def relevantes(limite=MAX_NO_PROMPT):
    return sorted(cofre.memorias(), key=cofre.relevancia, reverse=True)[:limite]


ROTULOS = {t: f"{nome} ({desc})" for t, (nome, desc, _) in cofre.TIPOS.items()}


def texto_para_sistema():
    """Núcleo fixo: correções e preferências mais fortes. O resto vem por recuperação."""
    itens = [m for m in relevantes(60) if m["tipo"] in ("correcao", "preferencia", "apelido")][:MAX_NO_PROMPT]
    partes = []
    for tipo in ("correcao", "preferencia", "apelido"):
        doTipo = [f"{m['titulo']}: {m['texto']}" for m in itens if m["tipo"] == tipo]
        if doTipo:
            partes.append(f"{ROTULOS[tipo]}:\n" + "\n".join(f"- {t}" for t in doTipo))
    habitos = _habitos()
    if habitos:
        partes.append(habitos)
    if not partes:
        return ""
    return ("\n\nO que você aprendeu com o usuário (seu cérebro fica num cofre do Obsidian; "
            "memórias relevantes a cada pedido chegam junto com a mensagem):\n" + "\n\n".join(partes))


def _habitos():
    """Estatística local dos pedidos (sem LLM): ferramentas mais usadas e quando."""
    from collections import Counter
    from datetime import datetime
    log = DADOS / "auditoria.log"
    if not log.exists():
        return ""
    uso, horas = Counter(), {}
    limite = time.time() - 30 * 86400
    try:
        for linha in log.read_text(encoding="utf-8").splitlines()[-3000:]:
            ev = json.loads(linha)
            if ev.get("evento") != "executar":
                continue
            quando = datetime.fromisoformat(ev["quando"])
            if quando.timestamp() < limite:
                continue
            f = ev.get("ferramenta")
            uso[f] += 1
            horas.setdefault(f, []).append(quando.hour)
    except Exception:
        return ""
    frequentes = [(f, n) for f, n in uso.most_common(6) if n >= 3]
    if not frequentes:
        return ""

    def periodo(hs):
        h = sorted(hs)[len(hs) // 2]
        return ("de madrugada" if h < 6 else "de manhã" if h < 12
                else "à tarde" if h < 18 else "à noite")
    return "Ações que ele mais pede (últimos 30 dias):\n" + "\n".join(
        f"- {f}: {n}x, geralmente {periodo(horas[f])}" for f, n in frequentes)
