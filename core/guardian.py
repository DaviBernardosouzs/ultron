"""Guardian: camada de permissões e segurança, independente do orquestrador.

Toda ferramenta passa por autorizar() antes de rodar (core/registro.executar_protegido).
Decisão em ordem:
  1. bloqueios fixos (código, não configuráveis): nunca são liberados;
  2. política explícita do Davi para o workspace atual (ou '*' = todos);
  3. padrão pelo nível da ferramenta: N1 permite, N2 pergunta (a menos que haja
     concessão "sempre"), N3 pergunta SEMPRE (nenhuma política transforma N3 em
     execução direta; dá para endurecer, não para afrouxar).

Também decide sobre caminhos (ler/escrever) e rede para os módulos que mexem em
arquivos (Archive, Claude Bridge...).

O modelo NÃO altera políticas: nenhuma ferramenta escreve aqui. definir_politica,
revogar e responder_pedido são chamados só pela janela/CLI. O modelo pode, no
máximo, abrir um pedido (pedir_permissao) que fica pendente para o Davi.
Tudo vira evento (approval.*) e as negações viram incidentes.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from core import eventos
from core.config import ajuste

DECISOES = ("permitir", "perguntar", "negar")
ACOES = ("ferramenta", "ler_arquivo", "escrever_arquivo", "rede", "comando", "instalar", "mcp",
         "mensagem", "dispositivo", "destrutiva")
# Bloqueios fixos: alvos que nenhuma política libera.
CAMINHOS_PROIBIDOS = ("~/.ssh", "~/.gnupg", "~/.password-store", "~/.config/ultron", "/etc/shadow",
                      "/etc/sudoers")
NOMES_PROIBIDOS = (".env", "id_rsa", "id_ed25519", "ultron.pub")
DIRETORIOS_PADRAO = ["~/Projetos", "~/ultron", "~/ultron-geospatial", "~/Documentos/Ultron Cérebro",
                     "~/Downloads"]


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS politicas (
            id INTEGER PRIMARY KEY, workspace TEXT NOT NULL DEFAULT '*', acao TEXT NOT NULL,
            alvo TEXT NOT NULL, decisao TEXT NOT NULL, motivo TEXT, por TEXT NOT NULL,
            criado TEXT NOT NULL, revogado TEXT, revogado_por TEXT);
        CREATE TABLE IF NOT EXISTS pedidos_permissao (
            id TEXT PRIMARY KEY, workspace TEXT, acao TEXT, alvo TEXT, motivo TEXT,
            pedido_por TEXT, criado TEXT, estado TEXT DEFAULT 'pendente', decidido TEXT, por TEXT);
        CREATE TABLE IF NOT EXISTS incidentes (
            id INTEGER PRIMARY KEY, quando TEXT, severidade TEXT, tipo TEXT, descricao TEXT,
            origem TEXT, correlacao TEXT);""")
    if "chamada" not in {r[1] for r in c.execute("PRAGMA table_info(pedidos_permissao)")}:
        c.execute("ALTER TABLE pedidos_permissao ADD COLUMN chamada TEXT")   # {"ferramenta", "args"} bloqueada
        c.commit()
    return c


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def workspace_atual():
    try:
        from core import workspaces
        return workspaces.atual() or "*"
    except Exception:
        return "*"


# ------------------------------------------------------------------ decisão

def _politica(acao, alvo, workspace):
    c = _con()
    linhas = c.execute("""SELECT * FROM politicas WHERE revogado IS NULL AND acao=? AND (alvo=? OR alvo='*')
                          AND (workspace=? OR workspace='*')
                          ORDER BY (workspace=?) DESC, (alvo=?) DESC, id DESC LIMIT 1""",
                       (acao, alvo, workspace, workspace, alvo)).fetchone()
    if not linhas and acao == "ferramenta" and alvo:
        # política criada no painel com outro tipo (ex.: "dispositivo") mas com o nome exato da
        # ferramenta como alvo: o Davi quis dizer esta ferramenta
        linhas = c.execute("""SELECT * FROM politicas WHERE revogado IS NULL AND alvo=?
                              AND acao NOT IN ('ler_arquivo', 'escrever_arquivo', 'diretorio')
                              AND (workspace=? OR workspace='*') ORDER BY (workspace=?) DESC, id DESC LIMIT 1""",
                           (alvo, workspace, workspace)).fetchone()
    return dict(linhas) if linhas else None


