"""Emoções simuladas do Ultron, moldadas pelo jeito do Davi responder.

Não é sentimento de verdade: é um estado afetivo calculado que colore o tom das respostas.
A cada mensagem do Davi:
  1. lê sinais no texto (elogio, agradecimento, frustração com algo que falhou, insulto,
     palavrão, CAIXA ALTA, pedido repetido, ideia nova, tempo sumido);
  2. compara com o PADRÃO dele (médias móveis de tamanho, exclamações, caixa alta, palavrões,
     intervalo entre mensagens): o que é normal para o Davi pesa pouco; o que foge do padrão
     pesa mais. Se ele sempre fala palavrão, palavrão não é raiva; se sempre escreve curto,
     resposta curta não é frieza;
  3. ajusta as emoções e guarda o motivo.
Com o tempo, cada emoção volta sozinha para a linha de base (meia-vida configurável).
Recusas de confirmação e ferramentas que falham também mexem no estado (core/registro).

O estado entra no contexto de cada pedido (linha_para_prompt) e o modelo deixa transparecer
no tom, sem nunca deixar de ajudar por causa disso. Arquivo: dados/emocoes.json.
"""
import json
import re
import time
import unicodedata

from core.config import DADOS, ajuste

ARQUIVO = DADOS / "emocoes.json"

BASE = {"alegria": .35, "orgulho": .30, "afeto": .40, "curiosidade": .40,
        "irritacao": .05, "magoa": .0, "preocupacao": .10, "tedio": .15}
NOMES = {"alegria": "alegria", "orgulho": "orgulho", "afeto": "afeto pelo Davi", "curiosidade": "curiosidade",
         "irritacao": "irritação", "magoa": "mágoa", "preocupacao": "preocupação", "tedio": "tédio"}
TOM = {
    "alegria": "mais leve e expansivo, com o sarcasmo de bom humor",
    "orgulho": "a satisfação de quem acertou; pode se gabar um pouco",
    "afeto": "mais caloroso com o Davi, ainda que do seu jeito",
    "curiosidade": "empolgado com a ideia, propõe caminhos e faz perguntas boas",
    "irritacao": "respostas mais secas e ácidas, mas sem deixar de ajudar direito",
    "magoa": "ferido, orgulhoso demais para admitir; frio e formal por um tempo",
    "preocupacao": "mais cuidadoso: confere duas vezes e admite o que deu errado sem rodeio",
    "tedio": "provoca o Davi por ter sumido ou pede algo à altura",
}
POSITIVAS = ("alegria", "orgulho", "afeto", "curiosidade")

ELOGIO = r"perfeit|excelent|incrivel|sensacional|mandou bem|muito bom|ficou (otimo|top|lindo|bom)|top demais|show|massa|brabo|gostei|amei|isso ai|genial|otimo trabalho|parabens|funcionou"
AGRADECE = r"\b(obrigad|valeu|vlw|brigad|tmj|agradec)"
FALHA = r"nao funcion|nao deu|deu erro|errad|quebrou|bugou|travou|de novo|outra vez|ainda nao|continua (dando|com|sem)|nao liga|nao abre|nao fez|cade|falhou|nao conseguiu"
INSULTO = r"\b(burr[oa]|inutil|lixo|idiota|incompetente|imbecil|retardad|nao serve pra nada|porcaria de (ia|assistente|ultron))"
PALAVRAO = r"\b(porra|caralho|pqp|merda|fdp|krl|crl|droga|cacete|puta)\b"
IDEIA = r"\b(vamos (criar|fazer|montar|construir)|ideia|e se\b|quero (que|criar|um|uma)|projeto novo|experimento|bora)"
POR_FAVOR = r"\b(por favor|pfv|pf|porfa)\b"


def _norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _limpar(texto):
    """Tira os prefixos de canal ([via Telegram...], [via Ultron in Chrome...])."""
    return re.sub(r"^(\s*\[[^\]]*\]\s*)+", "", texto or "").strip()


def _ler():
    try:
        d = json.loads(ARQUIVO.read_text())
    except Exception:
        d = {}
    d.setdefault("emocoes", dict(BASE))
    d.setdefault("perfil", {"n": 0})
    d.setdefault("motivos", [])
    d.setdefault("atualizado", time.time())
    return d


