"""Força emprestada do desktop: o Ultron usa CPU, RAM e GPU do PC de mesa para
os processos pesados que o Davi pedir, em vez de afogar o notebook.

- recursos_maquinas: carga real das duas máquinas e onde convém rodar.
- enviar_tarefa_desktop: copia uma pasta do notebook (opcional), roda o comando
  no desktop em segundo plano e devolve um ID. O processo é criado pelo WMI, fora
  da sessão SSH, então continua rodando depois que a conexão fecha.
- status / cancelar / trazer_resultado: acompanham e buscam o que foi produzido.
- ia_local_desktop: modelo local no Ollama do desktop (GPU RX 6700 XT).
- tunel_desktop: serviço que roda no desktop aparece em localhost no notebook,
  por SSH, sem abrir portas na rede.

As tarefas ficam em <computacao.pasta_remota>\\<id>\\ no desktop:
run.ps1, saida.log, codigo.txt (só existe quando terminou), pid.txt e trabalho\\.
O registro local fica em dados/computacao/tarefas.json.
"""
import atexit
import base64
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from core.config import DADOS, ajuste
from core.registro import NAO_CONFIAVEL, ferramenta
from ferramentas.ssh import _host, _ssh

PASTA = DADOS / "computacao"
PASTA.mkdir(exist_ok=True)
REGISTRO = PASTA / "tarefas.json"
TRAZIDOS = DADOS / "do-desktop"
EXCLUIR_PADRAO = ["node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build",
                  ".next", ".vite", "target"]

_tuneis = {}   # porta -> Popen do ssh -L


@atexit.register
def _fechar_tuneis():
    for proc in _tuneis.values():
        if proc.poll() is None:
            proc.terminate()


def _maquina():
    return _host(ajuste("computacao.maquina", "desktop"))


def _raiz_remota():
    return ajuste("computacao.pasta_remota", r"C:\Users\davib\ultron\trabalhos")


def _aspas(t):
    return "'" + str(t).replace("'", "''") + "'"


def _ssh_args(h):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR"]
    if h.get("chave"):
        cmd += ["-i", os.path.expanduser(h["chave"])]
    if h.get("porta"):
        cmd += ["-p", str(h["porta"])]
    return cmd + [f"{h.get('usuario', 'root')}@{h['endereco']}"]


def _ps(h, script, timeout=60):
    rc, saida = _ssh(h, script, timeout=timeout)
    if rc == 255:
        raise ConnectionError(f"sem conexão com o desktop: {saida[-200:]}")
    return rc, saida


def _no_ar(h):
    import socket
    try:
        socket.create_connection((h["endereco"], h.get("porta", 22)), timeout=2).close()
        return True
    except OSError:
        return False


def _garantir_ligado():
    nome, h = _maquina()
    if _no_ar(h):
        return nome, h, ""
    if not ajuste("computacao.ligar_automatico", True):
        raise ConnectionError(f"{nome} está desligado.")
    from ferramentas.modos import ligar_e_esperar
    return nome, h, ligar_e_esperar(nome) + " "


def _ler_registro():
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _gravar_registro(reg):
    tmp = REGISTRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, REGISTRO)


def _tarefa(id_):
    reg = _ler_registro()
    id_ = (id_ or "").strip()
    if id_ not in reg:
        achadas = [k for k in reg if k.startswith(id_)] if id_ else []
        if len(achadas) != 1:
            raise ValueError(f"tarefa '{id_}' não encontrada. Recentes: "
                             + (", ".join(list(reg)[-5:]) or "nenhuma"))
        id_ = achadas[0]
    return id_, reg[id_]


# ---------------------------------------------------------------- recursos

def _recursos_notebook():
    mem = {}
    for linha in Path("/proc/meminfo").read_text().splitlines():
        k, v = linha.split(":", 1)
        mem[k] = int(v.split()[0]) / 1048576
    carga = os.getloadavg()[0]
    gpu = ""
    for f in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
        try:
            gpu = f" GPU integrada {f.read_text().strip()}%."
        except OSError:
            pass
        break
    livre = mem["MemAvailable"]
    swap = mem["SwapTotal"] - mem["SwapFree"]
    return livre, (f"notebook: RAM {mem['MemTotal'] - livre:.1f} de {mem['MemTotal']:.1f} GB usada "
                   f"({livre:.1f} GB livres), swap em uso {swap:.1f} GB, carga {carga:.1f} "
                   f"em {os.cpu_count()} threads.{gpu}")


