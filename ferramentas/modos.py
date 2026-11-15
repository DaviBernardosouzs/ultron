"""Modos: um comando de voz dispara vários passos ("Ultron, modo dormir").

Os modos ficam no config.yaml, em 'modos'. Passos aceitos:
  {acao: ligar,    maquina: desktop}                # Wake-on-LAN + espera o SSH responder
  {acao: abrir,    maquina: notebook|desktop, programa: ..., argumentos: [...]}
  {acao: brilho,   nivel: 50}                       # notebook
  {acao: volume,   nivel: 30}                       # notebook
  {acao: midia,    comando: pausar|tocar|..., maquina: notebook}
  {acao: luzes,    estado: desligar|ligar}          # Home Assistant
  {acao: bloquear}                                  # bloqueia a tela do notebook
  {acao: desligar, maquina: notebook|desktop}       # o notebook é sempre o último
"""
import time

from core.config import ajuste
from core.registro import ferramenta


def _modos():
    return ajuste("modos", {}) or {}


def _achar(nome):
    alvo = nome.strip().lower().removeprefix("modo ").strip()
    for chave, m in _modos().items():
        if alvo == chave.lower() or alvo in [a.lower() for a in m.get("apelidos", [])]:
            return chave, m
    raise ValueError(f"não existe o modo '{nome}'. Modos: {', '.join(_modos()) or 'nenhum'}")


def _critico(m):
    return any(p.get("acao") == "desligar" for p in m.get("passos", []))


def _nivel(args):
    try:
        chave, m = _achar(args.get("nome", ""))
    except ValueError:
        return "N1", "ativar_modo"
    return ("N3" if _critico(m) else "N1"), f"ativar_modo:{chave}"


def _resumo(args):
    try:
        chave, m = _achar(args.get("nome", ""))
    except ValueError:
        return f"ativar o modo {args.get('nome')}"
    desl = [p.get("maquina", "?") for p in m.get("passos", []) if p.get("acao") == "desligar"]
    return f"ativar o modo {chave}" + (f" (desliga {' e '.join(desl)})" if desl else "")


def _passo(p):
    acao = p.get("acao")
    maquina = p.get("maquina", "notebook")
    if acao == "ligar":
        return ligar_e_esperar(maquina, int(p.get("espera_max", 150)))
    if acao == "abrir":
        from ferramentas.ssh import abrir_em
        return abrir_em(maquina, p["programa"], p.get("argumentos"))
    if acao == "brilho":
        from ferramentas.midia import brilho
        return brilho(p.get("nivel", 50))
    if acao == "volume":
        from ferramentas.sistema import volume
        return volume(nivel=p.get("nivel"))
    if acao == "midia":
        from ferramentas.midia import midia
        return midia(p.get("comando", "pausar"), busca=p.get("busca"), computador=maquina)
    if acao == "bloquear":
        from ferramentas.sistema import bloquear_tela
        return bloquear_tela()
    if acao == "luzes":
        from ferramentas.casa import _api
        servico = "turn_on" if p.get("estado") == "ligar" else "turn_off"
        _api("POST", f"services/light/{servico}", json={"entity_id": p.get("entidade", "all")})
        return f"luzes {'acesas' if servico == 'turn_on' else 'apagadas'}"
    if acao == "desligar":
        from ferramentas.ssh import desligar_computador
        return desligar_computador(maquina)
    return f"passo desconhecido: {acao}"


def _no_ar(endereco, porta=22):
    import socket
    try:
        socket.create_connection((endereco, porta), timeout=2).close()
        return True
    except OSError:
        return False


def ligar_e_esperar(maquina, espera_max=150):
    """Wake-on-LAN e espera o SSH responder (o Windows terminou de subir)."""
    from ferramentas.rede import ligar_dispositivo_wol
    from ferramentas.ssh import _host
    nome, h = _host(maquina)
    if h.get("local"):
        return f"{nome} já está ligado (é onde eu rodo)."
    if _no_ar(h["endereco"], h.get("porta", 22)):
        return f"{nome} já estava ligado."
    ligar_dispositivo_wol(nome)
    inicio = time.time()
    while time.time() - inicio < espera_max:
        time.sleep(5)
        if _no_ar(h["endereco"], h.get("porta", 22)):
            time.sleep(int(ajuste("modos_espera_login", 15)))   # tempo para a área de trabalho carregar
            return f"{nome} ligado em {int(time.time() - inicio)} s."
    raise TimeoutError(f"{nome} não respondeu em {espera_max} s (está no cabo e com WoL na BIOS?)")


@ferramenta(
    "ligar_computador",
    "Liga uma máquina da casa pela rede (Wake-on-LAN) e espera ela ficar pronta. Use para "
    "'liga o computador/desktop/pc'.",
    {"type": "object", "properties": {"computador": {"type": "string", "default": "desktop"}}})
def ligar_computador(computador="desktop"):
    return ligar_e_esperar(computador)


@ferramenta(
    "ativar_modo",
    "Ativa um modo (rotina com vários passos) pelo nome: ex.: dormir, trabalho, relaxar, "
    "jogar. Use quando o Davi disser 'modo X' ou algo equivalente ('vou dormir', 'bora jogar').",
    {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]},
    nivel="N1", resumo=_resumo, nivel_dinamico=_nivel)
def ativar_modo(nome):
    chave, m = _achar(nome)
    passos = list(m.get("passos", []))
    # Desligar o notebook mata o próprio Ultron: sempre por último.
    passos.sort(key=lambda p: p.get("acao") == "desligar" and p.get("maquina", "notebook") == "notebook")
    resultados = []
    for p in passos:
        try:
            resultados.append(f"- {p.get('acao')}: {_passo(p)}")
        except Exception as e:
            resultados.append(f"- {p.get('acao')} ({p.get('maquina', 'notebook')}): falhou ({e})")
        time.sleep(p.get("espera", 0.3))
    return f"Modo {chave}:\n" + "\n".join(resultados)


@ferramenta("listar_modos", "Lista os modos configurados e o que cada um faz.")
def listar_modos():
    modos = _modos()
    if not modos:
        return "Nenhum modo em 'modos' no config.yaml."
    return "\n".join(f"{n}: {m.get('descricao', '')} ({len(m.get('passos', []))} passos)"
                     for n, m in modos.items())