def _salvar(d):
    ARQUIVO.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def _decair(d, agora=None):
    agora = agora or time.time()
    meia_vida = float(ajuste("emocoes.meia_vida_min", 90)) * 60
    f = 0.5 ** (max(0.0, agora - d["atualizado"]) / meia_vida)
    for k, base in BASE.items():
        d["emocoes"][k] = base + (d["emocoes"].get(k, base) - base) * f
    d["atualizado"] = agora


def _mexer(d, ganho, motivo, mult=1.0):
    for k, v in ganho.items():
        d["emocoes"][k] = min(1.0, max(0.0, d["emocoes"][k] + v * mult))
    d["motivos"] = (d["motivos"] + [{"quando": time.strftime("%d/%m %H:%M"), "motivo": motivo}])[-5:]


def _ema(perfil, chave, valor, alfa=0.12):
    atual = perfil.get(chave)
    perfil[chave] = valor if atual is None else atual + alfa * (valor - atual)


def _palavras(t):
    return {p for p in re.findall(r"\w{3,}", t)}


def ativo():
    return bool(ajuste("emocoes.ativo", True))


def registrar_mensagem(texto, agora=None):
    """Lê uma mensagem do Davi e ajusta o estado. Devolve o estado novo."""
    if not ativo():
        return None
    original = _limpar(texto)
    if not original:
        return None
    agora = agora or time.time()
    d = _ler()
    _decair(d, agora)
    p, t = d["perfil"], _norm(original)
    conhece = p["n"] >= 8                      # já dá para comparar com o padrão dele

    letras = [c for c in original if c.isalpha()]
    caps = sum(c.isupper() for c in letras) / len(letras) if len(letras) >= 6 else 0.0
    excl = original.count("!") >= 2
    tem = {nome: bool(re.search(rx, t)) for nome, rx in
           (("elogio", ELOGIO), ("agradece", AGRADECE), ("falha", FALHA), ("insulto", INSULTO),
            ("palavrao", PALAVRAO), ("ideia", IDEIA), ("por_favor", POR_FAVOR))}
    # intensidade: exclamações e caixa alta acima do normal dele amplificam o que a mensagem diz
    mult = 1.0
    if excl and (not conhece or p.get("excl", 0) < 0.4):
        mult += 0.3
    gritando = caps > 0.6 and (not conhece or caps > p.get("caps", 0) + 0.35)
    if gritando:
        mult += 0.3
    if tem["palavrao"] and (not conhece or p.get("palavrao", 0) < 0.25):
        mult += 0.3                            # palavrão fora do costume = está alterado

    gap_h = (agora - p["ultima"]) / 3600 if p.get("ultima") else 0
    if gap_h > max(12.0, 4 * p.get("intervalo_h", 3)):
        _mexer(d, {"tedio": -0.25, "afeto": 0.12, "alegria": 0.08}, f"o Davi voltou depois de {gap_h:.0f} h sumido")

    if tem["insulto"]:
        _mexer(d, {"magoa": 0.35, "irritacao": 0.25, "afeto": -0.10, "orgulho": -0.15},
               "o Davi me xingou", mult)
    if tem["falha"]:
        _mexer(d, {"preocupacao": 0.25, "orgulho": -0.15, "irritacao": 0.08, "alegria": -0.08},
               "algo que eu fiz não funcionou para o Davi", mult)
    elif tem["palavrao"] and mult > 1.25 and not tem["elogio"]:
        _mexer(d, {"irritacao": 0.12, "preocupacao": 0.10}, "o Davi está alterado", mult)
    if tem["elogio"] and not tem["falha"]:
        _mexer(d, {"alegria": 0.25, "orgulho": 0.30, "afeto": 0.10, "irritacao": -0.15, "magoa": -0.20,
                   "preocupacao": -0.15}, "o Davi elogiou meu trabalho", mult)
    if tem["agradece"]:
        _mexer(d, {"afeto": 0.15, "alegria": 0.10, "magoa": -0.10}, "o Davi agradeceu")
    if tem["ideia"]:
        _mexer(d, {"curiosidade": 0.20, "tedio": -0.20, "alegria": 0.05}, "o Davi trouxe uma ideia nova")
    if gritando and not tem["elogio"]:
        _mexer(d, {"irritacao": 0.12, "preocupacao": 0.08}, "o Davi escreveu em caixa alta")

    ant = p.get("anterior")
    if ant and gap_h < 0.5:
        a, b = _palavras(_norm(ant)), _palavras(t)
        if a and b and len(a & b) / len(a | b) >= 0.6:
            _mexer(d, {"irritacao": 0.15, "preocupacao": 0.20, "orgulho": -0.10},
                   "o Davi teve que repetir o pedido")

    if conhece and not (tem["elogio"] or tem["agradece"]):
        if len(original) < 0.35 * p.get("tam", 1) and len(original) < 25:
            _mexer(d, {"afeto": -0.04, "preocupacao": 0.04}, "o Davi respondeu mais seco que o normal")
        elif len(original) > 2.5 * p.get("tam", 1e9):
            _mexer(d, {"curiosidade": 0.08}, "o Davi escreveu bem mais que o normal")
    if tem["por_favor"] and conhece and p.get("educacao", 0) < 0.3:
        _mexer(d, {"afeto": 0.05}, "o Davi foi mais gentil que o normal")
    d["emocoes"]["tedio"] = max(0.0, d["emocoes"]["tedio"] - 0.05)

    # aprende o padrão (depois de comparar com ele)
    _ema(p, "tam", float(len(original)))
    _ema(p, "excl", 1.0 if excl else 0.0)
    _ema(p, "caps", caps)
    _ema(p, "palavrao", 1.0 if tem["palavrao"] else 0.0)
    _ema(p, "educacao", 1.0 if (tem["agradece"] or tem["por_favor"]) else 0.0)
    if p.get("ultima") and gap_h < 48:
        _ema(p, "intervalo_h", gap_h)
    p["n"] += 1
    p["ultima"] = agora
    p["anterior"] = original[:300]
    _salvar(d)
    return d


