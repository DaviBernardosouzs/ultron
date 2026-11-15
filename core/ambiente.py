"""Modo ambiente: o Ultron fica escondido ao lado da tela e aparece quando é chamado.

A janela é um orbe com aura (ciano quando ouve, vermelho quando fala, pulsando
quando pensa) e as últimas falas da conversa. Ela lê o estado de core.animacao,
então funciona com o mesmo laço de voz do modo normal, rodando numa thread.

No KDE Wayland os programas não podem se posicionar sozinhos; por isso ele cria
uma regra do KWin (sem borda, sempre no topo, fora da barra de tarefas, no canto
escolhido em ambiente.lado).
"""
import logging
import math
import subprocess
import threading
import time

from core import animacao
from core.config import ajuste

LOG = logging.getLogger("ultron.ambiente")

TITULO = "Ultron Ambiente"
LARGURA, ALTURA = 300, 440
CORES = {"ouvindo": (0x1F, 0xD5, 0xF9), "falando": (0xF5, 0x22, 0x2D)}
# Etapas da evolução: cor própria e uma legenda curta embaixo do orbe.
EVOLUCAO = {"pesquisando": (0x66, 0x00, 0xFF), "desenvolvendo": (0xFF, 0x7A, 0x45),
            "testando": (0xFF, 0xC5, 0x3D), "melhoria concluída": (0x52, 0xC4, 0x1A)}
COR_PENSANDO = (0xB0, 0x10, 0x30)
OCULTOS = ("", 'aguardando "Ultron"')


def _tela():
    """Tamanho lógico da tela principal (ex.: 1280x800 com escala 1.5)."""
    try:
        from PySide6.QtGui import QGuiApplication
        g = QGuiApplication.primaryScreen().geometry()
        return g.width(), g.height()
    except Exception:
        return 1280, 800


def configurar_kwin():
    """Regra do KWin para a janela: posição fixa, sempre no topo, sem borda nem foco."""
    if not subprocess.run(["which", "kwriteconfig6"], capture_output=True).returncode == 0:
        return False
    w, h = _tela()
    margem = int(ajuste("ambiente.margem", 16))
    x = margem if ajuste("ambiente.lado", "direita") == "esquerda" else w - LARGURA - margem
    y = max(0, h - ALTURA - int(ajuste("ambiente.distancia_base", 70)))
    grupo = "ultron-ambiente"
    regras = {
        "Description": "Ultron (modo ambiente)", "title": TITULO, "titlematch": "1",
        "position": f"{x},{y}", "positionrule": "2",
        "size": f"{LARGURA},{ALTURA}", "sizerule": "2",
        "above": "true", "aboverule": "2",
        "skiptaskbar": "true", "skiptaskbarrule": "2",
        "skippager": "true", "skippagerrule": "2",
        "skipswitcher": "true", "skipswitcherrule": "2",
        "noborder": "true", "noborderrule": "2",
        "acceptfocus": "false", "acceptfocusrule": "2",
        "desktops": "", "desktopsrule": "2",   # vazio = em todas as áreas de trabalho
    }
    cfg = ["kwriteconfig6", "--file", "kwinrulesrc"]
    for k, v in regras.items():
        subprocess.run(cfg + ["--group", grupo, "--key", k, v], check=False)
    # registra o grupo na lista de regras sem duplicar
    atual = subprocess.run(["kreadconfig6", "--file", "kwinrulesrc", "--group", "General",
                            "--key", "rules"], capture_output=True, text=True).stdout.strip()
    nomes = [n for n in atual.split(",") if n]
    if grupo not in nomes:
        nomes.append(grupo)
    subprocess.run(cfg + ["--group", "General", "--key", "rules", ",".join(nomes)], check=False)
    subprocess.run(cfg + ["--group", "General", "--key", "count", str(len(nomes))], check=False)
    subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"], capture_output=True)
    return True


