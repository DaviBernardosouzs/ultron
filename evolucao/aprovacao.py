"""Approval Gateway: nada é instalado, ativado ou ganha permissão sem o usuário.

- Só candidatos APROVADOS na avaliação viram pedido de aprovação.
- O pedido guarda o hash do que foi testado; na aprovação o hash é conferido de
  novo (se o código mudou, não instala).
- Aprovar/rejeitar/rollback NÃO são ferramentas do modelo: só a CLI
  (`ultron evolucao ...`) e o Evolution Center chamam estas funções.
- Novas ferramentas entram com nível N2 (pedem confirmação), a não ser que o
  usuário escolha outro nível ao aprovar.
"""
import shutil

import yaml

from evolucao import avaliacao, extensoes, skills
from evolucao.base import (EXTENSOES, PASTA, _tarefa, agora, hash_pasta, novo_id, registrar,
                           tabela)
from core.config import RAIZ


class AprovacaoNegada(Exception):
    pass


def solicitar(resultado, pasta, resumo=""):
    if not resultado.get("aprovado"):
        raise AprovacaoNegada("a avaliação reprovou; corrija antes de pedir aprovação: "
                              + "; ".join(resultado.get("motivos", []))[:400])
    pid = novo_id("A")
    with tabela("aprovacoes") as d:
        for p in d:   # um pedido pendente por candidato
            if p["candidato"] == resultado["candidato"] and p["estado"] == "pendente":
                p["estado"] = "substituido"
        d.append({"id": pid, "tipo": resultado["tipo"], "nome": resultado["nome"],
                  "versao": resultado.get("versao"), "candidato": resultado["candidato"],
                  "pasta": str(pasta), "hash": resultado["hash"],
                  "permissoes": resultado.get("permissoes", {}), "nivel_sugerido": "N2",
                  "resumo": resumo, "relatorio": avaliacao.relatorio(resultado),
                  "criado": agora(), "estado": "pendente"})
    registrar("aprovacao_solicitada", nome=resultado["nome"], versao=resultado.get("versao"),
              resumo=f"pedido {pid}")
    _avisar(f"🧬 Ultron pede aprovação: {resultado['tipo']} {resultado['nome']} "
            f"v{resultado.get('versao')} (pedido {pid}). Veja no Evolution Center ou rode "
            f"`ultron evolucao pendentes`.")
    return pid


def _avisar(texto):
    try:
        from core.telegram import Telegram
        Telegram().enviar(texto)
    except Exception:
        pass


def pendentes():
    return [p for p in listar() if p["estado"] == "pendente"]


def listar():
    from evolucao.base import ler
    return ler("aprovacoes")


def _pedido(pid):
    for p in listar():
        if p["id"] == pid:
            return p
    raise KeyError(f"pedido {pid} não existe")


def aprovar(pid, nivel="N2", por="usuário"):
    """Aprovação humana explícita. nivel: N1 (sem confirmação), N2 ou N3."""
    if getattr(_tarefa, "ativa", False):
        raise AprovacaoNegada("aprovação não pode acontecer dentro de uma tarefa de evolução")
    if nivel not in ("N1", "N2", "N3"):
        raise ValueError("nível deve ser N1, N2 ou N3")
    p = _pedido(pid)
    if p["estado"] != "pendente":
        raise AprovacaoNegada(f"pedido {pid} está {p['estado']}")
    from pathlib import Path
    pasta = Path(p["pasta"])
    if hash_pasta(pasta) != p["hash"]:
        raise AprovacaoNegada("o candidato mudou depois de testado; rode a avaliação de novo")
    if p["tipo"] == "extensão":
        extensoes.instalar(pasta, p["nome"], p["versao"], p["hash"], nivel, origem=f"aprovado por {por}")
    elif p["tipo"] == "skill":
        skills.instalar(pasta, p["hash"])
    elif p["tipo"] in ("mcp", "mcp-ts"):
        _instalar_mcp(p, pasta, nivel)
    else:
        raise AprovacaoNegada(f"tipo desconhecido {p['tipo']}")
    _mudar(pid, "aprovado", por=por, nivel=nivel)
    registrar("aprovado", nome=p["nome"], versao=p.get("versao"), resumo=f"por {por}, nível {nivel}")
    return p


def rejeitar(pid, motivo="", por="usuário"):
    p = _pedido(pid)
    _mudar(pid, "rejeitado", por=por, motivo=motivo)
    registrar("rejeitado", nome=p["nome"], versao=p.get("versao"), resumo=motivo)


def _mudar(pid, estado, **extra):
    with tabela("aprovacoes") as d:
        for p in d:
            if p["id"] == pid:
                p.update(estado=estado, decidido=agora(), **extra)


def _instalar_mcp(p, pasta, nivel):
    """Adiciona o plugin ao plugins.yaml (com backup) preservando comentários."""
    from ruamel.yaml import YAML
    arq = RAIZ / "plugins.yaml"
    backup = PASTA / "versoes" / f"plugins.yaml.{agora().replace(':', '')}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(arq, backup)
    ry = YAML()
    dados = ry.load(arq.read_text(encoding="utf-8")) or {}
    if p["tipo"] == "mcp":
        cfg = yaml.safe_load((pasta / "plugin.yaml").read_text())["config"]
    else:
        # servidor próprio: copia, compila no sandbox e roda SEMPRE dentro do bwrap
        from evolucao import sandbox
        destino = EXTENSOES / f"mcp-{p['nome']}"
        shutil.rmtree(destino, ignore_errors=True)
        shutil.copytree(pasta, destino)
        r = sandbox.rodar(destino, ["/usr/bin/bash", "-c", "cp -r /codigo/. /dados/ && cd /dados && "
                                    "npm install --no-audit --no-fund --silent && npx tsc"],
                          rede=True, gravavel=destino, tempo=300)
        if r["codigo"] != 0:
            raise AprovacaoNegada(f"falhou ao compilar: {r['erro'][-300:]}")
        argv = sandbox.comando(destino, ["/usr/bin/node", "/codigo/dist/index.js"])
        cfg = {"descricao": f"(gerado pelo Ultron) {p.get('resumo') or p['nome']}",
               "comando": argv[0], "args": argv[1:]}
    cfg["nivel"] = nivel
    dados[p["nome"]] = cfg
    with arq.open("w", encoding="utf-8") as f:
        ry.dump(dados, f)
    registrar("mcp_instalado", nome=p["nome"], resumo=f"backup em {backup.name}",
              rollback=f"restaurar {backup}")
