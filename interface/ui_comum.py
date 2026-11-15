"""Peças visuais comuns das abas de módulos (mesma identidade do painel)."""
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QListWidget, QPushButton,
                               QTableWidget, QTableWidgetItem, QTextEdit)

FONTE = "FiraCode Nerd Font"


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


def texto(somente_leitura=True):
    t = QTextEdit()
    t.setReadOnly(somente_leitura)
    return t


def lista():
    l = QListWidget()
    l.setWordWrap(True)
    return l


def aviso(txt):
    l = QLabel(txt)
    l.setWordWrap(True)
    l.setStyleSheet("color:#bfb3b6;")
    return l


def em_fundo(janela, fn, ao_terminar, *args):
    """Roda fn numa thread e entrega o resultado (ou a exceção) na thread da interface."""
    import threading
    from PySide6.QtCore import QObject, Signal

    class _P(QObject):
        pronto = Signal(object)
    p = _P(janela)
    p.pronto.connect(ao_terminar)

    def job():
        try:
            r = fn(*args)
        except Exception as e:
            r = e
        p.pronto.emit(r)
    threading.Thread(target=job, daemon=True).start()
