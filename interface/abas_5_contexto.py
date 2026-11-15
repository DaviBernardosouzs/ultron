"""Abas da Fase 5: WORKSPACES e SENTINEL (com os interruptores de privacidade)."""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QSplitter, QVBoxLayout, QWidget)

from core import eventos, workspaces
from core.config import ajuste, definir
from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, texto
from modulos import sentinel


def criar(janela):
    return [("WORKSPACES", _workspaces(janela)), ("SENTINEL", _sentinel(janela))]


def _workspaces(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Um WorkSpace junta projeto, diretório, ferramentas, skills e plugins. Ativo, ele isola o contexto "
                      "do projeto e o Guardian bloqueia ferramentas fora dele. O diretório precisa estar liberado no Guardian."))
    div = QSplitter(Qt.Horizontal)
    lst = lista()
    div.addWidget(lst)
    form_box = hud.Moldura("workspace")
    f = QFormLayout()
    nome, projeto, diretorio, skills, mcps = (QLineEdit() for _ in range(5))
    tipo = QComboBox()
    tipo.addItems(workspaces.TIPOS)
    grupos = QLineEdit()
    grupos.setPlaceholderText("vazio = padrão do tipo")
    for rot, x in (("Nome", nome), ("Tipo", tipo), ("Projeto", projeto), ("Diretório", diretorio),
                   ("Grupos de ferramentas", grupos), ("Skills", skills), ("Plugins MCP", mcps)):
        f.addRow(rot, x)
    form_box.corpo.addLayout(f)
    b = QHBoxLayout()
    for rot, fn, n in (("SALVAR", lambda: salvar(), "ok"), ("ATIVAR", lambda: ativar(), "ok"), ("SAIR", lambda: sair(), ""),
                       ("REMOVER", lambda: remover(), "perigo"), ("PASTA…", lambda: diretorio.setText(
                           QFileDialog.getExistingDirectory(w, "Diretório", os.path.expanduser("~")) or diretorio.text()), "")):
        b.addWidget(botao(rot, fn, n))
    form_box.corpo.addLayout(b)
    sessao = texto()
    form_box.corpo.addWidget(sessao, 1)
    div.addWidget(form_box)
    div.setSizes([360, 900])
    v.addWidget(div, 1)
    sep = lambda t: [x.strip() for x in t.split(",") if x.strip()]

    def carregar():
        atual = workspaces.atual()
        lst.clear()
        w._ws = workspaces.listar()
        for x in w._ws:
            lst.addItem(f"{'▶ ' if x['nome'] == atual else ''}{x['nome']}  ({x['tipo']})\n{x['projeto'] or '—'} · {x['diretorio'] or '—'}")
        if not w._ws:
            lst.addItem("Nenhum WorkSpace. Preencha ao lado e salve.")

    def mostrar(r):
        if not 0 <= r < len(getattr(w, "_ws", [])):
            return
        x = w._ws[r]
        nome.setText(x["nome"]); tipo.setCurrentText(x["tipo"]); projeto.setText(x["projeto"] or "")
        diretorio.setText(x["diretorio"] or ""); grupos.setText(", ".join(x["grupos"]))
        skills.setText(", ".join(x["skills"])); mcps.setText(", ".join(x["mcps"]))
        s = workspaces.restaurar_sessao(x["nome"])
        sessao.setPlainText(f"Notas: {s['notas'] or '—'}\n\nPlanos: " + ("; ".join(f"{p['id']} [{p['estado']}]" for p in s["planos"]) or "—")
                            + "\nClaude Code: " + ("; ".join(f"{t['id']} [{t['estado']}]" for t in s["claude"]) or "—")
                            + "\nDocumentos: " + (", ".join(d["titulo"] for d in s["documentos"]) or "—")
                            + "\nAtividades:\n" + "\n".join(f"  {a['quando'][:16]} {a['titulo'][:70]}" for a in s["atividades"]))

    def salvar():
        try:
            _, av = workspaces.criar(nome.text(), tipo.currentText(), projeto.text().strip() or None,
                                     diretorio.text().strip() or None, sep(grupos.text()) or None, sep(skills.text()), sep(mcps.text()))
            if av:
                QMessageBox.information(w, "WorkSpace", av.strip())
        except Exception as e:
            QMessageBox.warning(w, "WorkSpace", str(e))
        carregar()

    def ativar():
        if nome.text().strip():
            workspaces.ativar(nome.text().strip())
            carregar()

    def sair():
        workspaces.desativar()
        carregar()

    def remover():
        if nome.text().strip() and QMessageBox.question(w, "Remover", f"Remover o WorkSpace {nome.text()}?") == QMessageBox.Yes:
            workspaces.remover(nome.text().strip())
            carregar()

    lst.currentRowChanged.connect(mostrar)
    carregar()
    return w


