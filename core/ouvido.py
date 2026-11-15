"""Audição: microfone -> detecção de fala por energia -> faster-whisper (local).

Não existe modelo pronto de wake word "Ultron" no openWakeWord, então a
ativação é feita transcrevendo trechos curtos e procurando a palavra "Ultron"
(com variações que o Whisper costuma escrever).
"""
import logging
import os
import queue
import re
import threading
import time
import unicodedata

import numpy as np
import sounddevice as sd

from core import animacao, voz
from core.config import ajuste

LOG = logging.getLogger("ultron.ouvido")

TAXA = 16000
THREADS = max(4, (os.cpu_count() or 4) - 4)
BLOCO = 1600  # 100 ms

PALAVRAS_ATIVACAO = re.compile(
    r"\b(ultron|ultrom|ultra[mn]|ultro|outron|altron|ultrão|utlon|utlom|ultrum|o tron|outro on|hulton)\b")

# Erros típicos do Whisper com nomes daqui (aplicados depois da transcrição).
CORRECOES = [
    (r"^\s*(o\s*tron|outro\s*on|utl?o[nm]|ultrom|ultr[aã]o?|hulton|altron)\b[,.]?", "Ultron,"),
    (r"\b(chaco|xaco|shako|chaque)\s*(e\s*)?(há|ia|ai|ar|ah)\b", "Shaco IA"),
    (r"\bescanei a\b", "escaneia a"),
    (r"\bdesk(to|top|topp)\b", "desktop"),
]


def sem_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


def _preparar(audio):
    """Tira o ruído de baixa frequência (zumbido, DC) e normaliza o volume."""
    a = np.asarray(audio, dtype=np.float32)
    if not len(a):
        return a
    # passa-altas simples: tira a média móvel de ~12 ms (zumbido, DC, vento)
    saida = a - np.convolve(a, np.ones(200, dtype=np.float32) / 200, mode="same")
    pico = float(np.max(np.abs(saida))) or 1.0
    return saida * min(0.9 / pico, 10.0)    # ganho até 10x se você falou baixo


def vocabulario():
    """Dica para o Whisper com os nomes que você usa (ajuda MUITO com nomes próprios)."""
    nomes = ["Ultron", ajuste("usuario.nome", "Davi")]
    for id_, h in (ajuste("hosts", {}) or {}).items():
        nomes.append(id_)
    nomes += list((ajuste("modos", {}) or {}).keys())
    nomes += ajuste("whisper.vocabulario", []) or []
    return ("Conversa em português do Brasil com o Ultron, assistente de voz. Nomes: "
            + ", ".join(dict.fromkeys(str(n) for n in nomes)) + ".")


def _hotwords():
    return " ".join(["Ultron"] + [str(x) for x in (ajuste("whisper.vocabulario", []) or [])][:15])


def corrigir(texto):
    for padrao, troca in CORRECOES:
        texto = re.sub(padrao, troca, texto, flags=re.I)
    return re.sub(r",\s*,", ",", texto).strip()


