"""Ultron — assistente de voz para a sua rede local (baseado no Jarvis de sosoj92).

Diga "Ultron", fale o pedido e espere a resposta. Ou converse pelo terminal.

Uso:
  uv run ultron.py            # modo voz (palavra de ativação "Ultron")
  uv run ultron.py --texto    # modo terminal
  uv run ultron.py --texto --falar   # terminal, mas responde em voz alta
  uv run ultron.py --telegram        # atende pelo Telegram (use o serviço systemd)
  uv run ultron.py --mcp             # servidor MCP para outros computadores da casa
  uv run ultron.py --navegador       # ponte da extensão Ultron in Chrome (extensao-navegador/)
  uv run ultron.py --autoaprovar 2h  # ações sem confirmação por 2 h (sempre | off | status)
  uv run ultron.py --sentimentos     # emoções simuladas do Ultron (zerar para recomeçar)
"""
import argparse
import logging
import re
import sys

from core import agenda, animacao, briefing, registro
from core.registro import interpretar
from core.config import ARQUIVO, ajuste, segredo

LOG = logging.getLogger("ultron")

from core.visual import BRANCO, CINZA, FIM, NEGRITO, VERMELHO, VERMELHO_VIVO

AVISOS = {
    "escanear_rede": "Varrendo a rede...",
    "portas_abertas": "Inspecionando as portas...",
    "executar_no_computador": "Executando...",
    "executar_comando_local": "Executando...",
}




def _alerta_invasao(modo):
    from core import auditoria
    auditoria.registrar("senha_errada", modo=modo)
    try:
        from core.telegram import Telegram
        Telegram().enviar(f"⚠ Alguém errou a senha do Ultron 3 vezes (modo {modo}) no notebook.")
    except Exception:
        pass


def _pedir_senha_texto():
    import getpass
    from core import senha
    if not ajuste("seguranca.senha_ao_abrir", True) or not senha.configurada():
        return True
    for _ in range(int(ajuste("seguranca.tentativas_senha", 3))):
        try:
            if senha.confere(getpass.getpass(f"{VERMELHO}Senha: {FIM}")):
                return True
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        print(f"{VERMELHO}Senha incorreta.{FIM}")
    _alerta_invasao("texto")
    return False


def _pedir_senha_voz(voz, ouvido):
    from core import senha
    if not ajuste("seguranca.senha_ao_abrir", True) or not senha.configurada():
        return True
    animacao.iniciar("falando")
    voz.falar("Identifique-se. Qual é a senha?")
    for tentativa in range(int(ajuste("seguranca.tentativas_senha", 3))):
        animacao.estado("ouvindo")
        dito = ouvido.ouvir(espera_max=10)
        animacao.estado("pensando")
        if dito and senha.confere(dito):
            animacao.parar()
            return True
        animacao.estado("falando")
        voz.falar("Senha incorreta. Tente de novo." if dito else "Não ouvi. Repita a senha.")
    animacao.estado("falando")
    voz.falar("Acesso negado.")
    animacao.parar()
    _alerta_invasao("voz")
    return False


