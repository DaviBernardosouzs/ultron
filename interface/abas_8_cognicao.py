"""COGNITIVE INTELLIGENCE CENTER: como o Ultron está usando a própria inteligência (dados reais).

Status cognitivo (último pedido: intenção, contexto, ferramentas enviadas, modelo que respondeu),
memória (fontes, conflitos), execução (planos, Claude Code), aprendizado e avaliação (benchmark,
Reflex), modelos (uso, sucesso, latência observados) e evolução (aprovações e necessidades).
Não mostra raciocínio interno do modelo: mostra decisões operacionais e evidências.
"""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.config import RAIZ, ajuste, definir
from interface import hud
from interface.ui_comum import aviso, botao, em_fundo, lista, preencher, tabela

MONO = "font-family:'FiraCode Nerd Font'; font-size:11px; color:#E6E8EC;"


def criar(janela):
    return [("COGNIÇÃO", _aba(janela))]


def _texto():
    l = QLabel("—")
    l.setWordWrap(True)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse)
    l.setStyleSheet(MONO)
    l.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    return l


def _ultimo_pedido():
    from core import eventos
    ini = eventos.consultar(tipo="task.started", origem="cerebro", limite=1)
    if not ini:
        return None
    corr = ini[0]["correlacao"]
    evs = eventos.consultar(correlacao=corr, apos=0, limite=200)
    r = {"pedido": ini[0]["dados"].get("pedido"), "quando": ini[0]["quando"], "ferramentas_usadas": [], "falhas": []}
    for e in evs:
        d = e["dados"]
        if e["tipo"] == "task.progress" and d.get("etapa") == "contexto":
            r.update(intencao=d.get("intencao"), sinais=d.get("sinais"), fontes=d.get("fontes"),
                     contexto=d.get("contexto_chars"), enviadas=d.get("ferramentas"),
                     peso=d.get("ferramentas_peso_aprox"))
        elif e["tipo"] == "task.progress" and d.get("etapa") == "modelo":
            r.update(modelo=d.get("modelo"), esforco=d.get("esforco"), ms=d.get("ms"), motivo=d.get("motivo"))
        elif e["tipo"] == "tool.completed":
            r["ferramentas_usadas"].append(d.get("ferramenta"))
        elif e["tipo"] == "tool.failed":
            r["falhas"].append(f"{d.get('ferramenta')}: {d.get('erro')}")
    return r


def _benchmarks():
    pasta = RAIZ / "avaliacao" / "resultados"
    saida = []
    for conjunto, filtro in (("desenvolvimento", lambda n: "-" not in n.split(".")[0][9:]),
                             ("validação", lambda n: n.endswith("-validacao.json")), ("teste final", lambda n: n.endswith("-teste.json"))):
        arqs = sorted(p for p in pasta.glob("*.json") if filtro(p.name) and "ANTES" not in p.name) if pasta.exists() else []
        if arqs:
            r = json.loads(arqs[-1].read_text())
            s = r["ferramentas"].get("selecao", {})
            saida.append((conjunto, r["quando"][:16].replace("T", " "), f"{s.get('inclusao', 0):.0%}" if s else "—",
                          s.get("tokens_medio", "—"), f"{r['intencao']['acuracia']:.0%}" if r.get("intencao", {}).get("acuracia") is not None else "—",
                          f"{r['recuperacao']['recall@5']:.0%}" if "recuperacao" in r else "—"))
    return saida


