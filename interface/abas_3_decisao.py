"""Abas da Fase 3: CORTEX (apoio à decisão) e MISSION CONTROL (planos do Vector)."""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLineEdit, QListWidgetItem, QMessageBox, QSplitter,
                               QVBoxLayout, QWidget)

from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela, texto
from modulos import cortex, vector

COR_ESTADO = {"feita": "#9dffb4", "executando": "#ffd28a", "falhou": "#ff6a74", "aguardando_aprovacao": "#8ab4ff",
              "aguardando_manual": "#8ab4ff", "interrompida": "#ffb36a", "bloqueada": "#ff6a74", "pendente": "#9a8f93"}


def criar(janela):
    return [("CORTEX", _cortex(janela)), ("MISSION CONTROL", _vector(janela))]


def _cortex(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("A recomendação é uma conta: notas × pesos, com teste de robustez. Cada nota mostra a evidência "
                      "(documento, memória, conversa) ou diz que é premissa. Quem decide é você."))
    f = QHBoxLayout()
    problema = QLineEdit()
    problema.setPlaceholderText("qual decisão você precisa tomar? (Enter)")
    alternativas = QLineEdit()
    alternativas.setPlaceholderText("alternativas, separadas por ; (opcional)")
    f.addWidget(problema, 3)
    f.addWidget(alternativas, 2)
    v.addLayout(f)
    status = aviso("")
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    hist = lista()
    div.addWidget(hist)
    direita = QWidget()
    vd = QVBoxLayout(direita)
    vd.setContentsMargins(0, 0, 0, 0)
    matriz = tabela(["Alternativa", "Pontos", "Cobertura de evidência"])
    vd.addWidget(matriz, 1)
    det = texto()
    vd.addWidget(det, 3)
    vd.addWidget(botao("REGISTRAR MINHA DECISÃO", lambda: registrar(), "ok"))
    div.addWidget(direita)
    div.setSizes([360, 900])
    v.addWidget(div, 1)

    def carregar():
        hist.clear()
        w._an = cortex.listar()
        for a in w._an:
            hist.addItem(f"#{a['id']} [{a['estado']}] {a['problema'][:70]}" + (f"\n→ {a['escolha']}" if a["escolha"] else ""))
        if not w._an:
            hist.addItem("Nenhuma análise ainda.")

    def mostrar(aid):
        a = cortex.obter(aid)
        r = a["dados"].get("resultado") or {}
        preencher(matriz, [(alt, r["pontos"][alt], f"{r['cobertura_evidencias'].get(alt, 0)}%") for alt in r.get("ordem", [])])
        det.setPlainText(cortex.relatorio(aid))
        w._atual = aid

    def analisar():
        q = problema.text().strip()
        if not q:
            return
        alts = [x.strip() for x in alternativas.text().split(";") if x.strip()] or None
        status.setText("estruturando, buscando evidências e avaliando (IA local do desktop primeiro)...")

        def job():
            aid = cortex.estruturar(q, alternativas=alts)
            cortex.avaliar(aid)
            return aid
        em_fundo(w, job, lambda r: (status.setText(f"erro: {r}") if isinstance(r, Exception) else
                                    (status.setText(f"análise #{r} pronta"), carregar(), mostrar(r))))

    def registrar():
        aid = getattr(w, "_atual", None)
        if not aid:
            return
        nomes = [x["nome"] for x in cortex.obter(aid)["dados"]["alternativas"]]
        esc, ok = QInputDialog.getItem(w, "Decisão", "O que você decidiu?", nomes, 0, False)
        if ok:
            cortex.registrar(aid, esc, por="Davi (painel)")
            status.setText(f"decisão registrada no Scribe e no NEURALINK: {esc}")
            carregar()

    problema.returnPressed.connect(analisar)
    hist.currentRowChanged.connect(lambda r: mostrar(w._an[r]["id"]) if 0 <= r < len(getattr(w, "_an", [])) else None)
    carregar()
    return w


