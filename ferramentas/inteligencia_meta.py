"""Meta-ferramenta da descoberta progressiva: o modelo pede ferramentas que não estão à vista."""
from core.registro import ferramenta
from inteligencia import ferramentas as ti


@ferramenta(
    "buscar_ferramentas",
    "Procura ferramentas do Ultron que não estão na lista atual. Use quando nenhuma ferramenta visível "
    "serve para o pedido, descrevendo a necessidade com suas palavras (ex.: 'ler o conteúdo de uma página "
    "web', 'testar se um aparelho responde na rede'). As encontradas ficam disponíveis na hora.",
    {"type": "object", "properties": {"necessidade": {"type": "string"}}, "required": ["necessidade"]})
def buscar_ferramentas(necessidade):
    achadas = ti.descobrir(necessidade, 8)
    if not achadas:
        return "Nenhuma ferramenta corresponde. Diga ao Davi que essa capacidade não existe (ela pode virar uma necessidade na Evolution Forge)."
    ti.registrar_descobertas([f.nome for f in achadas])
    return "Agora disponíveis:\n" + "\n".join(f"- {f.nome}: {f.descricao[:160]}" for f in achadas)


@ferramenta("relatorio_reflex",
            "O que o Ultron aprendeu com a própria operação: falhas recorrentes (com hipótese e evidência), "
            "falhas resolvidas, procedimentos que deram certo e a taxa de sucesso desta semana contra a anterior.")
def relatorio_reflex():
    from inteligencia import reflex
    r = reflex.aprender()
    comp = reflex.comparar_periodos(7)
    linhas = [f"Análise: {r['operacoes']} operações, {r['falhas_novas']} falhas novas."]
    a, b = comp["atual"], comp["anterior"]
    linhas.append(f"Sucesso: {a['sucesso']} em {a['operacoes']} operações (semana anterior: {b['sucesso']} em {b['operacoes']}).")
    for f in reflex.falhas()[:8]:
        linhas.append(f"- [{f['estado']}] {f['ferramenta']} {f['contagem']}x ({f['classe']}): {f['hipotese']}"
                      + (f" — resolvida: {f['evidencia_resolucao']}" if f["estado"] == "resolvida" else f" — {f['correcao']}"))
    for p in reflex.procedimentos()[:5]:
        linhas.append(f"- procedimento ({p['intencao']}): {' → '.join(p['sequencia'])} deu certo {p['sucessos']}x")
    return "\n".join(linhas)
