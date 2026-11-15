"""Abas da Fase 7: ORACLE (simulações) e SYNAPSE (agentes)."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela, texto
from modulos import oracle, synapse


def criar(janela):
    return [("ORACLE", _oracle(janela)), ("SYNAPSE", _synapse(janela))]


def _oracle(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("Simulação mostra o que aconteceria SE as premissas valerem; não é previsão. Dados observados "
                      "precisam de fonte; o resto é hipótese ou estimativa e aparece separado no relatório."))
    f = QHBoxLayout()
    desc = QLineEdit()
    desc.setPlaceholderText("descreva o cenário para a IA montar (ou edite o JSON abaixo)")
    f.addWidget(desc, 1)
    f.addWidget(botao("MONTAR COM IA", lambda: montar()))
    f.addWidget(botao("SIMULAR", lambda: simular(), "ok"))
    v.addLayout(f)
    status = aviso("")
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    hist = lista()
    div.addWidget(hist)
    editor = texto(False)
    editor.setStyleSheet("font-family:'FiraCode Nerd Font'; font-size:11px;")
    editor.setPlainText(json.dumps({"variaveis": [{"nome": "horas", "origem": "estimado", "valor": 40},
                                                  {"nome": "preco_hora", "origem": "hipotese", "tipo": "triangular",
                                                   "min": 60, "moda": 80, "max": 120}],
                                    "formulas": {"receita": "horas * preco_hora"},
                                    "alternativas": {"base": {}}, "premissas": []}, ensure_ascii=False, indent=1))
    div.addWidget(editor)
    rel = texto()
    div.addWidget(rel)
    div.setSizes([260, 520, 520])
    v.addWidget(div, 1)

    def carregar():
        hist.clear()
        w._cs = oracle.listar()
        for c in w._cs:
            hist.addItem(f"#{c['id']} {c['nome']}\n{c['criado'][:16]}")
        if not w._cs:
            hist.addItem("Nenhuma simulação.")

    def montar():
        if desc.text().strip():
            status.setText("montando cenário...")
            em_fundo(w, oracle.estruturar, lambda r: (status.setText(str(r)) if isinstance(r, Exception) else
                                                      (editor.setPlainText(json.dumps(r, ensure_ascii=False, indent=1)),
                                                       status.setText(f"proposto por {r.get('gerado_por')}: revise antes de simular"))),
                     desc.text().strip())

    def simular():
        try:
            c = json.loads(editor.toPlainText())
        except ValueError as e:
            status.setText(f"JSON inválido: {e}")
            return
        p = oracle.validar(c)
        if p:
            status.setText("; ".join(p))
            return
        nome = desc.text().strip() or "simulação"
        cid, r = oracle.salvar_e_simular(nome, c)
        rel.setPlainText(oracle.relatorio(nome, c, r))
        status.setText(f"simulação #{cid} pronta")
        carregar()

    hist.currentRowChanged.connect(lambda r: (editor.setPlainText(json.dumps(w._cs[r]["cenario"], ensure_ascii=False, indent=1)),
                                              rel.setPlainText(oracle.relatorio(w._cs[r]["nome"], w._cs[r]["cenario"], w._cs[r]["resultado"])))
                                   if 0 <= r < len(getattr(w, "_cs", [])) else None)
    carregar()
    return w


def _synapse(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(aviso("A Synapse divide objetivos grandes entre agentes, verifica cada entrega e diz quem fez o quê. "
                      "Sem delegação recursiva; tudo passa pelo Guardian; o Claude Code respeita o orçamento."))
    m = hud.Moldura("agentes")
    tab = tabela(["Agente", "Executor", "Responsabilidades", "US$ máx", "Tempo máx", "Ativo"], 2)
    m.corpo.addWidget(tab)
    v.addWidget(m, 1)
    f = QHBoxLayout()
    obj = QLineEdit()
    obj.setPlaceholderText("objetivo para coordenar")
    pasta = QLineEdit()
    pasta.setPlaceholderText("diretório (para código)")
    f.addWidget(obj, 3)
    f.addWidget(pasta, 2)
    f.addWidget(botao("COORDENAR", lambda: coordenar(), "ok"))
    v.addLayout(f)
    status = aviso("")
    v.addWidget(status)
    div = QSplitter(Qt.Horizontal)
    hist = lista()
    det = texto()
    div.addWidget(hist)
    div.addWidget(det)
    div.setSizes([360, 900])
    v.addWidget(div, 2)

    def carregar():
        preencher(tab, [(a["nome"], a["executor"], a["responsabilidades"], a["limite_usd"], a["limite_s"],
                         "sim" if a["ativo"] else "não") for a in synapse.agentes(False)])
        hist.clear()
        w._co = synapse.coordenacoes()
        for c in w._co:
            hist.addItem(f"{c['id']} [{c['estado']}]\n{c['objetivo'][:70]}")

    def coordenar():
        if obj.text().strip():
            status.setText("coordenando...")
            em_fundo(w, synapse.coordenar, lambda r: (status.setText(str(r) if isinstance(r, Exception) else f"{r[0]} pronta"),
                                                      carregar()), obj.text().strip(), pasta.text().strip() or None)

    def mostrar(r):
        if 0 <= r < len(getattr(w, "_co", [])):
            c = w._co[r]
            e = c["entrega"] or {}
            det.setPlainText("Plano:\n" + "\n".join(f"  {s['id']} → {s['agente']}: {s.get('descricao')}" for s in c["plano"].get("subtarefas", []))
                             + "\n\nPartes:\n" + "\n".join(f"  {k}: {p['agente']} ({'verificado' if p['verificado'] else 'NÃO verificado'})"
                                                           for k, p in (e.get("partes") or {}).items())
                             + f"\n\nEntrega (consolidada por {e.get('consolidado_por')}):\n{e.get('texto', '')}")

    hist.currentRowChanged.connect(mostrar)
    carregar()
    return w
