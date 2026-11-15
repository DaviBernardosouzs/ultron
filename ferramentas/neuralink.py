"""Ferramentas do NEURALINK para o orquestrador do Ultron.

Contrato proposto -> ferramenta:
  remember_information      lembrar_informacao
  search_memory             buscar_memoria
  retrieve_project_context  contexto_projeto
  search_documents          buscar_documentos
  list_knowledge_sources    listar_fontes_conhecimento
  get_related_entities      entidades_relacionadas
  summarize_project         resumir_projeto
  request_memory_update     pedir_atualizacao_memoria   (só cria sugestão para revisão)
  request_memory_deletion   pedir_exclusao_memoria      (só cria sugestão para revisão)
  get_recent_decisions      decisoes_recentes
Mais: autorizar_fonte_conhecimento (N2), sincronizar_conhecimento, salvar_conversa,
consolidar_memorias (só sugere).
"""
import json
import threading
from datetime import datetime

from core.config import DADOS, ajuste
from core.registro import NAO_CONFIAVEL, ferramenta
from neuralink import banco, busca, contexto, grafo, ingestao, memoria

CATS = ", ".join(memoria.CATEGORIAS)


@ferramenta(
    "lembrar_informacao",
    "Guarda uma memória estruturada no NEURALINK (nota no cofre do Obsidian). Use quando o Davi "
    "pedir para lembrar, registrar uma decisão técnica, um objetivo, um procedimento ou o estado "
    f"de um trabalho. categoria: {CATS}. escopo: 'global' ou o nome do projeto (isola o "
    "contexto). retencao: 'permanente', 'sessao' ou dias como '30d'.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"}, "conteudo": {"type": "string"},
        "categoria": {"type": "string", "default": "fato"},
        "escopo": {"type": "string", "default": "global"},
        "retencao": {"type": "string", "default": "permanente"}},
     "required": ["titulo", "conteudo"]})
def lembrar_informacao(titulo, conteudo, categoria="fato", escopo="global", retencao="permanente"):
    t = memoria.criar(titulo, conteudo, categoria, escopo, retencao=retencao, origem="usuario")
    return f"Memória '{t}' guardada ({categoria}, escopo {escopo}, retenção {retencao})."


@ferramenta(
    "buscar_memoria",
    "Procura nas memórias persistentes (preferências, decisões, projetos, procedimentos...). "
    "Devolve título, categoria, escopo, confiabilidade e datas de cada uma.",
    {"type": "object", "properties": {
        "consulta": {"type": "string"}, "categoria": {"type": "string"},
        "projeto": {"type": "string", "description": "limita ao escopo do projeto (e às globais)"}},
     "required": ["consulta"]})
def buscar_memoria(consulta, categoria=None, projeto=None):
    raiz = str(__import__("core.cofre", fromlist=["raiz"]).raiz().resolve()) + "/Memórias/"
    achados = busca.buscar(consulta, k=8, projetos=[projeto] if projeto else None, isolar=bool(projeto),
                           categoria=categoria)
    achados = [r for r in achados if r["caminho"].startswith(raiz)]
    if not achados:   # nada no índice: cai para a busca textual direta nas notas
        lista = memoria.listar(categoria=categoria, texto=consulta)[:8]
        if not lista:
            return "Nenhuma memória encontrada sobre isso."
        return "\n".join(f"- {m['titulo']} [{m['categoria']}, {m['escopo']}, conf. {m['confiabilidade']}]: "
                         f"{m['conteudo'][:300]}" for m in lista)
    por_titulo = {m["titulo"]: m for m in memoria.listar()}
    linhas = []
    for r in achados:
        m = por_titulo.get(r["titulo"]) or {}
        if projeto and not contexto.escopo_permitido(m.get("escopo"), [projeto]):
            continue
        linhas.append(f"- {r['titulo']} [{m.get('categoria', r['categoria'])}, escopo {m.get('escopo', 'global')}, "
                      f"conf. {m.get('confiabilidade', '?')}, atualizada {str(m.get('atualizado', ''))[:10]}]: "
                      f"{(m.get('conteudo') or r['texto'])[:300]}")
    avisos = contexto.conflitos([r["titulo"] for r in achados])
    return "\n".join(linhas + [f"Atenção: {a}" for a in avisos]) or "Nenhuma memória encontrada sobre isso."


