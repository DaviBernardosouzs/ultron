"""Registro de ferramentas (inspirado no core/registre.py do Jarvis).

Cada ferramenta é uma função decorada com @ferramenta dentro de ferramentas/.
Níveis de permissão:
  N1 (seguro)   : executa direto (ler status, escanear a rede, ping...).
  N2 (sensível) : pede confirmação; o usuário pode responder "sempre" para
                  não ser mais perguntado (revogável em config.yaml).
  N3 (crítico)  : pede confirmação SEMPRE (desligar máquinas, comandos de shell).
"""
import importlib
import logging
import pkgutil
import re

from core import auditoria
from core.config import ajuste, definir

LOG = logging.getLogger("ultron.registro")

_REGISTRO = {}
_confirmador = None     # quem responde confirmações em execuções de fundo (Vector, Macro Forge)


def definir_confirmador(funcao):
    """O cérebro ativo registra a sua forma de perguntar (janela, Telegram ou terminal)."""
    global _confirmador
    _confirmador = funcao


def confirmador():
    return _confirmador

NAO_CONFIAVEL = "[CONTEUDO EXTERNO NAO CONFIAVEL]\n"


class Ferramenta:
    def __init__(self, funcao, nome, descricao, parametros, nivel, resumo, nivel_dinamico=None):
        self.funcao = funcao
        self.nome = nome
        self.descricao = descricao
        self.parametros = parametros
        self.nivel = nivel
        self.resumo = resumo  # fn(args) -> frase usada na pergunta de confirmação
        # fn(args) -> (nivel, chave): nível que depende dos argumentos (plugins MCP).
        self.nivel_dinamico = nivel_dinamico


def ferramenta(nome, descricao, parametros=None, nivel="N1", resumo=None, nivel_dinamico=None):
    def deco(funcao):
        _REGISTRO[nome] = Ferramenta(
            funcao, nome, descricao,
            parametros or {"type": "object", "properties": {}},
            nivel, resumo, nivel_dinamico)
        return funcao
    return deco


def carregar():
    """Importa todos os módulos de ferramentas/. Um módulo quebrado não derruba os outros."""
    import ferramentas
    falhas = []
    for mod in pkgutil.iter_modules(ferramentas.__path__):
        try:
            importlib.import_module(f"ferramentas.{mod.name}")
        except Exception as e:
            falhas.append(mod.name)
            LOG.warning("ferramenta %s não carregada: %s", mod.name, e, exc_info=True)
    return falhas


def todas():
    return list(_REGISTRO.values())


def obter(nome):
    return _REGISTRO.get(nome)


def schemas():
    return [{"name": f.nome, "description": f.descricao, "input_schema": f.parametros}
            for f in _REGISTRO.values()]


def nivel_e_chave(f, args=None):
    """Nível efetivo e a chave usada no "sempre autorizar"."""
    if f.nivel_dinamico:
        try:
            return f.nivel_dinamico(args or {})
        except Exception:
            return "N3", f.nome
    return f.nivel, f.nome


def nivel_de(f, args=None):
    return nivel_e_chave(f, args)[0]


def decisao(f, args=None):
    """Pergunta ao Guardian: {"decisao": permitir|perguntar|negar, "motivo", "politica"}."""
    from core import guardian
    nivel, chave = nivel_e_chave(f, args)
    try:
        from core import workspaces
        if workspaces.ferramenta_permitida(f.nome, f.funcao.__module__) is False and not (
                _autoaprovar() or _ordem(nivel)):
            return {"decisao": "negar", "politica": None,
                    "motivo": f"ferramenta fora do WorkSpace ativo ({workspaces.atual()})"}
    except Exception:
        pass
    try:
        return guardian.autorizar("ferramenta", f.nome, nivel, {"chave": chave})
    except Exception as e:      # Guardian quebrado: na dúvida, pergunta (nunca libera N2/N3)
        LOG.warning("Guardian indisponível: %s", e)
        return {"decisao": "permitir" if nivel == "N1" else "perguntar", "motivo": "fallback", "politica": None}


def _autoaprovar():
    try:
        from core import autoaprovar
        return autoaprovar.ativo()
    except Exception:
        return False


def _ordem(nivel):
    try:
        from core import ordem
        return ordem.pula_confirmacao(nivel)
    except Exception:
        return False


def precisa_confirmar(f, args=None):
    return decisao(f, args)["decisao"] == "perguntar" and not _autoaprovar()


def _sentir(evento):
    try:
        from core import emocoes
        emocoes.reagir(evento)
    except Exception:
        pass


def lembrar_sempre(f, args=None):
    if isinstance(f, str):
        f = _REGISTRO.get(f)
    if not f:
        return False
    nivel, chave = nivel_e_chave(f, args)
    if nivel != "N2":
        return False
    atuais = list(ajuste("seguranca.sempre", []) or [])
    if chave not in atuais:
        atuais.append(chave)
        definir("seguranca.sempre", atuais)
    return True


