"""Ultron in Chrome: ponte entre o Ultron e a extensão do navegador (Brave/Chrome).

    uv run ultron.py --navegador      # ou o serviço systemd ultron-navegador.service

Escuta só em 127.0.0.1 (porta navegador.porta, padrão 8766):
  - WS  /extensao   a extensão conecta aqui (token + origem chrome-extension://).
  - POST /comando   qualquer processo do Ultron (janela, Telegram, voz) manda uma ação
                    para o navegador: {"acao", "args"} com o cabeçalho X-Ultron-Token.
  - GET  /estado    {"conectado": bool}

A extensão também tem um painel lateral de conversa: o texto vai para um Cerebro
próprio deste processo, que usa as ferramentas navegador_* (ferramentas/navegador.py)
e pergunta as confirmações N2/N3 no próprio painel.

Segurança: WebSocket não tem CORS, então qualquer página poderia tentar abrir
ws://127.0.0.1. Por isso a conexão exige o token (dados/navegador.token, 0600) e a
origem de extensão. O token é colado uma vez nas opções da extensão.
"""
import asyncio
import contextlib
import json
import logging
import os
import secrets
import uuid

from core.config import DADOS, ajuste

LOG = logging.getLogger("ultron.navegador")
ARQ_TOKEN = DADOS / "navegador.token"


def porta():
    return int(ajuste("navegador.porta", 8766))


def token():
    """Cria o token na primeira vez (só o dono do arquivo lê)."""
    if not ARQ_TOKEN.exists():
        ARQ_TOKEN.write_text(secrets.token_urlsafe(24))
        os.chmod(ARQ_TOKEN, 0o600)
    return ARQ_TOKEN.read_text().strip()


def _origem_ok(origem):
    return (origem or "").startswith("chrome-extension://")


class Ponte:
    def __init__(self):
        self.ws = None
        self.loop = None
        self.pendentes = {}          # id -> asyncio.Future (comandos e confirmações)
        self.cerebro = None
        self.trava_chat = None

    # ------------------------------------------------------------- envio
    async def _enviar(self, msg):
        if not self.ws:
            raise ConnectionError("a extensão Ultron in Chrome não está conectada (o Brave está aberto?)")
        await self.ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def pedir(self, tipo, dados, timeout):
        """Manda algo à extensão e espera a resposta com o mesmo id."""
        mid = uuid.uuid4().hex[:12]
        fut = self.loop.create_future()
        self.pendentes[mid] = fut
        try:
            await self._enviar({"tipo": tipo, "id": mid} | dados)
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pendentes.pop(mid, None)

    async def comando(self, acao, args, timeout=30):
        r = await self.pedir("comando", {"acao": acao, "args": args or {}}, timeout)
        if not r.get("ok"):
            raise RuntimeError(r.get("erro") or "falhou no navegador")
        return r.get("resultado")

    # ------------------------------------------------------------- cérebro do painel
    def _confirmar(self, acao, nivel="N2"):
        """Chamado da thread do cérebro: pergunta no painel lateral e espera."""
        pin = str(ajuste("telegram.pin") or "")
        espera = float(ajuste("navegador.tempo_confirmacao", 120))
        try:
            r = asyncio.run_coroutine_threadsafe(
                self.pedir("confirmar", {"acao": acao, "nivel": nivel, "pin": bool(nivel == "N3" and pin)}, espera),
                self.loop).result(espera + 5)
        except Exception:
            return "nao"
        resp = r.get("resposta", "nao")
        if nivel == "N3" and pin:
            if resp != pin:
                from core import auditoria
                auditoria.registrar("pin_errado", acao=acao, origem="navegador")
                return "nao"
            return "sim"
        if resp == "sempre" and nivel == "N3":
            return "sim"
        return resp if resp in ("sim", "nao", "sempre") else "nao"

    def _avisar(self, texto):
        try:
            asyncio.run_coroutine_threadsafe(self._enviar({"tipo": "progresso", "texto": str(texto)}), self.loop)
        except Exception:
            pass

    async def chat(self, mid, texto, aba):
        if texto.split()[:1] and texto.split()[0].lower() in ("/autoaprovar", "/autoaprove"):
            from core import autoaprovar          # comando do Davi: não passa pelo modelo
            try:
                resposta = autoaprovar.comando(texto.partition(" ")[2] or "status")
            except ValueError as e:
                resposta = str(e)
            await self._enviar({"tipo": "chat_resposta", "id": mid, "texto": resposta})
            return
        async with self.trava_chat:
            try:
                if self.cerebro is None:
                    from core.cerebro import Cerebro
                    self.cerebro = await asyncio.to_thread(Cerebro, self._confirmar, self._avisar)
                ctx = "[via Ultron in Chrome, painel lateral do navegador"
                if aba:
                    ctx += f"; aba ativa: {aba.get('titulo', '')[:120]} — {aba.get('url', '')[:300]}"
                ctx += "] "
                resposta = await asyncio.to_thread(self.cerebro.responder, ctx + texto)
            except Exception as e:
                LOG.exception("falha no chat do navegador")
                resposta = f"Algo falhou aqui: {e}"
            await self._enviar({"tipo": "chat_resposta", "id": mid, "texto": resposta})


