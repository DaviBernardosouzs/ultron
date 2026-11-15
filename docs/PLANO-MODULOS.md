# Plano: 16 módulos + Claude Code Bridge

Este documento é a etapa que os dois prompts pedem antes de implementar: auditoria, mapa de
dependências, componentes compartilhados, contratos, modelo de dados, plano e testes.
Data: 07/11/2026.

## 1. Auditoria: o que já existe

| Módulo pedido | Já existe | Lacuna real |
|---|---|---|
| **Guardian** | `core/registro.py`: níveis N1/N2/N3, `seguranca.sempre`, confirmação por janela/Telegram/PIN; `mcp.permitir_n3`; auditoria em `dados/auditoria.log` | políticas por WorkSpace, permissões de arquivo/rede por ferramenta, revogação com histórico, incidentes; camada independente do orquestrador |
| **Chronos** | `core/agenda.py` (agendador real com trava e Telegram), eventos do NEURALINK, histórico da evolução | uma linha do tempo única, consulta "o que mudou entre X e Y", ligação evento→projeto |
| **Atlas** | busca híbrida do NEURALINK (FTS5 + vetores, filtros, origem) | conversas e ferramentas MCP como fontes; uma ferramenta única de busca universal |
| **Archive** | ingestão do NEURALINK (cataloga e indexa) | duplicatas por hash, classificação, sugestões de reorganização (só sugestão) |
| **Scribe** | resumos progressivos (`neuralink/resumos.py`), notas no cofre | changelog, relatório de projeto, ata de reunião, registro de decisão como documento |
| **Cortex** | — | estruturar problema, alternativas × critérios, riscos, evidências com fonte, decisão registrada |
| **Vector** | tarefas no desktop (`ferramentas/computacao.py`) | plano com etapas, dependências, checkpoints, retomar/cancelar, validação |
| **WorkSpaces** | projeto ativo do NEURALINK (`contexto.projeto_ativo`) | ambiente com diretório, ferramentas, skills, MCPs e políticas próprias |
| **Sentinel** | — | app ativo (KDE via `qdbus6`), print sob pedido (`spectacle`), eventos do sistema; tudo opt-in |
| **Macro Forge** | `modos:` no config (sequências fixas), agendador | workflows com entradas, condições, versões, teste antes de ativar |
| **Self Audit** | `evolucao/autodiagnostico.py` (feito hoje): inicialização, testes, dependências, integrações, latência | relatório com evidências salvo e periódico, consumo anormal de recursos, validade de skills |
| **Synapse** | — | registro de agentes (Ultron, IA local do desktop, Claude Code), delegação com limites |
| **Oracle** | — | cenários com variáveis e premissas, cálculo em sandbox, relatório separando observado/hipótese/simulado |
| **Digital Twin** | `hosts:` no config, `status_computador`, `recursos_maquinas`, Docker local | inventário declarado + estado real; dependências entre serviços; incidentes |
| **Helios** | `ferramentas/casa.py` (Home Assistant) | **bloqueado: `casa.url` está vazio, não há Home Assistant configurado** |
| **Prism** | Gemini (multimodal) já é o cérebro principal | ferramenta de análise de imagem/print/PDF com aviso de precisão |
| **Claude Bridge** | Claude Code 2.1.288 instalado, com `--print --output-format stream-json`, `--max-budget-usd`, `--resume`, `--allowedTools`, `--permission-prompt-tool` | o módulo inteiro |

Achados da auditoria que importam:
- O painel principal é **Qt (PySide6)**, não HTML. "Preservar a interface HTML" vale como
  "preservar a interface atual": as seções novas entram na janela Qt.
- Não há barramento de eventos: cada módulo grava o seu (auditoria, histórico da evolução,
  eventos do NEURALINK). É o primeiro componente compartilhado a criar.
