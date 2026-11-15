"""Fala do Ultron: Piper (voz neural pt-BR, offline) com espeak-ng de reserva."""
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import wave

import numpy as np
import sounddevice as sd

from core import animacao
from core.config import DADOS, ajuste

LOG = logging.getLogger("ultron.voz")

VOZES = DADOS / "vozes"
BASE_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"

_piper = None
_falando = threading.Event()


def _baixar_voz(nome):
    """nome ex.: 'pt_BR-faber-medium' -> baixa .onnx e .onnx.json se faltarem."""
    VOZES.mkdir(parents=True, exist_ok=True)
    _, locutor, qualidade = nome.split("-")
    for ext in (".onnx", ".onnx.json"):
        destino = VOZES / f"{nome}{ext}"
        if not destino.exists():
            url = f"{BASE_HF}/{locutor}/{qualidade}/{nome}{ext}"
            LOG.info("baixando voz %s", url)
            urllib.request.urlretrieve(url, destino)
    return VOZES / f"{nome}.onnx"


def _carregar_piper():
    global _piper
    if _piper is None:
        from piper import PiperVoice
        modelo = _baixar_voz(ajuste("voz.piper", "pt_BR-faber-medium"))
        _piper = PiperVoice.load(str(modelo))
    return _piper


def preparar():
    """Carrega a voz no início para a primeira resposta não demorar."""
    if ajuste("voz.motor", "piper") == "piper":
        try:
            _carregar_piper()
            return "piper"
        except Exception as e:
            LOG.warning("Piper indisponível (%s); usando espeak-ng", e)
    return "espeak"


# Efeito "Ultron": voz mais grave, com ressonância metálica de robô. Não imita a
# voz de nenhum ator; é um processamento em cima da voz pt-BR do Piper.
#   tom: fator de grave (0.80 = ~4 semitons abaixo)
EFEITOS = {
    "nenhum": None,
    "leve": dict(tom=0.90, filtros=(
        "flanger=delay=0.5:depth=0.6:regen=20:width=40:speed=0.2,"
        "aecho=0.8:0.5:35:0.18,"
        "bass=g=4:f=140")),
    "ultron": dict(tom=0.84, filtros=(
        "flanger=delay=0.7:depth=1.0:regen=45:width=55:speed=0.25,"
        "chorus=0.6:0.8:18|26:0.25|0.18:0.25|0.35:1.5|1.8,"
        "aecho=0.8:0.55:28|62:0.28|0.14,"
        "bass=g=6:f=120,treble=g=-2:f=5000,"
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=80,"
        "alimiter=limit=0.95")),
}


def aplicar_efeito(audio, taxa, nome=None):
    """audio int16 -> audio int16 processado pelo ffmpeg (ou o original se falhar)."""
    efeito = EFEITOS.get(nome or ajuste("voz.efeito", "ultron"))
    if not efeito or not shutil.which("ffmpeg"):
        return audio
    t = efeito["tom"]
    cadeia = (f"asetrate={int(taxa * t)},aresample={taxa},atempo={1 / t:.4f},"
              + efeito["filtros"])
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(taxa), "-ac", "1", "-i", "-",
         "-af", cadeia, "-f", "s16le", "-ar", str(taxa), "-ac", "1", "-"],
        input=audio.tobytes(), capture_output=True)
    if r.returncode != 0 or not r.stdout:
        LOG.warning("efeito de voz falhou: %s", r.stderr.decode(errors="ignore")[:200])
        return audio
    return np.frombuffer(r.stdout, dtype=np.int16)


def sintetizar(texto, efeito=None):
    voz = _carregar_piper()
    pedacos = [c.audio_int16_array for c in voz.synthesize(texto)]
    if not pedacos:
        return None, voz.config.sample_rate
    audio = np.concatenate(pedacos)
    return aplicar_efeito(audio, voz.config.sample_rate, efeito), voz.config.sample_rate


def _frases(texto):
    """Quebra em frases para começar a falar antes de sintetizar tudo."""
    partes = re.split(r"(?<=[.!?;:])\s+", texto.strip())
    frases, atual = [], ""
    for p in partes:
        atual = f"{atual} {p}".strip()
        if len(atual) >= 25:           # junta frases muito curtas
            frases.append(atual)
            atual = ""
    if atual:
        frases.append(atual)
    return frases


_interrompido = threading.Event()


def interromper():
    """Corta a fala na hora (o usuário começou a falar por cima)."""
    _interrompido.set()
    try:
        sd.stop()
    except Exception:
        pass


def foi_interrompido():
    return _interrompido.is_set()


def _tocar(audio, taxa):
    sd.play(audio, taxa, device=ajuste("audio.saida"))
    inicio = time.time()
    fim = inicio + len(audio) / taxa + 0.3
    janela = int(taxa * 0.05)
    while time.time() < fim and not _interrompido.is_set():
        # volume do trecho que está tocando agora -> aura vermelha
        pos = int((time.time() - inicio) * taxa)
        trecho = audio[pos:pos + janela].astype(np.float32)
        animacao.nivel("falando", float(np.sqrt(np.mean(trecho ** 2))) / 6000 if len(trecho) else 0)
        time.sleep(0.02)
    animacao.nivel("falando", 0)
    if _interrompido.is_set():
        sd.stop()


def _falar_piper(texto):
    """Sintetiza a frase seguinte enquanto toca a atual."""
    fila = queue.Queue(maxsize=2)

    def produzir():
        try:
            for frase in _frases(texto):
                if _interrompido.is_set():
                    break
                fila.put(sintetizar(frase))
        finally:
            fila.put(None)

    threading.Thread(target=produzir, daemon=True).start()
    while (item := fila.get()) is not None:
        audio, taxa = item
        if audio is not None and not _interrompido.is_set():
            _tocar(audio, taxa)


def _falar_espeak(texto):
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "165", texto],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_fundo = None


def falar_em_fundo(texto):
    """Fala sem bloquear (avisos curtos enquanto uma ferramenta roda)."""
    global _fundo
    _esperar_fundo()
    _fundo = threading.Thread(target=falar, args=(texto,), daemon=True)
    _fundo.start()


def _esperar_fundo():
    if _fundo and _fundo.is_alive() and _fundo is not threading.current_thread():
        _fundo.join()


def falar(texto, ao_comecar=None):
    """Fala o texto. Devolve False se foi interrompido pelo usuário.
    ao_comecar(): chamado quando a fala começa (para ligar o vigia de interrupção)."""
    if not texto:
        return True
    _esperar_fundo()
    _interrompido.clear()
    _falando.set()
    if ao_comecar:
        ao_comecar()
    try:
        if ajuste("voz.motor", "piper") == "piper":
            try:
                _falar_piper(texto)
                return not _interrompido.is_set()
            except Exception as e:
                LOG.warning("falha no Piper: %s", e)
        _falar_espeak(texto)
        return True
    finally:
        _falando.clear()


def parar():
    try:
        sd.stop()
    except Exception:
        pass


def falando():
    return _falando.is_set()


def salvar_wav(texto, caminho, efeito=None):
    """Útil para testar a voz sem caixa de som."""
    audio, taxa = sintetizar(texto, efeito)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(audio.tobytes())