def autorizar(acao, alvo, nivel=None, contexto=None):
    """-> {"decisao", "motivo", "politica"}  (não emite eventos; quem age emite)."""
    contexto = contexto or {}
    ws = contexto.get("workspace") or workspace_atual()
    if acao in ("ler_arquivo", "escrever_arquivo"):
        return autorizar_caminho(alvo, escrita=acao == "escrever_arquivo", workspace=ws)
    pol = _politica(acao, alvo, ws)
    if pol:
        decisao = pol["decisao"]
        if nivel == "N3" and decisao == "permitir":       # N3 não afrouxa
            return {"decisao": "perguntar", "motivo": "ações críticas (N3) sempre pedem confirmação",
                    "politica": pol["id"]}
        return {"decisao": decisao, "motivo": pol["motivo"] or f"política #{pol['id']}", "politica": pol["id"]}
    if nivel == "N1" or (nivel is None and acao == "ferramenta"):
        return {"decisao": "permitir", "motivo": "nível N1", "politica": None}
    if nivel == "N2":
        chave = contexto.get("chave") or alvo
        if chave in (ajuste("seguranca.sempre", []) or []):
            return {"decisao": "permitir", "motivo": "autorizado com 'sempre'", "politica": None}
        return {"decisao": "perguntar", "motivo": "nível N2", "politica": None}
    return {"decisao": "perguntar", "motivo": f"nível {nivel or 'desconhecido'}", "politica": None}


def _dentro(p, base):
    base = Path(os.path.expanduser(base)).resolve()
    return p == base or base in p.parents


def diretorios_permitidos(workspace=None):
    dirs = list(ajuste("guardian.diretorios", DIRETORIOS_PADRAO) or [])
    c = _con()
    ws = workspace or workspace_atual()
    for r in c.execute("""SELECT alvo FROM politicas WHERE revogado IS NULL AND acao='diretorio'
                          AND decisao='permitir' AND (workspace=? OR workspace='*')""", (ws,)):
        dirs.append(r["alvo"])
    return dirs


def autorizar_caminho(caminho, escrita=False, workspace=None):
    p = Path(os.path.expanduser(str(caminho))).resolve()
    if any(_dentro(p, x) for x in CAMINHOS_PROIBIDOS) or p.name in NOMES_PROIBIDOS or p.name.startswith(".env"):
        return {"decisao": "negar", "motivo": "caminho sensível (bloqueio fixo)", "politica": None}
    if not any(_dentro(p, d) for d in diretorios_permitidos(workspace)):
        return {"decisao": "negar", "motivo": "fora dos diretórios autorizados", "politica": None}
    if escrita:
        return {"decisao": "perguntar", "motivo": "escrita em arquivo", "politica": None}
    return {"decisao": "permitir", "motivo": "diretório autorizado", "politica": None}


# ------------------------------------------------------------------ administração (só janela/CLI)

def definir_politica(acao, alvo, decisao, workspace="*", motivo="", por="Davi"):
    if acao not in ACOES and acao != "diretorio":
        raise ValueError(f"ação inválida: {acao}")
    if decisao not in DECISOES:
        raise ValueError(f"decisão inválida: {decisao}")
    c = _con()
    pid = c.execute("""INSERT INTO politicas(workspace, acao, alvo, decisao, motivo, por, criado)
                       VALUES (?,?,?,?,?,?,?)""", (workspace, acao, alvo, decisao, motivo, por, _agora())).lastrowid
    c.commit()
    eventos.emitir("module.status_changed", "guardian",
                   {"modulo": "guardian", "mudanca": "politica", "id": pid, "acao": acao, "alvo": alvo,
                    "decisao": decisao, "workspace": workspace, "por": por})
    return pid


def revogar(pid, por="Davi"):
    c = _con()
    n = c.execute("UPDATE politicas SET revogado=?, revogado_por=? WHERE id=? AND revogado IS NULL",
                  (_agora(), por, pid)).rowcount
    c.commit()
    if n:
        eventos.emitir("module.status_changed", "guardian",
                       {"modulo": "guardian", "mudanca": "revogada", "id": pid, "por": por})
    return bool(n)


def politicas(incluir_revogadas=False):
    q = "SELECT * FROM politicas" + ("" if incluir_revogadas else " WHERE revogado IS NULL") + " ORDER BY id DESC"
    return [dict(r) for r in _con().execute(q)]


def concessoes_sempre():
    return list(ajuste("seguranca.sempre", []) or [])


def revogar_sempre(chave, por="Davi"):
    from core.config import definir
    atuais = [x for x in concessoes_sempre() if x != chave]
    definir("seguranca.sempre", atuais)
    eventos.emitir("module.status_changed", "guardian",
                   {"modulo": "guardian", "mudanca": "sempre_revogado", "chave": chave, "por": por})


