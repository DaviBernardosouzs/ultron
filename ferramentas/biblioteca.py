"""Consulta à biblioteca do Ultron (saber geral no cofre do Obsidian)."""
from core import biblioteca
from core.registro import ferramenta


@ferramenta(
    "consultar_biblioteca",
    "Busca no seu próprio saber (filosofia, estratégia, ciências, política, literatura, "
    "redes, cibersegurança, programação...) e devolve os trechos mais relevantes. Use para "
    "perguntas de conhecimento antes de pesquisar na web.",
    {"type": "object", "properties": {"pergunta": {"type": "string"},
                                      "quantidade": {"type": "integer", "default": 6}},
     "required": ["pergunta"]})
def consultar_biblioteca(pergunta, quantidade=6):
    achados = biblioteca.buscar(pergunta, k=quantidade, minimo=0.2)
    if not achados:
        return "Nada na biblioteca sobre isso."
    return "\n".join(biblioteca._formatar(t, 1800) for t, _ in achados)


@ferramenta(
    "ler_nota_biblioteca",
    "Lê uma nota inteira da biblioteca pelo título (ex.: 'A Arte da Guerra').",
    {"type": "object", "properties": {"titulo": {"type": "string"}}, "required": ["titulo"]})
def ler_nota_biblioteca(titulo):
    notas, _ = biblioteca.carregar()
    alvo = titulo.strip().lower()
    for nome, n in notas.items():
        if alvo == nome.lower() or alvo in [a.lower() for a in n["aliases"]]:
            return n["arquivo"].read_text(encoding="utf-8")[:8000]
    parecidas = [n for n in notas if alvo in n.lower()]
    return "Não achei. Parecidas: " + (", ".join(parecidas[:10]) or "nenhuma")
