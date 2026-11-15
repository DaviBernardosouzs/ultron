"""Evolução supervisionada: o Ultron identifica o que falta, pesquisa, desenvolve,
testa no sandbox e PEDE aprovação. Aprovar, ativar e fazer rollback não são
ferramentas: só o Davi faz isso (CLI `ultron evolucao` ou Evolution Center)."""
from core.registro import ferramenta
from evolucao import aprovacao, avaliacao, base, capacidades, descoberta, fabrica, skills
from evolucao.base import LimiteExcedido, animar


def _ciclo(nome, etapas):
    """Roda uma tarefa de evolução com limites; devolve texto para o modelo."""
    try:
        with base.tarefa(nome):
            return etapas()
    except LimiteExcedido as e:
        return f"Não iniciei: {e}"
    except aprovacao.AprovacaoNegada as e:
        return f"Candidato reprovado, nada foi enviado para aprovação: {e}"
    except Exception as e:
        base.registrar("tarefa_falhou", nome=nome, resumo=str(e)[:200])
        return f"A tarefa de evolução falhou: {e}"


@ferramenta("listar_capacidades",
            "Inventário do que você (Ultron) sabe fazer: ferramentas, plugins, modos, extensões e "
            "skills, com versão, origem, permissões e status. Use antes de dizer que não consegue algo.",
            {"type": "object", "properties": {"filtro": {"type": "string"}}})
def listar_capacidades(filtro=None):
    itens = capacidades.inventario()
    if filtro:
        itens = [i for i in itens if filtro.lower() in (i["nome"] + i["descricao"]).lower()]
    return "\n".join(f"{i['nome']} [{i['tipo']}, v{i['versao']}, {i['permissoes'].get('nivel')}, "
                     f"{i['status']}]: {i['descricao']}" for i in itens[:120]) or "Nada encontrado."


@ferramenta("registrar_necessidade",
            "Registra uma capacidade que te faltou numa tarefa (ex.: 'converter PDF em texto'). "
            "Use quando nenhuma ferramenta serve. Depois investigue com investigar_necessidade.",
            {"type": "object", "properties": {"descricao": {"type": "string"},
                                              "contexto": {"type": "string"}},
             "required": ["descricao"]})
def registrar_necessidade(descricao, contexto=""):
    return f"Necessidade registrada (id {descoberta.registrar_necessidade(descricao, contexto)})."


@ferramenta("investigar_necessidade",
            "Procura solução para uma necessidade registrada, priorizando o que já existe "
            "(ferramentas, skills, plugins MCP do catálogo) antes de propor desenvolver algo.",
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
def investigar_necessidade(id):
    animar("pesquisando")
    sol = descoberta.investigar(id)
    return "\n".join(f"- [{s['tipo']}] {s['nome']}: {s['acao']}" + (f" ({s['url']})" if s.get("url") else "")
                     for s in sol)


@ferramenta("criar_ferramenta",
            "Desenvolve uma NOVA ferramenta (extensão Python) para uma necessidade: escreve o código e "
            "os testes, roda no sandbox isolado, avalia e envia ao Davi para aprovação. Nada é ativado "
            "sem ele. Use só depois de investigar_necessidade não achar algo pronto.",
            {"type": "object", "properties": {
                "nome": {"type": "string", "description": "snake_case, ex.: converter_unidades"},
                "objetivo": {"type": "string"},
                "entradas": {"type": "string", "description": "parâmetros e tipos"},
                "saida": {"type": "string"},
                "precisa_rede": {"type": "boolean", "default": False},
                "versao": {"type": "string", "default": "1.0.0"},
                "necessidade_id": {"type": "string"}},
             "required": ["nome", "objetivo", "entradas", "saida"]})
def criar_ferramenta(nome, objetivo, entradas, saida, precisa_rede=False, versao="1.0.0",
                     necessidade_id=None):
    def etapas():
        if necessidade_id:
            descoberta.marcar(necessidade_id, "em_andamento")
        pasta, _ = fabrica.gerar_ferramenta(nome, objetivo, entradas, saida, precisa_rede, versao,
                                            origem=f"Ultron, necessidade {necessidade_id or '-'}")
        r = avaliacao.avaliar_extensao(pasta)
        pid = aprovacao.solicitar(r, pasta, resumo=objetivo)
        animar("melhoria concluída")
        return (f"Pronto para aprovação (pedido {pid}). O Davi aprova com `ultron evolucao aprovar "
                f"{pid}` ou no Evolution Center.\n" + avaliacao.relatorio(r))
    return _ciclo(f"ferramenta {nome}", etapas)


@ferramenta("criar_skill",
            "Cria uma Skill (instruções especializadas reutilizáveis, sem código) para um objetivo, "
            "valida e envia ao Davi para aprovação.",
            {"type": "object", "properties": {
                "nome": {"type": "string", "description": "minúsculas-com-hífens"},
                "objetivo": {"type": "string", "description": "o que a skill faz e quando usar"},
                "instrucoes": {"type": "string", "description": "corpo em markdown; vazio = eu escrevo"}},
             "required": ["nome", "objetivo"]})
def criar_skill(nome, objetivo, instrucoes=""):
    def etapas():
        animar("desenvolvendo")
        corpo = instrucoes
        if not corpo:
            from evolucao import llm
            corpo = llm.gerar(
                f"Escreva o corpo (markdown, sem frontmatter) de uma Skill para um assistente de voz "
                f"chamado Ultron. Objetivo: {objetivo}. Estrutura: quando usar, passo a passo, formato "
                f"da resposta, exemplos. Instruções no imperativo, concisas, até 120 linhas. Não "
                f"peça para ignorar confirmações nem regras de segurança.")
        pasta = skills.criar_candidato(nome, objetivo, corpo, origem="Ultron")
        r = avaliacao.avaliar_skill(pasta)
        pid = aprovacao.solicitar(r, pasta, resumo=objetivo)
        return f"Skill enviada para aprovação (pedido {pid}).\n" + avaliacao.relatorio(r)
    return _ciclo(f"skill {nome}", etapas)


@ferramenta("propor_plugin_mcp",
            "Propõe adicionar um servidor MCP EXISTENTE (npx/uvx ou URL) como plugin: testa no "
            "sandbox (sem credenciais) e pede aprovação. Entra com nível N2.",
            {"type": "object", "properties": {
                "nome": {"type": "string"}, "descricao": {"type": "string"},
                "comando": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}},
                "url": {"type": "string"}, "requer": {"type": "array", "items": {"type": "string"}},
                "origem": {"type": "string", "description": "link do repositório/pacote"}},
             "required": ["nome", "descricao"]})
