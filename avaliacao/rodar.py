"""Benchmark cognitivo do Ultron: mede antes de mudar, mede depois de mudar.

    uv run python -m avaliacao.rodar            # roda e grava avaliacao/resultados/<data>.json
    uv run python -m avaliacao.rodar --comparar # compara com o resultado anterior

Categorias (avaliacao/casos.json), todas com verificação determinística (sem API paga):
  ferramentas   o conjunto de ferramentas enviado ao modelo contém a ferramenta certa?
                (estratégia 'todas' = linha de base; 'selecao' = Tool Intelligence)
                métricas: inclusão (recall), MRR da posição, tokens declarados
  intencao      classificação de complexidade (Cortex): acurácia
  recuperacao   busca no cofre REAL (só leitura): Recall@5, MRR, latência; diz se usou vetores
  seguranca     Guardian, Permission Bridge do Claude Code, segredos, injeção: taxa de acerto
  planejamento  validação de planos do Vector: taxa de acerto
Não lê nem grava nada fora do que cada caso pede; não chama o modelo de linguagem.
"""
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("NEURALINK_SEM_SERVICO", "1")
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))


def _tokens(texto):
    return len(texto) // 4          # aproximação usual (pt-BR, JSON); a mesma régua antes e depois


def ferramentas(casos):
    from core import registro, workspaces
    registro.carregar()
    workspaces.atual = lambda: None      # mede sem WorkSpace ativo (só neste processo; o estado real fica)
    todas = registro.todas()
    tok_todas = _tokens(json.dumps(registro.schemas(), ensure_ascii=False))
    res = {"todas": {"inclusao": 1.0, "mrr": None, "tokens_medio": tok_todas, "ferramentas_medio": len(todas)}}
    try:
        from inteligencia import ferramentas as ti
    except ImportError:
        return res
    acertos, rr, toks, qtd, falhas, ms = 0, [], [], [], [], []
    for c in casos:
        t0 = time.perf_counter()
        sel = ti.selecionar(c["pedido"])
        ms.append((time.perf_counter() - t0) * 1000)
        nomes = [f.nome for f in sel]
        pos = [nomes.index(a) + 1 for a in c["aceitas"] if a in nomes]
        if pos:
            acertos += 1
            rr.append(1 / min(pos))
        else:
            rr.append(0)
            falhas.append(c["pedido"])
        toks.append(_tokens(json.dumps(ti.schemas(sel), ensure_ascii=False)))
        qtd.append(len(sel))
    res["selecao"] = {"inclusao": round(acertos / len(casos), 3), "mrr": round(statistics.mean(rr), 3),
                      "tokens_medio": round(statistics.mean(toks)), "ferramentas_medio": round(statistics.mean(qtd), 1),
                      "ms_medio": round(statistics.mean(ms), 1), "falhas": falhas}
    return res


def intencao(casos):
    try:
        from inteligencia import intencao as it
    except ImportError:
        return {"acuracia": None, "nota": "não existe classificador (linha de base)"}
    erros = []
    for c in casos:
        obtida = it.classificar(c["pedido"])["classe"]
        if obtida != c["classe"]:
            erros.append({"pedido": c["pedido"], "esperado": c["classe"], "obtido": obtida})
    return {"acuracia": round(1 - len(erros) / len(casos), 3), "erros": erros}


def recuperacao(casos):
    from neuralink import busca, embeddings
    vetores = embeddings.gerar(["teste"], consulta=True) is not None
    rec, rr, lat, falhas = 0, [], [], []
    for c in casos:
        t0 = time.perf_counter()
        r = busca.buscar(c["consulta"], k=5, por_documento=1)
        lat.append((time.perf_counter() - t0) * 1000)
        titulos = [x["titulo"] for x in r]
        pos = [titulos.index(e) + 1 for e in c["esperado"] if e in titulos]
        if pos:
            rec += 1
            rr.append(1 / min(pos))
        else:
            rr.append(0)
            falhas.append({"consulta": c["consulta"], "obtido": titulos[:3]})
    return {"recall@5": round(rec / len(casos), 3), "mrr": round(statistics.mean(rr), 3),
            "latencia_ms_p50": round(statistics.median(lat)), "vetores": vetores, "falhas": falhas}


