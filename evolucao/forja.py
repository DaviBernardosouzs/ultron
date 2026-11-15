"""EVOLUTION FORGE: a janela onde o Davi acompanha e decide a evolução do Ultron.

Painéis (todos com dados reais do pacote evolucao/ e do sistema):
  esquerda  ESTADO DO SISTEMA, CAPACIDADES por tipo (saúde), LOG DA FORJA
  centro    o Ultron (dados/ultron.png) com anéis que mostram a etapa atual
  direita   WORKSPACE (candidatos), OBJETIVOS (necessidades abertas),
            PROTOCOLO (analisar > pesquisar > desenvolver > testar > aprovar),
            INTEGRIDADE (capacidades ok + testes do núcleo) e latência real
  base      navegação: FORJA, CAPACIDADES, APROVAÇÕES, DIAGNÓSTICO, VERSÕES

O Approval Gateway (aba APROVAÇÕES) é o único lugar, junto com a CLI, onde algo é
aprovado, ativado ou volta de versão. Nada disso é ferramenta do modelo.
"""
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from core.config import DADOS, RAIZ, ajuste
from evolucao import (aprovacao, autodiagnostico, avaliacao, base, capacidades, descoberta,
                      extensoes, skills)

FONTE = "FiraCode Nerd Font"
ETAPAS = ["analisar", "pesquisar", "desenvolver", "testar", "aprovar"]
DA_ETAPA = {"pesquisando": "pesquisar", "desenvolvendo": "desenvolver", "testando": "testar",
            "investigando": "analisar", "analisando": "analisar"}

ESTILO = f"""
QWidget {{ color: #e8e2e4; font-size: 12px; }}
QLabel {{ background: transparent; }}
QLabel#dado {{ color: #d8cdd0; }}
QLabel#valor {{ font-family: '{FONTE}'; color: #ffffff; }}
QLabel#rot {{ font-family: '{FONTE}'; font-size: 9px; color: #b9aaae; letter-spacing: 1px; }}
QPushButton {{ background: rgba(40, 10, 14, 200); border: 1px solid #5a1a22; padding: 6px 10px;
              color: #ffd6da; font-family: '{FONTE}'; font-size: 10px; letter-spacing: 1px; }}
QPushButton:hover {{ background: #3a1018; border-color: #ff3344; }}
QPushButton#nav {{ border-radius: 26px; padding: 0; font-size: 20px; background: rgba(20, 6, 9, 220); }}
QPushButton#nav:checked {{ border: 2px solid #ff2a3a; color: #ff2a3a; background: #2a0a10; }}
QPushButton#ok {{ border-color: #2f8a45; color: #9dffb4; }}
QPushButton#perigo {{ border-color: #a02020; color: #ff8a8a; }}
QListWidget, QTableWidget, QTextEdit {{ background: rgba(10, 8, 11, 210); border: 1px solid #2a1418;
    color: #e6dfe1; alternate-background-color: rgba(22, 14, 18, 200); }}
QListWidget::item {{ padding: 4px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: #3a1219; }}
QHeaderView::section {{ background: #16121a; color: #ff6a74; border: none; padding: 5px;
                        font-family: '{FONTE}'; font-size: 10px; }}
QComboBox, QLineEdit {{ background: #121116; border: 1px solid #3a1a20; padding: 4px; color: #f2eaec; }}
QCheckBox {{ background: transparent; }}
"""


