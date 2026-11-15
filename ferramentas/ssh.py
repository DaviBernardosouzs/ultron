"""Controle de computadores da rede via SSH (Linux, Mac, Raspberry, Windows com OpenSSH).

Os hosts ficam no config.yaml, em 'hosts'. O Ultron só fala com hosts listados.
Cada máquina tem um ID (a chave em 'hosts', ex.: notebook, desktop) e apelidos.
A máquina marcada com 'local: true' é esta onde o Ultron roda: os comandos rodam
direto, sem SSH. Use uma chave SSH dedicada (veja o README) e, de preferência,
um usuário sem sudo.
"""
import base64
import os
import shutil
import subprocess

from core.config import ajuste
from core.registro import NAO_CONFIAVEL, ferramenta


def _host(nome):
    """ID ou apelido -> (id, configuração)."""
    hosts = ajuste("hosts", {}) or {}
    alvo = nome.strip().lower()
    for id_, h in hosts.items():
        if alvo == id_.lower() or alvo in [a.lower() for a in h.get("apelidos", [])]:
            return id_, h
    raise ValueError(f"máquina '{nome}' não está no config.yaml. IDs: {', '.join(hosts) or 'nenhum'}")


def _decodificar(dados):
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp850", errors="replace")  # console padrão do Windows (pt-BR)


def _powershell(script):
    """Empacota um script PowerShell em -EncodedCommand: funciona com cmd ou
    PowerShell como shell do SSH e evita problemas de aspas e acentos."""
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "$ProgressPreference='SilentlyContinue';" + script)
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {b64}"


def _ssh(h, comando, timeout=60):
    if h.get("local"):
        r = subprocess.run(["bash", "-lc", comando], capture_output=True, timeout=timeout)
        return r.returncode, (_decodificar(r.stdout) + _decodificar(r.stderr)).strip()[:4000]
    if h.get("sistema") == "windows":
        comando = _powershell(comando)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR",
           "-o", "StrictHostKeyChecking=accept-new"]
    if h.get("chave"):
        cmd += ["-i", os.path.expanduser(h["chave"])]
    if h.get("porta"):
        cmd += ["-p", str(h["porta"])]
    cmd += [f"{h.get('usuario', 'root')}@{h['endereco']}", comando]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    saida = (_decodificar(r.stdout) + _decodificar(r.stderr)).strip()
    # Ruído do PowerShell quando a saída de erro vira XML (CLIXML).
    saida = "\n".join(l for l in saida.splitlines() if not l.startswith(("#< CLIXML", "<Objs ")))
    if len(saida) > 4000:
        saida = saida[:4000] + "\n...(cortado)"
    return r.returncode, saida


@ferramenta(
    "listar_computadores",
    "Lista os computadores que o Ultron controla por SSH (definidos no config.yaml).")
def listar_computadores():
    hosts = ajuste("hosts", {}) or {}
    if not hosts:
        return "Nenhum computador configurado em 'hosts' no config.yaml."
    return "\n".join(
        f"{n}: " + ("esta máquina" if h.get("local") else f"{h.get('usuario')}@{h.get('endereco')}")
        + f" ({h.get('sistema', 'linux')}; apelidos: {', '.join(h.get('apelidos', [])) or '-'})"
        for n, h in hosts.items())


@ferramenta(
    "status_computador",
    "Mostra se um computador está ligado, há quanto tempo, uso de CPU, memória e disco.",
    {"type": "object", "properties": {"computador": {"type": "string", "description": "ID da máquina (notebook, desktop) ou apelido"}}, "required": ["computador"]})
def status_computador(computador):
    nome, h = _host(computador)
    if h.get("sistema") == "windows":
        cmd = ("$o=Get-CimInstance Win32_OperatingSystem; $c=Get-CimInstance Win32_Processor;"
               "$d=Get-PSDrive C;"
               "'{0} ({1})' -f $env:COMPUTERNAME,$o.Caption;"
               "'Ligado desde {0:dd/MM HH:mm}' -f $o.LastBootUpTime;"
               "'CPU {0}%' -f ($c | Measure-Object LoadPercentage -Average).Average;"
               "'RAM {0:N1} de {1:N1} GB usada' -f (($o.TotalVisibleMemorySize-$o.FreePhysicalMemory)/1MB),"
               "($o.TotalVisibleMemorySize/1MB);"
               "'Disco C: {0:N0} GB livres de {1:N0} GB' -f ($d.Free/1GB),(($d.Used+$d.Free)/1GB)")
    else:
        cmd = "uptime; free -h | head -2; df -h / | tail -1"
    try:
        rc, saida = _ssh(h, cmd, timeout=20)
    except subprocess.TimeoutExpired:
        return f"{nome} não respondeu (provavelmente desligado)."
    if rc == 255:
        return f"Não consegui conectar em {nome}: {saida}"
    return NAO_CONFIAVEL + saida


