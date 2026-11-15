"""Janela de módulos do Ultron: GUARDIAN, CHRONOS e EVENTOS (e os próximos módulos).

Guardian: as decisões de permissão são do Davi e só acontecem aqui (ou na CLI):
criar/revogar políticas, liberar diretórios, responder pedidos do Ultron, revogar
autorizações "sempre" e ver incidentes.
Chronos: linha do tempo de tudo o que foi registrado e comparação entre períodos.
Eventos: o barramento ao vivo (task.*, tool.*, approval.*...), lido do banco a cada
segundo; clicar num evento mostra a operação inteira (mesma correlação).
"""
import json
import os
import sys

from core.config import RAIZ

FONTE = "FiraCode Nerd Font"
from interface.design import STYLE as ESTILO

COR_TIPO = {"task": "#ffd28a", "tool": "#ff6a74", "approval": "#9dffb4", "memory": "#8ab4ff",
            "module": "#c9a0ff", "audit": "#ffffff"}


def abrir(executar=True):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QColor, QIcon
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                                   QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                                   QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                   QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                   QTabWidget, QTextEdit, QVBoxLayout, QWidget)

    from core import chronos, eventos, guardian, registro
    from interface import hud

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(ESTILO)
    app.setWindowIcon(QIcon(str(RAIZ / "icone.png")))
    if not os.environ.get("ULTRON_AUTENTICADO"):      # permissões são sensíveis: pede a senha
        from interface.app import _login
        if not _login(app):
            return 1
    if not registro.todas():
        registro.carregar()

    def tabela(colunas, estica=0):
        t = QTableWidget(0, len(colunas))
        t.setHorizontalHeaderLabels(colunas)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(estica, QHeaderView.Stretch)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        return t

    def preencher(t, linhas):
        t.setRowCount(len(linhas))
        for r, linha in enumerate(linhas):
            for c, v in enumerate(linha):
                t.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))

    def botao(rot, fn, nome=""):
        b = QPushButton(rot)
        b.setObjectName(nome)
        b.clicked.connect(fn)
        return b

    class Janela(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron · Módulos")
            self.resize(1380, 860)
            fundo = hud.Fundo()
            self.setCentralWidget(fundo)
            v = QVBoxLayout(fundo)
            v.setContentsMargins(16, 12, 16, 12)
            cab = QHBoxLayout()
            cab.addWidget(hud.rotulo_hud("U L T R O N", 17, "#FF2A3A", 4))
            cab.addWidget(hud.rotulo_hud("  ·  MÓDULOS", 11, "#b8aeb0", 3))
            cab.addStretch()
            self.lbl = hud.rotulo_hud("", 9, "#9a8a8e", 2)
            cab.addWidget(self.lbl)
            v.addLayout(cab)
            self.abas = QTabWidget()
            self.abas.addTab(self._guardian(), "GUARDIAN")
            self.abas.addTab(self._chronos(), "CHRONOS")
            self.abas.addTab(self._eventos(), "EVENTOS")
            # abas dos módulos das fases seguintes (interface/abas_*.py)
            import importlib
            import pkgutil
            import interface
            for m in sorted(x.name for x in pkgutil.iter_modules(interface.__path__) if x.name.startswith("abas_")):
                try:
                    for nome, w in importlib.import_module(f"interface.{m}").criar(self):
                        self.abas.addTab(w, nome)
                except Exception as e:
                    erro = QLabel(f"A aba {m} não carregou: {e}")
                    erro.setStyleSheet("color:#ff6a74;")
                    self.abas.addTab(erro, m[5:].upper() + " (ERRO)")
            from interface.design import navigation
            navigation(v, self.abas)
            self.ultimo = 0
            self.t = QTimer(self)
            self.t.timeout.connect(self.ao_vivo)
            self.t.start(1000)
            self.carregar_guardian()
            self.carregar_tempo()
            self.ao_vivo(inicial=True)

        # ================================================= GUARDIAN
        def _guardian(self):
            w = QWidget()
            v = QVBoxLayout(w)
            aviso = QLabel("O Guardian decide antes de qualquer ferramenta rodar. Ações críticas (N3) pedem "
                           "confirmação sempre; nenhuma política afrouxa isso. O Ultron só pode PEDIR "
                           "permissões: quem concede é você, aqui.")
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color:#bfb3b6;")
            v.addWidget(aviso)
            div = QSplitter(Qt.Horizontal)
            esq = hud.Moldura("políticas")
            self.g_mostrar_rev = QCheckBox("mostrar revogadas")
            self.g_mostrar_rev.toggled.connect(self.carregar_guardian)
            esq.corpo.addWidget(self.g_mostrar_rev)
            self.g_pol = tabela(["#", "Workspace", "Ação", "Alvo", "Decisão", "Motivo", "Por", "Desde", "Revogada"], 3)
            esq.corpo.addWidget(self.g_pol, 1)
            b = QHBoxLayout()
            b.addWidget(botao("NOVA POLÍTICA", self.nova_politica))
            b.addWidget(botao("REVOGAR", self.revogar, "perigo"))
            b.addStretch()
            esq.corpo.addLayout(b)
            m = hud.Moldura("autorizações 'sempre'")
            self.g_sempre = QListWidget()
            m.corpo.addWidget(self.g_sempre)
            m.corpo.addWidget(botao("REVOGAR 'SEMPRE'", self.revogar_sempre, "perigo"))
            esq.corpo.addWidget(m)
            div.addWidget(esq)
            dir_ = QWidget()
            vd = QVBoxLayout(dir_)
            vd.setContentsMargins(0, 0, 0, 0)
            m = hud.Moldura("pedidos do ultron")
            self.g_ped = QListWidget()
            self.g_ped.setWordWrap(True)
            m.corpo.addWidget(self.g_ped)
            b = QHBoxLayout()
            b.addWidget(botao("CONCEDER", lambda: self.responder(True), "ok"))
            b.addWidget(botao("NEGAR", lambda: self.responder(False), "perigo"))
            m.corpo.addLayout(b)
            vd.addWidget(m, 2)
            m = hud.Moldura("diretórios autorizados")
            self.g_dirs = QListWidget()
            m.corpo.addWidget(self.g_dirs)
            m.corpo.addWidget(botao("+ DIRETÓRIO", self.add_dir))
            vd.addWidget(m, 2)
            m = hud.Moldura("incidentes")
            self.g_inc = QListWidget()
            self.g_inc.setWordWrap(True)
            m.corpo.addWidget(self.g_inc)
            vd.addWidget(m, 2)
            div.addWidget(dir_)
            div.setSizes([820, 480])
            v.addWidget(div, 1)
            return w

        def carregar_guardian(self):
            pols = guardian.politicas(self.g_mostrar_rev.isChecked())
            self._pols = pols
            preencher(self.g_pol, [(p["id"], p["workspace"], p["acao"], p["alvo"], p["decisao"], p["motivo"],
                                    p["por"], p["criado"][:16].replace("T", " "),
                                    (p["revogado"] or "")[:16].replace("T", " ")) for p in pols])
            self.g_sempre.clear()
            self.g_sempre.addItems(guardian.concessoes_sempre() or ["(nenhuma)"])
            self.g_ped.clear()
            self._peds = guardian.pedidos()
            for p in self._peds:
                cham = json.loads(p["chamada"]) if p.get("chamada") else None
                self.g_ped.addItem(f"{p['id']}  {p['acao']} → {p['alvo']}\nmotivo: {p['motivo']}\n"
                                   + (f"ao aprovar, executa: {cham['ferramenta']}({json.dumps(cham['args'], ensure_ascii=False)[:160]})\n"
                                      if cham else "")
                                   + f"{p['criado'][:16].replace('T', ' ')} · workspace {p['workspace']}")
            if not self._peds:
                self.g_ped.addItem("Nenhum pedido pendente.")
            self.g_dirs.clear()
            self.g_dirs.addItems(guardian.diretorios_permitidos())
            self.g_inc.clear()
            for i in guardian.incidentes(60):
                self.g_inc.addItem(f"{i['quando'][:16].replace('T', ' ')}  [{i['severidade']}] {i['tipo']}\n{i['descricao']}")
            if not self.g_inc.count():
                self.g_inc.addItem("Nenhum incidente.")

        def nova_politica(self):
            dlg = QDialog(self)
            dlg.setWindowTitle("Nova política")
            f = QFormLayout(dlg)
            acao = QComboBox()
            acao.addItems(list(guardian.ACOES) + ["diretorio"])
            alvo = QComboBox()
            alvo.setEditable(True)
            alvo.addItems(["*"] + sorted(x.nome for x in registro.todas()))
            dec = QComboBox()
            dec.addItems(["negar", "perguntar", "permitir"])
            ws = QComboBox()
            ws.setEditable(True)
            ws.addItems(["*"])
            motivo = QLineEdit()
            for rot, x in (("Ação", acao), ("Alvo", alvo), ("Decisão", dec), ("Workspace", ws), ("Motivo", motivo)):
                f.addRow(rot, x)
            bts = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            bts.accepted.connect(dlg.accept)
            bts.rejected.connect(dlg.reject)
            f.addRow(bts)
            if dlg.exec() == QDialog.Accepted:
                try:
                    guardian.definir_politica(acao.currentText(), alvo.currentText().strip() or "*",
                                              dec.currentText(), ws.currentText().strip() or "*",
                                              motivo.text().strip(), por="Davi (painel)")
                except Exception as e:
                    QMessageBox.warning(self, "Guardian", str(e))
                self.carregar_guardian()

        def revogar(self):
            r = self.g_pol.currentRow()
            if 0 <= r < len(self._pols) and not self._pols[r]["revogado"]:
                guardian.revogar(self._pols[r]["id"], por="Davi (painel)")
                self.carregar_guardian()

        def revogar_sempre(self):
            it = self.g_sempre.currentItem()
            if it and it.text() != "(nenhuma)":
                guardian.revogar_sempre(it.text(), por="Davi (painel)")
                self.carregar_guardian()

        def responder(self, conceder):
            r = self.g_ped.currentRow()
            if 0 <= r < len(self._peds):
                guardian.responder_pedido(self._peds[r]["id"], conceder, por="Davi (painel)")
                self.carregar_guardian()

        def add_dir(self):
            d = QFileDialog.getExistingDirectory(self, "Diretório autorizado", os.path.expanduser("~"))
            if d:
                try:
                    guardian.definir_politica("diretorio", d, "permitir", motivo="liberado no painel", por="Davi (painel)")
                except Exception as e:
                    QMessageBox.warning(self, "Guardian", str(e))
                self.carregar_guardian()

        # ================================================= CHRONOS
        def _chronos(self):
            w = QWidget()
            v = QVBoxLayout(w)
            f = QHBoxLayout()
            self.c_per = QComboBox()
            self.c_per.setEditable(True)
            self.c_per.addItems(["hoje", "ontem", "esta semana", "semana passada", "últimos 7 dias", "este mês",
                                 "mês passado"])
            self.c_txt = QLineEdit()
            self.c_txt.setPlaceholderText("filtrar por palavra...")
            f.addWidget(QLabel("período"))
            f.addWidget(self.c_per)
            f.addWidget(self.c_txt, 1)
            self.c_fontes = {}
            for fonte in ("conversa", "eventos", "neuralink", "agenda", "evolucao", "desktop"):
                ch = QCheckBox(fonte)
                ch.setChecked(True)
                f.addWidget(ch)
                self.c_fontes[fonte] = ch
            f.addWidget(botao("VER", self.carregar_tempo))
            v.addLayout(f)
            div = QSplitter(Qt.Horizontal)
            self.c_lista = QListWidget()
            self.c_lista.setWordWrap(True)
            div.addWidget(self.c_lista)
            m = hud.Moldura("o que mudou")
            g = QHBoxLayout()
            self.c_a, self.c_b = QComboBox(), QComboBox()
            for cb, padrao in ((self.c_a, "esta semana"), (self.c_b, "semana passada")):
                cb.setEditable(True)
                cb.addItems(["hoje", "ontem", "esta semana", "semana passada", "este mês", "mês passado"])
                cb.setCurrentText(padrao)
                g.addWidget(cb)
            g.addWidget(botao("COMPARAR", self.comparar))
            m.corpo.addLayout(g)
            self.c_comp = QTextEdit()
            self.c_comp.setReadOnly(True)
            m.corpo.addWidget(self.c_comp, 1)
            div.addWidget(m)
            div.setSizes([820, 480])
            v.addWidget(div, 1)
            self.c_per.currentIndexChanged.connect(self.carregar_tempo)
            self.c_txt.returnPressed.connect(self.carregar_tempo)
            return w

        def carregar_tempo(self):
            try:
                ini, fim = chronos.periodo(self.c_per.currentText())
            except ValueError as e:
                self.c_lista.clear()
                self.c_lista.addItem(str(e))
                return
            fontes = [k for k, ch in self.c_fontes.items() if ch.isChecked()]
            itens = chronos.atividades(ini, fim, fontes=fontes, texto=self.c_txt.text().strip() or None)
            self.c_lista.clear()
            for i in itens:
                it = QListWidgetItem(f"{i['quando'][:16].replace('T', ' ')}   {i['fonte'].upper()} · {i['tipo']}"
                                     + (f"  ·  {i['projeto']}" if i["projeto"] else "") + f"\n{i['titulo']}"
                                     + (f"\n{i['detalhe']}" if i["detalhe"] else ""))
                it.setData(Qt.UserRole, i["correlacao"])
                self.c_lista.addItem(it)
            if not itens:
                self.c_lista.addItem(f"Nada registrado entre {ini[:16]} e {fim[:16]}.")

        def comparar(self):
            try:
                c = chronos.comparar(self.c_a.currentText(), self.c_b.currentText())
            except ValueError as e:
                self.c_comp.setPlainText(str(e))
                return
            a, b = c["a"], c["b"]
            linhas = [f"{self.c_a.currentText()}: {a['total']} registros, {a['falhas']} falhas",
                      f"{self.c_b.currentText()}: {b['total']} registros, {b['falhas']} falhas", ""]
            for t, (x, y) in sorted(c["diferenca"].items(), key=lambda kv: -abs(kv[1][0] - kv[1][1])):
                linhas.append(f"{t:28} {x:5}  →  {y:5}")
            if a["ferramentas"]:
                linhas += ["", "ferramentas mais usadas (" + self.c_a.currentText() + "):"]
                linhas += [f"  {k}: {n}" for k, n in a["ferramentas"].items()]
            self.c_comp.setPlainText("\n".join(linhas))

        # ================================================= EVENTOS
        def _eventos(self):
            w = QWidget()
            v = QVBoxLayout(w)
            f = QHBoxLayout()
            self.e_tipo = QComboBox()
            self.e_tipo.addItems(["todos", "task.*", "tool.*", "approval.*", "memory.*", "module.*", "audit.*"])
            self.e_pausa = QCheckBox("pausar")
            f.addWidget(QLabel("tipo"))
            f.addWidget(self.e_tipo)
            f.addWidget(self.e_pausa)
            f.addStretch()
            self.e_info = QLabel("")
            f.addWidget(self.e_info)
            v.addLayout(f)
            div = QSplitter(Qt.Horizontal)
            self.e_lista = QListWidget()
            self.e_lista.itemClicked.connect(self.operacao)
            div.addWidget(self.e_lista)
            m = hud.Moldura("operação (mesma correlação)")
            self.e_det = QTextEdit()
            self.e_det.setReadOnly(True)
            m.corpo.addWidget(self.e_det)
            div.addWidget(m)
            div.setSizes([760, 540])
            v.addWidget(div, 1)
            self.e_tipo.currentIndexChanged.connect(lambda: self.ao_vivo(inicial=True))
            return w

        def ao_vivo(self, inicial=False):
            if self.e_pausa.isChecked() or (not inicial and not self.isVisible()):
                return
            tipo = None if self.e_tipo.currentText() == "todos" else self.e_tipo.currentText()
            if inicial:
                self.e_lista.clear()
                evs = list(reversed(eventos.consultar(tipo=tipo, limite=300)))
            else:
                evs = eventos.consultar(apos=self.ultimo, tipo=tipo, limite=200)
            for e in evs:
                d = e["dados"]
                resumo = d.get("ferramenta") or d.get("pedido") or d.get("resposta") or d.get("descricao") \
                    or d.get("mudanca") or json.dumps(d, ensure_ascii=False)[:120]
                it = QListWidgetItem(f"{e['quando'][11:19]}  {e['tipo']:<20} {e['origem']:<10} {str(resumo)[:110]}")
                it.setForeground(QColor(COR_TIPO.get(e["tipo"].split(".")[0], "#ddd")))
                it.setData(Qt.UserRole, e)
                self.e_lista.insertItem(0, it)
            if evs:
                self.ultimo = max(self.ultimo, *(e["seq"] for e in evs))
                self.e_lista.scrollToTop()
            while self.e_lista.count() > 1000:
                self.e_lista.takeItem(self.e_lista.count() - 1)
            if inicial and not evs:
                self.ultimo = max([self.ultimo] + [e["seq"] for e in eventos.consultar(limite=1)])
            self.e_info.setText(f"{self.e_lista.count()} eventos na tela · ao vivo")
            if evs and any(e["tipo"].startswith(("approval", "module")) for e in evs):
                self.carregar_guardian()

        def operacao(self, it):
            e = it.data(Qt.UserRole)
            if not e:
                return
            linhas = [json.dumps(e, ensure_ascii=False, indent=1)]
            if e["correlacao"]:
                linhas += ["", f"OPERAÇÃO {e['correlacao']}:"]
                for x in eventos.consultar(correlacao=e["correlacao"], apos=0, limite=200):
                    linhas.append(f"{x['quando'][11:23]}  {x['tipo']:<20} {json.dumps(x['dados'], ensure_ascii=False)[:160]}")
            self.e_det.setPlainText("\n".join(linhas))

    j = Janela()
    j.show()
    if not executar:          # testes: devolve a janela sem entrar no laço de eventos
        return j
    return app.exec()


if __name__ == "__main__":
    sys.exit(abrir())
