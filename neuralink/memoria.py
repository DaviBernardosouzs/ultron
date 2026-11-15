"""Memory Engine do NEURALINK.

Memórias são notas do cofre (Obsidian, pasta Memórias/). Este módulo acrescenta os
campos de governança no frontmatter de cada nota e mantém o índice em dia:

  categoria       um dos tipos de core/cofre.TIPOS (preferencia, projeto, decisao,
                  objetivo, atividade, conhecimento, sessao, procedimento...)
  escopo          'global' ou o nome de um projeto (isolamento de contexto)
  confiabilidade  0 a 1 (dito pelo Davi = 1.0; aprendido sozinho = 0.7)
  retencao        'permanente', 'sessao' ou '<N>d' (apagada depois de N dias)
  origem          de onde veio

Excluir é exclusão real: a nota, a cópia na lixeira, os trechos, os vetores, as
entidades e o cache de vetores antigo. A auditoria registra que algo foi apagado,
sem guardar o conteúdo.

Consolidação: o Ultron só SUGERE (tabela sugestoes). Aplicar é decisão do Davi,
pela janela NEURALINK ou pela CLI; nenhuma ferramenta do modelo aplica.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from core import auditoria, cofre
from core.config import DADOS, ajuste, definir
from neuralink import banco, embeddings, ingestao

CATEGORIAS = tuple(cofre.TIPOS)
CONFIANCA_PADRAO = {"usuario": 1.0, "ultron": 0.7}


def _arquivo(titulo):
    return cofre._pasta("Memórias") / cofre._nome_arquivo(titulo)


def _indexar(arq):
    ingestao.garantir_cofre()
    ingestao.indexar_arquivo(arq)


def _meta(arq):
    meta, corpo = cofre._ler(arq)
    return meta, corpo


def listar(categoria=None, escopo=None, texto=None):
    saida = []
    for m in cofre.memorias():
        meta, _ = _meta(m["arquivo"])
        item = {"titulo": m["titulo"], "conteudo": m["texto"], "categoria": m["tipo"],
                "escopo": meta.get("escopo", "global"),
                "confiabilidade": float(meta.get("confiabilidade", 0.7)),
                "retencao": str(meta.get("retencao", "permanente")),
                "origem": meta.get("origem", "aprendido em conversa"),
                "criado": str(meta.get("criado", "")), "atualizado": str(meta.get("atualizado", "")),
                "peso": m["peso"], "usos": m["usos"], "arquivo": str(m["arquivo"])}
        if categoria and item["categoria"] != categoria:
            continue
        if escopo and item["escopo"] != escopo:
            continue
        if texto and cofre._sem_acento(texto) not in cofre._sem_acento(item["titulo"] + " " + item["conteudo"]):
            continue
        saida.append(item)
    return sorted(saida, key=lambda x: x["atualizado"], reverse=True)


def _validar(categoria, escopo, confiabilidade, retencao):
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoria inválida; use: {', '.join(CATEGORIAS)}")
    if not re.fullmatch(r"permanente|sessao|\d{1,4}d", str(retencao)):
        raise ValueError("retenção: 'permanente', 'sessao' ou dias como '90d'")
    if not 0 <= float(confiabilidade) <= 1:
        raise ValueError("confiabilidade vai de 0 a 1")
    if escopo != "global" and not re.fullmatch(r"[\wÀ-ú .\-]{1,60}", escopo):
        raise ValueError("escopo: 'global' ou o nome de um projeto")


def criar(titulo, conteudo, categoria="fato", escopo="global", confiabilidade=None, retencao="permanente",
          origem="usuario", relacionados=None):
    confiabilidade = CONFIANCA_PADRAO.get(origem, 0.8) if confiabilidade is None else confiabilidade
    _validar(categoria, escopo, confiabilidade, retencao)
    titulo = cofre.salvar_memoria(titulo, conteudo, categoria, relacionados=relacionados,
                                  origem="dito pelo Davi" if origem == "usuario" else origem)
    arq = _arquivo(titulo)
    meta, corpo = _meta(arq)
    meta.update({"escopo": escopo, "confiabilidade": float(confiabilidade), "retencao": retencao,
                 "origem": origem})
    if escopo != "global":
        meta["projeto"] = escopo
    cofre._escrever(arq, meta, corpo)
    _indexar(arq)
    with banco.transacao() as c:
        banco.evento(c, "decisao" if categoria == "decisao" else "memoria_criada", titulo,
                     conteudo[:200], None if escopo == "global" else escopo)
    auditoria.registrar("neuralink_memoria_criada", titulo=titulo, categoria=categoria, escopo=escopo)
    return titulo


def corrigir(titulo, conteudo=None, categoria=None, escopo=None, confiabilidade=None, retencao=None):
    arq = _arquivo(titulo)
    if not arq.exists():
        raise ValueError(f"memória '{titulo}' não existe")
    meta, corpo = _meta(arq)
    _validar(categoria or meta.get("tipo", "fato"), escopo or meta.get("escopo", "global"),
             meta.get("confiabilidade", 0.7) if confiabilidade is None else confiabilidade,
             retencao or meta.get("retencao", "permanente"))
    if conteudo is not None:
        antigo = cofre._conteudo_principal(corpo)
        if antigo and antigo in corpo:
            corpo = corpo.replace(antigo, conteudo.strip(), 1)
        else:
            rel = [r.strip("[]\"' ") for r in meta.get("relacionados") or []]
            corpo = cofre._corpo_nota(titulo, meta.get("tipo", "fato"), conteudo.strip(), rel,
                                      "corrigido pelo Davi")
        meta.setdefault("historico", []).append({"quando": banco.agora(), "antes": antigo[:500]})
        meta["historico"] = meta["historico"][-10:]
    if categoria:
        meta["tipo"] = categoria
        meta["categoria"] = f"[[{cofre.TIPOS[categoria][0]}]]"
    for k, v in (("escopo", escopo), ("confiabilidade", confiabilidade), ("retencao", retencao)):
        if v is not None:
            meta[k] = v
    if escopo:
        meta.pop("projeto", None)
        if escopo != "global":
            meta["projeto"] = escopo
    meta["atualizado"] = cofre._agora_iso()
    cofre._escrever(arq, meta, corpo)
    cofre._atualizar_mapas()
    _indexar(arq)
    with banco.transacao() as c:
        banco.evento(c, "memoria_alterada", titulo, "conteúdo corrigido" if conteudo else "metadados",
                     meta.get("projeto"))
    auditoria.registrar("neuralink_memoria_corrigida", titulo=titulo)
    return titulo


def excluir(titulo):
    """Exclusão real da memória e de tudo o que foi derivado dela."""
    arq = _arquivo(titulo)
    lixo = cofre._pasta(".lixeira") / arq.name
    if not arq.exists() and not lixo.exists():
        raise ValueError(f"memória '{titulo}' não existe")
    for f in (arq, lixo):
        if f.exists():
            f.unlink()
    _indexar(arq)                        # arquivo sumiu: tira do índice (trechos, FTS, vetores)
    with banco.transacao() as c:
        c.execute("DELETE FROM entidades WHERE nome=? AND tipo IN ('nota','decisao') AND id NOT IN "
                  "(SELECT origem FROM relacoes UNION SELECT destino FROM relacoes)", (titulo,))
        banco.evento(c, "memoria_excluida", titulo, "excluída de vez (nota e índices)")
    # cache de vetores antigo do cofre (Gemini) também guardava o título
    cache = cofre._vetores()
    for k in [k for k in cache if k.split("|")[0] == titulo]:
        del cache[k]
    cofre._arq_vetores().write_text(json.dumps(cache))
    cofre._atualizar_mapas()
    auditoria.registrar("neuralink_memoria_excluida", titulo=titulo)
    return True


def aplicar_retencao():
    """Apaga as memórias cuja retenção venceu. Devolve os títulos apagados."""
    apagadas = []
    agora = datetime.now()
    for m in listar():
        r = m["retencao"]
        if not r.endswith("d"):
            continue
        try:
            base = datetime.fromisoformat(m["atualizado"] or m["criado"])
        except ValueError:
            continue
        if agora - base > timedelta(days=int(r[:-1])):
            excluir(m["titulo"])
            apagadas.append(m["titulo"])
    return apagadas


def limpar_sessao():
    """Memórias com retenção 'sessao' somem quando a sessão de trabalho acaba."""
    feitas = [m["titulo"] for m in listar() if m["retencao"] == "sessao"]
    for t in feitas:
        excluir(t)
    return feitas


def exportar(destino=None):
    destino = Path(destino or DADOS / f"neuralink-export-{datetime.now():%Y%m%d-%H%M}.json")
    dados = {"exportado": banco.agora(), "memorias": listar(), "fontes": ingestao.fontes(),
             "sugestoes": [dict(r) for r in banco.conexao().execute("SELECT * FROM sugestoes")]}
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    auditoria.registrar("neuralink_exportado", arquivo=str(destino))
    return destino


def gravacao_automatica(ligar=None):
    """Liga/desliga o aprendizado automático das conversas (memoria.aprender)."""
    if ligar is not None:
        definir("memoria.aprender", bool(ligar))
        auditoria.registrar("neuralink_gravacao_automatica", ligado=bool(ligar))
    return bool(ajuste("memoria.aprender", True))


# ------------------------------------------------------------------ sugestões (revisão humana)

def sugerir(tipo, alvos, motivo, proposta=None, origem="ultron"):
    c = banco.conexao()
    ja = c.execute("SELECT id FROM sugestoes WHERE tipo=? AND alvos=? AND estado='pendente'",
                   (tipo, json.dumps(sorted(alvos), ensure_ascii=False))).fetchone()
    if ja:
        return ja[0]
    with banco.transacao() as w:
        sid = w.execute("""INSERT INTO sugestoes(tipo, alvos, motivo, proposta, criado, origem)
                           VALUES (?,?,?,?,?,?)""",
                        (tipo, json.dumps(sorted(alvos), ensure_ascii=False), motivo,
                         banco.jsonl(proposta), banco.agora(), origem)).lastrowid
        banco.evento(w, "sugestao", f"Sugestão de {tipo}: {', '.join(alvos)[:80]}", motivo[:200])
    return sid


def sugestoes(estado="pendente"):
    return [dict(r) | {"alvos": json.loads(r["alvos"]),
                       "proposta": json.loads(r["proposta"]) if r["proposta"] else None}
            for r in banco.conexao().execute("SELECT * FROM sugestoes WHERE estado=? ORDER BY id DESC", (estado,))]


def aplicar_sugestao(sid, por="usuário"):
    """Só a janela/CLI chamam isto (decisão do Davi)."""
    s = next((x for x in sugestoes() if x["id"] == sid), None)
    if not s:
        raise ValueError(f"sugestão {sid} não está pendente")
    p = s["proposta"] or {}
    if s["tipo"] in ("exclusao", "desatualizada"):
        for t in s["alvos"]:
            excluir(t)
    elif s["tipo"] == "correcao":
        corrigir(s["alvos"][0], **{k: v for k, v in p.items() if k in ("conteudo", "categoria", "escopo",
                                                                         "confiabilidade", "retencao")})
    elif s["tipo"] == "duplicada":
        manter, *outras = s["alvos"]
        if p.get("conteudo"):
            corrigir(manter, conteudo=p["conteudo"])
        for t in outras:
            excluir(t)
    elif s["tipo"] == "contradicao":
        if not p.get("manter"):
            raise ValueError("escolha qual memória manter (proposta.manter)")
        for t in s["alvos"]:
            if t != p["manter"]:
                excluir(t)
    _fechar(sid, "aplicada", por)


def descartar_sugestao(sid, por="usuário"):
    _fechar(sid, "descartada", por)


def _fechar(sid, estado, por):
    with banco.transacao() as c:
        c.execute("UPDATE sugestoes SET estado=? WHERE id=?", (estado, sid))
        banco.evento(c, "sugestao_" + estado, f"Sugestão {sid} {estado}", f"por {por}")
    auditoria.registrar("neuralink_sugestao", id=sid, estado=estado, por=por)


def consolidar(usar_ia=True):
    """Procura memórias duplicadas, contraditórias e desatualizadas. Só cria sugestões."""
    itens = listar()
    criadas = []
    # duplicatas exatas (texto normalizado)
    vistos = {}
    for m in itens:
        chave = re.sub(r"\W+", " ", cofre._sem_acento(m["conteudo"])).strip()
        if chave and chave in vistos:
            criadas.append(sugerir("duplicada", [vistos[chave], m["titulo"]], "mesmo conteúdo em duas notas",
                                   origem="consolidacao"))
        vistos.setdefault(chave, m["titulo"])
    # desatualizadas: nunca usadas, peso baixo e paradas há muito tempo
    for m in itens:
        try:
            parado = datetime.now() - datetime.fromisoformat(m["atualizado"] or m["criado"])
        except ValueError:
            continue
        if parado.days > 180 and m["usos"] == 0 and m["peso"] < 1.2 and m["categoria"] != "correcao":
            criadas.append(sugerir("desatualizada", [m["titulo"]],
                                   f"sem uso há {parado.days} dias", origem="consolidacao"))
    # semelhantes: duplicata provável ou contradição (precisa de vetores)
    if len(itens) >= 2:
        mat = embeddings.gerar([f"{m['titulo']}. {m['conteudo']}" for m in itens])
        if mat is not None:
            sims = mat @ mat.T
            for i in range(len(itens)):
                for j in range(i + 1, len(itens)):
                    a, b = itens[i], itens[j]
                    if a["escopo"] != b["escopo"] and "global" not in (a["escopo"], b["escopo"]):
                        continue
                    if sims[i, j] < 0.72:
                        continue
                    # frases opostas ("prefere X" / "prefere Y") ficam quase iguais em vetor:
                    # quem decide entre duplicata e contradição é o juiz; o limiar só vale sem ele
                    veredito = _julgar(a, b) if usar_ia else None
                    if veredito and veredito[0] == "CONTRADICAO":
                        criadas.append(sugerir("contradicao", [a["titulo"], b["titulo"]], veredito[1],
                                               origem="consolidacao"))
                    elif veredito and veredito[0] == "DUPLICADA":
                        criadas.append(sugerir("duplicada", [a["titulo"], b["titulo"]], veredito[1],
                                               origem="consolidacao"))
                    elif veredito is None and sims[i, j] >= 0.95:
                        criadas.append(sugerir("duplicada", [a["titulo"], b["titulo"]],
                                               f"conteúdo quase igual (similaridade {sims[i, j]:.2f}); "
                                               "confira, sem juiz não dá para descartar contradição",
                                               origem="consolidacao"))
    return [s for s in criadas if s]


def _julgar(a, b):
    """IA local do desktop decide se duas memórias se contradizem. None se indisponível."""
    import requests
    try:
        from ferramentas.computacao import _ollama_url
        prompt = ("Compare as duas anotações sobre a mesma pessoa. Responda numa linha só, no formato "
                  "'VEREDITO: motivo curto', onde VEREDITO é CONTRADICAO (afirmam coisas incompatíveis), "
                  "DUPLICADA (dizem a mesma coisa) ou COMPATIVEL.\n"
                  f"A ({a['titulo']}): {a['conteudo'][:600]}\nB ({b['titulo']}): {b['conteudo'][:600]}")
        r = requests.post(_ollama_url() + "/api/generate", timeout=120, json={
            "model": ajuste("neuralink.modelo_juiz", ajuste("computacao.modelo_local", "qwen2.5-coder:7b")),
            "prompt": prompt, "stream": False, "options": {"temperature": 0}})
        linha = r.json().get("response", "").strip().splitlines()[0]
        m = re.match(r"\W*(CONTRADICAO|CONTRADIÇÃO|DUPLICADA|COMPATIVEL|COMPATÍVEL)\W*[:\-]?\s*(.*)", linha, re.I)
        if not m:
            return None
        v = cofre._sem_acento(m.group(1)).upper()
        return v, (m.group(2) or "segundo a IA local")[:300]
    except Exception:
        return None
