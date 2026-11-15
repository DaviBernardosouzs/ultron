"""Tool Intelligence Engine: registro inteligente e seleção progressiva de ferramentas.

Antes: as 127 ferramentas (~11 mil tokens de schemas) iam ao modelo em todo pedido.
Agora: selecionar(pedido) devolve só as relevantes (BM25 sobre nome, descrição, módulo e
parâmetros, com sinônimos em pt-BR) + as essenciais + a meta-ferramenta
'buscar_ferramentas', que o modelo usa para descobrir outras quando precisar
(descoberta progressiva). O benchmark (avaliacao/) mede inclusão da ferramenta certa,
MRR e tokens antes/depois.

perfil(nome): capacidades, schema, permissões, estado (plugin com chave faltando?),
latência observada e falhas recentes (barramento de eventos).
"""
import json
import math
import re
import unicodedata
from collections import Counter

from core import registro
from core.config import ajuste

ESSENCIAIS = ["data_hora", "buscar_ferramentas"]
SINONIMOS = {
    "tempo": "clima previsao chuva temperatura", "chover": "clima", "chuva": "clima", "frio": "clima", "calor": "clima",
    "celular": "telegram mensagem notificar android", "zap": "mensagem celular", "avisa": "notificar mensagem",
    "luz": "casa lampada controlar", "lampada": "casa luz", "tomada": "casa", "ar": "casa", "tv": "casa midia",
    "musica": "midia spotify tocar pausar", "pausa": "midia", "toca": "midia", "proxima": "midia",
    "lembra": "lembrete lembrar", "lembrete": "criar lembrete", "agenda": "agenda compromisso evento ver",
    "amanha": "agenda", "marca": "criar evento agenda", "marcar": "criar evento agenda",
    "consulta": "evento agenda", "dentista": "evento agenda", "medico": "evento agenda", "compromisso": "agenda evento", "reuniao": "reuniao resumir agenda evento",
    "pc": "computador desktop", "mesa": "desktop computador", "liga": "ligar", "desliga": "desligar",
    "internet": "web pesquisar", "google": "web pesquisar", "pesquisa": "pesquisar web buscar",
    "documentos": "documentos buscar atlas", "deploy": "documentos", "nota": "nota obsidian",
    "decidir": "cortex analisar decisao", "decisao": "decisao registrar cortex", "escolher": "cortex decidir",
    "planeja": "vector planejar", "etapas": "vector planejar", "migracao": "vector planejar",
    "claude": "claude delegar", "revisar": "claude delegar revisao", "codigo": "claude delegar",
    "duplicados": "duplicatas encontrar", "organiza": "organizacao sugerir arquivos", "pasta": "diretorio arquivos",
    "tela": "tela bloquear", "cade": "achar", "perdi": "achar", "tocar": "achar midia", "simula": "oracle simular",
    "gastar": "oracle simular custo", "energia": "oracle casa", "build": "desktop tarefa enviar",
    "pesado": "desktop tarefa enviar", "ram": "recursos memoria status", "gpu": "recursos desktop",
    "aconteceu": "linha tempo historico", "ontem": "linha tempo", "volume": "volume som", "som": "volume",
    "rede": "rede escanear dispositivos", "aparelhos": "dispositivos rede escanear", "conectados": "rede escanear",
    "modo": "ativar modo", "dormir": "modo", "trabalhar": "modo", "jogar": "modo",
    "guarda": "lembrar registrar", "memoria": "lembrar memoria buscar", "esquece": "esquecer",
    "email": "email enviar ler", "site": "pagina web ler abrir", "url": "pagina web ler", "link": "pagina web ler", "projeto": "projeto contexto", "workspace": "workspace", "arquivo": "arquivos buscar",
    "navegador": "navegador abas ler", "brave": "navegador", "chrome": "navegador", "aba": "navegador abas",
    "console": "navegador console depurar", "depurar": "navegador console rede", "whatsapp": "navegador mensagem enviar",
    "clica": "navegador clicar", "clicar": "navegador clicar", "digita": "navegador digitar",
}
_indice = None
# palavras de função do português: não indicam ferramenta nenhuma
STOP = set("""a o e é as os de da do das dos em no na nos nas um uma uns umas para pra por com sem que se ao aos
qual quais como quando onde quem porque por que isso isto esse essa este esta aquele aquela ele ela eles elas eu voce
meu minha meus minhas seu sua seus suas nosso nossa me te lhe nos vai vou ta esta estou estao foi ser sao tem ter
faz fazer fala diz ai la aqui ja mais menos muito pouco tudo nada algo agora hoje entre sobre ou mas nem tambem
funciona significa diferenca coisa quero queria pode poderia favor ultron""".split())


def _norm(t):
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return t


def _radical(p):
    return p[:5]          # decidi/decidir, lembra/lembrete, agenda/agendar caem no mesmo radical


def _palavras(t):
    return [p for p in re.findall(r"[a-z0-9]+", _norm(t).replace("_", " ")) if len(p) >= 2 and p not in STOP]


def _tokens(t):
    return [_radical(p) for p in _palavras(t)]


_SIN = None


def _sinonimos():
    """Sinônimos indexados pelo radical (a busca acontece depois do corte)."""
    global _SIN
    if _SIN is None:
        _SIN = {}
        for k, v in SINONIMOS.items():
            _SIN.setdefault(_radical(_norm(k)), []).extend(_tokens(v))
    return _SIN


def _expandir(texto):
    toks = _tokens(texto)
    extra = []
    for t in toks:
        extra += _sinonimos().get(t, [])
    return toks + extra


