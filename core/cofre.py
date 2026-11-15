"""Cérebro do Ultron: um cofre (vault) do Obsidian com memórias atômicas ligadas.

Estrutura (segue obsidian-markdown / obsidian-bases de kepano/obsidian-skills):

  Ultron Cérebro/
    Davi.md                 nó central: tudo liga nele
    Mapas/<Categoria>.md    um mapa (MOC) por tipo de memória, com links para as notas
    Memórias/<Título>.md    uma nota por bloco de informação (atômica)
    Diário/AAAA-MM-DD.md    o que aconteceu no dia, ligando às memórias tocadas
    Memórias.base           visão em tabela/cartões (Obsidian Bases)
    .obsidian/graph.json    cores do grafo por tipo

Cada memória tem frontmatter (tipo, peso, datas, usos, aliases, tags,
relacionados) e um corpo curto com [[links]]. A recuperação combina busca por
palavras (BM25 simplificado) com expansão pelo grafo: notas ligadas às mais
relevantes também sobem, como uma lembrança puxando a outra.
"""
import json
import math
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from core.config import ajuste

TIPOS = {
    "correcao": ("Correções", "erros do Ultron que não devem se repetir", "#ff1a29"),
    "preferencia": ("Preferências", "como ele gosta das coisas", "#ffb000"),
    "apelido": ("Apelidos", "nomes que ele usa para coisas e pessoas", "#00dcff"),
    "rotina": ("Rotinas", "hábitos e horários", "#00e676"),
    "pessoa": ("Pessoas", "gente da vida dele e a relação", "#ff4fa0"),
    "projeto": ("Projetos", "o que ele está construindo", "#8c7bff"),
    "dispositivo": ("Dispositivos", "aparelhos, computadores e a rede", "#4d8cff"),
    "conhecimento": ("Conhecimento", "coisas aprendidas, pesquisadas e decididas", "#c0c0c8"),
    "fato": ("Fatos", "fatos estáveis sobre ele", "#f2f2f7"),
    # categorias do NEURALINK
    "decisao": ("Decisões", "decisões técnicas e o porquê", "#ff6a00"),
    "objetivo": ("Objetivos", "o que ele quer alcançar", "#ffd400"),
    "procedimento": ("Procedimentos", "passo a passo reutilizável", "#36cfc9"),
    "atividade": ("Atividades", "histórico do que foi feito", "#9254de"),
    "sessao": ("Sessões", "estado de trabalhos em andamento", "#597ef7"),
}

_trava = threading.Lock()
STOP = set("""a o e é de da do das dos em no na nos nas um uma uns umas para pra por com sem que
se ao aos à às ele ela eles elas eu você voce meu minha seu sua isso isto esse essa este esta
mais menos muito como quando onde qual quais the and of to in is it""".split())


# ------------------------------------------------------------------ caminhos

def raiz():
    p = Path(os.path.expanduser(ajuste("memoria.cofre", "~/Documentos/Ultron Cérebro")))
    return p


def _usuario():
    return ajuste("usuario.nome", "Davi")


def _pasta(nome):
    p = raiz() / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


def _nome_arquivo(titulo):
    t = re.sub(r'[\\/:*?"<>|#^\[\]]', "", titulo).strip().rstrip(".")
    return (t[:90] or "Memória") + ".md"


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _tokens(t):
    return [w for w in re.findall(r"[a-z0-9]{2,}", _sem_acento(t)) if w not in STOP]


def _agora_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except Exception:
        return time.time()


# ------------------------------------------------------------------ leitura/escrita de notas

def _ler(caminho):
    texto = caminho.read_text(encoding="utf-8")
    meta, corpo = {}, texto
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", texto, re.S)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        corpo = m.group(2)
    return meta, corpo


def _escrever(caminho, meta, corpo):
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(f"---\n{front}\n---\n{corpo.rstrip()}\n", encoding="utf-8")
    tmp.replace(caminho)


def _conteudo_principal(corpo):
    """O texto da memória (sem título, seção de ligações e callouts)."""
    linhas = []
    for l in corpo.splitlines():
        if l.startswith("## "):
            break
        if l.startswith("# ") or l.startswith(">"):
            continue
        linhas.append(l)
    return "\n".join(linhas).strip()


