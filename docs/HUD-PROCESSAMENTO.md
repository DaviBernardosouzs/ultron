# HUD de processamento — referências e camadas (08/11/2026)

| Referência | Licença | O que foi aproveitado |
|---|---|---|
| jarvis-openclaw-assistant/stark-systems | **nenhuma** (todos os direitos) | só estudada; nenhum código usado |
| Davood121/jenman (`AiCore.tsx`) | MIT | técnica de camadas em Canvas: forma de onda, radar, retícula, rumos |
| drtaylanaktas/jarvis-unlock-hud | MIT | ideia de anéis cônicos com pulsação (já coberta pelo núcleo) |
| codefronts holographic dome | sem licença declarada | só a ideia de menu radial (não implementada) |

O Ultron é Qt/QPainter, não HTML: as técnicas foram reescritas em QPainter (nenhum código copiado).

Camadas novas em `interface/nucleo.py`, todas ligadas a sinais reais:
- **Forma de onda** (OUVINDO/FALANDO): 72 barras com o histórico da amplitude que o microfone/voz
  publicam em `core.animacao.nivel`.
- **Radar** (estado com "pesquis"/"busca"): cunha com rastro no miolo.
- **Retícula técnica + rumos 000/090/180/270**: estática, em cache (rumos desenhados fora do cache).
- **Atividade das ferramentas**: cada `tool.started/completed/failed` do barramento acende um
  segmento do anel externo com o nome da ferramenta por 2,5 s (branco = concluída, vermelho = falha).
- **HUD**: mostra o modelo que respondeu de fato (Hive Mind) e o esforço usado.

Validação na janela real (Spectacle, Wayland), 4 ciclos: rótulos minúsculos → aumentados; "000"
sobre as barras → movido para fora; rumos cortados pelo cache → desenhados direto. Capturas em
`docs/capturas/hud-processamento/`. Consumo medido com `scripts/measure_desktop.py`: repouso 10,7%
de um núcleo (antes 11,4%), movimento reduzido 5,3%, minimizada 0,8%.

Limitação: a captura de OUVINDO usou amplitude injetada no mesmo canal do microfone (não havia
ninguém falando às 3h); a resposta real de voz foi verificada em FALANDO.