def abrir():
    from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
                               QRadialGradient)
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QGridLayout,
                                   QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                                   QPushButton, QSplitter, QStackedWidget, QTableWidget,
                                   QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

    from interface import hud

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(ESTILO)
    app.setWindowIcon(QIcon(str(RAIZ / "icone.png")))
    VERM = QColor(255, 42, 58)

    class Ponte(QObject):
        pronto = Signal(str, object)

    ponte = Ponte()

    def em_fundo(chave, fn, *args):
        import threading

        def job():
            try:
                ponte.pronto.emit(chave, fn(*args))
            except Exception as e:
                ponte.pronto.emit(chave, e)
        threading.Thread(target=job, daemon=True).start()

    def rotulo(texto, nome="rot"):
        l = QLabel(texto)
        l.setObjectName(nome)
        l.setWordWrap(True)
        return l

    # ------------------------------------------------------------ widgets desenhados
    class Radar(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedSize(110, 110)
            self.t0 = time.time()
            self.alertas = 0

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            c = QPointF(55, 55)
            for r in (50, 36, 22, 8):
                p.setPen(QPen(QColor(255, 42, 58, 120 if r != 50 else 200), 1.2 if r == 50 else 1))
                p.drawEllipse(c, r, r)
            p.drawLine(QPointF(5, 55), QPointF(105, 55))
            p.drawLine(QPointF(55, 5), QPointF(55, 105))
            a = (time.time() - self.t0) * 90
            for k in range(14):
                ang = math.radians(a - k * 3)
                p.setPen(QPen(QColor(255, 42, 58, int(150 * (1 - k / 14))), 2))
                p.drawLine(c, c + QPointF(math.cos(ang) * 50, -math.sin(ang) * 50))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 60, 70) if self.alertas else QColor(255, 220, 220))
            p.drawEllipse(c, 3.5, 3.5)
            for k in range(min(self.alertas, 8)):    # um ponto por problema grave real
                ang = k * 2.4
                p.setBrush(QColor(255, 80, 60, 220))
                p.drawEllipse(c + QPointF(math.cos(ang) * (18 + k * 4), math.sin(ang) * (18 + k * 4)), 2.5, 2.5)
            p.end()

    class Barra(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedHeight(8)
            self.valor = 0.0

        def paintEvent(self, _):
            p = QPainter(self)
            w = self.width()
            p.fillRect(QRectF(0, 3, w, 2), QColor(255, 42, 58, 50))
            cor = QColor(255, 42, 58) if self.valor >= 0.999 else QColor(255, 170, 60)
            p.fillRect(QRectF(0, 1, w * self.valor, 5), cor)
            p.end()

    class Nucleo(QWidget):
        """O Ultron no centro, com anéis que mostram a etapa real (etapa.json)."""

        def __init__(self):
            super().__init__()
            self.setMinimumSize(360, 360)
            self.t0 = time.time()
            self.etapa = ""
            caminho = RAIZ / ajuste("visual.imagem", "dados/ultron.png")
            self.img = QPixmap(str(caminho)) if caminho.exists() else QPixmap()
            self._esc = None

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            w, h = self.width(), self.height()
            c = QPointF(w / 2, h / 2)
            R = min(w, h) / 2 - 8
            t = time.time() - self.t0
            ativo = bool(self.etapa)
            vel = 3.0 if ativo else 1.0
            halo = QRadialGradient(c, R * 1.05)
            halo.setColorAt(0, QColor(120, 10, 18, 120))
            halo.setColorAt(0.7, QColor(60, 6, 10, 60))
            halo.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(c, R * 1.05, R * 1.05)
            # imagem recortada num círculo
            ri = R * 0.72
            if not self.img.isNull():
                if self._esc is None or self._esc.width() != int(ri * 2):
                    self._esc = self.img.scaled(int(ri * 2), int(ri * 2), Qt.KeepAspectRatioByExpanding,
                                                Qt.SmoothTransformation)
                caminho = QPainterPath()
                caminho.addEllipse(c, ri, ri)
                p.save()
                p.setClipPath(caminho)
                p.drawPixmap(QPointF(c.x() - self._esc.width() / 2, c.y() - self._esc.height() / 2), self._esc)
                vin = QRadialGradient(c, ri)
                vin.setColorAt(0.65, QColor(0, 0, 0, 0))
                vin.setColorAt(1, QColor(0, 0, 0, 230))
                p.fillRect(QRectF(c.x() - ri, c.y() - ri, ri * 2, ri * 2), QBrush(vin))
                # varredura passando pela imagem enquanto trabalha
                if ativo:
                    y = c.y() - ri + (t * 80 % (ri * 2))
                    p.fillRect(QRectF(c.x() - ri, y, ri * 2, 3), QColor(255, 60, 70, 120))
                p.restore()
            # anéis
            for k, (raio, n, abert, larg, sentido) in enumerate(((0.76, 3, 80, 2.5, 1), (0.84, 48, 4, 1.4, -1),
                                                                 (0.92, 6, 40, 3, 1), (0.98, 120, 1, 1, -1))):
                rr = R * raio
                ret = QRectF(c.x() - rr, c.y() - rr, rr * 2, rr * 2)
                p.setPen(QPen(QColor(255, 42, 58, 200 - k * 30), larg))
                passo = 360 / n
                giro = t * (12 + 8 * k) * vel * sentido
                for i in range(n):
                    p.drawArc(ret, int((giro + i * passo) * 16), int(abert * 16))
            p.setPen(QPen(QColor(255, 42, 58, 230), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, ri + 2, ri + 2)
            p.end()

    class Integridade(QWidget):
        def __init__(self):
            super().__init__()
            self.setMinimumSize(200, 190)
            self.valor = None
            self.vis = 0.0
            self.lat = []

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()
            c = QPointF(w / 2, h / 2 - 8)
            R = min(w, h - 30) / 2 - 6
            alvo = self.valor or 0
            self.vis += (alvo - self.vis) * 0.15
            for i in range(24):
                ini = 90 - i * 15
                aceso = i < round(self.vis / 100 * 24)
                p.setPen(QPen(QColor(255, 42, 58, 230 if aceso else 45), 7, Qt.SolidLine, Qt.FlatCap))
                p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), int(ini * 16), int(-11 * 16))
            p.setPen(QPen(QColor(255, 42, 58, 90), 1))
            p.drawEllipse(c, R - 12, R - 12)
            p.setFont(QFont(FONTE, 20, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(c.x() - R, c.y() - 20, 2 * R, 32), Qt.AlignCenter,
                       f"{self.vis:.0f}%" if self.valor is not None else "--")
            # histograma real das latências (pedido -> resposta)
            if self.lat:
                ult = self.lat[-36:]
                mx = max(ult) or 1
                larg = (R * 1.1) / len(ult)
                for i, v in enumerate(ult):
                    hh = 3 + 16 * v / mx
                    p.fillRect(QRectF(c.x() - R * 0.55 + i * larg, c.y() + 26 - hh, max(1, larg - 1), hh),
                               QColor(255, 42, 58, 160))
            p.setFont(QFont(FONTE, 7))
            p.setPen(QColor(200, 180, 185))
            p.drawText(QRectF(0, h - 18, w, 16), Qt.AlignCenter, "capacidades ok + testes do núcleo")
            p.end()

    # ------------------------------------------------------------ janela
    class Janela(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron · Evolution Forge")
            self.resize(1520, 940)
            fundo = hud.Fundo()
            self.fundo = fundo
            self.setCentralWidget(fundo)
            raiz = QVBoxLayout(fundo)
            raiz.setContentsMargins(16, 12, 16, 12)
            raiz.setSpacing(10)

            # --- cabeçalho
            cab = QHBoxLayout()
            marca = QVBoxLayout()
            marca.addWidget(hud.rotulo_hud("ULTRON", 26, "#f0e6e8", 6))
            marca.addWidget(hud.rotulo_hud("EVOLUTION FORGE", 11, "#ff2a3a", 4))
            self.lbl_versao = hud.rotulo_hud("", 8, "#9a8a8e", 2)
            marca.addWidget(self.lbl_versao)
            cab.addLayout(marca)
            cab.addStretch()
            self.lbl_topo = hud.rotulo_hud("", 9, "#b8aeb0", 2)
            cab.addWidget(self.lbl_topo, alignment=Qt.AlignTop)
            raiz.addLayout(cab)

            corpo = QHBoxLayout()
            corpo.setSpacing(12)
            # --- esquerda
            esq = QVBoxLayout()
            esq.setSpacing(12)
            m = hud.Moldura("estado do sistema")
            linha = QHBoxLayout()
            self.radar = Radar()
            linha.addWidget(self.radar)
            grade = QGridLayout()
            self.estado = {}
            for i, (k, rot) in enumerate((("nucleo", "NÚCLEO"), ("ferr", "FERRAMENTAS"), ("sandbox", "SANDBOX"),
                                          ("testes", "TESTES"), ("aprov", "APROVAÇÕES"))):
                grade.addWidget(rotulo(rot), i, 0)
                v = rotulo("—", "valor")
                grade.addWidget(v, i, 1, alignment=Qt.AlignRight)
                self.estado[k] = v
            linha.addLayout(grade, 1)
            m.corpo.addLayout(linha)
            esq.addWidget(m)
            m = hud.Moldura("capacidades")
            self.barras = {}
            for tipo in ("ferramenta", "plugin", "modo", "extensão", "skill"):
                l = QHBoxLayout()
                l.addWidget(rotulo(tipo.upper()), 2)
                b = Barra()
                l.addWidget(b, 3)
                v = rotulo("—", "valor")
                v.setMinimumWidth(52)
                v.setAlignment(Qt.AlignRight)
                l.addWidget(v)
                self.barras[tipo] = (b, v)
                m.corpo.addLayout(l)
            esq.addWidget(m)
            m = hud.Moldura("log da forja")
            self.log = QListWidget()
            self.log.setStyleSheet(f"font-family:'{FONTE}'; font-size:9px; background: transparent; border: none;")
            self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.log.setTextElideMode(Qt.ElideRight)
            m.corpo.addWidget(self.log)
            esq.addWidget(m, 1)
            caixa = QWidget()
            caixa.setLayout(esq)
            caixa.setFixedWidth(330)
            esq.setContentsMargins(0, 0, 0, 0)
            corpo.addWidget(caixa)

            # --- centro (páginas)
            self.paginas = QStackedWidget()
            self.paginas.addWidget(self._pagina_forja())
            self.paginas.addWidget(self._pagina_capacidades())
            self.paginas.addWidget(self._pagina_aprovacoes())
            self.paginas.addWidget(self._pagina_diagnostico())
            self.paginas.addWidget(self._pagina_versoes())
            corpo.addWidget(self.paginas, 1)

            # --- direita
            dir_ = QVBoxLayout()
            dir_.setSpacing(12)
            m = hud.Moldura("workspace")
            self.workspace = QListWidget()
            self.workspace.setStyleSheet("background: transparent; border: none;")
            m.corpo.addWidget(self.workspace)
            dir_.addWidget(m, 2)
            m = hud.Moldura("objetivos")
            self.objetivos = QListWidget()
            self.objetivos.setStyleSheet("background: transparent; border: none;")
            m.corpo.addWidget(self.objetivos)
            dir_.addWidget(m, 2)
            m = hud.Moldura("protocolo")
            self.protocolo = {}
            for e in ETAPAS:
                l = rotulo(f"→ {e.upper()}", "dado")
                l.setStyleSheet(f"font-family:'{FONTE}'; font-size:10px; letter-spacing:2px; color:#7a6a6e;")
                m.corpo.addWidget(l)
                self.protocolo[e] = l
            dir_.addWidget(m)
            m = hud.Moldura("integridade")
            self.integridade = Integridade()
            m.corpo.addWidget(self.integridade)
            self.lbl_lat = rotulo("", "rot")
            self.lbl_lat.setAlignment(Qt.AlignCenter)
            m.corpo.addWidget(self.lbl_lat)
            dir_.addWidget(m, 2)
            caixa = QWidget()
            caixa.setLayout(dir_)
            caixa.setFixedWidth(330)
            dir_.setContentsMargins(0, 0, 0, 0)
            corpo.addWidget(caixa)
            raiz.addLayout(corpo, 1)

            # --- navegação
            nav = QHBoxLayout()
            nav.addStretch()
            self.bts = []
            for i, (icone, dica) in enumerate((("\U000f0e2a", "Forja"), ("\U000f0ad4", "Capacidades"),
                                               ("\U000f0e1e", "Aprovações"), ("\U000f0128", "Diagnóstico"),
                                               ("\U000f02da", "Versões"))):
                b = QPushButton(icone)
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setFixedSize(52, 52)
                b.setToolTip(dica)
                b.clicked.connect(lambda _=False, i=i: self.ir(i))
                nav.addWidget(b)
                nav.addSpacing(18)
                self.bts.append(b)
            nav.addStretch()
            self.lbl_rodape = hud.rotulo_hud("", 8, "#9a8a8e", 2)
            nav.addWidget(self.lbl_rodape)
            raiz.addLayout(nav)
            self.bts[0].setChecked(True)

            ponte.pronto.connect(self._pronto)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._quadro)
            self.timer.start(40)
            self.t_dados = QTimer(self)
            self.t_dados.timeout.connect(self.atualizar)
            self.t_dados.start(5000)
            self.atualizar()

        def ir(self, i):
            for k, b in enumerate(self.bts):
                b.setChecked(k == i)
            self.paginas.setCurrentIndex(i)
            [lambda: None, self.carregar_capacidades, self.carregar_aprovacoes, lambda: None,
             self.carregar_versoes][i]()

        def _quadro(self):
            if self.isVisible() and not self.isMinimized():
                self.radar.update()
                self.integridade.update()
                if self.paginas.currentIndex() == 0:
                    self.nucleo.update()

        # ------------------------------------------------ dados (thread)
        def atualizar(self):
            em_fundo("painel", self._coletar)

        @staticmethod
        def _coletar():
            itens = capacidades.inventario(salvar=False)
            por = {}
            for i in itens:
                t = i["tipo"]
                ok, tot = por.get(t, (0, 0))
                por[t] = (ok + (i["status"] == "ok"), tot + 1)
            try:
                etapa = json.loads((base.PASTA / "etapa.json").read_text())
                etapa = etapa["estado"] if time.time() - etapa["quando"] < 600 else ""
            except Exception:
                etapa = ""
            candidatos = []
            for pasta in sorted(base.CANDIDATOS.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:12]:
                ult = avaliacao.ultima(pasta.name)
                candidatos.append((pasta.name, ult["aprovado"] if ult else None))
            from evolucao import sandbox
            return {"por": por, "total": len(itens), "etapa": etapa, "candidatos": candidatos,
                    "pendentes": aprovacao.pendentes(), "necessidades": [n for n in descoberta.necessidades()
                                                                         if n["estado"] == "aberta"],
                    "historico": base.historico(12), "testes": autodiagnostico.ultimo_teste(),
                    "latencias": autodiagnostico.latencias(), "sandbox": sandbox.disponivel(),
                    "versao": capacidades._versao_nucleo()}

        def _pronto(self, chave, d):
            if isinstance(d, Exception):
                if chave == "diag":
                    self.diag_status.setText(f"erro: {d}")
                elif chave == "painel":
                    self.lbl_rodape.setText(f"erro ao ler o estado: {d}")
                return
            getattr(self, "_mostrar_" + chave)(d)

        def _mostrar_painel(self, d):
            por = d["por"]
            ferr_ok, ferr_tot = por.get("ferramenta", (0, 0))
            t = d["testes"]
            self.lbl_versao.setText(f"NÚCLEO v{d['versao']}  ·  {d['total']} CAPACIDADES")
            self.estado["nucleo"].setText(f"v{d['versao']}")
            self.estado["ferr"].setText(f"{ferr_ok}/{ferr_tot}")
            self.estado["sandbox"].setText("BWRAP OK" if d["sandbox"] else "INDISPONÍVEL")
            self.estado["testes"].setText(f"{t['passaram']}/{t['passaram'] + t['falharam']}" if t else "NUNCA RODOU")
            self.estado["aprov"].setText(f"{len(d['pendentes'])} PENDENTES")
            self.radar.alertas = (ferr_tot - ferr_ok) + (t["falharam"] if t else 0) + (0 if d["sandbox"] else 1)
            for tipo, (barra, val) in self.barras.items():
                ok, tot = por.get(tipo, (0, 0))
                barra.valor = ok / tot if tot else 0
                barra.update()
                val.setText(f"{ok}/{tot}")
            self.log.clear()
            for h in reversed(d["historico"]):
                self.log.addItem(f"{h.get('quando', '')[11:19]}  {h.get('evento', '').upper()}  {h.get('nome', '') or h.get('resumo', '')}"[:70])
            if not d["historico"]:
                self.log.addItem("sem eventos")
            self.workspace.clear()
            for nome, ok in d["candidatos"]:
                marca = {True: "✔ testado", False: "✖ reprovado", None: "… sem avaliação"}[ok]
                self.workspace.addItem(f"{nome}\n   {marca}")
            if not d["candidatos"]:
                self.workspace.addItem("Nenhum candidato em desenvolvimento.")
            self.objetivos.clear()
            for n in d["necessidades"][:8]:
                self.objetivos.addItem(f"»  {n['descricao'][:90]}")
            if not d["necessidades"]:
                self.objetivos.addItem("Nenhuma necessidade aberta.")
            atual = DA_ETAPA.get(d["etapa"]) or ("aprovar" if d["pendentes"] else None)
            for e, l in self.protocolo.items():
                l.setStyleSheet(f"font-family:'{FONTE}'; font-size:10px; letter-spacing:2px; color:"
                                + ("#ff2a3a; font-weight:bold" if e == atual else "#7a6a6e") + ";")
            self.nucleo.etapa = d["etapa"]
            self.lbl_etapa.setText((d["etapa"] or "em espera").upper()
                                   + (f"  ·  {len(d['pendentes'])} aguardando sua aprovação" if d["pendentes"] else ""))
            saude = [ok / tot for ok, tot in por.values() if tot]
            partes = [sum(saude) / len(saude)] if saude else []
            if t and (t["passaram"] + t["falharam"]):
                partes.append(t["passaram"] / (t["passaram"] + t["falharam"]))
            self.integridade.valor = 100 * sum(partes) / len(partes) if partes else None
            self.integridade.lat = d["latencias"]
            if d["latencias"]:
                lat = sorted(d["latencias"])
                self.lbl_lat.setText(f"RESPOSTA: mediana {lat[len(lat) // 2]:.1f} s · {len(lat)} amostras")
            self.lbl_topo.setText(f"◆ SANDBOX {'ATIVO' if d['sandbox'] else 'OFF'}   ·   "
                                  f"{len(d['necessidades'])} OBJETIVOS   ·   {len(d['candidatos'])} CANDIDATOS")
            self.lbl_rodape.setText(f"ULTRON FORGE · atualizado {datetime.now():%H:%M:%S}")

        # ------------------------------------------------ página: forja
        def _pagina_forja(self):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            self.nucleo = Nucleo()
            v.addWidget(self.nucleo, 1)
            m = hud.Moldura("etapa atual")
            self.lbl_etapa = hud.rotulo_hud("—", 12, "#ff4655", 3)
            self.lbl_etapa.setAlignment(Qt.AlignCenter)
            m.corpo.addWidget(self.lbl_etapa)
            sub = rotulo("O Ultron propõe, testa no sandbox e compara com a versão atual. Só você aprova.", "dado")
            sub.setAlignment(Qt.AlignCenter)
            m.corpo.addWidget(sub)
            v.addWidget(m)
            return w

        # ------------------------------------------------ página: capacidades
        def _pagina_capacidades(self):
            m = hud.Moldura("capability registry")
            f = QHBoxLayout()
            self.cap_tipo = QComboBox()
            self.cap_tipo.addItems(["todos", "ferramenta", "plugin", "modo", "extensão", "skill"])
            self.cap_busca = QLineEdit()
            self.cap_busca.setPlaceholderText("procurar capacidade...")
            self.cap_tipo.currentIndexChanged.connect(self.carregar_capacidades)
            self.cap_busca.textChanged.connect(self.carregar_capacidades)
            f.addWidget(self.cap_tipo)
            f.addWidget(self.cap_busca, 1)
            m.corpo.addLayout(f)
            div = QSplitter(Qt.Vertical)
            self.cap_tab = QTableWidget(0, 7)
            self.cap_tab.setHorizontalHeaderLabels(["Nome", "Tipo", "Origem", "Versão", "Estado", "Nível", "Últimos testes"])
            self.cap_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.cap_tab.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.cap_tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.cap_tab.verticalHeader().setVisible(False)
            self.cap_tab.setAlternatingRowColors(True)
            self.cap_tab.currentCellChanged.connect(lambda r, *_: self._detalhe_cap(r))
            div.addWidget(self.cap_tab)
            self.cap_det = QTextEdit()
            self.cap_det.setReadOnly(True)
            div.addWidget(self.cap_det)
            div.setSizes([500, 180])
            m.corpo.addWidget(div, 1)
            return m

        def carregar_capacidades(self):
            itens = capacidades.inventario(salvar=False)
            t = autodiagnostico.ultimo_teste()
            tipo = self.cap_tipo.currentText()
            txt = self.cap_busca.text().lower().strip()
            itens = [i for i in itens if (tipo == "todos" or i["tipo"] == tipo)
                     and (not txt or txt in (i["nome"] + i["descricao"]).lower())]
            self._caps = itens
            self.cap_tab.setRowCount(len(itens))
            for r, i in enumerate(itens):
                if i["tipo"] in ("extensão", "skill"):
                    nome = i["nome"].split(":", 1)[-1]
                    ult = next((a for a in avaliacao.todas() if a["nome"] == nome), None)
                    teste = (f"{'ok' if ult['aprovado'] else 'falhou'} {ult['quando'][:10]}") if ult else "sem avaliação"
                elif i["tipo"] == "ferramenta":
                    teste = f"suíte {t['passaram']}/{t['passaram'] + t['falharam']}" if t else "suíte nunca rodou"
                else:
                    teste = "—"
                for c, val in enumerate((i["nome"], i["tipo"], i["origem"], str(i["versao"]), i["status"],
                                         str(i["permissoes"].get("nivel", "")), teste)):
                    it = QTableWidgetItem(val)
                    if c == 4 and i["status"] != "ok":
                        it.setForeground(QColor(255, 120, 90))
                    self.cap_tab.setItem(r, c, it)

        def _detalhe_cap(self, r):
            if not 0 <= r < len(getattr(self, "_caps", [])):
                return
            i = self._caps[r]
            self.cap_det.setPlainText(
                f"{i['nome']}  ({i['tipo']}, {i['origem']}, v{i['versao']})\n\n{i['descricao']}\n\n"
                f"Estado: {i['status']}\nDependências: {', '.join(map(str, i['dependencias'])) or '—'}\n"
                f"Permissões: {json.dumps(i['permissoes'], ensure_ascii=False)}\n"
                + (f"Ferramentas: {', '.join(i.get('ferramentas', []))}\n" if i.get("ferramentas") else ""))

        # ------------------------------------------------ página: aprovações (gateway)
        def _pagina_aprovacoes(self):
            m = hud.Moldura("approval gateway")
            aviso = rotulo("Nada é instalado, ativado ou ganha permissão sem a sua decisão aqui. "
                           "O código aprovado precisa ter o mesmo hash do que foi testado.", "dado")
            m.corpo.addWidget(aviso)
            div = QSplitter(Qt.Horizontal)
            esq = QWidget()
            ve = QVBoxLayout(esq)
            ve.setContentsMargins(0, 0, 0, 0)
            self.ap_todos = QCheckBox("mostrar decididos")
            self.ap_todos.toggled.connect(self.carregar_aprovacoes)
            ve.addWidget(self.ap_todos)
            self.ap_lista = QListWidget()
            self.ap_lista.currentRowChanged.connect(self._detalhe_aprov)
            ve.addWidget(self.ap_lista, 1)
            div.addWidget(esq)
            dir_ = QWidget()
            vd = QVBoxLayout(dir_)
            vd.setContentsMargins(0, 0, 0, 0)
            self.ap_det = QTextEdit()
            self.ap_det.setReadOnly(True)
            vd.addWidget(self.ap_det, 1)
            b = QHBoxLayout()
            self.ap_nivel = QComboBox()
            self.ap_nivel.addItems(["N2 · pede confirmação (recomendado)", "N3 · confirma sempre",
                                    "N1 · executa direto"])
            b.addWidget(self.ap_nivel, 1)
            ok = QPushButton("APROVAR")
            ok.setObjectName("ok")
            ok.clicked.connect(self.aprovar)
            no = QPushButton("REJEITAR")
            no.setObjectName("perigo")
            no.clicked.connect(self.rejeitar)
            b.addWidget(ok)
            b.addWidget(no)
            vd.addLayout(b)
            div.addWidget(dir_)
            div.setSizes([260, 520])
            m.corpo.addWidget(div, 1)
            return m

        def carregar_aprovacoes(self):
            todos = aprovacao.listar()
            self._aprov = [p for p in reversed(todos) if self.ap_todos.isChecked() or p["estado"] == "pendente"]
            self.ap_lista.clear()
            for p in self._aprov:
                self.ap_lista.addItem(f"{p['id']}  [{p['estado'].upper()}]\n{p['tipo']} {p['nome']} v{p.get('versao')}")
            if not self._aprov:
                self.ap_lista.addItem("Nenhum pedido pendente.")
                self.ap_det.setPlainText("")

        def _detalhe_aprov(self, r):
            if not 0 <= r < len(getattr(self, "_aprov", [])):
                return
            p = self._aprov[r]
            pasta = Path(p["pasta"])
            arquivos = [f"  {f.relative_to(pasta)}  ({f.stat().st_size} bytes)"
                        for f in sorted(pasta.rglob("*")) if f.is_file() and "node_modules" not in f.parts][:40] \
                if pasta.exists() else ["  (pasta do candidato não existe mais)"]
            man = {}
            for nome in ("manifest.yaml", "plugin.yaml"):
                if (pasta / nome).exists():
                    import yaml
                    man = yaml.safe_load((pasta / nome).read_text()) or {}
            riscos = []
            perm = p.get("permissoes") or {}
            if perm.get("rede"):
                riscos.append("acessa a rede")
            if perm.get("arquivos"):
                riscos.append("lê/grava arquivos")
            if p["tipo"] in ("mcp", "plugin"):
                riscos.append("servidor externo: as ferramentas dele entram com confirmação N2")
            if not riscos:
                riscos.append("sem rede e sem arquivos (roda isolada)")
            hash_atual = base.hash_pasta(pasta) if pasta.exists() else "—"
            ult = avaliacao.ultima(p["candidato"])
            comp = (ult or {}).get("comparacao") or {}
            self.ap_det.setPlainText(
                f"{p['tipo'].upper()} {p['nome']} v{p.get('versao')}   ·   pedido {p['id']}   ·   {p['estado']}\n"
                f"criado {p['criado']}" + (f"  ·  decidido {p.get('decidido')} por {p.get('por')}" if p.get("decidido") else "")
                + f"\n\nDESCRIÇÃO\n{man.get('descricao') or p.get('resumo') or '—'}\n"
                f"\nARQUIVOS ENVOLVIDOS\n" + "\n".join(arquivos)
                + f"\n\nDEPENDÊNCIAS\n{', '.join(map(str, man.get('dependencias', []))) or '—'}"
                f"\n\nPERMISSÕES\n{json.dumps(perm, ensure_ascii=False)}  ·  nível sugerido {p.get('nivel_sugerido')}"
                f"\n\nRISCOS\n" + "\n".join(f"  • {x}" for x in riscos)
                + f"\n\nTESTES E COMPARAÇÃO COM A VERSÃO ATUAL\n{p.get('relatorio', '—')}"
                + (f"\nantes: {comp.get('antes_passaram')} em {comp.get('antes_ms')} ms  ·  "
                   f"depois: {comp.get('depois_passaram')} em {comp.get('depois_ms')} ms" if comp.get("antes_passaram") else "")
                + f"\n\nINTEGRIDADE\nhash testado {p['hash'][:16]}…  ·  hash atual {hash_atual[:16]}…  ·  "
                + ("IGUAIS" if hash_atual == p["hash"] else "DIFERENTES: o código mudou depois do teste; a aprovação será recusada"))

        def _pedido_sel(self):
            r = self.ap_lista.currentRow()
            p = self._aprov[r] if 0 <= r < len(getattr(self, "_aprov", [])) else None
            if p and p["estado"] != "pendente":
                QMessageBox.information(self, "Forge", "Esse pedido já foi decidido.")
                return None
            return p

        def aprovar(self):
            p = self._pedido_sel()
            if not p:
                return
            nivel = self.ap_nivel.currentText()[:2]
            if QMessageBox.question(self, "Aprovar", f"Instalar {p['tipo']} {p['nome']} v{p.get('versao')} "
                                    f"com nível {nivel}?") != QMessageBox.Yes:
                return
            try:
                aprovacao.aprovar(p["id"], nivel=nivel, por="Davi (Evolution Forge)")
                QMessageBox.information(self, "Forge", "Aprovado e instalado. Reinicie o Ultron para carregar.")
            except Exception as e:
                QMessageBox.warning(self, "Forge", f"Não aprovado: {e}")
            self.carregar_aprovacoes()
            self.atualizar()

        def rejeitar(self):
            p = self._pedido_sel()
            if not p:
                return
            motivo, ok = QInputDialog.getText(self, "Rejeitar", "Motivo (o Ultron usa isso para melhorar):")
            if ok:
                aprovacao.rejeitar(p["id"], motivo, por="Davi (Evolution Forge)")
                self.carregar_aprovacoes()
                self.atualizar()

        # ------------------------------------------------ página: diagnóstico
        def _pagina_diagnostico(self):
            m = hud.Moldura("self-diagnostics")
            b = QHBoxLayout()
            rodar = QPushButton("RODAR DIAGNÓSTICO")
            rodar.clicked.connect(self.diagnosticar)
            self.diag_testes = QCheckBox("incluir a suíte de testes (~10 s)")
            corr = QPushButton("PROPOR CORREÇÃO")
            corr.setToolTip("Vira uma necessidade e segue o processo normal: investigar, sandbox, sua aprovação")
            corr.clicked.connect(self.propor)
            b.addWidget(rodar)
            b.addWidget(self.diag_testes)
            b.addStretch()
            b.addWidget(corr)
            m.corpo.addLayout(b)
            self.diag_status = rotulo("Clique em RODAR DIAGNÓSTICO.", "dado")
            m.corpo.addWidget(self.diag_status)
            self.diag_tab = QTableWidget(0, 5)
            self.diag_tab.setHorizontalHeaderLabels(["Nível", "Fonte", "Origem", "Problema", "Sugestão"])
            self.diag_tab.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.diag_tab.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
            self.diag_tab.setColumnWidth(4, 300)
            self.diag_tab.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.diag_tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.diag_tab.verticalHeader().setVisible(False)
            self.diag_tab.setWordWrap(True)
            m.corpo.addWidget(self.diag_tab, 1)
            return m

        def diagnosticar(self):
            self.diag_status.setText("diagnosticando..." + (" rodando os testes..." if self.diag_testes.isChecked() else ""))
            em_fundo("diag", autodiagnostico.completo, self.diag_testes.isChecked())

        def _mostrar_diag(self, d):
            self._achados = d["achados"]
            t, lat = d["testes"], d["latencia"]
            self.diag_status.setText(
                f"{len(self._achados)} achados  ·  testes: "
                + (f"{t['passaram']} ok, {t['falharam']} falhas ({t['quando'][11:16]})" if t else "nunca rodaram")
                + (f"  ·  resposta: mediana {lat['mediana']} s, p90 {lat['p90']} s ({lat['amostras']} pedidos)" if lat else ""))
            self.diag_tab.setRowCount(len(self._achados))
            for r, a in enumerate(self._achados):
                for c, val in enumerate((a["nivel"], a["fonte"], a["origem"],
                                         a["problema"] + (f"  ({a['vezes']}x)" if a.get("vezes", 1) > 1 else ""),
                                         a["sugestao"])):
                    it = QTableWidgetItem(str(val))
                    if c == 0:
                        it.setForeground(QColor(255, 80, 80) if val == "ERROR" else
                                         QColor(255, 180, 80) if val == "WARNING" else QColor(170, 170, 180))
                    self.diag_tab.setItem(r, c, it)
            self.diag_tab.resizeRowsToContents()
            self.atualizar()

        def propor(self):
            r = self.diag_tab.currentRow()
            if not 0 <= r < len(getattr(self, "_achados", [])):
                return
            nid = autodiagnostico.propor_correcao(self._achados[r])
            QMessageBox.information(self, "Forge", f"Necessidade {nid} registrada. O Ultron investiga e, se "
                                    "houver correção, ela passa pelo sandbox e chega aqui para aprovação.")
            self.atualizar()

        # ------------------------------------------------ página: versões
        def _pagina_versoes(self):
            m = hud.Moldura("versões e rollback")
            self.ve_lista = QListWidget()
            m.corpo.addWidget(self.ve_lista, 1)
            b = QHBoxLayout()
            for rot, fn, nome in (("VOLTAR VERSÃO", self.rollback, "perigo"), ("DESATIVAR", self.desativar, ""),
                                  ("REATIVAR", self.reativar, "ok")):
                bt = QPushButton(rot)
                bt.setObjectName(nome)
                bt.clicked.connect(fn)
                b.addWidget(bt)
            m.corpo.addLayout(b)
            return m

        def carregar_versoes(self):
            self.ve_lista.clear()
            self._exts = []
            for nome, est in sorted(extensoes.estados().items()):
                vs = extensoes.versoes(nome)
                self._exts.append(nome)
                self.ve_lista.addItem(f"{nome}   ·   ativa v{est.get('versao', '?')}   ·   "
                                      f"{'ATIVA' if est.get('ativa', True) else 'DESATIVADA'}   ·   nível {est.get('nivel', 'N2')}\n"
                                      f"   versões guardadas: {', '.join(vs) or '—'}")
            for s in skills.instaladas():
                self.ve_lista.addItem(f"skill {s['nome']}   ·   v{s.get('versao', '1')}   ·   {s.get('origem', '')}")
                self._exts.append(None)
            if not self._exts:
                self.ve_lista.addItem("Nenhuma extensão ou skill instalada pela evolução.")

        def _ext_sel(self):
            r = self.ve_lista.currentRow()
            return self._exts[r] if 0 <= r < len(getattr(self, "_exts", [])) else None

        def rollback(self):
            n = self._ext_sel()
            if n and QMessageBox.question(self, "Rollback", f"Voltar {n} para a versão anterior?") == QMessageBox.Yes:
                try:
                    QMessageBox.information(self, "Forge", str(extensoes.rollback(n)))
                except Exception as e:
                    QMessageBox.warning(self, "Forge", str(e))
                self.carregar_versoes()

        def desativar(self):
            n = self._ext_sel()
            if n:
                extensoes.desativar(n)
                self.carregar_versoes()

        def reativar(self):
            n = self._ext_sel()
            if n:
                try:
                    extensoes.reativar(n)
                except Exception as e:
                    QMessageBox.warning(self, "Forge", str(e))
                self.carregar_versoes()

    j = Janela()
    j.show()
    return app.exec()
