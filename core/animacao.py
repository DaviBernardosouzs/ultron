"""Animação no terminal enquanto o Ultron ouve, pensa, age e fala.

Uso:
    animacao.iniciar("pensando")   # liga (só no terminal interativo)
    animacao.estado("escaneando a rede")
    animacao.imprimir("texto")     # imprime sem bagunçar a animação
    with animacao.pausada():       # para pedir input()
        ...
    animacao.parar()

Fora de um terminal (serviço do Telegram, logs) tudo vira no-op.
"""
import collections
import contextlib
import itertools
import math
import re
import shutil
import sys
import threading
import time

from core.visual import CINZA, FIM, VERMELHO_ESCURO as VERMELHO_ESC, VERMELHO_VIVO as VERMELHO
LIMPA = "\r\033[2K"

ROTULOS = {
    "escanear_rede": "varrendo a rede",
    "listar_dispositivos_conhecidos": "consultando o inventário",
    "ping": "pingando",
    "portas_abertas": "inspecionando portas",
    "ligar_dispositivo_wol": "despertando a máquina",
    "info_rede": "checando a conexão",
    "status_computador": "conectando via SSH",
    "executar_no_computador": "executando remotamente",
    "desligar_computador": "desligando a máquina",
    "executar_comando_local": "executando comando",
    "status_deste_pc": "lendo os sensores",
    "clima": "consultando o clima",
    "listar_casa": "consultando a casa",
    "controlar_casa": "comandando a casa",
    "ler_emails": "lendo e-mails",
    "enviar_email": "enviando e-mail",
    "me_enviar_email": "enviando e-mail",
    "mandar_mensagem_celular": "enviando ao celular",
    "lembrar": "memorizando",
    "pesquisar_web": "pesquisando na web",
    "ler_pagina": "lendo a página",
    "ativar_modo": "ativando o modo",
    "ligar_computador": "despertando a máquina",
    "abrir_no_computador": "abrindo",
    "midia": "controlando a mídia",
    "criar_lembrete": "agendando",
    "criar_evento": "agendando",
    "ver_agenda": "consultando a agenda",
    "achar_celular": "procurando o celular",
    "consultar_biblioteca": "consultando a biblioteca",
    "ler_nota_biblioteca": "lendo a biblioteca",
}


def rotulo(nome_ferramenta):
    return ROTULOS.get(nome_ferramenta, nome_ferramenta.replace("_", " "))


# ------------------------------------------------------------------ quadros

def _olhos(t):
    """Dois olhos que pulsam (brilho varia com o tempo)."""
    brilho = (math.sin(t * 5) + 1) / 2
    cor = VERMELHO if brilho > 0.5 else VERMELHO_ESC
    return f"{cor}◢■◣ ◢■◣{FIM}"


def _varredura(t, largura=14):
    """Feixe que vai e volta, como o visor do Ultron."""
    pos = int((math.sin(t * 3) + 1) / 2 * (largura - 1))
    barra = []
    for i in range(largura):
        d = abs(i - pos)
        barra.append(f"{VERMELHO}█" if d == 0 else f"{VERMELHO_ESC}▓" if d == 1
                     else f"{VERMELHO_ESC}░" if d == 2 else f"{CINZA}·")
    return "[" + "".join(barra) + f"{FIM}]"


# Aura: brilho que pulsa com o volume real do áudio (inspirada no visualizador
# "aura" do LiveKit). Ciano enquanto capta a sua voz; vermelho quando ele fala.
CORES_AURA = {"ouvindo": (0x1F, 0xD5, 0xF9), "falando": (0xF5, 0x22, 0x2D),
              # etapas da evolução supervisionada
              "pesquisando": (0x66, 0x00, 0xFF), "desenvolvendo": (0xFF, 0x7A, 0x45),
              "testando": (0xFF, 0xC5, 0x3D), "melhoria concluída": (0x52, 0xC4, 0x1A)}
_niveis = {"ouvindo": 0.0, "falando": 0.0}   # 0..1, alimentado por ouvido/voz


def nivel(fonte, valor):
    """Atualiza o volume (0..1) do microfone ("ouvindo") ou da fala ("falando")."""
    _niveis[fonte] = max(0.0, min(1.0, float(valor)))


