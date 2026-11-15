> Revisão atual: [Redesign desktop — novembro de 2026](REDESIGN-2026-11.md).
> O texto abaixo descreve a versão anterior.

# Direção visual do Ultron Painel

Aplicação desktop **Qt (PySide6 6.12)** no **KDE Plasma / Wayland**, desenhada com QPainter
(sem navegador, sem WebGL). Capturas reais feitas com `spectacle -b -n -a` sobre a janela aberta.
As skills `frontend-design`, `ui-ux-pro-max`, `brainstorming`, `writing-plans` e
`verification-before-completion` **não estão instaladas** neste ambiente; o ciclo de validação
foi feito à mão: alterar → abrir a janela real → capturar → inspecionar → corrigir.

## Identidade

| Papel | Cor |
|---|---|
| Fundo | preto profundo `#030305` → `#16060A` (vinheta) |
| Principal | carmesim `#F5222D` / `#FF2A3A` |
| Secundária | aço grafite `#AEB6C2` (antes: ciano `#1FD5F9`, que brigava com o núcleo) |
| Energia (só o núcleo) | laranja/ouro `#FF5414` → `#FFCD6E` → branco quente |
| Tipografia | FiraCode Nerd Font (rótulos técnicos, números) + Fira Sans (texto corrido) |

## Antes e depois

- Antes: `docs/capturas/antes.png`
- Depois: `depois-espera.png`, `depois-pensando.png`, `depois-erro.png`, `depois-pequena.png`

| Problema encontrado na captura | Correção |
|---|---|
| Ciano em medidores, voz, mídia e microfone dividia a paleta | secundária vira aço grafite; microfone com anel carmesim |
| Rastros grossos e marrons pareciam sujeira; um cortava "ULTRON · EM ESPERA" | rastros finos, menos numerosos, fora da faixa do rótulo e das legendas dos cantos |
| Vão vazio na coluna esquerda | painel ATIVIDADE com os eventos reais do barramento |
| Núcleo sem estado de erro | ERRO: núcleo inteiro vermelho pulsando + rótulo "ERRO NA ÚLTIMA AÇÃO" (acende com `tool.failed`/`task.failed` reais) |
| EXECUTANDO igual a PENSANDO | ferramenta rodando = mais rasgos de luz; pensando = rotação acelerada |
| Painéis mostravam "—" enquanto carregavam | "carregando…" |
| **100% de um núcleo de CPU com a janela parada** | fundo em cache (o redesenho a cada 80 ms repintava a janela inteira), medidores só redesenham em movimento, timer a 40 Hz → **31%**; sem foco cai para ~15 fps e minimizada não desenha |

## Estados do núcleo

| Estado | Comportamento |
|---|---|
| EM ESPERA | giro lento, 24 fps |
| OUVINDO | núcleo pulsa com o volume real do microfone, tom branco quente |
| PENSANDO | anéis aceleram, rasgos de luz |
| EXECUTANDO | (nome da ferramenta no rótulo) mais rasgos de luz |
| FALANDO | pulso com o nível do áudio reproduzido |
| ERRO | vermelho pulsando por 4 s após uma falha real |

`visual.movimento_reduzido: true` no config: 8 fps, sem rastros nem rasgos.

## Limitações conhecidas

- Os painéis de mídia/clima/agenda dependem de uma coleta em segundo plano (rede): nos
  primeiros segundos mostram "carregando…".
- 31% de um núcleo em espera ainda é a animação do núcleo a 24 fps com a janela em foco;
  `movimento_reduzido` reduz bastante.
- As janelas NEURALINK, Forge e Módulos ainda usam timers próprios; o mesmo ajuste de
  consumo será aplicado a elas.
