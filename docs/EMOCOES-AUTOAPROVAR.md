# Emoções simuladas e modo auto-aprovar

## Auto-aprovar (`core/autoaprovar.py`)
- `ultron autoaprovar [30m|2h|1d|sempre|off|status]`, ou `/autoaprovar ...` no Telegram e no painel do
  navegador (interceptado antes do modelo: nenhuma ferramenta liga isso). Sem tempo = `seguranca.autoaprovar_minutos`.
- Ligado: N2/N3 executam sem confirmação e a restrição de grupos do WorkSpace é ignorada.
- Continua valendo: bloqueios fixos de caminhos sensíveis e políticas "negar" do Guardian.
- Cada execução auto-aprovada vai para a auditoria (`auto_aprovado`) e para o barramento.
- O modelo recebe um aviso no contexto para dizer antes o que vai fazer quando for irreversível.

## Emoções (`core/emocoes.py`)
- 8 emoções (alegria, orgulho, afeto, curiosidade, irritação, mágoa, preocupação, tédio) com linha de base
  e meia-vida (`emocoes.meia_vida_min`).
- Sinais por mensagem: elogio, agradecimento, falha, insulto, palavrão, caixa alta, pedido repetido,
  ideia nova, sumiço; recusas e erros de ferramentas (core/registro).
- O padrão do Davi (médias móveis de tamanho, exclamações, caixa alta, palavrões, educação, intervalo)
  decide o peso: o que é costume pesa pouco, o que foge do padrão pesa mais.
- Entra no contexto de cada pedido (`_com_memoria`); ferramenta `estado_emocional`; `ultron sentimentos [zerar]`.