def _misturar(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def _aura(t, rgb, n, largura=24):
    """Brilho central que abre e fica mais intenso conforme o volume n (0..1)."""
    raio = 0.30 + 0.55 * n + 0.04 * math.sin(t * 2.2)
    saida = []
    for i in range(largura):
        d = (i - (largura - 1) / 2) / (largura / 2)
        brilho = math.exp(-((d / raio) ** 2) * 1.6)
        brilho *= 0.75 + 0.25 * math.sin(t * 7 - abs(d) * 9) * (0.3 + n)  # ondulação
        brilho = max(0.0, min(1.0, brilho * (0.55 + 0.6 * n)))
        if brilho < 0.06:
            saida.append(" ")
            continue
        c = _misturar((0, 0, 0), rgb, min(1.0, brilho * 1.3))
        if brilho > 0.8:                      # núcleo quase branco
            c = _misturar(c, (255, 255, 255), (brilho - 0.8) * 2)
        ch = "█" if brilho > 0.55 else "▓" if brilho > 0.35 else "▒" if brilho > 0.18 else "░"
        saida.append(f"\033[38;2;{c[0]};{c[1]};{c[2]}m{ch}")
    return "".join(saida) + FIM


def _olhos_aura(rgb, n):
    c = _misturar(_misturar((0, 0, 0), rgb, 0.55), rgb, n)
    return f"\033[38;2;{c[0]};{c[1]};{c[2]}m◢■◣ ◢■◣{FIM}"


class _Animacao:
    def __init__(self):
        self.ativa = False
        self.texto = ""
        self.inicio = 0.0
        self.trava = threading.Lock()
        self.thread = None
        self.pontos = itertools.cycle(["   ", ".  ", ".. ", "..."])
        self.habilitada = sys.stdout.isatty()
        self.suave = 0.0
        self.cor = self.cor_de = self.cor_para = CORES_AURA["ouvindo"]
        self.cor_t0 = 0.0
        # Estado visível para outras interfaces (janela do modo ambiente), com ou sem terminal.
        self.atual = ""
        self.falas = collections.deque(maxlen=6)

    def _desenhar(self):
        t = time.time() - self.inicio
        decorrido = f"{CINZA}{t:4.1f}s{FIM}"
        rgb = self._cor_aura(CORES_AURA.get(self.texto))
        if rgb:
            # sobe rápido, desce devagar: a aura não "pisca" entre sílabas
            alvo = _niveis.get(self.texto, 0.25 + 0.15 * math.sin(t * 4))
            self.suave += (alvo - self.suave) * (0.6 if alvo > self.suave else 0.15)
            cor_txt = "\033[38;2;{};{};{}m".format(*rgb)
            linha = (f"  {_olhos_aura(rgb, self.suave)}  {_aura(t, rgb, self.suave)}  "
                     f"{cor_txt}{self.texto}{next(self.pontos)}{FIM} {decorrido}")
        else:
            linha = f"  {_olhos(t)}  {_varredura(t)}  {VERMELHO}{self.texto}{next(self.pontos)}{FIM} {decorrido}"
        largura = shutil.get_terminal_size((80, 20)).columns
        sys.stdout.write(LIMPA + (linha if len(self.texto) + 40 < largura else linha[:largura]))
        sys.stdout.flush()

    def _cor_aura(self, alvo):
        """Troca de cor em 1 s linear, como o useMoodColor do LiveKit."""
        if alvo is None:
            return None
        agora = time.time()
        if alvo != self.cor_para:
            self.cor_de, self.cor_para, self.cor_t0 = self.cor, alvo, agora
        self.cor = _misturar(self.cor_de, self.cor_para, min(1.0, agora - self.cor_t0))
        return self.cor

    def _laco(self):
        while self.ativa:
            with self.trava:
                if self.ativa:
                    self._desenhar()
            time.sleep(0.08)

    def iniciar(self, texto):
        self.atual = texto
        if not self.habilitada:
            return
        with self.trava:
            self.texto = texto
            if self.ativa:
                return
            self.ativa = True
            self.inicio = time.time()
            sys.stdout.write("\033[?25l")  # esconde o cursor
        self.thread = threading.Thread(target=self._laco, daemon=True)
        self.thread.start()

    def estado(self, texto):
        self.atual = texto
        if self.ativa:
            with self.trava:
                self.texto = texto

    def parar(self):
        self.atual = ""
        if not self.ativa:
            return
        with self.trava:
            self.ativa = False
            sys.stdout.write(LIMPA + "\033[?25h")
            sys.stdout.flush()
        if self.thread:
            self.thread.join(timeout=0.5)

    def imprimir(self, texto):
        limpo = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", str(texto)).strip()
        if limpo:
            self.falas.append((time.time(), limpo))
        with self.trava:
            if self.ativa:
                sys.stdout.write(LIMPA)
            print(texto, flush=True)

    @contextlib.contextmanager
    def pausada(self):
        anterior = self.texto if self.ativa else None
        self.parar()
        try:
            yield
        finally:
            if anterior is not None:
                self.iniciar(anterior)


_a = _Animacao()
iniciar, estado, parar, imprimir, pausada = _a.iniciar, _a.estado, _a.parar, _a.imprimir, _a.pausada


def atual():
    """Estado atual ('ouvindo', 'falando', 'pensando', 'aguardando "Ultron"'...) ou ''."""
    return _a.atual


def niveis():
    return dict(_niveis)


def falas():
    return list(_a.falas)