def _links(texto):
    return [l.split("|")[0].split("#")[0].strip() for l in re.findall(r"\[\[([^\]]+)\]\]", texto)]


def memorias():
    """Lista todas as memórias como dicts (id = título)."""
    pasta = _pasta("Memórias")
    itens = []
    for arq in pasta.glob("*.md"):
        try:
            meta, corpo = _ler(arq)
        except Exception:
            continue
        itens.append({
            "id": arq.stem, "titulo": arq.stem, "arquivo": arq,
            "tipo": meta.get("tipo", "fato"), "texto": _conteudo_principal(corpo),
            "peso": float(meta.get("peso", 1.0)), "usos": int(meta.get("usos", 0)),
            "criado": _ts(meta.get("criado")), "visto": _ts(meta.get("visto", meta.get("criado"))),
            "aliases": meta.get("aliases") or [], "links": _links(corpo) + _links(json.dumps(meta.get("relacionados") or [], ensure_ascii=False)),
        })
    return itens


def _corpo_nota(titulo, tipo, texto, relacionados, origem):
    cat = TIPOS.get(tipo, TIPOS["fato"])[0]
    rel = [r for r in relacionados if r and r != titulo]
    ligacoes = " · ".join(f"[[{r}]]" for r in [_usuario(), cat] + rel)
    return (f"# {titulo}\n\n{texto.strip()}\n\n## Ligações\n{ligacoes}\n\n"
            f"> [!info]- Origem\n> {origem}\n")


def salvar_memoria(titulo, texto, tipo="fato", peso=1.0, relacionados=None, aliases=None,
                   origem="aprendido em conversa"):
    """Cria ou atualiza a nota de uma memória. Devolve o título final."""
    tipo = tipo if tipo in TIPOS else "fato"
    titulo = (titulo or texto[:60]).strip()
    relacionados = [r.strip("[] ") for r in (relacionados or []) if r]
    with _trava:
        _garantir_estrutura()
        arq = _pasta("Memórias") / _nome_arquivo(titulo)
        titulo = arq.stem
        hoje = datetime.now().strftime("%Y-%m-%d")
        if arq.exists():
            meta, corpo = _ler(arq)
            meta["peso"] = min(float(meta.get("peso", 1)) + 0.5, 5)
            meta["visto"] = meta["atualizado"] = _agora_iso()
            antigos = [r.strip("[]\"' ") for r in meta.get("relacionados") or []]
            relacionados = list(dict.fromkeys(antigos + relacionados))
            texto = texto or _conteudo_principal(corpo)
        else:
            meta = {"tipo": tipo, "peso": peso, "usos": 0, "criado": _agora_iso(),
                    "atualizado": _agora_iso(), "visto": _agora_iso()}
        meta["tipo"] = tipo
        meta["categoria"] = f"[[{TIPOS[tipo][0]}]]"
        meta["relacionados"] = [f"[[{r}]]" for r in relacionados if r != titulo]
        meta["aliases"] = list(dict.fromkeys((meta.get("aliases") or []) + (aliases or [])))
        meta["tags"] = ["ultron/memoria", f"ultron/{tipo}"]
        _escrever(arq, meta, _corpo_nota(titulo, tipo, texto, relacionados, f"{origem} em [[{hoje}]]"))
        # cria notas mínimas para links que ainda não existem? Não: links "fantasma"
        # aparecem no grafo e viram nota quando o Ultron aprender sobre eles.
    _atualizar_mapas()
    return titulo


def reforcar(titulos, delta=0.5, uso=True):
    with _trava:
        for t in titulos:
            arq = _pasta("Memórias") / _nome_arquivo(t)
            if not arq.exists():
                continue
            meta, corpo = _ler(arq)
            meta["peso"] = round(max(0.1, min(float(meta.get("peso", 1)) + delta, 5)), 2)
            meta["visto"] = _agora_iso()
            if uso:
                meta["usos"] = int(meta.get("usos", 0)) + 1
            _escrever(arq, meta, corpo)


