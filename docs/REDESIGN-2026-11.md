# Ultron — revisão desktop de novembro de 2026

## Implementação e auditoria

Aplicação local em PySide6/Qt Widgets; renderização QPainter, pixmaps em cache e QSS.
A inspeção foi realizada em janelas abertas no KDE/Wayland. Capturas de janela por
`QWidget.grab()` e capturas do compositor por Spectacle. Nenhum screenshot de site
foi usado como substituto do desktop. A tela principal e o terminal foram abertos
pelo lançador real; as outras capturas usam os próprios construtores das janelas.

O frontend recebe mensagens por sinais Qt (`Ponte`), consulta o estado e amplitude
em `core.animacao` e lê eventos de `core.eventos`. Voz e cérebro trabalham em threads.
O redesign não modifica o backend nem os contratos de eventos.

O tema anterior tinha fundo vinho, contornos saturados em todos os painéis, núcleo
superexposto em ouro, conversa estreita e navegação horizontal que escondia módulos.
As capturas de referência local estão em `capturas/redesign/antes.png` e nas pastas
`ultron-before-*`. Backup do código anterior nesta sessão: `/tmp/ultron-interface-before.tgz`.

## Design system

`interface/design.py` é a fonte compartilhada de cores, tipografia, superfícies,
controles, estados de foco, tabelas, scrollbars e navegação. As quatro janelas usam
esse tema. Os desenhos QPainter em `hud.py` usam os mesmos tokens básicos.

| Papel | Valor |
|---|---|
| Fundo | #050507 |
| Superfície | #111216 |
| Metal / divisores | #24262C |
| Ação principal | #C8102E |
| Energia / seleção | #FF243F |
| Texto | #E6E8EC |
| Informação secundária | #858B96 |
| Texto corrido | Fira Sans, 13–15 px |
| Instrumentação | FiraCode Nerd Font, 11–12 px |
| Espaçamento | 4, 8, 12, 16, 24, 32 px |
| Transição de módulo | 180 ms, OutCubic, opacidade |

Superfícies foscas substituem colchetes luminosos. Vermelho identifica seleção,
atividade e envio; tipografia neutra sustenta leitura longa. Tabelas dimensionam
cabeçalhos pelo conteúdo; listas e tabelas mantêm rolagem quando necessário.

## Composição e estados

A janela inicia com núcleo à esquerda e conversa à direita, separados por splitter
redimensionável. Sistema/voz e contexto são docks recolhíveis, flutuantes e móveis.
Navegação superior leva ao Neuralink, Forge, módulos e terminal. A janela principal
foi inspecionada em 1360×840 e 900×620 unidades Qt (a captura reflete o DPI do desktop).

O núcleo tem segmentos orbitais independentes, camadas de telemetria, luz carmesim,
centro energético, paralaxe e suavização de amplitude. As barras continuam sendo
CPU/RAM/GPU reais; os segmentos mecânicos são movimento visual, não métricas.

- Repouso: rotação lenta, aproximadamente 10–12 quadros/s efetivos.
- Ouvindo/falando: amplitude recebida do backend, sem amplitude fictícia de tarefa.
- Pensando: velocidades diferentes por camada.
- Pesquisa: aceleração adicional quando o estado informa pesquisa/busca.
- Executando: estado textual da ação e movimento mais intenso.
- Aprovação: sinal real de confirmação ativa reduz o movimento até a decisão.
- Erro: falha nova do barramento gera indicação breve e pulso lento; eventos
  históricos carregados ao abrir a janela não disparam erro.

HUD mostra estado, tempo de atividade e **modelo configurado**. Gemini pode usar
fallback; o rótulo não afirma qual modelo respondeu porque esse dado não é exposto
pela interface atual do cérebro. Não foram inventados percentuais de conclusão.

Movimento reduzido congela o relógio visual e as rotações do núcleo. O checkbox vale
para a janela atual; `visual.movimento_reduzido` configura a preferência na abertura
e é respeitado pela navegação. Neuralink reduz repaints; Forge pausa atualização da
aura quando escondido/minimizado. O núcleo e medidores param com a janela minimizada.

## Validação

- Suíte final: **83 passed, 1 skipped**, saída normal (código 0).
- Testes novos: acesso bidirecional da navegação, amplitude real com movimento
  reduzido, ausência de movimento oculto e limite do cache após redimensionamentos.
- Corrigido isolamento do teste temporal: ele lia eventos do banco Neuralink real
  e agenda real. Fontes agora isoladas na fixture, sem alteração de regra de negócio.
- Conversação real: o backend respondeu “Canal de comunicação operacional.” à
  mensagem curta enviada pelo campo da janela. Captura em `ultron-cycle3-main/conversa.png`.
- Terminal real abriu com 127 ferramentas carregadas e prompt de texto disponível;
  captura `terminal.png`. O lançador e as regras do terminal permanecem operacionais.
- Todas as 15 abas de módulos abriram sem aba de erro; suíte inclui Claude Bridge,
  Workspaces, Guardian, Cortex, Vector e Synapse. Não foram disparadas ações externas
  de todos os módulos apenas para demonstrar o visual.

Ciclos visuais da principal: primeiro tema/composição; segundo estado/modelo;
terceiro janela pequena/docks/conversa; revisão final removeu sobreposição entre
legendas e núcleo. No Forge, a revisão detectou e corrigiu fundo herdado do sistema.
Nos módulos, foram corrigidos navegação oculta e cabeçalhos estreitos. Neuralink teve
contraste das conexões e reflexo reduzidos. Arquivos dos ciclos estão em
`capturas/redesign/`; os nomes identificam as etapas e telas.

Scripts reproduzíveis (rodar em sessão gráfica, não offscreen):

