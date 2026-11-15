"""Ferramentas do DIGITAL TWIN, PRISM e HELIOS."""
from core.registro import NAO_CONFIAVEL, ferramenta
from modulos import gemeo, helios, prism


# ------------------------------------------------------------------ Digital Twin
@ferramenta(
    "gemeo_estado",
    "Retrato do ambiente digital (máquinas, containers Docker, serviços do Ultron, endpoints cadastrados): "
    "o que está fora do ar, parado ou instável e a causa provável pela cadeia de dependências. Só fontes "
    "configuradas; não varre a rede.",
    {"type": "object", "properties": {"atualizar": {"type": "boolean", "default": True}}})
def gemeo_estado(atualizar=True):
    if atualizar:
        gemeo.atualizar()
    comps = gemeo.componentes()
    ruins = gemeo.diagnostico()
    linhas = [f"{len(comps)} componentes · {sum(c['estado'] == 'ok' for c in comps)} ok · {len(ruins)} com problema."]
    for d in ruins[:12]:
        linhas.append(f"- {d['componente']} [{d['estado']}]: {d['detalhe'][:110]}"
                      + (f" · causa provável: {', '.join(d['causa_provavel'])}" if d["causa_provavel"] else ""))
    return NAO_CONFIAVEL + "\n".join(linhas)


@ferramenta("gemeo_historico", "Histórico de mudanças de estado de um componente (ou de todos) do Digital Twin.",
            {"type": "object", "properties": {"componente": {"type": "string"}}})
def gemeo_historico(componente=None):
    h = gemeo.historico(componente, 30)
    return "\n".join(f"{x['quando'][:16]} {x['componente']}: {x['de'] or '—'} → {x['para']}" for x in h) or "Sem histórico."


# ------------------------------------------------------------------ Prism
@ferramenta(
    "analisar_imagem",
    "Interpreta uma imagem, screenshot, diagrama, gráfico ou PDF (pasta autorizada): descrição, texto extraído, "
    "componentes, dados de gráfico e limitações. PDF com texto é lido localmente; imagens vão ao modelo de "
    "visão (Gemini) se não houver modelo local.",
    {"type": "object", "properties": {"caminho": {"type": "string"}, "pergunta": {"type": "string"}},
     "required": ["caminho"]},
    nivel="N2", resumo=lambda a: f"analisar {a.get('caminho')} (imagens podem ser enviadas ao Gemini)")
def analisar_imagem(caminho, pergunta=""):
    return NAO_CONFIAVEL + prism.formatar(prism.analisar(caminho, pergunta))


@ferramenta(
    "analisar_tela",
    "Tira UMA captura da tela agora (Sentinel precisa estar ligado), interpreta com o Prism e apaga a captura. "
    "Use só quando o Davi pedir para olhar a tela.",
    {"type": "object", "properties": {"pergunta": {"type": "string"}}},
    nivel="N2", resumo=lambda a: "capturar a tela agora e enviá-la ao modelo de visão (a captura é apagada depois)")
def analisar_tela(pergunta=""):
    from modulos import sentinel
    arq = sentinel.capturar_tela()
    try:
        return NAO_CONFIAVEL + prism.formatar(prism.analisar(arq, pergunta, captura_interna=True))
    finally:
        arq.unlink(missing_ok=True)


# ------------------------------------------------------------------ Helios
def _sem_ha():
    return "O Home Assistant não está configurado (casa.url e HOME_ASSISTANT_TOKEN). O Helios precisa dele para agir na casa."


@ferramenta("helios_dispositivos", "Lista os dispositivos autorizados da casa (Home Assistant) com estado e nível de risco.",
            {"type": "object", "properties": {"dominio": {"type": "string"}}})
def helios_dispositivos(dominio=None):
    if not helios.configurado():
        return _sem_ha()
    ds = helios.dispositivos(dominio)
    return "\n".join(f"- {d['nome']} ({d['id']}): {d['estado']}" + (f" [{d['risco']}]" if d["risco"] != "normal" else "")
                     for d in ds) or "Nenhum dispositivo autorizado."


def _nivel_helios(a):
    n = helios.nivel_acao(a.get("entidade", ""))
    return ("N3" if n in ("N3", "bloqueado") else "N1"), f"helios_acionar.{a.get('entidade')}"


@ferramenta(
    "helios_acionar",
    "Liga, desliga ou alterna uma luz/tomada/ventilador da casa (brilho 0-100 para luzes). Fechaduras, alarmes "
    "e portões não podem ser acionados; dispositivos de risco pedem confirmação sempre.",
    {"type": "object", "properties": {"entidade": {"type": "string"}, "acao": {"type": "string", "enum": ["ligar", "desligar", "alternar"]},
                                      "brilho": {"type": "integer"}}, "required": ["entidade", "acao"]},
    nivel_dinamico=_nivel_helios, resumo=lambda a: f"{a.get('acao')} {a.get('entidade')}")
def helios_acionar(entidade, acao, brilho=None):
    if not helios.configurado():
        return _sem_ha()
    return helios.acionar(entidade, acao, brilho)


@ferramenta("helios_energia", "Consumo de energia medido (kWh por dia) e potência agora, com relatório no Scribe.",
            {"type": "object", "properties": {"dias": {"type": "integer", "default": 7}}})
def helios_energia(dias=7):
    if not helios.configurado():
        return _sem_ha()
    texto, total = helios.relatorio_energia(int(dias))
    try:
        from modulos import scribe
        scribe.gravar("Energia", f"Energia {dias} dias", texto, {"tipo": "energia"})
    except Exception:
        pass
    return texto


@ferramenta("helios_cena", "Cria uma cena com o estado atual de dispositivos (acao=criar) ou ativa uma cena (acao=ativar).",
            {"type": "object", "properties": {"acao": {"type": "string", "enum": ["criar", "ativar"]}, "nome": {"type": "string"},
                                              "entidades": {"type": "array", "items": {"type": "string"}}},
             "required": ["acao", "nome"]},
            nivel="N2", resumo=lambda a: f"{a.get('acao')} a cena {a.get('nome')}")
def helios_cena(acao, nome, entidades=None):
    if not helios.configurado():
        return _sem_ha()
    if acao == "criar":
        return f"Cena criada: {helios.criar_cena(nome, entidades or [])}"
    return f"Cena ativada: {helios.ativar_cena(nome)}"
