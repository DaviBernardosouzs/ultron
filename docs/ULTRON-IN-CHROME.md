# Ultron in Chrome

Extensão para Brave/Chrome (`extensao-navegador/`) que liga o navegador ao Ultron.

```
painel lateral ─┐                         ┌─ Cerebro próprio (chat do painel)
                ├─ WS ─ core/navegador.py ┤
fundo.js ───────┘   127.0.0.1:8766        └─ POST /comando ← ferramentas/navegador.py
(CDP + scripting)                              (janela, Telegram, voz, painel)
```

- **Ponte**: `ultron --navegador` / `ultron-navegador.service`. Só escuta em localhost; a extensão
  entra com o token de `dados/navegador.token` e origem `chrome-extension://` (WebSocket não tem
  CORS, então sem token qualquer site poderia conectar). Token errado → código 4401.
- **Ferramentas** (grupo `navegador` dos WorkSpaces): `navegador_abas`, `_abrir`, `_pesquisar`, `_ler`
  (texto + elementos `[rN]`), `_rolar`, `_focar_aba`, `_captura`, `_console`, `_rede` são N1;
  `_clicar`, `_digitar`, `_tecla`, `_fechar_aba` são N2; `_digitar` com `enviar=true` e
  `_executar_js` são N3. Tudo que vem da página volta marcado como conteúdo não confiável.
- **Ações**: clique, teclas e texto passam pelo protocolo de depuração (eventos confiáveis, funcionam
  em WhatsApp Web/React); por isso o Brave mostra a faixa "sendo depurado" nas abas em que o Ultron agiu.
- **Confirmações** do chat do painel aparecem no próprio painel (com PIN para N3, se `telegram.pin` existir).
  Pedidos vindos do Telegram/janela confirmam lá, como sempre.

## Instalar

1. `cp ultron-navegador.service ~/.config/systemd/user/ && systemctl --user enable --now ultron-navegador`
2. Brave → `brave://extensions` → Modo do desenvolvedor → Carregar sem compactação → `extensao-navegador/`.
3. Nas opções da extensão, cole o conteúdo de `dados/navegador.token`.
4. `Alt+U` ou o ícone abre o painel.

Testes: `tests/test_navegador.py` (extensão falsa via websockets).
