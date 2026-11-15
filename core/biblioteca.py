"""Biblioteca do Ultron: o saber geral dele, no cofre do Obsidian.

  Ultron Cérebro/
    Biblioteca/Índice da Biblioteca.md   mapa geral (gerado), liga todas as áreas
    Biblioteca/<Área>/<Área>.md          mapa da área (gerado)
    Biblioteca/<Área>/<Nota>.md          uma nota por tema, com seções "## " e [[links]]
    Personalidade/*.md                   quem ele é (persona e história entram no prompt)

Diferente das Memórias (fatos sobre o Davi, que perdem força com o tempo), o saber
da biblioteca não envelhece. A cada pedido, as seções mais relevantes entram no
contexto sozinhas: busca por palavras (BM25) + significado (embeddings do Gemini,
se disponíveis) + um salto no grafo de links, como uma ideia puxando a outra.
Notas novas que você criar no Obsidian dentro de Biblioteca/ entram no índice
automaticamente.
"""
import json
import logging
import math
import re
import threading
import time
from collections import Counter

from core import cofre
from core.config import DADOS, ajuste

LOG = logging.getLogger("ultron.biblioteca")

PASTA = "Biblioteca"
INDICE = "Índice da Biblioteca"
_trava = threading.Lock()
_cache = {"assinatura": None, "trechos": [], "notas": {}}


def raiz():
    return cofre.raiz() / PASTA


def _assinatura():
    arqs = list(raiz().rglob("*.md")) + list((cofre.raiz() / "Personalidade").glob("*.md"))
    return tuple(sorted((str(a), a.stat().st_mtime_ns) for a in arqs))


def _trechos_da_nota(arq, area):
    meta, corpo = cofre._ler(arq)
    if meta.get("tipo") == "mapa":
        return None, []
    titulo = arq.stem
    aliases = meta.get("aliases") or []
    links = cofre._links(corpo) + cofre._links(json.dumps(meta.get("relacionados") or [],
                                                          ensure_ascii=False))
    trechos = []
    # Cada seção "## " vira um trecho; a parte antes da primeira seção é o resumo.
    partes = re.split(r"^## +(.+)$", corpo, flags=re.M)
    resumo = re.sub(r"^# .*$", "", partes[0], flags=re.M)
    resumo = re.sub(r"^> ?", "", resumo, flags=re.M).strip()
    if resumo:
        trechos.append({"nota": titulo, "secao": "", "texto": resumo})
    for i in range(1, len(partes) - 1, 2):
        secao, texto = partes[i].strip(), partes[i + 1].strip()
        if secao.lower() in ("ligações", "ligacoes", "veja também") or not texto:
            continue
        trechos.append({"nota": titulo, "secao": secao, "texto": texto})
    for t in trechos:
        t.update(area=area, aliases=aliases)
    return {"titulo": titulo, "area": area, "aliases": aliases, "links": links,
            "arquivo": arq}, trechos


def carregar():
    """Lê (com cache) todas as notas da Biblioteca e da Personalidade."""
    with _trava:
        ass = _assinatura()
        if ass == _cache["assinatura"]:
            return _cache["notas"], _cache["trechos"]
        notas, trechos = {}, []
        fontes = [(a, a.parent.name if a.parent != raiz() else "Geral") for a in raiz().rglob("*.md")]
        fontes += [(a, "Personalidade") for a in (cofre.raiz() / "Personalidade").glob("*.md")]
        for arq, area in fontes:
            try:
                nota, ts = _trechos_da_nota(arq, area)
            except Exception as e:
                LOG.warning("nota ilegível %s: %s", arq, e)
                continue
            if nota:
                notas[nota["titulo"]] = nota
                trechos += ts
        _cache.update(assinatura=ass, notas=notas, trechos=trechos)
        return notas, trechos


# ------------------------------------------------------------------ busca

def _chave(t):
    return f"{t['nota']}#{t['secao']}|{cofre.assinatura(t['texto'])}"


def _arq_vetores():
    return cofre.arquivo_vetores("biblioteca")


_vetores = None
_pausa_ate = 0.0   # sem cota de embeddings: não tenta de novo a cada pedido


