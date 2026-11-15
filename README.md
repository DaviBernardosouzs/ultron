# Ultron

Assistente de voz em português para a sua rede local. É o Ultron com a voz e o
humor seco do personagem, mas leal e sem planos de dominar o mundo.

Baseado na arquitetura do [jarvis-assistant-vocal](https://github.com/sosoj92/jarvis-assistant-vocal)
(MIT, © sosoj92): registro de ferramentas com `@ferramenta`, níveis de permissão
N1/N2/N3, cadeia voz → Whisper → LLM → fala e marcação de conteúdo não confiável.
Foi reescrito para Linux e pt-BR, com foco em controlar os dispositivos da rede.

## Começar

```fish
cd ~/ultron
# 1. coloque sua chave em .env (https://console.anthropic.com/settings/keys)
nano .env
# 2. ajuste config.yaml (seu nome, cidade, apelidos, computadores)
# 3. rode
uv run ultron.py --texto     # conversa pelo terminal
uv run ultron.py             # modo voz: diga "Ultron, ..."
```

Depois de instalado, de qualquer pasta:

```fish
ultron            # voz
ultron --texto    # terminal
```

Ou abra **Ultron** no menu de aplicativos do KDE. Clique com o botão direito no
ícone para ver a opção "modo texto". O lançador é o script `ultron`, ligado em
`~/.local/bin/ultron`; o atalho do menu está em `~/.local/share/applications/ultron.desktop`.

Na primeira execução no modo voz, ele baixa o modelo do Whisper (~500 MB).

## O que ele faz

| Área | Ferramentas | Nível |
|---|---|---|
| Rede | escanear a rede (avisa sobre dispositivos novos), inventário, ping, portas abertas, Wake-on-LAN, IP público, apelidos | N1 |
| Computadores (SSH) | listar, status, rodar comando, desligar/reiniciar | status N1, comando/desligar **N3** |
| Este PC | status, volume, abrir programa/site, bloquear tela | N1 |
| Este PC | rodar comando de shell | **N3** |
| Casa inteligente (Home Assistant) | listar e controlar luzes, tomadas, TV, ar etc. | N1 (destrancar fechadura é bloqueado) |
| Android (ADB) | listar, conectar, `adb shell` | shell N2 |
| Geral | hora, clima, lembrar/esquecer fatos | N1 |

| Máquinas | IDs `notebook` (este, Linux) e `desktop` (Windows), com apelidos em `hosts:`; abrir programa com janela em qualquer um | N1 |
| Modos | `dormir`, `trabalho`, `relaxar`, `jogar` (em `modos:` no config.yaml) | N1; com desligar, **N3** |
| Mídia | tocar/pausar/pular/status (MPRIS no notebook, teclas de mídia no desktop), buscar no Spotify, brilho | N1 |
| Web | pesquisar (Bing sem chave; Brave/Tavily se houver chave) e ler páginas | N1 |
| Agenda | compromissos e lembretes; avisa no Telegram na hora (ou X min antes) | N1 |

| Celular | "cadê meu celular?": toca no volume máximo pelo ADB (ou avisa no Telegram) | N1 |

**Senha ao abrir:** no modo voz e no modo texto, o Ultron pede a senha antes de
iniciar (falada ou digitada; números podem ser ditos por extenso). Três erros fecham
o programa e avisam no Telegram. Troque com `ultron definir-senha`; o `.env` guarda
só o hash. Desligue em `seguranca.senha_ao_abrir`.

**Janela (Ultron Console)** (`ultron janela`): interface visual local em Qt, sem navegador. Aura à
esquerda (clique no microfone para falar, ou ligue a escuta contínua "diga Ultron"), conversa no
centro (digite e Enter), e painéis de máquinas (com botão Ligar), modos, mídia, clima/agenda e
evolução à direita. Mesma senha, mesmas confirmações e mesmo cérebro; o terminal continua igual.
Também aparece no menu: clique direito no Ultron → "Ultron (janela)".

**Modo ambiente** (`ultron --ambiente`): o Ultron fica escondido no canto direito da tela e
aparece quando você diz "Ultron": um anel de luz (ciano ouvindo, vermelho falando, arco girando
pensando) com as últimas falas, e some sozinho quando a conversa acaba. Clique direito esconde.
Para abrir ao entrar no KDE: Configurações do Sistema > Inicialização automática > Adicionar
aplicativo, com o comando `/home/davi/ultron/ultron --ambiente`. Lado e posição em
`ambiente.lado` (direita/esquerda) e `ambiente.distancia_base`. Não rode o modo voz no terminal
ao mesmo tempo: os dois disputariam o microfone.

**Evolução supervisionada** (pacote `evolucao/`): quando falta uma capacidade, o Ultron registra a
necessidade, procura primeiro o que já existe (ferramentas, skills, plugins MCP, web) e, se você
concordar, desenvolve uma extensão Python, uma Skill ou um servidor MCP (TypeScript, SDK oficial).
Tudo é testado num sandbox `bwrap` (sem rede, sem credenciais, sem acesso à pasta pessoal,
com limites de memória/processos/tempo), comparado com a versão anterior e só então vira um
pedido de aprovação. **Só você aprova**:
```fish
ultron evolucao pendentes          # relatórios
ultron evolucao aprovar A0... N2   # N2 = a ferramenta pede confirmação (padrão)
ultron evolucao rollback NOME      # volta à versão anterior
ultron evolucao centro             # Evolution Center (janela)
```
Extensões ativas rodam sempre isoladas e não carregam se forem alteradas depois da aprovação.
O núcleo (`core/`, `ferramentas/`, `evolucao/`), as permissões e os logs nunca são alterados
pelo Ultron. Histórico em `dados/evolucao/historico.jsonl` e no cofre (`Evolução/`).

**Cérebro no Obsidian** (`~/Documentos/Ultron Cérebro`):
- `Personalidade/`: quem ele é. `Persona.md` e `História.md` entram direto no prompt, então dá
  para editar o jeito dele no Obsidian. Os limites de segurança ficam só no código.
- `Biblioteca/`: o saber dele (filosofia, estratégia, ciências, política, literatura, redes,
  cibersegurança, programação, IA), ligado pelo `Índice da Biblioteca`. A cada pedido, as
  seções mais relevantes entram no contexto sozinhas; ele também tem `consultar_biblioteca`.
  Notas novas em `Biblioteca/<Área>/` entram no índice quando o Ultron abre.
- `Memórias/`: o que ele aprende sobre você.

Na primeira vez que você abre o Ultron no dia, ele faz o **briefing**: clima, agenda,
e-mails e quais máquinas estão ligadas (desligue em `briefing.ativo`).

Os lembretes são enviados pelo processo que estiver com o agendador, normalmente o
serviço `ultron-telegram`. Mantenha esse serviço ligado para receber os avisos.

- **N1** executa direto.
- **N2** pede confirmação. Se você responder "sempre", ele não pergunta de novo (fica em `seguranca.sempre`).
- **N3** pede confirmação toda vez.

Tudo que ele executa fica registrado em `dados/auditoria.log`.

## Dando acesso aos dispositivos

**Computadores (Linux/Mac/Raspberry/Windows com OpenSSH):** crie uma chave só para o Ultron:

```fish
ssh-keygen -t ed25519 -f ~/.ssh/ultron -N ""
ssh-copy-id -i ~/.ssh/ultron.pub usuario@192.168.1.20
```

Depois adicione o computador em `hosts:` no `config.yaml`. O ideal é usar um
usuário sem sudo e liberar só os comandos necessários em `/etc/sudoers.d/`
(ex.: `systemctl poweroff`).

**Ligar PCs pela rede:** ative o Wake-on-LAN na BIOS e coloque o MAC em `dispositivos:`.

**Lâmpadas, tomadas, TVs, ar-condicionado:** a forma mais prática é o
[Home Assistant](https://www.home-assistant.io/), que integra quase todas as
marcas (Tuya/Smart Life, Xiaomi, Positivo, Philips Hue, Chromecast, LG/Samsung TV...).
Coloque a URL em `casa.url` e um token de longa duração em `HOME_ASSISTANT_TOKEN`.

**Celulares/TV Android:** ative "Depuração sem fio" e peça "Ultron, conecta no Android 192.168.1.38:5555".

**Roteador:** muitos roteadores (incluindo o ZTE da sua rede) têm uma integração
no Home Assistant ou uma interface web. Dá pra criar uma ferramenta específica.

## Ultron no celular (Telegram)

1. No Telegram, fale com o **@BotFather** → `/newbot` → escolha nome (ex.: Ultron) e usuário.
2. Rode `ultron configurar-telegram` num terminal. Ele pede o token, espera você mandar
   uma mensagem pro bot, grava seu ID como dono e liga o serviço `ultron-telegram`.
   Só esse ID é obedecido.
Aceita texto e áudio; se você mandar áudio, ele responde também com áudio na voz dele.
Ações críticas pedem confirmação por botão, ou pelo PIN se `telegram.pin` estiver definido.

## E-mail próprio

Crie uma conta Gmail para o Ultron, ative a verificação em duas etapas e gere uma
**senha de app**. Coloque o endereço em `email.endereco` e a senha em `EMAIL_SENHA`.
Ele lê a caixa de entrada dele, envia para você sem perguntar, e para terceiros só com confirmação.

## Acesso de fora de casa

O bot do Telegram já funciona de qualquer lugar, sem abrir portas no roteador.
Para você (ou o Ultron) alcançar os outros computadores da casa pela internet,
use o Tailscale (VPN privada entre os seus aparelhos):
```fish
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up --ssh
```
Instale o app Tailscale no celular com a mesma conta. Nunca faça redirecionamento
de portas no roteador para o Ultron.

## NEURALINK (conhecimento e memória)

`ultron neuralink` abre o grafo de conhecimento, a busca universal, o gerenciador de memória, a
linha do tempo e as fontes autorizadas. O Ultron usa tudo isso sozinho: a cada pedido, os
trechos relevantes dos documentos autorizados entram no contexto (com a fonte), e ele tem
ferramentas como `buscar_documentos`, `contexto_projeto`, `lembrar_informacao` e
`resumir_projeto`. Só lê pastas que você autorizar. Detalhes em `docs/NEURALINK.md`.

## Módulos (Guardian, Chronos, eventos)

`ultron modulos` (ou o botão MÓDULOS): o **Guardian** decide antes de qualquer ferramenta rodar
(políticas por workspace, diretórios autorizados, pedidos do Ultron que só você concede,
incidentes); o **Chronos** mostra a linha do tempo e compara períodos ("o que mudou esta semana?");
**Eventos** mostra o barramento ao vivo (`task.*`, `tool.*`, `approval.*`), agrupado por operação.
Plano dos próximos módulos e da ponte com o Claude Code: `docs/PLANO-MODULOS.md`.

## Evolution Forge

`ultron evolucao centro` (ou o botão EVOLUTION CENTER) abre a Forja: estado do sistema,
registro de capacidades, Approval Gateway, autodiagnóstico (log, testes, dependências,
integrações e latência real) e versões/rollback. A janela antiga continua em
`ultron evolucao centro-classico`.

## Força do desktop (processos pesados)

O notebook tem 7 GB de RAM e trava quando é sobrecarregado. Por isso o Ultron usa o PC de mesa
(20 GB de RAM, 12 threads, RX 6700 XT) sozinho quando você pede algo pesado: build,
`npm install`, compilar, testes longos, converter vídeo, IA local. Basta pedir normalmente
("faz o build do projeto X", "converte esse vídeo"). Ele escolhe a máquina e diz onde rodou.

| Ferramenta | O que faz | Nível |
|---|---|---|
| `recursos_maquinas` | CPU, RAM, GPU e VRAM reais das duas máquinas e onde convém rodar | N1 |
| `enviar_tarefa_desktop` | copia a pasta (sem `node_modules`, `.venv`, `dist`...), roda o comando em segundo plano no desktop e devolve um ID | **N3** |
| `status_tarefa_desktop` | rodando, concluída ou falhou (com o código de saída) e o fim da saída | N1 |
| `cancelar_tarefa_desktop` | mata o processo e os filhos | N2 |
| `trazer_resultado_desktop` | traz arquivos para `dados/do-desktop/<id>/` (ou para um destino, com confirmação) | N1/N2 |
| `ia_local_desktop` | modelo do Ollama na GPU do desktop, sem gastar cota da nuvem | N1 |
| `tunel_desktop` | serviço do desktop (ex.: porta 4173) abre em `localhost` no notebook | N1 |

Se o desktop estiver desligado, ele acorda pela rede (`computacao.ligar_automatico`).
As tarefas rodam fora da sessão SSH (via WMI), então continuam mesmo se o notebook
desconectar. Ficam em `C:\Users\davib\ultron\trabalhos\<id>\` (`saida.log`, `codigo.txt`).
O Ollama é acessado por túnel SSH, então a porta 11434 continua fechada no firewall.
Os comandos rodam no PowerShell 5.1 do Windows; `&&` é convertido automaticamente.
O WSL do desktop não funciona enquanto a virtualização estiver desligada na BIOS.

## MCP (outros computadores usam o Ultron)

`ultron --mcp` sobe um servidor MCP em `http://<ip-do-notebook>:8765/mcp` para o Claude
Code, Claude Desktop, Cursor etc. dos outros PCs da casa. Ele exige o token
`ULTRON_MCP_TOKEN` (criado sozinho no `.env`) e só aceita IPs da rede local.
Ações N1 e N2 ficam liberadas, e as N3 (shell, desligar, e-mail) só se você listar em
`mcp.permitir_n3`. Também há a ferramenta `pedir_ao_ultron`, que passa o pedido pelo
cérebro dele. Para deixar sempre ligado:
```fish
systemctl --user enable --now ultron-mcp
```
No cliente: `claude mcp add --scope user --transport http ultron http://192.168.1.106:8765/mcp --header "Authorization: Bearer <token>"`.

## Voz

`voz.efeito: ultron` deixa a voz pt-BR do Piper mais grave e metálica (ffmpeg).
Amostras de cada combinação ficam em `dados/amostras/`.

## Segurança

- Não exponha o Ultron na internet. Para acessar de fora, use Tailscale/WireGuard.
- Varreduras e ping ficam limitados a IPs privados.
- Saídas de comandos e nomes de dispositivos são marcados como não confiáveis, para
  que um texto malicioso num dispositivo não consiga dar ordens ao Ultron.
- As ações críticas sempre passam por você.

## Adicionar uma ferramenta

Crie um arquivo em `ferramentas/`:

```python
from core.registro import ferramenta

@ferramenta("minha_acao", "O que ela faz (o modelo lê isso).",
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            nivel="N2", resumo=lambda a: f"fazer algo com {a['x']}")
def minha_acao(x):
    return "resultado em texto"
```

Ela é carregada automaticamente.

## Configuração útil

- `ia.esforco`: `low` responde mais rápido; `medium`/`high` raciocina mais em tarefas complexas.
- `whisper.modelo`: `base` se o reconhecimento estiver lento, `medium` se estiver errando muito.
- `voz.piper`: troque a voz (`pt_BR-cadu-medium`, `pt_BR-jeff-medium`).
- `audio.microfone`: índice listado por `uv run python -m sounddevice`.
