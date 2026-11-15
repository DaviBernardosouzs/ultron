"""Cliente do servidor MCP "shaco-pc" para o Ultron (roda no notebook Linux).

Requisitos no notebook:
    pip install "mcp>=2"
    ~/.ssh/config com o Host "shaco-pc" (HostName 192.168.1.103, User davib, IdentityFile ~/.ssh/ultron)

Uso básico:
    async with ShacoPC() as pc:
        tools = pc.tools_anthropic()          # ou pc.tools_openai()
        resultado = await pc.call("run_command", {"command": "git status"})
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SSH_HOST = "shaco-pc"
REMOTE_PY = r"C:\Users\davib\ultron\.venv\Scripts\python.exe"
REMOTE_SERVER = r"C:\Users\davib\ultron\pc_mcp_server.py"


class ShacoPC:
    def __init__(self, host: str = SSH_HOST):
        self.params = StdioServerParameters(
            command="ssh",
            args=["-T", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30",
                  host, REMOTE_PY, REMOTE_SERVER],
        )
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tools = []

    async def __aenter__(self) -> "ShacoPC":
        read, write = await self._stack.enter_async_context(stdio_client(self.params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = (await self.session.list_tools()).tools
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    # Esquemas prontos para entregar ao LLM do Ultron
    def tools_anthropic(self) -> list[dict]:
        return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in self.tools]

    def tools_openai(self) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                  "parameters": t.input_schema}}
                for t in self.tools]

    async def call(self, name: str, arguments: dict) -> str:
        """Executa uma ferramenta no PC e devolve o texto do resultado."""
        r = await self.session.call_tool(name, arguments)
        texto = "\n".join(getattr(c, "text", str(c)) for c in r.content)
        return ("ERRO: " + texto) if r.is_error else texto


async def _demo():
    async with ShacoPC() as pc:
        print("Ferramentas:", [t.name for t in pc.tools])
        print(await pc.call("run_command", {"command": "hostname; git -C shaco-ia status --short"}))


if __name__ == "__main__":
    asyncio.run(_demo())