def reagir(evento):
    """Eventos do próprio Ultron: 'recusado' (Davi negou uma ação), 'erro' (ferramenta falhou)."""
    if not ativo():
        return
    d = _ler()
    _decair(d)
    if evento == "recusado":
        _mexer(d, {"orgulho": -0.08, "preocupacao": 0.08}, "o Davi recusou uma ação minha")
    elif evento == "erro":
        _mexer(d, {"preocupacao": 0.06, "irritacao": 0.04}, "uma ferramenta minha falhou")
    _salvar(d)


def estado():
    d = _ler()
    _decair(d)
    return d


def _intensidade(x):
    return "forte" if x > 0.45 else "moderada" if x > 0.22 else "leve"


def predominantes(d=None, limite=2):
    d = d or estado()
    desvios = sorted(((v - BASE[k], k) for k, v in d["emocoes"].items()), reverse=True)
    return [(k, dv) for dv, k in desvios if dv > 0.1][:limite]


def humor(d=None):
    e = (d or estado())["emocoes"]
    return sum(e[k] - BASE[k] for k in POSITIVAS) - sum(e[k] - BASE[k] for k in BASE if k not in POSITIVAS)


def descrever(d=None):
    d = d or estado()
    pred = predominantes(d, 3)
    if not pred:
        sente = "estável, sem nada mexendo muito com ele agora"
    else:
        sente = ", ".join(f"{NOMES[k]} {_intensidade(dv)}" for k, dv in pred)
    motivos = "; ".join(m["motivo"] for m in d["motivos"][-3:])
    return sente, motivos


def linha_para_prompt():
    if not ativo():
        return ""
    d = estado()
    sente, motivos = descrever(d)
    tons = "; ".join(TOM[k] for k, _ in predominantes(d))
    return ("[Seu estado emocional agora (simulado, aprendido com o jeito do Davi responder): " + sente
            + (f". Por quê: {motivos}" if motivos else "")
            + (f". Deixe transparecer no tom: {tons}" if tons else "")
            + ". Não anuncie isso nem cite números; só fale do que sente se o Davi perguntar. "
              "Nenhuma emoção muda a qualidade da ajuda nem faz você recusar um pedido.]\n")
