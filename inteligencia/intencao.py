"""Classificação de complexidade (Cortex): quanto processo e contexto cada pedido merece.

Classes: conversa, factual, memoria, ferramenta, pesquisa, multietapas, delegacao, decisao.
Regras determinísticas e explicáveis (devolve os sinais que decidiram), medidas no
benchmark. O Context Manager usa a classe para não gastar recuperação em "bom dia" e
para trazer memória/documentos só quando o pedido precisa.
"""
import re
import unicodedata

from inteligencia.ferramentas import pontuar


def _n(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


SAUDACAO = re.compile(r"^\s*(oi|ola|e ai|eai|bom dia|boa tarde|boa noite|tudo bem|valeu|obrigad[oa]|tchau|beleza)\b"
                      r"[\s,!.?]*(ultron)?[\s,!.?]*(tudo bem)?[\s!.?]*$")
MEMORIA = re.compile(r"\b(lembra(s)?( de| qual| que| o que)?|o que (voce )?sabe sobre|qual (e|era) (o|a) (meu|minha)|"
                     r"voce (sabe|lembra)|ja te (falei|disse)|anotou|guardou)\b")
FACTUAL = re.compile(r"^\s*(quem (foi|e|era)|o que (e|foi|significa)|qual a diferenca|como funciona|por que|quando foi|"
                     r"explica|defina|o que sao)\b")
DECISAO = re.compile(r"\b(decidir|devo|vale a pena|qual (e )?(melhor|escolho)|compar(a|ar) .* (ou|e) |ajuda a escolher|"
                     r"entre .* (ou|e) )")
PESQUISA = re.compile(r"\b(a fundo|aprofundad\w*|pesquis\w* a fundo|levantamento|compar\w* as? (\w+ )?(melhores|principais)|estado da arte|"
                      r"pesquisa (completa|aprofundada)|relatorio sobre)\b")
DELEGACAO = re.compile(r"\b(refator\w*|reposit[oó]rio|repo\b|escreve(r)? testes|code review|revis\w* (o )?codigo|"
                       r"claude code|arquitetura do (projeto|codigo))")
ETAPAS = re.compile(r"(,|\be\b|\bdepois\b|\bem seguida\b|\bentao\b|;)")
VERBOS_ACAO = re.compile(r"\b(migra|roda|faz|executa|instala|configura|cria|gera|publica|deploy|testa|atualiza|"
                         r"envia|organiza|baixa|sobe|compila)\w*\b")


def classificar(pedido):
    t = _n(pedido.strip())
    sinais = []
    if SAUDACAO.match(t):
        return {"classe": "conversa", "sinais": ["saudação"], "confianca": 0.95}
    if DELEGACAO.search(t):
        sinais.append("código/repositório")
        return {"classe": "delegacao", "sinais": sinais, "confianca": 0.8}
    acoes = len(VERBOS_ACAO.findall(t))
    if acoes >= 2 and ETAPAS.search(t):
        return {"classe": "multietapas", "sinais": [f"{acoes} verbos de ação encadeados"], "confianca": 0.75}
    if DECISAO.search(t) and not FACTUAL.match(t):     # "qual a diferença entre X e Y" é conhecimento
        return {"classe": "decisao", "sinais": ["escolha entre alternativas"], "confianca": 0.75}
    if PESQUISA.search(t):
        return {"classe": "pesquisa", "sinais": ["pesquisa aprofundada/comparativa"], "confianca": 0.7}
    if MEMORIA.search(t):
        return {"classe": "memoria", "sinais": ["referência ao que já foi dito/guardado"], "confianca": 0.75}
    ranking = pontuar(pedido)
    forte = ranking and ranking[0][1] >= 4.0
    if FACTUAL.match(t) and not forte:
        return {"classe": "factual", "sinais": ["pergunta de conhecimento"], "confianca": 0.7}
    if forte or acoes:
        return {"classe": "ferramenta", "sinais": [f"ferramenta provável: {ranking[0][0]}" if ranking else "verbo de ação"],
                "confianca": 0.7}
    if FACTUAL.match(t):
        return {"classe": "factual", "sinais": ["pergunta de conhecimento"], "confianca": 0.6}
    return {"classe": "conversa", "sinais": ["nenhum sinal de tarefa"], "confianca": 0.5}


# quanto contexto cada classe merece (Context Budget Manager usa)
PERFIL_CONTEXTO = {
    "conversa": {"memorias": True, "documentos": False, "biblioteca": False},
    "factual": {"memorias": False, "documentos": True, "biblioteca": True},
    "memoria": {"memorias": True, "documentos": True, "biblioteca": False},
    "ferramenta": {"memorias": True, "documentos": False, "biblioteca": False},
    "pesquisa": {"memorias": True, "documentos": True, "biblioteca": True},
    "multietapas": {"memorias": True, "documentos": True, "biblioteca": False},
    "delegacao": {"memorias": True, "documentos": True, "biblioteca": False},
    "decisao": {"memorias": True, "documentos": True, "biblioteca": True},
}
