"""Este PC (Linux): status, volume, apps, sites, tela e comandos locais."""
import os
import re
import shutil
import subprocess
import webbrowser

from core.registro import NAO_CONFIAVEL, ferramenta


def _rodar(cmd, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


@ferramenta("status_deste_pc", "Status deste computador: CPU, memória, disco, bateria e tempo ligado.")
def status_deste_pc():
    partes = [_rodar(["uptime", "-p"])]
    carga = os.getloadavg()[0]
    partes.append(f"carga {carga:.1f} em {os.cpu_count()} núcleos")
    mem = _rodar(["free", "-h"]).splitlines()[1].split()
    partes.append(f"RAM {mem[2]} de {mem[1]} usada")
    disco = shutil.disk_usage("/")
    partes.append(f"disco {disco.used * 100 // disco.total}% cheio")
    for bat in ("/sys/class/power_supply/BAT0", "/sys/class/power_supply/BAT1"):
        if os.path.exists(bat):
            cap = open(f"{bat}/capacity").read().strip()
            st = open(f"{bat}/status").read().strip()
            partes.append(f"bateria {cap}% ({st})")
            break
    return "; ".join(partes)


@ferramenta(
    "volume",
    "Ajusta o volume do PC: nível de 0 a 100, ou mudo/desmudo.",
    {"type": "object", "properties": {
        "nivel": {"type": "integer", "minimum": 0, "maximum": 100},
        "mudo": {"type": "boolean"}}})
def volume(nivel=None, mudo=None):
    if mudo is not None:
        _rodar(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mudo else "0"])
    if nivel is not None:
        _rodar(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{nivel}%"])
    atual = re.search(r"(\d+)%", _rodar(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
    return f"Volume em {atual.group(1) if atual else '?'}%."


@ferramenta(
    "abrir_programa",
    "Abre um programa instalado neste PC pelo nome (ex.: firefox, spotify, code, steam).",
    {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]})
def abrir_programa(nome):
    nome = nome.strip().lower()
    pastas = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications"),
              "/var/lib/flatpak/exports/share/applications"]
    candidatos = []
    for p in pastas:
        if os.path.isdir(p):
            candidatos += [f[:-8] for f in os.listdir(p) if f.endswith(".desktop") and nome in f.lower()]
    if candidatos:
        alvo = min(candidatos, key=len)
        subprocess.Popen(["gtk-launch", alvo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Abrindo {alvo}."
    if shutil.which(nome):
        subprocess.Popen([nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Abrindo {nome}."
    return f"Não encontrei o programa {nome}."


@ferramenta(
    "abrir_site",
    "Abre um site ou faz uma busca no navegador padrão.",
    {"type": "object", "properties": {
        "url_ou_busca": {"type": "string"}}, "required": ["url_ou_busca"]})
def abrir_site(url_ou_busca):
    alvo = url_ou_busca.strip()
    if not re.match(r"https?://", alvo):
        if "." in alvo and " " not in alvo:
            alvo = "https://" + alvo
        else:
            from urllib.parse import quote_plus
            alvo = "https://duckduckgo.com/?q=" + quote_plus(alvo)
    webbrowser.open(alvo)
    return f"Abri {alvo}."


@ferramenta("bloquear_tela", "Bloqueia a tela deste PC.")
def bloquear_tela():
    _rodar(["loginctl", "lock-session"])
    return "Tela bloqueada."


@ferramenta(
    "executar_comando_local",
    "Executa um comando bash neste notebook (Linux) e devolve a saída. Último recurso: "
    "use só quando nenhuma ferramenta ou plugin cobre a tarefa. Comandos não interativos.",
    {"type": "object", "properties": {"comando": {"type": "string"}}, "required": ["comando"]},
    nivel="N3",
    resumo=lambda a: f"rodar neste PC: `{a.get('comando')}`")
def executar_comando_local(comando):
    r = subprocess.run(["bash", "-lc", comando], capture_output=True, text=True, timeout=120)
    saida = (r.stdout + r.stderr).strip()[:4000]
    return f"código de saída {r.returncode}\n" + NAO_CONFIAVEL + (saida or "(sem saída)")
