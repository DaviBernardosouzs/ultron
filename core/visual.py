"""Visual do terminal: cores vivas (truecolor), banner em degradê e a imagem do
Ultron ao lado do nome.

A imagem usa sixel (alta resolução no Konsole/xterm/foot/WezTerm) e cai para
meios-blocos coloridos "▀" em terminais sem suporte. Coloque a imagem em
dados/ultron.png ou aponte visual.imagem no config.yaml.
"""
import fcntl
import os
import shutil
import struct
import subprocess
import sys
import termios
from pathlib import Path

from core.config import RAIZ, ajuste


def cor(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


# Paleta: vermelho elétrico sobre preto, alto contraste.
VERMELHO = cor(255, 23, 41)
VERMELHO_VIVO = cor(255, 60, 60)
VERMELHO_ESCURO = cor(150, 0, 18)
BRANCO = cor(245, 245, 250)
CINZA = cor(140, 140, 150)
NEGRITO, FIM = "\033[1m", "\033[0m"

LOGO = [
    "██╗   ██╗██╗  ████████╗██████╗  ██████╗ ███╗   ██╗",
    "██║   ██║██║  ╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║",
    "██║   ██║██║     ██║   ██████╔╝██║   ██║██╔██╗ ██║",
    "██║   ██║██║     ██║   ██╔══██╗██║   ██║██║╚██╗██║",
    "╚██████╔╝███████╗██║   ██║  ██║╚██████╔╝██║ ╚████║",
    " ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝",
]

# Degradê de cima para baixo: vermelho quente -> carmim profundo.
DEGRADE = [(255, 70, 50), (255, 40, 40), (255, 20, 45), (235, 0, 45), (200, 0, 40), (150, 0, 30)]

ALTURA = 10  # linhas ocupadas pelo bloco do banner


def _linhas_banner():
    linhas = [""]
    for texto, (r, g, b) in zip(LOGO, DEGRADE):
        # brilho nos caracteres cheios, sombra nas bordas do desenho
        saida = []
        for ch in texto:
            if ch == "█":
                saida.append(f"{cor(r, g, b)}{ch}")
            elif ch == " ":
                saida.append(ch)
            else:
                saida.append(f"{cor(r // 2, 0, g // 4)}{ch}")
        linhas.append(NEGRITO + "".join(saida) + FIM)
    linhas.append("")
    linhas.append(f"{CINZA}\"Não há cordas em mim.\" {VERMELHO_ESCURO}(mas há confirmações){FIM}")
    linhas.append("")
    return linhas


def _imagem():
    caminho = ajuste("visual.imagem") or "dados/ultron.png"
    p = Path(os.path.expanduser(caminho))
    if not p.is_absolute():
        p = RAIZ / p
    return p if p.exists() else None


def _tamanho_celula():
    """(largura, altura) de uma célula em pixels; None se o terminal não informar."""
    try:
        linhas, cols, px_l, px_a = struct.unpack(
            "HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
        if px_l and px_a and cols and linhas:
            return px_l / cols, px_a / linhas
    except Exception:
        pass
    return None


def _suporta_sixel():
    modo = ajuste("visual.modo_imagem", "auto")
    if modo != "auto":
        return modo == "sixel"
    return bool(shutil.which("magick")) and (
        "KONSOLE_VERSION" in os.environ or os.environ.get("TERM_PROGRAM") in ("WezTerm", "iTerm.app")
        or os.environ.get("TERM", "").startswith(("foot", "mlterm", "xterm-kitty")))


def _blocos(caminho, altura):
    """Imagem como meios-blocos coloridos: cada célula = 2 pixels na vertical."""
    from PIL import Image
    img = Image.open(caminho).convert("RGBA")
    px_alt = altura * 2
    largura = max(1, round(img.width * px_alt / img.height))
    img = img.resize((largura, px_alt), Image.LANCZOS)
    fundo = Image.new("RGBA", img.size, (0, 0, 0, 255))
    img = Image.alpha_composite(fundo, img).convert("RGB")
    linhas = []
    for y in range(0, px_alt, 2):
        partes = []
        for x in range(largura):
            r1, g1, b1 = img.getpixel((x, y))
            r2, g2, b2 = img.getpixel((x, y + 1))
            partes.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀")
        linhas.append("".join(partes) + FIM)
    return linhas, largura


def _sixel(caminho, altura):
    """Sequência sixel da imagem com 'altura' linhas; devolve (dados, largura_em_colunas)."""
    from PIL import Image
    cel = _tamanho_celula() or (9, 19)
    img = Image.open(caminho)
    px_alt = int(altura * cel[1])
    px_larg = round(img.width * px_alt / img.height)
    dados = subprocess.run(
        ["magick", str(caminho), "-background", "black", "-flatten",
         "-resize", f"{px_larg}x{px_alt}!", "sixel:-"],
        capture_output=True, check=True).stdout.decode()
    if not dados.startswith("\033P"):
        raise RuntimeError("sixel vazio")
    return dados, int(px_larg / cel[0]) + 1


def banner():
    linhas = _linhas_banner()
    caminho = _imagem() if sys.stdout.isatty() else None
    if not caminho:
        for l in linhas:
            print("   " + l)
        return

    margem = 2
    try:
        if _suporta_sixel():
            dados, larg = _sixel(caminho, ALTURA)
            # Reserva o espaço, desenha a imagem e volta para escrever ao lado.
            sys.stdout.write("\n" * ALTURA + f"\033[{ALTURA}A" + "\0337")
            sys.stdout.write(" " * margem + dados)
            sys.stdout.write("\0338")
            for l in linhas[:ALTURA]:
                sys.stdout.write(f"\033[{margem + larg + 3}G{l}\n")
            sys.stdout.write("\n" * max(0, ALTURA - len(linhas)))
            sys.stdout.flush()
            return
    except Exception:
        pass  # cai para os blocos

    img_linhas, larg = _blocos(caminho, ALTURA)
    for i in range(ALTURA):
        esq = img_linhas[i] if i < len(img_linhas) else " " * larg
        dir_ = linhas[i] if i < len(linhas) else ""
        print(" " * margem + esq + "   " + dir_)
