"""Evaluation Engine: cenários padronizados e comparação entre versões.

Para uma extensão candidata:
  1. manifesto válido e código aprovado na checagem estática;
  2. testes.py da nova versão no sandbox (todos precisam passar, mínimo 3);
  3. cenários do manifesto (chamadas reais à ferramenta no sandbox);
  4. regressão: os testes da versão ATIVA rodam contra o código novo;
  5. comparação de desempenho (tempo médio) antes x depois.
Qualquer falha reprova, e reprovado não pode ser enviado para aprovação.

O resultado fica em dados/evolucao/avaliacoes/<candidato>.json com o hash exato do
que foi testado. Promptfoo: não integrado por enquanto (exigiria Node e chaves de
API para avaliar respostas do modelo); os testes aqui são determinísticos.
"""
import json
import shutil
import statistics
import tempfile
from pathlib import Path

import yaml

from evolucao import fabrica, sandbox, skills
from evolucao.base import EXTENSOES, PASTA, agora, animar, hash_pasta, registrar

AVALIACOES = PASTA / "avaliacoes"
AVALIACOES.mkdir(exist_ok=True)
MIN_TESTES = 3


def _rodar_testes(pasta):
    r = sandbox.python(pasta, "testar", {})
    res = r.get("resultado") or {}
    if not res.get("ok"):
        return {"ok": False, "erro": res.get("erro") or r["erro"][-800:], "resultados": []}
    rs = res["resultados"]
    return {"ok": all(x["ok"] for x in rs) and bool(rs), "resultados": rs,
            "passaram": sum(x["ok"] for x in rs), "total": len(rs),
            "ms_medio": round(statistics.mean(x["ms"] for x in rs), 2) if rs else None,
            "segundos": r["segundos"]}


def _cenarios(pasta, man):
    saida = []
    perms = man.get("permissoes") or {}
    for c in man.get("cenarios") or []:
        r = sandbox.python(pasta, "chamar", {"funcao": c["ferramenta"], "argumentos": c.get("argumentos", {})},
                           rede=bool(perms.get("rede")))
        res = r.get("resultado") or {}
        valor = json.dumps(res.get("valor"), ensure_ascii=False) if res.get("ok") else ""
        esperado = str(c.get("espera_contem", ""))
        ok = bool(res.get("ok")) and (esperado.lower() in valor.lower())
        saida.append({"cenario": f"{c['ferramenta']}({c.get('argumentos')})", "ok": ok,
                      "obtido": valor[:300] or res.get("erro"), "esperado": esperado,
                      "segundos": r["segundos"]})
    return saida


def avaliar_extensao(pasta):
    pasta = Path(pasta)
    animar("testando")
    man = yaml.safe_load((pasta / "manifest.yaml").read_text())
    motivos = list(fabrica.validar_manifesto(man))
    for arq in ("ferramenta.py", "testes.py"):
        motivos += [f"{arq}: {p}" for p in fabrica.verificar_codigo((pasta / arq).read_text(),
                                                                   man.get("permissoes"))]
    novo = _rodar_testes(pasta)
    if not novo["ok"]:
        motivos.append("testes da nova versão falharam")
    if novo.get("total", 0) < MIN_TESTES:
        motivos.append(f"menos de {MIN_TESTES} testes")
    cen = _cenarios(pasta, man)
    motivos += [f"cenário falhou: {c['cenario']}" for c in cen if not c["ok"]]

    # Regressão e comparação com a versão ativa
    regressao, antes = None, None
    ativa = EXTENSOES / man["nome"]
    if ativa.exists():
        antiga = yaml.safe_load((ativa / "manifest.yaml").read_text())
        if [int(x) for x in man["versao"].split(".")] <= [int(x) for x in antiga["versao"].split(".")]:
            motivos.append(f"versão {man['versao']} não é maior que a ativa {antiga['versao']}")
        antes = _rodar_testes(ativa)
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(pasta / "ferramenta.py", tmp)
            shutil.copy(ativa / "testes.py", tmp)
            regressao = _rodar_testes(Path(tmp))
        if not regressao["ok"]:
            motivos.append("regressão: o código novo quebra testes da versão ativa")
    resultado = {
        "candidato": pasta.name, "tipo": "extensão", "nome": man["nome"], "versao": man["versao"],
        "hash": hash_pasta(pasta), "quando": agora(), "aprovado": not motivos, "motivos": motivos,
        "testes": novo, "cenarios": cen, "regressao": regressao,
        "comparacao": {"antes_ms": antes.get("ms_medio") if antes else None,
                       "depois_ms": novo.get("ms_medio"),
                       "antes_passaram": f"{antes['passaram']}/{antes['total']}" if antes and antes.get("total") else None,
                       "depois_passaram": f"{novo.get('passaram', 0)}/{novo.get('total', 0)}"},
        "permissoes": man.get("permissoes") or {}}
    _salvar(resultado)
    return resultado