- No notebook rodam 11 containers Docker; `gatlingsend-backend-1` e
  `gatlingsend-homolog-backend-1` estão reiniciando em loop. Isso consome RAM e foi um fator do
  travamento de hoje. O Digital Twin deve mostrar exatamente isso.

## 2. Mapa de dependências

```
                 ┌──────────── Guardian (permissões, aprovações) ◄──── todos que agem
eventos (bus) ◄──┤
  ▲              └──────────── Chronos (linha do tempo, agendamento)
  │
Atlas ──► NEURALINK (índices)        Scribe ──► NEURALINK + cofre
Archive ─► NEURALINK (ingestão)      Cortex ──► Atlas (evidências) ─► registra decisão em NEURALINK
Vector ──► Guardian, Chronos, Synapse, ferramentas
Synapse ─► executores: modelo principal, IA local (desktop), Claude Bridge
Claude Bridge ─► Guardian (permission-prompt-tool), Vector (etapas), NEURALINK (resumo), Forge (candidatos)
WorkSpaces ─► Guardian (políticas), NEURALINK (projeto ativo), Sentinel (associação)
Macro Forge ─► Vector (execução), Guardian, Chronos (agendamento)
Self Audit ─► autodiagnostico + eventos ─► Evolution Forge (propostas)
Digital Twin ─► hosts, Docker, computacao ─► Self Audit (incidentes)
Helios ─► Home Assistant (casa.py)      Prism ─► modelo multimodal
```

## 3. Componentes compartilhados

1. **Barramento de eventos** (`core/eventos.py`): grava em SQLite e publica para a janela.
2. **Guardian** como única porta para ações: `registro.executar` passa por ele.
3. **Executores** (`core/executores.py`): interface comum para modelo principal, IA local e
   Claude Code, usada por Synapse, Vector e Cortex.
4. **NEURALINK**: memória, índice e grafo de todos.
5. **Sandbox** (`evolucao/sandbox.py`): Oracle e Macro Forge testam ali.

## 4. Contratos

### Evento (todos os módulos)

```json
{"id": "ev_01J…", "tipo": "task.started", "quando": "2026-11-07T23:10:02",
 "origem": "vector", "correlacao": "tk_…", "pai": "ev_…",
 "dados": {"…": "sem segredos; textos longos truncados"}}
```

Tipos: `task.created|started|progress|completed|failed`, `tool.started|completed|failed`,
`approval.requested|granted|denied`, `memory.updated`, `module.status_changed`,
`audit.completed`. Antes de gravar, `dados` passa pelo mesmo filtro de segredos do NEURALINK.

### Decisão do Guardian

`autorizar(acao, alvo, contexto) -> {"decisao": "permitir|perguntar|negar", "motivo", "politica"}`
onde `acao` ∈ ler_arquivo, escrever_arquivo, rede, comando, instalar, mcp, mensagem,
dispositivo, destrutiva; `contexto` traz workspace, executor e tarefa. O modelo nunca chama
nada que altere política: só a janela/CLI.

### Delegação (Synapse, Vector e Claude Bridge)

```json
{"tarefa": "tk_…", "objetivo": "…", "contexto": "só o necessário", "diretorio": "/autorizado",
 "arquivos": ["…"], "restricoes": ["…"], "aceite": ["testes passam"],
 "ferramentas": ["Read", "Grep", "Edit"], "limite_s": 900, "limite_usd": 1.0,
 "aprovacao": "guardian", "profundidade": 1}
```

`profundidade` impede delegação recursiva (máximo 2).

## 5. Modelo de dados

Um banco novo `dados/ultron.db` (SQLite, WAL), separado do NEURALINK:
`eventos`, `politicas` (por workspace), `concessoes` (com revogação), `incidentes`,
`workspaces`, `tarefas` + `etapas` + `checkpoints` (Vector), `macros` + `versoes_macro` +
`execucoes`, `agentes`, `delegacoes`, `sessoes_claude`, `cenarios` (Oracle),
`decisoes` (Cortex), `componentes` + `dependencias` (Digital Twin).
Memória e documentos continuam no NEURALINK; o Atlas não cria outro índice.

