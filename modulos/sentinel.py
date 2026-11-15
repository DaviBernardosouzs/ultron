"""SENTINEL: percepção do ambiente digital, com ativação e privacidade explícitas.

Tudo desligado por padrão (sentinel.ativo: false). Cada capacidade tem chave própria:
  app_ativo         ler o app em foco (KWin, Wayland) quando pedido ou no monitor
  eventos_sistema   monitor a cada minuto: memória quase cheia (o que travou o notebook),
                    disco, bateria, serviços do Ultron parados, desktop ligou/desligou
  guardar_titulos   guardar o título da janela nas atividades (padrão: não; guarda só o app)
  processos_permitidos  só esses processos podem ser consultados
Capturas de tela: só quando o Davi pede (uma imagem, com confirmação N2), vão para o
Prism e são apagadas; nada de gravação contínua. Não há monitoramento de outras
pessoas nem de outros computadores.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from core import eventos
from core.config import DADOS, ajuste

SCRIPT_KWIN = """var w = workspace.activeWindow;
print("ULTRON_SENTINEL|" + (w ? w.resourceClass : "") + "|" + (w ? w.caption : "").replace(/\\|/g, "/") + "|" + (w ? w.pid : ""));"""
_estado = {"desktop": None, "avisos": {}}
_iniciado = False


def cfg(chave, padrao=False):
    return ajuste(f"sentinel.{chave}", padrao)


def ligado(cap=None):
    return bool(cfg("ativo")) and (cap is None or bool(cfg(cap, True)))


# ------------------------------------------------------------------ app ativo

def app_ativo():
    """{'app', 'titulo', 'pid'} da janela em foco, via script do KWin. Exige sentinel.app_ativo."""
    if not ligado("app_ativo"):
        raise PermissionError("o Sentinel está desligado (ou sem permissão para ler o app ativo)")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(SCRIPT_KWIN)
        js = f.name
    nome = f"ultron_sentinel_{os.getpid()}"
    try:
        inicio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid = subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", js, nome],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.run"],
                       capture_output=True, timeout=5)
        time.sleep(0.3)
        log = subprocess.run(["journalctl", "--user", "--since", inicio, "--no-pager", "-o", "cat"],
                             capture_output=True, text=True, timeout=5).stdout
    finally:
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", nome],
                       capture_output=True, timeout=5)
        os.unlink(js)
    linhas = [l for l in log.splitlines() if "ULTRON_SENTINEL|" in l]
    if not linhas:
        raise RuntimeError("o KWin não respondeu (só funciona no Plasma)")
    app, titulo, pid = (linhas[-1].split("ULTRON_SENTINEL|", 1)[1].split("|") + ["", "", ""])[:3]
    return {"app": app, "titulo": titulo, "pid": pid}


def associar_workspace(janela):
    """Qual WorkSpace combina com a janela (projeto ou pasta do workspace no título)."""
    from core import workspaces
    texto = (janela.get("titulo", "") + " " + janela.get("app", "")).lower()
    for ws in workspaces.listar():
        chaves = [ws["nome"], ws["projeto"] or "", os.path.basename((ws["diretorio"] or "").rstrip("/"))]
        if any(k and len(k) > 2 and k.lower() in texto for k in chaves):
            return ws["nome"]
    return None


def contexto_da_janela():
    """App ativo + WorkSpace sugerido + documentos do NEURALINK ligados ao título."""
    j = app_ativo()
    ws = associar_workspace(j)
    docs = []
    try:
        from neuralink import busca
        if j["titulo"].strip():
            docs = [r["citacao"] for r in busca.buscar(j["titulo"], k=4, semantica=False)]
    except Exception:
        pass
    eventos.emitir("module.status_changed", "sentinel", {
        "modulo": "sentinel", "mudanca": "contexto", "app": j["app"], "workspace": ws,
        **({"titulo": j["titulo"]} if cfg("guardar_titulos") else {})})
    return {"janela": j, "workspace": ws, "documentos": docs}


# ------------------------------------------------------------------ processos e capturas

def processos(nome=None):
    permitidos = [p.lower() for p in (cfg("processos_permitidos", []) or [])]
    r = subprocess.run(["ps", "-eo", "pid,%cpu,rss,etime,comm", "--sort=-rss"], capture_output=True, text=True)
    saida = []
    for l in r.stdout.splitlines()[1:]:
        pid, cpu, rss, etime, comm = l.split(None, 4)
        if comm.lower() not in permitidos or (nome and nome.lower() not in comm.lower()):
            continue
        saida.append({"pid": int(pid), "cpu": float(cpu), "ram_mb": int(rss) // 1024, "tempo": etime, "nome": comm})
    return saida


def capturar_tela():
    """Uma captura da tela inteira, sob pedido. O arquivo é temporário: quem chamou apaga."""
    if not ligado():
        raise PermissionError("o Sentinel está desligado")
    destino = Path(tempfile.gettempdir()) / f"ultron-captura-{int(time.time())}.png"
    r = subprocess.run(["spectacle", "-b", "-n", "-f", "-o", str(destino)], capture_output=True, timeout=20)
    if r.returncode or not destino.exists():
        raise RuntimeError("a captura falhou (spectacle)")
    eventos.emitir("module.status_changed", "sentinel", {"modulo": "sentinel", "mudanca": "captura_sob_pedido"})
    return destino


# ------------------------------------------------------------------ eventos do sistema

def verificar_sistema():
    """Uma rodada de verificação. Devolve a lista de alertas (cada um vira evento uma vez por hora)."""
    alertas = []
    mem = {}
    for l in open("/proc/meminfo"):
        k, v = l.split(":", 1)
        mem[k] = int(v.split()[0]) / 1048576
    livre = mem["MemAvailable"]
    if livre < float(cfg("ram_minima_gb", 0.8)):
        alertas.append(("memoria", "alta", f"só {livre:.1f} GB de RAM livre: risco de travar; mande tarefas pesadas "
                                           "ao desktop ou feche o Docker/Brave"))
    import shutil
    disco = shutil.disk_usage("/")
    if disco.free / disco.total < 0.06:
        alertas.append(("disco", "media", f"disco com {disco.free / 2**30:.0f} GB livres"))
    for b in ("BAT0", "BAT1"):
        base = Path(f"/sys/class/power_supply/{b}")
        if base.exists():
            try:
                cap = int((base / "capacity").read_text())
                if cap < 15 and (base / "status").read_text().strip() == "Discharging":
                    alertas.append(("bateria", "media", f"bateria em {cap}%"))
            except (OSError, ValueError):
                pass
    for svc in cfg("servicos", ["ultron-telegram"]) or []:
        r = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
        if r.stdout.strip() not in ("active", "activating"):
            alertas.append((f"servico:{svc}", "media", f"o serviço {svc} está {r.stdout.strip() or 'parado'}"))
    try:
        from ferramentas.computacao import _maquina, _no_ar
        on = _no_ar(_maquina()[1])
        if _estado["desktop"] is not None and on != _estado["desktop"]:
            alertas.append(("desktop", "info", "o desktop ligou" if on else "o desktop desligou"))
        _estado["desktop"] = on
    except Exception:
        pass
    agora = time.time()
    novos = []
    for chave, sev, texto in alertas:
        if agora - _estado["avisos"].get(chave, 0) > 3600 or sev == "info":
            _estado["avisos"][chave] = agora
            eventos.emitir("module.status_changed", "sentinel", {"modulo": "sentinel", "mudanca": "alerta",
                                                                 "alerta": chave, "severidade": sev, "descricao": texto})
            novos.append((chave, sev, texto))
    return novos


def _laco():
    import fcntl
    trava = open(DADOS / "sentinel.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    while True:
        if ligado("eventos_sistema"):
            try:
                for chave, sev, texto in verificar_sistema():
                    if sev == "alta":
                        try:
                            from ferramentas.comunicacao import mandar_mensagem_celular
                            mandar_mensagem_celular(f"⚠️ Sentinel: {texto}")
                        except Exception:
                            pass
            except Exception:
                pass
        time.sleep(60)


def iniciar():
    global _iniciado
    if _iniciado or os.environ.get("NEURALINK_SEM_SERVICO"):
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True, name="sentinel").start()