```sh
.venv/bin/python scripts/capture_desktop.py main /tmp/ultron-main
.venv/bin/python scripts/capture_desktop.py modules /tmp/ultron-modules
.venv/bin/python scripts/capture_desktop.py neural /tmp/ultron-neural
.venv/bin/python scripts/capture_desktop.py forge /tmp/ultron-forge
.venv/bin/python scripts/measure_desktop.py
.venv/bin/python -m pytest -q
```

CPU medida pelo tempo de CPU do processo dividido pelo tempo real, em amostras de
seis segundos, após cinco segundos de inicialização; valores são de **um núcleo**:

| Estado | CPU | Pico RSS do processo |
|---|---:|---:|
| Repouso | 11,4% | 528 MB |
| Movimento reduzido | 5,2% | 528 MB |
| Minimizada | 0,8% | 528 MB |

Inclui cérebro/Qt/telemetria e threads. Não é benchmark isolado de GPU nem prova de
60 fps; repaints são deliberadamente limitados em repouso. RSS é pico acumulado.

## Limitações e escopo preservado

- World Observation é um projeto web separado, `ultron-geospatial/gods-eye-view`,
  não um módulo Qt desta aplicação. Globo, fontes e código desse projeto não foram
  alterados nem validados por esta revisão desktop.
- Voz física (microfone e saída), aprovações reais de ações críticas e todos os
  serviços externos não tiveram validação ponta a ponta nesta sessão. Suas conexões
  foram preservadas; testes automatizados e abertura de telas não substituem isso.
- Redução de movimento não é uma configuração global editável pela nova checkbox;
  apenas núcleo na sessão. A preferência persistente permanece no config.yaml.
- Algumas cores específicas do grafo e rótulos legados ainda estão locais; a base
  compartilhada cobre controles e superfícies, sem reescrever todas as primitivas.
- Docks simultâneos podem exigir janela mais larga; podem ser destacados ou fechados.
- Animações por notificação/sessão e um HUD completo de executor/checkpoints ainda
  dependem de contratos que não estão presentes em todas as telas atuais.

Skill consultada: `premium-frontend-ui`, adaptada ao Qt. As skills frontend-design,
UI UX Pro Max e Superpowers citadas não foram encontradas na busca local; não foram
instaladas ferramentas web para substituir a aplicação desktop.

## Botão de modo de canto

O botão **MODO DE CANTO** na barra superior incorpora o overlay existente de
`core.ambiente` à mesma aplicação Qt e sessão do cérebro. Ativa a escuta contínua
e minimiza o painel. O orbe aparece ao chamar “Ultron”, como no modo ambiente original.
Para desativar, reabra o painel pela barra de tarefas e clique novamente no botão;
a configuração de escuta anterior é restaurada. Aprovações fazem o painel reaparecer.
Fechar o painel encerra também o overlay incorporado. O comando `ultron --ambiente`
continua usando seu laço independente de voz.

Validação: cinco testes de interface passaram, incluindo overlay incorporado sem
nova thread de voz ou novo event loop; botão inspecionado na janela desktop a 900×620.
Teste não inclui reconhecimento físico do microfone. Captura: `capturas/redesign/botao-modo-canto.png`.

## Auditoria de aceitação ASTRA (08/11/2026, 2ª passada)

Capturas reais (Spectacle/Wayland e `scripts/capture_desktop.py`) da principal, NEURALINK, Forja e de
todas as abas de módulos. Em `capturas/redesign/aceitacao/`.

Defeitos encontrados e corrigidos:
- O script de captura fotografava o Evolution Center **antigo** (`evolucao/centro.py`); o botão abre a
  Forja nova (`evolucao/forja.py`). Script corrigido (`forge` = Forja, `forge_classico` = antiga).
  A Forja já herdava o design system pelos componentes compartilhados; o log dela tinha barra de
  rolagem horizontal fora do padrão (removida, texto com reticências).
- NEURALINK: retângulos de "telas" no fundo eram decoração sem função (removidos); fios rosados
  passaram ao carmesim do sistema (#C8102E/#FF243F); nomes dos nós ilegíveis sobre os fios (placa
  escura, folga entre nomes, só os 16 mais conectados); Explorador vazio desperdiçava três caixas
  (agora mostra as entidades mais conectadas, clicáveis, e o histórico real de indexação). 3 ciclos.
- HUD da principal: além de estado e modelo que respondeu, ganhou a linha de operação com dados
  reais do barramento: executor (Claude Code quando há tarefa), ferramenta em curso, operações
  concluídas/falhas do pedido, plano do Vector com etapa atual e aprovações pendentes.

Critérios de aceitação: aplicação funcionando; design system único (`interface/design.py`, também na
Forja e no NEURALINK); núcleo com estados reais (espera, ouvindo/falando com amplitude real,
pensando, pesquisando com radar, executando com o nome da ferramenta, aprovação, erro); terminal
preservado; legível em 1360×840 e 900×620; suíte 112 testes (3 rodadas); repouso 11,8% de um núcleo,
movimento reduzido 5,2%, minimizada 0,8%.

Limitações que continuam:
- Skills citadas no prompt (frontend-design, UI UX Pro Max, Superpowers) não estão instaladas; o
  ciclo de validação foi feito manualmente com capturas reais.
- GPU não medida: o notebook tem iGPU AMD sem ferramenta de uso por processo; o QPainter desenha na CPU.
- WORLD OBSERVATION não existe na interface: o God's Eye View exige Node 24 no desktop (há Node 22).
- Microinterações: transição de 180 ms nos módulos e nos estados do núcleo; notificações e aprovações
  ainda usam diálogos do sistema, sem animação própria.
- Não há tela "SYSTEM INTELLIGENCE" dedicada: hardware e processos ficam no painel Sistema/voz,
  no Digital Twin e na aba COGNIÇÃO.