# ------------------------------------------------------------------ pedidos e incidentes

def pedir_permissao(acao, alvo, motivo, pedido_por="ultron", workspace=None, chamada=None):
    """O modelo pode PEDIR; só o Davi concede. Um pedido pendente igual é reaproveitado (sem fila
    de duplicatas). chamada = {"ferramenta", "args"}: o que foi bloqueado e roda sozinho ao aprovar."""
    c = _con()
    igual = c.execute("SELECT id FROM pedidos_permissao WHERE estado='pendente' AND acao=? AND alvo=?",
                      (acao, alvo)).fetchone()
    if igual:
        if chamada:
            c.execute("UPDATE pedidos_permissao SET chamada=?, motivo=? WHERE id=?",
                      (json.dumps(chamada, ensure_ascii=False), motivo, igual["id"]))
            c.commit()
        return igual["id"]
    pid = f"P{uuid.uuid4().hex[:8]}"
    c.execute("""INSERT INTO pedidos_permissao(id, workspace, acao, alvo, motivo, pedido_por, criado, chamada)
                 VALUES (?,?,?,?,?,?,?,?)""",
              (pid, workspace or workspace_atual(), acao, alvo, motivo, pedido_por, _agora(),
               json.dumps(chamada, ensure_ascii=False) if chamada else None))
    c.commit()
    eventos.emitir("approval.requested", "guardian", {"pedido": pid, "acao": acao, "alvo": alvo, "motivo": motivo})
    return pid


def pedidos(estado="pendente"):
    return [dict(r) for r in _con().execute("SELECT * FROM pedidos_permissao WHERE estado=? ORDER BY criado DESC", (estado,))]


def responder_pedido(pid, conceder, por="Davi"):
    c = _con()
    p = c.execute("SELECT * FROM pedidos_permissao WHERE id=? AND estado='pendente'", (pid,)).fetchone()
    if not p:
        raise ValueError(f"pedido {pid} não está pendente")
    c.execute("UPDATE pedidos_permissao SET estado=?, decidido=?, por=? WHERE id=?",
              ("concedido" if conceder else "negado", _agora(), por, pid))
    c.commit()
    if conceder:   # vale em qualquer WorkSpace: aprovar tem que resolver, não depender de onde o pedido nasceu
        definir_politica(p["acao"], p["alvo"], "permitir", "*", p["motivo"] or "", por)
    eventos.emitir("approval.granted" if conceder else "approval.denied", "guardian",
                   {"pedido": pid, "acao": p["acao"], "alvo": p["alvo"], "por": por})
    # todos os pendentes iguais têm a mesma resposta
    c.execute("UPDATE pedidos_permissao SET estado=?, decidido=?, por=? WHERE estado='pendente' AND acao=? AND alvo=?",
              ("concedido" if conceder else "negado", _agora(), por, p["acao"], p["alvo"]))
    c.commit()
    if conceder and p["chamada"]:
        import threading
        threading.Thread(target=executar_aprovado, args=(pid, json.loads(p["chamada"])), daemon=True).start()


def executar_aprovado(pid, chamada):
    """Roda a ação que estava bloqueada (o Davi acabou de aprovar exatamente ela) e avisa o resultado."""
    from core import registro
    if not registro.todas():
        registro.carregar()
    f = registro.obter(chamada.get("ferramenta"))
    if not f:
        return None
    saida, erro = registro.executar(f, chamada.get("args") or {})
    eventos.emitir("tool.failed" if erro else "tool.completed", "guardian",
                   {"ferramenta": f.nome, "pedido": pid, "aprovado": True, "resultado": str(saida)[:500]})
    try:
        from core.telegram import Telegram
        Telegram().enviar(f"{'⚠' if erro else '✅'} Aprovado no Guardian, executei {f.nome}:\n"
                          + str(saida).replace("[CONTEUDO EXTERNO NAO CONFIAVEL]\n", "")[:1500])
    except Exception:
        pass
    return saida, erro


def incidente(tipo, descricao, severidade="media", origem="guardian"):
    c = _con()
    c.execute("INSERT INTO incidentes(quando, severidade, tipo, descricao, origem, correlacao) VALUES (?,?,?,?,?,?)",
              (_agora(), severidade, tipo, eventos.limpar(descricao), origem, eventos.correlacao_atual.get()))
    c.commit()


def incidentes(limite=100):
    return [dict(r) for r in _con().execute("SELECT * FROM incidentes ORDER BY id DESC LIMIT ?", (limite,))]
