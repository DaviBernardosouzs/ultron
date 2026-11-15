"""Base do motor de evolução: caminhos, armazenamento, histórico e limites.

Regras que valem para todo o pacote (e que nada criado pelo Ultron pode mudar):
- Código candidato só é escrito em dados/evolucao/candidatos/. Nada do Ultron
  escreve em core/, ferramentas/, evolucao/ ou ultron.py.
- Só o usuário aprova e ativa (CLI ou Evolution Center); nenhuma ferramenta do
  modelo faz isso.
- Toda etapa vai para o histórico (dados/evolucao/historico.jsonl) e para a
  auditoria geral.
"""
import contextlib
import fcntl
import hashlib
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from core import auditoria
from core.config import DADOS, RAIZ, ajuste

PASTA = DADOS / "evolucao"
CANDIDATOS = PASTA / "candidatos"
VERSOES = PASTA / "versoes"
ARQUIVOS_EXT = PASTA / "arquivos"      # única pasta gravável pelas extensões
EXTENSOES = RAIZ / "extensoes"         # extensões ativas (instaladas após aprovação)
SKILLS = RAIZ / "skills"               # skills ativas
for _p in (PASTA, CANDIDATOS, VERSOES, ARQUIVOS_EXT, EXTENSOES, SKILLS):
    _p.mkdir(parents=True, exist_ok=True)

# O núcleo: nada gerado pelo Ultron pode tocar nestes caminhos.
PROTEGIDOS = [RAIZ / "core", RAIZ / "ferramentas", RAIZ / "evolucao", RAIZ / "ultron.py",
              RAIZ / "ultron", RAIZ / ".env", RAIZ / "pyproject.toml"]

NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
SKILL_VALIDA = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def limite(chave, padrao):
    return ajuste(f"evolucao.{chave}", padrao)


def agora():
    return datetime.now().isoformat(timespec="seconds")


def protegido(caminho):
    p = Path(caminho).resolve()
    return any(p == x.resolve() or x.resolve() in p.parents for x in PROTEGIDOS)


# ------------------------------------------------------------------ armazenamento JSON

@contextlib.contextmanager
def tabela(nome, padrao=None):
    """Lê e grava dados/evolucao/<nome>.json com trava entre processos."""
    arq = PASTA / f"{nome}.json"
    with open(PASTA / f".{nome}.lock", "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else (
            padrao if padrao is not None else [])
        yield dados
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(arq)


def ler(nome, padrao=None):
    arq = PASTA / f"{nome}.json"
    if not arq.exists():
        return padrao if padrao is not None else []
    return json.loads(arq.read_text(encoding="utf-8"))


def novo_id(prefixo):
    return f"{prefixo}{int(time.time() * 1000) % 10**9:09d}"


# ------------------------------------------------------------------ histórico (memória da evolução)

def registrar(evento, **campos):
    """Histórico da evolução + auditoria geral + nota no cofre do Obsidian."""
    linha = {"quando": agora(), "evento": evento, **campos}
    with open(PASTA / "historico.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    auditoria.registrar(f"evolucao_{evento}", **{k: v for k, v in campos.items() if k != "relatorio"})
    try:
        _nota_cofre(linha)
    except Exception:
        pass


def historico(n=200):
    arq = PASTA / "historico.jsonl"
    if not arq.exists():
        return []
    linhas = arq.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(l) for l in linhas if l.strip()]


def _nota_cofre(linha):
    from core import cofre
    pasta = cofre.raiz() / "Evolução"
    pasta.mkdir(parents=True, exist_ok=True)
    dia = linha["quando"][:10]
    arq = pasta / f"{dia}.md"
    if not arq.exists():
        arq.write_text(f"---\ntipo: evolucao\ntags: [ultron/evolucao]\n---\n# Evolução em {dia}\n\n"
                       "Registro das melhorias do [[Ultron]] (necessidades, testes, aprovações).\n\n",
                       encoding="utf-8")
    alvo = linha.get("nome") or linha.get("descricao") or ""
    with arq.open("a", encoding="utf-8") as f:
        f.write(f"- {linha['quando'][11:16]} **{linha['evento']}** {alvo}"
                + (f" (v{linha['versao']})" if linha.get("versao") else "")
                + (f": {linha['resumo']}" if linha.get("resumo") else "") + "\n")


# ------------------------------------------------------------------ integridade

def hash_pasta(pasta):
    """Hash de todo o conteúdo de uma pasta (o que foi testado é o que será ativado)."""
    h = hashlib.sha256()
    for arq in sorted(Path(pasta).rglob("*")):
        if arq.is_file() and "__pycache__" not in arq.parts and not arq.name.startswith("."):
            h.update(str(arq.relative_to(pasta)).encode())
            h.update(arq.read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------ limites e anti-recursão

_tarefa = threading.local()
_ocupado = threading.Lock()


class LimiteExcedido(Exception):
    pass


@contextlib.contextmanager
def tarefa(nome):
    """Uma tarefa de evolução por vez, com limite diário; impede ciclos recursivos."""
    if getattr(_tarefa, "ativa", False) or not _ocupado.acquire(blocking=False):
        raise LimiteExcedido("já há uma tarefa de evolução em andamento; uma de cada vez.")
    try:
        hoje = agora()[:10]
        feitas = sum(1 for e in historico(500) if e["evento"] == "tarefa_iniciada"
                     and e["quando"].startswith(hoje))
        if feitas >= int(limite("max_tarefas_dia", 8)):
            raise LimiteExcedido(f"limite de {feitas} tarefas de evolução por dia atingido.")
        _tarefa.ativa = True
        _tarefa.inicio = time.time()
        registrar("tarefa_iniciada", nome=nome)
        yield
    finally:
        _tarefa.ativa = False
        _ocupado.release()


def tempo_restante():
    inicio = getattr(_tarefa, "inicio", time.time())
    return int(limite("tempo_max_tarefa", 600)) - (time.time() - inicio)


def animar(estado):
    """Mostra a etapa na animação (terminal, modo ambiente e Evolution Center)."""
    try:
        from core import animacao
        animacao.estado(estado)
    except Exception:
        pass
    try:
        (PASTA / "etapa.json").write_text(json.dumps({"estado": estado, "quando": time.time()}))
    except Exception:
        pass