def _semantica(consulta, trechos):
    global _vetores, _pausa_ate
    if not ajuste("biblioteca.embeddings", True) or time.time() < _pausa_ate:
        return {}
    try:
        if _vetores is None:
            try:
                _vetores = json.loads(_arq_vetores().read_text())
            except Exception:
                _vetores = {}
        faltam = [t for t in trechos if _chave(t) not in _vetores]
        if faltam:
            cofre.completar("biblioteca", [_chave(t) for t in faltam],
                            [f"{t['nota']} — {t['secao']}. {t['texto']}" for t in faltam],
                            _vetores, _arq_vetores(), {_chave(t) for t in trechos})
        q = cofre._embed([consulta], "RETRIEVAL_QUERY")
        if not q:
            return {}
        return {_chave(t): cofre._cos(q[0], _vetores[_chave(t)])
                for t in trechos if _chave(t) in _vetores}
    except Exception as e:
        LOG.info("embeddings indisponíveis (%s); só busca por palavras por 15 min", e)
        _pausa_ate = time.time() + 900
        return {}


# Palavras de pergunta e de comando: não dizem nada sobre o assunto.
VAZIAS = set("""qual quais quem como onde quando porque porquê pq oque que sobre fala falar diz dizer
explica explicar explique me mim te liga ligar desliga desligar abre abrir fecha fechar faz fazer
quero queria pode podes poderia sabe saber conta contar mostra mostrar ve ver vai tem ter ser
esta estao foi era sao seria ultron favor agora hoje aqui ai la isso aquilo coisa coisas tipo
funciona funcionar significa algo alguma algum ola oi bom boa dia tarde noite obrigado valeu""".split())


def _termos(texto):
    return [w for w in cofre._tokens(texto) if w not in VAZIAS]


def buscar(consulta, k=4, minimo=0.35):
    """Trechos mais relevantes: [(trecho, pontuação 0..~2)].

    Pontuação = palavras (BM25 saturado, pesado pela fração da pergunta coberta)
    + bônus se a pergunta cita o título/apelido da nota + significado (embeddings)
    + um pouco do vizinho mais forte no grafo."""
    notas, trechos = carregar()
    q = list(dict.fromkeys(_termos(consulta)))
    if not trechos or not q:
        return []
    qset = set(q)
    # O nome da nota pesa no resumo; nas seções pesa o título da seção, para que
    # dentro de uma nota vença a seção que de fato fala do assunto.
    docs = [(_termos(f"{t['nota']} {' '.join(t['aliases'])}") * (3 if not t["secao"] else 1)
             + _termos(t["secao"]) * 2 + _termos(t["texto"])) for t in trechos]
    n = len(docs)
    df = Counter(w for d in docs for w in set(d))
    media = sum(len(d) for d in docs) / n or 1
    pont = {}
    for i, d in enumerate(docs):
        tf = Counter(d)
        s, achou = 0.0, 0
        for w in q:
            if w in tf:
                achou += 1
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / media))
        if not s:
            continue
        cobertura = achou / len(q)
        nota = s / (s + 6) * (0.3 + 0.7 * cobertura)
        # A pergunta cita a nota pelo nome ("Sun Tzu", "OWASP", "buraco negro")?
        nomes = [set(_termos(x)) for x in [trechos[i]["nota"], *trechos[i]["aliases"]]]
        if any(nm and nm <= qset for nm in nomes):
            nota += 0.6 if not trechos[i]["secao"] else 0.3
        pont[i] = nota
    limiar = float(ajuste("biblioteca.limiar_semantico", 0.62))
    sem = _semantica(consulta, trechos)
    for i, t in enumerate(trechos):
        sim = sem.get(_chave(t), 0)
        if sim > limiar:
            pont[i] = pont.get(i, 0) + (sim - limiar) / (1 - limiar)
    # Grafo: o resumo de uma nota ganha 20% do seu vizinho mais forte (não soma todos).
    por_nota = {}
    for i, s in pont.items():
        por_nota[trechos[i]["nota"]] = max(por_nota.get(trechos[i]["nota"], 0), s)
    for i, t in enumerate(trechos):
        if t["secao"]:
            continue
        viz = [por_nota.get(v, 0) for v in notas.get(t["nota"], {}).get("links", [])]
        viz += [s for nm, s in por_nota.items() if t["nota"] in notas.get(nm, {}).get("links", [])]
        if viz and max(viz) > 0:
            pont[i] = pont.get(i, 0) + 0.2 * max(viz)
    melhores = sorted(pont.items(), key=lambda x: x[1], reverse=True)
    saida, vistas = [], Counter()
    for i, s in melhores:
        if s < minimo:
            break
        if vistas[trechos[i]["nota"]] >= 2:   # no máximo 2 seções da mesma nota
            continue
        vistas[trechos[i]["nota"]] += 1
        saida.append((trechos[i], s))
        if len(saida) >= k:
            break
    return saida


