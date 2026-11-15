"""Ferramentas dos WORKSPACES e do SENTINEL."""
from core import eventos, workspaces
from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import sentinel


@ferramenta(
    "criar_workspace",
    "Cria (ou atualiza) um WorkSpace: ambiente com projeto, diretório, grupos de ferramentas, skills e "
    "plugins MCP. tipo: desenvolvimento, pesquisa, estudo, pessoal ou outro (define as ferramentas padrão).",
    {"type": "object", "properties": {
        "nome": {"type": "string"}, "tipo": {"type": "string"}, "projeto": {"type": "string"},
        "diretorio": {"type": "string"}, "skills": {"type": "array", "items": {"type": "string"}},
        "mcps": {"type": "array", "items": {"type": "string"}}, "descricao": {"type": "string"}},
     "required": ["nome", "tipo"]})
def criar_workspace(nome, tipo, projeto=None, diretorio=None, skills=None, mcps=None, descricao=""):
    n, aviso = workspaces.criar(nome, tipo, projeto, diretorio, None, skills or [], mcps or [], descricao)
    return f"WorkSpace '{n}' criado ({tipo}).{aviso}"


@ferramenta("listar_workspaces", "Lista os WorkSpaces e qual está ativo.")
def listar_workspaces():
    atual = workspaces.atual()
    ws = workspaces.listar()
    return "\n".join(f"{'▶ ' if w['nome'] == atual else '  '}{w['nome']} ({w['tipo']})"
                     + (f" · projeto {w['projeto']}" if w["projeto"] else "") + (f" · {w['diretorio']}" if w["diretorio"] else "")
                     for w in ws) or "Nenhum WorkSpace criado."


@ferramenta(
    "ativar_workspace",
    "Entra num WorkSpace: o projeto dele vira o contexto ativo, valem as permissões dele e as ferramentas "
    "fora dele ficam bloqueadas. Devolve o que estava em andamento (sessão restaurada).",
    {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]})
def ativar_workspace(nome):
    ws = workspaces.ativar(nome)
    r = workspaces.restaurar_sessao(ws["nome"])
    linhas = [f"WorkSpace '{ws['nome']}' ativo" + (f" (projeto {ws['projeto']})" if ws["projeto"] else "") + "."]
    if r["notas"]:
        linhas.append(f"Notas da última sessão ({(r['salvo'] or '')[:16]}): {r['notas']}")
    if r["planos"]:
        linhas.append("Planos em aberto: " + "; ".join(f"{p['id']} [{p['estado']}] {p['objetivo'][:60]}" for p in r["planos"]))
    if r["claude"]:
        linhas.append("Tarefas do Claude Code: " + "; ".join(f"{t['id']} [{t['estado']}]" for t in r["claude"]))
    if r["atividades"]:
        linhas.append("Últimas atividades: " + "; ".join(f"{a['quando'][:10]} {a['titulo'][:50]}" for a in r["atividades"][:6]))
    if r["documentos"]:
        linhas.append("Documentos: " + ", ".join(d["titulo"] for d in r["documentos"][:8]))
    return NAO_CONFIAVEL + "\n".join(linhas)


@ferramenta("sair_do_workspace", "Sai do WorkSpace ativo (volta ao contexto geral, sem restrições de WorkSpace).")
def sair_do_workspace():
    workspaces.desativar()
    return "Sem WorkSpace ativo."


@ferramenta(
    "salvar_sessao_workspace",
    "Guarda notas do estado atual do trabalho no WorkSpace ativo (o que falta, onde parou), para retomar depois.",
    {"type": "object", "properties": {"notas": {"type": "string"}}, "required": ["notas"]})
def salvar_sessao_workspace(notas):
    nome = workspaces.atual()
    if not nome:
        return "Nenhum WorkSpace ativo."
    workspaces.salvar_sessao(nome, notas)
    return f"Sessão do '{nome}' salva."


@ferramenta(
    "sentinel_contexto",
    "Diz qual aplicativo/janela o Davi está usando agora, sugere o WorkSpace correspondente e lista "
    "documentos relacionados. Só funciona se o Sentinel estiver ligado por ele.")
def sentinel_contexto():
    try:
        c = sentinel.contexto_da_janela()
    except PermissionError as e:
        return f"{e}. O Davi liga na aba SENTINEL do painel de módulos."
    j = c["janela"]
    return NAO_CONFIAVEL + (f"App ativo: {j['app']} — {j['titulo']}\n"
                            + (f"WorkSpace sugerido: {c['workspace']}\n" if c["workspace"] else "")
                            + ("Documentos relacionados: " + "; ".join(c["documentos"]) if c["documentos"] else ""))


@ferramenta(
    "sentinel_processos",
    "Consulta CPU, RAM e tempo de execução de processos que o Davi permitiu no Sentinel.",
    {"type": "object", "properties": {"nome": {"type": "string"}}})
def sentinel_processos(nome=None):
    ps = sentinel.processos(nome)
    if not ps:
        return "Nenhum processo permitido encontrado (a lista fica em sentinel.processos_permitidos)."
    return "\n".join(f"{p['nome']} (pid {p['pid']}): CPU {p['cpu']}%, RAM {p['ram_mb']} MB, rodando há {p['tempo']}" for p in ps)


@ferramenta("sentinel_alertas", "Alertas recentes do Sentinel (memória, disco, bateria, serviços, desktop).")
def sentinel_alertas():
    evs = [e for e in eventos.consultar(origem="sentinel", limite=100) if e["dados"].get("mudanca") == "alerta"][:10]
    return "\n".join(f"{e['quando'][:16]} [{e['dados'].get('severidade')}] {e['dados'].get('descricao')}" for e in evs) \
        or "Nenhum alerta recente."


sentinel.iniciar()
