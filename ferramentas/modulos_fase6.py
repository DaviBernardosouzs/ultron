"""Ferramentas da MACRO FORGE e do SELF AUDIT. Ativar uma macro é decisão do Davi (só na janela)."""
import json

from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import macros, self_audit


@ferramenta(
    "criar_macro",
    "Cria uma nova versão (rascunho) de uma automação. 'definicao' é JSON com nome, descricao, entradas "
    "[{nome, padrao}], passos [{id, ferramenta, args, se}], saida e gatilho ({tipo: manual|diario|semanal|"
    "intervalo|evento, hora, dia, minutos, evento}). Modelos: {{entrada.x}}, {{passos.e1.saida}}, {{agora}}. "
    "Condições: '<expr> contem <texto>', 'nao_contem', '==', '!=', '<expr> vazio'. A macro NÃO é ativada: "
    "o Davi testa e ativa na janela de módulos.",
    {"type": "object", "properties": {"definicao": {"type": "string"}}, "required": ["definicao"]})
def criar_macro(definicao):
    d = json.loads(definicao)
    nome, v, problemas = macros.salvar(d)
    teste = macros.testar(nome, v)
    return (f"Macro {nome} v{v} salva como rascunho. Teste a seco: {'OK' if teste['ok'] else 'FALHOU: ' + '; '.join(teste['problemas'])}."
            + (f" Ferramentas sensíveis que o Davi precisa aprovar: {teste['sensiveis']}." if teste["sensiveis"] else "")
            + " Para ativar, o Davi usa a aba MACRO FORGE.")


@ferramenta("listar_macros", "Lista as automações, a versão ativa e o gatilho de cada uma.")
def listar_macros():
    ms = macros.listar()
    return "\n".join(f"{m['nome']}: ativa v{m['ativa'] or '-'} (última v{m['ultima']} {m['estado_ultima']}), gatilho {m['gatilho']}"
                     for m in ms) or "Nenhuma macro."


@ferramenta(
    "executar_macro",
    "Executa agora a versão ATIVA de uma macro, com entradas opcionais. Ações sensíveis não aprovadas "
    "na ativação pedem confirmação.",
    {"type": "object", "properties": {"nome": {"type": "string"}, "entradas": {"type": "object"}}, "required": ["nome"]},
    nivel="N2", resumo=lambda a: f"executar a macro {a.get('nome')}")
def executar_macro(nome, entradas=None):
    r = macros.executar(nome, entradas or {})
    return NAO_CONFIAVEL + f"Macro {nome}: {r['estado']}\n" + "\n".join(
        f"- {x['passo']}: {x['estado']} {x.get('erro') or x.get('motivo') or x.get('saida', '')[:150]}" for x in r["log"]) + \
        (f"\nSaída: {r['saida']}" if r["saida"] else "")


@ferramenta("historico_macro", "Últimas execuções de uma macro (ou de todas).",
            {"type": "object", "properties": {"nome": {"type": "string"}}})
def historico_macro(nome=None):
    h = macros.historico(nome, 15)
    return "\n".join(f"#{x['id']} {x['nome']} v{x['versao']} [{x['estado']}] {x['inicio'][:16]} ({x['gatilho']})" for x in h) \
        or "Nenhuma execução."


@ferramenta(
    "auditar_ultron",
    "Auditoria operacional do Ultron com evidências: serviços, configuração, MCP, skills, falhas recorrentes, "
    "dependências, testes e consumo de recursos. Gera relatório no Scribe. Não altera nada.",
    {"type": "object", "properties": {"rodar_testes": {"type": "boolean", "default": False}}})
def auditar_ultron(rodar_testes=False):
    r = self_audit.auditar(rodar_testes)
    return f"Auditoria #{r['id']}: {r['resumo']}\n" + "\n".join(
        f"- [{a['nivel']}] {a['area']}/{a['item']}: {a['problema']} (evidência: {a['evidencia'][:120]})" for a in r["achados"][:20])


@ferramenta(
    "propor_correcao_auditoria",
    "Transforma um achado da última auditoria numa proposta de correção na Evolution Forge (passa por "
    "sandbox, testes e aprovação do Davi). 'indice' é a posição do achado na lista (1 = primeiro).",
    {"type": "object", "properties": {"indice": {"type": "integer"}}, "required": ["indice"]})
def propor_correcao_auditoria(indice):
    ult = self_audit.ultimas(1)
    if not ult or not 1 <= int(indice) <= len(ult[0]["achados"]):
        return "Achado não encontrado (rode auditar_ultron antes)."
    nid = self_audit.propor(ult[0]["achados"][int(indice) - 1])
    return f"Proposta registrada na Evolution Forge como necessidade {nid}."


macros.iniciar()   # agendador real (uma instância por máquina, com trava)
