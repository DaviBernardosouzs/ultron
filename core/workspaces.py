"""WORKSPACES: ambientes de trabalho com contexto e permissões próprios.

Cada WorkSpace: nome, tipo (desenvolvimento, pesquisa, estudo, pessoal, outro),
projeto do NEURALINK, diretório, grupos de ferramentas permitidas, skills e plugins
MCP associados, notas de sessão.

- Ativar um WorkSpace: o projeto vira o projeto ativo do NEURALINK (o contexto de outros
  projetos não entra), o Guardian passa a aplicar as políticas desse workspace e as
  ferramentas fora dos grupos permitidos são negadas (as essenciais continuam).
- Restaurar a sessão: devolve o que estava em andamento (planos do Vector, tarefas do
  Claude Code, eventos recentes, documentos e notas do projeto).
- O diretório não é liberado automaticamente: ele precisa estar autorizado no Guardian
  (decisão do Davi).
"""
import json
from datetime import datetime

from core import eventos
from core.config import DADOS

TIPOS = ("desenvolvimento", "pesquisa", "estudo", "pessoal", "outro")
# grupos = módulos de ferramentas/ (registro: f.funcao.__module__)
GRUPOS = {
    "desenvolvimento": ["ssh", "computacao", "claude_bridge", "neuralink", "modulos_fase2", "modulos_fase3",
                        "web", "sistema", "plugins", "evolucao", "navegador"],
    "pesquisa": ["web", "neuralink", "modulos_fase2", "modulos_fase3", "biblioteca", "plugins", "navegador"],
    "estudo": ["web", "neuralink", "modulos_fase2", "biblioteca", "agenda"],
    "pessoal": ["midia", "casa", "agenda", "comunicacao", "modos", "android", "rede", "sistema", "navegador"],
    "outro": [],
}
ESSENCIAIS = {"chronos_guardian", "utilidades", "workspaces_sentinel", "inteligencia_meta", "emocoes"}   # sempre disponíveis
ARQ_ATUAL = "workspace_atual.json"


def _con():
    c = eventos._con()
    c.execute("""CREATE TABLE IF NOT EXISTS workspaces (
        nome TEXT PRIMARY KEY, tipo TEXT, projeto TEXT, diretorio TEXT, grupos TEXT, skills TEXT, mcps TEXT,
        descricao TEXT, criado TEXT, sessao TEXT, usado TEXT)""")
    return c


def _linha(r):
    return dict(r) | {k: json.loads(r[k] or "[]") for k in ("grupos", "skills", "mcps")} | \
        {"sessao": json.loads(r["sessao"] or "{}")}


def criar(nome, tipo="outro", projeto=None, diretorio=None, grupos=None, skills=(), mcps=(), descricao=""):
    nome = nome.strip()
    if not nome or len(nome) > 40:
        raise ValueError("nome de 1 a 40 caracteres")
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {', '.join(TIPOS)}")
    c = _con()
    c.execute("""INSERT INTO workspaces(nome, tipo, projeto, diretorio, grupos, skills, mcps, descricao, criado)
                 VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(nome) DO UPDATE SET tipo=excluded.tipo, projeto=excluded.projeto,
                 diretorio=excluded.diretorio, grupos=excluded.grupos, skills=excluded.skills, mcps=excluded.mcps,
                 descricao=excluded.descricao""",
              (nome, tipo, projeto, diretorio, json.dumps(list(grupos if grupos is not None else GRUPOS[tipo])),
               json.dumps(list(skills)), json.dumps(list(mcps)), descricao, datetime.now().isoformat(timespec="seconds")))
    c.commit()
    eventos.emitir("module.status_changed", "workspaces", {"modulo": "workspaces", "mudanca": "criado", "workspace": nome})
    aviso = ""
    if diretorio:
        from core import guardian
        if guardian.autorizar_caminho(diretorio)["decisao"] == "negar":
            aviso = f" O diretório {diretorio} ainda não está autorizado no Guardian."
    return nome, aviso


def listar():
    return [_linha(r) for r in _con().execute("SELECT * FROM workspaces ORDER BY usado DESC, nome")]


def obter(nome):
    r = _con().execute("SELECT * FROM workspaces WHERE lower(nome)=lower(?)", (nome,)).fetchone()
    if not r:
        raise ValueError(f"WorkSpace '{nome}' não existe")
    return _linha(r)


def remover(nome):
    if atual() == nome:
        desativar()
    _con().execute("DELETE FROM workspaces WHERE nome=?", (nome,))
    _con().commit()


def atual():
    try:
        return json.loads((DADOS / ARQ_ATUAL).read_text()).get("nome")
    except Exception:
        return None


