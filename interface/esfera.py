"""Palco cinematográfico do painel: esfera geodésica em wireframe sobre um horizonte carmesim.

Ocupa a janela inteira; os painéis de vidro flutuam por cima (interface/app.py). Herda do
Nucleo a máquina de estados (animacao.atual(), amplitude real da voz, ferramentas do
barramento, erro, cliques, movimento reduzido, quadros por segundo conforme a atividade)
e troca só o desenho:

  esfera      icosfera (162 vértices) girando; gira mais rápido pensando/executando;
              a superfície se deforma com o VOLUME REAL do microfone/voz e ondula ao processar
  anel        dentro da esfera: forma de onda da amplitude real dos últimos ~2 s
  brilho      o "sol" atrás da esfera acende com a atividade e pulsa com a voz
  órbita      nomes das ferramentas que o Ultron está usando agora (barramento de eventos),
              verde ao concluir e vermelho ao falhar
  erro        a esfera perde a cor e tremula por alguns segundos

Só a área da esfera é redesenhada a cada quadro (o fundo e os painéis não), para o
custo de CPU ficar no nível do núcleo antigo.
"""
import math
import random
import time

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)

from interface.nucleo import Nucleo

FONTE = "FiraCode Nerd Font"


def _icosfera(nivel=2):
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    v = [np.array(p, float) / np.linalg.norm(p) for p in v]
    for _ in range(nivel):
        meio, nf = {}, []

        def m(a, b):
            k = (min(a, b), max(a, b))
            if k not in meio:
                p = v[a] + v[b]
                v.append(p / np.linalg.norm(p))
                meio[k] = len(v) - 1
            return meio[k]
        for a, b, c in f:
            ab, bc, ca = m(a, b), m(b, c), m(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    arestas = {(min(a, b), max(a, b)) for tri in f for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))}
    return np.array(v), np.array(sorted(arestas))


VERT, ARESTAS = _icosfera(2)