def avaliar_skill(pasta):
    pasta = Path(pasta)
    animar("testando")
    motivos = skills.validar(pasta)
    meta, corpo = skills._ler(pasta / "SKILL.md") if (pasta / "SKILL.md").exists() else ({}, "")
    resultado = {"candidato": pasta.name, "tipo": "skill", "nome": (meta or {}).get("name"),
                 "versao": str(((meta or {}).get("metadata") or {}).get("versao", "1")),
                 "hash": hash_pasta(pasta), "quando": agora(), "aprovado": not motivos,
                 "motivos": motivos, "testes": {"total": 1, "passaram": int(not motivos)},
                 "permissoes": {}}
    _salvar(resultado)
    return resultado


def avaliar_mcp(pasta):
    pasta = Path(pasta)
    animar("testando")
    if (pasta / "package.json").exists():
        teste = fabrica.compilar_testar_mcp_ts(pasta)
        nome, tipo = pasta.name.removeprefix("mcpts-"), "mcp-ts"
    else:
        teste = fabrica.testar_plugin_mcp(pasta)
        nome, tipo = pasta.name.removeprefix("mcp-"), "mcp"
    motivos = [] if teste.get("ok") or teste.get("ok") is None else [f"servidor não respondeu: {teste.get('erro', '')[:300]}"]
    if teste.get("ok") and not teste.get("ferramentas"):
        motivos.append("o servidor não expõe nenhuma ferramenta")
    resultado = {"candidato": pasta.name, "tipo": tipo, "nome": nome, "versao": "1.0.0",
                 "hash": hash_pasta(pasta), "quando": agora(), "aprovado": not motivos,
                 "motivos": motivos, "testes": teste, "permissoes": {"rede": True}}
    _salvar(resultado)
    return resultado


def _salvar(r):
    (AVALIACOES / f"{r['candidato']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    registrar("avaliacao", nome=r["nome"], versao=r.get("versao"),
              resumo=("aprovada" if r["aprovado"] else "reprovada: " + "; ".join(r["motivos"])[:200]))
    animar("melhoria concluída" if r["aprovado"] else "pensando")


def ultima(candidato):
    arq = AVALIACOES / f"{candidato}.json"
    return json.loads(arq.read_text()) if arq.exists() else None


def todas():
    return sorted((json.loads(a.read_text()) for a in AVALIACOES.glob("*.json")),
                  key=lambda x: x["quando"], reverse=True)


def relatorio(r):
    """Texto legível do resultado, para o pedido de aprovação."""
    linhas = [f"# {r['tipo']} {r['nome']} v{r.get('versao')}",
              f"Resultado: {'APROVADA nos testes' if r['aprovado'] else 'REPROVADA'}"]
    t = r.get("testes") or {}
    if "total" in t:
        linhas.append(f"Testes: {t.get('passaram')}/{t.get('total')} passaram"
                      + (f", {t['ms_medio']} ms em média" if t.get("ms_medio") is not None else ""))
    for c in r.get("cenarios") or []:
        linhas.append(f"Cenário {'ok' if c['ok'] else 'FALHOU'}: {c['cenario']} -> {c['obtido']}")
    comp = r.get("comparacao") or {}
    if comp.get("antes_passaram"):
        linhas.append(f"Comparação: antes {comp['antes_passaram']} ({comp['antes_ms']} ms), "
                      f"depois {comp['depois_passaram']} ({comp['depois_ms']} ms)")
    if r.get("regressao"):
        linhas.append(f"Regressão (testes antigos no código novo): "
                      f"{r['regressao'].get('passaram')}/{r['regressao'].get('total')}")
    if r.get("permissoes"):
        linhas.append(f"Permissões pedidas: {r['permissoes']}")
    for m in r.get("motivos") or []:
        linhas.append(f"- {m}")
    return "\n".join(linhas)