## 6. Plano de implementação

| Fase | Entregas | Observação |
|---|---|---|
| 1 | barramento de eventos, Guardian, Chronos | tudo o mais depende disso |
| 2 | Atlas, Archive, Scribe | finos sobre o NEURALINK |
| 3 | Cortex, Vector | Vector usa checkpoints persistidos |
| 4 | **Claude Code Bridge** + Intelligence Router | usa Guardian (fase 1) e Vector (fase 3) |
| 5 | WorkSpaces, Sentinel | Sentinel desligado por padrão |
| 6 | Macro Forge, Self Audit | Self Audit estende o autodiagnóstico |
| 7 | Synapse, Oracle | Synapse orquestra os executores |
| 8 | Digital Twin, Prism, Helios | Helios depende de você instalar o Home Assistant |
| 9 | integração com NEURALINK e Forge, painel de cada módulo | |

### Claude Code Bridge: escolha técnica

**CLI em modo não interativo** (`claude -p --output-format stream-json --verbose`), não o
Agent SDK, porque:
- o CLI já está instalado e autenticado; o SDK Python não está no projeto e usaria o mesmo binário;
- `stream-json` já entrega eventos estruturados (início, ferramenta, resultado, custo, `session_id`);
- `--permission-prompt-tool` permite plugar o Guardian como servidor MCP de aprovação, sem
  `--dangerously-skip-permissions`;
- `--max-budget-usd`, `--max-turns`, `--resume` e `--allowedTools` cobrem os limites pedidos.
Isolamento: cada tarefa que altera código roda num `git worktree` próprio; o resumo das
mudanças (`git diff --stat`) passa por aprovação antes de voltar ao ramo principal. A
documentação oficial será conferida na fase 4, antes de fixar os flags.

Router: `LOCAL_ONLY | AUTOMATIC | CLAUDE_PREFERRED` em `config.yaml`, com orçamento diário e
consentimento por projeto para enviar arquivos. A decisão usa ferramentas necessárias, número de
etapas, arquivos envolvidos e privacidade, não o tamanho da mensagem.

## 7. Estratégia de testes

- Unidade por módulo com banco temporário (como `tests/test_neuralink.py`).
- Guardian: matriz ação × política × workspace, revogação e "o modelo não muda política".
- Eventos: segredos nunca gravados; correlação ponta a ponta numa tarefa.
- Claude Bridge: **executor simulado** (script que emite `stream-json` gravado), cobrindo
  sessão, eventos, cancelamento, timeout, orçamento, falha de autenticação e worktree. Um
  teste real opcional, pulado sem consentimento explícito.
- Vector: retomar após matar o processo no meio (checkpoint).
- Regressão: a suíte inteira roda no Self Audit e na Forge antes de qualquer aprovação.

## Resultado da Fase 1 (07/11/2026)

Feito e testado (`tests/test_fase1.py`, 12 testes; suíte total 30):
- `core/eventos.py`: barramento em `dados/ultron.db`, formato padronizado, correlação por pedido
  (aberta quando o cérebro registra o pedido), filtro de segredos, leitura incremental por `seq`.
- `core/guardian.py`: decisão permitir/perguntar/negar antes de toda ferramenta
  (`registro.executar` e `registro.executar_protegido`, usado pelos dois cérebros e pelo MCP);
  N3 nunca vira execução direta; políticas por workspace com revogação e histórico; diretórios
  autorizados; bloqueios fixos (~/.ssh, .env...); pedidos do Ultron e incidentes.
- `core/chronos.py`: linha do tempo única (eventos, NEURALINK, agenda, evolução, desktop,
  conversas), períodos em português e comparação entre períodos.