class Esfera(Nucleo):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(600, 400)
        self.setCursor(Qt.ArrowCursor)
        self.area = QRectF()          # retângulo livre entre os painéis (a janela define)
        self._fase = np.random.default_rng(7).uniform(0, 2 * math.pi, len(VERT))

    # ------------------------------------------------------------ geometria e interação
    def _geo(self):
        a = self.area if not self.area.isEmpty() else QRectF(self.rect())
        R = max(60.0, min(a.width() * 0.36, a.height() * 0.34))
        return a.center().x(), a.top() + a.height() * 0.44, R

    def _zona_em(self, pos):
        cx, cy, R = self._geo()
        return "nucleo" if math.hypot(pos.x() - cx, pos.y() - cy) < R * 1.05 else None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._zona_em(ev.position()):
            self.ondas.append((time.time(), 1.0))
            self.zona_clicada.emit("nucleo")

    def _rect_animado(self):
        """Em repouso só a esfera muda (o brilho fica constante): ~1.2R. Com voz, atividade,
        erro, ondas de clique ou ferramentas em órbita, o halo e os rótulos também: ~1.75R."""
        cx, cy, R = self._geo()
        agora = time.time()
        largo = (self._ativo() or self.est.nivel > 0.01 or self.em_erro() or self.ondas
                 or any(agora - t0 < 9 for t0, _ in self.ferramentas.values()) or self.zona
                 or getattr(self, "_largo_ate", 0) > agora)
        if largo:
            self._largo_ate = agora + 1.0       # um quadro largo a mais para apagar o que sobrou
        m = R * (1.75 if largo else 1.2)
        return QRect(int(cx - m), int(cy - m), int(2 * m), int(2 * m))

    def update(self, *args):
        """Sem argumentos (o quadro da animação): só a região da esfera."""
        if args:
            return super().update(*args)
        return super().update(self._rect_animado())

    def resizeEvent(self, ev):
        self._cache.clear()
        super().resizeEvent(ev)

    # ------------------------------------------------------------ camadas estáticas (cache)
    def _cenario(self):
        w, h = self.width(), self.height()
        k = ("cenario", w, h, int(self._geo()[1]), int(self._geo()[2]))
        if k not in self._cache:
            self._cache = {c: v for c, v in self._cache.items() if c[0] != "cenario"}
            cx, cy, R = self._geo()
            pm = QPixmap(w, h)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            ceu = QLinearGradient(0, 0, 0, h)
            ceu.setColorAt(0.0, QColor(5, 4, 6))
            ceu.setColorAt(0.55, QColor(14, 6, 9))
            ceu.setColorAt(1.0, QColor(4, 3, 4))
            q.fillRect(0, 0, w, h, ceu)
            hz = cy + R * 0.62                       # horizonte
            # névoa quente no horizonte
            nev = QRadialGradient(QPointF(cx, hz), max(w, h) * 0.6)
            nev.setColorAt(0.0, QColor(120, 18, 30, 90))
            nev.setColorAt(0.35, QColor(60, 8, 16, 50))
            nev.setColorAt(1.0, QColor(0, 0, 0, 0))
            q.fillRect(0, 0, w, h, QBrush(nev))
            # chão em perspectiva
            q.setPen(QPen(QColor(255, 36, 63, 26), 1))
            for i in range(-28, 29):
                q.drawLine(QPointF(cx + i * 18, hz), QPointF(cx + i * 260, h + 40))
            y, passo = hz, 3.0
            while y < h:
                alfa = int(min(40, 8 + (y - hz) / 12))
                q.setPen(QPen(QColor(255, 36, 63, alfa), 1))
                q.drawLine(QPointF(0, y), QPointF(w, y))
                passo *= 1.22
                y += passo
            q.setPen(QPen(QColor(255, 70, 90, 70), 1))
            q.drawLine(QPointF(0, hz), QPointF(w, hz))
            # poeira de estrelas no céu
            rng = random.Random(11)
            q.setPen(Qt.NoPen)
            for _ in range(int(w * h / 9000)):
                x, yy = rng.uniform(0, w), rng.uniform(0, hz)
                q.setBrush(QColor(255, 200, 205, rng.randint(10, 55)))
                q.drawEllipse(QPointF(x, yy), 0.9, 0.9)
            # retícula em colchetes em volta da esfera
            s = R * 1.32
            q.setPen(QPen(QColor(255, 60, 80, 90), 1.2))
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                ax, ay = cx + sx * s, cy + sy * s
                q.drawLine(QPointF(ax, ay), QPointF(ax - sx * 22, ay))
                q.drawLine(QPointF(ax, ay), QPointF(ax, ay - sy * 22))
            q.end()
            self._cache[k] = pm
        return self._cache[k]

    def _sol(self, R):
        k = ("sol", int(R))
        if k not in self._cache:
            self._cache = {c: v for c, v in self._cache.items() if c[0] != "sol"}
            lado = int(R * 3.4)
            pm = QPixmap(lado, lado)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            g = QRadialGradient(QPointF(lado / 2, lado / 2), lado / 2)
            # núcleo incandescente dentro da esfera (até ~0.55R) e halo que some devagar
            g.setColorAt(0.00, QColor(255, 196, 170, 255))
            g.setColorAt(0.10, QColor(255, 120, 96, 250))
            g.setColorAt(0.22, QColor(240, 60, 62, 225))
            g.setColorAt(0.32, QColor(205, 28, 46, 170))
            g.setColorAt(0.44, QColor(150, 14, 34, 95))
            g.setColorAt(0.62, QColor(90, 8, 20, 38))
            g.setColorAt(0.82, QColor(40, 4, 10, 12))
            g.setColorAt(1.00, QColor(0, 0, 0, 0))
            q.fillRect(0, 0, lado, lado, QBrush(g))
            q.end()
            self._cache[k] = pm
        return self._cache[k]

    # ------------------------------------------------------------ desenho
    def paintEvent(self, ev):
        p = QPainter(self)
        p.drawPixmap(ev.rect(), self._cenario(), ev.rect())
        cx, cy, R = self._geo()
        m = R * 1.8
        if not ev.rect().intersects(QRect(int(cx - m), int(cy - m), int(2 * m), int(2 * m))):
            # repintura pedida por um painel translúcido longe da esfera (medidor, rótulo):
            # basta o cenário em cache, sem recalcular a esfera
            p.end()
            return
        p.setRenderHint(QPainter.Antialiasing)
        t = self.tempo_visual
        agora = time.time()
        nivel = self.est.nivel
        ativo = self._ativo()
        erro = self.em_erro()
        esperando = self.estado == "aguardando aprovação"

        # sol atrás da esfera: acende com a atividade e pulsa com a voz
        brilho = 0.78 + (0.17 if ativo else 0) + 0.25 * nivel
        if esperando:
            brilho = 0.45 + 0.2 * math.sin(t * 3)
        if erro:
            brilho = 0.25 + 0.2 * random.random()
        sol = self._sol(R)
        esc = 1.0 + 0.06 * nivel
        p.save()
        p.setOpacity(max(0.0, min(1.0, brilho)))
        p.translate(cx, cy)
        p.scale(esc, esc)
        p.drawPixmap(QPointF(-sol.width() / 2, -sol.height() / 2), sol)
        p.restore()

        # esfera: rotação, inclinação pelo mouse, deformação pela voz e ondulação ao processar
        ay = math.radians(self.giro["a"] * 1.6)
        ax = 0.35 + self.tilt.y() * 0.6
        az = self.tilt.x() * 0.4
        cy_, sy_ = math.cos(ay), math.sin(ay)
        cx_, sx_ = math.cos(ax), math.sin(ax)
        V = VERT
        x = V[:, 0] * cy_ + V[:, 2] * sy_
        z = -V[:, 0] * sy_ + V[:, 2] * cy_
        y = V[:, 1] * cx_ - z * sx_
        z = V[:, 1] * sx_ + z * cx_
        x, y = x * math.cos(az) - y * math.sin(az), x * math.sin(az) + y * math.cos(az)
        pensando = ativo and self.estado not in ("ouvindo", "falando", "aguardando aprovação")
        amp = 0.10 * nivel + (0.035 if pensando else 0.008)
        if self.reduzido:
            amp = 0.02 * nivel
        deforma = 1 + amp * np.sin(self._fase + t * (7 if pensando else 3) + V[:, 1] * 4)
        if erro:
            deforma = deforma + np.random.default_rng(int(agora * 20)).normal(0, 0.03, len(V))
        persp = 3.4 / (3.4 - z * 0.9)
        px = cx + x * R * deforma * persp
        py = cy + y * R * deforma * persp
        a, b = ARESTAS[:, 0], ARESTAS[:, 1]
        frente = (z[a] + z[b]) > 0
        base = (235, 235, 240) if erro else (255, 92, 104)
        for grupo, alfa, larg in ((~frente, 55, 0.8), (frente, 175 + int(60 * nivel), 1.05)):
            p.setPen(QPen(QColor(*base, min(255, alfa)), larg))
            idx = np.nonzero(grupo)[0]
            p.drawLines([QLineF(px[a[i]], py[a[i]], px[b[i]], py[b[i]]) for i in idx])
        # vértices da frente acesos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 210, 210, 150))
        for i in np.nonzero(z > 0.55)[0][::2]:
            p.drawEllipse(QPointF(px[i], py[i]), 1.3, 1.3)

        # anel interno: forma de onda da amplitude real (fica plano quando ninguém fala)
        onda = self.onda[-72:] if self.onda else []
        n = 96
        caminho = QPainterPath()
        for i in range(n + 1):
            ang = 2 * math.pi * i / n
            k = onda[int(i / n * (len(onda) - 1))] if len(onda) > 1 else 0.0
            ruido = math.sin(ang * 9 + t * 4) * (0.012 if pensando else 0.004)
            r = R * (0.52 + 0.20 * k * (0.6 + 0.4 * math.sin(ang * 6 + t * 8)) + ruido)
            pt = QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r * 0.96)
            caminho.moveTo(pt) if i == 0 else caminho.lineTo(pt)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 225, 225, 120 + int(120 * nivel)), 1.6))
        p.drawPath(caminho)

        # ondas de clique
        for t0, _ in self.ondas:
            k = (agora - t0) / 0.9
            p.setPen(QPen(QColor(255, 120, 130, int(200 * (1 - k))), 1.5))
            p.drawEllipse(QPointF(cx, cy), R * (1.0 + 0.5 * k), R * (1.0 + 0.5 * k))

        # órbita: ferramentas em uso agora (dado real do barramento)
        recentes = sorted(((nome, t0, tipo) for nome, (t0, tipo) in self.ferramentas.items() if agora - t0 < 8),
                          key=lambda x: x[1])[-6:]
        if recentes:
            p.setFont(QFont(FONTE, 8))
            for i, (nome, t0, tipo) in enumerate(recentes):
                ang = -math.pi / 2 + (i - (len(recentes) - 1) / 2) * 0.42 + math.pi
                ox, oy = cx + math.cos(ang) * R * 1.42, cy + math.sin(ang) * R * 1.42
                c = (130, 230, 160) if tipo.endswith("completed") else (255, 80, 95) if tipo.endswith("failed") else (255, 190, 195)
                alfa = int(255 * max(0.15, 1 - (agora - t0) / 8))
                p.setPen(QPen(QColor(*c, alfa // 2), 1))
                p.drawLine(QPointF(cx + math.cos(ang) * R * 1.08, cy + math.sin(ang) * R * 1.08), QPointF(ox, oy))
                p.setPen(QColor(*c, alfa))
                p.drawText(QRectF(ox - 90, oy - 18 if oy < cy else oy + 2, 180, 16), Qt.AlignCenter, nome)

        # dica de interação
        if self.zona == "nucleo" and not ativo:
            p.setFont(QFont(FONTE, 8))
            p.setPen(QColor(255, 200, 205, 200))
            p.drawText(QRectF(cx - 120, cy + R * 1.08, 240, 18), Qt.AlignCenter, "CLIQUE PARA FALAR")
        p.end()


class Espectro(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget):
    """Barras da amplitude REAL da voz/microfone (histórico do núcleo). Em silêncio, uma linha
    plana com o rótulo do que está acontecendo; nada de onda inventada."""

    def __init__(self, nucleo):
        super().__init__()
        self.nucleo = nucleo
        self.setMinimumHeight(54)
        self._ultimo = None

    def passo(self):
        onda = tuple(round(x, 2) for x in self.nucleo.onda[-48:])
        if onda != self._ultimo:
            self._ultimo = onda
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(5, 4, 6, 140))
        p.setPen(QPen(QColor(255, 36, 63, 30), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(0, h * i / 4), QPointF(w, h * i / 4))
        onda = list(self.nucleo.onda[-48:])
        n = 48
        larg = w / n
        base = h - 4
        for i in range(n):
            k = onda[i - (n - len(onda))] if i >= n - len(onda) else 0.0
            alt = k * (h - 10)
            if alt < 1:
                continue
            g = QLinearGradient(0, base - alt, 0, base)
            g.setColorAt(0, QColor(255, 120, 130, 230))
            g.setColorAt(1, QColor(200, 16, 46, 160))
            p.fillRect(QRectF(i * larg + 1, base - alt, larg - 2, alt), QBrush(g))
        if not any(x > 0.02 for x in onda):
            p.setFont(QFont(FONTE, 8))
            p.setPen(QColor(200, 150, 158, 160))
            p.drawText(QRectF(0, 0, w, h - 8), Qt.AlignCenter, "SILÊNCIO")
        p.end()