@ferramenta(
    "buscar_documentos",
    "Busca universal nos documentos autorizados (Obsidian, pastas, PDFs, repositórios, páginas "
    "salvas), por palavras e por significado. Cada resultado traz a fonte e a linha. Filtros "
    "opcionais: projeto, tipo (markdown, pdf, codigo, texto, web, conversa), fonte, desde "
    "(AAAA-MM-DD).",
    {"type": "object", "properties": {
        "consulta": {"type": "string"}, "projeto": {"type": "string"}, "tipo": {"type": "string"},
        "fonte": {"type": "string"}, "desde": {"type": "string"},
        "quantidade": {"type": "integer", "default": 6}},
     "required": ["consulta"]})
def buscar_documentos(consulta, projeto=None, tipo=None, fonte=None, desde=None, quantidade=6):
    achados = busca.buscar(consulta, k=min(int(quantidade), 15), projetos=[projeto] if projeto else None,
                           isolar=False, tipo=tipo, fonte=fonte, desde=desde)
    if not achados:
        return ("Nada encontrado nas fontes autorizadas. Se a informação existir em outro lugar, "
                "a fonte precisa ser autorizada primeiro.")
    return NAO_CONFIAVEL + "\n\n".join(
        f"[{i}] {r['citacao']} · {r['encontrado_por']}\n{r['texto'][:700]}" for i, r in enumerate(achados, 1))


@ferramenta(
    "consultar_livros",
    "Consulta os LIVROS e textos de referência do Ultron (física, relatividade, cálculo, programação, IA, "
    "sociologia, estratégia militar, armas, aviação, culturas brasileira/alemã/francesa/italiana, xadrez). "
    "Devolve trechos reais com obra, autor, seção e licença. Muitos livros estão em inglês: a busca por "
    "significado acha em qualquer idioma; responda em português e cite a obra. Filtro opcional: area.",
    {"type": "object", "properties": {"consulta": {"type": "string"}, "area": {"type": "string"},
                                      "quantidade": {"type": "integer", "default": 5}},
     "required": ["consulta"]})
def consultar_livros(consulta, area=None, quantidade=5):
    k = min(int(quantidade), 10)
    achados = busca.buscar(consulta + (f" {area}" if area else ""), k=k * (3 if area else 1), categoria="livro", por_documento=1)
    if area:
        a = area.lower()
        achados = [r for r in achados if a in r["caminho"].lower()] or achados
    achados = achados[:k]
    if not achados:
        return ("Nada nos livros importados sobre isso. A lista de obras está em conhecimento/catalogo.yaml; "
                "para incluir outra, ela precisa ter licença aberta ou ser de domínio público.")
    c = banco.conexao()
    saida = []
    for i, r in enumerate(achados, 1):
        meta = json.loads(c.execute("SELECT propriedades FROM documentos WHERE id=?", (r["doc_id"],)).fetchone()[0] or "{}")
        saida.append(f"[{i}] {meta.get('obra', r['titulo'])} — {meta.get('autor', '?')} · {meta.get('secao', r['secao'] or '')} "
                     f"({meta.get('area', '')}; {meta.get('licenca', '')}) · {r['encontrado_por']}\n{r['texto'][:900]}")
    return NAO_CONFIAVEL + "\n\n".join(saida)


@ferramenta("listar_fontes_conhecimento",
            "Lista as fontes de conhecimento autorizadas no NEURALINK, quantos documentos cada uma "
            "tem, a última sincronização e erros.")
def listar_fontes_conhecimento():
    fs = ingestao.fontes()
    if not fs:
        return "Nenhuma fonte autorizada."
    return "\n".join(f"#{f['id']} {f['nome']} [{f['tipo']}{', projeto ' + f['projeto'] if f['projeto'] else ''}]: "
                     f"{f['documentos']} documentos, sincronizado {f['sincronizado'] or 'nunca'}"
                     + (f", ERRO: {f['erro']}" if f["erro"] else "") for f in fs) + \
        f"\nTrechos sem vetor: {ingestao.pendentes_vetor()}."


@ferramenta(
    "autorizar_fonte_conhecimento",
    "Autoriza o NEURALINK a ler e indexar uma pasta, arquivo, vault do Obsidian ou URL indicada "
    "pelo Davi, opcionalmente ligada a um projeto. Nunca autorize pastas que ele não pediu.",
    {"type": "object", "properties": {
        "caminho": {"type": "string", "description": "pasta, arquivo ou URL"},
        "projeto": {"type": "string"}, "nome": {"type": "string"}},
     "required": ["caminho"]},
    nivel="N2", resumo=lambda a: f"autorizar o NEURALINK a ler {a.get('caminho')}")
