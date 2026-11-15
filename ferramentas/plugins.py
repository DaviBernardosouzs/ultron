"""Acesso aos plugins MCP (plugins.yaml) e notificações via Apprise.

O modelo não recebe as centenas de ferramentas de todos os servidores de uma vez:
ele lista os plugins, abre o que precisa e chama a ferramenta certa.
"""
import json

from core import plugins
from core.config import ajuste, segredo
from core.registro import NAO_CONFIAVEL, ferramenta


@ferramenta(
    "listar_plugins",
    "Lista os plugins MCP do Ultron (GitHub, Notion, Gmail, Playwright, arquivos, busca "
    "na web...) e se estão prontos para uso. Use antes de ferramentas_do_plugin.")
def listar_plugins():
    linhas = []
    for nome, cfg in plugins.configuracao().items():
        if not cfg.get("ativo", True):
            estado = "desativado"
        elif plugins.faltando(cfg):
            estado = "falta configurar " + ", ".join(plugins.faltando(cfg))
        else:
            estado = "pronto"
        linhas.append(f"{nome}: {cfg.get('descricao', '')} [{estado}]")
    return "\n".join(linhas) or "Nenhum plugin em plugins.yaml."


@ferramenta(
    "ferramentas_do_plugin",
    "Conecta a um plugin MCP e mostra as ferramentas dele, com os parâmetros. "
    "Chame antes de usar_plugin para saber o nome e os argumentos certos.",
    {"type": "object", "properties": {"plugin": {"type": "string"}}, "required": ["plugin"]})
def ferramentas_do_plugin(plugin):
    tools = plugins.gerente().listar_ferramentas(plugin)
    saida = []
    for t in tools:
        props = (t.input_schema or {}).get("properties", {})
        obrig = set((t.input_schema or {}).get("required", []))
        params = ", ".join(f"{k}{'*' if k in obrig else ''}: {v.get('type', '?')}"
                           for k, v in props.items())
        desc = (t.description or "").strip().split("\n")[0][:160]
        saida.append(f"- {t.name}({params}) [{plugins.nivel_da_ferramenta(plugin, t.name)}]: {desc}")
    instr = plugins.gerente().instrucoes.get(plugin)
    cab = f"Instruções do servidor: {instr}\n\n" if instr else ""
    return cab + f"{len(tools)} ferramentas em {plugin} (* = obrigatório):\n" + "\n".join(saida)


def _nivel(args):
    p, f = args.get("plugin", ""), args.get("ferramenta", "")
    conhecidas = plugins.gerente().ferramentas.get(p)
    if conhecidas is not None and f not in {t.name for t in conhecidas}:
        return "N1", f"{p}.{f}"   # não existe: vai só devolver erro, nada a confirmar
    return plugins.nivel_da_ferramenta(p, f), f"{p}.{f}"


def _resumo(args):
    a = json.dumps(args.get("argumentos") or {}, ensure_ascii=False)
    return f"usar {args.get('ferramenta')} do plugin {args.get('plugin')} com {a[:200]}"


@ferramenta(
    "usar_plugin",
    "Executa uma ferramenta de um plugin MCP. Use os nomes e argumentos exatos de "
    "ferramentas_do_plugin.",
    {"type": "object", "properties": {
        "plugin": {"type": "string"},
        "ferramenta": {"type": "string"},
        "argumentos": {"type": "object"}}, "required": ["plugin", "ferramenta"]},
    nivel="N3", nivel_dinamico=_nivel, resumo=_resumo)
def usar_plugin(plugin, ferramenta, argumentos=None):
    r = plugins.gerente().chamar(plugin, ferramenta, argumentos or {})
    texto = plugins.texto_do_resultado(r)
    if getattr(r, "is_error", False):
        raise RuntimeError(texto)
    return NAO_CONFIAVEL + texto


@ferramenta(
    "notificar",
    "Envia uma notificação pelos serviços configurados no Apprise (Discord, WhatsApp, "
    "Telegram, e-mail, ntfy, Pushbullet... mais de 100 serviços).",
    {"type": "object", "properties": {
        "mensagem": {"type": "string"}, "titulo": {"type": "string"}}, "required": ["mensagem"]})
def notificar(mensagem, titulo="Ultron"):
    import apprise
    urls = [u.strip() for u in (segredo("APPRISE_URLS") or "").split(",") if u.strip()]
    urls += ajuste("apprise.urls", []) or []
    if not urls:
        return "Nenhum destino no Apprise. Coloque URLs em APPRISE_URLS no .env (separadas por vírgula)."
    ap = apprise.Apprise()
    for u in urls:
        ap.add(u)
    return "Notificação enviada." if ap.notify(body=mensagem, title=titulo) else "Falha ao notificar."
