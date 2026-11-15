"""Evolution Center: a janela onde o Davi acompanha e decide a evolução do Ultron.

Abas: Capacidades, Sugestões, Skills, Ferramentas, Em desenvolvimento, Testes,
Histórico, Versões e Aprovações (onde fica o único botão que ativa algo).
No topo, a aura do Ultron mostra a etapa atual: roxo pesquisando, laranja
desenvolvendo, amarelo testando, verde concluído.
"""
import json
import math
import time

from evolucao import aprovacao, avaliacao, base, capacidades, descoberta, extensoes, skills

ETAPAS = {"pesquisando": (0x66, 0x00, 0xFF), "desenvolvendo": (0xFF, 0x7A, 0x45),
          "testando": (0xFF, 0xC5, 0x3D), "melhoria concluída": (0x52, 0xC4, 0x1A)}
OCIOSO = (0xF5, 0x22, 0x2D)

from interface.design import STYLE as ESTILO



def abrir():
    from PySide6.QtCore import QPointF, Qt, QTimer
    from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient
    from PySide6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                                   QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                   QTabWidget, QTextEdit, QVBoxLayout, QWidget)

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(ESTILO)
    from PySide6.QtGui import QIcon
    from core.config import RAIZ as _RAIZ
    app.setWindowIcon(QIcon(str(_RAIZ / "icone.png")))

    class Aura(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedSize(70, 70)
            self.t0 = time.time()
            self.cor = OCIOSO

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            t = time.time() - self.t0
            r, g, b = self.cor
            ativo = self.cor != OCIOSO
            for k in range(4):
                raio = 22 + 2 * math.sin(t * (1.2 + k * 0.3) + k) + (3 * math.sin(t * 6) if ativo else 0)
                ox = 35 + 3 * math.cos(t * (0.7 + k * 0.2) + k)
                oy = 35 + 3 * math.sin(t * (0.9 + k * 0.2) + k)
                gr = QRadialGradient(QPointF(ox, oy), raio * 1.4)
                gr.setColorAt(0.0, QColor(r, g, b, 0))
                gr.setColorAt(0.68, QColor(r, g, b, 60))
                gr.setColorAt(0.74, QColor(255, 255, 255, 70))
                gr.setColorAt(0.82, QColor(r, g, b, 50))
                gr.setColorAt(1.0, QColor(r, g, b, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(gr))
                p.drawEllipse(QPointF(ox, oy), raio * 1.4, raio * 1.4)
            p.end()

    def tabela(colunas):
        t = QTableWidget(0, len(colunas))
        t.setHorizontalHeaderLabels(colunas)
        t.horizontalHeader().setStretchLastSection(True)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(False)
        return t

    def preencher(t, linhas):
        sel = t.currentRow()
        t.setRowCount(len(linhas))
        for i, linha in enumerate(linhas):
            for j, v in enumerate(linha):
                item = QTableWidgetItem(str(v))
                if str(v) in ("ok", "aprovado", "APROVADO", "pendente", "ativa"):
                    item.setForeground(QColor("#52c41a") if str(v) != "pendente" else QColor("#ffc53d"))
                elif str(v).startswith(("falta", "falha", "reprov", "REPROV", "desativ", "rejeit")):
                    item.setForeground(QColor("#ff5a64"))
                t.setItem(i, j, item)
        t.resizeColumnsToContents()
        if 0 <= sel < len(linhas):
            t.selectRow(sel)

    class Centro(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ultron · Evolution Forge")
            self.setObjectName("forge")
            self.resize(1180, 720)
            raiz = QVBoxLayout(self)
            topo = QHBoxLayout()
            self.aura = Aura()
            topo.addWidget(self.aura)
            col = QVBoxLayout()
            titulo = QLabel("EVOLUTION FORGE")
            titulo.setObjectName("titulo")
            self.status = QLabel("")
            self.status.setStyleSheet("color:#9a9aa6")
            col.addWidget(titulo)
            col.addWidget(self.status)
            topo.addLayout(col, 1)
            raiz.addLayout(topo)

            self.abas = QTabWidget()

            self.t_cap = tabela(["Tipo", "Nome", "Versão", "Origem", "Permissões", "Status", "Descrição"])
            self.t_nec = tabela(["ID", "Estado", "Vezes", "Necessidade", "Soluções encontradas"])
            self.t_skl = tabela(["Skill", "Versão", "Origem", "Descrição"])
            self.t_fer = tabela(["Ferramenta", "Extensão", "Versão", "Nível", "Rede", "Estado"])
            self.t_dev = tabela(["Candidato", "Avaliação", "Quando", "Motivos"])
            self.t_tst = tabela(["Quando", "Candidato", "Resultado", "Testes", "Antes", "Depois", "Motivos"])
            self.t_his = tabela(["Quando", "Evento", "Nome", "Versão", "Detalhe"])
            self.t_ver = tabela(["Extensão", "Ativa", "Versão atual", "Anterior", "Guardadas", "Nível"])
            self.t_apr = tabela(["ID", "Tipo", "Nome", "Versão", "Permissões", "Criado", "Estado"])

            self.abas.addTab(self.t_cap, "Capacidades")
            self.abas.addTab(self._com_botoes(self.t_nec, [("Investigar", self.investigar)]), "Sugestões")
            self.abas.addTab(self._com_botoes(self.t_skl, [("Remover skill", self.remover_skill, "perigo")]), "Skills")
            self.abas.addTab(self.t_fer, "Ferramentas")
            self.abas.addTab(self.t_dev, "Em desenvolvimento")
            self.abas.addTab(self.t_tst, "Testes e benchmarks")
            self.abas.addTab(self.t_his, "Histórico")
            self.abas.addTab(self._com_botoes(self.t_ver, [
                ("Rollback", self.rollback), ("Desativar", self.desativar, "perigo"),
                ("Reativar", self.reativar)]), "Versões")
            apr = QSplitter(Qt.Vertical)
            apr.addWidget(self._com_botoes(self.t_apr, [
                ("Aprovar (pede confirmação, N2)", lambda: self.aprovar("N2"), "aprovar"),
                ("Aprovar sem confirmação (N1)", lambda: self.aprovar("N1"), "aprovar"),
                ("Aprovar crítico (N3)", lambda: self.aprovar("N3")),
                ("Rejeitar", self.rejeitar, "perigo")]))
            self.relatorio = QTextEdit()
            self.relatorio.setReadOnly(True)
            apr.addWidget(self.relatorio)
            self.abas.addTab(apr, "Aprovações")
            from interface.design import navigation
            navigation(raiz, self.abas)
            self.t_apr.itemSelectionChanged.connect(self.mostrar_relatorio)

            self.atualizar()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.atualizar)
            self.timer.start(4000)
            self.anim = QTimer(self)
            self.anim.timeout.connect(self._etapa)
            from core.config import ajuste
            self.anim.start(1000 if ajuste("visual.movimento_reduzido", False) else 100)

        def _com_botoes(self, tabela_, botoes):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(tabela_)
            h = QHBoxLayout()
            h.addStretch()
            for b in botoes:
                bt = QPushButton(b[0])
                if len(b) > 2:
                    bt.setObjectName(b[2])
                bt.clicked.connect(b[1])
                h.addWidget(bt)
            v.addLayout(h)
            return w

        def _etapa(self):
            if not self.isVisible() or self.isMinimized():
                return
            try:
                e = json.loads((base.PASTA / "etapa.json").read_text())
                ativo = time.time() - e["quando"] < 120 and e["estado"] in ETAPAS
                self.aura.cor = ETAPAS[e["estado"]] if ativo else OCIOSO
            except Exception:
                self.aura.cor = OCIOSO
            self.aura.update()

        # ---------------------------------------------------- dados
        def atualizar(self):
            caps = capacidades.inventario(salvar=False)
            preencher(self.t_cap, [(c["tipo"], c["nome"], c["versao"], c["origem"],
                                    c["permissoes"].get("nivel"), c["status"], c["descricao"]) for c in caps])
            nec = descoberta.necessidades()
            preencher(self.t_nec, [(n["id"], n["estado"], n.get("vezes", 1), n["descricao"],
                                    "; ".join(f"{s['tipo']}: {s['nome']}" for s in n.get("solucoes", []))[:200])
                                   for n in reversed(nec)])
            preencher(self.t_skl, [(s["nome"], s["versao"], s["origem"], s["descricao"]) for s in skills.instaladas()])
            est = extensoes.estados()
            linhas = []
            for nome, e in est.items():
                try:
                    m = extensoes.manifesto(base.EXTENSOES / nome)
                except Exception:
                    continue
                for f in m.get("ferramentas", []):
                    linhas.append((f"ext_{f['nome']}", nome, e.get("versao"), e.get("nivel"),
                                   "sim" if (m.get("permissoes") or {}).get("rede") else "não",
                                   "ativa" if e.get("ativa") else "desativada"))
            preencher(self.t_fer, linhas)
            dev = []
            for p in sorted(base.CANDIDATOS.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                r = avaliacao.ultima(p.name)
                dev.append((p.name, "sem avaliação" if not r else ("APROVADO" if r["aprovado"] else "REPROVADO"),
                            r["quando"] if r else "", "; ".join(r["motivos"])[:160] if r else ""))
            preencher(self.t_dev, dev)
            tst = []
            for r in avaliacao.todas()[:100]:
                t = r.get("testes") or {}
                c = r.get("comparacao") or {}
                tst.append((r["quando"], r["candidato"], "aprovado" if r["aprovado"] else "reprovado",
                            f"{t.get('passaram', '-')}/{t.get('total', '-')}",
                            f"{c.get('antes_passaram') or '-'} {c.get('antes_ms') or ''}ms" if c.get("antes_passaram") else "-",
                            f"{c.get('depois_passaram') or '-'} {c.get('depois_ms') or ''}ms" if c else "-",
                            "; ".join(r["motivos"])[:150]))
            preencher(self.t_tst, tst)
            preencher(self.t_his, [(h["quando"], h["evento"], h.get("nome", ""), h.get("versao", "") or "",
                                    h.get("resumo", "") or h.get("descricao", "") or "")
                                   for h in reversed(base.historico(300))])
            preencher(self.t_ver, [(n, "sim" if e.get("ativa") else "não", e.get("versao"), e.get("anterior") or "-",
                                    ", ".join(extensoes.versoes(n)), e.get("nivel")) for n, e in est.items()])
            self.pedidos = list(reversed(aprovacao.listar()))
            preencher(self.t_apr, [(p["id"], p["tipo"], p["nome"], p.get("versao"), p.get("permissoes"),
                                    p["criado"], p["estado"]) for p in self.pedidos])
            pend = sum(p["estado"] == "pendente" for p in self.pedidos)
            self.status.setText(f"{len(caps)} capacidades · {len(skills.instaladas())} skills · "
                                f"{len(est)} extensões · {sum(n['estado'] == 'aberta' for n in nec)} "
                                f"necessidades abertas · {pend} aguardando sua aprovação")
            self.abas.setTabText(8, f"Aprovações ({pend})" if pend else "Aprovações")

        def _sel(self, t, coluna=0):
            r = t.currentRow()
            return t.item(r, coluna).text() if r >= 0 and t.item(r, coluna) else None

        def mostrar_relatorio(self):
            pid = self._sel(self.t_apr)
            p = next((x for x in getattr(self, "pedidos", []) if x["id"] == pid), None)
            self.relatorio.setPlainText(p["relatorio"] + f"\n\nResumo: {p.get('resumo', '')}\nPasta: {p['pasta']}"
                                        if p else "")

        # ---------------------------------------------------- ações humanas
        def _fazer(self, fn, ok_msg):
            try:
                fn()
                QMessageBox.information(self, "Ultron", ok_msg)
            except Exception as e:
                QMessageBox.warning(self, "Ultron", str(e))
            self.atualizar()

        def aprovar(self, nivel):
            pid = self._sel(self.t_apr)
            if not pid:
                return
            if QMessageBox.question(self, "Aprovar", f"Instalar e ativar o pedido {pid} com nível {nivel}?") \
                    != QMessageBox.Yes:
                return
            self._fazer(lambda: aprovacao.aprovar(pid, nivel, por="usuário (Evolution Center)"),
                        "Aprovado. Reinicie o Ultron para carregar.")

        def rejeitar(self):
            pid = self._sel(self.t_apr)
            if pid:
                motivo, ok = QInputDialog.getText(self, "Rejeitar", "Motivo (opcional):")
                if ok:
                    self._fazer(lambda: aprovacao.rejeitar(pid, motivo, por="usuário (Evolution Center)"),
                                "Rejeitado.")

        def rollback(self):
            nome = self._sel(self.t_ver)
            if nome:
                self._fazer(lambda: extensoes.rollback(nome), "Voltou para a versão anterior.")

        def desativar(self):
            nome = self._sel(self.t_ver)
            if nome:
                self._fazer(lambda: extensoes.desativar(nome), "Desativada.")

        def reativar(self):
            nome = self._sel(self.t_ver)
            if nome:
                self._fazer(lambda: extensoes.reativar(nome), "Reativada.")

        def remover_skill(self):
            nome = self._sel(self.t_skl)
            if nome:
                self._fazer(lambda: skills.remover(nome), "Skill removida.")

        def investigar(self):
            nid = self._sel(self.t_nec)
            if nid:
                self._fazer(lambda: descoberta.investigar(nid), "Investigação concluída.")

    janela = Centro()
    janela.show()
    return app.exec()