def autorizar_fonte_conhecimento(caminho, projeto=None, nome=None):
    fid = ingestao.adicionar_fonte(caminho, nome, projeto)
    threading.Thread(target=ingestao.sincronizar, args=(fid,), daemon=True).start()
    return f"Fonte #{fid} autorizada; a indexação está rodando em segundo plano."


@ferramenta("sincronizar_conhecimento",
            "Atualiza o índice do NEURALINK (só arquivos alterados) e gera os vetores pendentes.")
def sincronizar_conhecimento():
    return "\n".join(ingestao.sincronizar()) or "Nada para sincronizar."


@ferramenta(
    "contexto_projeto",
    "Recupera o contexto documentado de um projeto para continuar o trabalho: documentos, "
    "tecnologias, decisões, memórias do escopo e eventos recentes. Também marca o projeto como "
    "ativo (o contexto dele passa a entrar nos pedidos).",
    {"type": "object", "properties": {"projeto": {"type": "string"}}, "required": ["projeto"]})
def contexto_projeto(projeto):
    nomes = contexto.projetos_conhecidos()
    alvo = next((n for n in nomes if n.lower() == projeto.lower()), None) or \
        next((n for n in nomes if projeto.lower() in n.lower()), None)
    if not alvo:
        return f"Não conheço o projeto '{projeto}'. Projetos: {', '.join(nomes) or 'nenhum'}."
    contexto.projeto_ativo(alvo)
    c = banco.conexao()
    docs = c.execute("SELECT COUNT(*) FROM documentos WHERE projeto=?", (alvo,)).fetchone()[0]
    ent = grafo.achar(alvo, "projeto")
    tecs, decs = [], []
    if ent:
        nos, arestas = grafo.relacionadas(ent[0]["id"])
        tecs = sorted(nos[a["destino"]]["nome"] for a in arestas if a["tipo"] == "usa")
    mems = [m for m in memoria.listar() if m["escopo"] == alvo]
    decs = [m for m in mems if m["categoria"] == "decisao"]
    sessao = [m for m in mems if m["categoria"] in ("sessao", "objetivo")]
    eventos = c.execute("SELECT quando, titulo FROM eventos WHERE projeto=? ORDER BY quando DESC LIMIT 6",
                        (alvo,)).fetchall()
    resumo = c.execute("SELECT texto FROM trechos t JOIN documentos d ON d.id=t.doc_id WHERE d.categoria='resumo' "
                       "AND d.projeto=? ORDER BY d.indexado DESC LIMIT 1", (alvo,)).fetchone()
    partes = [f"Projeto {alvo} (agora ativo): {docs} documentos indexados."]
    if tecs:
        partes.append("Tecnologias: " + ", ".join(tecs[:25]) + ".")
    if resumo:
        partes.append("Último resumo: " + resumo[0][:800])
    if sessao:
        partes.append("Estado/objetivos: " + " | ".join(f"{m['titulo']}: {m['conteudo'][:200]}" for m in sessao[:5]))
    if decs:
        partes.append("Decisões: " + " | ".join(f"{m['titulo']}: {m['conteudo'][:200]}" for m in decs[:6]))
    if eventos:
        partes.append("Recentes: " + "; ".join(f"{e['quando'][:16]} {e['titulo']}" for e in eventos))
    if not (tecs or resumo or sessao or decs):
        partes.append("Não há decisões nem estado registrados para ele ainda; o que existir está só nos documentos.")
    return NAO_CONFIAVEL + "\n".join(partes)


@ferramenta(
    "entidades_relacionadas",
    "Consulta o grafo de conhecimento: o que está ligado a uma entidade (projeto, nota, "
    "tecnologia, decisão, ferramenta, capacidade...), com o documento de origem de cada ligação.",
    {"type": "object", "properties": {"nome": {"type": "string"}, "tipo": {"type": "string"}},
     "required": ["nome"]})
def entidades_relacionadas(nome, tipo=None):
    achadas = grafo.achar(nome, tipo)
    if not achadas:
        return f"Nenhuma entidade com '{nome}' no grafo."
    e = achadas[0]
    nos, arestas = grafo.relacionadas(e["id"])
    linhas = [f"{e['nome']} ({e['tipo']})" + (f": {e['descricao'][:160]}" if e["descricao"] else "")]
    for a in arestas[:40]:
        o, d = nos.get(a["origem"], {}), nos.get(a["destino"], {})
        linhas.append(f"- {o.get('nome')} ({o.get('tipo')}) -{a['tipo']}-> {d.get('nome')} ({d.get('tipo')})"
                      + (f"  [fonte: {a['doc']}]" if a["doc"] else ""))
    if len(achadas) > 1:
        linhas.append("Outras com nome parecido: " + ", ".join(f"{x['nome']} ({x['tipo']})" for x in achadas[1:6]))
    return "\n".join(linhas)


