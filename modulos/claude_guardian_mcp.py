"""Servidor MCP (stdio) que o Claude Code chama antes de cada ação (--permission-prompt-tool).

Ferramenta 'autorizar(tool_name, input)' -> texto JSON
  {"behavior": "allow", "updatedInput": {...}}   ou   {"behavior": "deny", "message": "..."}
A decisão é do Guardian (modulos.claude_bridge.decidir_ferramenta). Quando a resposta é
'perguntar', o pedido aparece na aba CLAUDE BRIDGE do Ultron e este servidor espera a
decisão do Davi (até claude_bridge.espera_aprovacao_s); sem resposta, nega.
Variáveis: ULTRON_TAREFA (tarefa), ULTRON_CWD (diretório isolado da tarefa).
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from core import eventos  # noqa: E402
from modulos import claude_bridge as cb  # noqa: E402

servidor = MCPServer("ultron_guardian")
TAREFA = os.environ.get("ULTRON_TAREFA", "?")
CWD = os.environ.get("ULTRON_CWD", os.getcwd())


def _resposta(permitir, entrada=None, motivo=""):
    if permitir:
        return json.dumps({"behavior": "allow", "updatedInput": entrada or {}})
    return json.dumps({"behavior": "deny", "message": f"Negado pelo Guardian do Ultron: {motivo}"})


@servidor.tool()
async def autorizar(tool_name: str, input: dict, tool_use_id: str | None = None) -> str:
    """Decide se o Claude Code pode executar uma ação (Guardian do Ultron)."""
    decisao, motivo = cb.decidir_ferramenta(tool_name, input, CWD)
    cb._evento(TAREFA, "permissao", {"ferramenta": tool_name, "decisao": decisao, "motivo": motivo})
    if decisao == "permitir":
        return _resposta(True, input)
    if decisao == "negar":
        eventos.emitir("approval.denied", "guardian", {"ferramenta": tool_name, "motivo": motivo}, correlacao=TAREFA)
        return _resposta(False, motivo=motivo)
    aid = f"ca_{uuid.uuid4().hex[:8]}"
    c = cb._con()
    c.execute("INSERT INTO claude_aprovacoes(id, tarefa, ferramenta, entrada, motivo, criado) VALUES (?,?,?,?,?,?)",
              (aid, TAREFA, tool_name, json.dumps(eventos.limpar(input), ensure_ascii=False), motivo, cb._agora()))
    c.commit()
    eventos.emitir("approval.requested", "claude_bridge", {"pedido": aid, "ferramenta": tool_name, "motivo": motivo,
                                                           "entrada": input}, correlacao=TAREFA)
    limite = float(cb.cfg("espera_aprovacao_s", 300))
    passou = 0.0
    while passou < limite:
        r = cb._con().execute("SELECT estado FROM claude_aprovacoes WHERE id=?", (aid,)).fetchone()
        if r and r[0] != "pendente":
            return _resposta(r[0] == "permitida", input, "o Davi negou")
        await asyncio.sleep(1)
        passou += 1
    c = cb._con()
    c.execute("UPDATE claude_aprovacoes SET estado='expirada' WHERE id=? AND estado='pendente'", (aid,))
    c.commit()
    return _resposta(False, motivo="ninguém aprovou a tempo")


if __name__ == "__main__":
    servidor.run("stdio")