def _aba(janela):
    w = QWidget()
    v = QVBoxLayout(w)
    topo = QHBoxLayout()
    topo.addWidget(aviso("Decisões operacionais e evidências reais de cada pedido. O raciocínio interno do modelo não é "
                         "exibido (nem acessível); o que aparece é o que o Ultron decidiu e mediu."), 1)
    modo = QComboBox()
    modo.addItems(["automatico", "avancado", "privacidade", "local_only"])
    modo.setCurrentText(ajuste("inteligencia.modo_modelos", "automatico"))
    modo.currentTextChanged.connect(lambda m: definir("inteligencia.modo_modelos", m))
    sel = QCheckBox("seleção de ferramentas")
    sel.setChecked(bool(ajuste("inteligencia.selecao_ferramentas", True)))
    sel.toggled.connect(lambda on: definir("inteligencia.selecao_ferramentas", bool(on)))
    topo.addWidget(QLabel("modo dos modelos"))
    topo.addWidget(modo)
    topo.addWidget(sel)
    v.addLayout(topo)
    grade = QGridLayout()
    grade.setSpacing(12)
    status_m, status = hud.Moldura("cognitive status"), _texto()
    status_m.corpo.addWidget(status)
    mem_m, mem = hud.Moldura("memory intelligence"), _texto()
    mem_m.corpo.addWidget(mem)
    exe_m, exe = hud.Moldura("execution intelligence"), _texto()
    exe_m.corpo.addWidget(exe)
    apr_m = hud.Moldura("learning & evaluation")
    bench = tabela(["Conjunto", "Quando", "Ferramenta certa", "Tokens", "Intenção", "Recall@5"], 0)
    apr_m.corpo.addWidget(bench, 2)
    falhas = lista()
    apr_m.corpo.addWidget(falhas, 3)
    b = QHBoxLayout()
    estado_apr = aviso("")
    b.addWidget(botao("RODAR BENCHMARK", lambda: rodar_bench()))
    b.addWidget(botao("REFLEX: APRENDER AGORA", lambda: aprender()))
    b.addWidget(estado_apr, 1)
    apr_m.corpo.addLayout(b)
    mod_m = hud.Moldura("model intelligence")
    modelos = tabela(["Modelo", "Usos", "Sucesso", "p50"], 0)
    mod_m.corpo.addWidget(modelos)
    evo_m, evo = hud.Moldura("evolution"), _texto()
    evo_m.corpo.addWidget(evo)
    grade.addWidget(status_m, 0, 0)
    grade.addWidget(mem_m, 0, 1)
    grade.addWidget(exe_m, 0, 2)
    grade.addWidget(apr_m, 1, 0, 2, 2)          # aprendizado ocupa as duas linhas de baixo
    grade.addWidget(mod_m, 1, 2)
    grade.addWidget(evo_m, 2, 2)
    grade.setRowStretch(0, 2)
    grade.setRowStretch(1, 2)
    grade.setRowStretch(2, 1)
    bench.setMinimumHeight(130)
    from PySide6.QtWidgets import QHeaderView
    modelos.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    v.addLayout(grade, 1)

    def atualizar():
        if not w.isVisible():
            return
        u = _ultimo_pedido()
        if u:
            fontes = " · ".join(f"{k} {v}" for k, v in (u.get("fontes") or {}).items()) or "nenhuma"
            peso = f" (~{u['peso']} tokens)" if u.get("peso") else ""
            ms = f"{u['ms'] / 1000:.1f} s" if u.get("ms") else "—"
            status.setText(f"Último pedido ({u['quando'][11:19]}): {str(u['pedido'])[:120]}\n\n"
                           f"Intenção: {u.get('intencao', '—')} ({', '.join(u.get('sinais') or []) or '—'})\n"
                           f"Modelo: {u.get('modelo', '—')} · esforço {u.get('esforco') or '—'} · {ms}\n"
                           f"Motivo: {u.get('motivo', '—')}\n"
                           f"Contexto: {u.get('contexto', 0)} caracteres ({fontes})\n"
                           f"Ferramentas enviadas: {u.get('enviadas', '—')}{peso}\n"
                           f"Usadas: {', '.join(x for x in u['ferramentas_usadas'] if x) or 'nenhuma'}"
                           + (f"\nFalhas: {'; '.join(u['falhas'])}" if u["falhas"] else ""))
        else:
            status.setText("Nenhum pedido registrado ainda.")
        try:
            from neuralink import banco, ingestao, memoria
            c = banco.conexao()
            docs = c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
            ult = c.execute("SELECT quando, titulo FROM eventos ORDER BY quando DESC LIMIT 4").fetchall()
            sug = memoria.sugestoes()
            mem.setText(f"Fontes: {len(ingestao.fontes())} · documentos: {docs} · sem vetor: {ingestao.pendentes_vetor()}\n"
                        f"Conflitos/sugestões pendentes: {len(sug)} ({sum(s['tipo'] == 'contradicao' for s in sug)} contradições)\n\n"
                        "Últimas atualizações:\n" + "\n".join(f"  {r[0][5:16]} {r[1][:60]}" for r in ult))
        except Exception as e:
            mem.setText(f"NEURALINK indisponível: {e}")
        try:
            from modulos import claude_bridge, vector
            planos = [p for p in vector.listar(30) if p["estado"] in ("executando", "pausado", "interrompido")]
            cc = [t for t in claude_bridge.listar(10) if t["estado"] == "executando"]
            linhas = [f"Planos ativos: {len(planos)}"]
            for p in planos[:4]:
                det = vector.obter(p["id"])
                feitas = sum(e["estado"] == "feita" for e in det["etapas"])
                atual = next((e for e in det["etapas"] if e["estado"] not in ("feita", "pulada")), None)
                linhas.append(f"  {p['id']} [{p['estado']}] {feitas}/{len(det['etapas'])} · agora: "
                              f"{atual['descricao'][:50] if atual else '—'}")
            linhas.append(f"Claude Code executando: {len(cc)}")
            exe.setText("\n".join(linhas))
        except Exception as e:
            exe.setText(f"erro: {e}")
        preencher(bench, _benchmarks())
        try:
            from inteligencia import reflex, roteador
            falhas.clear()
            comp = reflex.comparar_periodos(7)
            pct = lambda x: f"{x['sucesso']:.0%} de {x['operacoes']} operações" if x["sucesso"] is not None else "sem dados"
            falhas.addItem(f"Sucesso: {pct(comp['atual'])} nesta semana · semana anterior: {pct(comp['anterior'])}")
            for f in reflex.falhas()[:20]:
                falhas.addItem(f"[{f['estado']}] {f['ferramenta']} {f['contagem']}x ({f['classe']}) · {f['hipotese']}"
                               + (f" · {f['evidencia_resolucao']}" if f["evidencia_resolucao"] else ""))
            for p in reflex.procedimentos()[:5]:
                falhas.addItem(f"[procedimento] {' → '.join(p['sequencia'])} · {p['sucessos']} sucessos")
            est = roteador.estatisticas()
            preencher(modelos, [(m, x["usos"], f"{x['sucesso']:.0%}" if x["sucesso"] is not None else "—",
                                 f"{x['latencia_ms_p50']} ms" if x["latencia_ms_p50"] else "—")
                                for m, x in sorted(est.items(), key=lambda kv: -kv[1]["usos"])])
        except Exception as e:
            falhas.addItem(f"erro: {e}")
        try:
            from evolucao import aprovacao, descoberta
            nec = [n for n in descoberta.necessidades() if n["estado"] == "aberta"]
            evo.setText(f"Aprovações pendentes: {len(aprovacao.pendentes())}\nNecessidades abertas: {len(nec)}\n"
                        + "\n".join(f"  » {n['descricao'][:70]}" for n in nec[:6]))
        except Exception as e:
            evo.setText(f"erro: {e}")

    def rodar_bench():
        import subprocess
        import sys
        estado_apr.setText("rodando o benchmark...")
        em_fundo(w, lambda: subprocess.run([sys.executable, "-m", "avaliacao.rodar"], cwd=RAIZ, capture_output=True,
                                           text=True, timeout=600).stdout,
                 lambda r: (estado_apr.setText(str(r).splitlines()[0] if r else "erro"), atualizar()))

    def aprender():
        from inteligencia import reflex
        em_fundo(w, reflex.aprender, lambda r: (estado_apr.setText(str(r)[:160]), atualizar()))

    t = QTimer(w)
    t.timeout.connect(atualizar)
    t.start(3000)
    w.showEvent = lambda e: atualizar()
    return w