def descrever(f, args):
    if f.resumo:
        try:
            return f.resumo(args)
        except Exception:
            pass
    return f"executar {f.nome} com {args}"


def executar(f, args):
    """Executa a ferramenta; devolve (texto, erro?). Ferramentas negadas pelo Guardian não rodam."""
    import time
    from core import eventos
    d = decisao(f, args)
    if d["decisao"] == "negar":
        from core import guardian
        guardian.incidente("ferramenta_negada", f"{f.nome}: {d['motivo']}", "media", "registro")
        eventos.emitir("tool.failed", "registro", {"ferramenta": f.nome, "erro": "negada pelo Guardian",
                                                   "motivo": d["motivo"]})
        try:
            pid = guardian.pedir_permissao("ferramenta", f.nome, d["motivo"], pedido_por="guardian",
                                           chamada={"ferramenta": f.nome, "args": args or {}})
        except Exception:
            pid = None
        return (f"Bloqueado pelo Guardian: {d['motivo']}. "
                + (f"Já abri o pedido {pid} com esta chamada: quando o Davi aprovar (ultron modulos), ela é "
                   "executada sozinha e o resultado chega para ele no Telegram. Não abra outro pedido."
                   if pid else "Só o Davi muda isso, no painel do Guardian.")), True
    auditoria.registrar("executar", ferramenta=f.nome, nivel=f.nivel, args=args)
    ini = eventos.emitir("tool.started", "registro", {"ferramenta": f.nome, "nivel": nivel_de(f, args),
                                                      "args": args})
    t0 = time.time()
    try:
        resultado = f.funcao(**(args or {}))
        eventos.emitir("tool.completed", "registro", {"ferramenta": f.nome, "ms": int((time.time() - t0) * 1000),
                                                      "tamanho": len(str(resultado))}, pai=ini["id"])
        return str(resultado), False
    except TypeError as e:
        eventos.emitir("tool.failed", "registro", {"ferramenta": f.nome, "erro": f"argumentos: {e}"}, pai=ini["id"])
        return f"Argumentos inválidos para {f.nome}: {e}", True
    except Exception as e:
        LOG.exception("falha em %s", f.nome)
        auditoria.registrar("erro", ferramenta=f.nome, erro=str(e))
        eventos.emitir("tool.failed", "registro", {"ferramenta": f.nome, "erro": str(e)}, pai=ini["id"])
        return f"Erro ao executar {f.nome}: {e}", True


def executar_protegido(f, args, confirmar, acoes=None, ao_executar=None):
    """O caminho completo de uma chamada do modelo: Guardian, confirmação humana, execução.
    Devolve (texto, erro?). Usado pelos dois cérebros (Gemini e Claude)."""
    from core import eventos
    d = decisao(f, args)
    if d["decisao"] == "negar":
        return executar(f, args)          # registra o bloqueio e devolve a mensagem
    if d["decisao"] == "perguntar" and (_autoaprovar() or _ordem(nivel_de(f, args))):
        por = "autoaprovar" if _autoaprovar() else "ordem"
        auditoria.registrar("auto_aprovado", ferramenta=f.nome, args=args, nivel=nivel_de(f, args), por=por)
        eventos.emitir("approval.granted", por, {"ferramenta": f.nome, "nivel": nivel_de(f, args),
                                                 "descricao": descrever(f, args)})
    elif d["decisao"] == "perguntar":
        pedido = eventos.emitir("approval.requested", "registro",
                                {"ferramenta": f.nome, "descricao": descrever(f, args), "nivel": nivel_de(f, args),
                                 "motivo": d["motivo"]})
        resposta = confirmar(descrever(f, args), nivel_de(f, args))
        auditoria.registrar("confirmacao", ferramenta=f.nome, args=args, resposta=resposta)
        if resposta == "nao":
            _sentir("recusado")
            eventos.emitir("approval.denied", "usuario", {"ferramenta": f.nome}, pai=pedido["id"])
            if acoes is not None:
                acoes.append((f.nome, args, "recusado pelo usuário"))
            return "O usuário recusou esta ação. Não tente de novo.", False
        eventos.emitir("approval.granted", "usuario", {"ferramenta": f.nome, "sempre": resposta == "sempre"},
                       pai=pedido["id"])
        if resposta == "sempre":
            lembrar_sempre(f, args)
    if ao_executar:
        ao_executar()
    saida, erro = executar(f, args)
    if erro:
        _sentir("erro")
    if acoes is not None:
        acoes.append((f.nome, args, "erro" if erro else "ok"))
    return saida, erro


def interpretar(resposta):
    """Resposta livre de confirmação -> 'sim' | 'nao' | 'sempre'."""
    t = (resposta or "").lower().strip()
    if re.search(r"\bsempre\b", t):
        return "sempre"
    if re.search(r"\b(sim|s|pode|confirmo|confirma|manda|vai|ok|claro|isso)\b", t):
        return "sim"
    return "nao"