class Ouvido:
    def __init__(self):
        from faster_whisper import WhisperModel
        modelo = ajuste("whisper.modelo", "small")
        LOG.info("carregando whisper %s", modelo)
        self.whisper = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=THREADS)
        # Modelo pequeno só para achar a palavra "Ultron" no começo da fala:
        # conversa de fundo não custa uma transcrição completa.
        rapido = ajuste("whisper.modelo_ativacao", "tiny")
        self.whisper_ativacao = (self.whisper if rapido == modelo else
                                 WhisperModel(rapido, device="cpu", compute_type="int8", cpu_threads=THREADS))
        self.fila = queue.Queue()
        self.stream = sd.InputStream(samplerate=TAXA, channels=1, dtype="float32",
                                     blocksize=BLOCO, device=ajuste("audio.microfone"),
                                     callback=self._callback)
        self.stream.start()
        self.limiar = self._calibrar()
        self._pendente = None          # áudio do usuário capturado ao interromper
        self._vigiando = threading.Event()
        self._vigia = None

    def _callback(self, dados, _frames, _tempo, _status):
        bloco = dados[:, 0].copy()
        self.fila.put(bloco)
        if not voz.falando():  # o eco da própria voz não acende a aura azul
            rms = float(np.sqrt(np.mean(bloco ** 2)))
            animacao.nivel("ouvindo", rms / (getattr(self, "limiar", 0.015) * 5))

    def _calibrar(self):
        """Mede o ruído ambiente por ~1 s e define o limiar de fala."""
        fixo = ajuste("audio.limiar_fala")
        if fixo:
            return float(fixo)
        niveis = []
        fim = time.time() + 1.0
        while time.time() < fim:
            niveis.append(float(np.sqrt(np.mean(self.fila.get() ** 2))))
        ruido = float(np.median(niveis)) if niveis else 0.005
        limiar = max(0.008, ruido * 2.5)   # mais sensível: pega começo de fala baixa
        LOG.info("ruído %.4f -> limiar %.4f", ruido, limiar)
        return limiar

    def _limpar_fila(self):
        while not self.fila.empty():
            try:
                self.fila.get_nowait()
            except queue.Empty:
                break

    # ------------------------------------------------------- interrupção por voz
    def iniciar_vigia(self):
        """Enquanto o Ultron fala, escuta o microfone; se o usuário começar a falar
        por cima, corta a fala e guarda o começo do que ele disse."""
        if not ajuste("audio.interromper", True):
            return
        self._limpar_fila()
        self._pendente = None
        self._vigiando.set()
        self._vigia = threading.Thread(target=self._vigiar, daemon=True)
        self._vigia.start()

    def parar_vigia(self):
        self._vigiando.clear()
        if self._vigia:
            self._vigia.join(timeout=1)
            self._vigia = None

    def _vigiar(self):
        from core import voz
        sens = float(ajuste("audio.sensibilidade_interrupcao", 2.5))
        precisa = int(ajuste("audio.blocos_interrupcao", 3))   # x100 ms de voz contínua
        historico, recentes, seguidos = [], [], 0
        inicio = time.time()
        while self._vigiando.is_set():
            try:
                bloco = self.fila.get(timeout=0.2)
            except queue.Empty:
                continue
            nivel = float(np.sqrt(np.mean(bloco ** 2)))
            recentes = (recentes + [bloco])[-(precisa + 2):]
            # Nível do "eco": o que o microfone capta da própria voz do Ultron.
            eco = float(np.percentile(historico, 80)) if len(historico) >= 4 else self.limiar * 2
            gatilho = max(self.limiar * 3, eco * sens)
            if time.time() - inicio > 0.4 and nivel > gatilho:
                seguidos += 1
                if seguidos >= precisa:
                    LOG.info("interrompido (nível %.3f > %.3f)", nivel, gatilho)
                    voz.interromper()
                    self._pendente = list(recentes)
                    self._vigiando.clear()
                    return
            else:
                seguidos = 0
                historico = (historico + [nivel])[-30:]

    def ouvir_interrupcao(self):
        """Continua gravando o que o usuário começou a dizer ao interromper."""
        return self.ouvir(espera_max=3)

    def gravar_frase(self, espera_max=None, silencio_fim=None, duracao_max=None):
        """Espera alguém falar e grava até um silêncio. None se ninguém falar."""
        silencio_fim = silencio_fim or ajuste("audio.silencio_fim", 1.0)
        duracao_max = duracao_max or ajuste("audio.duracao_max", 15)
        inicio = time.time()
        pre = []          # 500 ms antes da fala, para não cortar a primeira sílaba
        gravando, audio, ultimo_som = False, [], 0.0
        if self._pendente:
            # Veio de uma interrupção: a fala já começou, não descarta o microfone.
            gravando, audio, ultimo_som = True, self._pendente, time.time()
            self._pendente = None
        else:
            self._limpar_fila()
        while True:
            bloco = self.fila.get()
            nivel = float(np.sqrt(np.mean(bloco ** 2)))
            agora = time.time()
            if not gravando:
                pre = (pre + [bloco])[-5:]
                if nivel > self.limiar:
                    gravando, audio, ultimo_som = True, list(pre), agora
                elif espera_max and agora - inicio > espera_max:
                    return None
                continue
            audio.append(bloco)
            if nivel > self.limiar:
                ultimo_som = agora
            dur = len(audio) * BLOCO / TAXA
            if agora - ultimo_som > silencio_fim or dur > duracao_max:
                break
        if len(audio) * BLOCO / TAXA < 0.5:
            return None
        return np.concatenate(audio)

    def transcrever(self, audio, rapido=False):
        modelo = self.whisper_ativacao if rapido else self.whisper
        segs, _ = modelo.transcribe(
            _preparar(audio), language="pt", beam_size=1 if rapido else int(ajuste("whisper.beam", 3)),
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400},
            initial_prompt=vocabulario(), hotwords=_hotwords(), condition_on_previous_text=False)
        # descarta trechos que o Whisper "inventou" sobre silêncio ou ruído
        texto = " ".join(s.text.strip() for s in segs
                         if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)).strip()
        return corrigir(texto)

    def esperar_ativacao(self):
        """Bloqueia até ouvir 'Ultron'. Devolve o que veio depois do nome, se houver."""
        while True:
            audio = self.gravar_frase(duracao_max=8)
            if audio is None:
                continue
            if len(audio) > TAXA * 5:
                # Fala longa (conversa de fundo?): confere só o começo com o
                # modelo de ativação antes de pagar a transcrição completa.
                previa = self.transcrever(audio[: int(TAXA * 2.5)], rapido=True)
                if not PALAVRAS_ATIVACAO.search(sem_acentos(previa)):
                    continue
            texto = self.transcrever(audio)
            m = PALAVRAS_ATIVACAO.search(sem_acentos(texto))
            if not m:
                continue
            LOG.info("ativado: %r", texto)
            resto = sem_acentos(texto)[m.end():].strip(" ,.!?")
            return texto if len(resto) > 3 else ""

    def ouvir(self, espera_max=6):
        audio = self.gravar_frase(espera_max=espera_max)
        if audio is None:
            return ""
        return self.transcrever(audio)

    def fechar(self):
        self.stream.stop()
        self.stream.close()