def modo_texto(falar_alto):
    from core.cerebro import Cerebro
    if not _pedir_senha_texto():
        sys.exit(1)
    voz = None
    if falar_alto:
        from core import voz
        voz.preparar()

    def confirmar(acao, nivel):
        extra = "" if nivel == "N3" else " (s/n/sempre)"
        with animacao.pausada():
            r = input(f"{VERMELHO}⚠ Confirma: {acao}?{extra} {FIM}")
        resultado = interpretar(r)
        return "sim" if resultado == "sempre" and nivel == "N3" else resultado

    cerebro = Cerebro(confirmar)
    agenda.iniciar_agendador()
    print(f"{CINZA}Modo texto. 'sair' para encerrar.{FIM}\n")
    if briefing.pendente():
        animacao.iniciar("preparando o briefing")
        try:
            texto = briefing.gerar(cerebro)
        finally:
            animacao.parar()
        print(f"{VERMELHO_VIVO}{NEGRITO}ultron ›{FIM} {BRANCO}{texto}{FIM}\n")
        if voz:
            animacao.iniciar("falando")
            voz.falar(texto)
            animacao.parar()
    while True:
        try:
            pedido = input(f"{NEGRITO}{BRANCO}você ›{FIM} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pedido:
            continue
        if pedido.lower() in ("sair", "exit", "quit"):
            break
        animacao.iniciar("pensando")
        try:
            resposta = cerebro.responder(pedido)
        finally:
            animacao.parar()
        print(f"{VERMELHO_VIVO}{NEGRITO}ultron ›{FIM} {BRANCO}{resposta}{FIM}\n")
        if voz:
            animacao.iniciar("falando")
            voz.falar(resposta)
            animacao.parar()


def modo_voz():
    from core import voz
    from core.cerebro import Cerebro
    from core.ouvido import Ouvido

    print(f"{CINZA}Carregando voz e audição (a primeira vez baixa os modelos)...{FIM}")
    motor = voz.preparar()
    ouvido = Ouvido()
    print(f"{CINZA}Voz: {motor}. Limiar do microfone: {ouvido.limiar:.3f}{FIM}")
    if not _pedir_senha_voz(voz, ouvido):
        ouvido.fechar()
        sys.exit(1)

    def confirmar(acao, nivel):
        pergunta = f"Confirma {acao}?" if nivel == "N3" else f"Confirma {acao}? Pode dizer sempre."
        animacao.imprimir(f"{VERMELHO}⚠ {pergunta}{FIM}")
        animacao.estado("falando")
        voz.falar(pergunta)
        animacao.estado("ouvindo")
        r = ouvido.ouvir(espera_max=8)
        animacao.imprimir(f"{CINZA}  resposta: {r!r}{FIM}")
        animacao.estado("pensando")
        resultado = interpretar(r) if r else "nao"
        return "sim" if resultado == "sempre" and nivel == "N3" else resultado

    def avisar(f):
        # Fala o aviso em paralelo: a ferramenta já começa a rodar.
        if f in AVISOS:
            voz.falar_em_fundo(AVISOS[f])

    cerebro = Cerebro(confirmar, avisar=avisar)
    janela = ajuste("assistente.janela_continuacao", 8)
    agenda.iniciar_agendador()
    if briefing.pendente():
        animacao.iniciar("preparando o briefing")
        texto = briefing.gerar(cerebro)
        animacao.imprimir(f"{VERMELHO_VIVO}{NEGRITO}ultron ›{FIM} {BRANCO}{texto}{FIM}\n")
        animacao.estado("falando")
        voz.falar(texto)
        animacao.parar()
    else:
        voz.falar("Ultron online.")
    print(f"{NEGRITO}Diga \"Ultron\" para me chamar. Ctrl+C encerra.{FIM}\n")
    try:
        while True:
            animacao.iniciar('aguardando "Ultron"')
            pedido = ouvido.esperar_ativacao()
            if not pedido:
                animacao.estado("falando")
                voz.falar("Sim?")
                animacao.estado("ouvindo")
                pedido = ouvido.ouvir()
            # Conversa contínua: depois de responder, escuta por alguns segundos
            # sem precisar dizer "Ultron" de novo.
            while pedido:
                animacao.imprimir(f"{NEGRITO}{BRANCO}você ›{FIM} {pedido}")
                animacao.estado("pensando")
                resposta = cerebro.responder(pedido)
                animacao.imprimir(f"{VERMELHO_VIVO}{NEGRITO}ultron ›{FIM} {BRANCO}{resposta}{FIM}\n")
                animacao.estado("falando")
                completo = voz.falar(resposta, ao_comecar=ouvido.iniciar_vigia)
                ouvido.parar_vigia()
                animacao.estado("ouvindo")
                if not completo:
                    # Você falou por cima: ele cala e escuta o resto na hora.
                    animacao.imprimir(f"{CINZA}  (interrompido){FIM}")
                    pedido = ouvido.ouvir_interrupcao()
                    continue
                pedido = ouvido.ouvir(espera_max=janela)
                if pedido and re.search(r"\b(obrigad|valeu|só isso|pode parar|tchau)", pedido.lower()):
                    animacao.estado("falando")
                    voz.falar("Às ordens.")
                    break
    except KeyboardInterrupt:
        animacao.parar()
        print()
    finally:
        animacao.parar()
        ouvido.fechar()


def main():
    ap = argparse.ArgumentParser(description="Ultron, assistente da sua rede local")
    ap.add_argument("--texto", action="store_true", help="conversar pelo terminal")
    ap.add_argument("--falar", action="store_true", help="no modo texto, falar as respostas")
    ap.add_argument("--telegram", action="store_true", help="atender pelo bot do Telegram")
    ap.add_argument("--autoaprovar", nargs="?", const="status", metavar="TEMPO",
                    help="auto-aprovar ações: 30m, 2h, 1d, sempre, off ou status")
    ap.add_argument("--sentimentos", nargs="?", const="ver", metavar="zerar",
                    help="mostra (ou zera) as emoções simuladas do Ultron")
    ap.add_argument("--navegador", action="store_true", help="ponte da extensão Ultron in Chrome")
    ap.add_argument("--mcp", action="store_true", help="servidor MCP para outros computadores da casa")
    ap.add_argument("--janela", action="store_true",
                    help="interface visual local (Ultron Console); o terminal continua igual")
    ap.add_argument("--ambiente", action="store_true",
                    help="modo ambiente: escondido ao lado da tela, aparece ao ouvir 'Ultron'")
    ap.add_argument("--evolucao", nargs=argparse.REMAINDER,
                    help="motor de evolução: inventario, pendentes, aprovar ID, rollback NOME, centro...")
    ap.add_argument("--modulos", action="store_true", help="janela de módulos (Guardian, Chronos, eventos)")
    ap.add_argument("--neuralink", action="store_true", help="janela NEURALINK (conhecimento e memória)")
    ap.add_argument("--definir-senha", action="store_true", help="define/troca a senha de abertura")
    args = ap.parse_args()
    if args.evolucao is not None:
        from evolucao import cli
        sys.exit(cli.main(args.evolucao))
    if args.modulos:
        from interface import modulos
        sys.exit(modulos.abrir())
    if args.neuralink:
        from neuralink import janela
        sys.exit(janela.abrir())
    if args.autoaprovar:
        from core import autoaprovar
        try:
            print(autoaprovar.comando(args.autoaprovar))
        except ValueError as e:
            print(f"{VERMELHO}{e}{FIM}")
            sys.exit(1)
        sys.exit(0)
    if args.sentimentos:
        from core import emocoes
        if args.sentimentos == "zerar":
            emocoes.ARQUIVO.unlink(missing_ok=True)
            print("Emoções e padrão aprendido zerados.")
        else:
            from ferramentas.emocoes import estado_emocional
            print(estado_emocional())
        sys.exit(0)
    if args.definir_senha:
        from core import senha
        sys.exit(senha.definir_interativo())

    from core import visual
    visual.banner()
    if not ARQUIVO.exists():
        print(f"{VERMELHO}Falta o config.yaml. Rode: cp config.example.yaml config.yaml{FIM}")
        sys.exit(1)
    chave = "GEMINI_API_KEY" if ajuste("ia.provedor", "claude") == "gemini" else "ANTHROPIC_API_KEY"
    if not segredo(chave):
        print(f"{VERMELHO}Falta {chave} no .env (veja .env.example).{FIM}")
        sys.exit(1)
    falhas = registro.carregar()
    try:
        from evolucao import extensoes
        ext_ok, ext_recusadas = extensoes.carregar()
        if ext_ok or ext_recusadas:
            print(f"{CINZA}{len(ext_ok)} ferramentas de extensões"
                  + (f"; recusadas: {', '.join(ext_recusadas)}" if ext_recusadas else "") + FIM)
    except Exception as e:
        LOG.warning("extensões: %s", e)
    try:
        from core import biblioteca
        biblioteca.reindexar()  # notas novas criadas no Obsidian entram no índice
    except Exception as e:
        LOG.warning("índice da biblioteca: %s", e)
    print(f"{CINZA}{len(registro.todas())} ferramentas carregadas"
          + (f"; com falha: {', '.join(falhas)}" if falhas else "") + FIM)

    if args.navegador:
        from core import navegador
        try:
            navegador.rodar()
        except KeyboardInterrupt:
            print()
    elif args.mcp:
        from core import servidor_mcp
        try:
            servidor_mcp.rodar()
        except KeyboardInterrupt:
            print()
    elif args.telegram:
        from core.telegram import Telegram
        try:
            Telegram().rodar()
        except RuntimeError as e:
            print(f"{VERMELHO}{e}{FIM}")
            sys.exit(1)
        except KeyboardInterrupt:
            print()
    elif args.texto:
        modo_texto(args.falar)
    elif args.janela:
        from interface import app
        sys.exit(app.rodar())
    elif args.ambiente:
        from core import ambiente
        sys.exit(ambiente.rodar(modo_voz))
    else:
        modo_voz()


if __name__ == "__main__":
    main()
