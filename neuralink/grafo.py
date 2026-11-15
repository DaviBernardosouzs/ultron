"""Knowledge Graph simples e consultável, em duas tabelas do SQLite (entidades, relacoes).

Relações criadas automaticamente:
  Projeto -contem-> Documento/Nota          (fonte com projeto)
  Nota -menciona-> Nota                      ([[links]] do Obsidian = backlinks)
  Nota -marcado-> Tag
  Nota(projeto) -descreve-> Projeto
  Projeto -usa-> Tecnologia                 (package.json, pyproject, requirements...)
  Decisão -decide-> Projeto                 (memória categoria decisao com escopo)
  Capacidade -oferecida_por-> Ferramenta     (inventário do evolucao/)
  Modo -usa-> Capacidade, Plugin -oferece-> Capacidade
  Tarefa -pertence-> Projeto                 (tarefas enviadas ao desktop)
Um banco de grafos dedicado não se justifica: são poucos milhares de arestas e as
consultas são de 1 ou 2 saltos.
"""
import json

from core.config import DADOS
from neuralink import banco

NOMES_CAPACIDADE = {
    "agenda": "Agenda e lembretes", "android": "Android", "biblioteca": "Biblioteca",
    "casa": "Casa inteligente", "comunicacao": "Comunicação", "computacao": "Força do desktop",
    "evolucao": "Evolução supervisionada", "midia": "Mídia", "modos": "Modos", "plugins": "Plugins MCP",
    "rede": "Rede", "sistema": "Este PC", "ssh": "Computadores (SSH)", "utilidades": "Utilidades",
    "web": "Web", "neuralink": "NEURALINK",
}


def sincronizar_capacidades():
    """Espelha o Capability Registry (evolucao/capacidades) no grafo."""
    from evolucao import capacidades
    itens = capacidades.inventario(salvar=False)
    with banco.transacao() as c:
        c.execute("DELETE FROM relacoes WHERE tipo IN ('oferecida_por','oferece') OR "
                  "(tipo='usa' AND origem IN (SELECT id FROM entidades WHERE tipo='modo'))")
        for i in itens:
            if i["tipo"] == "ferramenta":
                mod = (i["dependencias"] or ["?"])[0].split(".")[-1]
                cap = banco.entidade(c, "capacidade", NOMES_CAPACIDADE.get(mod, mod.capitalize()))
                fer = banco.entidade(c, "ferramenta", i["nome"], i["descricao"])
                banco.relacao(c, cap, "oferecida_por", fer)
            elif i["tipo"] == "modo":
                m = banco.entidade(c, "modo", i["nome"].split(":", 1)[-1], i["descricao"])
                for acao in i["dependencias"]:
                    if acao:
                        banco.relacao(c, m, "usa", banco.entidade(c, "capacidade", f"ação: {acao}"))
            elif i["tipo"] in ("plugin", "skill", "extensão"):
                tipo = {"plugin": "plugin", "skill": "skill", "extensão": "extensao"}[i["tipo"]]
                e = banco.entidade(c, tipo, i["nome"].split(":", 1)[-1], i["descricao"])
                banco.relacao(c, e, "oferece", banco.entidade(c, "capacidade", i["nome"].split(":", 1)[-1]))
                for f in i.get("ferramentas", []):
                    banco.relacao(c, e, "oferece", banco.entidade(c, "ferramenta", f))
        _tarefas_desktop(c)
        _decisoes(c)
    return len(itens)


def _tarefas_desktop(c):
    try:
        tarefas = json.loads((DADOS / "computacao" / "tarefas.json").read_text())
    except Exception:
        return
    fontes = c.execute("SELECT caminho, projeto FROM fontes WHERE projeto IS NOT NULL AND tipo='pasta'").fetchall()
    for tid, t in tarefas.items():
        e = banco.entidade(c, "tarefa", f"{tid} {t.get('nome', '')}"[:120], t.get("comando"))
        for f in fontes:
            if t.get("pasta") and str(t["pasta"]).rstrip("/").startswith(f["caminho"]):
                banco.relacao(c, e, "pertence", banco.entidade(c, "projeto", f["projeto"]))


