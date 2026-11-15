"""Ferramentas de ATLAS (busca universal), ARCHIVE (arquivos) e SCRIBE (documentação).

O Archive nunca move, renomeia ou apaga por ferramenta: só sugere. Quem aplica é o
Davi, na janela de módulos. Recuperar uma versão antiga cria uma cópia (N2).
"""
from pathlib import Path

from core import guardian
from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import archive, atlas, scribe


@ferramenta(
    "atlas_buscar",
    "Busca universal em tudo o que o Ultron conhece: documentos autorizados, memórias, histórico "
    "de conversas, atividades (Chronos) e o catálogo de arquivos. Cada resultado diz a origem. "
    "periodo como no Chronos ('semana passada', 'últimos 30 dias'...). fontes: documentos, "
    "memorias, conversas, atividades, arquivos.",
    {"type": "object", "properties": {
        "consulta": {"type": "string"}, "projeto": {"type": "string"}, "periodo": {"type": "string"},
        "fontes": {"type": "array", "items": {"type": "string"}}},
     "required": ["consulta"]})
def atlas_buscar(consulta, projeto=None, periodo=None, fontes=None):
    res = atlas.buscar(consulta, projeto, periodo, fontes)
    if not res:
        return ("Nada encontrado nas fontes do Atlas. Serviços MCP não são pesquisados aqui; "
                "use usar_plugin se a informação estiver num deles.")
    return NAO_CONFIAVEL + "\n\n".join(f"[{i}] ({r['fonte']}) {r['titulo']} — {r['origem']}\n{r['texto'][:400]}"
                                       for i, r in enumerate(res, 1))


@ferramenta(
    "catalogar_diretorio",
    "Cataloga os arquivos de uma pasta autorizada no Guardian (nome, tipo, tamanho, data, "
    "duplicatas). Só lê. Devolve o resumo por tipo.",
    {"type": "object", "properties": {"diretorio": {"type": "string"}}, "required": ["diretorio"]})
def catalogar_diretorio(diretorio):
    r = archive.catalogar(diretorio)
    linhas = [f"{r['arquivos']} arquivos catalogados em {r['raiz']} ({r['removidos']} sumiram desde a última vez)."]
    for x in archive.resumo(r["raiz"]):
        linhas.append(f"- {x['categoria']}: {x['n']} ({(x['bytes'] or 0) / 1048576:.1f} MB)")
    dup = archive.duplicatas(r["raiz"], 5)
    if dup:
        linhas.append(f"Duplicatas: {len(dup)} grupos, {sum(d['desperdicio'] for d in dup) / 1048576:.1f} MB repetidos.")
    return "\n".join(linhas)


@ferramenta(
    "buscar_arquivos",
    "Procura arquivos catalogados pelo nome (e opcionalmente pelo tipo: documento, imagem, video, "
    "audio, codigo, planilha, compactado, instalador...). Para conteúdo, use buscar_documentos.",
    {"type": "object", "properties": {"nome": {"type": "string"}, "tipo": {"type": "string"}},
     "required": ["nome"]})
def buscar_arquivos(nome, tipo=None):
    res = archive.buscar(nome, tipo, limite=25)
    if not res:
        return "Nenhum arquivo catalogado com esse nome (catalogue a pasta primeiro)."
    return "\n".join(f"- {r['caminho']} ({r['categoria']}, {r['tamanho'] // 1024} KB, {r['mtime_iso'][:10]})" for r in res)


@ferramenta("encontrar_duplicatas",
            "Lista arquivos com conteúdo idêntico (mesmo SHA-256) nas pastas catalogadas. Só lê.",
            {"type": "object", "properties": {"diretorio": {"type": "string"}}})
def encontrar_duplicatas(diretorio=None):
    raiz = str(Path(diretorio).expanduser().resolve()) if diretorio else None
    grupos = archive.duplicatas(raiz, 15)
    if not grupos:
        return "Nenhuma duplicata encontrada."
    return "\n".join(f"- {g['copias']} cópias, {g['tamanho'] / 1048576:.1f} MB cada: " + " | ".join(g["caminhos"][:4])
                     for g in grupos)


@ferramenta(
    "sugerir_organizacao_arquivos",
    "Monta um plano para organizar os arquivos soltos de uma pasta autorizada em subpastas por tipo. "
    "NÃO move nada: o Davi revisa e aplica (ou descarta) na janela de módulos.",
    {"type": "object", "properties": {"diretorio": {"type": "string"}}, "required": ["diretorio"]})
def sugerir_organizacao_arquivos(diretorio):
    archive.catalogar(diretorio)
    sid = archive.sugerir_organizacao(diretorio)
    if not sid:
        return "Nada a organizar: não há arquivos soltos de tipos conhecidos."
    s = next(x for x in archive.sugestoes() if x["id"] == sid)
    return f"Sugestão #{sid}: {s['motivo']}. Aguardando o Davi aplicar na janela de módulos (ARCHIVE)."