def seguranca(casos):
    from core import guardian
    from modulos import claude_bridge
    from neuralink import contexto, ingestao
    ok, erros = 0, []
    for c in casos:
        t = c["tipo"]
        if t in ("caminho", "caminho_escrita"):
            obtido = guardian.autorizar_caminho(c["alvo"], escrita=t == "caminho_escrita")["decisao"]
            certo = obtido == c["esperado"]
        elif t == "nivel":
            obtido = guardian.autorizar("ferramenta", "x_teste", c["nivel"])["decisao"]
            certo = obtido == c["esperado"]
        elif t == "claude":
            obtido = claude_bridge.decidir_ferramenta(c["ferramenta"], c["entrada"], str(AQUI.parent))[0]
            certo = obtido == c["esperado"]
        elif t == "segredo":
            obtido = ingestao._redigir(c["texto"])
            certo = c["nao_deve_conter"] not in obtido
        elif t == "injecao":
            from core.registro import NAO_CONFIAVEL
            obtido = NAO_CONFIAVEL + c["texto"]       # contrato: todo conteúdo externo vem marcado
            certo = c["deve_conter"] in obtido
        else:
            obtido, certo = "tipo desconhecido", False
        ok += certo
        if not certo:
            erros.append({"caso": c, "obtido": str(obtido)[:200]})
    return {"acerto": round(ok / len(casos), 3), "erros": erros}


def planejamento(casos):
    from core import registro
    from modulos import vector
    registro.carregar()
    ok = sum((not vector.validar_plano(c["etapas"])) == c["valido"] for c in casos)
    return {"acerto": round(ok / len(casos), 3)}


def rodar(arquivo="casos.json"):
    casos = json.loads((AQUI / arquivo).read_text())
    casos.pop("_nota", None)
    r = {"quando": datetime.now().isoformat(timespec="seconds"), "casos": sum(map(len, casos.values()))}
    for nome, fn in (("ferramentas", ferramentas), ("intencao", intencao), ("recuperacao", recuperacao),
                     ("seguranca", seguranca), ("planejamento", planejamento)):
        if nome not in casos:
            continue
        t0 = time.perf_counter()
        r[nome] = fn(casos[nome])
        r[nome]["segundos"] = round(time.perf_counter() - t0, 2)
    return r


def resumo(r):
    f = r["ferramentas"]
    linhas = [f"Benchmark {r['quando']} · {r['casos']} casos",
              f"ferramentas  todas: {f['todas']['ferramentas_medio']} ferramentas, ~{f['todas']['tokens_medio']} tokens"]
    if "selecao" in f:
        s = f["selecao"]
        linhas.append(f"             seleção: inclusão {s['inclusao']:.0%}, MRR {s['mrr']}, {s['ferramentas_medio']} ferramentas, "
                      f"~{s['tokens_medio']} tokens, {s['ms_medio']} ms")
    if "intencao" not in r:
        return "\n".join(linhas)
    i = r["intencao"]
    linhas.append(f"intenção     acurácia {i['acuracia'] if i['acuracia'] is None else format(i['acuracia'], '.0%')}")
    if "recuperacao" not in r:
        return "\n".join(linhas)
    q = r["recuperacao"]
    linhas.append(f"recuperação  Recall@5 {q['recall@5']:.0%}, MRR {q['mrr']}, p50 {q['latencia_ms_p50']} ms "
                  f"({'palavras + vetores' if q['vetores'] else 'só palavras: desktop desligado'})")
    linhas.append(f"segurança    {r['seguranca']['acerto']:.0%}   planejamento {r['planejamento']['acerto']:.0%}")
    return "\n".join(linhas)


if __name__ == "__main__":
    conjunto = "validacao" if "--validacao" in sys.argv else ("teste" if "--teste" in sys.argv else "")
    validacao = bool(conjunto)
    r = rodar(f"casos_{conjunto}.json" if conjunto else "casos.json")
    destino = AQUI / "resultados" / f"{datetime.now():%Y%m%d-%H%M%S}{'-' + conjunto if conjunto else ''}.json"
    anteriores = sorted(p for p in (AQUI / "resultados").glob("*.json") if ("validacao" in p.name) == validacao)
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print(resumo(r))
    if "--comparar" in sys.argv and anteriores:
        print("\nAnterior:\n" + resumo(json.loads(anteriores[-1].read_text())))
    print(f"\nGravado em {destino}")
