"""Ferramentas do ORACLE (simulações) e da SYNAPSE (coordenação de agentes)."""
import json

from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import oracle, synapse


@ferramenta(
    "oracle_simular",
    "Simula cenários com premissas explícitas (Monte Carlo): custos, prazos, desempenho, alternativas. "
    "Passe 'cenario' em JSON (variaveis com origem observado/estimado/hipotese, formulas, alternativas, premissas) "
    "ou só 'descricao' para a IA montar o cenário. Resultado é simulação, não previsão: diga isso ao Davi.",
    {"type": "object", "properties": {"nome": {"type": "string"}, "descricao": {"type": "string"},
                                      "cenario": {"type": "string"}, "projeto": {"type": "string"}},
     "required": ["nome"]})
def oracle_simular(nome, descricao=None, cenario=None, projeto=None):
    c = json.loads(cenario) if cenario else oracle.estruturar(descricao or nome)
    problemas = oracle.validar(c)
    if problemas:
        return "O cenário precisa de ajustes antes de simular: " + "; ".join(problemas) + \
            f"\nCenário proposto: {json.dumps(c, ensure_ascii=False)[:1500]}"
    cid, r = oracle.salvar_e_simular(nome, c, projeto)
    texto = oracle.relatorio(nome, c, r)
    try:
        from modulos import scribe
        scribe.gravar("Simulações", f"Simulação {nome}", texto, {"tipo": "simulacao", "projeto": projeto,
                                                                "gerado_por": c.get("gerado_por", "Davi")})
    except Exception:
        pass
    return NAO_CONFIAVEL + texto


@ferramenta("synapse_agentes", "Lista os agentes especializados que a Synapse pode acionar, com responsabilidades e limites.")
def synapse_agentes():
    return "\n".join(f"{a['nome']} ({a['executor']}): {a['responsabilidades']} · até US$ {a['limite_usd']} e {a['limite_s']} s"
                     for a in synapse.agentes())


@ferramenta(
    "synapse_coordenar",
    "Divide um objetivo grande entre agentes especializados (IA local, Claude Code, o próprio Ultron), "
    "verifica cada entrega e consolida o resultado dizendo quem fez o quê. Para código, informe o diretório.",
    {"type": "object", "properties": {"objetivo": {"type": "string"}, "diretorio": {"type": "string"},
                                      "editar": {"type": "boolean", "default": False}}, "required": ["objetivo"]},
    nivel="N2", resumo=lambda a: f"coordenar agentes para: {a.get('objetivo')}")
def synapse_coordenar(objetivo, diretorio=None, editar=False):
    cid, e = synapse.coordenar(objetivo, diretorio, editar)
    partes = "; ".join(f"{k}: {v['agente']} ({'verificado' if v['verificado'] else 'não verificado'})" for k, v in e["partes"].items())
    return NAO_CONFIAVEL + f"Coordenação {cid}. Partes: {partes}\nConsolidado por {e['consolidado_por']}:\n{e['texto']}"
