"""Ultron Console: interface visual local (Qt nativo, nada de web).

  ultron janela      (o terminal continua funcionando: `ultron`, `ultron --texto`)

Layout: núcleo e conversa com divisor ajustável; sistema/voz e contexto em docks
recolhíveis. Navegação superior para Neuralink, Forge, módulos e terminal. Usa o mesmo cérebro,
as mesmas ferramentas, confirmações N2/N3, senha de abertura e briefing do dia.
"""
import queue
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta

from core import animacao
from core.config import RAIZ, ajuste
from interface import aura

VERMELHO, CIANO = "#F5222D", "#AEB6C2"   # CIANO agora é o aço grafite (secundária)
ICONES = {"dormir": "\U000f0594", "trabalho": "\U000f0322", "relaxar": "\U000f075a", "jogar": "\U000f0297"}
ROTULO_ESTADO = {"": "em espera", 'aguardando "Ultron"': 'diga "Ultron"'}

from interface.design import STYLE as ESTILO



def _no_ar(endereco, porta=22):
    try:
        socket.create_connection((endereco, porta), timeout=1.2).close()
        return True
    except OSError:
        return False


def rodar():
    from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QFont, QIcon, QPainter
    from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDockWidget, QSplitter, QFrame, QGridLayout,
                                   QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                                   QMessageBox, QPushButton, QScrollArea, QSizePolicy, QTabWidget,
                                   QVBoxLayout, QWidget)

    app = QApplication.instance() or QApplication([])
    QApplication.setDesktopFileName("ultron-painel")   # casa com ultron-painel.desktop (ícone na barra)
    app.setWindowIcon(QIcon(str(RAIZ / "icone.png")))
    app.setStyleSheet(ESTILO + """
QPushButton#nav { background:rgba(12,9,12,170); border:1px solid rgba(255,36,63,55); border-radius:2px;
 padding:7px 12px; letter-spacing:1px; }
QPushButton#nav:hover { border-color:rgba(255,36,63,150); background:rgba(40,12,20,200); }
QPushButton#nav:checked { background:rgba(60,14,26,190); border-color:rgba(255,36,63,160); }
QTabWidget#vidro::pane { border:none; background:transparent; }
QTabWidget#vidro > QWidget, QTabWidget#vidro QStackedWidget > QWidget { background:transparent; }
QTabWidget#vidro QTabBar::tab { padding:7px 9px; font-size:10px; letter-spacing:1px; font-family:'FiraCode Nerd Font'; }
""")

    # ------------------------------------------------------------ ponte thread -> interface
    class Ponte(QObject):
        mensagem = Signal(str, str)          # quem ("eu"|"ultron"|"acao"), texto
        perguntar = Signal(str, str)         # ação, nível
        painel = Signal(dict)
        ocupado = Signal(bool)

    ponte = Ponte()
    resposta_conf = {"valor": "nao", "evento": threading.Event()}

    def confirmar(acao, nivel):
        """Chamado pelo cérebro numa thread: pergunta na janela e espera."""
        resposta_conf["evento"].clear()
        ponte.perguntar.emit(acao, nivel)
        resposta_conf["evento"].wait(timeout=300)
        return resposta_conf["valor"]

    # ------------------------------------------------------------ cérebro, voz e fila de pedidos
    from core.cerebro import Cerebro
    cerebro = Cerebro(confirmar, avisar=lambda _f: None)
    pedidos = queue.Queue()
    estado_voz = {"ouvido": None, "falar": bool(ajuste("janela.falar_respostas", True)),
                  "continua": False, "trava_mic": threading.Lock()}

    def _voz():
        from core import voz
        return voz

    def _ouvido():
        if estado_voz["ouvido"] is None:
            ponte.mensagem.emit("acao", "carregando o microfone e o Whisper...")
            from core.ouvido import Ouvido
            _voz().preparar()
            estado_voz["ouvido"] = Ouvido()
        return estado_voz["ouvido"]

    def falar(texto):
        if not estado_voz["falar"] or not texto:
            return
        animacao.estado("falando")
        ouv = estado_voz["ouvido"]
        _voz().falar(texto, ao_comecar=ouv.iniciar_vigia if ouv and estado_voz["continua"] else None)
        if ouv:
            ouv.parar_vigia()

    def processar(texto):
        ponte.mensagem.emit("eu", texto)
        animacao.iniciar("pensando")
        try:
            resposta = cerebro.responder(texto)
        except Exception as e:
            resposta = f"Algo falhou aqui: {e}"
        ponte.mensagem.emit("ultron", resposta)
        falar(resposta)
        animacao.parar()

    def trabalhador():
        while True:
            tipo, dado = pedidos.get()
            ponte.ocupado.emit(True)
            try:
                if tipo == "texto":
                    processar(dado)
                elif tipo == "ouvir":
                    with estado_voz["trava_mic"]:
                        ouv = _ouvido()
                        animacao.iniciar("ouvindo")
                        texto = ouv.ouvir(espera_max=8)
                        animacao.parar()
                    if texto:
                        processar(texto)
                    else:
                        ponte.mensagem.emit("acao", "não ouvi nada")
                elif tipo == "funcao":
                    dado()
                elif tipo == "briefing":
                    from core import briefing
                    animacao.iniciar("preparando o briefing")
                    texto = briefing.gerar(cerebro)
                    ponte.mensagem.emit("ultron", texto)
                    falar(texto)
                    animacao.parar()
            except Exception as e:
                ponte.mensagem.emit("acao", f"erro: {e}")
                animacao.parar()
            finally:
                ponte.ocupado.emit(False)

    threading.Thread(target=trabalhador, daemon=True, name="cerebro").start()

    def escuta_continua():
        """Modo 'diga Ultron': fica ouvindo enquanto a chave estiver ligada."""
        while estado_voz["continua"]:
            try:
                with estado_voz["trava_mic"]:
                    ouv = _ouvido()
                    animacao.iniciar('aguardando "Ultron"')
                    pedido = ouv.esperar_ativacao()
                    if not estado_voz["continua"]:
                        break
                    if not pedido:
                        animacao.estado("falando")
                        if estado_voz["falar"]:
                            _voz().falar("Sim?")
                        animacao.estado("ouvindo")
                        pedido = ouv.ouvir()
                if pedido:
                    feito = threading.Event()
                    pedidos.put(("funcao", lambda p=pedido: (processar(p), feito.set())))
                    feito.wait()
            except Exception as e:
                ponte.mensagem.emit("acao", f"escuta: {e}")
                time.sleep(2)
        animacao.parar()

    # ------------------------------------------------------------ componentes visuais
    from interface import hud
    from interface.telemetria import Telemetria, taxa

    def painel(titulo="", destaque=None):
        return hud.Moldura(titulo, destaque or hud.VERMELHO)

    def secao(texto):
        l = QLabel(texto.upper())
        l.setObjectName("secao")
        return l

    class Janela(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron")
            self.resize(1360, 840)
            self.setMinimumSize(900, 620)
            # palco cinematográfico: a esfera ocupa a janela inteira e os painéis flutuam por cima
            from interface.esfera import Esfera
            self.reator = Esfera()
            self.reator.zona_clicada.connect(self.clicar_nucleo)
            self.palco = self.reator
            self.setCentralWidget(self.palco)

            # --- barra superior: marca, status, navegação e relógio (sem painel, direto no palco)
            self.barra = QWidget(self.palco)
            topo = QHBoxLayout(self.barra)
            topo.setContentsMargins(0, 0, 0, 0)
            marca = hud.rotulo_hud("U L T R O N", 17, "#FF2A3A", 4)
            marca.setStyleSheet(marca.styleSheet() + "font-weight:700;")
            topo.addWidget(marca)
            self.marca = marca
            self.lbl_sistema = hud.rotulo_hud("  CONSOLE LOCAL  /  "
                                              + f"OPERADOR: {ajuste('usuario.nome', 'Davi').upper()}", 8, "#858B96", 0)
            topo.addWidget(self.lbl_sistema)
            topo.addStretch()
            for label, callback in (("NEURALINK", self.abrir_neuralink),
                                    ("FORGE", self.abrir_centro),
                                    ("MÓDULOS", lambda: self.abrir_janela("--modulos")),
                                    ("TERMINAL", self.abrir_terminal)):
                b = QPushButton(label)
                b.setObjectName("nav")
                b.clicked.connect(callback)
                topo.addWidget(b)
            self.ambiente = None
            self._falas_ambiente = []
            self.bt_ambiente = QPushButton("MODO DE CANTO")
            self.bt_ambiente.setObjectName("nav")
            self.bt_ambiente.setCheckable(True)
            self.bt_ambiente.setToolTip(
                'Minimiza o painel e ativa a escuta "Ultron". '
                'Reabra o painel pela barra de tarefas para desativar.')
            self.bt_ambiente.toggled.connect(self.alternar_ambiente)
            topo.addWidget(self.bt_ambiente)
            self.bt_sistema = QPushButton("STATUS")
            self.bt_contexto = QPushButton("DADOS")
            for b in (self.bt_sistema, self.bt_contexto):
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setChecked(True)
                topo.addWidget(b)
            topo.addSpacing(14)
            self.lbl_data = hud.rotulo_hud("", 9, "#A08890", 2)
            self.lbl_hora = hud.rotulo_hud("", 14, "#E6E8EC", 1)
            self.lbl_hora.setStyleSheet(self.lbl_hora.styleSheet() + "font-weight:600;")
            topo.addWidget(self.lbl_data)
            topo.addSpacing(10)
            topo.addWidget(self.lbl_hora)

            # --- STATUS (esquerda, em cima): telemetria e máquinas
            self.p_status = hud.Vidro("status do sistema", "")
            self.p_status.setParent(self.palco)
            grade = QGridLayout()
            grade.setSpacing(2)
            self.med = {}
            for i, (chave, rot, c) in enumerate((("cpu", "CPU", hud.VERMELHO), ("ram", "RAM", hud.CIANO),
                                                 ("disco", "DISCO", hud.VERMELHO), ("bateria", "BATERIA", hud.CIANO),
                                                 ("temp", "TEMP", hud.VERMELHO), ("carga", "CARGA", hud.CIANO))):
                m = hud.Medidor(rot, c)
                self.med[chave] = m
                grade.addWidget(m, i // 3, i % 3, Qt.AlignCenter)
            self.p_status.corpo.addLayout(grade)
            self.lbl_rede = hud.rotulo_hud("", 8, "#A08890", 1)
            self.lbl_ligado = hud.rotulo_hud("", 8, "#A08890", 1)
            self.p_status.corpo.addWidget(self.lbl_rede)
            self.p_status.corpo.addWidget(self.lbl_ligado)
            self.p_status.corpo.addStretch()
            self.bt_sistema.toggled.connect(lambda v: (self.p_status.setVisible(v), self._dispor()))

            # --- CANAL (esquerda, embaixo): a conversa
            self.p_canal = hud.Vidro("canal", "ONLINE")
            self.p_canal.setParent(self.palco)
            self.p_canal.ponto = "#9dffb4"
            self.rolagem = QScrollArea()
            self.rolagem.setWidgetResizable(True)
            self.lista = QWidget()
            self.vl = QVBoxLayout(self.lista)
            self.vl.setContentsMargins(2, 4, 8, 4)
            self.vl.setSpacing(8)
            self.vl.addStretch()
            self.rolagem.setWidget(self.lista)
            self.p_canal.corpo.addWidget(self.rolagem, 1)
            entrada = QHBoxLayout()
            self.campo = QLineEdit()
            self.campo.setAccessibleName("Mensagem para Ultron")
            self.campo.setPlaceholderText("Fale com o Ultron…")
            self.campo.returnPressed.connect(self.enviar)
            bt_limpar = QPushButton("\U000f0a79")
            bt_limpar.setObjectName("icone")
            bt_limpar.setToolTip("Limpar o registro da tela")
            bt_limpar.clicked.connect(self.limpar)
            self.bt_enviar = QPushButton("\U000f048a")
            self.bt_enviar.setObjectName("enviar")
            self.bt_enviar.setAccessibleName("Enviar mensagem")
            self.bt_enviar.setToolTip("Enviar mensagem · Enter")
            self.bt_enviar.clicked.connect(self.enviar)
            entrada.addWidget(self.campo, 1)
            entrada.addWidget(bt_limpar)
            entrada.addWidget(self.bt_enviar)
            self.p_canal.corpo.addLayout(entrada)

            # --- centro: estado sob a esfera (o que o Ultron faz agora, com dados reais)
            self.centro_txt = QWidget(self.palco)
            cv = QVBoxLayout(self.centro_txt)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(3)
            self.lbl_estado = hud.rotulo_hud("EM ESPERA", 15, "#F2E6E8", 4)
            self.lbl_estado.setAlignment(Qt.AlignCenter)
            self.lbl_exec = hud.rotulo_hud("", 9, "#B08890", 1)
            self.lbl_exec.setAlignment(Qt.AlignCenter)
            self.lbl_exec.setWordWrap(True)
            self.lbl_op = hud.rotulo_hud("", 9, "#858B96", 0)
            self.lbl_op.setAlignment(Qt.AlignCenter)
            self.lbl_op.setWordWrap(True)
            for l in (self.lbl_estado, self.lbl_exec, self.lbl_op):
                l.setAttribute(Qt.WA_TransparentForMouseEvents)
                cv.addWidget(l)
            self.centro_txt.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.inicio_acao = None
            self.aprovacao_pendente = False

            # --- CENTRO DE DADOS (direita, em cima): atividade, protocolos, hoje, evolução
            self.p_dados = hud.Vidro("centro de dados", "")
            self.p_dados.setParent(self.palco)
            abas = QTabWidget()
            abas.setObjectName("vidro")
            abas.setUsesScrollButtons(False)
            abas.tabBar().setExpanding(False)
            ativ = QWidget()
            av = QVBoxLayout(ativ)
            av.setContentsMargins(0, 6, 0, 0)
            self.lst_ativ = QVBoxLayout()
            self.lst_ativ.setSpacing(3)
            av.addLayout(self.lst_ativ)
            av.addStretch()
            self._ev_seq = None
            abas.addTab(ativ, "ATIVIDADE")
            abas.addTab(self._painel_modos(), "MODOS")
            hoje = QWidget()
            hv = QVBoxLayout(hoje)
            hv.setContentsMargins(0, 6, 0, 0)
            hv.addWidget(self._painel_maquinas())
            hv.addWidget(self._painel_hoje(), 1)
            hv.addWidget(self._painel_midia())
            abas.addTab(hoje, "HOJE")
            abas.addTab(self._painel_evolucao(), "EVOLUÇÃO")
            self.p_dados.corpo.addWidget(abas, 1)

            # --- VOZ (direita, embaixo): espectro real, microfone e escuta
            self.p_voz = hud.Vidro("voz", "")
            self.p_voz.setParent(self.palco)
            from interface.esfera import Espectro
            self.espectro = Espectro(self.reator)
            self.p_voz.corpo.addWidget(self.espectro, 1)
            linha_mic = QHBoxLayout()
            self.bt_mic = QPushButton("\U000f036c")
            self.bt_mic.setObjectName("mic")
            self.bt_mic.setFixedSize(48, 48)
            self.bt_mic.setToolTip("Falar agora (clique e fale)")
            self.bt_mic.clicked.connect(lambda: pedidos.put(("ouvir", None)))
            linha_mic.addWidget(self.bt_mic)
            chaves = QVBoxLayout()
            self.ch_continua = QCheckBox('ESCUTA "ULTRON"')
            self.ch_continua.toggled.connect(self.alternar_continua)
            self.ch_falar = QCheckBox("RESPONDER EM VOZ")
            self.ch_falar.setChecked(estado_voz["falar"])
            self.ch_falar.toggled.connect(lambda v: estado_voz.__setitem__("falar", v))
            self.ch_reduzido = QCheckBox("MOVIMENTO REDUZIDO")
            self.ch_reduzido.setChecked(self.reator.reduzido)
            self.ch_reduzido.toggled.connect(lambda v: setattr(self.reator, "reduzido", v))
            for c in (self.ch_continua, self.ch_falar, self.ch_reduzido):
                chaves.addWidget(c)
            linha_mic.addLayout(chaves, 1)
            self.p_voz.corpo.addLayout(linha_mic)
            self.bt_contexto.toggled.connect(lambda v: (self.p_dados.setVisible(v), self.p_voz.setVisible(v),
                                                        self._dispor()))
            self._dispor()

            for bt in self.findChildren(QPushButton):
                bt.setFocusPolicy(Qt.StrongFocus)
            self.campo.setFocus()
            ponte.mensagem.connect(self.adicionar)
            ponte.perguntar.connect(self.perguntar)
            ponte.painel.connect(self.atualizar_paineis)
            ponte.ocupado.connect(self.ocupado)
            self.telemetria = Telemetria()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.quadro)
            self.timer.start(33)      # o núcleo limita os próprios quadros
            self.t_tele = QTimer(self)
            self.t_tele.timeout.connect(self.ler_telemetria)
            self.t_tele.start(1000)
            self.t_ativ = QTimer(self)
            self.t_ativ.timeout.connect(self.ler_atividade)
            self.t_ativ.start(1000)
            self.ler_telemetria()
            self.ultimo_estado = None
            threading.Thread(target=self.coletar_paineis, daemon=True).start()
            threading.Thread(target=self.coletar_desktop, daemon=True).start()

        def _operacao(self):
            """Resumo real da operação em curso para o HUD (barramento de eventos e módulos)."""
            from core import eventos
            partes = []
            ini = eventos.consultar(tipo="task.started", origem="cerebro", limite=1)
            if ini:
                evs = eventos.consultar(correlacao=ini[0]["correlacao"], apos=0, limite=200)
                aberta = not any(e["tipo"] in ("task.completed", "task.failed") and e["origem"] == "cerebro" for e in evs)
                feitas = sum(e["tipo"] == "tool.completed" for e in evs)
                falhas = sum(e["tipo"] == "tool.failed" for e in evs)
                fechadas = [e["pai"] for e in evs if e["tipo"] in ("tool.completed", "tool.failed")]
                em_curso = [e["dados"].get("ferramenta") for e in evs if e["tipo"] == "tool.started" and e["id"] not in fechadas]
                if aberta and em_curso:
                    partes.append(f"FERRAMENTA · {em_curso[-1]}")
                if feitas or falhas:
                    partes.append(f"OPERAÇÕES {feitas} ✓" + (f" {falhas} ✗" if falhas else ""))
            try:
                from modulos import claude_bridge, vector
                if any(t["estado"] == "executando" for t in claude_bridge.listar(5)):
                    partes.insert(0, "EXECUTOR · CLAUDE CODE")
                plano = next((p for p in vector.listar(10) if p["estado"] in ("executando", "pausado")), None)
                if plano:
                    det = vector.obter(plano["id"])
                    atual = next((e for e in det["etapas"] if e["estado"] not in ("feita", "pulada")), None)
                    feitas_p = sum(e["estado"] == "feita" for e in det["etapas"])
                    partes.append(f"PLANO {feitas_p}/{len(det['etapas'])}" + (f" · {atual['descricao'][:40]}" if atual else ""))
            except Exception:
                pass
            try:
                from core import guardian
                from modulos import claude_bridge
                pend = len(guardian.pedidos()) + len(claude_bridge.aprovacoes())
                if pend or self.aprovacao_pendente:
                    partes.append(f"APROVAÇÕES PENDENTES {pend + (1 if self.aprovacao_pendente else 0)}")
            except Exception:
                pass
            return "  ·  ".join(partes)

        def ler_atividade(self):
            """Últimos eventos do barramento; uma falha acende o estado de ERRO do núcleo."""
            if not self.isVisible():
                return
            try:
                op = self._operacao()
                if self.lbl_op.text() != op:
                    self.lbl_op.setText(op)
            except Exception:
                pass
            from core import eventos
            try:
                inicial = self._ev_seq is None
                if inicial:
                    ult = eventos.consultar(limite=8)
                    self._ev_seq = max([e["seq"] for e in ult] or [0])
                    novos = list(reversed(ult))
                else:
                    novos = eventos.consultar(apos=self._ev_seq, limite=50)
            except Exception:
                return
            if not novos:
                if not self.lst_ativ.count():
                    vazio = QLabel("nenhuma atividade registrada ainda")
                    vazio.setStyleSheet("font-family:'FiraCode Nerd Font'; font-size:9px; color:#6A5A5E; background:transparent;")
                    vazio.setObjectName("ativ_vazio")
                    self.lst_ativ.addWidget(vazio)
                return
            for i in reversed(range(self.lst_ativ.count())):      # some o aviso de vazio
                w = self.lst_ativ.itemAt(i).widget()
                if w and w.objectName() == "ativ_vazio":
                    self.lst_ativ.takeAt(i)
                    w.deleteLater()
            self._ev_seq = max(self._ev_seq, *(e["seq"] for e in novos))
            if not inicial and any(e["tipo"] in ("tool.failed", "task.failed") for e in novos[-10:]) and len(novos) < 50:
                self.reator.marcar_erro()
            if not inicial and hasattr(self.reator, "evento_ferramenta"):
                for e in novos:                                   # atividade real das ferramentas no anel externo
                    if e["tipo"].startswith("tool."):
                        self.reator.evento_ferramenta(e["dados"].get("ferramenta"), e["tipo"])
            cores = {"tool": "#E8DDE0", "task": "#FFB36A", "approval": "#AEB6C2", "memory": "#AEB6C2",
                     "module": "#8A7A7E", "audit": "#8A7A7E"}
            for e in novos[-8:]:
                d = e["dados"]
                o_que = d.get("ferramenta") or d.get("objetivo") or d.get("pedido") or d.get("descricao") \
                    or d.get("mudanca") or d.get("nota") or ""
                falha = e["tipo"].endswith("failed") or e["tipo"].endswith("denied")
                l = QLabel(f"{e['quando'][11:19]}  {e['tipo']:<17} {str(o_que)[:34]}")
                l.setStyleSheet(f"font-family:'FiraCode Nerd Font'; font-size:9px; background:transparent; color:"
                                f"{'#FF4655' if falha else cores.get(e['tipo'].split('.')[0], '#C8B8BC')};")
                self.lst_ativ.insertWidget(0, l)
            while self.lst_ativ.count() > 12:
                w = self.lst_ativ.takeAt(self.lst_ativ.count() - 1).widget()
                if w:
                    w.deleteLater()

        def ler_telemetria(self):
            d = self.telemetria.ler()
            self.reator.cpu, self.reator.ram, self.reator.ram_txt = d["cpu"], d["ram"], d["ram_txt"]
            self.med["cpu"].definir(d["cpu"])
            self.med["ram"].definir(d["ram"])
            self.med["disco"].definir(d["disco"])
            self.med["bateria"].definir(d["bateria"], None if d["bateria"] is None else f"{d['bateria']}%")
            self.med["temp"].definir(d["temp"], "--" if d["temp"] is None else f"{d['temp']:.0f}°")
            self.med["carga"].definir(min(100, 100 * d["carga"] / d["nucleos"]), f"{d['carga']:.1f}")
            self.lbl_rede.setText(f"REDE  ↓ {taxa(d['rx'])}   ↑ {taxa(d['tx'])}")
            h, m = divmod(int(d["ligado"]) // 60, 60)
            estado_bat = {"Charging": "carregando", "Discharging": "na bateria", "Full": "cheia",
                          "Not charging": "na tomada"}.get(
                d.get("bateria_estado"), d.get("bateria_estado") or "")
            self.lbl_ligado.setText(f"LIGADO {h}h{m:02d}   ·   {estado_bat.upper()}")
            self.lbl_ligado.setToolTip(f"RAM {d['ram_txt']}")
            agora = datetime.now()
            dias = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]
            self.lbl_hora.setText(agora.strftime("%H:%M:%S"))
            self.lbl_data.setText(f"{dias[agora.weekday()]} · {agora:%d.%m.%Y}")

        # ----- painéis
        def _caixa(self, titulo, destaque=None):
            """Seção leve (sem moldura própria): vive dentro dos painéis de vidro."""
            f = QWidget()
            v = QVBoxLayout(f)
            v.setContentsMargins(0, 6, 0, 0)
            v.setSpacing(6)
            v.addWidget(hud.rotulo_hud(titulo.upper(), 8, "#C8707E", 2))
            f.corpo = v
            return f, v

        def _dispor(self):
            """Posiciona os painéis sobre o palco. Colunas laterais proporcionais à largura;
            o espaço do meio é da esfera (o palco recebe esse retângulo)."""
            if not hasattr(self, "p_voz"):
                return
            W, H = self.palco.width(), self.palco.height()
            m, topo = 16, 64
            col = int(max(290, min(440, W * 0.25)))
            self.barra.setGeometry(m, 10, W - 2 * m, 44)
            esq = self.p_status.isVisible()
            dir_ = self.p_dados.isVisible()
            # esquerda: status em cima (se visível), canal embaixo
            alt_status = min(self.p_status.minimumSizeHint().height() + 6, int((H - topo - m) * 0.58)) if esq else 0
            self.p_status.setGeometry(m, topo, col, alt_status)
            y_canal = topo + (alt_status + 12 if esq else 0)
            self.p_canal.setGeometry(m, y_canal, col, H - y_canal - m)
            # direita: centro de dados e voz
            alt_voz = 190
            x_dir = W - m - col
            self.p_dados.setGeometry(x_dir, topo, col, H - topo - m - alt_voz - 12)
            self.p_voz.setGeometry(x_dir, H - m - alt_voz, col, alt_voz)
            # meio: a esfera e o texto de estado embaixo dela
            x0 = m + col + 12
            x1 = (x_dir - 12) if dir_ else (W - m)
            self.reator.area = QRectF(x0, topo, x1 - x0, H - topo - 110)
            self.reator._cache.clear()
            cx, cy, R = self.reator._geo()
            larg = int(min(x1 - x0, 620))
            self.centro_txt.setGeometry(int(cx - larg / 2), int(min(H - 110, cy + R * 1.45)), larg, 96)
            self.palco.update(self.palco.rect())

        def _painel_maquinas(self):
            f, v = self._caixa("máquinas")
            self.maquinas = {}
            for id_, h in (ajuste("hosts", {}) or {}).items():
                linha = QHBoxLayout()
                ponto = QLabel("◆")
                ponto.setObjectName("ponto_off")
                nome = QLabel(id_.upper())
                nome.setObjectName("maq")
                nome.setToolTip("esta máquina" if h.get("local") else h.get("endereco", ""))
                linha.addWidget(ponto)
                linha.addWidget(nome, 1)
                if not h.get("local") and h.get("mac"):
                    bt = QPushButton("\U000f0425 LIGAR")
                    bt.clicked.connect(lambda _=False, i=id_: self.acao_direta(
                        f"ligando o {i}", lambda: __import__("ferramentas.modos", fromlist=["x"]).ligar_e_esperar(i)))
                    linha.addWidget(bt)
                v.addLayout(linha)
                self.maquinas[id_] = (ponto, h)
            return f

        def _painel_modos(self):
            f, v = self._caixa("protocolos")
            grade = QGridLayout()
            grade.setSpacing(6)
            for i, nome in enumerate((ajuste("modos", {}) or {}).keys()):
                bt = QPushButton(f"{ICONES.get(nome, chr(0xF0E7))}  {nome.upper()}")
                bt.setObjectName("modo")
                bt.clicked.connect(lambda _=False, n=nome: self.ativar_modo(n))
                grade.addWidget(bt, i // 2, i % 2)
            v.addLayout(grade)
            return f

        def _painel_midia(self):
            f, v = self._caixa("mídia", hud.CIANO)
            self.lbl_midia = QLabel("carregando…")
            self.lbl_midia.setObjectName("dado")
            self.lbl_midia.setWordWrap(True)
            v.addWidget(self.lbl_midia)
            linha = QHBoxLayout()
            for icone, acao in (("\U000f04ae", "anterior"), ("\U000f040e", "alternar"), ("\U000f04ad", "proxima")):
                bt = QPushButton(icone)
                bt.setObjectName("icone")
                bt.clicked.connect(lambda _=False, a=acao: self.acao_direta(
                    None, lambda: __import__("ferramentas.midia", fromlist=["x"]).midia(a), atualizar=True))
                linha.addWidget(bt)
            v.addLayout(linha)
            return f

        def _painel_hoje(self):
            f, v = self._caixa("ambiente e agenda")
            self.lbl_clima = QLabel("carregando…")
            self.lbl_clima.setObjectName("dado")
            self.lbl_clima.setWordWrap(True)
            self.lbl_agenda = QLabel("carregando…")
            self.lbl_agenda.setObjectName("dado")
            self.lbl_agenda.setWordWrap(True)
            self.lbl_agenda.setAlignment(Qt.AlignTop)
            v.addWidget(self.lbl_clima)
            v.addWidget(self.lbl_agenda, 1)
            return f

        def _painel_evolucao(self):
            f, v = self._caixa("evolução")
            self.lbl_evo = QLabel("carregando…")
            self.lbl_evo.setObjectName("dado")
            self.lbl_evo.setWordWrap(True)
            v.addWidget(self.lbl_evo)
            bt = QPushButton("\U000f0e2a  EVOLUTION CENTER")
            bt.clicked.connect(self.abrir_centro)
            v.addWidget(bt)
            bt_nl = QPushButton("\U000f09d6  NEURALINK")
            bt_nl.setToolTip("Grafo de conhecimento, busca, memória e fontes")
            bt_nl.clicked.connect(self.abrir_neuralink)
            v.addWidget(bt_nl)
            bt_mod = QPushButton("\U000f0565  MÓDULOS")
            bt_mod.setToolTip("Guardian (permissões), Chronos (linha do tempo) e eventos ao vivo")
            bt_mod.clicked.connect(lambda: self.abrir_janela("--modulos"))
            v.addWidget(bt_mod)
            return f

        # ----- conversa
        def adicionar(self, quem, texto):
            if quem in ("eu", "ultron"):
                self._falas_ambiente.append((time.time(), f"{'Ultron' if quem == 'ultron' else 'Você'}: {texto}"))
                self._falas_ambiente = self._falas_ambiente[-6:]
            hora = datetime.now().strftime("%H:%M:%S")
            if quem == "acao":
                l = QLabel(f"{hora}  ▸ {texto.upper()}")
                l.setObjectName("acao")
            elif quem == "info":     # detalhes pedidos pelo núcleo (não é fala do Ultron)
                l = QLabel(f"{hora}  ▸ {texto}")
                l.setStyleSheet("font-family:'FiraCode Nerd Font'; font-size:8pt; color:#FFA834;"
                                "background:transparent;")
                l.setWordWrap(True)
                l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            else:
                from html import escape
                rot, c = ("VOCÊ", CIANO) if quem == "eu" else ("ULTRON", VERMELHO)
                l = QLabel(f"<span style=\"font-family:'FiraCode Nerd Font'; font-size:9pt; color:{c};"
                           f" letter-spacing:2px\">{hora} · {rot}</span><br>{escape(texto)}")
                l.setObjectName("log_eu" if quem == "eu" else "log_ultron")
                l.setTextFormat(Qt.RichText)
                l.setWordWrap(True)
                l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.vl.insertWidget(self.vl.count() - 1, l)
            QTimer.singleShot(30, lambda: self.rolagem.verticalScrollBar().setValue(
                self.rolagem.verticalScrollBar().maximum()))

        def limpar(self):
            while self.vl.count() > 1:
                w = self.vl.takeAt(0).widget()
                if w:
                    w.deleteLater()

        def enviar(self):
            texto = self.campo.text().strip()
            if not texto:
                return
            self.campo.clear()
            pedidos.put(("texto", texto))

        def ocupado(self, sim):
            self.bt_mic.setEnabled(not sim and not estado_voz["continua"])

        def alternar_continua(self, ligado):
            estado_voz["continua"] = ligado
            self.bt_mic.setEnabled(not ligado)
            if ligado:
                anterior = estado_voz.get("thread_escuta")
                if anterior is None or not anterior.is_alive():
                    thread = threading.Thread(target=escuta_continua, daemon=True, name="escuta")
                    estado_voz["thread_escuta"] = thread
                    thread.start()

        # ----- animação (60 fps) e rótulo de estado
        def quadro(self):
            if self.isMinimized() or not self.isVisible():
                return
            est = "aguardando aprovação" if self.aprovacao_pendente else animacao.atual()
            n = animacao.niveis().get(est, 0.0) if est in ("ouvindo", "falando") else (
                0.0)
            self.reator.passo(est, n)
            active = est not in aura.OCIOSOS
            if active and self.inicio_acao is None:
                self.inicio_acao = time.monotonic()
            elif not active:
                self.inicio_acao = None
            elapsed = f" · {int(time.monotonic() - self.inicio_acao)}s" if self.inicio_acao else ""
            usado = getattr(cerebro, "modelo_usado", None)      # registrado pelo Hive Mind a cada resposta
            if usado:
                esf = getattr(cerebro, "_esforco_turno", None)
                status = f"RESPONDEU · {usado}" + (f" · esforço {esf}" if esf else "") + elapsed
            else:
                model = getattr(cerebro, "modelo", None) or (getattr(cerebro, "modelos", []) or ["não informado"])[0]
                status = f"CONFIGURADO · {ajuste('ia.provedor', 'claude').upper()} / {model}{elapsed}"
            if self.lbl_exec.text() != status:
                self.lbl_exec.setText(status)
            label = "ERRO NA ÚLTIMA AÇÃO" if self.reator.em_erro() else ROTULO_ESTADO.get(est, est).upper()
            if self.lbl_estado.text() != label:
                self.lbl_estado.setText(label)
            for m in self.med.values():
                m.passo()
            self.espectro.passo()
            if est != self.ultimo_estado:
                self.ultimo_estado = est
                if est and est not in aura.OCIOSOS and est not in ("ouvindo", "falando", "pensando",
                                                                  "preparando o briefing"):
                    self.adicionar("acao", est)

        # ----- confirmações N2/N3
        def perguntar(self, acao, nivel):
            if self.isMinimized():
                self.showNormal()
                self.raise_()
                self.activateWindow()
            self.aprovacao_pendente = True
            caixa = QMessageBox(self)
            caixa.setWindowTitle("Ultron pede confirmação")
            caixa.setText(f"Confirma {acao}?")
            caixa.setInformativeText("Ação crítica: confirma toda vez." if nivel == "N3"
                                     else "Ação sensível. 'Sempre' deixa de perguntar.")
            sim = caixa.addButton("Sim", QMessageBox.AcceptRole)
            sempre = caixa.addButton("Sempre", QMessageBox.ActionRole) if nivel != "N3" else None
            caixa.addButton("Não", QMessageBox.RejectRole)
            try:
                caixa.exec()
            finally:
                self.aprovacao_pendente = False
            clicado = caixa.clickedButton()
            resposta_conf["valor"] = "sim" if clicado == sim else "sempre" if clicado == sempre else "nao"
            resposta_conf["evento"].set()

        # ----- ações diretas (sem passar pelo modelo)
        def acao_direta(self, aviso, fn, atualizar=False):
            def job():
                if aviso:
                    animacao.iniciar(aviso)
                try:
                    r = fn()
                    if aviso:
                        ponte.mensagem.emit("acao", str(r).replace("[CONTEUDO EXTERNO NAO CONFIAVEL]\n", ""))
                finally:
                    if aviso:
                        animacao.parar()
                if atualizar:
                    self.coletar_paineis(uma_vez=True)
            pedidos.put(("funcao", job))

        def ativar_modo(self, nome):
            from core import registro
            f = registro.obter("ativar_modo")
            args = {"nome": nome}
            if registro.precisa_confirmar(f, args):
                if QMessageBox.question(self, "Ultron", f"Confirma {registro.descrever(f, args)}?") != QMessageBox.Yes:
                    return
            self.acao_direta(f"ativando o modo {nome}", lambda: f.funcao(**args))

        def alternar_ambiente(self, ativo):
            if ativo:
                if self.ambiente is None:
                    from core import ambiente
                    self.ambiente = ambiente.rodar(falas=lambda: self._falas_ambiente)
                self._escuta_antes_ambiente = self.ch_continua.isChecked()
                self.ch_continua.setChecked(True)
                self.ambiente.ultimo_ativo = time.time()
                self.ambiente.timer.start(33)
                self.ambiente._passo()
                self.showMinimized()
            elif self.ambiente is not None:
                self.ambiente.timer.stop()
                self.ambiente.hide()
                self.ch_continua.setChecked(self._escuta_antes_ambiente)

        def abrir_terminal(self):
            import shutil
            terminal = shutil.which("konsole")
            if terminal:
                subprocess.Popen([terminal, "--workdir", str(RAIZ), "-e", str(RAIZ / "ultron"), "--texto"],
                                 start_new_session=True)
            else:
                QMessageBox.information(self, "Terminal", "Execute ultron --texto no seu terminal.")

        def abrir_neuralink(self):
            self.abrir_janela("--neuralink")

        def abrir_janela(self, opcao):
            """Abre outra janela do Ultron já autenticada (a senha foi pedida aqui)."""
            import os
            import sys
            subprocess.Popen([sys.executable, str(RAIZ / "ultron.py"), opcao], cwd=RAIZ,
                             start_new_session=True, env=os.environ | {"ULTRON_AUTENTICADO": "1"})

        def abrir_centro(self):
            import subprocess
            import sys
            subprocess.Popen([sys.executable, str(RAIZ / "ultron.py"), "--evolucao", "centro"],
                             cwd=RAIZ, start_new_session=True)

        # ----- núcleo: carga do desktop e cliques nos anéis
        def coletar_desktop(self):
            """Lê a carga real do desktop a cada 6 s enquanto a janela está visível."""
            from ferramentas.computacao import carga_desktop
            while True:
                if self.isVisible() and not self.isMinimized():
                    try:
                        self.reator.desktop = carga_desktop()
                    except Exception:
                        self.reator.desktop = None
                time.sleep(6)

        def clicar_nucleo(self, zona):
            if zona == "nucleo":
                if self.bt_mic.isEnabled():
                    pedidos.put(("ouvir", None))
                else:
                    self.adicionar("info", "microfone ocupado (escuta contínua ligada ou resposta em andamento)")
                return

            def job():
                try:
                    if zona.startswith("nb_"):
                        campo = "-%cpu" if zona == "nb_cpu" else "-rss"
                        r = subprocess.run(["ps", "-eo", "pid,%cpu,rss,comm", f"--sort={campo}"],
                                           capture_output=True, text=True, timeout=5).stdout.splitlines()
                        linhas = [f"{l.split()[3][:22]:22} CPU {float(l.split()[1]):5.1f}%  "
                                  f"RAM {int(l.split()[2]) / 1024:6.0f} MB" for l in r[1:7]]
                        titulo = "notebook: processos que mais usam " + ("CPU" if zona == "nb_cpu" else "RAM")
                        texto = titulo + "\n" + "\n".join(linhas)
                    else:
                        from ferramentas.computacao import recursos_maquinas, status_tarefa_desktop
                        texto = recursos_maquinas() + "\n" + status_tarefa_desktop()
                except Exception as e:
                    texto = f"não consegui ler os detalhes: {e}"
                ponte.mensagem.emit("info", texto.replace("[CONTEUDO EXTERNO NAO CONFIAVEL]\n", ""))
            self.adicionar("info", "lendo " + {"nb_cpu": "CPU do notebook", "nb_ram": "RAM do notebook"}
                           .get(zona, "carga do desktop") + "...")
            threading.Thread(target=job, daemon=True).start()

        # ----- dados dos painéis (thread)
        def coletar_paineis(self, uma_vez=False):
            clima, t_clima = "", 0
            while True:
                d = {"maquinas": {}}
                for id_, (_, h) in self.maquinas.items():
                    d["maquinas"][id_] = True if h.get("local") else _no_ar(h.get("endereco", ""), h.get("porta", 22))
                try:
                    from ferramentas.midia import midia
                    d["midia"] = midia("status").replace("[CONTEUDO EXTERNO NAO CONFIAVEL]\n", "")
                except Exception as e:
                    d["midia"] = str(e)[:80]
                try:
                    from core import agenda
                    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    itens = agenda.do_periodo(hoje, hoje + timedelta(days=1))
                    d["agenda"] = "\n".join(f"{x['quando'][11:]}  {x['titulo']}" for x in itens) or "Nada marcado hoje."
                except Exception:
                    d["agenda"] = "—"
                if time.time() - t_clima > 1800:
                    try:
                        from ferramentas.utilidades import clima as f_clima
                        clima, t_clima = f_clima(), time.time()
                    except Exception:
                        pass
                d["clima"] = clima
                try:
                    from evolucao import aprovacao, descoberta
                    d["evo"] = (len(aprovacao.pendentes()),
                                sum(n["estado"] == "aberta" for n in descoberta.necessidades()))
                except Exception:
                    d["evo"] = (0, 0)
                ponte.painel.emit(d)
                if uma_vez:
                    return
                time.sleep(15)

        def atualizar_paineis(self, d):
            for id_, on in d["maquinas"].items():
                ponto = self.maquinas[id_][0]
                ponto.setText("◆")
                ponto.setObjectName("ponto_on" if on else "ponto_off")
                ponto.setStyle(ponto.style())
                ponto.setToolTip("ligado" if on else "desligado")
            texto_midia = re.sub(r"^\w+: ", "", d.get("midia", "—").splitlines()[0] if d.get("midia") else "—")
            self.lbl_midia.setText(texto_midia[:120])
            self.lbl_agenda.setText(d.get("agenda", "—"))
            self.lbl_clima.setText(d.get("clima") or "—")
            pend, nec = d.get("evo", (0, 0))
            self.lbl_evo.setText(f"{pend} aguardando sua aprovação · {nec} necessidades abertas")
            on = sum(d["maquinas"].values())
            self.lbl_sistema.setText(f"  {on}/{len(d['maquinas'])} MÁQUINAS  ·  "
                                     f"OPERADOR: {ajuste('usuario.nome', 'Davi').upper()}"
                                     + (f"  ·  {pend} APROVAÇÕES PENDENTES" if pend else ""))

        def resizeEvent(self, ev):
            super().resizeEvent(ev)
            if hasattr(self, "lbl_data"):
                self.lbl_data.setVisible(self.width() >= 1250)
                self.lbl_sistema.setVisible(self.width() >= 1500)
                estreita = self.width() < 1250
                self.marca.setText("ULTRON" if estreita else "U L T R O N")
                self.bt_ambiente.setText("CANTO" if estreita else "MODO DE CANTO")
                if not getattr(self, "_disposto_auto", False) or (self.width() < 1100) != self._estreito:
                    # janela estreita: os painéis da direita recolhem (botão DADOS traz de volta)
                    self._estreito = self.width() < 1100
                    self._disposto_auto = True
                    self.bt_contexto.setChecked(not self._estreito)
                self._dispor()

        def closeEvent(self, ev):
            estado_voz["continua"] = False
            if self.ambiente is not None:
                self.ambiente.timer.stop()
                self.ambiente.close()
            ev.accept()

    # ------------------------------------------------------------ senha e abertura
    if not _login(app):
        return 1
    janela = Janela()
    janela.show()
    janela.adicionar("ultron", "Sistemas online. Digite um comando ou use a interface de voz. "
                               "O terminal continua à disposição, se preferir o clássico.")
    from core import agenda, briefing
    agenda.iniciar_agendador()
    if briefing.pendente():
        pedidos.put(("briefing", None))
    return app.exec()


def _login(app):
    """Capa do Ultron Painel com a senha de abertura (a mesma do terminal)."""
    from interface.capa import entrar
    return entrar(app)
