"""Ferramentas do Chronos (tempo) e do Guardian (permissões) para o orquestrador.

Guardian: o modelo só CONSULTA e PEDE. Conceder, negar e revogar ficam na janela
de módulos (ultron modulos) e nunca viram ferramenta.
"""
from core import chronos, guardian
from core.registro import NAO_CONFIAVEL, ferramenta


@ferramenta(
    "linha_do_tempo",
    "O que aconteceu num período: pedidos, ferramentas usadas, aprovações, documentos e "
    "memórias do NEURALINK, agenda, evolução e tarefas do desktop. periodo: 'hoje', 'ontem', "
    "'semana passada', 'últimos 3 dias', 'este mês', 'AAAA-MM-DD' ou 'AAAA-MM-DD a AAAA-MM-DD'.",
    {"type": "object", "properties": {
        "periodo": {"type": "string", "default": "hoje"}, "projeto": {"type": "string"},
        "texto": {"type": "string", "description": "filtra por palavra"},
        "quantidade": {"type": "integer", "default": 25}}})
def linha_do_tempo(periodo="hoje", projeto=None, texto=None, quantidade=25):
    ini, fim = chronos.periodo(periodo)
    itens = chronos.atividades(ini, fim, projeto=projeto, texto=texto)
    if not itens:
        return f"Nada registrado entre {ini[:16]} e {fim[:16]}."
    r = chronos.resumo(itens)
    linhas = [f"{len(itens)} registros entre {ini[:16].replace('T', ' ')} e {fim[:16].replace('T', ' ')}; "
              f"{r['falhas']} falhas."]
    linhas += [f"- {i['quando'][:16].replace('T', ' ')} [{i['fonte']}/{i['tipo']}] {i['titulo']}"
               + (f" ({i['detalhe']})" if i["detalhe"] else "") for i in itens[:int(quantidade)]]
    return NAO_CONFIAVEL + "\n".join(linhas)


@ferramenta(
    "o_que_mudou",
    "Compara dois períodos (ex.: 'esta semana' e 'semana passada') e diz o que mudou em números "
    "reais: pedidos, ferramentas, falhas, documentos, memórias, decisões.",
    {"type": "object", "properties": {
        "periodo_a": {"type": "string"}, "periodo_b": {"type": "string"}, "projeto": {"type": "string"}},
     "required": ["periodo_a", "periodo_b"]})
def o_que_mudou(periodo_a, periodo_b, projeto=None):
    c = chronos.comparar(periodo_a, periodo_b, projeto)
    a, b = c["a"], c["b"]
    linhas = [f"{periodo_a}: {a['total']} registros, {a['falhas']} falhas. "
              f"{periodo_b}: {b['total']} registros, {b['falhas']} falhas."]
    for tipo, (x, y) in sorted(c["diferenca"].items(), key=lambda kv: -abs(kv[1][0] - kv[1][1]))[:12]:
        linhas.append(f"- {tipo}: {x} vs {y}")
    if a["ferramentas"]:
        linhas.append(f"Ferramentas mais usadas em {periodo_a}: " +
                      ", ".join(f"{k} ({v})" for k, v in list(a["ferramentas"].items())[:6]))
    return "\n".join(linhas)


@ferramenta(
    "consultar_permissoes",
    "Mostra as permissões do Guardian: políticas ativas, autorizações 'sempre', diretórios "
    "liberados, pedidos pendentes e incidentes recentes. Só leitura.")
def consultar_permissoes():
    pols = guardian.politicas()
    linhas = ["Políticas: " + ("; ".join(f"#{p['id']} {p['acao']}:{p['alvo']} = {p['decisao']} "
                                         f"(workspace {p['workspace']})" for p in pols[:15]) or "nenhuma")]
    linhas.append("Autorizações 'sempre': " + (", ".join(guardian.concessoes_sempre()) or "nenhuma"))
    linhas.append("Diretórios liberados: " + ", ".join(guardian.diretorios_permitidos()))
    pend = guardian.pedidos()
    linhas.append(f"Pedidos pendentes: {len(pend)}")
    inc = guardian.incidentes(5)
    if inc:
        linhas.append("Incidentes recentes: " + "; ".join(f"{i['quando'][:16]} {i['tipo']}: {i['descricao'][:80]}"
                                                         for i in inc))
    return "\n".join(linhas)


@ferramenta(
    "pedir_permissao",
    "Abre um pedido de permissão no Guardian quando uma ação foi bloqueada ou precisa de acesso "
    "novo (ex.: um diretório). NÃO concede nada: o Davi decide no painel de módulos.",
    {"type": "object", "properties": {
        "acao": {"type": "string", "description": "ferramenta | diretorio | rede | mcp | instalar | comando"},
        "alvo": {"type": "string", "description": "nome da ferramenta, caminho ou serviço"},
        "motivo": {"type": "string"}},
     "required": ["acao", "alvo", "motivo"]})
def pedir_permissao(acao, alvo, motivo):
    if acao == "ferramenta":
        from core import registro
        if not registro.obter(alvo):
            return (f"'{alvo}' não é uma ferramenta. Use o nome exato de UMA ferramenta (um pedido por "
                    "ferramenta); aprovar um pedido com outro texto não libera nada.")
    pid = guardian.pedir_permissao(acao, alvo, motivo)
    return f"Pedido {pid} aberto. O Davi decide no painel de módulos (ultron modulos)."