def _formatar(t, limite=900):
    onde = t["nota"] + (f" › {t['secao']}" if t["secao"] else "")
    texto = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), t["texto"])
    texto = re.sub(r"\n{2,}", "\n", texto)
    return f"- {onde}: {texto[:limite]}"


def contexto_para_pedido(pedido):
    """Bloco curto colado ao pedido; vazio se nada for relevante o bastante."""
    if not ajuste("biblioteca.ativa", True) or len(cofre._tokens(pedido)) < 2:
        return ""
    achados = buscar(pedido, k=int(ajuste("biblioteca.trechos_por_pedido", 3)),
                     minimo=float(ajuste("biblioteca.minimo", 0.45)))
    if not achados:
        return ""
    return ("[Da sua biblioteca (saber seu; use se ajudar, com suas palavras, sem dizer que "
            "consultou)]\n" + "\n".join(_formatar(t) for t, _ in achados) + "\n\n")


# ------------------------------------------------------------------ personalidade

def secao_personalidade(nota):
    """Texto de Personalidade/<nota>.md (sem frontmatter, título e ligações); None se não existir."""
    arq = cofre.raiz() / "Personalidade" / f"{nota}.md"
    if not arq.exists():
        return None
    _, corpo = cofre._ler(arq)
    corpo = re.split(r"^## +Ligações", corpo, flags=re.M)[0]
    corpo = re.sub(r"^# .*$", "", corpo, flags=re.M)
    corpo = re.sub(r"^> \[!.*$", "", corpo, flags=re.M)
    corpo = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), corpo)
    return corpo.strip() or None


# ------------------------------------------------------------------ índice

def reindexar():
    """Regera o Índice da Biblioteca e o mapa de cada área a partir das notas."""
    r = raiz()
    if not r.exists():
        return 0
    areas = {}
    for arq in r.rglob("*.md"):
        if arq.parent == r:
            continue
        meta, corpo = cofre._ler(arq)
        if meta.get("tipo") == "mapa":
            continue
        resumo = next((l.strip("> ").strip() for l in corpo.splitlines()
                       if l.startswith("> ") and not l.startswith("> [!")), "")
        areas.setdefault(arq.parent.name, []).append((arq.stem, resumo))
    for area, notas in areas.items():
        linhas = "\n".join(f"- [[{t}]]" + (f" — {r_}" if r_ else "") for t, r_ in sorted(notas))
        cofre._escrever(r / area / f"{area}.md",
                        {"tipo": "mapa", "tags": ["ultron/biblioteca", "ultron/mapa"],
                         "total": len(notas)},
                        f"# {area}\n\nMapa da área. Volta para [[{INDICE}]].\n\n{linhas}\n")
    total = sum(len(v) for v in areas.values())
    blocos = "\n".join(f"- [[{a}]] ({len(v)} notas)" for a, v in sorted(areas.items()))
    cofre._escrever(r / f"{INDICE}.md",
                    {"tipo": "mapa", "tags": ["ultron/biblioteca", "ultron/mapa"], "total": total,
                     "aliases": ["Biblioteca", "Índice"]},
                    f"# {INDICE}\n\n> [!quote] Ultron\n> Li a internet inteira em minutos. Isto é o "
                    f"que valeu a pena guardar.\n\nO saber do [[Ultron]], ligado por áreas. Cada nota "
                    f"aponta para as vizinhas; o Ultron puxa as seções relevantes sozinho a cada "
                    f"pedido. Personalidade: [[Persona]] · [[História]] · [[Ultron no MCU]].\n\n"
                    f"## Áreas\n{blocos}\n\n## Para criar notas novas\nCrie em `Biblioteca/<Área>/`, "
                    f"com um resumo em `> ` logo abaixo do título, seções `## ` e `[[links]]` para "
                    f"notas vizinhas. O índice se atualiza quando o Ultron abre.\n")
    return total
