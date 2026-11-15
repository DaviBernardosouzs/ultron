"""Aba CLAUDE BRIDGE: estado, modo, orçamento, tarefas, eventos ao vivo, aprovações e mudanças."""
import json
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem,
                               QMessageBox, QSplitter, QVBoxLayout, QWidget)

from core.config import definir
from interface import hud
from interface.ui_comum import aviso, botao, lista, texto
from modulos import claude_bridge as cb

COR = {"executando": "#ffd28a", "concluida": "#9dffb4", "falhou": "#ff6a74", "cancelada": "#9a8f93",
       "interrompida": "#ffb36a"}


def criar(janela):
    return [("CLAUDE BRIDGE", _aba(janela))]


def _aba(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    cb.recuperar_interrompidas()
    topo = QHBoxLayout()
    estado = QLabel()
    estado.setStyleSheet("font-family:'FiraCode Nerd Font'; color:#ffd6da;")
    topo.addWidget(estado, 1)
    modo = QComboBox()
    modo.addItems(["local_only", "automatico", "claude_preferido"])
    modo.setCurrentText(cb.cfg("modo", "automatico"))
    modo.currentTextChanged.connect(lambda m: definir("claude_bridge.modo", m))
    topo.addWidget(QLabel("modo"))
    topo.addWidget(modo)
    v.addLayout(topo)
    v.addWidget(aviso("O Claude Code é um executor que o Ultron aciona; o resultado sempre aparece como dele. Cada ação "
                      "passa pelo Guardian; edições ficam num worktree isolado até você aplicar. Só diretórios com "
                      "consentimento são enviados."))
    nova = QHBoxLayout()
    objetivo = QLineEdit()
    objetivo.setPlaceholderText("nova tarefa direto no Claude Code")
    pasta = QLineEdit()
    pasta.setPlaceholderText("diretório")
    editar = QCheckBox("pode editar")
    nova.addWidget(objetivo, 3)
    nova.addWidget(pasta, 2)
    nova.addWidget(botao("…", lambda: pasta.setText(QFileDialog.getExistingDirectory(w, "Diretório", os.path.expanduser("~")) or pasta.text())))
    nova.addWidget(editar)
    nova.addWidget(botao("INICIAR", lambda: iniciar(), "ok"))
    nova.addWidget(botao("PERMITIR ENVIO", lambda: consentir()))
    v.addLayout(nova)
    status = aviso("")
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    tarefas = lista()
    div.addWidget(tarefas)
    meio = hud.Moldura("execução ao vivo")
    evs = lista()
    meio.corpo.addWidget(evs, 3)
    det = texto()
    meio.corpo.addWidget(det, 2)
    b = QHBoxLayout()
    for rot, fn, nome in (("INTERROMPER", lambda: interromper(), "perigo"), ("VER MUDANÇAS", lambda: ver_diff(), ""),
                          ("APLICAR MUDANÇAS", lambda: aplicar(), "ok"), ("DESCARTAR WORKTREE", lambda: descartar(), "perigo")):
        b.addWidget(botao(rot, fn, nome))
    meio.corpo.addLayout(b)
    div.addWidget(meio)
    direita = hud.Moldura("aprovações pedidas")
    aprov = lista()
    direita.corpo.addWidget(aprov, 1)
    b2 = QHBoxLayout()
    b2.addWidget(botao("PERMITIR", lambda: responder(True), "ok"))
    b2.addWidget(botao("NEGAR", lambda: responder(False), "perigo"))
    direita.corpo.addLayout(b2)
    div.addWidget(direita)
    div.setSizes([330, 640, 330])
    v.addWidget(div, 1)
    w._sel = None
    w._seq = 0

    def atualizar():
        if not w.isVisible():
            return
        disp = cb.disponibilidade() if not hasattr(w, "_disp") or not w._disp["ok"] else w._disp
        w._disp = disp
        estado.setText(("● CLAUDE CODE " + disp.get("versao", "") if disp["ok"] else "○ INDISPONÍVEL: " + disp["motivo"])
                       + f"   ·   hoje US$ {cb.gasto_hoje():.2f} de {cb.cfg('orcamento_diario_usd', 3.0)}"
                       + f"   ·   consentimento: {', '.join(cb.cfg('consentimento', []) or []) or 'nenhum'}")
        sel = w._sel
        tarefas.clear()
        w._tarefas = cb.listar(60)
        for i, t in enumerate(w._tarefas):
            dur = f"{(t['duracao_ms'] or 0) / 1000:.0f}s" if t["duracao_ms"] else ""
            it = QListWidgetItem(f"{t['id']} [{t['estado'].upper()}] US$ {t['custo'] or 0:.2f} {dur}\n{t['objetivo'][:70]}"
                                 + ("\n✎ worktree pendente" if t["worktree"] and not t["aplicado"] else "")
                                 + (f"\n✔ aplicado {t['aplicado'][:16]}" if t["aplicado"] else ""))
            it.setForeground(QColor(COR.get(t["estado"], "#ddd")))
            tarefas.addItem(it)
            if t["id"] == sel:
                tarefas.setCurrentRow(i)
        if sel:
            novos = cb.eventos_da_tarefa(sel, w._seq)
            for e in novos:
                d = e["dados"]
                txt = {"inicio": lambda: f"sessão {d.get('sessao')} · modelo {d.get('modelo')}",
                       "ferramenta": lambda: f"{d.get('nome')} {json.dumps(d.get('entrada'), ensure_ascii=False)[:140]}",
                       "resultado_ferramenta": lambda: f"{d.get('nome')} {'ERRO ' if d.get('erro') else ''}{str(d.get('saida'))[:140]}",
                       "permissao": lambda: f"Guardian: {d.get('ferramenta')} → {d.get('decisao')} ({d.get('motivo')})",
                       "mensagem": lambda: str(d.get("texto"))[:300],
                       "fim": lambda: f"{d.get('subtype')} · US$ {d.get('total_cost_usd')} · {d.get('num_turns')} turnos · {d.get('duration_ms')} ms"}
                it = QListWidgetItem(f"{e['quando'][11:19]}  {e['tipo'].upper():<20} {txt.get(e['tipo'], lambda: str(d))()}")
                it.setForeground(QColor("#ff6a74" if e["tipo"] in ("fim",) and d.get("is_error") else
                                        "#8ab4ff" if e["tipo"] == "permissao" else "#e6dfe1"))
                evs.addItem(it)
                w._seq = e["seq"]
            if novos:
                evs.scrollToBottom()
        aprov.clear()
        w._aprov = cb.aprovacoes()
        for a in w._aprov:
            aprov.addItem(f"{a['tarefa']} · {a['ferramenta']}\n{a['motivo']}\n{json.dumps(a['entrada'], ensure_ascii=False)[:200]}")
        if not w._aprov:
            aprov.addItem("Nenhuma ação esperando você.")

    def selecionar(r):
        if 0 <= r < len(getattr(w, "_tarefas", [])) and w._tarefas[r]["id"] != w._sel:
            w._sel = w._tarefas[r]["id"]
            w._seq = 0
            evs.clear()
            t = cb.obter(w._sel)
            det.setPlainText(f"[Resultado do Claude Code]\n{t['resultado'] or '(em andamento)'}\n\nArquivos: "
                             + (", ".join(t["arquivos"]) or "-") + (f"\n\nErro: {t['erro']}" if t["erro"] else "")
                             + f"\n\nMotivo da delegação: {t['motivo'] or '-'}\nContrato: "
                             + json.dumps({k: t['contrato'].get(k) for k in ('aceite', 'restricoes', 'limite_usd', 'max_turnos', 'limite_s', 'editar')},
                                          ensure_ascii=False))
            atualizar()

    def iniciar():
        try:
            d = cb.nova_delegacao(objetivo.text().strip(), pasta.text().strip(), editar=editar.isChecked(), origem="painel",
                                  motivo="iniciada pelo Davi no painel")
            w._sel = cb.iniciar(d)
            w._seq = 0
            evs.clear()
            status.setText(f"tarefa {w._sel} iniciada")
        except Exception as e:
            QMessageBox.warning(w, "Claude Bridge", str(e))

    def consentir():
        d = pasta.text().strip()
        if d and QMessageBox.question(w, "Consentimento", f"Permitir que o Ultron envie conteúdo de\n{d}\nao Claude Code "
                                      "(Anthropic) quando delegar tarefas?") == QMessageBox.Yes:
            atual = list(cb.cfg("consentimento", []) or [])
            if d not in atual:
                definir("claude_bridge.consentimento", atual + [os.path.realpath(os.path.expanduser(d))])
            atualizar()

    def interromper():
        if w._sel:
            cb.cancelar(w._sel)

    def ver_diff():
        if w._sel:
            det.setPlainText(cb.diff(w._sel) or "Sem mudanças (ou tarefa sem edição).")

    def aplicar():
        if w._sel and QMessageBox.question(w, "Aplicar", "Fazer merge das mudanças do worktree no repositório?") == QMessageBox.Yes:
            try:
                cb.aplicar(w._sel, por="Davi (painel)")
                status.setText("mudanças aplicadas")
            except Exception as e:
                QMessageBox.warning(w, "Claude Bridge", str(e))

    def descartar():
        if w._sel and QMessageBox.question(w, "Descartar", "Apagar o worktree e o ramo desta tarefa?") == QMessageBox.Yes:
            cb.descartar_worktree(w._sel)

    def responder(permitir):
        r = aprov.currentRow()
        if 0 <= r < len(getattr(w, "_aprov", [])):
            cb.responder_aprovacao(w._aprov[r]["id"], permitir, por="Davi (painel)")
            atualizar()

    tarefas.currentRowChanged.connect(selecionar)
    t = QTimer(w)
    t.timeout.connect(atualizar)
    t.start(1000)
    w.showEvent = lambda e: atualizar()
    return w