RECURSOS_PS = (
    "$o=Get-CimInstance Win32_OperatingSystem;"
    "$cpu=(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average;"
    "$g=Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage',"
    "'\\GPU Engine(*engtype_Compute*)\\Utilization Percentage',"
    "'\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue;"
    "$s=$g.CounterSamples;"
    "$g3d=($s | ? Path -like '*engtype_3d*' | Measure-Object CookedValue -Sum).Sum;"
    "$gcp=($s | ? Path -like '*engtype_compute*' | Measure-Object CookedValue -Sum).Sum;"
    "$vram=($s | ? Path -like '*dedicated usage' | Measure-Object CookedValue -Sum).Sum;"
    "'{0}|{1}|{2}|{3}|{4}|{5}' -f $cpu,($o.FreePhysicalMemory/1MB),($o.TotalVisibleMemorySize/1MB),"
    "[math]::Max($g3d,$gcp),($vram/1GB),((Get-PSDrive C).Free/1GB)"
)


def _abrir_tunel(h, local, remota):
    """ssh -L em segundo plano; devolve None se subiu, ou o erro."""
    proc = _tuneis.get(local)
    if proc and proc.poll() is None:
        return None
    args = _ssh_args(h)
    proc = subprocess.Popen(args[:1] + ["-N", "-o", "ExitOnForwardFailure=yes",
                                        "-o", "ServerAliveInterval=30",
                                        "-L", f"127.0.0.1:{local}:127.0.0.1:{remota}"] + args[1:],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    for _ in range(20):
        time.sleep(0.25)
        if proc.poll() is not None:
            return proc.stderr.read().decode(errors="replace")[-200:] or "o ssh fechou"
        try:
            import socket
            socket.create_connection(("127.0.0.1", local), timeout=0.5).close()
            break
        except OSError:
            pass
    _tuneis[local] = proc
    return None


def _ollama_url():
    """'tunel' (padrão): fala com o Ollama do desktop por SSH, sem abrir o firewall."""
    url = str(ajuste("computacao.ollama", "tunel"))
    if url != "tunel":
        return url.rstrip("/")
    local = int(ajuste("computacao.porta_ollama_local", 21434))
    _, h = _maquina()
    _abrir_tunel(h, local, 11434)
    return f"http://127.0.0.1:{local}"


def _ollama_carregados():
    try:
        r = requests.get(_ollama_url() + "/api/ps", timeout=3)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def carga_desktop():
    """Carga real do desktop: {cpu, ram, ram_total, gpu, vram, vram_total, disco} em
    %/GB, ou None se estiver desligado. Também usada pelo HUD da janela."""
    _, h = _maquina()
    if not _no_ar(h):
        return None
    rc, saida = _ps(h, RECURSOS_PS, timeout=30)
    cpu, livre, total, gpu, vram, disco = (float(x.replace(",", "."))
                                            for x in saida.strip().splitlines()[-1].split("|"))
    return {"cpu": cpu, "ram": total - livre, "ram_total": total, "gpu": gpu, "vram": vram,
            "vram_total": float(ajuste("computacao.vram_gb", 12)), "disco": disco}


@ferramenta(
    "recursos_maquinas",
    "Mostra a carga real de CPU, RAM e GPU do notebook e do desktop e recomenda onde "
    "rodar um processo pesado. Use antes de decidir se algo deve ir para o desktop.")
def recursos_maquinas():
    livre_nb, txt_nb = _recursos_notebook()
    nome, h = _maquina()
    try:
        c = carga_desktop()
    except Exception as e:
        return txt_nb + f"\n{nome}: ligado, mas não consegui ler a carga ({e})."
    if c is None:
        return (txt_nb + f"\n{nome}: desligado (posso ligar pela rede). "
                + ("O notebook está apertado de memória." if livre_nb < 2 else ""))
    cpu, total, gpu, vram, disco = c["cpu"], c["ram_total"], c["gpu"], c["vram"], c["disco"]
    livre = total - c["ram"]
    vram_total = float(ajuste("computacao.vram_gb", 12))
    carregados = _ollama_carregados()
    ia = ("Ollama fora do ar" if carregados is None
          else "Ollama sem modelo carregado" if not carregados
          else "Ollama com " + ", ".join(carregados) + " na GPU")
    txt_dk = (f"{nome}: CPU {cpu:.0f}%, RAM {total - livre:.1f} de {total:.1f} GB usada "
              f"({livre:.1f} GB livres), GPU {gpu:.0f}%, VRAM {vram:.1f} de {vram_total:.0f} GB, "
              f"disco C {disco:.0f} GB livres, {ia}.")
    if livre > livre_nb + 2 and cpu < 80:
        dica = "Recomendação: processos pesados vão melhor no desktop."
    elif livre_nb >= 4:
        dica = "Recomendação: o notebook ainda dá conta de tarefas leves."
    else:
        dica = "Recomendação: as duas máquinas estão ocupadas; espere ou rode algo menor."
    return f"{txt_nb}\n{txt_dk}\n{dica}"


# ---------------------------------------------------------------- tarefas

def _enviar_pasta(h, origem, destino_remoto, excluir):
    origem = Path(os.path.expanduser(origem)).resolve()
    if not origem.is_dir():
        raise ValueError(f"pasta não encontrada no notebook: {origem}")
    args = ["tar", "-C", str(origem.parent), "-czf", "-"]
    args += [f"--exclude={e}" for e in excluir]
    args.append(origem.name)
    remoto = f"tar.exe -xzf - -C {_aspas(destino_remoto)}"
    tar = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ssh = subprocess.run(_ssh_args(h) + [remoto], stdin=tar.stdout, capture_output=True,
                         timeout=int(ajuste("computacao.tempo_envio", 900)))
    tar.stdout.close()
    erro_tar = tar.communicate()[1]
    if tar.returncode or ssh.returncode:
        raise RuntimeError("falha ao copiar a pasta: "
                           + (erro_tar + ssh.stderr).decode(errors="replace")[-300:])
    return origem.name


def _resumo_envio(a):
    return (f"rodar `{a.get('comando')}` no desktop"
            + (f" com a pasta {a['pasta']}" if a.get("pasta") else ""))


@ferramenta(
    "enviar_tarefa_desktop",
    "Roda um processo pesado no DESKTOP (20 GB de RAM, 12 threads, GPU RX 6700 XT) em "
    "segundo plano, em vez do notebook. Use para builds, npm/pip install, compilar, "
    "testes longos, converter vídeo/áudio, processar muitos arquivos, scripts Python/Node "
    "pesados ou servidores de desenvolvimento. Se 'pasta' for dada, ela é copiada do "
    "notebook (sem node_modules, .venv, dist...) e o comando roda dentro dela. O comando "
    "é PowerShell 5.1 no Windows (separe etapas com ';' ou '&&'; há node 22, npm, python, "
    "git, uv e ollama). Devolve um ID; "
    "acompanhe com status_tarefa_desktop e busque arquivos com trazer_resultado_desktop.",
    {"type": "object", "properties": {
        "comando": {"type": "string", "description": "comando PowerShell, ex.: 'npm ci; npm run build'"},
        "pasta": {"type": "string", "description": "pasta do notebook para copiar (opcional)"},
        "nome": {"type": "string", "description": "nome curto da tarefa"},
        "excluir": {"type": "array", "items": {"type": "string"},
                    "description": "padrões a não copiar; substitui a lista padrão"}},
     "required": ["comando"]},
    nivel="N3", resumo=_resumo_envio)
def enviar_tarefa_desktop(comando, pasta=None, nome=None, excluir=None):
    # O PowerShell 5.1 do Windows não tem '&&': para na primeira etapa que falhar, como no bash.
    original = comando
    comando = re.sub(r"\s*&&\s*", "\nif (-not $?) { throw 'etapa anterior falhou' }\n", comando)
    nome_maq, h, aviso = _garantir_ligado()
    id_ = datetime.now().strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    raiz = _raiz_remota() + "\\" + id_
    trabalho = raiz + "\\trabalho"
    _ps(h, f"New-Item -ItemType Directory -Force -Path {_aspas(trabalho)} | Out-Null")
    cwd = trabalho
    if pasta:
        sub = _enviar_pasta(h, pasta, trabalho, EXCLUIR_PADRAO if excluir is None else excluir)
        cwd = trabalho + "\\" + sub
    script = (
        "$ErrorActionPreference='Continue'\r\n"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8\r\n"
        "$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'\r\n"
        f"Set-Location -LiteralPath {_aspas(cwd)}\r\n"
        f"$log={_aspas(raiz + chr(92) + 'saida.log')}\r\n"
        "$global:LASTEXITCODE=0; $global:__falhou=$false\r\n"
        "try {\r\n"
        f"  & {{\r\n{comando}\r\nif (-not $?) {{ $global:__falhou=$true }}\r\n  }} *>&1 | ForEach-Object {{ \"$_\" }} | Out-File -FilePath $log -Encoding utf8 -Append\r\n"
        "  $c = if ($LASTEXITCODE) { $LASTEXITCODE } elseif ($global:__falhou) { 1 } else { 0 }\r\n"
        "} catch { \"ERRO: $_\" | Out-File -FilePath $log -Encoding utf8 -Append\r\n"
        "  $c = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 } }\r\n"
        f"Set-Content -LiteralPath {_aspas(raiz + chr(92) + 'codigo.txt')} -Value $c\r\n"
    )
    b64 = base64.b64encode(script.encode("utf-8-sig")).decode()
    rodar = (f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{raiz}\\run.ps1\"")
    rc, saida = _ps(h, (
        f"[IO.File]::WriteAllBytes({_aspas(raiz + chr(92) + 'run.ps1')},"
        f"[Convert]::FromBase64String('{b64}'));"
        f"$r=Invoke-CimMethod Win32_Process -MethodName Create -Arguments "
        f"@{{CommandLine={_aspas(rodar)};CurrentDirectory={_aspas(raiz)}}};"
        f"Set-Content -LiteralPath {_aspas(raiz + chr(92) + 'pid.txt')} -Value $r.ProcessId;"
        "'PID=' + $r.ProcessId + ' RV=' + $r.ReturnValue"))
    m = re.search(r"PID=(\d+) RV=0", saida)
    if not m:
        raise RuntimeError(f"o desktop não iniciou a tarefa: {saida[-300:]}")
    reg = _ler_registro()
    reg[id_] = {"nome": nome or original[:60], "comando": original, "pasta": pasta,
                "raiz": raiz, "cwd": cwd, "pid": int(m.group(1)),
                "inicio": datetime.now().isoformat(timespec="seconds"), "maquina": nome_maq}
    _gravar_registro(reg)
    return (f"{aviso}Tarefa {id_} rodando no {nome_maq} (PID {m.group(1)}). "
            "Use status_tarefa_desktop para acompanhar.")


def _estado(h, t, linhas=15):
    rc, saida = _ps(h, (
        f"$r={_aspas(t['raiz'])};"
        "$c=if(Test-Path \"$r\\codigo.txt\"){(Get-Content \"$r\\codigo.txt\" -Raw).Trim()}else{''};"
        f"$vivo=[bool](Get-Process -Id {t['pid']} -ErrorAction SilentlyContinue);"
        "'#C=' + $c + '|' + $vivo;"
        f"if(Test-Path \"$r\\saida.log\"){{Get-Content \"$r\\saida.log\" -Tail {int(linhas)} -Encoding utf8}}"),
        timeout=30)
    cab, _, log = saida.partition("\n")
    m = re.search(r"#C=(.*)\|(True|False)", cab)
    codigo, vivo = (m.group(1), m.group(2) == "True") if m else ("", False)
    if codigo == "cancelada":
        estado = "cancelada"
    elif codigo:
        estado = "concluída" if codigo == "0" else f"falhou (código {codigo})"
    elif vivo:
        estado = "rodando"
    else:
        estado = "interrompida (o processo sumiu sem terminar)"
    return estado, log.strip()


@ferramenta(
    "status_tarefa_desktop",
    "Mostra o estado de uma tarefa enviada ao desktop (rodando, concluída, falhou) e as "
    "últimas linhas da saída. Sem ID, lista as tarefas recentes.",
    {"type": "object", "properties": {
        "id": {"type": "string", "description": "ID da tarefa (o começo basta)"},
        "linhas": {"type": "integer", "default": 15}}})
def status_tarefa_desktop(id=None, linhas=15):
    nome, h = _maquina()
    if not id:
        reg = _ler_registro()
        if not reg:
            return "Nenhuma tarefa enviada ao desktop ainda."
        if not _no_ar(h):
            return f"{nome} está desligado. Tarefas registradas: " + ", ".join(list(reg)[-8:])
        saidas = []
        for k in list(reg)[-8:]:
            try:
                estado, _ = _estado(h, reg[k], 0)
            except Exception as e:
                estado = f"sem resposta ({e})"
            saidas.append(f"{k} [{reg[k]['nome']}]: {estado}")
        return "\n".join(saidas)
    id_, t = _tarefa(id)
    if not _no_ar(h):
        return f"{nome} está desligado; não dá para ver a tarefa {id_}."
    estado, log = _estado(h, t, linhas)
    decorrido = int((datetime.now() - datetime.fromisoformat(t["inicio"])).total_seconds())
    return (f"Tarefa {id_} [{t['nome']}]: {estado}, iniciada há {decorrido // 60} min "
            f"{decorrido % 60} s.\n" + (NAO_CONFIAVEL + log if log else "(sem saída ainda)"))


@ferramenta(
    "cancelar_tarefa_desktop",
    "Interrompe uma tarefa que está rodando no desktop (encerra o processo e os filhos).",
    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    nivel="N2", resumo=lambda a: f"cancelar a tarefa {a.get('id')} no desktop")
def cancelar_tarefa_desktop(id):
    nome, h = _maquina()
    id_, t = _tarefa(id)
    rc, saida = _ps(h, (
        f"taskkill /PID {t['pid']} /T /F 2>&1 | Out-Null;"
        f"Set-Content -LiteralPath {_aspas(t['raiz'] + chr(92) + 'codigo.txt')} -Value 'cancelada'"))
    return f"Tarefa {id_} cancelada no {nome}."


def _nivel_trazer(args):
    return ("N2", "trazer_resultado_desktop.destino") if args.get("destino") else \
        ("N1", "trazer_resultado_desktop")


@ferramenta(
    "trazer_resultado_desktop",
    "Copia arquivos produzidos por uma tarefa do desktop para o notebook. 'caminho' é "
    "relativo à pasta onde o comando rodou (ex.: 'dist', 'saida.mp4'; '.' traz tudo). "
    "Sem 'destino', grava em ~/ultron/dados/do-desktop/<id>/ sem sobrescrever nada.",
    {"type": "object", "properties": {
        "id": {"type": "string"},
        "caminho": {"type": "string", "default": "."},
        "destino": {"type": "string", "description": "pasta do notebook onde extrair (opcional)"}},
     "required": ["id"]},
    nivel_dinamico=_nivel_trazer,
    resumo=lambda a: f"trazer {a.get('caminho', '.')} da tarefa {a.get('id')} para {a.get('destino')}")
def trazer_resultado_desktop(id, caminho=".", destino=None):
    nome, h = _maquina()
    id_, t = _tarefa(id)
    caminho = caminho.replace("/", "\\").strip("\\") or "."
    if ".." in caminho.split("\\"):
        raise ValueError("caminho precisa ficar dentro da pasta da tarefa")
    alvo = Path(os.path.expanduser(destino)) if destino else TRAZIDOS / id_
    alvo.mkdir(parents=True, exist_ok=True)
    remoto = f"tar.exe -czf - -C {_aspas(t['cwd'])} {_aspas(caminho)}"
    ssh = subprocess.Popen(_ssh_args(h) + [remoto], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar = subprocess.run(["tar", "-xzf", "-", "-C", str(alvo)], stdin=ssh.stdout,
                         capture_output=True, timeout=int(ajuste("computacao.tempo_envio", 900)))
    ssh.stdout.close()
    erro_ssh = ssh.communicate()[1]
    if tar.returncode or ssh.returncode:
        raise RuntimeError("falha ao trazer: " + (erro_ssh + tar.stderr).decode(errors="replace")[-300:])
    tamanho = sum(f.stat().st_size for f in alvo.rglob("*") if f.is_file())
    return f"Resultado da tarefa {id_} trazido para {alvo} ({tamanho / 1048576:.1f} MB)."


# ---------------------------------------------------------------- IA local na GPU

@ferramenta(
    "ia_local_desktop",
    "Usa um modelo de IA local rodando na GPU do desktop (Ollama), sem gastar a cota da "
    "nuvem. Bom para resumir ou analisar arquivos grandes, revisar código e rascunhos. "
    "Modelos: qwen2.5-coder:7b (rápido, código), qwen2.5-coder:14b (melhor), dolphin3. "
    "'arquivo' é um texto do notebook anexado ao pedido.",
    {"type": "object", "properties": {
        "pedido": {"type": "string"},
        "arquivo": {"type": "string", "description": "caminho de um arquivo de texto do notebook"},
        "modelo": {"type": "string"}},
     "required": ["pedido"]})
def ia_local_desktop(pedido, arquivo=None, modelo=None):
    nome, h, aviso = _garantir_ligado()
    modelo = modelo or ajuste("computacao.modelo_local", "qwen2.5-coder:7b")
    prompt = pedido
    if arquivo:
        caminho = Path(os.path.expanduser(arquivo))
        texto = caminho.read_text(encoding="utf-8", errors="replace")
        limite = int(ajuste("computacao.limite_arquivo", 60000))
        if len(texto) > limite:
            texto = texto[:limite] + "\n...(cortado)"
        prompt = f"{pedido}\n\nArquivo {caminho.name}:\n```\n{texto}\n```"
    contexto = int(ajuste("computacao.contexto_local", 16384))
    try:
        r = requests.post(_ollama_url() + "/api/generate", timeout=600, json={
            "model": modelo, "prompt": prompt, "stream": False,
            "options": {"num_ctx": contexto}})
    except (requests.ConnectionError, requests.ReadTimeout):
        return f"{aviso}O Ollama do {nome} não respondeu em {_ollama_url()}. Ele está aberto?"
    if r.status_code != 200:
        return f"O Ollama recusou ({r.status_code}): {r.text[:300]}"
    d = r.json()
    seg = d.get("total_duration", 0) / 1e9
    return (f"{aviso}[{modelo} na GPU do {nome}, {seg:.0f} s]\n"
            + (NAO_CONFIAVEL if arquivo else "") + d.get("response", "").strip())


# ---------------------------------------------------------------- túnel

@ferramenta(
    "tunel_desktop",
    "Liga um serviço que roda no desktop (ex.: servidor de desenvolvimento na porta 4173) "
    "ao notebook por SSH: ele passa a abrir em http://localhost:<porta> aqui, sem expor "
    "nada na rede. acao: abrir | fechar | listar.",
    {"type": "object", "properties": {
        "porta": {"type": "integer"},
        "acao": {"type": "string", "enum": ["abrir", "fechar", "listar"], "default": "abrir"},
        "porta_local": {"type": "integer", "description": "porta no notebook (padrão: a mesma)"}}})
def tunel_desktop(porta=None, acao="abrir", porta_local=None):
    for p, proc in list(_tuneis.items()):
        if proc.poll() is not None:
            del _tuneis[p]
    if acao == "listar":
        return ("Túneis abertos: " + ", ".join(f"localhost:{p}" for p in _tuneis)) if _tuneis \
            else "Nenhum túnel aberto."
    if not porta:
        raise ValueError("informe a porta")
    local = int(porta_local or porta)
    if acao == "fechar":
        proc = _tuneis.pop(local, None)
        if not proc:
            return f"Não há túnel na porta {local}."
        proc.terminate()
        return f"Túnel localhost:{local} fechado."
    if local in _tuneis:
        return f"Já existe túnel em http://localhost:{local}."
    nome, h, aviso = _garantir_ligado()
    erro = _abrir_tunel(h, local, int(porta))
    if erro:
        return f"O túnel falhou: {erro}"
    return f"{aviso}Porta {porta} do {nome} disponível em http://localhost:{local}."