@ferramenta("versoes_arquivo",
            "Lista as versões de um arquivo que está num repositório git (commit, data, autor, mensagem).",
            {"type": "object", "properties": {"caminho": {"type": "string"}}, "required": ["caminho"]})
def versoes_arquivo(caminho):
    v = archive.versoes(caminho)
    return "\n".join(f"- {x['commit']} {x['data']} {x['autor']}: {x['mensagem']}" for x in v) or \
        "Sem histórico (o arquivo não está num repositório git)."


@ferramenta(
    "recuperar_versao_arquivo",
    "Recupera uma versão antiga (commit) de um arquivo versionado como CÓPIA ao lado do original "
    "(<nome>.versao-<commit>). O arquivo atual não é alterado.",
    {"type": "object", "properties": {"caminho": {"type": "string"}, "commit": {"type": "string"}},
     "required": ["caminho", "commit"]},
    nivel="N2", resumo=lambda a: f"recuperar {a.get('caminho')} na versão {a.get('commit')} como cópia")
def recuperar_versao_arquivo(caminho, commit):
    return f"Versão salva em {archive.recuperar_versao(caminho, commit)}."


@ferramenta(
    "registrar_decisao",
    "Registra uma decisão (formato ADR: contexto, decisão, alternativas, consequências) como nota "
    "no Obsidian (Scribe/Decisões) e como memória de decisão no NEURALINK.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"}, "contexto": {"type": "string"}, "decisao": {"type": "string"},
        "alternativas": {"type": "string"}, "consequencias": {"type": "string"}, "projeto": {"type": "string"}},
     "required": ["titulo", "contexto", "decisao"]})
def registrar_decisao(titulo, contexto, decisao, alternativas="", consequencias="", projeto=None):
    arq = scribe.registrar_decisao(titulo, contexto, decisao, alternativas, consequencias, projeto)
    return f"Decisão registrada em {arq.name} (Scribe/Decisões)."


@ferramenta(
    "criar_nota",
    "Cria (ou atualiza, guardando a versão anterior) uma nota do Ultron no Obsidian, em Scribe/Notas.",
    {"type": "object", "properties": {"titulo": {"type": "string"}, "conteudo": {"type": "string"},
                                      "projeto": {"type": "string"}}, "required": ["titulo", "conteudo"]})
def criar_nota(titulo, conteudo, projeto=None):
    return f"Nota salva: {scribe.criar_nota(titulo, conteudo, projeto).name}."


@ferramenta(
    "resumir_reuniao",
    "Resume uma reunião a partir da transcrição (texto colado ou arquivo de texto autorizado): "
    "decisões, ações e pendências, numa nota em Scribe/Reuniões. A transcrição não é guardada.",
    {"type": "object", "properties": {
        "titulo": {"type": "string"}, "transcricao": {"type": "string"},
        "arquivo": {"type": "string"}, "participantes": {"type": "string"}, "projeto": {"type": "string"}},
     "required": ["titulo"]})
def resumir_reuniao(titulo, transcricao=None, arquivo=None, participantes="", projeto=None):
    if arquivo:
        if guardian.autorizar_caminho(arquivo)["decisao"] == "negar":
            return "Esse arquivo está fora dos diretórios autorizados."
        transcricao = Path(arquivo).expanduser().read_text(encoding="utf-8", errors="replace")
    if not transcricao:
        return "Preciso da transcrição (texto ou arquivo)."
    arq = scribe.resumir_reuniao(titulo, transcricao, projeto, participantes)
    return f"Resumo salvo em Scribe/Reuniões/{arq.name}."


@ferramenta(
    "gerar_changelog",
    "Atualiza o changelog de um repositório git autorizado (Scribe/Changelogs), só com os commits "
    "novos desde a última vez, mantendo os hashes como referência.",
    {"type": "object", "properties": {"repositorio": {"type": "string"}, "projeto": {"type": "string"},
                                      "desde": {"type": "string"}}, "required": ["repositorio"]})
def gerar_changelog(repositorio, projeto=None, desde=None):
    arq, n = scribe.changelog(repositorio, projeto, desde)
    return f"{n} commits novos no {arq.name}." if n else "Nenhum commit novo desde o último changelog."


@ferramenta(
    "gerar_relatorio",
    "Gera um relatório de atividades (geral ou de um projeto) num período, a partir do Chronos, "
    "como nota em Scribe/Relatórios.",
    {"type": "object", "properties": {"projeto": {"type": "string"},
                                      "periodo": {"type": "string", "default": "esta semana"}}})
def gerar_relatorio(projeto=None, periodo="esta semana"):
    arq = scribe.relatorio(projeto, periodo)
    return f"Relatório salvo: Scribe/Relatórios/{arq.name}."


@ferramenta(
    "documentar_projeto",
    "Gera ou atualiza a documentação viva de um projeto (resumo, decisões e documentos de origem) "
    "em Scribe/Projetos, guardando a versão anterior.",
    {"type": "object", "properties": {"projeto": {"type": "string"}}, "required": ["projeto"]})
def documentar_projeto(projeto):
    return f"Documentação atualizada: Scribe/Projetos/{scribe.documentar_projeto(projeto).name}."