def _vector(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Planos do Vector: cada etapa usa uma ferramenta real e passa pelo Guardian. Etapas que precisam "
                      "de você param aqui até você aprovar (ou fazer, se for manual). O progresso é o das etapas "
                      "realmente concluídas."))
    vector.recuperar_interrompidos()
    f = QHBoxLayout()
    objetivo = QLineEdit()
    objetivo.setPlaceholderText("novo objetivo para planejar (Enter)")
    f.addWidget(objetivo, 1)
    for rot, fn, nome in (("EXECUTAR / RETOMAR", lambda: executar(), "ok"), ("APROVAR ETAPA", lambda: aprovar(), "ok"),
                          ("CANCELAR", lambda: cancelar(), "perigo"), ("VALIDAR", lambda: validar(), "")):
        f.addWidget(botao(rot, fn, nome))
    v.addLayout(f)
    status = aviso("")
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    planos = lista()
    div.addWidget(planos)
    m = hud.Moldura("etapas")
    etapas = lista()
    m.corpo.addWidget(etapas, 2)
    det = texto()
    m.corpo.addWidget(det, 1)
    div.addWidget(m)
    div.setSizes([380, 880])
    v.addWidget(div, 1)

    def carregar():
        atual = getattr(w, "_pid", None)
        planos.clear()
        w._planos = vector.listar(60)
        for p in w._planos:
            planos.addItem(f"{p['id']} [{p['estado'].upper()}]\n{p['objetivo'][:80]}")
        if not w._planos:
            planos.addItem("Nenhum plano. Escreva um objetivo acima ou peça ao Ultron.")
        if atual:
            mostrar(atual)

    def mostrar(pid):
        w._pid = pid
        p = vector.obter(pid)
        etapas.clear()
        feitas = sum(e["estado"] == "feita" for e in p["etapas"])
        status.setText(f"{p['objetivo']} · {p['estado']} · {feitas}/{len(p['etapas'])} etapas concluídas · "
                       f"gerado por {p['gerado_por']}")
        w._etapas = p["etapas"]
        for e in p["etapas"]:
            alvo = f"{e['ferramenta']} {json.dumps(e['args'], ensure_ascii=False)}" if e["executor"] == "ferramenta" else e["executor"]
            it = QListWidgetItem(f"{e['id']}  [{e['estado']}]  {e['descricao']}\n    {alvo}"
                                 + (f"   ← {', '.join(e['depende'])}" if e["depende"] else ""))
            it.setForeground(QColor(COR_ESTADO.get(e["estado"], "#ddd")))
            etapas.addItem(it)
        val = json.loads(p["validacao"]) if p["validacao"] else None
        det.setPlainText(("Critérios: " + "; ".join(map(str, p["criterios"])) if p["criterios"] else "")
                         + (f"\n\nValidação ({val.get('por')}): {'OK' if val.get('ok') else 'NÃO'} {val.get('motivo', '')}" if val else ""))

    def planejar():
        q = objetivo.text().strip()
        if q:
            status.setText("planejando com as ferramentas disponíveis...")
            em_fundo(w, vector.planejar, lambda r: (status.setText(f"erro: {r}") if isinstance(r, Exception) else
                                                    (objetivo.clear(), carregar(), mostrar(r))), q)

    def confirmar_na_tela(desc, nivel):
        return "sim" if QMessageBox.question(w, f"Confirmação ({nivel})", desc) == QMessageBox.Yes else "nao"

    def executar():
        pid = getattr(w, "_pid", None)
        if pid:
            try:
                vector.executar(pid)            # confirmações vão para o confirmador do Ultron ou pausam
            except Exception as e:
                status.setText(str(e))

    def aprovar():
        pid = getattr(w, "_pid", None)
        r = etapas.currentRow()
        if pid and 0 <= r < len(w._etapas):
            e = w._etapas[r]
            if QMessageBox.question(w, "Aprovar etapa", f"{e['descricao']}\n\nAprovar e continuar o plano?") == QMessageBox.Yes:
                try:
                    vector.aprovar_etapa(pid, e["id"])
                except Exception as ex:
                    status.setText(str(ex))

    def cancelar():
        pid = getattr(w, "_pid", None)
        if pid:
            vector.cancelar(pid)
            carregar()

    def validar():
        pid = getattr(w, "_pid", None)
        if pid:
            status.setText("validando...")
            em_fundo(w, vector.validar, lambda r: (status.setText(f"erro: {r}") if isinstance(r, Exception) else mostrar(pid)), pid)

    objetivo.returnPressed.connect(planejar)
    planos.currentRowChanged.connect(lambda r: mostrar(w._planos[r]["id"]) if 0 <= r < len(getattr(w, "_planos", [])) else None)
    t = QTimer(w)
    t.timeout.connect(lambda: carregar() if w.isVisible() else None)
    t.start(2000)
    carregar()
    return w