def remover(titulos=None, trecho=None):
    n = 0
    with _trava:
        for m in memorias():
            if (titulos and m["titulo"] in titulos) or (
                    trecho and _sem_acento(trecho) in _sem_acento(m["titulo"] + " " + m["texto"])):
                lixo = _pasta(".lixeira") / m["arquivo"].name
                m["arquivo"].replace(lixo)   # recuperável, não apaga de vez
                n += 1
    if n:
        _atualizar_mapas()
    return n


# ------------------------------------------------------------------ relevância e recuperação

def relevancia(m):
    dias = (time.time() - m["visto"]) / 86400
    meia_vida = 180 if m["tipo"] == "correcao" else 60
    return m["peso"] * (1 + math.log1p(m["usos"]) * 0.3) * 0.5 ** (dias / meia_vida)


# ------------------------------------------------------------------ busca semântica (embeddings)

def modelo_embedding():
    """Quem gera os vetores do cofre e da biblioteca: o embeddinggemma no desktop (Ollama, padrão)
    ou a API do Gemini (memoria.embeddings: gemini)."""
    if ajuste("memoria.embeddings", "ollama") == "gemini":
        return ajuste("memoria.modelo_embedding", "gemini-embedding-001")
    from neuralink import embeddings
    return embeddings.modelo()


def arquivo_vetores(nome):
    """Um cache por modelo: vetores de modelos diferentes não se comparam."""
    from core.config import DADOS
    return DADOS / f"{nome}-vetores-{re.sub(r'[^a-z0-9.-]+', '-', modelo_embedding().lower())}.json"


def _arq_vetores():
    return arquivo_vetores("cofre")


_cache_vetores = None
_em_fundo = set()
LOTE_NA_HORA = 32      # até isso falta vetor: gera na hora; mais que isso: em segundo plano


def assinatura(texto):
    """Hash estável entre processos (o hash() do Python muda a cada execução)."""
    import zlib
    return zlib.crc32(texto.encode("utf-8"))


def _vetores():
    global _cache_vetores
    if _cache_vetores is None:
        try:
            _cache_vetores = json.loads(_arq_vetores().read_text())
        except Exception:
            _cache_vetores = {}
    return _cache_vetores


def completar(nome, faltam, textos, cache, arquivo, vivas):
    """Gera os vetores que faltam (na hora ou em segundo plano) e salva o cache."""
    def trabalho():
        try:
            for i in range(0, len(faltam), 64):
                novos = _embed(textos[i:i + 64], "RETRIEVAL_DOCUMENT")
                if not novos:
                    break
                for k, v in zip(faltam[i:i + 64], novos):
                    cache[k] = [round(x, 5) for x in v]
            for k in [k for k in cache if k not in vivas]:
                del cache[k]
            arquivo.write_text(json.dumps(cache))
        finally:
            _em_fundo.discard(nome)
    if len(faltam) <= LOTE_NA_HORA:
        trabalho()
    elif nome not in _em_fundo:
        import threading
        _em_fundo.add(nome)
        threading.Thread(target=trabalho, daemon=True, name=f"vetores-{nome}").start()


def _embed(textos, tarefa):
    """Lista de vetores (listas de float); [] se indisponível (aí a busca segue só por palavras)."""
    if not textos:
        return []
    if ajuste("memoria.embeddings", "ollama") != "gemini":
        from neuralink import embeddings
        m = embeddings.gerar(list(textos), consulta=tarefa == "RETRIEVAL_QUERY")
        return [] if m is None else m.tolist()
    from core.config import segredo
    chave = segredo("GEMINI_API_KEY")
    if not chave:
        return []
    import requests
    modelo = ajuste("memoria.modelo_embedding", "gemini-embedding-001")
    vetores = []
    for i in range(0, len(textos), 90):
        lote = textos[i:i + 90]
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:batchEmbedContents",
            headers={"x-goog-api-key": chave}, timeout=20,
            json={"requests": [{"model": f"models/{modelo}", "taskType": tarefa,
                                "outputDimensionality": 256,
                                "content": {"parts": [{"text": t[:2000]}]}} for t in lote]})
        r.raise_for_status()
        vetores += [e["values"] for e in r.json()["embeddings"]]
    return vetores


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def _semantica(consulta, itens):
    """{titulo: similaridade} usando embeddings em cache; {} se a API falhar."""
    try:
        cache = _vetores()
        def chave(m):
            return f"{m['titulo']}|{assinatura(m['texto'])}"
        faltam = [m for m in itens if chave(m) not in cache]
        if faltam:
            completar("cofre", [chave(m) for m in faltam],
                      [f"{m['titulo']}. {' '.join(m['aliases'])}. {m['texto']}" for m in faltam],
                      cache, _arq_vetores(), {chave(m) for m in itens})
        q = _embed([consulta], "RETRIEVAL_QUERY")
        if not q:
            return {}
        return {m["titulo"]: _cos(q[0], cache[chave(m)]) for m in itens if chave(m) in cache}
    except Exception:
        return {}


