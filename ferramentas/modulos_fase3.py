"""Ferramentas do CORTEX (decisão) e do VECTOR (planejamento e execução)."""
from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import cortex, vector


@ferramenta(
    "cortex_analisar",
    "Apoio à decisão: estrutura o problema (critérios com peso, alternativas, premissas, riscos), "
    "busca evidências reais no Atlas, dá notas justificadas e calcula a recomendação ponderada e se ela "
    "é robusta. Use quando o Davi pedir ajuda para decidir entre opções.",
    {"type": "object", "properties": {
        "problema": {"type": "string"}, "contexto": {"type": "string"}, "projeto": {"type": "string"},
        "alternativas": {"type": "array", "items": {"type": "string"}},
        "criterios": {"type": "array", "items": {"type": "string"}}},
     "required": ["problema"]})
def cortex_analisar(problema, contexto="", projeto=None, alternativas=None, criterios=None):
    aid = cortex.estruturar(problema, contexto, projeto, alternativas, criterios)
    cortex.avaliar(aid)
    return NAO_CONFIAVEL + cortex.relatorio(aid) + f"\n(Para registrar a escolha: cortex_registrar_decisao com analise={aid}.)"


@ferramenta(
    "cortex_registrar_decisao",
    "Registra a alternativa que o DAVI escolheu numa análise do Cortex (vira registro de decisão no "
    "Obsidian e memória). Só chame depois que ele disser qual escolheu.",
    {"type": "object", "properties": {"analise": {"type": "integer"}, "alternativa": {"type": "string"}},
     "required": ["analise", "alternativa"]},
    nivel="N2", resumo=lambda a: f"registrar a decisão '{a.get('alternativa')}' da análise {a.get('analise')}")
def cortex_registrar_decisao(analise, alternativa):
    cortex.registrar(int(analise), alternativa)
    return f"Decisão registrada: {alternativa}."


def _resumo_plano(pid):
    p = vector.obter(pid)
    linhas = [f"Plano {pid} [{p['estado']}]: {p['objetivo']} (gerado por {p['gerado_por']})"]
    for e in p["etapas"]:
        alvo = f"{e['ferramenta']}({e['args']})" if e["executor"] == "ferramenta" else e["executor"]
        linhas.append(f"- {e['id']} [{e['estado']}] {e['descricao']} → {alvo}"
                      + (f" depois de {e['depende']}" if e["depende"] else "")
                      + (f"\n    resultado: {e['resultado'][:200]}" if e["resultado"] else "")
                      + (f"\n    erro: {e['erro'][:200]}" if e["erro"] else ""))
    if p["criterios"]:
        linhas.append("Critérios de aceite: " + "; ".join(map(str, p["criterios"])))
    return "\n".join(linhas)


@ferramenta(
    "vector_planejar",
    "Cria um plano de execução para um objetivo com várias etapas, usando as ferramentas que existem. "
    "Só planeja: mostre o plano ao Davi e execute com vector_executar se ele concordar.",
    {"type": "object", "properties": {
        "objetivo": {"type": "string"}, "projeto": {"type": "string"}, "contexto": {"type": "string"},
        "criterios": {"type": "array", "items": {"type": "string"}}},
     "required": ["objetivo"]})
def vector_planejar(objetivo, projeto=None, contexto="", criterios=None):
    return _resumo_plano(vector.planejar(objetivo, projeto, contexto, criterios))


@ferramenta(
    "vector_executar",
    "Executa (ou retoma) um plano do Vector em segundo plano. Cada ação sensível ainda pede "
    "confirmação; se ninguém puder confirmar, o plano pausa e espera o Davi.",
    {"type": "object", "properties": {"plano": {"type": "string"}}, "required": ["plano"]},
    nivel="N2", resumo=lambda a: f"executar o plano {a.get('plano')} (ações sensíveis ainda pedem confirmação)")
def vector_executar(plano):
    vector.executar(plano)
    return f"Plano {plano} em execução. Acompanhe com vector_status."


@ferramenta("vector_status", "Mostra o estado de um plano do Vector (ou lista os recentes).",
            {"type": "object", "properties": {"plano": {"type": "string"}}})
def vector_status(plano=None):
    if plano:
        return NAO_CONFIAVEL + _resumo_plano(plano)
    ps = vector.listar(10)
    return "\n".join(f"{p['id']} [{p['estado']}] {p['objetivo'][:80]}" for p in ps) or "Nenhum plano."


@ferramenta("vector_cancelar", "Cancela um plano em execução (para antes da próxima etapa).",
            {"type": "object", "properties": {"plano": {"type": "string"}}, "required": ["plano"]})
def vector_cancelar(plano):
    vector.cancelar(plano)
    return f"Plano {plano} cancelado."


@ferramenta("vector_validar", "Verifica se um plano concluído cumpriu o objetivo e os critérios de aceite.",
            {"type": "object", "properties": {"plano": {"type": "string"}}, "required": ["plano"]})
def vector_validar(plano):
    v = vector.validar(plano)
    return NAO_CONFIAVEL + f"{'CUMPRIDO' if v.get('ok') else 'NÃO CUMPRIDO'} ({v.get('por')}): {v.get('motivo', '')}\n" + \
        "\n".join(f"- {c.get('criterio')}: {'ok' if c.get('atendido') else 'não'} ({c.get('evidencia', '')})"
                  for c in v.get("criterios", []))
