"""Ferramentas da ClaudeCodeBridge para o orquestrador (o Ultron continua no comando)."""
from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import claude_bridge as cb


@ferramenta(
    "claude_rotear",
    "Diz qual executor é o mais adequado para um pedido (modelo local/Ultron ou Claude Code) e por quê, "
    "considerando modo configurado, tipo de tarefa, etapas, arquivos, privacidade e orçamento.",
    {"type": "object", "properties": {"pedido": {"type": "string"}, "diretorio": {"type": "string"},
                                      "projeto": {"type": "string"}}, "required": ["pedido"]})
def claude_rotear(pedido, diretorio=None, projeto=None):
    r = cb.rotear(pedido, diretorio, projeto=projeto)
    return (f"Executor: {r['executor']} — {r['motivo']}"
            + (" (precisa do consentimento do Davi para enviar este projeto ao Claude Code)" if r["pede_consentimento"] else "")
            + f"\nCritérios: {r['criterios']}")


@ferramenta(
    "claude_delegar",
    "Delega uma tarefa complexa de código/arquivos ao Claude Code, num diretório autorizado. Só o "
    "contexto necessário é enviado. Com editar=true, as mudanças ficam num git worktree isolado e só "
    "entram no projeto quando o Davi aplicar. Cada ação do Claude Code passa pelo Guardian. "
    "Diga ao Davi que o resultado veio do Claude Code.",
    {"type": "object", "properties": {
        "objetivo": {"type": "string"}, "diretorio": {"type": "string"}, "contexto": {"type": "string"},
        "arquivos": {"type": "array", "items": {"type": "string"}},
        "aceite": {"type": "array", "items": {"type": "string"}},
        "editar": {"type": "boolean", "default": False}, "limite_usd": {"type": "number"},
        "projeto": {"type": "string"}},
     "required": ["objetivo", "diretorio"]},
    nivel="N2", resumo=lambda a: f"delegar ao Claude Code: {a.get('objetivo')} em {a.get('diretorio')}"
                                 + (" (com edição isolada)" if a.get("editar") else " (só leitura)"))
def claude_delegar(objetivo, diretorio, contexto="", arquivos=None, aceite=None, editar=False, limite_usd=None,
                   projeto=None):
    r = cb.rotear(objetivo, diretorio, arquivos or [], projeto)
    if r["criterios"]["modo"] == "local_only":
        return "O modo está em LOCAL ONLY: nada é enviado ao Claude Code. Mude o modo na aba CLAUDE BRIDGE."
    if r["criterios"].get("privado"):
        return "Esse projeto está marcado como privado: não vou enviá-lo ao Claude Code."
    if not r["criterios"]["consentido"]:
        return ("Ainda não há consentimento para enviar esse diretório ao Claude Code. O Davi autoriza na aba "
                "CLAUDE BRIDGE (botão PERMITIR ENVIO).")
    d = cb.nova_delegacao(objetivo, diretorio, contexto, arquivos or [], aceite=aceite or [], editar=editar,
                          limite_usd=limite_usd, motivo=r["motivo"])
    tid = cb.iniciar(d)
    return f"Tarefa {tid} iniciada no Claude Code (limite US$ {d['limite_usd']}). Acompanhe com claude_status."


@ferramenta("claude_status", "Estado de uma tarefa delegada ao Claude Code (ou lista as recentes).",
            {"type": "object", "properties": {"tarefa": {"type": "string"}}})
def claude_status(tarefa=None):
    if not tarefa:
        return "\n".join(f"{t['id']} [{t['estado']}] {t['objetivo'][:70]} US$ {t['custo'] or 0:.2f}"
                         for t in cb.listar(10)) or "Nenhuma tarefa delegada."
    t = cb.obter(tarefa)
    return NAO_CONFIAVEL + (f"{t['id']} [{t['estado']}] {t['objetivo']}\ncusto US$ {t['custo'] or 0:.2f}, "
                            f"{t['turnos'] or 0} turnos, sessão {t['sessao']}\narquivos: {', '.join(t['arquivos']) or '-'}\n"
                            + (f"erro: {t['erro']}\n" if t["erro"] else "")
                            + f"resultado (Claude Code): {(t['resultado'] or '')[:2500]}")


@ferramenta("claude_cancelar", "Interrompe uma tarefa do Claude Code em execução.",
            {"type": "object", "properties": {"tarefa": {"type": "string"}}, "required": ["tarefa"]})
def claude_cancelar(tarefa):
    cb.cancelar(tarefa)
    return f"Tarefa {tarefa} interrompida."
