"""Abas da Fase 6: MACRO FORGE (automações) e SELF AUDIT (auditoria operacional)."""
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QListWidgetItem, QMessageBox, QSplitter,
                               QVBoxLayout, QWidget)

from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela, texto
from modulos import macros, self_audit

EXEMPLO = {"nome": "resumo da manhã", "descricao": "clima e agenda no Telegram",
           "entradas": [], "passos": [{"id": "e1", "ferramenta": "clima", "args": {}},
                                      {"id": "e2", "ferramenta": "mandar_mensagem_celular",
                                       "args": {"texto": "Bom dia. {{passos.e1.saida}}"}}],
           "saida": "{{passos.e2.saida}}", "gatilho": {"tipo": "diario", "hora": "08:00"}}


def criar(janela):
    return [("MACRO FORGE", _macros(janela)), ("SELF AUDIT", _audit(janela))]


def _macros(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Cada edição vira uma versão. Para ativar: teste a seco e aprove as ferramentas sensíveis (N2). "
                      "Ações críticas (N3) nunca rodam sozinhas: a macro pausa e pede você."))
    div = QSplitter(Qt.Horizontal)
    lst = lista()
    div.addWidget(lst)
    meio = hud.Moldura("definição (json)")
    editor = texto(False)
    editor.setStyleSheet("font-family:'FiraCode Nerd Font'; font-size:11px;")
    meio.corpo.addWidget(editor, 3)
    b = QHBoxLayout()
    for rot, fn, n in (("NOVA", lambda: editor.setPlainText(json.dumps(EXEMPLO, ensure_ascii=False, indent=1)), ""),
                       ("SALVAR VERSÃO", lambda: salvar(), ""), ("TESTAR A SECO", lambda: testar(), ""),
                       ("APROVAR E ATIVAR", lambda: ativar(), "ok"), ("DESATIVAR", lambda: desativar(), "perigo"),
                       ("EXECUTAR AGORA", lambda: rodar(), ""), ("IMPORTAR", lambda: importar(), ""),
                       ("EXPORTAR", lambda: exportar(), "")):
        b.addWidget(botao(rot, fn, n))
    meio.corpo.addLayout(b)
    resultado = texto()
    meio.corpo.addWidget(resultado, 2)
    div.addWidget(meio)
    hist = lista()
    div.addWidget(hist)
    div.setSizes([300, 720, 330])
    v.addWidget(div, 1)
    w._sel = None

    def carregar():
        lst.clear()
        w._ms = macros.listar()
        for m in w._ms:
            lst.addItem(f"{m['nome']}\nativa v{m['ativa'] or '—'} · última v{m['ultima']} ({m['estado_ultima']})\n"
                        f"gatilho: {m['gatilho'].get('tipo')} {m['gatilho'].get('hora', '')}{m['gatilho'].get('evento', '')}")
        if not w._ms:
            lst.addItem("Nenhuma macro. Clique NOVA para um exemplo.")
        hist.clear()
        for x in macros.historico(w._sel, 40):
            it = QListWidgetItem(f"#{x['id']} {x['nome']} v{x['versao']} [{x['estado']}]\n{x['inicio'][:16]} · {x['gatilho']}")
            it.setForeground(QColor({"concluida": "#9dffb4", "falhou": "#ff6a74", "pausada": "#8ab4ff"}.get(x["estado"], "#ddd")))
            hist.addItem(it)

    def mostrar(r):
        if 0 <= r < len(getattr(w, "_ms", [])):
            w._sel = w._ms[r]["nome"]
            m = macros.obter(w._sel)
            editor.setPlainText(json.dumps(m["definicao"], ensure_ascii=False, indent=1))
            resultado.setPlainText(f"v{m['versao']} · {m['estado']}" + (f"\nTeste: {json.dumps(m['teste'], ensure_ascii=False, indent=1)}" if m["teste"] else ""))
            carregar()

    def _def():
        try:
            return json.loads(editor.toPlainText())
        except ValueError as e:
            resultado.setPlainText(f"JSON inválido: {e}")
            return None

    def salvar():
        d = _def()
        if d:
            nome, ver, p = macros.salvar(d)
            w._sel = nome
            resultado.setPlainText(f"{nome} v{ver} salva como rascunho." + (f"\nProblemas: {p}" if p else ""))
            carregar()

    def testar():
        if w._sel:
            t = macros.testar(w._sel)
            resultado.setPlainText(json.dumps(t, ensure_ascii=False, indent=1))
            carregar()

    def ativar():
        if not w._sel:
            return
        m = macros.obter(w._sel)
        sens = macros.sensiveis(m["definicao"])
        msg = f"Ativar {w._sel} v{m['versao']}?" + (f"\n\nFerramentas sensíveis: {sens}\nN2 aprovadas aqui rodam sem perguntar "
                                                     "dentro desta macro; N3 sempre pedem você." if sens else "")
        if QMessageBox.question(w, "Ativar macro", msg) == QMessageBox.Yes:
            try:
                macros.ativar(w._sel, m["versao"], por="Davi (painel)")
            except Exception as e:
                QMessageBox.warning(w, "Macro Forge", str(e))
            carregar()

    def desativar():
        if w._sel:
            macros.desativar(w._sel)
            carregar()

    def rodar():
        if w._sel:
            em_fundo(w, macros.executar, lambda r: (resultado.setPlainText(
                str(r) if isinstance(r, Exception) else json.dumps(r, ensure_ascii=False, indent=1)), carregar()), w._sel)

    def importar():
        arq, _ = QFileDialog.getOpenFileName(w, "Importar macro", os.path.expanduser("~"), "JSON (*.json)")
        if arq:
            nome, ver, p = macros.importar(open(arq, encoding="utf-8").read())
            resultado.setPlainText(f"{nome} v{ver} importada como rascunho." + (f"\nProblemas: {p}" if p else ""))
            carregar()

    def exportar():
        if w._sel:
            arq, _ = QFileDialog.getSaveFileName(w, "Exportar", os.path.expanduser(f"~/{w._sel}.json"), "JSON (*.json)")
            if arq:
                open(arq, "w", encoding="utf-8").write(macros.exportar(w._sel))

    lst.currentRowChanged.connect(mostrar)
    carregar()
    return w