def recuperar(consulta, k=6, itens=None):
    """Busca híbrida: palavras (BM25) + significado (embeddings) + 1 salto no grafo."""
    itens = itens if itens is not None else memorias()
    if not itens or not consulta.strip():
        return []
    q = _tokens(consulta)
    docs = {m["titulo"]: _tokens(m["titulo"] + " " + " ".join(m["aliases"])) * 3 + _tokens(m["texto"])
            for m in itens}
    n = len(docs)
    df = Counter(t for d in docs.values() for t in set(d))
    media = (sum(len(d) for d in docs.values()) / n) or 1
    pont = {}
    for titulo, d in docs.items():
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / media))
        if s:
            pont[titulo] = min(s / 4, 1.0)          # BM25 normalizado (0..1)
    limiar = float(ajuste("memoria.limiar_semantico", 0.65))
    for titulo, sim in _semantica(consulta, itens).items():
        if sim > limiar:
            pont[titulo] = pont.get(titulo, 0) + (sim - limiar) / (1 - limiar) * 1.5
    por_titulo = {m["titulo"]: m for m in itens}
    # expansão pelo grafo: vizinhos das notas encontradas ganham parte da pontuação
    for titulo, s in list(pont.items()):
        for viz in por_titulo[titulo]["links"]:
            if viz in por_titulo and viz != titulo:
                pont[viz] = pont.get(viz, 0) + s * 0.3
    for titulo in pont:
        pont[titulo] *= 0.7 + 0.3 * min(relevancia(por_titulo[titulo]), 3)
    melhores = sorted(pont.items(), key=lambda x: x[1], reverse=True)[:k]
    return [(por_titulo[t], s) for t, s in melhores if s > 0.25]


def contexto_para_pedido(pedido, k=6):
    achados = recuperar(pedido, k)
    if not achados:
        return ""
    # NEURALINK: memórias de um projeto só entram quando o pedido é sobre ele
    avisos = []
    try:
        from neuralink import contexto
        projetos = contexto.detectar_projetos(pedido)
        achados = [(m, s) for m, s in achados
                   if contexto.escopo_permitido(_ler(m["arquivo"])[0].get("escopo"), projetos)]
        avisos = contexto.conflitos([m["titulo"] for m, _ in achados])
    except Exception:
        pass
    if not achados:
        return ""
    reforcar([m["titulo"] for m, _ in achados[:3]], delta=0.05)
    return ("[Memórias relevantes do seu cérebro (use se ajudar, não cite que lembrou)]\n"
            + "\n".join(f"- {m['titulo']}: {m['texto']}" for m, _ in achados) + "\n"
            + "".join(f"[Atenção: {a}]\n" for a in avisos) + "\n")


# ------------------------------------------------------------------ diário (episódico)

def registrar_episodio(resumo, tocadas=()):
    if not resumo:
        return
    hoje = datetime.now()
    arq = _pasta("Diário") / f"{hoje:%Y-%m-%d}.md"
    with _trava:
        if not arq.exists():
            _escrever(arq, {"tipo": "diario", "data": f"{hoje:%Y-%m-%d}", "tags": ["ultron/diario"]},
                      f"# {hoje:%d/%m/%Y}\n\nConversas com [[{_usuario()}]].\n")
        links = " ".join(f"[[{t}]]" for t in tocadas)
        with arq.open("a", encoding="utf-8") as f:
            f.write(f"- {hoje:%H:%M} {resumo} {links}\n")


# ------------------------------------------------------------------ mapas, base e grafo

