"""Janela NEURALINK: o grafo de conhecimento do Ultron e a administração da memória.

Centro: o grafo real (entidades e relações do banco) como uma rede de esferas de
vidro ligadas por fios vermelhos, refletida no piso. Arrastar move, a roda dá
zoom, passar o mouse destaca as ligações, clicar abre o nó no Explorador e o
duplo clique foca na vizinhança dele.

Abas: Explorador, Busca universal, Memória (com sugestões de consolidação),
Linha do tempo e Fontes. Topo: números reais do índice. Nada é simulado: se não
há dado, a tela diz que não há.

Desempenho: o grafo é desenhado uma vez num pixmap (refeito só quando a câmera ou
os dados mudam); por quadro só se animam pulsos e partículas, a ~30 fps, e nada
anima com a janela escondida.
"""
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime

import numpy as np

from core.config import DADOS, RAIZ, ajuste

TIPO_COR = {
    "projeto": (255, 196, 92), "decisao": (255, 120, 40), "nota": (255, 70, 80),
    "documento": (255, 130, 130), "tecnologia": (110, 200, 255), "tag": (255, 90, 160),
    "capacidade": (225, 225, 235), "ferramenta": (170, 170, 185), "modo": (180, 140, 255),
    "plugin": (120, 230, 190), "skill": (120, 230, 190), "extensao": (120, 230, 190),
    "tarefa": (255, 225, 120), "memoria": (255, 70, 80),
}
TIPO_NOME = {"projeto": "projeto", "decisao": "decisão", "nota": "nota", "documento": "documento",
             "tecnologia": "tecnologia", "tag": "tag", "capacidade": "capacidade",
             "ferramenta": "ferramenta", "modo": "modo", "plugin": "plugin", "skill": "skill",
             "extensao": "extensão", "tarefa": "tarefa"}
FONTE = "FiraCode Nerd Font"

from interface.design import STYLE as ESTILO



