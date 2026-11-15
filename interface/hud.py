"""Componentes de HUD (estilo painéis holográficos) desenhados com QPainter.

Fundo         grade de pontos, vinheta e uma faixa de varredura lenta.
Moldura       painel com cantos em colchete e título "// NOME" com índice.
Reator        o núcleo central: escala graduada, anéis segmentados girando,
              arcos de CPU/RAM, radar e a aura do Ultron no meio.
Medidor       arco circular pequeno com valor e rótulo.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from interface import aura

from interface.design import ENERGY, TEXT, METAL, SURFACE, MONO

VERMELHO = QColor(ENERGY)
CIANO = QColor(174, 182, 194)   # aço grafite: a cor secundária do painel
FONTE = "FiraCode Nerd Font"


def cor(c, alfa):
    q = QColor(c)
    q.setAlpha(int(max(0, min(255, alfa))))
    return q


def caneta(c, largura=1.0, alfa=255, ponta=Qt.FlatCap):
    p = QPen(cor(c, alfa), largura)
    p.setCapStyle(ponta)
    return p


def fonte(tamanho, peso=QFont.Normal, espaco=0):
    f = QFont(FONTE, tamanho, peso)
    if espaco:
        f.setLetterSpacing(QFont.AbsoluteSpacing, espaco)
    return f


# ------------------------------------------------------------------ fundo

class Fundo(QWidget):
    """Widget raiz: grade de pontos e vinheta, desenhadas UMA vez por tamanho (cache).
    Redesenhar o fundo a cada quadro forçava o repaint da janela inteira (100% de CPU)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("raiz")
        self._cache = None

    def _desenhar(self, w, h):
        from PySide6.QtGui import QPixmap
        pm = QPixmap(w, h)
        p = QPainter(pm)
        g = QRadialGradient(QPointF(w * 0.5, h * 0.42), max(w, h) * 0.75)
        g.setColorAt(0.0, QColor(15, 16, 21))
        g.setColorAt(0.55, QColor(7, 8, 11))
        g.setColorAt(1.0, QColor(5, 5, 7))
        p.fillRect(0, 0, w, h, QBrush(g))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(130, 140, 160, 12))
        passo = 26
        for x in range(passo // 2, w, passo):
            for y in range(passo // 2, h, passo):
                p.drawRect(QRectF(x, y, 1.2, 1.2))
        p.end()
        return pm

    def paintEvent(self, ev):
        if self._cache is None or self._cache.size() != self.size():
            self._cache = self._desenhar(self.width(), self.height())
        p = QPainter(self)
        p.drawPixmap(ev.rect(), self._cache, ev.rect())     # só a área pedida
        p.end()


# ------------------------------------------------------------------ moldura

class Moldura(QFrame):
    """Painel HUD: fundo translúcido, borda fina, colchetes nos cantos e título."""

    contador = 0

    def __init__(self, titulo="", destaque=VERMELHO):
        super().__init__()
        Moldura.contador += 1
        self.indice = Moldura.contador
        self.titulo = titulo.upper()
        self.destaque = destaque
        self.corpo = QVBoxLayout(self)
        self.corpo.setContentsMargins(16, 44 if titulo else 14, 16, 14)
        self.corpo.setSpacing(8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(SURFACE))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 5, 5)
        if self.titulo:
            p.setPen(caneta(self.destaque, 2, 210))
            p.drawLine(QPointF(16, 15), QPointF(16, 23))
            p.setFont(fonte(8, QFont.DemiBold, 1))
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(26, 9, r.width() - 42, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       self.titulo)
            p.setPen(QColor(METAL))
            p.drawLine(QPointF(16, 32), QPointF(r.width() - 16, 32))
        p.end()


# ------------------------------------------------------------------ reator central

class Reator(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(380, 380)
        self.est = aura.Estado()
        self.estado = ""
        self.cpu = self.ram = 0.0
        self.cpu_vis = self.ram_vis = 0.0
        self.t0 = time.time()
        self.nome = "ULTRON"

    def passo(self, estado, nivel):
        self.estado = estado
        self.est.passo(estado, nivel)
        self.cpu_vis += (self.cpu - self.cpu_vis) * 0.08
        self.ram_vis += (self.ram - self.ram_vis) * 0.08
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = time.time() - self.t0
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(w, h) / 2 - 12
        tinta = QColor(*aura.misturar((255, 42, 58), self.est.cor, 0.35))

        # 1) escala graduada externa (120 marcas), gira devagar
        p.save()
        p.translate(cx, cy)
        p.rotate(-t * 3)
        for i in range(120):
            longo = i % 10 == 0
            p.setPen(caneta(tinta, 2 if longo else 1, 200 if longo else 80))
            r0 = R - (14 if longo else 7)
            p.drawLine(QPointF(0, -R), QPointF(0, -r0))
            p.rotate(3)
        p.restore()

        # 2) anel de segmentos grossos (8), sentido horário
        self._segmentos(p, cx, cy, R * 0.88, 8, 30, 6, t * 14, tinta, 150)
        # 3) anel tracejado fino, anti-horário
        self._segmentos(p, cx, cy, R * 0.81, 48, 4, 1.4, -t * 22, tinta, 120)

        # 4) arcos de dados: CPU (vermelho) e RAM (ciano), com trilho
        for raio, valor, c, rotulo, ang0 in ((R * 0.74, self.cpu_vis, VERMELHO, "CPU", 120),
                                             (R * 0.68, self.ram_vis, CIANO, "RAM", 120)):
            ret = QRectF(cx - raio, cy - raio, raio * 2, raio * 2)
            p.setPen(caneta(c, 4, 30))
            p.drawArc(ret, ang0 * 16, -300 * 16)
            p.setPen(caneta(c, 4, 230, Qt.RoundCap))
            p.drawArc(ret, ang0 * 16, int(-300 * 16 * valor / 100))

        # legenda dos arcos, na abertura de baixo
        p.setFont(fonte(8, QFont.DemiBold, 2))
        p.setPen(cor(VERMELHO, 230))
        p.drawText(QRectF(cx - 120, cy + R * 0.70, 115, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"CPU {self.cpu_vis:3.0f}%")
        p.setPen(cor(CIANO, 230))
        p.drawText(QRectF(cx + 5, cy + R * 0.70, 115, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   f"RAM {self.ram_vis:3.0f}%")

        # 5) radar: varredura girando com rastro
        p.save()
        p.translate(cx, cy)
        varre = (t * 90) % 360
        for k in range(18):
            p.setPen(caneta(tinta, 1.5, 70 * (1 - k / 18)))
            a = math.radians(varre - k * 2.2)
            p.drawLine(QPointF(math.cos(a) * R * 0.30, -math.sin(a) * R * 0.30),
                       QPointF(math.cos(a) * R * 0.62, -math.sin(a) * R * 0.62))
        p.restore()

        # 6) anel interno fino com 4 marcadores
        ri = R * 0.62
        p.setPen(caneta(tinta, 1, 90))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), ri, ri)
        for k in range(4):
            a = math.radians(k * 90 + t * 25)
            p.setBrush(cor(tinta, 220))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx + math.cos(a) * ri, cy + math.sin(a) * ri), 3, 3)

        # 7) núcleo: a aura do Ultron
        aura.desenhar(p, cx, cy, R * 0.30, self.est, self.estado)

        # 8) nome e estado
        p.setFont(fonte(13, QFont.Bold, 7))
        p.setPen(cor(QColor(255, 235, 238), 235))
        p.drawText(QRectF(0, cy - 12, w, 24), Qt.AlignCenter, self.nome)
        p.setFont(fonte(7, QFont.Normal, 3))
        rot = {"": "EM ESPERA", 'aguardando "Ultron"': 'DIGA "ULTRON"'}.get(self.estado, self.estado.upper())
        p.setPen(cor(QColor(*self.est.cor), 230))
        p.drawText(QRectF(0, cy + 12, w, 16), Qt.AlignCenter, rot)
        p.end()

    @staticmethod
    def _segmentos(p, cx, cy, raio, n, abertura, largura, giro, c, alfa):
        ret = QRectF(cx - raio, cy - raio, raio * 2, raio * 2)
        p.setPen(caneta(c, largura, alfa))
        p.setBrush(Qt.NoBrush)
        passo = 360 / n
        for i in range(n):
            ini = giro + i * passo
            p.drawArc(ret, int(ini * 16), int(min(abertura, passo - 2) * 16))