def ativar(nome):
    ws = obter(nome)
    (DADOS / ARQ_ATUAL).write_text(json.dumps({"nome": ws["nome"], "desde": datetime.now().isoformat(timespec="seconds")}))
    c = _con()
    c.execute("UPDATE workspaces SET usado=? WHERE nome=?", (datetime.now().isoformat(timespec="seconds"), ws["nome"]))
    c.commit()
    try:
        from neuralink import contexto
        if ws["projeto"]:
            contexto.projeto_ativo(ws["projeto"])
        else:
            contexto.projeto_ativo(limpar=True)
    except Exception:
        pass
    eventos.emitir("module.status_changed", "workspaces", {"modulo": "workspaces", "mudanca": "ativado",
                                                           "workspace": ws["nome"], "projeto": ws["projeto"]})
    return ws


def desativar():
    (DADOS / ARQ_ATUAL).unlink(missing_ok=True)
    try:
        from neuralink import contexto
        contexto.projeto_ativo(limpar=True)
    except Exception:
        pass
    eventos.emitir("module.status_changed", "workspaces", {"modulo": "workspaces", "mudanca": "desativado"})


def ferramenta_permitida(nome_ferramenta, modulo):
    """None = sem WorkSpace ativo (sem restrição extra). True/False quando há um ativo."""
    nome = atual()
    if not nome:
        return None
    try:
        ws = obter(nome)
    except ValueError:
        return None
    if not ws["grupos"]:
        return True
    grupo = modulo.rsplit(".", 1)[-1]
    if grupo in ESSENCIAIS or grupo in ws["grupos"] or not modulo.startswith("ferramentas."):
        return True
    try:    # o Davi liberou essa ferramenta no Guardian (pedido aprovado): vale mesmo fora dos grupos
        from core import guardian
        pol = guardian._politica("ferramenta", nome_ferramenta, ws["nome"])
        if pol and pol["decisao"] == "permitir":
            return True
    except Exception:
        pass
    return False


def salvar_sessao(nome, notas=""):
    ws = obter(nome)
    s = ws["sessao"]
    s.update({"salvo": datetime.now().isoformat(timespec="seconds"), "notas": notas})
    c = _con()
    c.execute("UPDATE workspaces SET sessao=? WHERE nome=?", (json.dumps(s, ensure_ascii=False), ws["nome"]))
    c.commit()
    return s


def restaurar_sessao(nome):
    """O que estava em andamento neste WorkSpace (dados reais de cada módulo)."""
    ws = obter(nome)
    r = {"workspace": ws["nome"], "projeto": ws["projeto"], "diretorio": ws["diretorio"], "notas": ws["sessao"].get("notas", ""),
         "salvo": ws["sessao"].get("salvo")}
    try:
        from modulos import vector
        r["planos"] = [p for p in vector.listar(30) if p["estado"] in ("executando", "pausado", "interrompido", "planejado")
                       and (not ws["projeto"] or p["projeto"] in (ws["projeto"], None))][:6]
    except Exception:
        r["planos"] = []
    try:
        from modulos import claude_bridge
        r["claude"] = [t for t in claude_bridge.listar(20) if ws["diretorio"] and t["diretorio"] and
                       t["diretorio"].startswith(ws["diretorio"].rstrip("/"))][:5]
    except Exception:
        r["claude"] = []
    try:
        from core import chronos
        ini, fim = chronos.periodo("últimos 14 dias")
        r["atividades"] = chronos.atividades(ini, fim, projeto=ws["projeto"], limite=12) if ws["projeto"] else []
    except Exception:
        r["atividades"] = []
    try:
        from neuralink import banco
        r["documentos"] = [dict(x) for x in banco.conexao().execute(
            "SELECT titulo, caminho FROM documentos WHERE projeto=? ORDER BY indexado DESC LIMIT 10", (ws["projeto"],))] \
            if ws["projeto"] else []
    except Exception:
        r["documentos"] = []
    return r


def linha_para_prompt():
    """Uma linha para o contexto do pedido: qual WorkSpace está ativo."""
    nome = atual()
    if not nome:
        return ""
    try:
        ws = obter(nome)
    except ValueError:
        return ""
    return (f"[WorkSpace ativo: {ws['nome']} ({ws['tipo']})"
            + (f", projeto {ws['projeto']}" if ws["projeto"] else "")
            + (f", diretório {ws['diretorio']}" if ws["diretorio"] else "")
            + (f", skills: {', '.join(ws['skills'])}" if ws["skills"] else "")
            + (f", plugins MCP: {', '.join(ws['mcps'])}" if ws["mcps"] else "") + "]\n")
