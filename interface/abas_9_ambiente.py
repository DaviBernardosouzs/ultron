"""Abas da Fase 8: DIGITAL TWIN, PRISM e HELIOS."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela, texto
from modulos import gemeo, helios, prism

COR = {"ok": "#9dffb4", "atencao": "#ffb36a", "fora": "#FF243F", "parado": "#858B96", "desligado": "#858B96"}


def criar(janela):
    return [("DIGITAL TWIN", _gemeo(janela)), ("PRISM", _prism(janela)), ("HELIOS", _helios(janela))]


def _gemeo(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Ambiente real a partir de fontes configuradas (máquinas do config, Docker local, serviços do Ultron, "
                      "endpoints cadastrados em gemeo.endpoints). Nada de varredura de rede."))
    b = QHBoxLayout()
    status = aviso("")
    b.addWidget(botao("ATUALIZAR RETRATO", lambda: atualizar(), "ok"))
    b.addWidget(status, 1)
    v.addLayout(b)
    div = QSplitter(Qt.Horizontal)
    tab = tabela(["Componente", "Tipo", "Estado", "Detalhe", "Métricas"], 3)
    div.addWidget(tab)
    lado = QWidget()
    vl = QVBoxLayout(lado)
    vl.setContentsMargins(0, 0, 0, 0)
    m1 = hud.Moldura("diagnóstico")
    diag = lista()
    m1.corpo.addWidget(diag)
    vl.addWidget(m1, 1)
    m2 = hud.Moldura("histórico")
    hist = lista()
    m2.corpo.addWidget(hist)
    vl.addWidget(m2, 1)
    div.addWidget(lado)
    div.setSizes([900, 420])
    v.addWidget(div, 1)

    def mostrar():
        comps = gemeo.componentes()
        preencher(tab, [(c["nome"], c["tipo"], c["estado"], c["detalhe"],
                         ", ".join(f"{k}={x}" for k, x in (c["metricas"] or {}).items() if x not in ("", None))[:90]) for c in comps])
        for i, c in enumerate(comps):
            tab.item(i, 2).setForeground(QColor(COR.get(c["estado"], "#E6E8EC")))
        diag.clear()
        for d in gemeo.diagnostico():
            diag.addItem(f"[{d['estado']}] {d['componente']}\n{d['detalhe'][:120]}"
                         + (f"\ncausa provável: {', '.join(d['causa_provavel'])}" if d["causa_provavel"] else ""))
        if not diag.count():
            diag.addItem("Nenhum componente com problema.")
        hist.clear()
        for x in gemeo.historico(limite=80):
            hist.addItem(f"{x['quando'][5:16]} {x['componente']}: {x['de'] or '—'} → {x['para']}")
        status.setText(f"{len(comps)} componentes")

    def atualizar():
        status.setText("lendo o ambiente...")
        em_fundo(w, gemeo.atualizar, lambda r: (status.setText(str(r)) if isinstance(r, Exception) else mostrar()))

    w.showEvent = lambda e: mostrar()
    return w


def _prism(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Imagens, screenshots, diagramas, gráficos e PDFs de pastas autorizadas. PDF com texto é lido no "
                      "computador; imagens vão ao modelo de visão (hoje: Gemini). O resultado sempre diz quem leu e o que "
                      "não dá para afirmar."))
    f = QHBoxLayout()
    caminho = QLineEdit()
    caminho.setPlaceholderText("arquivo")
    pergunta = QLineEdit()
    pergunta.setPlaceholderText("pergunta (opcional)")
    f.addWidget(caminho, 2)
    f.addWidget(botao("…", lambda: caminho.setText(QFileDialog.getOpenFileName(w, "Arquivo", os.path.expanduser("~"),
                                                                               "Imagens e PDFs (*.png *.jpg *.jpeg *.webp *.pdf *.txt *.md)")[0] or caminho.text())))
    f.addWidget(pergunta, 2)
    f.addWidget(botao("ANALISAR", lambda: analisar(), "ok"))
    v.addLayout(f)
    status = aviso("")
    v.addWidget(status)
    saida = texto()
    v.addWidget(saida, 1)

    def analisar():
        if caminho.text().strip():
            status.setText("analisando...")
            em_fundo(w, prism.analisar, lambda r: (status.setText(f"erro: {r}"), saida.clear()) if isinstance(r, Exception)
                     else (status.setText(f"lido por {r.get('lido_por')}"), saida.setPlainText(prism.formatar(r))),
                     caminho.text().strip(), pergunta.text().strip())
    return w


def _helios(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    if not helios.configurado():
        v.addWidget(aviso("O HELIOS precisa de um Home Assistant. Hoje ele NÃO está configurado: instale o Home Assistant "
                          "(https://www.home-assistant.io), crie um token de longa duração no perfil, coloque a URL em "
                          "casa.url no config.yaml e o token em HOME_ASSISTANT_TOKEN no .env. Nenhum dado de energia é "
                          "mostrado sem medidores reais."))
        v.addStretch()
        return w
    v.addWidget(aviso("Fechaduras, alarmes e portões são só leitura. Dispositivos de risco pedem confirmação sempre."))
    b = QHBoxLayout()
    b.addWidget(botao("ATUALIZAR", lambda: carregar(), "ok"))
    b.addWidget(botao("RELATÓRIO DE ENERGIA (7 DIAS)", lambda: energia()))
    b.addStretch()
    v.addLayout(b)
    div = QSplitter(Qt.Horizontal)
    tab = tabela(["Dispositivo", "Entidade", "Estado", "Risco"], 0)
    div.addWidget(tab)
    rel = texto()
    div.addWidget(rel)
    v.addWidget(div, 1)

    def carregar():
        em_fundo(w, helios.dispositivos, lambda r: rel.setPlainText(str(r)) if isinstance(r, Exception) else
                 preencher(tab, [(d["nome"], d["id"], d["estado"], d["risco"]) for d in r]))

    def energia():
        em_fundo(w, helios.relatorio_energia, lambda r: rel.setPlainText(str(r) if isinstance(r, Exception) else r[0]))
    carregar()
    return w