# ------------------------------------------------------------------ medidor

class Medidor(QWidget):
    def __init__(self, rotulo, c=VERMELHO):
        super().__init__()
        self.rotulo = rotulo
        self.c = c
        self.valor = 0.0
        self.vis = 0.0
        self.texto = "--"
        self.setFixedSize(84, 92)

    def definir(self, valor, texto=None):
        self.valor = 0.0 if valor is None else float(valor)
        self.texto = texto if texto is not None else (f"{self.valor:.0f}%" if valor is not None else "--")

    def passo(self):
        if abs(self.valor - self.vis) < 0.05:
            return                      # parado: não redesenha
        self.vis += (self.valor - self.vis) * 0.12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = 42, 40, 32
        ret = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setPen(caneta(self.c, 5, 30))
        p.drawArc(ret, 225 * 16, -270 * 16)
        p.setPen(caneta(self.c, 5, 235, Qt.RoundCap))
        p.drawArc(ret, 225 * 16, int(-270 * 16 * min(self.vis, 100) / 100))
        p.setPen(caneta(self.c, 1, 70))
        p.drawEllipse(QPointF(cx, cy), r - 9, r - 9)
        p.setFont(fonte(10, QFont.Bold))
        p.setPen(QColor(240, 232, 234))
        p.drawText(QRectF(0, cy - 10, 84, 20), Qt.AlignCenter, self.texto)
        p.setFont(fonte(7, QFont.Normal, 2))
        p.setPen(cor(self.c, 210))
        p.drawText(QRectF(0, 76, 84, 14), Qt.AlignCenter, self.rotulo)
        p.end()


