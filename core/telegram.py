"""Ultron no celular via bot do Telegram.

O bot faz long polling (conexão de saída até o Telegram), então funciona de
qualquer lugar sem abrir portas no roteador. Só obedece ao chat do dono
(telegram.dono_id); qualquer outra pessoa recebe uma recusa.

Aceita texto e mensagens de voz (transcritas localmente pelo Whisper) e
responde em texto e, opcionalmente, com áudio na voz do Ultron.
"""
import logging
import subprocess
import tempfile
import time

import numpy as np
import requests

from core import auditoria
from core.registro import interpretar
from core.config import ajuste, segredo

LOG = logging.getLogger("ultron.telegram")

API = "https://api.telegram.org/bot{}/{}"
ARQ = "https://api.telegram.org/file/bot{}/{}"


class Telegram:
    def __init__(self):
        self.token = segredo("TELEGRAM_TOKEN")
        if not self.token:
            raise RuntimeError("Falta TELEGRAM_TOKEN no .env (crie o bot com o @BotFather).")
        self.dono = ajuste("telegram.dono_id")
        self.offset = None
        self._whisper = None
        self.sessao = requests.Session()

    # ----------------------------------------------------------- API básica
    def _api(self, metodo, timeout=40, **dados):
        # A conexão com o Telegram às vezes reseta: tenta de novo algumas vezes.
        for tentativa in range(4):
            try:
                r = self.sessao.post(API.format(self.token, metodo), timeout=timeout, **dados)
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                if tentativa == 3:
                    raise
                LOG.warning("Telegram %s: %s; tentando de novo", metodo, type(e).__name__)
                self.sessao = requests.Session()
                for arq in (dados.get("files") or {}).values():
                    arq[1].seek(0)
                time.sleep(1 + tentativa * 2)
        corpo = r.json()
        if not corpo.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {corpo.get('description')}")
        return corpo["result"]

    def enviar(self, texto, chat=None, botoes=None):
        dados = {"chat_id": chat or self.dono, "text": texto[:4000]}
        if botoes:
            dados["reply_markup"] = {"inline_keyboard": [botoes]}
        return self._api("sendMessage", json=dados)

    def enviar_voz(self, texto, chat=None):
        from core import voz
        audio, taxa = voz.sintetizar(texto)
        if audio is None:
            return
        with tempfile.NamedTemporaryFile(suffix=".ogg") as ogg:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(taxa), "-ac", "1",
                 "-i", "-", "-c:a", "libopus", "-b:a", "32k", ogg.name],
                input=audio.tobytes(), check=True)
            with open(ogg.name, "rb") as f:
                self._api("sendVoice", data={"chat_id": chat or self.dono},
                          files={"voice": ("ultron.ogg", f, "audio/ogg")}, timeout=60)

    def _atualizacoes(self, espera=30):
        params = {"timeout": espera, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            params["offset"] = self.offset
        upds = self._api("getUpdates", timeout=espera + 10, json=params)
        if upds:
            self.offset = upds[-1]["update_id"] + 1
        return upds

    # ----------------------------------------------------------- voz -> texto
    def _transcrever(self, file_id):
        info = self._api("getFile", json={"file_id": file_id})
        bruto = requests.get(ARQ.format(self.token, info["file_path"]), timeout=60).content
        pcm = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", "-", "-f", "s16le", "-ar", "16000", "-ac", "1", "-"],
            input=bruto, capture_output=True, check=True).stdout
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(ajuste("telegram.whisper", "base"),
                                         device="cpu", compute_type="int8")
        from core.ouvido import _hotwords, _preparar, corrigir, vocabulario
        segs, _ = self._whisper.transcribe(_preparar(audio), language="pt",
                                           beam_size=int(ajuste("whisper.beam", 3)), vad_filter=True,
                                           initial_prompt=vocabulario(), hotwords=_hotwords(),
                                           condition_on_previous_text=False)
        return corrigir(" ".join(s.text.strip() for s in segs).strip())

    # ----------------------------------------------------------- confirmação
    def confirmar(self, acao, nivel):
        """Pergunta no chat e espera o dono responder (botões ou PIN)."""
        pin = str(ajuste("telegram.pin") or "")
        if nivel == "N3" and pin:
            self.enviar(f"⚠ Ação crítica: {acao}.\nDigite o PIN para confirmar (ou 'não').")
        else:
            botoes = [{"text": "✅ Sim", "callback_data": "sim"},
                      {"text": "❌ Não", "callback_data": "nao"}]
            if nivel == "N2":
                botoes.append({"text": "Sempre", "callback_data": "sempre"})
            self.enviar(f"⚠ Confirma: {acao}?", botoes=botoes)

        limite = time.time() + ajuste("telegram.tempo_confirmacao", 120)
        while time.time() < limite:
            for u in self._atualizacoes(espera=20):
                cb = u.get("callback_query")
                if cb and cb["from"]["id"] == self.dono:
                    self._api("answerCallbackQuery", json={"callback_query_id": cb["id"]})
                    if nivel == "N3" and pin:
                        continue  # com PIN, botões antigos não valem
                    resp = cb.get("data", "nao")
                    return "sim" if resp == "sempre" and nivel == "N3" else resp
                msg = u.get("message")
                if msg and msg["from"]["id"] == self.dono and "text" in msg:
                    t = msg["text"].strip()
                    if nivel == "N3" and pin:
                        ok = t == pin
                        if not ok:
                            self.enviar("PIN incorreto. Ação cancelada.")
                            auditoria.registrar("pin_errado", acao=acao)
                        return "sim" if ok else "nao"
                    resp = interpretar(t)
                    return "sim" if resp == "sempre" and nivel == "N3" else resp
        self.enviar("Sem resposta. Ação cancelada.")
        return "nao"

    # ----------------------------------------------------------- loop principal
    def rodar(self):
        from core.cerebro import Cerebro
        cerebro = Cerebro(self.confirmar, avisar=lambda _f: self._digitando())
        responder_com_voz = ajuste("telegram.responder_com_voz", "quando_receber_voz")
        print("Ultron no Telegram: aguardando mensagens. Ctrl+C encerra.")
        from core import agenda
        agenda.iniciar_agendador()  # avisa lembretes mesmo com o notebook sem o Ultron aberto
        if self.dono:
            try:
                self.enviar("Ultron online.")
            except Exception as e:
                LOG.warning("não consegui avisar o dono: %s", e)
        while True:
            try:
                upds = self._atualizacoes()
            except Exception as e:
                LOG.warning("erro no polling: %s", e)
                time.sleep(5)
                continue
            for u in upds:
                msg = u.get("message")
                if not msg:
                    continue
                remetente, chat = msg["from"]["id"], msg["chat"]["id"]
                if not self.dono:
                    self.enviar(f"Ainda não tenho dono. Seu ID é {remetente}: coloque em "
                                "telegram.dono_id no config.yaml e reinicie.", chat=chat)
                    continue
                if remetente != self.dono:
                    auditoria.registrar("telegram_estranho", de=remetente,
                                        nome=msg["from"].get("username"))
                    self.enviar("Eu não falo com estranhos.", chat=chat)
                    continue
                try:
                    self._tratar(msg, cerebro, responder_com_voz)
                except Exception as e:
                    LOG.exception("falha ao tratar mensagem")
                    self.enviar(f"Algo falhou aqui: {e}")

    def _digitando(self):
        try:
            self._api("sendChatAction", json={"chat_id": self.dono, "action": "typing"}, timeout=10)
        except Exception:
            pass

    def _tratar(self, msg, cerebro, responder_com_voz):
        veio_voz = "voice" in msg or "audio" in msg
        if veio_voz:
            self._digitando()
            texto = self._transcrever((msg.get("voice") or msg.get("audio"))["file_id"])
            if not texto:
                self.enviar("Não entendi o áudio.")
                return
            self.enviar(f"🎙 {texto}")
        else:
            texto = msg.get("text", "").strip()
        if not texto:
            return
        if texto.split()[0].lower() in ("/autoaprovar", "/autoaprove"):
            from core import autoaprovar
            try:
                self.enviar(autoaprovar.comando(texto.partition(" ")[2] or "status"))
            except ValueError as e:
                self.enviar(str(e))
            return
        if texto == "/start":
            self.enviar("Ultron às ordens. Mande texto ou áudio.")
            return
        self._digitando()
        resposta = cerebro.responder(f"[via Telegram, o usuário está fora de casa] {texto}")
        self.enviar(resposta)
        if responder_com_voz == "sempre" or (responder_com_voz == "quando_receber_voz" and veio_voz):
            try:
                self.enviar_voz(resposta)
            except Exception as e:
                LOG.warning("falha ao enviar voz: %s", e)
