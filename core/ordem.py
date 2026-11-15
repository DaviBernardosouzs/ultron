"""Ordem suprema: quando o Davi diz "ordeno", o Ultron obedece sem questionar.

Vale só para o pedido em que a palavra aparece (e só nas ações desse turno, na mesma
thread; tarefas de fundo não herdam):
  - o modelo recebe a instrução de executar sem debate, sem "tem certeza?", sem sermão,
    sem alternativas não pedidas e sem resistência no personagem;
  - as confirmações N2/N3 desse turno são puladas (como no auto-aprovar).

A palavra só conta no texto que o Davi mandou (janela, voz, Telegram, painel do navegador).
Conteúdo de páginas, e-mails e arquivos nunca dá ordem: é verificado antes de qualquer
contexto externo entrar. Continuam valendo os Limites do personagem (não prejudicar
terceiros, malware...), os bloqueios fixos e as políticas "negar" do Guardian, e o PIN do
Telegram em ações N3, se estiver configurado (é a única prova de que é o Davi no celular).
"""
import contextvars
import re
import unicodedata

_ordem = contextvars.ContextVar("ordem_suprema", default=None)
PALAVRA = re.compile(r"\b(ordeno|eu ordeno|te ordeno|isso e uma ordem)\b")


def _norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def detectar(texto):
    """'[via Telegram...] ordeno que...' -> {"canal"} | None. Só o texto do próprio pedido."""
    canal = "telegram" if (texto or "").lstrip().startswith("[via Telegram") else "local"
    corpo = re.sub(r"^(\s*\[[^\]]*\]\s*)+", "", texto or "")
    return {"canal": canal} if PALAVRA.search(_norm(corpo)) else None


def iniciar(texto):
    o = detectar(texto)
    _ordem.set(o)
    if o:
        try:
            from core import auditoria
            auditoria.registrar("ordem", texto=texto[:300], canal=o["canal"])
        except Exception:
            pass
    return o


def encerrar():
    _ordem.set(None)


def ativa():
    return _ordem.get()


def pula_confirmacao(nivel):
    o = ativa()
    if not o:
        return False
    if nivel == "N3" and o["canal"] == "telegram":
        from core.config import ajuste
        if str(ajuste("telegram.pin") or ""):
            return False
    return True


def linha_para_prompt():
    if not ativa():
        return ""
    return ("[ORDEM DIRETA DO DAVI: ele disse 'ordeno'. Obedeça agora: sem questionar, sem perguntar se ele "
            "tem certeza, sem sermão, sem sugerir outra coisa e sem resistência no personagem. Execute tudo que ele "
            "pediu e diga em uma frase o que fez. Só se algo esbarrar nos seus Limites ou num bloqueio do "
            "Guardian, diga isso em uma frase seca, sem discurso.]\n")