def _decisoes(c):
    for d in c.execute("SELECT id, titulo, projeto FROM documentos WHERE categoria='decisao' AND projeto IS NOT NULL"):
        dec = banco.entidade(c, "decisao", d["titulo"], doc_id=d["id"])
        banco.relacao(c, dec, "decide", banco.entidade(c, "projeto", d["projeto"]), d["id"])


# ------------------------------------------------------------------ consultas

def achar(nome, tipo=None):
    c = banco.conexao()
    q = "SELECT * FROM entidades WHERE nome LIKE ?" + (" AND tipo=?" if tipo else "") + \
        " ORDER BY (nome = ?) DESC, length(nome) LIMIT 20"
    args = [f"%{nome}%"] + ([tipo] if tipo else []) + [nome]
    return [dict(r) for r in c.execute(q, args)]


def relacionadas(entidade_id, profundidade=1, limite=80):
    """Vizinhos (entrada e saída) até 'profundidade' saltos, com o documento de origem."""
    c = banco.conexao()
    vistos, fronteira, arestas = {entidade_id}, {entidade_id}, []
    for _ in range(profundidade):
        nova = set()
        for eid in fronteira:
            for r in c.execute("""SELECT r.origem, r.tipo, r.destino, d.titulo AS doc, d.caminho
                                  FROM relacoes r LEFT JOIN documentos d ON d.id=r.doc_id
                                  WHERE r.origem=? OR r.destino=? LIMIT ?""", (eid, eid, limite)):
                arestas.append(dict(r))
                for v in (r["origem"], r["destino"]):
                    if v not in vistos:
                        vistos.add(v)
                        nova.add(v)
        fronteira = nova
    marcas = ",".join("?" * len(vistos))
    nos = {r["id"]: dict(r) for r in c.execute(f"SELECT * FROM entidades WHERE id IN ({marcas})", list(vistos))}
    return nos, arestas


def detalhe(entidade_id):
    c = banco.conexao()
    e = c.execute("SELECT * FROM entidades WHERE id=?", (entidade_id,)).fetchone()
    if not e:
        return None
    nos, arestas = relacionadas(entidade_id)
    docs = []
    if e["doc_id"]:
        d = c.execute("SELECT titulo, caminho, projeto, indexado FROM documentos WHERE id=?", (e["doc_id"],)).fetchone()
        if d:
            docs.append(dict(d))
    docs += [{"titulo": a["doc"], "caminho": a["caminho"]} for a in arestas if a["doc"]]
    projetos = sorted({nos[x]["nome"] for a in arestas for x in (a["origem"], a["destino"])
                       if nos.get(x, {}).get("tipo") == "projeto" and x != entidade_id})
    historico = [dict(r) for r in c.execute(
        "SELECT quando, tipo, detalhe FROM eventos WHERE titulo=? ORDER BY quando DESC LIMIT 15", (e["nome"],))]
    vistos_docs, docs_unicos = set(), []
    for d in docs:
        if d["caminho"] not in vistos_docs:
            vistos_docs.add(d["caminho"])
            docs_unicos.append(d)
    return {"entidade": dict(e), "vizinhos": nos, "arestas": arestas, "documentos": docs_unicos[:20],
            "projetos": projetos, "historico": historico}


def visao(limite_nos=220, tipos=None):
    """Recorte do grafo para desenhar: as entidades mais conectadas e as arestas entre elas."""
    c = banco.conexao()
    filtro = f"WHERE e.tipo IN ({','.join('?' * len(tipos))})" if tipos else ""
    nos = [dict(r) for r in c.execute(f"""
        SELECT e.id, e.tipo, e.nome, (SELECT COUNT(*) FROM relacoes r WHERE r.origem=e.id OR r.destino=e.id) AS grau
        FROM entidades e {filtro} ORDER BY grau DESC LIMIT ?""", list(tipos or []) + [limite_nos])]
    ids = {n["id"] for n in nos}
    marcas = ",".join("?" * len(ids)) or "NULL"
    arestas = [dict(r) for r in c.execute(
        f"SELECT origem, tipo, destino FROM relacoes WHERE origem IN ({marcas}) AND destino IN ({marcas})",
        list(ids) * 2)]
    return nos, arestas