def _audit(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Auditoria com evidências. Nada é corrigido automaticamente: um achado vira proposta na Evolution "
                      "Forge, que testa no sandbox e espera sua aprovação."))
    b = QHBoxLayout()
    com_testes = QCheckBox("rodar a suíte de testes")
    status = aviso("")
    b.addWidget(botao("AUDITAR AGORA", lambda: auditar(), "ok"))
    b.addWidget(com_testes)
    b.addWidget(botao("PROPOR CORREÇÃO", lambda: propor()))
    b.addStretch()
    v.addLayout(b)
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    hist = lista()
    div.addWidget(hist)
    tab = tabela(["Nível", "Área", "Item", "Problema", "Evidência", "Sugestão"], 3)
    tab.setWordWrap(True)
    div.addWidget(tab)
    div.setSizes([260, 1000])
    v.addWidget(div, 1)

    def carregar():
        hist.clear()
        w._auds = self_audit.ultimas(30)
        for a in w._auds:
            hist.addItem(f"#{a['id']} {a['quando'][:16].replace('T', ' ')}\n{a['resumo']}")
        if not w._auds:
            hist.addItem("Nenhuma auditoria ainda.")

    def mostrar(r):
        if 0 <= r < len(getattr(w, "_auds", [])):
            w._achados = w._auds[r]["achados"]
            preencher(tab, [(a["nivel"], a["area"], a["item"], a["problema"], a["evidencia"], a["sugestao"]) for a in w._achados])
            for i, a in enumerate(w._achados):
                tab.item(i, 0).setForeground(QColor({"ERROR": "#ff4655", "WARNING": "#ffb36a"}.get(a["nivel"], "#9a8f93")))
            tab.resizeRowsToContents()

    def auditar():
        status.setText("auditando...")
        em_fundo(w, self_audit.auditar, lambda r: (status.setText(str(r) if isinstance(r, Exception) else r["resumo"]),
                                                   carregar(), hist.setCurrentRow(0)), com_testes.isChecked())

    def propor():
        r = tab.currentRow()
        if 0 <= r < len(getattr(w, "_achados", [])):
            status.setText(f"proposta registrada: {self_audit.propor(w._achados[r])}")

    hist.currentRowChanged.connect(mostrar)
    carregar()
    return w
