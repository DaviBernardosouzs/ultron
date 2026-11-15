"""Rede local: descobrir dispositivos, apelidos, ping, portas e Wake-on-LAN.

Por segurança, toda varredura é limitada a endereços privados (RFC 1918).
"""
import ipaddress
import json
import re
import shutil
import socket
import subprocess
from datetime import datetime

from core.config import DADOS, ajuste
from core.registro import NAO_CONFIAVEL, ferramenta

INVENTARIO = DADOS / "dispositivos.json"


# ------------------------------------------------------------------ apoio

def _rodar(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def sub_rede():
    """Sub-rede da interface com a rota padrão (ex.: 192.168.1.0/24)."""
    fixa = ajuste("rede.sub_rede")
    if fixa:
        return fixa
    rota = _rodar(["ip", "-4", "route", "show", "default"])
    m = re.search(r"dev (\S+)", rota)
    if not m:
        raise RuntimeError("não encontrei a rota padrão")
    addr = _rodar(["ip", "-4", "-o", "addr", "show", "dev", m.group(1)])
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", addr)
    return str(ipaddress.ip_network(m.group(1), strict=False))


def _privado(alvo):
    try:
        return ipaddress.ip_network(alvo, strict=False).is_private
    except ValueError:
        return False


def _carregar():
    try:
        return json.loads(INVENTARIO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salvar(inv):
    INVENTARIO.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")


def _apelidos():
    """config.yaml -> dispositivos: { 'pc do quarto': {mac: .., ip: ..}, ... }"""
    return ajuste("dispositivos", {}) or {}


def resolver(nome_ou_ip):
    """Aceita IP, MAC, apelido do config.yaml ou nome do inventário -> (ip, mac)."""
    alvo = nome_ou_ip.strip().lower()
    for apelido, d in _apelidos().items():
        if apelido.lower() == alvo:
            ip, mac = d.get("ip"), (d.get("mac") or "").lower()
            if not ip and mac:
                ip = next((e["ip"] for e in _carregar().values()
                           if e.get("mac", "").lower() == mac), None)
            return ip, mac or None
    # Máquinas do config (IDs e apelidos de 'hosts', ex.: "desktop", "pc windows")
    for id_, h in (ajuste("hosts", {}) or {}).items():
        if h.get("mac") and alvo in [id_.lower()] + [a.lower() for a in h.get("apelidos", [])]:
            return h.get("endereco"), h["mac"].lower()
    for mac, e in _carregar().items():
        if alvo in (e.get("ip", ""), mac.lower(), (e.get("nome") or "").lower(),
                    (e.get("apelido") or "").lower()):
            return e.get("ip"), mac
    try:
        ipaddress.ip_address(alvo)
        return alvo, None
    except ValueError:
        return None, None


def _vizinhos():
    """Tabela ARP do kernel: {ip: mac}."""
    tab = {}
    for linha in _rodar(["ip", "neigh"]).splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+) .*lladdr ([0-9a-f:]{17})", linha)
        if m and "FAILED" not in linha:
            tab[m.group(1)] = m.group(2)
    return tab


# ------------------------------------------------------------------ ferramentas

@ferramenta(
    "escanear_rede",
    "Varre a rede local e lista todos os dispositivos conectados (IP, MAC, nome, "
    "fabricante), marcando os novos. Use quando perguntarem quem/o que está na rede.",
    resumo=lambda a: "escanear a rede local")
def escanear_rede():
    if not shutil.which("nmap"):
        return "O nmap não está instalado (sudo pacman -S nmap)."
    rede = sub_rede()
    if not _privado(rede):
        return f"Recusado: {rede} não é uma rede privada."
    saida = _rodar(["nmap", "-sn", "-T4", "--host-timeout", "5s", rede], timeout=180)
    vistos = {}
    atual = None
    for linha in saida.splitlines():
        m = re.match(r"Nmap scan report for (?:(\S+) \()?(\d+\.\d+\.\d+\.\d+)\)?", linha)
        if m:
            atual = {"ip": m.group(2), "nome": m.group(1) or ""}
            vistos[atual["ip"]] = atual
            continue
        m = re.match(r"MAC Address: ([0-9A-F:]{17}) \((.*)\)", linha)
        if m and atual:
            atual["mac"], atual["fabricante"] = m.group(1).lower(), m.group(2)
    arp = _vizinhos()
    meus_ips = set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", _rodar(["ip", "-4", "-o", "addr"])))
    for ip, d in vistos.items():
        if d["nome"] == ip:
            d["nome"] = ""
        d.setdefault("mac", arp.get(ip, ""))
        if ip in meus_ips:
            d["nome"] = d["nome"] or "este PC"
        elif d["mac"] and not d.get("fabricante") and int(d["mac"][1], 16) & 2:
            # MAC "localmente administrado": celulares/tablets com MAC aleatório.
            d["fabricante"] = "MAC aleatório (provável celular/tablet)"

    inv = _carregar()
    agora = datetime.now().isoformat(timespec="minutes")
    novos = []
    for d in vistos.values():
        chave = d.get("mac") or d["ip"]
        if chave not in inv:
            novos.append(d)
            inv[chave] = {"primeira_vez": agora}
        inv[chave].update({k: v for k, v in d.items() if v})
        inv[chave]["ultima_vez"] = agora
    _salvar(inv)

    apelido_por_mac = {(v.get("mac") or "").lower(): k for k, v in _apelidos().items()}
    linhas = []
    for d in sorted(vistos.values(), key=lambda d: ipaddress.ip_address(d["ip"])):
        chave = d.get("mac") or d["ip"]
        apelido = apelido_por_mac.get(d.get("mac", "")) or inv[chave].get("apelido", "")
        partes = [d["ip"], apelido or d.get("nome") or "?", d.get("fabricante", ""), d.get("mac", "")]
        marca = " (NOVO)" if d in novos else ""
        linhas.append(" | ".join(p for p in partes if p) + marca)
    return (f"{len(vistos)} dispositivos em {rede}, {len(novos)} novos.\n"
            + NAO_CONFIAVEL + "\n".join(linhas))


@ferramenta(
    "listar_dispositivos_conhecidos",
    "Lista o inventário salvo de dispositivos (inclusive offline), com apelidos e "
    "quando foram vistos pela última vez. Não varre a rede.")
def listar_dispositivos_conhecidos():
    inv = _carregar()
    if not inv:
        return "Inventário vazio. Rode escanear_rede primeiro."
    apelido_por_mac = {(v.get("mac") or "").lower(): k for k, v in _apelidos().items()}
    linhas = [f"{e.get('ip','?')} | {apelido_por_mac.get(mac) or e.get('apelido') or e.get('nome') or '?'} | "
              f"{e.get('fabricante','')} | visto {e.get('ultima_vez','?')}"
              for mac, e in inv.items()]
    return NAO_CONFIAVEL + "\n".join(linhas)


@ferramenta(
    "ping",
    "Verifica se um dispositivo da rede está online. Aceita IP, apelido ou nome.",
    {"type": "object", "properties": {"alvo": {"type": "string"}}, "required": ["alvo"]})
def ping(alvo):
    ip, _ = resolver(alvo)
    if not ip:
        return f"Não sei quem é '{alvo}'. Escaneie a rede ou configure um apelido."
    if not _privado(ip):
        return "Só faço ping em dispositivos da rede local."
    r = subprocess.run(["ping", "-c", "2", "-W", "1", ip], capture_output=True, text=True)
    if r.returncode != 0:
        return f"{alvo} ({ip}) não respondeu."
    m = re.search(r"= [\d.]+/([\d.]+)/", r.stdout)
    return f"{alvo} ({ip}) online, latência média {m.group(1) if m else '?'} ms."


@ferramenta(
    "portas_abertas",
    "Descobre os serviços/portas abertas de um dispositivo da rede local "
    "(útil para saber o que ele é ou checar segurança).",
    {"type": "object", "properties": {"alvo": {"type": "string"}}, "required": ["alvo"]},
    resumo=lambda a: f"verificar as portas abertas de {a.get('alvo')}")
def portas_abertas(alvo):
    ip, _ = resolver(alvo)
    if not ip or not _privado(ip):
        return "Só verifico portas de dispositivos da minha rede local."
    saida = _rodar(["nmap", "-F", "-sV", "--version-light", "-T4", ip], timeout=180)
    linhas = [l for l in saida.splitlines() if re.match(r"\d+/(tcp|udp)", l)]
    return NAO_CONFIAVEL + ("\n".join(linhas) if linhas else "Nenhuma porta comum aberta.")


@ferramenta(
    "ligar_dispositivo_wol",
    "Liga um computador pela rede (Wake-on-LAN). Precisa do MAC ou de um apelido "
    "com MAC no config.yaml, e do WoL habilitado na BIOS/placa de rede.",
    {"type": "object", "properties": {"alvo": {"type": "string"}}, "required": ["alvo"]})
def ligar_dispositivo_wol(alvo):
    _, mac = resolver(alvo)
    if not mac and re.fullmatch(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}", alvo.lower()):
        mac = alvo.lower()
    if not mac:
        return f"Não tenho o MAC de '{alvo}'."
    hexmac = mac.replace(":", "").replace("-", "")
    pacote = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast = str(ipaddress.ip_network(sub_rede()).broadcast_address)
        s.sendto(pacote, (broadcast, 9))
    return f"Pacote mágico enviado para {alvo} ({mac})."


@ferramenta(
    "info_rede",
    "Informações da conexão: IP deste PC, roteador, sub-rede, IP público e se a "
    "internet está funcionando.")
def info_rede():
    rota = _rodar(["ip", "-4", "route", "show", "default"])
    gw = re.search(r"via (\S+)", rota)
    try:
        import requests
        publico = requests.get("https://api.ipify.org", timeout=5).text
    except Exception:
        publico = "sem internet"
    return (f"Sub-rede {sub_rede()}, roteador {gw.group(1) if gw else '?'}, "
            f"IP público {publico}.")


@ferramenta(
    "apelidar_dispositivo",
    "Dá um apelido amigável a um dispositivo do inventário (ex.: 'TV da sala').",
    {"type": "object", "properties": {
        "alvo": {"type": "string", "description": "IP ou MAC atual"},
        "apelido": {"type": "string"}}, "required": ["alvo", "apelido"]})
def apelidar_dispositivo(alvo, apelido):
    inv = _carregar()
    for mac, e in inv.items():
        if alvo.lower() in (mac.lower(), e.get("ip", "")):
            e["apelido"] = apelido
            _salvar(inv)
            return f"Ok, {e.get('ip')} agora é '{apelido}'."
    return "Não achei esse dispositivo no inventário."