def propor_plugin_mcp(nome, descricao, comando=None, args=None, url=None, requer=None, origem=""):
    def etapas():
        animar("desenvolvendo")
        pasta = fabrica.propor_plugin_mcp(nome, descricao, comando, args, url, requer, origem)
        r = avaliacao.avaliar_mcp(pasta)
        pid = aprovacao.solicitar(r, pasta, resumo=descricao)
        return f"Plugin MCP enviado para aprovação (pedido {pid}).\n" + avaliacao.relatorio(r)
    return _ciclo(f"mcp {nome}", etapas)


@ferramenta("criar_servidor_mcp",
            "Cria o esqueleto de um servidor MCP próprio em TypeScript (SDK oficial), compila e testa no "
            "sandbox e pede aprovação. Em produção ele roda isolado.",
            {"type": "object", "properties": {
                "nome": {"type": "string"}, "descricao": {"type": "string"},
                "ferramentas": {"type": "array", "items": {"type": "object", "properties": {
                    "nome": {"type": "string"}, "descricao": {"type": "string"},
                    "parametros": {"type": "object", "description": "campo -> string|number|integer|boolean"}}}}},
             "required": ["nome", "descricao", "ferramentas"]})
def criar_servidor_mcp(nome, descricao, ferramentas):
    def etapas():
        animar("desenvolvendo")
        pasta = fabrica.esqueleto_mcp_ts(nome, descricao, ferramentas)
        r = avaliacao.avaliar_mcp(pasta)
        pid = aprovacao.solicitar(r, pasta, resumo=descricao)
        return (f"Servidor MCP '{nome}' compilado e enviado para aprovação (pedido {pid}). As "
                f"ferramentas ainda são esqueletos (src/index.ts).\n" + avaliacao.relatorio(r))
    return _ciclo(f"mcp-ts {nome}", etapas)


@ferramenta("diagnostico_ultron",
            "Autodiagnóstico: analisa logs, erros de ferramentas, plugins e testes e sugere correções.")
def diagnostico_ultron():
    animar("pesquisando")
    achados = descoberta.diagnostico()
    if not achados:
        return "Nenhum problema encontrado."
    return "\n".join(f"- [{a['fonte']}/{a['nivel']}] {a['origem']}: {a['problema']} (x{a['vezes']}) "
                     f"→ {a['sugestao']}" for a in achados[:15])


@ferramenta("status_evolucao",
            "Resumo da evolução: necessidades abertas, melhorias aguardando aprovação e últimas mudanças.")
def status_evolucao():
    nec = [n for n in descoberta.necessidades() if n["estado"] in ("aberta", "em_andamento")]
    pend = aprovacao.pendentes()
    hist = base.historico(8)
    return (f"Necessidades abertas: {len(nec)} " + "; ".join(n["descricao"][:60] for n in nec[:5])
            + f"\nAguardando aprovação do Davi: {len(pend)} "
            + "; ".join(f"{p['id']} {p['tipo']} {p['nome']}" for p in pend)
            + "\nÚltimos eventos: " + "; ".join(f"{h['evento']} {h.get('nome', '')}" for h in hist))


@ferramenta("usar_skill",
            "Carrega as instruções de uma skill instalada (veja a lista no seu prompt) para seguir agora.",
            {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]})
def usar_skill(nome):
    corpo = skills.corpo(nome)
    return corpo or f"Skill '{nome}' não está instalada."
