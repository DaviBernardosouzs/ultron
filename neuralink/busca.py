"""Semantic Search: busca híbrida por palavras (FTS5/BM25) e significado (vetores).

As duas listas são fundidas por Reciprocal Rank Fusion (RRF), que não depende da
escala das notas de cada método. Cada resultado aponta para a origem: documento,
seção e linha. Filtros: projeto, fonte, tipo, categoria e período.

Isolamento por projeto: com isolar=True, só entram documentos globais e os dos
projetos em 'projetos'. Assim o contexto de um projeto não contamina outro.
"""
import re
import threading

import numpy as np

from neuralink import banco, embeddings

RRF_K = 60
_cache = {"chave": None, "ids": None, "matriz": None}
_trava = threading.Lock()


def _termos(consulta):
    return [t for t in re.findall(r"[\wÀ-ú]{2,}", consulta.lower())][:24]


def _filtro_sql(projetos, isolar, fonte, tipo, categoria, desde, ate):
    cond, args = [], []
    if isolar:
        cond.append("(d.projeto IS NULL" + (f" OR d.projeto IN ({','.join('?' * len(projetos))})" if projetos else "") + ")")
        args += list(projetos or [])
    elif projetos:
        cond.append(f"d.projeto IN ({','.join('?' * len(projetos))})")
        args += list(projetos)
    if fonte:
        cond.append("(d.fonte_id = ? OR f.nome = ?)")
        args += [fonte, fonte]
    if tipo:
        cond.append("d.tipo = ?")
        args.append(tipo)
    if categoria:
        cond.append("d.categoria = ?")
        args.append(categoria)
    if desde:
        cond.append("d.indexado >= ?")
        args.append(desde)
    if ate:
        cond.append("d.indexado <= ?")
        args.append(ate)
    return (" AND " + " AND ".join(cond)) if cond else "", args


def _matriz():
    """Vetores do modelo atual em memória; recarrega quando a tabela muda."""
    c = banco.conexao()
    modelo = embeddings.modelo()
    n, maxid = c.execute("SELECT COUNT(*), COALESCE(MAX(trecho_id),0) FROM vetores WHERE modelo=?",
                         (modelo,)).fetchone()
    chave = (str(banco.ARQUIVO), modelo, n, maxid)
    with _trava:
        if _cache["chave"] != chave:
            linhas = c.execute("SELECT trecho_id, vetor FROM vetores WHERE modelo=?", (modelo,)).fetchall()
            if linhas:
                _cache["ids"] = np.array([r[0] for r in linhas])
                _cache["matriz"] = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in linhas])
            else:
                _cache["ids"], _cache["matriz"] = np.array([], dtype=int), None
            _cache["chave"] = chave
        return _cache["ids"], _cache["matriz"]


def buscar(consulta, k=8, projetos=None, isolar=False, fonte=None, tipo=None, categoria=None,
           desde=None, ate=None, por_documento=2, semantica=True):
    c = banco.conexao()
    filtro, args = _filtro_sql(projetos, isolar, fonte, tipo, categoria, desde, ate)
    base = ("SELECT t.id FROM trechos t JOIN documentos d ON d.id=t.doc_id "
            "JOIN fontes f ON f.id=d.fonte_id WHERE f.ativo=1" + filtro)
    rank = {}
    origem = {}
    # 1) palavras
    termos = _termos(consulta)
    if termos:
        q = " OR ".join('"' + t.replace('"', "") + '"' for t in termos)
        try:
            linhas = c.execute(
                f"SELECT rowid FROM trechos_fts WHERE trechos_fts MATCH ? AND rowid IN ({base}) "
                "ORDER BY bm25(trechos_fts, 1.0, 0.6, 1.4) LIMIT 150", [q] + args).fetchall()
        except Exception:
            linhas = []
        for i, (tid,) in enumerate(linhas):
            rank[tid] = rank.get(tid, 0) + 1 / (RRF_K + i)
            origem[tid] = "palavras"
    # 2) significado
    if semantica:
        ids, m = _matriz()
        if m is not None and len(ids):
            qv = embeddings.gerar([consulta], consulta=True)
            if qv is not None and qv.shape[1] == m.shape[1]:
                sims = m @ qv[0]
                permitidos = None
                if filtro:
                    permitidos = {r[0] for r in c.execute(base, args)}
                ordem = np.argsort(-sims)
                i = 0
                for j in ordem[:600]:
                    tid = int(ids[j])
                    if permitidos is not None and tid not in permitidos:
                        continue
                    if sims[j] < 0.30 or i >= 150:
                        break
                    rank[tid] = rank.get(tid, 0) + 1 / (RRF_K + i)
                    origem[tid] = "ambos" if tid in origem else "significado"
                    origem.setdefault(f"sim{tid}", float(sims[j]))
                    i += 1
    if not rank:
        return []
    melhores = sorted(rank, key=rank.get, reverse=True)[:k * 6]
    marcas = ",".join("?" * len(melhores))
    dados = {r["id"]: r for r in c.execute(
        f"""SELECT t.id, t.texto, t.secao, t.linha, d.id AS doc_id, d.titulo, d.caminho, d.tipo,
                   d.projeto, d.categoria, d.indexado, f.nome AS fonte
            FROM trechos t JOIN documentos d ON d.id=t.doc_id JOIN fontes f ON f.id=d.fonte_id
            WHERE t.id IN ({marcas})""", melhores)}
    saida, por_doc = [], {}
    for tid in melhores:
        r = dados.get(tid)
        if not r:
            continue
        if por_doc.get(r["doc_id"], 0) >= por_documento:
            continue
        por_doc[r["doc_id"]] = por_doc.get(r["doc_id"], 0) + 1
        saida.append(dict(r) | {"pontos": round(rank[tid] * 1000, 2), "encontrado_por": origem[tid],
                                "similaridade": origem.get(f"sim{tid}"),
                                "citacao": citacao(r)})
        if len(saida) >= k:
            break
    return saida


def citacao(r):
    lugar = r["caminho"]
    if r["linha"]:
        lugar += f":{r['linha']}"
    return f"{r['titulo']}" + (f" § {r['secao']}" if r["secao"] else "") + f" ({lugar})"
