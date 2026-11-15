"""Plugins MCP: o Ultron como CLIENTE de servidores MCP (GitHub, Notion, Gmail...).

Os servidores ficam em plugins.yaml. Cada um só é iniciado quando o Ultron
precisa dele (economiza memória) e fica conectado depois disso.

Um plugin fica disponível quando todas as variáveis em "requer" existem no
.env. Valores ${VAR} em args/env/url/cabecalhos são trocados pelo .env.

Nível de permissão de cada ferramenta MCP (para as confirmações do Ultron):
  - "nivel" fixo no plugin (N1/N2/N3), ou
  - automático: read_only_hint -> N1; destructive_hint -> N3; o resto -> N2.
"""
import asyncio
import contextlib
import logging
import os
import re
import shutil
import threading
from pathlib import Path

import yaml

from core.config import RAIZ

LOG = logging.getLogger("ultron.plugins")
ARQ = RAIZ / "plugins.yaml"
TEMPO_CONEXAO = 120   # npx/uvx podem baixar o pacote na primeira vez


def _expandir(valor):
    if isinstance(valor, str):
        valor = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), valor)
        return os.path.expanduser(valor) if valor.startswith("~") else valor
    if isinstance(valor, list):
        return [_expandir(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _expandir(v) for k, v in valor.items()}
    return valor


def configuracao():
    try:
        return yaml.safe_load(ARQ.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


def faltando(cfg):
    """Variáveis do .env que o plugin exige e ainda não existem."""
    return [v for v in cfg.get("requer", []) or [] if not os.environ.get(v)]


def disponivel(cfg):
    return cfg.get("ativo", True) and not faltando(cfg)


class _Gerente:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="plugins").start()
        self.sessoes = {}       # nome -> ClientSession
        self.pilhas = {}        # nome -> AsyncExitStack
        self.ferramentas = {}   # nome -> [types.Tool]
        self.instrucoes = {}    # nome -> instruções que o servidor manda no initialize
        self.travas = {}

    def _rodar(self, coro, timeout=TEMPO_CONEXAO + 60):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _conectar(self, nome):
        from mcp import ClientSession, StdioServerParameters
        cfg = configuracao().get(nome)
        if not cfg:
            validos = [n for n, c in configuracao().items() if disponivel(c)]
            raise ValueError(f"plugin '{nome}' não existe. Prontos: {', '.join(validos)}")
        if not cfg.get("ativo", True):
            raise RuntimeError(f"plugin '{nome}' está desativado no plugins.yaml")
        if faltando(cfg):
            raise RuntimeError(f"plugin '{nome}' precisa de {', '.join(faltando(cfg))} no .env")
        cfg = _expandir(cfg)
        pilha = contextlib.AsyncExitStack()
        try:
            if cfg.get("url"):
                from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
                http = await pilha.enter_async_context(
                    create_mcp_http_client(headers=cfg.get("cabecalhos") or {}))
                streams = await pilha.enter_async_context(
                    streamable_http_client(cfg["url"], http_client=http))
            else:
                from mcp.client.stdio import stdio_client
                comando = cfg["comando"]
                if not shutil.which(comando):
                    raise RuntimeError(f"comando '{comando}' não instalado")
                env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
                params = StdioServerParameters(command=comando, args=[str(a) for a in cfg.get("args", [])],
                                               env=env, cwd=str(RAIZ))
                log_erros = open(RAIZ / "dados" / f"plugin-{nome}.log", "a")
                pilha.callback(log_erros.close)
                streams = await pilha.enter_async_context(stdio_client(params, errlog=log_erros))
            sessao = await pilha.enter_async_context(ClientSession(streams[0], streams[1]))
            inicio = await asyncio.wait_for(sessao.initialize(), TEMPO_CONEXAO)
            ferramentas = (await sessao.list_tools()).tools
            self.instrucoes[nome] = (getattr(inicio, "instructions", None) or "").strip()
        except BaseException:
            await pilha.aclose()
            raise
        self.sessoes[nome], self.pilhas[nome], self.ferramentas[nome] = sessao, pilha, ferramentas
        LOG.info("plugin %s conectado (%d ferramentas)", nome, len(ferramentas))

    async def _garantir(self, nome):
        trava = self.travas.setdefault(nome, asyncio.Lock())
        async with trava:
            if nome not in self.sessoes:
                await self._conectar(nome)

    def listar_ferramentas(self, nome):
        self._rodar(self._garantir(nome))
        return self.ferramentas[nome]

    def chamar(self, nome, ferramenta, argumentos):
        async def _c():
            await self._garantir(nome)
            nomes = [t.name for t in self.ferramentas.get(nome, [])]
            if ferramenta not in nomes:
                raise ValueError(f"'{ferramenta}' não existe em {nome}. Ferramentas: {', '.join(nomes)}")
            try:
                return await self.sessoes[nome].call_tool(ferramenta, argumentos or {})
            except Exception:
                # conexão caiu: reconecta uma vez
                await self.desconectar(nome)
                await self._garantir(nome)
                return await self.sessoes[nome].call_tool(ferramenta, argumentos or {})
        return self._rodar(_c())

    async def desconectar(self, nome):
        pilha = self.pilhas.pop(nome, None)
        self.sessoes.pop(nome, None)
        self.ferramentas.pop(nome, None)
        if pilha:
            with contextlib.suppress(Exception):
                await pilha.aclose()

    def fechar_tudo(self):
        for nome in list(self.pilhas):
            with contextlib.suppress(Exception):
                self._rodar(self.desconectar(nome), timeout=10)


_gerente = None
_trava = threading.Lock()


def gerente():
    global _gerente
    with _trava:
        if _gerente is None:
            _gerente = _Gerente()
        return _gerente


def nivel_da_ferramenta(plugin, ferramenta):
    cfg = configuracao().get(plugin, {})
    fixo = cfg.get("nivel")
    if fixo in ("N1", "N2", "N3"):
        return fixo
    por_ferramenta = (cfg.get("niveis") or {}).get(ferramenta)
    if por_ferramenta:
        return por_ferramenta
    g = gerente()
    for t in g.ferramentas.get(plugin, []):
        if t.name == ferramenta and t.annotations:
            if t.annotations.read_only_hint:
                return "N1"
            if t.annotations.destructive_hint:
                return "N3"
    return "N2"


def texto_do_resultado(r):
    partes = []
    for c in r.content or []:
        if getattr(c, "type", "") == "text":
            partes.append(c.text)
        elif getattr(c, "type", "") == "image":
            partes.append("[imagem]")
        else:
            partes.append(f"[{getattr(c, 'type', 'conteúdo')}]")
    if not partes and getattr(r, "structured_content", None):
        partes.append(str(r.structured_content))
    texto = "\n".join(partes) or "(sem conteúdo)"
    return texto[:6000] + ("\n...(cortado)" if len(texto) > 6000 else "")
