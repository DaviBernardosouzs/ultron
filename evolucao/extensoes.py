"""Extension Manager: carrega, ativa, desativa, atualiza, desinstala e faz rollback.

Uma extensão é uma pasta extensoes/<nome>/ com:
  manifest.yaml   nome, versao, descricao, origem, permissoes {rede, arquivos},
                  dependencias, ferramentas [{nome, descricao, parametros}]
  ferramenta.py   as funções (sem acesso ao Ultron)
  testes.py       funções teste_* com assert
As ferramentas viram ext_<nome> no Ultron, com o nível de confirmação decidido
pelo usuário na aprovação (padrão N2), e SEMPRE rodam no sandbox. Antes de carregar,
o hash da pasta é conferido com o aprovado: alteração depois da aprovação = não carrega.
"""
import logging
import shutil

import yaml

from evolucao import base
from evolucao.base import EXTENSOES, VERSOES, agora, hash_pasta, registrar, tabela

LOG = logging.getLogger("ultron.evolucao")


def estados():
    return base.ler("extensoes", {})


def estado(nome):
    return estados().get(nome, {})


def manifesto(pasta):
    return yaml.safe_load((pasta / "manifest.yaml").read_text(encoding="utf-8")) or {}


def carregar():
    """Registra as ferramentas das extensões ativas. Devolve (carregadas, recusadas)."""
    from core import registro
    from evolucao import sandbox
    ok, recusadas = [], []
    for nome, est in estados().items():
        pasta = EXTENSOES / nome
        if not est.get("ativa") or not pasta.exists():
            continue
        if hash_pasta(pasta) != est.get("hash"):
            recusadas.append(f"{nome} (alterada depois da aprovação)")
            registrar("extensao_recusada", nome=nome, resumo="hash diferente do aprovado")
            continue
        m = manifesto(pasta)
        perms = m.get("permissoes") or {}
        nivel = est.get("nivel", "N2")
        for f in m.get("ferramentas", []):
            nome_tool = f"ext_{f['nome']}"
            if registro.obter(nome_tool):
                recusadas.append(f"{nome_tool} (nome já existe)")
                continue

            def chamar(_f=f["nome"], _pasta=pasta, _nome=nome, _perms=perms, **args):
                return sandbox.chamar_extensao(_pasta, _nome, _f, args, _perms)

            registro.ferramenta(
                nome_tool, f"[extensão {nome} v{m.get('versao')}] {f.get('descricao', '')}",
                f.get("parametros") or {"type": "object", "properties": {}},
                nivel=nivel,
                resumo=lambda a, _n=nome_tool: f"usar a extensão {_n} com {a}")(chamar)
            registro.obter(nome_tool).extensao = nome
            ok.append(nome_tool)
    return ok, recusadas


def instalar(pasta_candidato, nome, versao, hash_aprovado, nivel, origem):
    """Só chamado pelo Approval Gateway, depois da aprovação do usuário."""
    if hash_pasta(pasta_candidato) != hash_aprovado:
        raise RuntimeError("o candidato mudou depois de testado; teste de novo antes de aprovar.")
    destino_versao = VERSOES / nome / versao
    if destino_versao.exists():
        shutil.rmtree(destino_versao)
    shutil.copytree(pasta_candidato, destino_versao, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    anterior = estado(nome)
    tmp = EXTENSOES / f".{nome}.novo"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(destino_versao, tmp)
    if (EXTENSOES / nome).exists():
        shutil.rmtree(EXTENSOES / nome)
    tmp.rename(EXTENSOES / nome)
    with tabela("extensoes", {}) as d:
        d[nome] = {"ativa": True, "versao": versao, "hash": hash_pasta(EXTENSOES / nome),
                   "nivel": nivel, "origem": origem, "instalada_em": agora(),
                   "anterior": anterior.get("versao") if anterior else None}
    registrar("extensao_ativada", nome=nome, versao=versao, resumo=f"nível {nivel}",
              rollback=f"ultron evolucao rollback {nome}")


def desativar(nome):
    with tabela("extensoes", {}) as d:
        if nome not in d:
            raise KeyError(nome)
        d[nome]["ativa"] = False
    registrar("extensao_desativada", nome=nome)


def reativar(nome):
    with tabela("extensoes", {}) as d:
        if nome not in d:
            raise KeyError(nome)
        if hash_pasta(EXTENSOES / nome) != d[nome]["hash"]:
            raise RuntimeError("os arquivos mudaram desde a aprovação; não reativo.")
        d[nome]["ativa"] = True
    registrar("extensao_reativada", nome=nome)


def versoes(nome):
    pasta = VERSOES / nome
    return sorted((p.name for p in pasta.iterdir()), key=_chave_versao) if pasta.exists() else []


def _chave_versao(v):
    return [int(x) if x.isdigit() else x for x in v.replace("-", ".").split(".")]


def rollback(nome, versao=None):
    """Volta para a versão anterior (ou a indicada), já aprovada e guardada."""
    est = estado(nome)
    alvo = versao or est.get("anterior")
    if not alvo:
        raise RuntimeError(f"{nome} não tem versão anterior; use desativar.")
    origem = VERSOES / nome / alvo
    if not origem.exists():
        raise RuntimeError(f"versão {alvo} de {nome} não está guardada.")
    shutil.rmtree(EXTENSOES / nome, ignore_errors=True)
    shutil.copytree(origem, EXTENSOES / nome)
    with tabela("extensoes", {}) as d:
        d[nome].update(versao=alvo, hash=hash_pasta(EXTENSOES / nome), ativa=True,
                       anterior=est.get("versao"))
    registrar("rollback", nome=nome, versao=alvo, resumo=f"de {est.get('versao')} para {alvo}")


def desinstalar(nome):
    shutil.rmtree(EXTENSOES / nome, ignore_errors=True)
    with tabela("extensoes", {}) as d:
        d.pop(nome, None)
    registrar("extensao_desinstalada", nome=nome, resumo="versões antigas continuam em dados/evolucao/versoes")