def _doc(f):
    mod = f.funcao.__module__.rsplit(".", 1)[-1]
    params = " ".join(f.parametros.get("properties", {}))
    # o nome pesa mais: aparece duas vezes
    return f"{f.nome} {f.nome} {f.descricao} {mod} {params}"


def _construir():
    global _indice
    fs = registro.todas() or (registro.carregar() and registro.todas()) or registro.todas()
    docs = {f.nome: Counter(_tokens(_doc(f))) for f in fs}
    df = Counter(t for d in docs.values() for t in d)
    n = len(docs)
    media = sum(sum(d.values()) for d in docs.values()) / max(n, 1)
    _indice = {"docs": docs, "idf": {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()},
               "media": media, "n": len(fs)}
    return _indice


def _idx():
    if _indice is None or _indice["n"] != len(registro.todas()):
        _construir()
    return _indice


def pontuar(pedido):
    idx = _idx()
    q = _expandir(pedido)
    pts = {}
    for nome, d in idx["docs"].items():
        tam = sum(d.values())
        s = 0.0
        for t in set(q):
            if t in d:
                tf = d[t]
                s += idx["idf"][t] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * tam / idx["media"]))
        if s > 0:
            pts[nome] = s
    return sorted(pts.items(), key=lambda x: -x[1])


def selecionar(pedido, k=None, extras=()):
    """Ferramentas para este pedido: top-K + essenciais + descobertas nesta conversa."""
    k = int(k or ajuste("inteligencia.max_ferramentas", 14))
    ranking = pontuar(pedido)
    # sem confiança (nenhuma ferramenta casa bem): manda todas, como antes. Limiar escolhido
    # nos conjuntos de desenvolvimento/validação (menor acerto observado: 3,9).
    if not ranking or ranking[0][1] < float(ajuste("inteligencia.confianca_minima", 5.0)):
        return _permitidas(list(registro.todas()))
    escolhidas = []
    if ranking:
        corte = ranking[0][1] * 0.18          # descarta o que é muito mais fraco que o melhor
        escolhidas = [n for n, s in ranking[:k] if s >= corte]
    nomes = list(dict.fromkeys(escolhidas + list(extras) + ESSENCIAIS))
    return _permitidas([f for f in (registro.obter(n) for n in nomes) if f])


def _permitidas(fs):
    """Não oferece ao modelo o que o WorkSpace ativo bloqueia (ele tentaria e levaria 'negado')."""
    try:
        from core import workspaces
        return [f for f in fs if workspaces.ferramenta_permitida(f.nome, f.funcao.__module__) is not False]
    except Exception:
        return fs


def schemas(fs):
    return [{"name": f.nome, "description": f.descricao, "input_schema": f.parametros} for f in fs]


def descobrir(necessidade, k=8):
    return [registro.obter(n) for n, _ in pontuar(necessidade)[:k] if registro.obter(n)]


def perfil(nome):
    """Ficha da ferramenta com dados observados (latência, falhas) e estado."""
    f = registro.obter(nome)
    if not f:
        raise ValueError(f"ferramenta {nome} não existe")
    from core import eventos
    concl = [e for e in eventos.consultar(tipo="tool.completed", limite=3000) if e["dados"].get("ferramenta") == nome]
    falhas = [e for e in eventos.consultar(tipo="tool.failed", limite=3000) if e["dados"].get("ferramenta") == nome]
    ms = sorted(e["dados"].get("ms", 0) for e in concl)
    estado = "ok"
    if getattr(f, "plugin", None) or nome.startswith("plugin"):
        estado = "plugin"
    return {"nome": nome, "descricao": f.descricao, "modulo": f.funcao.__module__, "nivel": f.nivel,
            "schema": f.parametros, "estado": estado, "usos": len(concl), "falhas": len(falhas),
            "taxa_sucesso": round(len(concl) / (len(concl) + len(falhas)), 3) if concl or falhas else None,
            "latencia_ms_p50": ms[len(ms) // 2] if ms else None,
            "ultima_falha": falhas[0]["dados"].get("erro") if falhas else None}


# ------------------------------------------------------------------ descoberta progressiva (por turno)
import threading as _threading

_turno = _threading.local()


def iniciar_turno(pedido):
    _turno.pedido = pedido
    _turno.descobertas = []
    try:
        from inteligencia import intencao
        _turno.classe = intencao.classificar(pedido)["classe"]
    except Exception:
        _turno.classe = None


def descobertas():
    return list(getattr(_turno, "descobertas", []))


def registrar_descobertas(nomes):
    if not hasattr(_turno, "descobertas"):
        _turno.descobertas = []
    for n in nomes:
        if n not in _turno.descobertas:
            _turno.descobertas.append(n)


def declaradas(usadas_no_historico=()):
    """O que vai ao modelo nesta chamada: seleção do pedido + já usadas no histórico + descobertas."""
    if not ajuste("inteligencia.selecao_ferramentas", True):
        return list(registro.todas())
    pedido = getattr(_turno, "pedido", "") or ""
    extras = list(dict.fromkeys(list(usadas_no_historico) + descobertas()))
    sel = selecionar(pedido, extras=extras)
    # conversa/pergunta de conhecimento sem ferramenta clara: só as essenciais (o modelo descobre se precisar)
    if getattr(_turno, "classe", None) in ("conversa", "factual") and len(sel) == len(_permitidas(list(registro.todas()))):
        livros = ["consultar_livros"] if _turno.classe == "factual" else []    # pergunta de saber: os livros
        sel = _permitidas([f for f in (registro.obter(n) for n in list(dict.fromkeys(extras + ESSENCIAIS + livros))) if f])
    return sel