@ferramenta(
    "executar_no_computador",
    "Executa um comando de terminal em um computador da rede via SSH e devolve a "
    "saída. Em computadores Windows o comando roda no PowerShell (use sintaxe "
    "PowerShell); nos demais, no shell do sistema. Use comandos não interativos e "
    "prefira comandos de leitura.",
    {"type": "object", "properties": {
        "computador": {"type": "string", "description": "ID da máquina (notebook, desktop) ou apelido"},
        "comando": {"type": "string"}}, "required": ["computador", "comando"]},
    nivel="N3",
    resumo=lambda a: f"rodar `{a.get('comando')}` em {a.get('computador')}")
def executar_no_computador(computador, comando):
    nome, h = _host(computador)
    try:
        rc, saida = _ssh(h, comando, timeout=ajuste("seguranca.timeout_ssh", 120))
    except subprocess.TimeoutExpired:
        return "O comando passou do tempo limite."
    return f"código de saída {rc}\n" + NAO_CONFIAVEL + (saida or "(sem saída)")


@ferramenta(
    "desligar_computador",
    "Desliga ou reinicia um computador da rede via SSH.",
    {"type": "object", "properties": {
        "computador": {"type": "string", "description": "ID da máquina (notebook, desktop) ou apelido"},
        "reiniciar": {"type": "boolean", "default": False}}, "required": ["computador"]},
    nivel="N3",
    resumo=lambda a: f"{'reiniciar' if a.get('reiniciar') else 'desligar'} {a.get('computador')}")
def desligar_computador(computador, reiniciar=False):
    nome, h = _host(computador)
    if h.get("local"):
        # Espera um pouco para ele conseguir responder antes de apagar.
        subprocess.Popen(["bash", "-c", f"sleep 15; systemctl {'reboot' if reiniciar else 'poweroff'}"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"{nome} vai {'reiniciar' if reiniciar else 'desligar'} em 15 segundos."
    if h.get("sistema") == "windows":
        cmd = "shutdown /r /t 5" if reiniciar else "shutdown /s /t 5"
    else:
        cmd = "systemctl reboot" if reiniciar else "systemctl poweroff"
    try:
        rc, saida = _ssh(h, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        return f"Comando enviado a {nome}; a conexão caiu, o que é esperado."
    if rc not in (0, 255):
        return f"{nome} recusou: {saida}"
    return f"{nome} está {'reiniciando' if reiniciar else 'desligando'}."


ABRIR_WINDOWS = r"C:\Users\davib\ultron\abrir.ps1"


def _aspas_ps(t):
    return "'" + str(t).replace("'", "''") + "'"


def abrir_em(computador, programa, argumentos=None):
    """Abre um programa com janela na tela da máquina (usado também pelos modos)."""
    nome, h = _host(computador)
    argumentos = [str(a) for a in (argumentos or [])]
    if h.get("local"):
        from ferramentas.sistema import abrir_programa
        if shutil.which(programa):
            subprocess.Popen([programa, *argumentos], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return f"{programa} aberto no {nome}."
        return abrir_programa(programa)
    if h.get("sistema") != "windows":
        return f"Abrir programas com janela só está pronto para o notebook e máquinas Windows."
    # Comandos via SSH rodam numa sessão invisível; o abrir.ps1 usa uma tarefa agendada
    # interativa para a janela aparecer na tela do usuário logado.
    script = h.get("abrir_script", ABRIR_WINDOWS)
    cmd = "& " + " ".join(_aspas_ps(x) for x in [script, programa, *argumentos])
    try:
        rc, saida = _ssh(h, cmd, timeout=40)
    except subprocess.TimeoutExpired:
        return f"{nome} não respondeu ao abrir {programa}."
    if rc != 0:
        return f"Falhou ao abrir {programa} no {nome}: {saida[-300:]}"
    return f"{programa.split(chr(92))[-1]} aberto no {nome}."


@ferramenta(
    "abrir_no_computador",
    "Abre um programa, atalho ou site COM JANELA na tela de uma máquina pelo ID "
    "(notebook ou desktop). No desktop Windows use o caminho do .exe ou um URL.",
    {"type": "object", "properties": {
        "computador": {"type": "string", "description": "ID da máquina (notebook, desktop)"},
        "programa": {"type": "string", "description": "programa, caminho do .exe ou URL"},
        "argumentos": {"type": "array", "items": {"type": "string"}}},
     "required": ["computador", "programa"]})
def abrir_no_computador(computador, programa, argumentos=None):
    return abrir_em(computador, programa, argumentos)
