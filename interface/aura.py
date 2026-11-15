"""Aura do Ultron para janelas Qt: anéis de luz somados, no estilo do visualizador
"aura" do LiveKit (sem texto no meio). Ciano ouvindo, vermelho falando, arco
girando pensando, cores próprias para as etapas da evolução."""
import math
import time

CORES = {"ouvindo": (0xFF, 0xD2, 0xA0),   # ouvindo: branco quente
          "falando": (0xF5, 0x22, 0x2D),
         "pesquisando": (0x66, 0x00, 0xFF), "desenvolvendo": (0xFF, 0x7A, 0x45),
         "testando": (0xFF, 0xC5, 0x3D), "melhoria concluída": (0x52, 0xC4, 0x1A)}
REPOUSO = (0x8A, 0x10, 0x20)     # aguardando: brasa vermelha fraca
PENSANDO = (0xB0, 0x10, 0x30)
OCIOSOS = ("", 'aguardando "Ultron"')


def misturar(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def cor_do_estado(estado):
    if estado in CORES:
        return CORES[estado]
    return REPOUSO if estado in OCIOSOS else PENSANDO


class Estado:
    """Suaviza cor (1 s linear, como o useMoodColor) e volume entre quadros."""

    def __init__(self):
        self.cor = self.de = self.para = REPOUSO
        self.t_cor = 0.0
        self.nivel = 0.0
        self.t0 = time.time()

    def passo(self, estado, nivel_alvo):
        agora = time.time()
        alvo = cor_do_estado(estado)
        if alvo != self.para:
            self.de, self.para, self.t_cor = self.cor, alvo, agora
        self.cor = misturar(self.de, self.para, min(1.0, agora - self.t_cor))
        self.nivel += (nivel_alvo - self.nivel) * (0.5 if nivel_alvo > self.nivel else 0.12)


def desenhar(p, cx, cy, base, est, estado):
    """Desenha a aura com o QPainter p centrada em (cx, cy)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient

    t = time.time() - est.t0
    r, g, b = est.cor
    n = est.nivel
    ocioso = estado in OCIOSOS
    base = base * (1 + 0.28 * n) + base * 0.04 * math.sin(t * (0.8 if ocioso else 1.6))
    p.save()
    p.setPen(Qt.NoPen)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    halo = QRadialGradient(QPointF(cx, cy), base * 2.0)
    halo.setColorAt(0.0, QColor(r, g, b, 0))
    halo.setColorAt(0.45, QColor(r, g, b, int((25 if ocioso else 40) + 50 * n)))
    halo.setColorAt(1.0, QColor(r, g, b, 0))
    p.setBrush(QBrush(halo))
    p.drawEllipse(QPointF(cx, cy), base * 2.0, base * 2.0)
    branco = misturar((r, g, b), (255, 255, 255), 0.6)
    forca = (0.35 if ocioso else 0.55) + 0.45 * n
    for k in range(6):
        fase = k * 1.047
        vel = (0.25 if ocioso else 0.6) + 0.25 * k
        desvio = base * (0.05 + 0.12 * n)
        ox = cx + desvio * math.cos(t * vel + fase)
        oy = cy + desvio * math.sin(t * vel * 1.3 + fase)
        raio = base * (1 + 0.035 * math.sin(t * (1.1 + 0.3 * k) + fase) + 0.08 * n * math.sin(t * 7 + fase))
        fora = raio * 1.35
        anel = QRadialGradient(QPointF(ox, oy), fora)
        anel.setColorAt(0.0, QColor(r, g, b, 0))
        anel.setColorAt(0.55, QColor(r, g, b, int(10 * forca)))
        anel.setColorAt(0.70, QColor(r, g, b, int(70 * forca)))
        anel.setColorAt(0.74, QColor(*branco, int(90 * forca)))
        anel.setColorAt(0.80, QColor(r, g, b, int(60 * forca)))
        anel.setColorAt(1.0, QColor(r, g, b, 0))
        p.setBrush(QBrush(anel))
        p.drawEllipse(QPointF(ox, oy), fora, fora)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    if not ocioso and estado not in CORES:     # pensando / usando ferramenta
        caneta = QPen(QColor(255, 80, 90, 200), 2)
        caneta.setCapStyle(Qt.RoundCap)
        p.setBrush(Qt.NoBrush)
        p.setPen(caneta)
        ret = QRectF(cx - base * 1.45, cy - base * 1.45, base * 2.9, base * 2.9)
        p.drawArc(ret, int(-t * 360 * 16) % (360 * 16), 90 * 16)
    p.restore()
