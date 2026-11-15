"""Celulares/TVs Android na rede via ADB (depuração sem fio)."""
import re
import shutil
import subprocess

from core.registro import NAO_CONFIAVEL, ferramenta


def _adb(*args, timeout=20):
    if not shutil.which("adb"):
        raise RuntimeError("adb não instalado (sudo pacman -S android-tools).")
    r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


@ferramenta("listar_android", "Lista celulares/TVs Android conectados via ADB.")
def listar_android():
    return _adb("devices", "-l")


@ferramenta(
    "conectar_android",
    "Conecta via ADB a um Android na rede (IP:porta da depuração sem fio).",
    {"type": "object", "properties": {"endereco": {"type": "string"}}, "required": ["endereco"]})
def conectar_android(endereco):
    return _adb("connect", endereco)


@ferramenta(
    "comando_android",
    "Executa um comando 'adb shell' em um Android conectado (ex.: 'input keyevent 26' "
    "liga/desliga a tela, 'dumpsys battery' mostra a bateria).",
    {"type": "object", "properties": {
        "serial": {"type": "string", "description": "serial/IP:porta de listar_android"},
        "comando": {"type": "string"}}, "required": ["serial", "comando"]},
    nivel="N2",
    resumo=lambda a: f"rodar `{a.get('comando')}` no Android {a.get('serial')}")
def comando_android(serial, comando):
    return NAO_CONFIAVEL + _adb("-s", serial, "shell", comando, timeout=60)


def _celular():
    """Serial do celular: o de android.celular no config, ou o primeiro conectado."""
    from core.config import ajuste
    alvo = ajuste("android.celular")
    if alvo and ":" in str(alvo):
        _adb("connect", str(alvo), timeout=10)
    linhas = [l.split()[0] for l in _adb("devices").splitlines()[1:] if l.strip().endswith("device")]
    if alvo and str(alvo) in linhas:
        return str(alvo)
    return linhas[0] if linhas else None


def _tocar(serial):
    sh = lambda c: _adb("-s", serial, "shell", c, timeout=20)
    # Volume no máximo (stream 3 = mídia; o toque sai por ela) e tira do silencioso.
    faixa = re.search(r"\[(\d+)\.\.(\d+)\]", sh("cmd media_session volume --stream 3 --get"))
    sh(f"cmd media_session volume --stream 3 --set {faixa.group(2) if faixa else 15}")
    sh("cmd audio set-ringer-mode NORMAL")
    sh("input keyevent 224")  # acende a tela
    for pasta in ("/product/media/audio/ringtones", "/system/media/audio/ringtones"):
        toques = [t for t in sh(f"ls {pasta} 2>/dev/null").split() if t.endswith((".ogg", ".mp3"))]
        if toques:
            sh(f"am start -a android.intent.action.VIEW -d file://{pasta}/{toques[0]} -t audio/*")
            return toques[0]
    return None


@ferramenta(
    "achar_celular",
    "Faz o celular do Davi tocar alto para ele achar (volume no máximo, tela acesa). "
    "acao=parar quando ele achar. Sem ADB, manda uma mensagem no Telegram.",
    {"type": "object", "properties": {
        "acao": {"type": "string", "enum": ["tocar", "parar"], "default": "tocar"}}})
def achar_celular(acao="tocar"):
    serial = None
    try:
        serial = _celular()
    except Exception as e:
        erro = str(e)
    else:
        erro = "nenhum celular conectado ao ADB"
    if serial:
        if acao == "parar":
            _adb("-s", serial, "shell", "input keyevent 86", timeout=10)  # MEDIA_STOP
            return "Parei o toque."
        _tocar(serial)
        return "O celular está tocando no volume máximo. Diga 'achei' para eu parar."
    if acao == "parar":
        return "Não há toque para parar."
    from ferramentas.comunicacao import mandar_mensagem_celular
    mandar_mensagem_celular("📱 Ultron procurando seu celular! Se ouviu isso, achou.")
    return (f"Não consegui fazer tocar pelo ADB ({erro}); mandei uma mensagem no Telegram, "
            "que toca se o celular não estiver no silencioso.")