def _abrir_arquivo(caminho, linha=None):
    if not caminho or caminho.startswith(("conversa:",)):
        return
    if caminho.startswith(("http://", "https://")):
        subprocess.Popen(["xdg-open", caminho], start_new_session=True)
        return
    if linha and os.environ.get("EDITOR_LINHA", "code"):
        try:
            subprocess.Popen(["code", "-g", f"{caminho}:{linha}"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            pass
    subprocess.Popen(["xdg-open", caminho], start_new_session=True)


def _layout(n, arestas, iteracoes=360, semente=7):
    """Fruchterman-Reingold vetorizado com numpy. Devolve posições em ~[-1, 1].
    A atração de cada aresta é dividida pela raiz do grau do hub, senão um nó com
    100 ligações puxa todos para cima dele e o grafo vira um novelo."""
    if n == 0:
        return np.zeros((0, 2))
    rng = np.random.default_rng(semente)
    ang = rng.uniform(0, 2 * np.pi, n)
    raio = np.sqrt(rng.uniform(0.05, 1, n))
    pos = np.c_[np.cos(ang) * raio, np.sin(ang) * raio]
    if not arestas:
        return pos
    a = np.array(arestas)
    grau = np.bincount(a.ravel(), minlength=n).astype(float)
    peso = 1 / np.sqrt(np.maximum(grau[a[:, 0]], grau[a[:, 1]]))[:, None]
    k = 3.6 / math.sqrt(n)
    t = 0.2
    for _ in range(iteracoes):
        d = pos[:, None, :] - pos[None, :, :]
        dist2 = (d ** 2).sum(-1) + 1e-4
        desloc = ((k * k / dist2)[:, :, None] * d).sum(1)
        de = pos[a[:, 0]] - pos[a[:, 1]]
        dl = np.sqrt((de ** 2).sum(-1))[:, None] + 1e-4
        atr = de * dl / k * peso
        np.add.at(desloc, a[:, 0], -atr)
        np.add.at(desloc, a[:, 1], atr)
        desloc -= pos * 0.12                          # gravidade: mantém tudo junto
        tam = np.sqrt((desloc ** 2).sum(-1))[:, None] + 1e-9
        pos += desloc / tam * np.minimum(tam, t)
        t = max(0.004, t * 0.988)
    return _arrumar_componentes(pos, a, n)


def _arrumar_componentes(pos, a, n):
    """O maior componente fica no centro (raio ~1); os pequenos, compactados, em volta."""
    pai = list(range(n))

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    for u, v in a:
        pai[raiz(u)] = raiz(v)
    grupos = {}
    for i in range(n):
        grupos.setdefault(raiz(i), []).append(i)
    ordem = sorted(grupos.values(), key=len, reverse=True)
    principal = np.array(ordem[0])
    centro = np.median(pos[principal], 0)
    escala = np.percentile(np.sqrt(((pos[principal] - centro) ** 2).sum(1)), 90) + 1e-6
    saida = (pos - centro) / escala
    resto = ordem[1:]
    for k, g in enumerate(resto):
        g = np.array(g)
        sub = saida[g] - saida[g].mean(0)
        r = np.sqrt((sub ** 2).sum(1)).max() + 1e-6
        sub = sub / r * min(0.16, 0.05 + 0.02 * len(g))
        ang = -math.pi / 2 + 2 * math.pi * (k + 0.5) / max(1, len(resto))
        saida[g] = sub + np.array([math.cos(ang) * 1.32, math.sin(ang) * 1.0])
    return saida


def abrir():
    from PySide6.QtCore import QDate, QObject, QPointF, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
                               QPainterPath, QPen, QPixmap, QRadialGradient, QTransform)
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit,
                                   QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                                   QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                                   QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                   QTabWidget, QTextEdit, QVBoxLayout, QWidget)

    from neuralink import banco, busca, contexto, grafo, ingestao, memoria, servico

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(ESTILO)
    app.setWindowIcon(QIcon(str(RAIZ / "icone.png")))
    # a memória é privada: aberta sozinha, pede a senha do Ultron
    if not os.environ.get("ULTRON_AUTENTICADO"):
        from interface.app import _login
        if not _login(app):
            return 1
    servico.iniciar()

    def cor(rgb, a=255):
        return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(max(0, min(255, a))))

    class Ponte(QObject):
        grafo_pronto = Signal(object)
        resultado = Signal(str, object)     # chave, dados

    ponte = Ponte()

    def em_fundo(chave, fn, *args):
        def job():
            try:
                ponte.resultado.emit(chave, fn(*args))
            except Exception as e:
                ponte.resultado.emit(chave, e)
        threading.Thread(target=job, daemon=True).start()

    # ================================================================ cena do grafo
    class Cena(QWidget):
        selecionado = Signal(int)
        focar = Signal(int)

        def __init__(self):
            super().__init__()
            self.setMouseTracking(True)
            self.setMinimumSize(520, 420)
            self.nos, self.arestas, self.pos, self.prof = [], [], np.zeros((0, 2)), np.zeros(0)
            self.indice = {}
            self.vizinhos = {}
            self.zoom, self.pan = 1.0, QPointF(0, 0)
            self.hover = self.sel = None
            self.arrastando = None
            self._cache = None
            self._chave_cache = None
            self._fundo = None
            self.pulsos = []
            self.particulas = [[random.random(), random.random(), random.uniform(0.002, 0.008),
                                random.uniform(0.6, 2.2)] for _ in range(45)]
            self.t0 = time.time()
            self.mensagem = "carregando o grafo..."

        def definir(self, nos, arestas, pos):
            self.nos = nos
            self.indice = {n["id"]: i for i, n in enumerate(nos)}
            self.arestas = [(self.indice[a["origem"]], self.indice[a["destino"]], a["tipo"])
                            for a in arestas if a["origem"] in self.indice and a["destino"] in self.indice]
            self.vizinhos = {i: set() for i in range(len(nos))}
            for a, b, _ in self.arestas:
                self.vizinhos[a].add(b)
                self.vizinhos[b].add(a)
            self.pos = pos
            rng = np.random.default_rng(3)
            self.prof = rng.uniform(0, 1, len(nos))           # profundidade aparente
            self.zoom, self.pan = 1.0, QPointF(0, 0)
            self.mensagem = "" if nos else "O grafo está vazio: autorize fontes na aba FONTES."
            self._cache = None
            self.update()

        # ----- geometria
        def _area(self):
            w, h = self.width(), self.height()
            return QRectF(30, 20, w - 60, h * 0.74 - 30)

        def _tela(self, i):
            r = self._area()
            x, y = self.pos[i]
            esc = min(r.width(), r.height()) / 2.3 * self.zoom
            return QPointF(r.center().x() + x * esc + self.pan.x(), r.center().y() + y * esc + self.pan.y())

        def _raio(self, i):
            g = self.nos[i]["grau"]
            return min(15.0, 2.6 + 1.3 * math.sqrt(g)) * (0.65 + 0.6 * self.prof[i]) * min(1.6, max(0.7, self.zoom ** 0.5))

        def _no_em(self, p):
            melhor, dist = None, 1e9
            for i in range(len(self.nos)):
                q = self._tela(i)
                d = math.hypot(q.x() - p.x(), q.y() - p.y())
                if d < max(8, self._raio(i) + 3) and d < dist:
                    melhor, dist = i, d
            return melhor

        # ----- mouse
        def mouseMoveEvent(self, ev):
            p = ev.position()
            if self.arrastando is not None:
                self.pan += p - self.arrastando
                self.arrastando = p
                self._cache = None
                self.update()
                return
            h = self._no_em(p)
            if h != self.hover:
                self.hover = h
                self.setCursor(Qt.PointingHandCursor if h is not None else Qt.OpenHandCursor)
                self.update()

        def mousePressEvent(self, ev):
            i = self._no_em(ev.position())
            if i is not None and ev.button() == Qt.LeftButton:
                self.sel = i
                self.selecionado.emit(self.nos[i]["id"])
                for j in list(self.vizinhos.get(i, []))[:14]:         # pulsos saem do nó
                    self.pulsos.append([i, j, time.time(), random.uniform(0.7, 1.3)])
                self.update()
            else:
                self.arrastando = ev.position()
                self.setCursor(Qt.ClosedHandCursor)

        def mouseReleaseEvent(self, _):
            self.arrastando = None
            self.setCursor(Qt.OpenHandCursor)

        def mouseDoubleClickEvent(self, ev):
            i = self._no_em(ev.position())
            if i is not None:
                self.focar.emit(self.nos[i]["id"])

        def wheelEvent(self, ev):
            fator = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            novo = max(0.35, min(6.0, self.zoom * fator))
            r = self._area()
            m = ev.position() - r.center() - self.pan
            self.pan -= m * (novo / self.zoom - 1)
            self.zoom = novo
            self._cache = None
            self.update()

        def selecionar_id(self, eid):
            if eid in self.indice:
                self.sel = self.indice[eid]
                self.update()

        # ----- desenho
        def _desenhar_fundo(self, w, h):
            pm = QPixmap(w, h)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            g = QRadialGradient(QPointF(w * 0.5, h * 0.36), max(w, h) * 0.8)
            g.setColorAt(0, QColor(42, 42, 48))
            g.setColorAt(0.5, QColor(20, 20, 24))
            g.setColorAt(1, QColor(6, 6, 8))
            p.fillRect(0, 0, w, h, QBrush(g))
            # galerias da sala (faixas curvas) e telas apagadas ao fundo
            for k, y in enumerate((0.16, 0.42, 0.55)):
                path = QPainterPath()
                path.moveTo(0, h * y + 30)
                path.quadTo(w / 2, h * y - 26, w, h * y + 30)
                p.setPen(QPen(QColor(70, 70, 80, 60 - 12 * k), 2))
                p.drawPath(path)
            # bokeh vermelho
            rng = random.Random(11)
            p.setPen(Qt.NoPen)
            for _ in range(14):
                x, y, r = rng.uniform(0, w), rng.uniform(0, h * 0.5), rng.uniform(6, 22)
                gb = QRadialGradient(QPointF(x, y), r)
                gb.setColorAt(0, QColor(255, 70, 60, 90))
                gb.setColorAt(0.7, QColor(255, 70, 60, 50))
                gb.setColorAt(1, QColor(255, 70, 60, 0))
                p.setBrush(QBrush(gb))
                p.drawEllipse(QPointF(x, y), r, r)
            # piso
            piso = QLinearGradient(0, h * 0.74, 0, h)
            piso.setColorAt(0, QColor(18, 18, 22))
            piso.setColorAt(1, QColor(4, 4, 6))
            p.fillRect(QRectF(0, h * 0.74, w, h * 0.26), QBrush(piso))
            p.setPen(QPen(QColor(90, 90, 100, 60), 1))
            p.drawLine(QPointF(0, h * 0.74), QPointF(w, h * 0.74))
            p.end()
            return pm

        def _desenhar_grafo(self, w, h):
            pm = QPixmap(w, h)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            denso = min(1.0, 600 / max(1, len(self.arestas)))     # muitos fios: cada um mais fraco
            fio_largo = QPen(QColor(200, 16, 46, int(10 + 16 * denso)), 3.4)      # carmesim #C8102E
            fio = QPen(QColor(255, 36, 63, int(60 + 60 * denso)), 1.0)            # vermelho luminoso #FF243F
            caminhos = QPainterPath()
            for a, b, _ in self.arestas:
                pa, pb = self._tela(a), self._tela(b)
                meio = (pa + pb) / 2
                dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
                ctrl = QPointF(meio.x() - dy * 0.12, meio.y() + dx * 0.12)
                caminhos.moveTo(pa)
                caminhos.quadTo(ctrl, pb)
            p.setBrush(Qt.NoBrush)
            p.setPen(fio_largo)
            p.drawPath(caminhos)
            p.setPen(fio)
            p.drawPath(caminhos)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            ordem = np.argsort(self.prof)                     # fundos primeiro
            for i in ordem:
                self._esfera(p, i, 1.0)
            # nomes dos nós mais conectados
            p.setFont(QFont(FONTE, 7))
            fm = p.fontMetrics()
            ocupado = []
            for i in sorted(range(len(self.nos)), key=lambda i: -self.nos[i]["grau"])[:16]:
                q = self._tela(i)
                r = self._raio(i)
                nome = self.nos[i]["nome"][:26]
                caixa = QRectF(q.x() - fm.horizontalAdvance(nome) / 2 - 2, q.y() + r + 1,
                               fm.horizontalAdvance(nome) + 4, 13)
                if any(caixa.adjusted(-6, -3, 6, 3).intersects(o) for o in ocupado):
                    continue                              # não empilha nomes
                ocupado.append(caixa)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(5, 5, 7, 205))             # placa: o nome fica legível sobre os fios
                p.drawRoundedRect(caixa.adjusted(-3, -1, 3, 1), 2, 2)
                p.setPen(QColor(230, 232, 236, 230))
                p.drawText(caixa, Qt.AlignCenter, nome)
            p.end()
            return pm

        def _esfera(self, p, i, forca):
            q = self._tela(i)
            r = self._raio(i)
            tint = TIPO_COR.get(self.nos[i]["tipo"], (255, 80, 80))
            prof = 0.55 + 0.45 * self.prof[i]
            brilho = QRadialGradient(q, r * 2.6)
            brilho.setColorAt(0, cor(tint, 70 * forca * prof))
            brilho.setColorAt(1, cor(tint, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(brilho))
            p.drawEllipse(q, r * 2.6, r * 2.6)
            vidro = QRadialGradient(QPointF(q.x() - r * 0.25, q.y() - r * 0.3), r * 1.25)
            vidro.setColorAt(0.0, QColor(255, 255, 255, int(120 * prof)))
            vidro.setColorAt(0.45, cor((40, 30, 34), 150 * prof))
            vidro.setColorAt(0.85, cor(tint, 200 * prof))
            vidro.setColorAt(1.0, cor(tint, 90 * prof))
            p.setBrush(QBrush(vidro))
            p.setPen(QPen(cor((255, 235, 235), 140 * prof), 0.8))
            p.drawEllipse(q, r, r)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(210 * prof)))
            p.drawEllipse(QPointF(q.x() - r * 0.35, q.y() - r * 0.4), r * 0.22, r * 0.16)

        def paintEvent(self, _):
            w, h = self.width(), self.height()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            if self._fundo is None or self._fundo.size() != self.size():
                self._fundo = self._desenhar_fundo(w, h)
            p.drawPixmap(0, 0, self._fundo)
            chave = (w, h, round(self.zoom, 3), round(self.pan.x()), round(self.pan.y()), len(self.nos))
            if self.nos and (self._cache is None or self._chave_cache != chave):
                self._cache, self._chave_cache = self._desenhar_grafo(w, h), chave
            if self.nos:
                # reflexo no piso
                piso = h * 0.74
                p.save()
                p.setOpacity(0.12)
                p.translate(0, piso * 2 - 6)
                p.scale(1, -1)
                p.setClipRect(QRectF(0, piso * 0.25 - 6, w, piso))
                p.drawPixmap(0, 0, self._cache)
                p.restore()
                vela = QLinearGradient(0, piso, 0, h)
                vela.setColorAt(0, QColor(6, 6, 8, 40))
                vela.setColorAt(1, QColor(6, 6, 8, 235))
                p.fillRect(QRectF(0, piso, w, h - piso), QBrush(vela))
                p.drawPixmap(0, 0, self._cache)
            agora = time.time()
            # pulsos de luz viajando pelas ligações
            if self.arestas and len(self.pulsos) < 10 and random.random() < 0.25:
                a, b, _ = random.choice(self.arestas)
                self.pulsos.append([a, b, agora, random.uniform(0.9, 1.8)])
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            vivos = []
            for a, b, t0, dur in self.pulsos:
                k = (agora - t0) / dur
                if k >= 1 or a >= len(self.nos) or b >= len(self.nos):
                    continue
                vivos.append([a, b, t0, dur])
                pa, pb = self._tela(a), self._tela(b)
                meio = (pa + pb) / 2
                dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
                ctrl = QPointF(meio.x() - dy * 0.12, meio.y() + dx * 0.12)
                x = (1 - k) ** 2 * pa.x() + 2 * (1 - k) * k * ctrl.x() + k * k * pb.x()
                y = (1 - k) ** 2 * pa.y() + 2 * (1 - k) * k * ctrl.y() + k * k * pb.y()
                g = QRadialGradient(QPointF(x, y), 9)
                g.setColorAt(0, QColor(255, 235, 225, 230))
                g.setColorAt(0.3, QColor(255, 80, 60, 140))
                g.setColorAt(1, QColor(255, 40, 40, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(x, y), 9, 9)
            self.pulsos = vivos
            # partículas flutuando
            for part in self.particulas:
                part[1] -= part[2] * 0.25
                if part[1] < 0:
                    part[0], part[1] = random.random(), 0.74
                p.setBrush(QColor(255, 120, 100, 120))
                p.drawEllipse(QPointF(part[0] * w, part[1] * h), part[3] * 0.6, part[3] * 0.6)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            # destaque do hover / seleção
            for idx, forte in ((self.sel, True), (self.hover, False)):
                if idx is None or idx >= len(self.nos):
                    continue
                q = self._tela(idx)
                p.setPen(QPen(QColor(255, 120, 110, 200 if forte else 140), 1.6))
                p.setBrush(Qt.NoBrush)
                for j in self.vizinhos.get(idx, []):
                    p.drawLine(q, self._tela(j))
                self._esfera(p, idx, 1.6)
                for j in self.vizinhos.get(idx, []):
                    self._esfera(p, j, 1.2)
                r = self._raio(idx)
                p.setPen(QPen(QColor(255, 255, 255, 220), 1.2))
                p.drawEllipse(q, r + 4, r + 4)
                n = self.nos[idx]
                txt = f"{n['nome']}  ·  {TIPO_NOME.get(n['tipo'], n['tipo'])}  ·  {n['grau']} ligações"
                p.setFont(QFont(FONTE, 8))
                largura = p.fontMetrics().horizontalAdvance(txt) + 16
                caixa = QRectF(min(q.x() + r + 8, w - largura - 4), q.y() - 12, largura, 22)
                p.setPen(QPen(QColor(255, 70, 80, 200), 1))
                p.setBrush(QColor(12, 10, 14, 225))
                p.drawRect(caixa)
                p.setPen(QColor(255, 225, 228))
                p.drawText(caixa, Qt.AlignCenter, txt)
            if self.mensagem:
                p.setFont(QFont(FONTE, 10))
                p.setPen(QColor(255, 150, 155, 200))
                p.drawText(self._area(), Qt.AlignCenter, self.mensagem)
            # legenda
            p.setFont(QFont(FONTE, 7))
            tipos = sorted({n["tipo"] for n in self.nos})
            x = 14
            for t in tipos:
                p.setPen(Qt.NoPen)
                p.setBrush(cor(TIPO_COR.get(t, (255, 80, 80))))
                p.drawEllipse(QPointF(x + 4, h - 14), 4, 4)
                p.setPen(QColor(220, 200, 205, 200))
                rot = TIPO_NOME.get(t, t)
                p.drawText(QPointF(x + 12, h - 10), rot)
                x += 22 + p.fontMetrics().horizontalAdvance(rot)
            p.end()

    # ================================================================ janela
    class Janela(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron · NEURALINK")
            self.resize(1500, 900)
            raiz = QWidget()
            self.setCentralWidget(raiz)
            v = QVBoxLayout(raiz)
            v.setContentsMargins(14, 10, 14, 10)
            v.setSpacing(8)
            # --- topo: título e números reais
            topo = QHBoxLayout()
            titulo = QLabel("N E U R A L I N K")
            titulo.setStyleSheet(f"font-family:'{FONTE}'; font-size:18pt; color:#ff2a3a; letter-spacing:4px;")
            topo.addWidget(titulo)
            sub = QLabel("central de conhecimento do Ultron")
            sub.setStyleSheet("color:#8a7f83; letter-spacing:2px;")
            topo.addWidget(sub)
            topo.addStretch()
            self.cartoes = {}
            for chave, rot in (("docs", "DOCUMENTOS"), ("proj", "PROJETOS"), ("mem", "MEMÓRIAS"),
                               ("fontes", "FONTES"), ("vet", "SEM VETOR"), ("indice", "ÍNDICE"),
                               ("erros", "ERROS")):
                caixa = QVBoxLayout()
                n = QLabel("—")
                n.setStyleSheet(f"font-family:'{FONTE}'; font-size:13pt; color:#ffe3e6;")
                l = QLabel(rot)
                l.setStyleSheet(f"font-family:'{FONTE}'; font-size:7pt; color:#ff4655; letter-spacing:2px;")
                caixa.addWidget(n, alignment=Qt.AlignRight)
                caixa.addWidget(l, alignment=Qt.AlignRight)
                topo.addSpacing(18)
                topo.addLayout(caixa)
                self.cartoes[chave] = n
            v.addLayout(topo)

            div = QSplitter(Qt.Horizontal)
            # --- esquerda: grafo + filtros
            esq = QWidget()
            ve = QVBoxLayout(esq)
            ve.setContentsMargins(0, 0, 0, 0)
            filtros = QHBoxLayout()
            self.ch_tipos = {}
            for t, rot in (("projeto", "projetos"), ("nota", "notas"), ("documento", "documentos"),
                           ("decisao", "decisões"), ("tecnologia", "tecnologias"), ("tag", "tags"),
                           ("capacidade", "capacidades"), ("ferramenta", "ferramentas")):
                ch = QCheckBox(rot)
                ch.setChecked(t not in ("ferramenta",))
                ch.toggled.connect(lambda _: self.carregar_grafo())
                filtros.addWidget(ch)
                self.ch_tipos[t] = ch
            filtros.addStretch()
            bt_tudo = QPushButton("VISÃO GERAL")
            bt_tudo.clicked.connect(lambda: self.carregar_grafo())
            filtros.addWidget(bt_tudo)
            ve.addLayout(filtros)
            self.cena = Cena()
            self.cena.selecionado.connect(self.explorar)
            self.cena.focar.connect(self.focar)
            ve.addWidget(self.cena, 1)
            div.addWidget(esq)
            # --- direita: abas
            self.abas = QTabWidget()
            self.abas.addTab(self._aba_explorador(), "EXPLORADOR")
            self.abas.addTab(self._aba_busca(), "BUSCA")
            self.abas.addTab(self._aba_memoria(), "MEMÓRIA")
            self.abas.addTab(self._aba_tempo(), "LINHA DO TEMPO")
            self.abas.addTab(self._aba_fontes(), "FONTES")
            self.abas.currentChanged.connect(self._ao_trocar_aba)
            div.addWidget(self.abas)
            div.setSizes([930, 540])
            v.addWidget(div, 1)

            ponte.resultado.connect(self._resultado)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._quadro)
            self.timer.start(66)
            self.t_numeros = QTimer(self)
            self.t_numeros.timeout.connect(self.atualizar_numeros)
            self.t_numeros.start(10000)
            self.atualizar_numeros()
            self.carregar_grafo()

        def _quadro(self):
            if (self.isVisible() and not self.isMinimized()
                    and not ajuste("visual.movimento_reduzido", False)
                    and (self.isActiveWindow() or self.cena.underMouse())):
                self.cena.update()

        # ----------------------------------------------------- números do topo
        def atualizar_numeros(self):
            em_fundo("numeros", self._numeros)

        @staticmethod
        def _numeros():
            c = banco.conexao()
            fs = c.execute("SELECT COUNT(*), MAX(sincronizado), SUM(erro IS NOT NULL) FROM fontes").fetchone()
            return {"docs": c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0],
                    "proj": len(contexto.projetos_conhecidos()),
                    "mem": len(list((__import__("core.cofre", fromlist=["x"]).raiz() / "Memórias").glob("*.md"))),
                    "fontes": fs[0], "vet": ingestao.pendentes_vetor(),
                    "indice": (fs[1] or "nunca")[11:16] if fs[1] else "nunca", "erros": fs[2] or 0}

        # ----------------------------------------------------- grafo
        def carregar_grafo(self, foco=None):
            tipos = [t for t, ch in self.ch_tipos.items() if ch.isChecked()]
            if "nota" in tipos:
                tipos.append("memoria")
            if "capacidade" in tipos:
                tipos += ["modo", "plugin", "skill", "extensao"]
            self.cena.mensagem = "calculando o grafo..."
            self.cena.update()

            def job():
                if foco:
                    nos_d, arestas = grafo.relacionadas(foco, profundidade=2, limite=60)
                    graus = {}
                    for a in arestas:
                        graus[a["origem"]] = graus.get(a["origem"], 0) + 1
                        graus[a["destino"]] = graus.get(a["destino"], 0) + 1
                    nos = [dict(n) | {"grau": graus.get(n["id"], 0)} for n in nos_d.values()][:220]
                    ids = {n["id"] for n in nos}
                    arestas = [a for a in arestas if a["origem"] in ids and a["destino"] in ids]
                else:
                    nos, arestas = grafo.visao(limite_nos=200, tipos=tipos or None)
                ligados = {}
                for a in arestas:
                    if a["origem"] != a["destino"]:
                        ligados[a["origem"]] = ligados.get(a["origem"], 0) + 1
                        ligados[a["destino"]] = ligados.get(a["destino"], 0) + 1
                # "grau" = ligações visíveis (tamanho da esfera); "grau_total" = todas, no banco
                nos = [dict(n) | {"grau": ligados[n["id"]], "grau_total": n.get("grau", ligados[n["id"]])}
                       for n in nos if n["id"] in ligados]
                idx = {n["id"]: i for i, n in enumerate(nos)}
                pares = list({(idx[a["origem"]], idx[a["destino"]]) for a in arestas
                              if a["origem"] in idx and a["destino"] in idx})
                return nos, arestas, _layout(len(nos), pares)
            em_fundo("grafo", job)

        def focar(self, eid):
            self.carregar_grafo(foco=eid)
            self.explorar(eid)

        # ----------------------------------------------------- explorador
        def _aba_explorador(self):
            w = QWidget()
            v = QVBoxLayout(w)
            self.ex_titulo = QLabel("Selecione um nó no grafo")
            self.ex_titulo.setStyleSheet(f"font-family:'{FONTE}'; font-size:13pt; color:#ff4655;")
            self.ex_titulo.setWordWrap(True)
            self.ex_info = QLabel("Clique numa esfera para ver o que ela é, com o que se liga e de onde veio. "
                                  "Duplo clique foca a vizinhança dela.")
            self.ex_info.setWordWrap(True)
            self.ex_info.setStyleSheet("color:#bfb3b6;")
            v.addWidget(self.ex_titulo)
            v.addWidget(self.ex_info)
            busca_ent = QLineEdit()
            busca_ent.setPlaceholderText("achar entidade pelo nome...")
            busca_ent.returnPressed.connect(lambda: self._achar_entidade(busca_ent.text()))
            v.addWidget(busca_ent)
            for rot, attr in (("LIGAÇÕES", "ex_rel"), ("DOCUMENTOS DE ORIGEM", "ex_docs"),
                              ("HISTÓRICO", "ex_hist")):
                l = QLabel(rot)
                l.setStyleSheet(f"font-family:'{FONTE}'; font-size:8pt; color:#ff4655; letter-spacing:2px;")
                v.addWidget(l)
                lista = QListWidget()
                setattr(self, attr, lista)
                v.addWidget(lista, 2 if attr == "ex_rel" else 1)
            self.ex_rel.itemDoubleClicked.connect(lambda it: self.explorar(it.data(Qt.UserRole)) if it.data(Qt.UserRole) else None)
            self.ex_rel.itemClicked.connect(lambda it: self.cena.selecionar_id(it.data(Qt.UserRole)))
            self.ex_docs.itemDoubleClicked.connect(lambda it: _abrir_arquivo(it.data(Qt.UserRole)))
            return w

        def _visao_inicial(self):
            """Explorador sem seleção: as entidades mais conectadas (clicáveis) e as últimas mudanças."""
            if self.cena.sel is not None:
                return
            self.ex_rel.clear()
            for n in sorted(self.cena.nos, key=lambda n: -n.get("grau_total", n["grau"]))[:15]:
                it = QListWidgetItem(f"◆  {n['nome']}   ({TIPO_NOME.get(n['tipo'], n['tipo'])} · "
                                     f"{n.get('grau_total', n['grau'])} ligações)")
                it.setData(Qt.UserRole, n["id"])
                self.ex_rel.addItem(it)
            self.ex_docs.clear()
            self.ex_docs.addItem("Selecione um nó para ver de quais documentos ele veio.")
            self.ex_hist.clear()
            for r in banco.conexao().execute("SELECT quando, tipo, titulo FROM eventos ORDER BY quando DESC LIMIT 12"):
                self.ex_hist.addItem(f"{r['quando'][5:16].replace('T', ' ')}  {r['tipo']}  {r['titulo'][:60]}")

        def _achar_entidade(self, texto):
            achadas = grafo.achar(texto.strip()) if texto.strip() else []
            if achadas:
                self.explorar(achadas[0]["id"])
                if achadas[0]["id"] not in self.cena.indice:
                    self.focar(achadas[0]["id"])
            else:
                self.ex_titulo.setText(f"Nada com '{texto}'")

        def explorar(self, eid):
            self.abas.setCurrentIndex(0)
            em_fundo("explorar", grafo.detalhe, eid)

        def _mostrar_detalhe(self, d):
            if not d:
                return
            e = d["entidade"]
            self.cena.selecionar_id(e["id"])
            self.ex_titulo.setText(e["nome"])
            info = [f"<b>{TIPO_NOME.get(e['tipo'], e['tipo'])}</b> · criada {e['criado'][:16].replace('T', ' ')}"]
            if e.get("descricao"):
                info.append(e["descricao"][:400])
            if d["projetos"]:
                info.append("Projetos: " + ", ".join(d["projetos"]))
            self.ex_info.setText("<br>".join(info))
            self.ex_rel.clear()
            nos = d["vizinhos"]
            for a in d["arestas"]:
                sai = a["origem"] == e["id"]
                outro = nos.get(a["destino"] if sai else a["origem"])
                if not outro:
                    continue
                seta = f"→ {a['tipo']}" if sai else f"← {a['tipo']}"
                it = QListWidgetItem(f"{seta}   {outro['nome']}   ({TIPO_NOME.get(outro['tipo'], outro['tipo'])})"
                                     + (f"   · fonte: {a['doc']}" if a["doc"] else ""))
                it.setData(Qt.UserRole, outro["id"])
                self.ex_rel.addItem(it)
            if not d["arestas"]:
                self.ex_rel.addItem("Sem ligações.")
            self.ex_docs.clear()
            for doc in d["documentos"]:
                it = QListWidgetItem(f"{doc['titulo']}\n{doc['caminho']}")
                it.setData(Qt.UserRole, doc["caminho"])
                self.ex_docs.addItem(it)
            if not d["documentos"]:
                self.ex_docs.addItem("Nenhum documento de origem (entidade derivada).")
            self.ex_hist.clear()
            for h in d["historico"]:
                self.ex_hist.addItem(f"{h['quando'][:16].replace('T', ' ')}  {h['tipo']}  {h['detalhe'] or ''}")
            if not d["historico"]:
                self.ex_hist.addItem("Sem alterações registradas.")

        # ----------------------------------------------------- busca universal
        def _aba_busca(self):
            w = QWidget()
            v = QVBoxLayout(w)
            self.bu_campo = QLineEdit()
            self.bu_campo.setPlaceholderText("buscar em todas as fontes autorizadas (Enter)")
            self.bu_campo.returnPressed.connect(self.buscar)
            v.addWidget(self.bu_campo)
            f = QHBoxLayout()
            self.bu_proj, self.bu_tipo, self.bu_cat, self.bu_fonte = (QComboBox() for _ in range(4))
            self.bu_tipo.addItems(["todos os tipos", "markdown", "pdf", "codigo", "texto", "web", "conversa"])
            for cb in (self.bu_proj, self.bu_tipo, self.bu_cat, self.bu_fonte):
                f.addWidget(cb, 1)
            v.addLayout(f)
            f2 = QHBoxLayout()
            self.bu_desde_on = QCheckBox("desde")
            self.bu_desde = QDateEdit(QDate.currentDate().addMonths(-1))
            self.bu_desde.setCalendarPopup(True)
            self.bu_ordem = QComboBox()
            self.bu_ordem.addItems(["por relevância", "mais recentes"])
            f2.addWidget(self.bu_desde_on)
            f2.addWidget(self.bu_desde)
            f2.addStretch()
            f2.addWidget(self.bu_ordem)
            v.addLayout(f2)
            self.bu_status = QLabel("")
            self.bu_status.setStyleSheet("color:#8a7f83;")
            v.addWidget(self.bu_status)
            self.bu_lista = QListWidget()
            self.bu_lista.setWordWrap(True)
            self.bu_lista.itemDoubleClicked.connect(
                lambda it: _abrir_arquivo(*it.data(Qt.UserRole)) if it.data(Qt.UserRole) else None)
            v.addWidget(self.bu_lista, 1)
            return w

        def _preencher_filtros(self):
            c = banco.conexao()
            for cb, primeiro, valores in (
                    (self.bu_proj, "todos os projetos", contexto.projetos_conhecidos()),
                    (self.bu_cat, "todas as categorias",
                     [r[0] for r in c.execute("SELECT DISTINCT categoria FROM documentos WHERE categoria IS NOT NULL ORDER BY 1")]),
                    (self.bu_fonte, "todas as fontes", [f["nome"] for f in ingestao.fontes()])):
                atual = cb.currentText()
                cb.blockSignals(True)
                cb.clear()
                cb.addItems([primeiro] + list(valores))
                if atual in valores:
                    cb.setCurrentText(atual)
                cb.blockSignals(False)

        def buscar(self):
            q = self.bu_campo.text().strip()
            if not q:
                return
            args = dict(
                projetos=[self.bu_proj.currentText()] if self.bu_proj.currentIndex() > 0 else None,
                tipo=self.bu_tipo.currentText() if self.bu_tipo.currentIndex() > 0 else None,
                categoria=self.bu_cat.currentText() if self.bu_cat.currentIndex() > 0 else None,
                fonte=self.bu_fonte.currentText() if self.bu_fonte.currentIndex() > 0 else None,
                desde=self.bu_desde.date().toString("yyyy-MM-dd") if self.bu_desde_on.isChecked() else None)
            self.bu_status.setText("buscando...")
            t = time.time()
            em_fundo("busca", lambda: (busca.buscar(q, k=25, **args), time.time() - t))

        def _mostrar_busca(self, dados):
            res, dt = dados
            if self.bu_ordem.currentIndex() == 1:
                res = sorted(res, key=lambda r: r["indexado"], reverse=True)
            self.bu_lista.clear()
            vet = any(r["similaridade"] for r in res)
            self.bu_status.setText(f"{len(res)} resultados em {dt * 1000:.0f} ms · "
                                   + ("palavras + significado" if vet else "só palavras (desktop/vetores indisponíveis)"))
            for r in res:
                sim = f" · sim {r['similaridade']:.2f}" if r["similaridade"] else ""
                it = QListWidgetItem(f"{r['titulo']}" + (f"  §  {r['secao']}" if r["secao"] else "")
                                     + f"\n{r['texto'][:260].strip()}\n"
                                     f"↳ {r['fonte']} · {r['tipo']}" + (f" · projeto {r['projeto']}" if r["projeto"] else "")
                                     + f" · {r['encontrado_por']}{sim} · relevância {r['pontos']}")
                it.setData(Qt.UserRole, (r["caminho"], r["linha"]))
                it.setToolTip(r["citacao"])
                self.bu_lista.addItem(it)
            if not res:
                self.bu_lista.addItem("Nada encontrado nas fontes autorizadas.")

        # ----------------------------------------------------- memória
        def _aba_memoria(self):
            w = QWidget()
            v = QVBoxLayout(w)
            f = QHBoxLayout()
            self.me_cat = QComboBox()
            self.me_cat.addItems(["todas"] + list(memoria.CATEGORIAS))
            self.me_esc = QComboBox()
            self.me_txt = QLineEdit()
            self.me_txt.setPlaceholderText("filtrar...")
            for x in (self.me_cat, self.me_esc):
                x.currentIndexChanged.connect(self.carregar_memorias)
            self.me_txt.textChanged.connect(self.carregar_memorias)
            f.addWidget(self.me_cat)
            f.addWidget(self.me_esc)
            f.addWidget(self.me_txt, 1)
            v.addLayout(f)
            self.me_tab = QTableWidget(0, 6)
            self.me_tab.setHorizontalHeaderLabels(["Título", "Categoria", "Escopo", "Conf.", "Retenção", "Atualizada"])
            self.me_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.me_tab.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.me_tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.me_tab.verticalHeader().setVisible(False)
            self.me_tab.setAlternatingRowColors(True)
            self.me_tab.cellDoubleClicked.connect(lambda *_: self.editar_memoria())
            v.addWidget(self.me_tab, 3)
            b = QHBoxLayout()
            for rot, fn, nome in (("NOVA", lambda: self.editar_memoria(nova=True), ""),
                                  ("EDITAR", self.editar_memoria, ""),
                                  ("EXCLUIR", self.excluir_memoria, "perigo"),
                                  ("EXPORTAR", self.exportar, ""),
                                  ("CONSOLIDAR", self.consolidar, "")):
                bt = QPushButton(rot)
                bt.setObjectName(nome)
                bt.clicked.connect(fn)
                b.addWidget(bt)
            v.addLayout(b)
            self.me_auto = QCheckBox("Gravação automática: o Ultron aprende sozinho com as conversas")
            self.me_auto.setChecked(memoria.gravacao_automatica())
            self.me_auto.toggled.connect(lambda on: memoria.gravacao_automatica(on))
            v.addWidget(self.me_auto)
            l = QLabel("SUGESTÕES PARA REVISAR (nada muda sem você)")
            l.setStyleSheet(f"font-family:'{FONTE}'; font-size:8pt; color:#ff4655; letter-spacing:2px;")
            v.addWidget(l)
            self.me_sug = QListWidget()
            self.me_sug.setWordWrap(True)
            v.addWidget(self.me_sug, 2)
            b2 = QHBoxLayout()
            ap = QPushButton("APLICAR")
            ap.setObjectName("ok")
            ap.clicked.connect(self.aplicar_sugestao)
            de = QPushButton("DESCARTAR")
            de.clicked.connect(self.descartar_sugestao)
            b2.addWidget(ap)
            b2.addWidget(de)
            b2.addStretch()
            v.addLayout(b2)
            return w

        def carregar_memorias(self):
            todas = memoria.listar()
            escopos = sorted({m["escopo"] for m in todas})
            atual = self.me_esc.currentText()
            self.me_esc.blockSignals(True)
            self.me_esc.clear()
            self.me_esc.addItems(["todos os escopos"] + escopos)
            if atual in escopos:
                self.me_esc.setCurrentText(atual)
            self.me_esc.blockSignals(False)
            cat = self.me_cat.currentText()
            esc = self.me_esc.currentText()
            txt = self.me_txt.text().strip().lower()
            lista = [m for m in todas if (cat == "todas" or m["categoria"] == cat)
                     and (esc == "todos os escopos" or m["escopo"] == esc)
                     and (not txt or txt in (m["titulo"] + " " + m["conteudo"]).lower())]
            self.me_tab.setRowCount(len(lista))
            self._memorias = lista
            for i, m in enumerate(lista):
                for j, val in enumerate((m["titulo"], m["categoria"], m["escopo"], f"{m['confiabilidade']:.1f}",
                                         m["retencao"], m["atualizado"][:16].replace("T", " "))):
                    it = QTableWidgetItem(val)
                    it.setToolTip(m["conteudo"][:500] + f"\n\norigem: {m['origem']}\ncriada: {m['criado']}")
                    self.me_tab.setItem(i, j, it)
            self.me_sug.clear()
            for s in memoria.sugestoes():
                it = QListWidgetItem(f"#{s['id']} {s['tipo'].upper()}: {' / '.join(s['alvos'])}\n{s['motivo']}"
                                     + (f"\nproposta: {json.dumps(s['proposta'], ensure_ascii=False)[:200]}" if s["proposta"] else ""))
                it.setData(Qt.UserRole, s)
                self.me_sug.addItem(it)
            if not self.me_sug.count():
                self.me_sug.addItem("Nenhuma sugestão pendente.")

        def _mem_sel(self):
            r = self.me_tab.currentRow()
            return self._memorias[r] if 0 <= r < len(getattr(self, "_memorias", [])) else None

        def editar_memoria(self, nova=False):
            m = None if nova else self._mem_sel()
            if not nova and not m:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Nova memória" if nova else f"Editar: {m['titulo']}")
            form = QFormLayout(dlg)
            tit = QLineEdit(m["titulo"] if m else "")
            tit.setEnabled(nova)
            cont = QTextEdit(m["conteudo"] if m else "")
            cat = QComboBox()
            cat.addItems(memoria.CATEGORIAS)
            cat.setCurrentText(m["categoria"] if m else "fato")
            esc = QComboBox()
            esc.setEditable(True)
            esc.addItems(["global"] + contexto.projetos_conhecidos())
            esc.setCurrentText(m["escopo"] if m else "global")
            conf = QDoubleSpinBox()
            conf.setRange(0, 1)
            conf.setSingleStep(0.1)
            conf.setValue(m["confiabilidade"] if m else 1.0)
            ret = QComboBox()
            ret.setEditable(True)
            ret.addItems(["permanente", "sessao", "7d", "30d", "90d", "365d"])
            ret.setCurrentText(m["retencao"] if m else "permanente")
            for rot, w_ in (("Título", tit), ("Conteúdo", cont), ("Categoria", cat), ("Escopo", esc),
                            ("Confiabilidade", conf), ("Retenção", ret)):
                form.addRow(rot, w_)
            bts = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            bts.accepted.connect(dlg.accept)
            bts.rejected.connect(dlg.reject)
            form.addRow(bts)
            dlg.resize(560, 420)
            if dlg.exec() != QDialog.Accepted:
                return
            try:
                if nova:
                    memoria.criar(tit.text().strip(), cont.toPlainText().strip(), cat.currentText(),
                                  esc.currentText().strip() or "global", conf.value(), ret.currentText().strip())
                else:
                    memoria.corrigir(m["titulo"], cont.toPlainText().strip()
                                     if cont.toPlainText().strip() != m["conteudo"] else None,
                                     cat.currentText(), esc.currentText().strip() or "global", conf.value(),
                                     ret.currentText().strip())
            except Exception as e:
                QMessageBox.warning(self, "NEURALINK", str(e))
            self.carregar_memorias()

        def excluir_memoria(self):
            m = self._mem_sel()
            if not m:
                return
            if QMessageBox.question(self, "Excluir de vez",
                                    f"Apagar '{m['titulo']}' para sempre?\n\nSai a nota do Obsidian, a cópia "
                                    "da lixeira e tudo o que foi indexado a partir dela. Não dá para desfazer."
                                    ) == QMessageBox.Yes:
                memoria.excluir(m["titulo"])
                self.carregar_memorias()

        def exportar(self):
            destino, _ = QFileDialog.getSaveFileName(self, "Exportar memória",
                                                     str(DADOS / f"neuralink-{datetime.now():%Y%m%d}.json"),
                                                     "JSON (*.json)")
            if destino:
                memoria.exportar(destino)
                QMessageBox.information(self, "NEURALINK", f"Exportado para {destino}")

        def consolidar(self):
            self.me_sug.clear()
            self.me_sug.addItem("procurando duplicadas, contradições e desatualizadas (IA local do desktop)...")
            em_fundo("consolidar", memoria.consolidar)

        def _sug_sel(self):
            it = self.me_sug.currentItem()
            return it.data(Qt.UserRole) if it else None

        def aplicar_sugestao(self):
            s = self._sug_sel()
            if not s:
                return
            try:
                if s["tipo"] == "contradicao":
                    manter, ok = QInputDialog.getItem(self, "Contradição", "Qual versão está certa? A outra será apagada.",
                                                      s["alvos"], 0, False)
                    if not ok:
                        return
                    with banco.transacao() as c:
                        c.execute("UPDATE sugestoes SET proposta=? WHERE id=?", (json.dumps({"manter": manter}), s["id"]))
                elif QMessageBox.question(self, "Aplicar", f"Aplicar a sugestão #{s['id']} ({s['tipo']})?") != QMessageBox.Yes:
                    return
                memoria.aplicar_sugestao(s["id"])
            except Exception as e:
                QMessageBox.warning(self, "NEURALINK", str(e))
            self.carregar_memorias()

        def descartar_sugestao(self):
            s = self._sug_sel()
            if s:
                memoria.descartar_sugestao(s["id"])
                self.carregar_memorias()

        # ----------------------------------------------------- linha do tempo
        def _aba_tempo(self):
            w = QWidget()
            v = QVBoxLayout(w)
            f = QHBoxLayout()
            self.tl_proj = QComboBox()
            self.tl_tipo = QComboBox()
            self.tl_tipo.addItems(["tudo", "decisões", "documentos", "memória", "projetos", "evolução", "tarefas"])
            self.tl_proj.currentIndexChanged.connect(self.carregar_tempo)
            self.tl_tipo.currentIndexChanged.connect(self.carregar_tempo)
            f.addWidget(self.tl_proj, 1)
            f.addWidget(self.tl_tipo, 1)
            v.addLayout(f)
            self.tl_lista = QListWidget()
            self.tl_lista.setWordWrap(True)
            v.addWidget(self.tl_lista, 1)
            return w

        def carregar_tempo(self):
            atual = self.tl_proj.currentText()
            projs = contexto.projetos_conhecidos()
            self.tl_proj.blockSignals(True)
            self.tl_proj.clear()
            self.tl_proj.addItems(["todos os projetos"] + projs)
            if atual in projs:
                self.tl_proj.setCurrentText(atual)
            self.tl_proj.blockSignals(False)
            proj = self.tl_proj.currentText() if self.tl_proj.currentIndex() > 0 else None
            filtro = self.tl_tipo.currentText()
            itens = []
            c = banco.conexao()
            for e in c.execute("SELECT * FROM eventos " + ("WHERE projeto=? " if proj else "") +
                               "ORDER BY quando DESC LIMIT 400", (proj,) if proj else ()):
                itens.append((e["quando"], e["tipo"], e["titulo"], e["detalhe"] or "", e["projeto"]))
            if not proj:
                try:
                    for l in (DADOS / "evolucao" / "historico.jsonl").read_text(encoding="utf-8").splitlines()[-300:]:
                        h = json.loads(l)
                        itens.append((h.get("quando", ""), "evolucao:" + h.get("evento", ""), h.get("nome", ""),
                                      h.get("resumo", ""), None))
                except Exception:
                    pass
                try:
                    for tid, t in json.loads((DADOS / "computacao" / "tarefas.json").read_text()).items():
                        itens.append((t["inicio"], "tarefa_desktop", t["nome"], t["comando"][:120], None))
                except Exception:
                    pass
            grupos = {"decisões": ("decisao",), "documentos": ("documento", "indexacao", "fonte", "conversa"),
                      "memória": ("memoria", "sugestao"), "projetos": ("resumo", "fonte_adicionada"),
                      "evolução": ("evolucao",), "tarefas": ("tarefa",)}
            if filtro != "tudo":
                itens = [x for x in itens if x[1].startswith(grupos[filtro])]
            itens.sort(key=lambda x: x[0], reverse=True)
            self.tl_lista.clear()
            for quando, tipo, titulo, detalhe, p in itens[:400]:
                self.tl_lista.addItem(f"{quando[:16].replace('T', ' ')}   {tipo.upper()}\n{titulo}"
                                      + (f"  ·  {p}" if p else "") + (f"\n{detalhe[:200]}" if detalhe else ""))
            if not itens:
                self.tl_lista.addItem("Nenhum evento registrado ainda.")

        # ----------------------------------------------------- fontes
        def _aba_fontes(self):
            w = QWidget()
            v = QVBoxLayout(w)
            aviso = QLabel("O NEURALINK só lê o que estiver aqui. Nada do computador é examinado sem você "
                           "autorizar a pasta. Remover tira do índice tudo o que veio dela; os arquivos "
                           "originais não são tocados.")
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color:#bfb3b6;")
            v.addWidget(aviso)
            self.fo_tab = QTableWidget(0, 6)
            self.fo_tab.setHorizontalHeaderLabels(["Nome", "Tipo", "Projeto", "Docs", "Sincronizado", "Erro"])
            self.fo_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.fo_tab.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.fo_tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.fo_tab.verticalHeader().setVisible(False)
            v.addWidget(self.fo_tab, 1)
            b = QHBoxLayout()
            for rot, fn, nome in (("+ PASTA", self.add_pasta, ""), ("+ VAULT OBSIDIAN", self.add_pasta, ""),
                                  ("+ URL", self.add_url, ""), ("SINCRONIZAR", self.sincronizar, "ok"),
                                  ("REMOVER", self.remover_fonte, "perigo")):
                bt = QPushButton(rot)
                bt.setObjectName(nome)
                bt.clicked.connect(fn)
                b.addWidget(bt)
            v.addLayout(b)
            self.fo_status = QLabel("")
            self.fo_status.setWordWrap(True)
            self.fo_status.setStyleSheet("color:#8a7f83;")
            v.addWidget(self.fo_status)
            return w

        def carregar_fontes(self):
            fs = ingestao.fontes()
            self._fontes = fs
            self.fo_tab.setRowCount(len(fs))
            for i, f in enumerate(fs):
                for j, val in enumerate((f["nome"], f["tipo"], f["projeto"] or "—", str(f["documentos"]),
                                         (f["sincronizado"] or "nunca")[:16].replace("T", " "), f["erro"] or "")):
                    it = QTableWidgetItem(val)
                    it.setToolTip(f["caminho"])
                    self.fo_tab.setItem(i, j, it)

        def _projeto_para(self, padrao=""):
            projs = [""] + contexto.projetos_conhecidos()
            p, ok = QInputDialog.getItem(self, "Projeto", "Ligar a um projeto? (vazio = conhecimento global)",
                                         projs, 0, True)
            return (p.strip() or None) if ok else False

        def add_pasta(self):
            d = QFileDialog.getExistingDirectory(self, "Pasta autorizada", os.path.expanduser("~"))
            if not d:
                return
            p = self._projeto_para()
            if p is False:
                return
            try:
                fid = ingestao.adicionar_fonte(d, projeto=p)
            except Exception as e:
                QMessageBox.warning(self, "NEURALINK", str(e))
                return
            self.fo_status.setText("indexando... (os vetores são gerados na GPU do desktop)")
            self.carregar_fontes()
            em_fundo("sync", ingestao.sincronizar, fid)

        def add_url(self):
            url, ok = QInputDialog.getText(self, "URL autorizada", "Endereço da página:")
            if not ok or not url.strip().startswith(("http://", "https://")):
                return
            p = self._projeto_para()
            if p is False:
                return
            fid = ingestao.adicionar_fonte(url.strip(), projeto=p)
            em_fundo("sync", ingestao.sincronizar, fid)

        def sincronizar(self):
            self.fo_status.setText("sincronizando (só o que mudou)...")
            em_fundo("sync", ingestao.sincronizar)

        def remover_fonte(self):
            r = self.fo_tab.currentRow()
            if r < 0 or r >= len(getattr(self, "_fontes", [])):
                return
            f = self._fontes[r]
            if QMessageBox.question(self, "Remover fonte", f"Tirar '{f['nome']}' do NEURALINK?\n\n{f['documentos']} "
                                    "documentos saem do índice (trechos, vetores e ligações). Os arquivos "
                                    "originais continuam onde estão.") == QMessageBox.Yes:
                try:
                    n = ingestao.remover_fonte(f["id"])
                    self.fo_status.setText(f"{n} documentos removidos do índice.")
                except Exception as e:
                    QMessageBox.warning(self, "NEURALINK", str(e))
                self.carregar_fontes()
                self.carregar_grafo()

        # ----------------------------------------------------- respostas das threads
        def _ao_trocar_aba(self, i):
            [lambda: None, self._preencher_filtros, self.carregar_memorias, self.carregar_tempo,
             self.carregar_fontes][i]()

        def _resultado(self, chave, dados):
            if isinstance(dados, Exception):
                if chave == "grafo":
                    self.cena.mensagem = f"erro ao montar o grafo: {dados}"
                    self.cena.update()
                elif chave == "busca":
                    self.bu_status.setText(f"erro: {dados}")
                elif chave == "sync":
                    self.fo_status.setText(f"erro: {dados}")
                return
            if chave == "grafo":
                self.cena.definir(*dados)
                self._visao_inicial()
            elif chave == "explorar":
                self._mostrar_detalhe(dados)
            elif chave == "busca":
                self._mostrar_busca(dados)
            elif chave == "numeros":
                for k, val in dados.items():
                    self.cartoes[k].setText(str(val))
                self.cartoes["erros"].setStyleSheet(
                    f"font-family:'{FONTE}'; font-size:13pt; color:{'#ff4655' if dados['erros'] else '#ffe3e6'};")
            elif chave == "sync":
                self.fo_status.setText("\n".join(dados))
                self.carregar_fontes()
                self.carregar_grafo()
                self.atualizar_numeros()
            elif chave == "consolidar":
                self.carregar_memorias()

    j = Janela()
    j.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(abrir())
