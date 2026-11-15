"""Música, mídia e brilho da tela.

No notebook fala com os players pelo MPRIS (D-Bus): Spotify, Brave/YouTube,
VLC, qualquer um que apareça no KDE. No desktop Windows manda as teclas de
mídia (play/pause, próxima, anterior), que o Spotify e o navegador obedecem.
"""
import base64
import re
import subprocess
from urllib.parse import quote, quote_plus

from core.registro import NAO_CONFIAVEL, ferramenta

MPRIS = "org.mpris.MediaPlayer2"
METODOS = {"tocar": "Play", "pausar": "Pause", "alternar": "PlayPause",
           "proxima": "Next", "anterior": "Previous", "parar": "Stop"}
TECLAS_WINDOWS = {"alternar": 0xB3, "tocar": 0xB3, "pausar": 0xB3, "proxima": 0xB0,
                  "anterior": 0xB1, "parar": 0xB2}


def _gdbus(destino, metodo, *args):
    r = subprocess.run(["gdbus", "call", "--session", "--dest", destino, "--object-path",
                        "/org/mpris/MediaPlayer2", "--method", metodo, *args],
                       capture_output=True, text=True, timeout=5)
    return r.returncode, (r.stdout + r.stderr).strip()


def _players():
    r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                        "--object-path", "/org/freedesktop/DBus",
                        "--method", "org.freedesktop.DBus.ListNames"],
                       capture_output=True, text=True, timeout=5)
    nomes = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", r.stdout)
    # O plasma-browser-integration duplica o que o navegador já expõe.
    return [n for n in nomes if "plasma-browser-integration" not in n] or nomes


def _prop(player, nome):
    return _gdbus(player, "org.freedesktop.DBus.Properties.Get", f"{MPRIS}.Player", nome)[1]


def _info(player):
    meta = _prop(player, "Metadata")
    # GLib usa aspas duplas quando o texto tem apóstrofo
    titulo = re.search(r"""'xesam:title': <(?:'([^']*)'|"([^"]*)")>""", meta)
    artista = re.search(r"""'xesam:artist': <\[(?:'([^']*)'|"([^"]*)")""", meta)
    titulo = titulo and (titulo.group(1) or titulo.group(2))
    artista = artista and (artista.group(1) or artista.group(2))
    estado = re.search(r"'(Playing|Paused|Stopped)'", _prop(player, "PlaybackStatus"))
    app = player.split(".")[3]
    pt = {"Playing": "tocando", "Paused": "pausado", "Stopped": "parado"}
    return (f"{app}: {pt.get(estado.group(1), '?') if estado else '?'}"
            + (f" — {titulo}" if titulo else "")
            + (f" ({artista})" if artista else ""))


def _escolher(players, app=None):
    if app:
        for p in players:
            if app.lower() in p.lower():
                return p
    for p in players:  # prefere o que está tocando
        if "Playing" in _prop(p, "PlaybackStatus"):
            return p
    for p in players:
        if "spotify" in p.lower():
            return p
    return players[0] if players else None


def _tecla_windows(computador, vk):
    from ferramentas.ssh import abrir_em
    script = ("Add-Type -Name K -Namespace W -MemberDefinition '[DllImport(\"user32.dll\")] public "
              "static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);';"
              f"[W.K]::keybd_event({vk},0,0,[UIntPtr]::Zero);[W.K]::keybd_event({vk},0,2,[UIntPtr]::Zero)")
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    return abrir_em(computador, "powershell.exe",
                    ["-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", b64])


@ferramenta(
    "midia",
    "Controla música e vídeo: tocar, pausar, alternar, proxima, anterior, parar, status "
    "(o que está tocando) ou buscar (abre uma música/artista/playlist no Spotify). "
    "Padrão: notebook. No desktop só tocar/pausar/proxima/anterior.",
    {"type": "object", "properties": {
        "acao": {"type": "string", "enum": ["tocar", "pausar", "alternar", "proxima", "anterior",
                                            "parar", "status", "buscar"]},
        "busca": {"type": "string", "description": "o que tocar, para acao=buscar"},
        "app": {"type": "string", "description": "player específico, ex.: spotify, brave, vlc"},
        "computador": {"type": "string", "description": "ID da máquina: notebook (padrão) ou desktop"}},
     "required": ["acao"]})
def midia(acao, busca=None, app=None, computador="notebook"):
    from ferramentas.ssh import _host
    id_, h = _host(computador or "notebook")
    if not h.get("local"):
        if acao == "buscar" and busca:
            from ferramentas.ssh import abrir_em
            return abrir_em(id_, f"spotify:search:{quote(busca)}")
        if acao not in TECLAS_WINDOWS:
            return "No desktop eu só consigo tocar, pausar, pular e voltar."
        return _tecla_windows(id_, TECLAS_WINDOWS[acao]).replace("powershell.exe", f"tecla {acao}")

    if acao == "buscar":
        if not busca:
            return "Diga o que tocar."
        spotify = [p for p in _players() if "spotify" in p.lower()]
        if spotify:
            rc, saida = _gdbus(spotify[0], f"{MPRIS}.Player.OpenUri", f"spotify:search:{quote(busca)}")
            if rc == 0:
                return f"Procurando '{busca}' no Spotify."
        subprocess.Popen(["xdg-open", f"https://open.spotify.com/search/{quote_plus(busca)}"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Abri a busca por '{busca}' no Spotify."

    players = _players()
    if not players:
        return "Nenhum player aberto no notebook."
    if acao == "status":
        return NAO_CONFIAVEL + "\n".join(_info(p) for p in players)
    p = _escolher(players, app)
    if acao in ("pausar", "parar"):  # pausa tudo que estiver tocando
        alvos = [x for x in players if "Playing" in _prop(x, "PlaybackStatus")] or [p]
    else:
        alvos = [p]
    for alvo in alvos:
        rc, saida = _gdbus(alvo, f"{MPRIS}.Player.{METODOS[acao]}")
        if rc != 0:
            return f"O player recusou: {saida[:200]}"
    return NAO_CONFIAVEL + _info(alvos[0])


@ferramenta(
    "brilho",
    "Ajusta o brilho da tela do notebook (0 a 100%) ou informa o atual.",
    {"type": "object", "properties": {"nivel": {"type": "integer", "minimum": 1, "maximum": 100}}})
def brilho(nivel=None):
    if nivel is not None:
        r = subprocess.run(["brightnessctl", "-q", "set", f"{int(nivel)}%"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return f"Não consegui mudar o brilho: {r.stderr.strip()[:200]}"
    saida = subprocess.run(["brightnessctl", "-m"], capture_output=True, text=True).stdout
    atual = re.search(r",(\d+)%", saida)
    return f"Brilho em {atual.group(1) if atual else '?'}%."