- Ferramentas: `linha_do_tempo`, `o_que_mudou`, `consultar_permissoes`, `pedir_permissao`
  (só leitura ou pedido; nenhuma concede).
- Janela `ultron modulos` (botão MÓDULOS no painel Evolução): GUARDIAN, CHRONOS e EVENTOS ao vivo.

Próxima: Fase 2 (Atlas, Archive, Scribe).

## Resultado das Fases 2 e 3 (07/11/2026)

- **Atlas** (`modulos/atlas.py`): busca universal sem índice próprio (NEURALINK, memórias,
  conversas da auditoria, Chronos, catálogo do Archive), fusão por RRF, filtros de projeto e período.
- **Archive** (`modulos/archive.py`): catálogo das pastas autorizadas pelo Guardian, duplicatas
  por SHA-256, sugestões de organização que só você aplica (com desfazer), versões via git
  recuperadas como cópia.
- **Scribe** (`modulos/scribe.py`): notas em `Scribe/` no cofre com histórico de versões; ADR,
  reuniões, changelog incremental por git, relatórios do Chronos e documentação viva de projeto.
- **Cortex** (`modulos/cortex.py`): estrutura, evidências do Atlas com códigos E1.., notas com
  citação validada, pontuação ponderada e teste de robustez em Python; registro só com a escolha do Davi.
- **Vector** (`modulos/vector.py`): planos validados contra o registro real, execução em fundo
  com Guardian e checkpoint por etapa, pausa quando ninguém pode confirmar, retomada após
  travamento (só se o processo dono morreu), cancelamento e validação por critérios.
- IA estruturada (`modulos/ia.py`): IA local do desktop primeiro, nuvem como reserva; o
  resultado sempre diz quem gerou.
- Abas: ATLAS, ARCHIVE, SCRIBE, CORTEX, MISSION CONTROL. Testes: 49 + teste da janela.

## Resultado da Fase 4 (07/11/2026): Claude Code Bridge

- `modulos/claude_bridge.py`: contrato de delegação validado (Guardian, profundidade 1),
  CLI `claude -p --output-format stream-json --verbose` com `--max-turns`, `--max-budget-usd`,
  `--tools`, `--strict-mcp-config` e `--permission-prompt-tool mcp__ultron_guardian__autorizar`;
  eventos estruturados gravados e publicados no barramento; sessão guardada (`--resume`);
  limites de concorrência, tempo, turnos, custo por tarefa e por dia; worktree isolado para
  edições com diff, aplicar (merge) e descartar; resumo (não a transcrição) no Scribe/NEURALINK.
- `modulos/claude_guardian_mcp.py`: o Guardian decide cada ação do Claude Code; "perguntar"
  vira pedido na aba CLAUDE BRIDGE e o servidor espera sua resposta.
- Intelligence Router (`rotear`): LOCAL ONLY / AUTOMÁTICO / CLAUDE PREFERRED, por tipo de tarefa,
  etapas, diretório, contexto, privacidade, orçamento e consentimento.
- Vector: etapa `delegado` vai pela Synapse ao Claude Code.
- Testes com Claude Code simulado (`tests/fake_claude.py`), sem chamadas pagas: 12 testes.
- Não verificado ainda: uma execução real (custa uso da sua conta). Se o CLI recusar algum
  flag, a tarefa falha mostrando o erro do CLI na aba.

## Fases 4–8 concluídas (07–08/11/2026)

Claude Bridge (fase 4), WorkSpaces/Sentinel (5), Macro Forge/Self Audit (6), Oracle/Synapse (7),
Digital Twin/Prism/Helios (8). Helios está pronto e testado contra um Home Assistant simulado, mas
só funciona quando `casa.url` e `HOME_ASSISTANT_TOKEN` forem configurados. Prism usa o Gemini para
imagens (não há modelo de visão local). Suíte: 112 testes. Camada cognitiva: `docs/COGNICAO.md`.