@ferramenta(
    "decisoes_recentes",
    "Lista as decisões técnicas registradas (memórias de categoria decisao), opcionalmente de um projeto.",
    {"type": "object", "properties": {"projeto": {"type": "string"}, "quantidade": {"type": "integer", "default": 8}}})
def decisoes_recentes(projeto=None, quantidade=8):
    decs = memoria.listar(categoria="decisao", escopo=projeto)
    if not decs:
        return "Nenhuma decisão registrada" + (f" para {projeto}." if projeto else ".")
    return "\n".join(f"- {d['atualizado'][:10]} {d['titulo']} [{d['escopo']}]: {d['conteudo'][:300]}"
                     for d in decs[:int(quantidade)])


@ferramenta(
    "pedir_atualizacao_memoria",
    "Propõe corrigir uma memória que está errada ou desatualizada. NÃO altera nada: cria uma "
    "sugestão que o Davi revisa na janela NEURALINK.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"}, "conteudo_novo": {"type": "string"}, "motivo": {"type": "string"}},
     "required": ["titulo", "conteudo_novo", "motivo"]})
def pedir_atualizacao_memoria(titulo, conteudo_novo, motivo):
    if not any(m["titulo"] == titulo for m in memoria.listar()):
        return f"Não existe memória '{titulo}'."
    sid = memoria.sugerir("correcao", [titulo], motivo, {"conteudo": conteudo_novo})
    return f"Sugestão #{sid} criada; o Davi aprova na janela NEURALINK."


@ferramenta(
    "pedir_exclusao_memoria",
    "Propõe apagar uma memória. NÃO apaga: cria uma sugestão para o Davi revisar.",
    {"type": "object", "properties": {"titulo": {"type": "string"}, "motivo": {"type": "string"}},
     "required": ["titulo", "motivo"]})
def pedir_exclusao_memoria(titulo, motivo):
    if not any(m["titulo"] == titulo for m in memoria.listar()):
        return f"Não existe memória '{titulo}'."
    sid = memoria.sugerir("exclusao", [titulo], motivo)
    return f"Sugestão #{sid} criada; o Davi aprova na janela NEURALINK."


@ferramenta("consolidar_memorias",
            "Procura memórias duplicadas, contraditórias ou desatualizadas e cria sugestões para o "
            "Davi revisar (não altera nada).")
def consolidar_memorias():
    ids = memoria.consolidar()
    return f"{len(ids)} sugestões de consolidação pendentes de revisão." if ids else "Nada a consolidar."


@ferramenta(
    "salvar_conversa",
    "Salva as últimas trocas desta conversa no NEURALINK como documento pesquisável, quando o "
    "Davi pedir para guardar a conversa.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"}, "trocas": {"type": "integer", "default": 10},
        "projeto": {"type": "string"}}, "required": ["titulo"]})
def salvar_conversa(titulo, trocas=10, projeto=None):
    linhas = []
    try:
        for l in (DADOS / "auditoria.log").read_text(encoding="utf-8").splitlines()[-2000:]:
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("evento") in ("pedido", "resposta"):
                linhas.append(("Davi: " if e["evento"] == "pedido" else "Ultron: ") + e.get("texto", ""))
    except FileNotFoundError:
        pass
    linhas = linhas[-int(trocas) * 2:]
    if not linhas:
        return "Não achei trocas recentes para salvar."
    ingestao.salvar_conversa(titulo, "\n\n".join(linhas), projeto)
    return f"Conversa '{titulo}' salva com {len(linhas)} falas."


@ferramenta(
    "resumir_projeto",
    "Gera ou atualiza o resumo progressivo de um projeto a partir dos documentos e do resumo "
    "anterior. O resumo vira uma nota nova (Resumos/<projeto>.md); os documentos originais não "
    "são alterados.",
    {"type": "object", "properties": {"projeto": {"type": "string"}}, "required": ["projeto"]})
def resumir_projeto(projeto):
    from neuralink import resumos
    return resumos.resumir(projeto)


# Mantém o índice atualizado em segundo plano (só um processo do Ultron faz isso).
from neuralink import servico as _servico   # noqa: E402
_servico.iniciar()