def _sentinel(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("O Sentinel só observa o que você ligar aqui. Não grava a tela continuamente, não monitora outras "
                      "pessoas e só tira uma captura quando você pede. Títulos de janela não são guardados, a menos que "
                      "você permita."))
    chaves = QHBoxLayout()
    for chave, rot in (("ativo", "SENTINEL LIGADO"), ("app_ativo", "ler app em foco"),
                       ("eventos_sistema", "alertas do sistema"), ("guardar_titulos", "guardar títulos de janela")):
        ch = QCheckBox(rot)
        ch.setChecked(bool(ajuste(f"sentinel.{chave}", chave != "guardar_titulos" and chave != "ativo")))
        ch.toggled.connect(lambda on, c=chave: (definir(f"sentinel.{c}", bool(on)),
                                                eventos.emitir("module.status_changed", "sentinel",
                                                               {"modulo": "sentinel", "mudanca": f"{c}={'on' if on else 'off'}"})))
        chaves.addWidget(ch)
    chaves.addStretch()
    v.addLayout(chaves)
    b = QHBoxLayout()
    status = aviso("")
    b.addWidget(botao("O QUE ESTOU USANDO?", lambda: agora()))
    b.addWidget(botao("VERIFICAR SISTEMA AGORA", lambda: verificar()))
    b.addStretch()
    v.addLayout(b)
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    m1 = hud.Moldura("contexto atual")
    ctx = texto()
    m1.corpo.addWidget(ctx)
    div.addWidget(m1)
    m2 = hud.Moldura("alertas")
    alertas = lista()
    m2.corpo.addWidget(alertas)
    div.addWidget(m2)
    v.addWidget(div, 1)

    def agora():
        try:
            c = sentinel.contexto_da_janela()
            j = c["janela"]
            ctx.setPlainText(f"App: {j['app']}\nJanela: {j['titulo']}\nPID: {j['pid']}\n\nWorkSpace sugerido: "
                             f"{c['workspace'] or '—'}\n\nDocumentos relacionados:\n" + ("\n".join(c["documentos"]) or "—"))
        except Exception as e:
            ctx.setPlainText(str(e))

    def verificar():
        status.setText("verificando...")
        em_fundo(w, sentinel.verificar_sistema, lambda r: (status.setText(
            f"erro: {r}" if isinstance(r, Exception) else f"{len(r)} alerta(s) novo(s)"), carregar()))

    def carregar():
        alertas.clear()
        evs = [e for e in eventos.consultar(origem="sentinel", limite=200) if e["dados"].get("mudanca") == "alerta"]
        for e in evs[:60]:
            alertas.addItem(f"{e['quando'][:16].replace('T', ' ')} [{e['dados'].get('severidade')}] {e['dados'].get('descricao')}")
        if not evs:
            alertas.addItem("Nenhum alerta.")

    t = QTimer(w)
    t.timeout.connect(lambda: carregar() if w.isVisible() else None)
    t.start(5000)
    carregar()
    return w
