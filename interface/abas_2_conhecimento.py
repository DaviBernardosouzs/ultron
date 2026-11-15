"""Abas da Fase 2: ATLAS (busca universal), ARCHIVE (arquivos) e SCRIBE (documentação)."""
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit,
                               QListWidgetItem, QMessageBox, QSplitter, QVBoxLayout, QWidget)

from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela, texto
from modulos import archive, atlas, scribe


def _abrir(caminho, linha=None):
    if not caminho:
        return
    if linha:
        try:
            subprocess.Popen(["code", "-g", f"{caminho}:{linha}"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            pass
    subprocess.Popen(["xdg-open", caminho], start_new_session=True)


def criar(janela):
    return [("ATLAS", _atlas(janela)), ("ARCHIVE", _archive(janela)), ("SCRIBE", _scribe(janela))]


# ------------------------------------------------------------------ ATLAS
def _atlas(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    campo = QLineEdit()
    campo.setPlaceholderText("buscar em documentos, memórias, conversas, atividades e arquivos (Enter)")
    v.addWidget(campo)
    f = QHBoxLayout()
    periodo = QComboBox()
    periodo.setEditable(True)
    periodo.addItems(["qualquer período", "hoje", "esta semana", "últimos 30 dias", "este mês", "mês passado"])
    projeto = QComboBox()
    projeto.setEditable(True)
    try:
        from neuralink import contexto
        projeto.addItems(["todos os projetos"] + contexto.projetos_conhecidos())
    except Exception:
        projeto.addItem("todos os projetos")
    f.addWidget(periodo)
    f.addWidget(projeto)
    fontes = {}
    for nome in atlas.FONTES:
        ch = QCheckBox(nome)
        ch.setChecked(True)
        f.addWidget(ch)
        fontes[nome] = ch
    v.addLayout(f)
    status = aviso("Serviços MCP não entram no Atlas (cada um tem uma API); para eles, peça ao Ultron.")
    v.addWidget(status)
    res = lista()
    v.addWidget(res, 1)

    def mostrar(r):
        res.clear()
        if isinstance(r, Exception):
            status.setText(f"erro: {r}")
            return
        status.setText(f"{len(r)} resultados")
        for x in r:
            it = QListWidgetItem(f"[{x['fonte'].upper()}] {x['titulo']}   · relevância {x['relevancia']}\n"
                                 f"{x['texto'][:240].strip()}\n↳ {x['origem']}")
            it.setData(Qt.UserRole, (x.get("caminho"), x.get("linha")))
            res.addItem(it)
        if not r:
            res.addItem("Nada encontrado.")

    def buscar():
        q = campo.text().strip()
        if not q:
            return
        status.setText("buscando...")
        per = None if periodo.currentIndex() == 0 and periodo.currentText() == "qualquer período" else periodo.currentText()
        proj = None if projeto.currentText() == "todos os projetos" else projeto.currentText()
        em_fundo(w, atlas.buscar, mostrar, q, proj, per, [k for k, c in fontes.items() if c.isChecked()])
    campo.returnPressed.connect(buscar)
    res.itemDoubleClicked.connect(lambda it: _abrir(*(it.data(Qt.UserRole) or (None, None))))
    return w


# ------------------------------------------------------------------ ARCHIVE
def _archive(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("O Archive só lê. Organizar é sempre uma sugestão: nada é movido, renomeado ou apagado "
                      "até você aplicar, e cada movimento pode ser desfeito."))
    f = QHBoxLayout()
    raiz = QComboBox()
    raiz.setEditable(True)
    from core import guardian
    raiz.addItems([os.path.expanduser(d) for d in guardian.diretorios_permitidos()])
    status = aviso("")
    f.addWidget(raiz, 1)
    f.addWidget(botao("CATALOGAR", lambda: catalogar()))
    f.addWidget(botao("SUGERIR ORGANIZAÇÃO", lambda: sugerir()))
    v.addLayout(f)
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    esq = hud.Moldura("resumo e duplicatas")
    resumo = tabela(["Tipo", "Arquivos", "MB"])
    esq.corpo.addWidget(resumo, 1)
    dups = lista()
    esq.corpo.addWidget(dups, 2)
    div.addWidget(esq)
    dir_ = hud.Moldura("sugestões e alterações")
    sug = lista()
    dir_.corpo.addWidget(sug, 2)
    b = QHBoxLayout()
    b.addWidget(botao("APLICAR", lambda: aplicar(), "ok"))
    b.addWidget(botao("DESCARTAR", lambda: descartar(), "perigo"))
    dir_.corpo.addLayout(b)
    alts = lista()
    dir_.corpo.addWidget(alts, 2)
    dir_.corpo.addWidget(botao("DESFAZER ALTERAÇÃO", lambda: desfazer()))
    div.addWidget(dir_)
    v.addWidget(div, 1)

    def atualizar():
        r = os.path.realpath(os.path.expanduser(raiz.currentText()))
        preencher(resumo, [(x["categoria"], x["n"], f"{(x['bytes'] or 0) / 1048576:.1f}") for x in archive.resumo(r)])
        dups.clear()
        for g in archive.duplicatas(r, 40):
            dups.addItem(f"{g['copias']} cópias · {g['tamanho'] / 1048576:.2f} MB cada\n" + "\n".join(g["caminhos"][:5]))
        if not dups.count():
            dups.addItem("Nenhuma duplicata (conteúdo idêntico) encontrada.")
        sug.clear()
        w._sug = archive.sugestoes()
        for s in w._sug:
            sug.addItem(f"#{s['id']} {s['motivo']}\n" + "\n".join(f"  {m['de'].split('/')[-1]} → {m['para'].split('/')[-2]}/"
                                                                 for m in s["plano"][:12])
                        + (f"\n  ... e mais {len(s['plano']) - 12}" if len(s["plano"]) > 12 else ""))
        if not w._sug:
            sug.addItem("Nenhuma sugestão pendente.")
        alts.clear()
        w._alts = archive.alteracoes(100)
        for a in w._alts:
            alts.addItem(f"{a['quando'][:16].replace('T', ' ')} {'(desfeita) ' if a['desfeita'] else ''}{a['de']} → {a['para']}")

    def catalogar():
        status.setText("catalogando...")
        em_fundo(w, archive.catalogar, lambda r: (status.setText(str(r) if isinstance(r, Exception) else
                                                                 f"{r['arquivos']} arquivos em {r['raiz']}"),
                                                  atualizar()), raiz.currentText())

    def sugerir():
        try:
            sid = archive.sugerir_organizacao(raiz.currentText())
            status.setText(f"sugestão #{sid} criada" if sid else "nada a organizar (catalogue antes)")
        except Exception as e:
            status.setText(str(e))
        atualizar()

    def _sel(lst, itens):
        r = lst.currentRow()
        return itens[r] if 0 <= r < len(itens) else None

    def aplicar():
        s = _sel(sug, getattr(w, "_sug", []))
        if s and QMessageBox.question(w, "Archive", f"Mover {len(s['plano'])} arquivos como no plano #{s['id']}?"
                                      ) == QMessageBox.Yes:
            try:
                status.setText(f"{archive.aplicar(s['id'], por='Davi (painel)')} arquivos movidos")
            except Exception as e:
                QMessageBox.warning(w, "Archive", str(e))
            atualizar()

    def descartar():
        s = _sel(sug, getattr(w, "_sug", []))
        if s:
            archive.descartar(s["id"])
            atualizar()

    def desfazer():
        a = _sel(alts, getattr(w, "_alts", []))
        if a:
            try:
                archive.desfazer(a["id"])
            except Exception as e:
                QMessageBox.warning(w, "Archive", str(e))
            atualizar()
    raiz.currentIndexChanged.connect(lambda: atualizar())
    atualizar()
    return w


# ------------------------------------------------------------------ SCRIBE
def _scribe(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("O Scribe escreve só em notas próprias no Obsidian (Scribe/). Cada atualização guarda a "
                      "versão anterior em Scribe/.historico. Texto de IA diz qual modelo gerou."))
    f = QHBoxLayout()
    projeto = QComboBox()
    projeto.setEditable(True)
    try:
        from neuralink import contexto
        projeto.addItems([""] + contexto.projetos_conhecidos())
    except Exception:
        pass
    projeto.setPlaceholderText("projeto (opcional)")
    f.addWidget(projeto, 1)
    saida = texto()
    status = aviso("")

    def rodar(rot, fn, *args):
        status.setText(f"{rot}...")
        em_fundo(w, fn, lambda r: (status.setText(f"erro: {r}" if isinstance(r, Exception) else f"{rot}: pronto"),
                                   carregar()), *args)

    def proj():
        return projeto.currentText().strip() or None

    def relatorio():
        per, ok = QInputDialog.getItem(w, "Relatório", "Período:", ["esta semana", "semana passada", "este mês",
                                                                     "últimos 7 dias", "hoje"], 0, True)
        if ok:
            rodar("relatório", scribe.relatorio, proj(), per)

    def changelog():
        d = QFileDialog.getExistingDirectory(w, "Repositório git", os.path.expanduser("~"))
        if d:
            rodar("changelog", scribe.changelog, d, proj())

    def documentar():
        if not proj():
            QMessageBox.information(w, "Scribe", "Escolha o projeto.")
            return
        rodar("documentação", scribe.documentar_projeto, proj())

    def reuniao():
        arq, _ = QFileDialog.getOpenFileName(w, "Transcrição da reunião", os.path.expanduser("~"), "Texto (*.txt *.md *.vtt *.srt)")
        if not arq:
            return
        titulo, ok = QInputDialog.getText(w, "Reunião", "Título:")
        if ok and titulo.strip():
            rodar("reunião", scribe.resumir_reuniao, titulo.strip(),
                  open(arq, encoding="utf-8", errors="replace").read(), proj())

    for rot, fn in (("RELATÓRIO", relatorio), ("CHANGELOG", changelog), ("DOCUMENTAR PROJETO", documentar),
                    ("RESUMIR REUNIÃO", reuniao)):
        f.addWidget(botao(rot, fn))
    v.addLayout(f)
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    notas = lista()
    div.addWidget(notas)
    div.addWidget(saida)
    div.setSizes([420, 800])
    v.addWidget(div, 1)

    def carregar():
        from core import cofre
        notas.clear()
        raiz = cofre.raiz() / "Scribe"
        arqs = sorted((p for p in raiz.rglob("*.md") if ".historico" not in p.parts),
                      key=lambda p: p.stat().st_mtime, reverse=True) if raiz.exists() else []
        for p in arqs[:300]:
            it = QListWidgetItem(f"{p.relative_to(raiz).parent} / {p.stem}  (v{len(scribe.historico(p.stem)) + 1})")
            it.setData(Qt.UserRole, str(p))
            notas.addItem(it)
        if not arqs:
            notas.addItem("Nenhuma nota do Scribe ainda.")

    notas.currentItemChanged.connect(lambda it, _: saida.setPlainText(open(it.data(Qt.UserRole), encoding="utf-8").read())
                                     if it and it.data(Qt.UserRole) else None)
    notas.itemDoubleClicked.connect(lambda it: _abrir(it.data(Qt.UserRole)))
    carregar()
    return w
