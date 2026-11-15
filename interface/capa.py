"""Capa do Ultron Painel: a tela de entrada com o retrato do Ultron (dados/capa.png).

Pede a senha de abertura (a mesma do terminal e da voz). Três erros fecham e avisam
no Telegram, como antes. Sem senha configurada, a capa aparece por um instante e
o painel abre sozinho. Uma linha de varredura passa pelo retrato e o brilho
vermelho pulsa devagar; nada disso roda depois que a capa fecha.
"""
import math
import time

from core.config import RAIZ, ajuste

FONTE = "FiraCode Nerd Font"
FUNDO = (32, 30, 32)      # a mesma cor do fundo do retrato: a imagem não tem borda


def entrar(app):
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPixmap, QRadialGradient
    from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout, QWidget

    from core import senha

    precisa = ajuste("seguranca.senha_ao_abrir", True) and senha.configurada()
    maximo = int(ajuste("seguranca.tentativas_senha", 3))

    class Retrato(QWidget):
        def __init__(self):
            super().__init__()
            caminho = RAIZ / ajuste("visual.capa", "dados/capa.png")
            self.img = QPixmap(str(caminho)) if caminho.exists() else QPixmap()
            self.t0 = time.time()
            self.erro = 0.0
            self.setMinimumSize(420, 420)

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()
            t = time.time() - self.t0
            if not self.img.isNull():
                esc = self.img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x, y = (w - esc.width()) / 2, (h - esc.height()) / 2
                p.drawPixmap(QPointF(x, y), esc)
                # brilho vermelho atrás do rosto, pulsando (mais forte depois de um erro)
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                forca = 26 + 14 * math.sin(t * 1.6) + 120 * self.erro
                g = QRadialGradient(QPointF(w / 2, y + esc.height() * 0.36), esc.width() * 0.42)
                g.setColorAt(0, QColor(255, 30, 40, int(forca)))
                g.setColorAt(1, QColor(255, 30, 40, 0))
                p.fillRect(self.rect(), QBrush(g))
                # varredura descendo pelo retrato
                ly = y + (t * 70) % esc.height()
                faixa = QLinearGradient(0, ly - 18, 0, ly + 2)
                faixa.setColorAt(0, QColor(255, 40, 50, 0))
                faixa.setColorAt(1, QColor(255, 60, 70, 70))
                p.fillRect(QRectF(x, ly - 18, esc.width(), 20), QBrush(faixa))
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            self.erro = max(0.0, self.erro - 0.03)
            p.end()

    class Capa(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron")
            self.resize(760, 880)
            self.setStyleSheet(f"""
                QDialog {{ background: rgb{FUNDO}; }}
                QLabel {{ background: transparent; }}
                QLineEdit {{ background: rgba(14, 12, 14, 230); border: 1px solid #5a1a22; color: #ffe3e6;
                            padding: 10px 14px; font-family: '{FONTE}'; font-size: 14px; letter-spacing: 6px;
                            selection-background-color: #6a1a22; }}
                QLineEdit:focus {{ border-color: #ff2a3a; }}""")
            v = QVBoxLayout(self)
            v.setContentsMargins(40, 24, 40, 30)
            self.retrato = Retrato()
            v.addWidget(self.retrato, 1)
            nome = QLabel("U L T R O N")
            nome.setAlignment(Qt.AlignCenter)
            nome.setStyleSheet(f"font-family:'{FONTE}'; font-size:26pt; color:#ff2a3a; letter-spacing:10px;")
            v.addWidget(nome)
            sub = QLabel("P A I N E L")
            sub.setAlignment(Qt.AlignCenter)
            sub.setStyleSheet(f"font-family:'{FONTE}'; font-size:9pt; color:#9a8a8e; letter-spacing:6px;")
            v.addWidget(sub)
            v.addSpacing(16)
            self.campo = QLineEdit()
            self.campo.setEchoMode(QLineEdit.Password)
            self.campo.setAlignment(Qt.AlignCenter)
            self.campo.setPlaceholderText("IDENTIFIQUE-SE")
            self.campo.returnPressed.connect(self.conferir)
            self.campo.setVisible(precisa)
            v.addWidget(self.campo)
            self.status = QLabel("" if precisa else "inicializando sistemas...")
            self.status.setAlignment(Qt.AlignCenter)
            self.status.setStyleSheet(f"font-family:'{FONTE}'; font-size:9pt; color:#b8aeb0; letter-spacing:2px;")
            v.addWidget(self.status)
            self.erros = 0
            self.ok = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.retrato.update)
            self.timer.start(40)
            if not precisa:
                QTimer.singleShot(1400, self._liberar)

        def conferir(self):
            if senha.confere(self.campo.text()):
                self.status.setStyleSheet(f"font-family:'{FONTE}'; font-size:9pt; color:#9dffb4; letter-spacing:2px;")
                self.status.setText("IDENTIDADE CONFIRMADA")
                self.campo.setEnabled(False)
                QTimer.singleShot(500, self._liberar)
                return
            self.erros += 1
            self.retrato.erro = 1.0
            self.campo.clear()
            restam = maximo - self.erros
            self.status.setStyleSheet(f"font-family:'{FONTE}'; font-size:9pt; color:#ff4655; letter-spacing:2px;")
            self.status.setText(f"SENHA INCORRETA · {restam} TENTATIVA{'S' if restam != 1 else ''}" if restam > 0
                                else "ACESSO NEGADO")
            if restam <= 0:
                self.campo.setEnabled(False)
                QTimer.singleShot(900, self.reject)

        def _liberar(self):
            self.ok = True
            self.timer.stop()
            self.accept()

    capa = Capa()
    capa.exec()
    if not capa.ok and capa.erros >= maximo:
        from ultron import _alerta_invasao
        _alerta_invasao("janela")
    return capa.ok
