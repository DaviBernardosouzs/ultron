"""Capability Registry: inventário de tudo o que o Ultron sabe fazer.

Cada capacidade: nome, descrição, versão, origem, dependências, permissões e status.
Fontes: ferramentas do núcleo, plugins MCP, modos, extensões e skills instaladas.
O inventário é recalculado na hora (nada fica desatualizado) e salvo em
dados/evolucao/capacidades.json para o Evolution Center.
"""
import tomllib

import yaml

from core.config import RAIZ, ajuste
from evolucao.base import EXTENSOES, SKILLS, agora, tabela


def _versao_nucleo():
    try:
        return tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["version"]
    except Exception:
        return "?"


def _do_nucleo():
    from core import registro
    if not registro.todas():
        registro.carregar()
    v = _versao_nucleo()
    saida = []
    for f in registro.todas():
        if getattr(f, "extensao", None):
            continue
        modulo = f.funcao.__module__
        saida.append({
            "nome": f.nome, "descricao": f.descricao.split(". ")[0][:160], "versao": v,
            "origem": "núcleo" if modulo.startswith("ferramentas.") else modulo,
            "dependencias": [modulo], "permissoes": {"nivel": f.nivel},
            "status": "ok", "tipo": "ferramenta"})
    return saida


def _plugins():
    try:
        from core import plugins
        cfg = plugins.configuracao()
    except Exception:
        return []
    saida = []
    for nome, c in cfg.items():
        falta = plugins.faltando(c)
        saida.append({
            "nome": f"plugin:{nome}", "descricao": c.get("descricao", "")[:160],
            "versao": "externo", "origem": "plugin MCP (plugins.yaml)",
            "dependencias": [c.get("comando") or c.get("url", "")],
            "permissoes": {"nivel": c.get("nivel", "por ferramenta")},
            "status": "ok" if not falta else f"falta {', '.join(falta)}", "tipo": "plugin"})
    return saida


def _modos():
    return [{"nome": f"modo:{n}", "descricao": m.get("descricao", ""), "versao": "config",
             "origem": "config.yaml", "dependencias": sorted({p.get("acao") for p in m.get("passos", [])}),
             "permissoes": {"nivel": "N3" if any(p.get("acao") == "desligar" for p in m.get("passos", []))
                            else "N1"}, "status": "ok", "tipo": "modo"}
            for n, m in (ajuste("modos", {}) or {}).items()]


def _extensoes():
    from evolucao import extensoes
    saida = []
    for pasta in sorted(EXTENSOES.iterdir()):
        man = pasta / "manifest.yaml"
        if not man.exists():
            continue
        m = yaml.safe_load(man.read_text()) or {}
        estado = extensoes.estado(m.get("nome", pasta.name))
        saida.append({
            "nome": f"ext:{m.get('nome', pasta.name)}", "descricao": m.get("descricao", ""),
            "versao": m.get("versao", "?"), "origem": m.get("origem", "extensão"),
            "dependencias": m.get("dependencias", []),
            "permissoes": {**(m.get("permissoes") or {}), "nivel": estado.get("nivel", "N2")},
            "status": "ok" if estado.get("ativa", True) else "desativada", "tipo": "extensão",
            "ferramentas": [f["nome"] for f in m.get("ferramentas", [])]})
    return saida


def _skills():
    from evolucao import skills
    saida = []
    for s in skills.instaladas():
        saida.append({"nome": f"skill:{s['nome']}", "descricao": s["descricao"][:160],
                      "versao": s.get("versao", "1"), "origem": s.get("origem", "skill"),
                      "dependencias": [], "permissoes": {"nivel": "instrução (sem permissões)"},
                      "status": "ok", "tipo": "skill"})
    return saida


def inventario(salvar=True):
    itens = []
    for fonte in (_do_nucleo, _plugins, _modos, _extensoes, _skills):
        try:
            itens += fonte()
        except Exception as e:
            itens.append({"nome": f"erro:{fonte.__name__}", "descricao": str(e), "versao": "-",
                          "origem": "inventário", "dependencias": [], "permissoes": {},
                          "status": "falha", "tipo": "erro"})
    if salvar:
        with tabela("capacidades", {}) as d:
            d.clear()
            d.update({"atualizado": agora(), "itens": itens})
    return itens


def resumo():
    itens = inventario()
    por_tipo = {}
    for i in itens:
        por_tipo[i["tipo"]] = por_tipo.get(i["tipo"], 0) + 1
    falhas = [i["nome"] for i in itens if i["status"] not in ("ok",)]
    return por_tipo, falhas
