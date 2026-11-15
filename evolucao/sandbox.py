"""Sandbox Runner: executa código candidato isolado com bubblewrap.

Dentro do sandbox:
- só existem /usr, o Python do uv e o .venv (somente leitura) e a pasta do código;
- sem rede (a não ser que o manifesto peça 'rede' e o usuário aprove);
- variáveis de ambiente zeradas: nenhum .env, chave SSH, token ou cookie entra;
- /tmp vazio, sem acesso à pasta pessoal; processos morrem com o pai;
- limites de CPU, memória, processos e tempo.
"""
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.config import RAIZ
from evolucao.base import ARQUIVOS_EXT, limite

PYTHON_UV = Path.home() / ".local/share/uv/python"
VENV = RAIZ / ".venv"
EXECUTOR = Path(__file__).with_name("executor.py")


class SandboxIndisponivel(RuntimeError):
    pass


def disponivel():
    return bool(shutil.which("bwrap"))


def _limites(cpu, memoria_mb):
    def aplicar():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 2**20, 50 * 2**20))
        os.setsid()
    return aplicar


def comando(pasta_codigo, argv, rede=False, gravavel=None, extra_ro=()):
    """Monta a linha do bwrap. pasta_codigo fica em /codigo (somente leitura)."""
    if not disponivel():
        raise SandboxIndisponivel("bubblewrap (bwrap) não instalado: sudo pacman -S bubblewrap")
    cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
           "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
           "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
           "--ro-bind", str(PYTHON_UV), str(PYTHON_UV), "--ro-bind", str(VENV), str(VENV),
           "--ro-bind", str(pasta_codigo), "/codigo",
           "--ro-bind", str(EXECUTOR), "/sandbox/executor.py",
           "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp",
           "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "LANG", "C.UTF-8",
           "--chdir", "/tmp"]
    for origem, destino in extra_ro:
        cmd += ["--ro-bind", str(origem), destino]
    if rede:
        cmd += ["--share-net"]
        for f in ("/etc/resolv.conf", "/etc/hosts", "/etc/ssl", "/etc/ca-certificates",
                  "/etc/nsswitch.conf"):
            if os.path.exists(f):
                cmd += ["--ro-bind", f, f]
    if gravavel:
        Path(gravavel).mkdir(parents=True, exist_ok=True)
        cmd += ["--bind", str(gravavel), "/dados"]
    cmd += argv
    # Limites de verdade via cgroup (memória, nº de processos, CPU), se o systemd do usuário existir.
    if shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"):
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
               "-p", f"MemoryMax={int(limite('memoria_sandbox_mb', 1024))}M", "-p", "MemorySwapMax=0",
               "-p", "TasksMax=64", "-p", "CPUQuota=100%", *cmd]
    return cmd


def rodar(pasta_codigo, argv, entrada=None, rede=False, gravavel=None, tempo=None, extra_ro=()):
    """Executa e devolve dict(codigo, saida, erro, segundos, estourou)."""
    tempo = tempo or int(limite("tempo_sandbox", 60))
    cmd = comando(pasta_codigo, argv, rede, gravavel, extra_ro)
    inicio = time.time()
    try:
        r = subprocess.run(cmd, input=entrada, capture_output=True, text=True, timeout=tempo,
                           preexec_fn=_limites(tempo, int(limite("memoria_sandbox_mb", 1024))))
        return {"codigo": r.returncode, "saida": r.stdout[-20000:], "erro": r.stderr[-8000:],
                "segundos": round(time.time() - inicio, 3), "estourou": False}
    except subprocess.TimeoutExpired as e:
        return {"codigo": -9, "saida": (e.stdout or "")[-4000:] if isinstance(e.stdout, str) else "",
                "erro": f"tempo limite de {tempo}s estourado", "segundos": tempo, "estourou": True}


def python(pasta_codigo, modo, dados, rede=False, gravavel=None, tempo=None):
    """Roda o executor em Python dentro do sandbox (modo: 'testar' ou 'chamar')."""
    r = rodar(pasta_codigo, [str(VENV / "bin/python"), "-I", "/sandbox/executor.py", modo],
              entrada=json.dumps(dados), rede=rede, gravavel=gravavel, tempo=tempo)
    try:
        r["resultado"] = json.loads(r["saida"].strip().splitlines()[-1])
    except Exception:
        r["resultado"] = None
    return r


def chamar_extensao(pasta, nome_ext, funcao, argumentos, permissoes):
    """Execução em produção de uma ferramenta de extensão: sempre isolada."""
    gravavel = ARQUIVOS_EXT / nome_ext if permissoes.get("arquivos") else None
    r = python(pasta, "chamar", {"funcao": funcao, "argumentos": argumentos},
               rede=bool(permissoes.get("rede")), gravavel=gravavel,
               tempo=int(limite("tempo_ferramenta", 30)))
    res = r.get("resultado") or {}
    if r["estourou"]:
        raise TimeoutError(r["erro"])
    if not res.get("ok"):
        raise RuntimeError(res.get("erro") or r["erro"][-500:] or "falha sem mensagem")
    return res["valor"]