def app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, WebSocketRoute

    ponte = Ponte()
    tok = token()

    @contextlib.asynccontextmanager
    async def ciclo(_app):
        ponte.loop = asyncio.get_running_loop()
        ponte.trava_chat = asyncio.Lock()
        yield

    async def extensao(ws):
        if not _origem_ok(ws.headers.get("origin")) or not secrets.compare_digest(
                ws.query_params.get("token", ""), tok):
            await ws.accept()               # aceita só para dizer o motivo (4401) e fecha
            await ws.close(code=4401)
            return
        await ws.accept()
        if ponte.ws:
            try:
                await ponte.ws.close(code=4000)
            except Exception:
                pass
        ponte.ws = ws
        LOG.info("extensão conectada")
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                tipo = msg.get("tipo")
                if tipo in ("resposta", "confirmacao"):
                    fut = ponte.pendentes.get(msg.get("id"))
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif tipo == "chat":
                    asyncio.create_task(ponte.chat(msg.get("id"), str(msg.get("texto", ""))[:4000], msg.get("aba")))
                elif tipo == "ping":
                    await ws.send_text('{"tipo":"pong"}')
        except Exception:
            pass
        finally:
            if ponte.ws is ws:
                ponte.ws = None
                for f in ponte.pendentes.values():
                    if not f.done():
                        f.set_exception(ConnectionError("a extensão desconectou"))
            LOG.info("extensão desconectada")

    def _autorizado(req):
        return req.client.host in ("127.0.0.1", "::1") and secrets.compare_digest(
            req.headers.get("x-ultron-token", ""), tok)

    async def comando(req):
        if not _autorizado(req):
            return JSONResponse({"ok": False, "erro": "não autorizado"}, status_code=401)
        d = await req.json()
        try:
            r = await ponte.comando(d["acao"], d.get("args"), float(d.get("timeout", 30)))
            return JSONResponse({"ok": True, "resultado": r})
        except asyncio.TimeoutError:
            return JSONResponse({"ok": False, "erro": "o navegador não respondeu a tempo"})
        except Exception as e:
            return JSONResponse({"ok": False, "erro": str(e)})

    async def estado(req):
        if not _autorizado(req):
            return JSONResponse({"ok": False}, status_code=401)
        return JSONResponse({"ok": True, "conectado": ponte.ws is not None})

    return Starlette(routes=[WebSocketRoute("/extensao", extensao), Route("/comando", comando, methods=["POST"]),
                             Route("/estado", estado)], lifespan=ciclo)


def rodar():
    import uvicorn
    token()
    print(f"Ultron in Chrome: ponte em 127.0.0.1:{porta()}. Token em {ARQ_TOKEN}.")
    uvicorn.run(app(), host="127.0.0.1", port=porta(), log_level="warning", ws="websockets-sansio")


# ------------------------------------------------------------------ cliente (outros processos)

def enviar(acao, args=None, timeout=30):
    """Usado pelas ferramentas: manda uma ação à extensão através da ponte."""
    import requests
    try:
        r = requests.post(f"http://127.0.0.1:{porta()}/comando", timeout=timeout + 5,
                          headers={"X-Ultron-Token": token()},
                          json={"acao": acao, "args": args or {}, "timeout": timeout})
    except requests.ConnectionError:
        raise RuntimeError("a ponte do navegador não está rodando (systemctl --user start ultron-navegador)")
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError(d.get("erro") or "falhou no navegador")
    return d.get("resultado")