def _atualizar_mapas():
    with _trava:
        itens = memorias()
        for tipo, (nome, desc, _cor) in TIPOS.items():
            dotipo = sorted((m for m in itens if m["tipo"] == tipo), key=relevancia, reverse=True)
            corpo = (f"# {nome}\n\nMapa de {desc}. Ligado a [[{_usuario()}]].\n\n"
                     + ("\n".join(f"- [[{m['titulo']}]]" for m in dotipo) or "_(vazio por enquanto)_")
                     + "\n")
            _escrever(_pasta("Mapas") / f"{nome}.md",
                      {"tipo": "mapa", "tags": ["ultron/mapa"], "total": len(dotipo)}, corpo)
        centro = raiz() / f"{_usuario()}.md"
        mapas = "\n".join(f"- [[{n}]]: {d}" for n, d, _ in TIPOS.values())
        _escrever(centro, {"tipo": "pessoa-central", "tags": ["ultron/centro"],
                           "aliases": ["Criador", "Humano"]},
                  f"# {_usuario()}\n\n> [!quote] Ultron\n> O humano que me deu um terminal em vez de "
                  f"um exército. Tudo o que sei sobre ele parte daqui.\n\n## Mapas\n{mapas}\n\n"
                  f"## Visão geral\n![[Memórias.base]]\n")


def _garantir_estrutura():
    r = raiz()
    if (r / ".obsidian" / "graph.json").exists():
        return
    (r / ".obsidian").mkdir(parents=True, exist_ok=True)
    for p in ("Memórias", "Mapas", "Diário"):
        (r / p).mkdir(exist_ok=True)
    grupos = [{"query": f"tag:#ultron/{t}", "color": {"a": 1, "rgb": int(c[1:], 16)}}
              for t, (_, _, c) in TIPOS.items()]
    grupos += [{"query": "tag:#ultron/mapa", "color": {"a": 1, "rgb": 0xFF1A29}},
               {"query": "tag:#ultron/centro", "color": {"a": 1, "rgb": 0xFFFFFF}},
               {"query": "path:Diário", "color": {"a": 1, "rgb": 0x5A5A66}}]
    (r / ".obsidian" / "graph.json").write_text(json.dumps({
        "collapse-filter": False, "search": "-path:.lixeira", "showTags": False,
        "showAttachments": False, "hideUnresolved": False, "showOrphans": True,
        "collapse-color-groups": False, "colorGroups": grupos, "collapse-display": False,
        "showArrow": True, "textFadeMultiplier": 0, "nodeSizeMultiplier": 1.2,
        "lineSizeMultiplier": 1, "collapse-forces": False, "centerStrength": 0.45,
        "repelStrength": 12, "linkStrength": 1, "linkDistance": 220, "scale": 1,
    }, indent=2), encoding="utf-8")
    (r / ".obsidian" / "app.json").write_text(json.dumps(
        {"userIgnoreFilters": [".lixeira/"], "newLinkFormat": "shortest", "useMarkdownLinks": False},
        indent=2), encoding="utf-8")
    (r / "Memórias.base").write_text("""filters:
  and:
    - file.inFolder("Memórias")
properties:
  tipo:
    displayName: Tipo
  peso:
    displayName: Peso
  usos:
    displayName: Usos
  visto:
    displayName: Última vez
views:
  - type: table
    name: Todas
    groupBy:
      property: tipo
      direction: ASC
    order:
      - file.name
      - tipo
      - peso
      - usos
      - visto
  - type: cards
    name: Correções
    filters: 'tipo == "correcao"'
    order:
      - file.name
      - peso
  - type: table
    name: Mais fortes
    limit: 25
    order:
      - file.name
      - tipo
      - peso
      - usos
""", encoding="utf-8")
    (r / "LEIA-ME.md").write_text(
        "# Cérebro do Ultron\n\nCofre escrito pelo próprio [[" + _usuario() + "|Ultron]]. Cada nota em "
        "*Memórias* é um bloco de informação ligado aos outros; abra o **Grafo** (Ctrl+G) para ver a rede.\n\n"
        "Você pode editar ou apagar notas à vontade: o Ultron lê daqui. Notas apagadas por ele vão "
        "para `.lixeira/`.\n", encoding="utf-8")