def rotulo_hud(texto, tamanho=9, c="#B8AEB0", espaco=1):
    l = QLabel(texto)
    l.setStyleSheet(f"font-family:'{FONTE}'; font-size:{tamanho}pt; color:{c}; "
                    f"letter-spacing:{espaco}px; background:transparent;")
    return l


# ------------------------------------------------------------------ vidro (painel flutuante)

class Vidro(QFrame):
    """Painel de vidro que flutua sobre o palco: fundo translúcido escuro, borda carmesim
    tênue, cantos chanfrados e título em caixa alta com um acessório à direita
    (ex.: "ONLINE", relógio). Mostra o palco por baixo."""

    def __init__(self, titulo="", acessorio=""):
        super().__init__()
        self.titulo = titulo.upper()
        self.acessorio = acessorio
        self.ponto = None            # cor do ponto de estado ao lado do título (None = sem ponto)
        self.corpo = QVBoxLayout(self)
        self.corpo.setContentsMargins(14, 40 if titulo else 12, 14, 12)
        self.corpo.setSpacing(8)

    def definir_acessorio(self, texto, ponto=None):
        if (texto, ponto) != (self.acessorio, self.ponto):
            self.acessorio, self.ponto = texto, ponto
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, c = self.width() - 1, self.height() - 1, 10
        from PySide6.QtGui import QPainterPath
        forma = QPainterPath()
        forma.moveTo(c, 0.5)
        forma.lineTo(w, 0.5)
        forma.lineTo(w, h - c)
        forma.lineTo(w - c, h)
        forma.lineTo(0.5, h)
        forma.lineTo(0.5, c)
        forma.closeSubpath()
        p.fillPath(forma, QColor(10, 8, 11, 214))
        p.setPen(QPen(QColor(255, 36, 63, 70), 1))
        p.drawPath(forma)
        p.setPen(QPen(QColor(255, 36, 63, 200), 2))
        p.drawLine(QPointF(c, 0.5), QPointF(c + 26, 0.5))
        p.drawLine(QPointF(w - c, h), QPointF(w - c - 26, h))
        if self.titulo:
            p.setFont(fonte(8, QFont.DemiBold, 2))
            p.setPen(QColor(255, 70, 88))
            larg = p.fontMetrics().horizontalAdvance(self.titulo)
            p.drawText(QRectF(14, 10, w - 28, 18), Qt.AlignLeft | Qt.AlignVCenter, self.titulo)
            if self.ponto:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.ponto))
                p.drawEllipse(QPointF(14 + larg + 9, 19), 3, 3)
            if self.acessorio:
                p.setFont(fonte(8, QFont.Normal, 1))
                p.setPen(QColor(200, 150, 158))
                p.drawText(QRectF(14, 10, w - 28, 18), Qt.AlignRight | Qt.AlignVCenter, self.acessorio)
            p.setPen(QPen(QColor(255, 36, 63, 45), 1))
            p.drawLine(QPointF(14, 32), QPointF(w - 14, 32))
        p.end()