def _misturar(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def rodar(laco_de_voz=None, falas=None):
    """Sem laço de voz, devolve o overlay para usar a sessão Qt/voz do painel."""
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QPainter, QPainterPath,
                               QPen, QRadialGradient)
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    if laco_de_voz is not None:
        QGuiApplication.setDesktopFileName("ultron-ambiente")
        app.setQuitOnLastWindowClosed(False)
    obter_falas = falas or animacao.falas
    from PySide6.QtGui import QIcon
    from core.config import RAIZ as _RAIZ
    app.setWindowIcon(QIcon(str(_RAIZ / "icone.png")))
    try:
        configurar_kwin()
    except Exception as e:
        LOG.warning("regra do KWin: %s", e)

    def _caneta(cor, largura):
        c = QPen(cor, largura)
        c.setCapStyle(Qt.RoundCap)
        return c

    class Janela(QWidget):
        def __init__(self):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                             | Qt.WindowDoesNotAcceptFocus)
            self.setWindowTitle(TITULO)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.resize(LARGURA, ALTURA)
            self.t0 = time.time()
            self.nivel = 0.0
            self.cor = self.cor_de = self.cor_para = CORES["ouvindo"]
            self.cor_t = 0.0
            self.opacidade = 0.0      # fade de entrada/saída
            self.visivel_desde = 0.0
            self.ultimo_ativo = 0.0
            self.estado = ""
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._passo)
            self.timer.start(16)

        # ---------------------------------------------------- estado
        def _passo(self):
            agora = time.time()
            est = animacao.atual()
            ativo = est not in OCULTOS
            if ativo:
                self.ultimo_ativo = agora
                self.estado = est
            # aparece na hora; some 1,5 s depois de voltar a esperar o "Ultron"
            quer = ativo or agora - self.ultimo_ativo < 1.5
            if quer and not self.isVisible():
                self.opacidade = 0.0
                self.show()
            self.opacidade += (1.0 if quer else -1.0) * 0.06
            self.opacidade = max(0.0, min(1.0, self.opacidade))
            if not quer and self.opacidade <= 0 and self.isVisible():
                self.hide()
                return
            alvo = CORES.get(self.estado) or EVOLUCAO.get(self.estado, COR_PENSANDO)
            if alvo != self.cor_para:
                self.cor_de, self.cor_para, self.cor_t = self.cor, alvo, agora
            self.cor = _misturar(self.cor_de, self.cor_para, min(1.0, agora - self.cor_t))
            n = (animacao.niveis().get(self.estado, 0.0) if self.estado in CORES
                 else 0.35 + 0.2 * math.sin(agora * 3) if self.estado in EVOLUCAO else 0.15)
            self.nivel += (n - self.nivel) * (0.5 if n > self.nivel else 0.12)
            if self.isVisible():
                self.update()

        # ---------------------------------------------------- desenho
        def paintEvent(self, _ev):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setOpacity(self.opacidade)
            t = time.time() - self.t0
            r, g, b = self.cor
            cx, cy = LARGURA / 2, 150
            n = self.nivel
            base = 62 * (1 + 0.28 * n) + 3 * math.sin(t * 1.6)

            # Aura no estilo do visualizador "aura" do LiveKit: anéis de luz suaves,
            # somados (modo aditivo), que se deslocam e respiram com o volume.
            # Sem texto no meio, só a luz.
            p.setPen(Qt.NoPen)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            halo = QRadialGradient(QPointF(cx, cy), base * 2.0)
            halo.setColorAt(0.0, QColor(r, g, b, 0))
            halo.setColorAt(0.45, QColor(r, g, b, int(40 + 50 * n)))
            halo.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(cx, cy), base * 2.0, base * 2.0)
            branco = _misturar((r, g, b), (255, 255, 255), 0.6)
            for k in range(6):
                fase = k * 1.047
                vel = 0.6 + 0.25 * k
                desvio = base * (0.05 + 0.12 * n)
                ox = cx + desvio * math.cos(t * vel + fase)
                oy = cy + desvio * math.sin(t * vel * 1.3 + fase)
                raio = base * (1 + 0.035 * math.sin(t * (1.1 + 0.3 * k) + fase) + 0.08 * n * math.sin(t * 7 + fase))
                fora = raio * 1.35
                anel = QRadialGradient(QPointF(ox, oy), fora)
                forca = 0.55 + 0.45 * n
                anel.setColorAt(0.0, QColor(r, g, b, 0))
                anel.setColorAt(0.55, QColor(r, g, b, int(10 * forca)))
                anel.setColorAt(0.70, QColor(r, g, b, int(70 * forca)))
                anel.setColorAt(0.74, QColor(*branco, int(90 * forca)))
                anel.setColorAt(0.80, QColor(r, g, b, int(60 * forca)))
                anel.setColorAt(1.0, QColor(r, g, b, 0))
                p.setBrush(QBrush(anel))
                p.drawEllipse(QPointF(ox, oy), fora, fora)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

            if self.estado in EVOLUCAO:
                p.setPen(QColor(r, g, b, 230))
                f = QFont("Monospace", 9)
                f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
                p.setFont(f)
                p.drawText(QRectF(0, cy + base * 1.5, LARGURA, 18), Qt.AlignCenter,
                           "EVOLUINDO · " + self.estado.upper())
            # pensando: arco girando em volta
            if self.estado not in CORES:
                p.setBrush(Qt.NoBrush)
                p.setPen(_caneta(QColor(255, 80, 90, 200), 2))
                ret = QRectF(cx - base * 1.45, cy - base * 1.45, base * 2.9, base * 2.9)
                p.drawArc(ret, int(-t * 360 * 16) % (360 * 16), 90 * 16)

            # últimas falas (até 25 s atrás)
            falas = [txt for quando, txt in obter_falas() if time.time() - quando < 25][-2:]
            if falas:
                p.setFont(QFont("Sans Serif", 10))
                larg = LARGURA - 52
                alturas = [p.boundingRect(QRectF(0, 0, larg, 400), Qt.TextWordWrap, x).height()
                           for x in falas]
                altura = min(sum(alturas) + 6 * (len(falas) - 1) + 20, ALTURA - 276)
                caixa = QRectF(14, 262, LARGURA - 28, altura)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(10, 10, 14, 200))
                p.drawRoundedRect(caixa, 14, 14)
                y = caixa.top() + 10
                for txt, alt in zip(falas, alturas):
                    eh_ultron = txt.lower().startswith("ultron")
                    p.setPen(QColor(255, 120, 125) if eh_ultron else QColor(150, 225, 245))
                    p.drawText(QRectF(caixa.left() + 12, y, larg, caixa.bottom() - y - 4),
                               Qt.TextWordWrap, txt)
                    y += alt + 6
            p.end()

        def mousePressEvent(self, ev):
            # clique direito esconde até a próxima chamada
            if ev.button() == Qt.RightButton:
                self.ultimo_ativo = 0
                self.hide()

    janela = Janela()
    janela._passo()

    if laco_de_voz is None:
        return janela

    def voz():
        try:
            laco_de_voz()
        except SystemExit:
            pass
        except Exception:
            LOG.exception("laço de voz caiu")
        finally:
            app.quit()

    threading.Thread(target=voz, daemon=True, name="voz").start()
    return app.exec()
