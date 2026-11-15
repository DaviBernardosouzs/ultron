"""Knowledge Ingestion: fontes autorizadas, leitura, divisão em trechos e indexação.

Só entra o que estiver numa fonte cadastrada explicitamente (adicionar_fonte).
A indexação é incremental: arquivos com mesmo mtime/tamanho são pulados, e os
com mesmo conteúdo (hash) só têm o mtime atualizado. Arquivos apagados saem do
índice por inteiro (trechos, FTS, vetores, relações).
"""
import hashlib
import html
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import yaml

from neuralink import banco, embeddings

LOG = logging.getLogger("ultron.neuralink")

TEXTO = {".md": "markdown", ".markdown": "markdown", ".txt": "texto", ".rst": "texto",
         ".pdf": "pdf"}
CODIGO = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".h",
          ".cpp", ".cs", ".sh", ".fish", ".ps1", ".yaml", ".yml", ".toml", ".json", ".sql",
          ".html", ".css", ".vue", ".svelte", ".dart", ".swift", ".rb", ".php", ".lua"}
IGNORAR_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
                ".vite", "target", ".cache", ".obsidian", ".lixeira", ".trash", ".idea",
                ".vscode", "coverage", ".pytest_cache", ".mypy_cache", "vendor"}
# Arquivos que podem conter segredos: nunca entram.
SEGREDOS = re.compile(r"(^\.env|\.pem$|\.key$|\.p12$|\.jks$|^id_(rsa|ed25519|ecdsa)|"
                      r"senha|password|secret|segredo|credenc|credential|token|chave[_-]?privada)", re.I)
REDIGIR = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|"
                     r"xox[baprs]-[A-Za-z0-9-]{10,}|(?i:(?:api[_-]?key|token|senha|password|secret)"
                     r"\s*[:=]\s*)['\"]?[A-Za-z0-9_\-\.]{16,})")
PROIBIDOS = [Path("/"), Path.home(), Path("/etc"), Path("/usr"), Path("/var"), Path("/proc"),
             Path("/sys"), Path("/boot"), Path("/dev"), Path("/root"),
             Path.home() / ".ssh", Path.home() / ".gnupg", Path.home() / ".config",
             Path.home() / ".local"]
MAX_ARQUIVO = 2 * 1024 * 1024
MAX_PDF = 40 * 1024 * 1024
MAX_ARQUIVOS_FONTE = 5000
TAM_TRECHO = 1100
MAX_TRECHOS_DOC = 400


# ------------------------------------------------------------------ fontes

def _validar_caminho(caminho):
    p = Path(os.path.expanduser(str(caminho))).resolve()
    if not p.exists():
        raise ValueError(f"não existe: {p}")
    if p in PROIBIDOS or any(p == x for x in PROIBIDOS):
        raise ValueError(f"{p} é amplo ou sensível demais; escolha uma pasta específica")
    if any(str(p).startswith(str(x) + os.sep) for x in PROIBIDOS[-4:]):
        raise ValueError(f"{p} fica numa pasta sensível (.ssh, .gnupg, .config, .local)")
    return p


def adicionar_fonte(caminho, nome=None, projeto=None, tipo=None):
    """Autoriza uma fonte. Devolve o id. Não indexa (chame sincronizar)."""
    if str(caminho).startswith(("http://", "https://")):
        tipo, chave = "url", str(caminho)
        nome = nome or re.sub(r"^https?://", "", chave)[:60]
    else:
        p = _validar_caminho(caminho)
        if tipo is None:
            tipo = "obsidian" if (p / ".obsidian").is_dir() else ("pasta" if p.is_dir() else "arquivo")
        chave = str(p)
        nome = nome or p.name
    with banco.transacao() as c:
        c.execute("""INSERT INTO fontes(tipo, caminho, nome, projeto, criado) VALUES (?,?,?,?,?)
                     ON CONFLICT(caminho) DO UPDATE SET nome=excluded.nome, projeto=excluded.projeto,
                     ativo=1""", (tipo, chave, nome, projeto, banco.agora()))
        fid = c.execute("SELECT id FROM fontes WHERE caminho=?", (chave,)).fetchone()[0]
        banco.evento(c, "fonte_adicionada", f"Fonte autorizada: {nome}", chave, projeto)
        if projeto:
            banco.entidade(c, "projeto", projeto)
    return fid


def fontes():
    c = banco.conexao()
    return [dict(r) | {"documentos": c.execute("SELECT COUNT(*) FROM documentos WHERE fonte_id=?",
                                                (r["id"],)).fetchone()[0]}
            for r in c.execute("SELECT * FROM fontes ORDER BY id")]


def remover_fonte(fonte_id):
    """Exclusão real de tudo o que veio da fonte. Os arquivos originais não são tocados."""
    with banco.transacao() as c:
        f = c.execute("SELECT * FROM fontes WHERE id=?", (fonte_id,)).fetchone()
        if not f:
            raise ValueError(f"fonte {fonte_id} não existe")
        docs = c.execute("SELECT id FROM documentos WHERE fonte_id=?", (fonte_id,)).fetchall()
        for (d,) in docs:
            banco.apagar_documento(c, d)
        c.execute("DELETE FROM fontes WHERE id=?", (fonte_id,))
        banco.evento(c, "fonte_removida", f"Fonte removida: {f['nome']}",
                     f"{len(docs)} documentos tirados do índice", f["projeto"])
    return len(docs)


def garantir_cofre():
    """O cofre do Ultron (Obsidian) é sempre uma fonte."""
    from core import cofre
    raiz = cofre.raiz()
    raiz.mkdir(parents=True, exist_ok=True)
    c = banco.conexao()
    r = c.execute("SELECT id FROM fontes WHERE caminho=?", (str(raiz.resolve()),)).fetchone()
    return r[0] if r else adicionar_fonte(raiz, "Cofre do Ultron", tipo="obsidian")


# ------------------------------------------------------------------ leitura

def _frontmatter(texto):
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        if fim > 0:
            try:
                meta = yaml.safe_load(texto[3:fim]) or {}
                if isinstance(meta, dict):
                    return meta, texto[fim + 4:].lstrip("\n"), texto[:fim + 4].count("\n") + 1
            except yaml.YAMLError:
                pass
    return {}, texto, 0


def _redigir(t):
    return REDIGIR.sub("[segredo removido]", t)


def _trechos_markdown(texto, linha0=0):
    """Divide por títulos e parágrafos; cada trecho guarda a seção e a linha inicial."""
    pilha, saida, buf, ini = [], [], [], None
    def fechar():
        nonlocal buf, ini
        t = "\n".join(buf).strip()
        if t:
            saida.append((" > ".join(pilha), ini, t))
        buf, ini = [], None
    em_codigo = False
    for i, linha in enumerate(texto.splitlines(), start=linha0 + 1):
        if linha.strip().startswith("```"):
            em_codigo = not em_codigo
        m = None if em_codigo else re.match(r"^(#{1,6})\s+(.*)", linha)
        if m:
            fechar()
            nivel = len(m.group(1))
            pilha = pilha[:nivel - 1] + [m.group(2).strip()]
            continue
        if ini is None and linha.strip():
            ini = i
        buf.append(linha)
        if sum(len(x) + 1 for x in buf) >= TAM_TRECHO and not linha.strip():
            fechar()
    fechar()
    # junta trechos muito curtos da mesma seção
    juntos = []
    for sec, lin, t in saida:
        if juntos and juntos[-1][0] == sec and len(juntos[-1][2]) + len(t) < TAM_TRECHO:
            juntos[-1] = (sec, juntos[-1][1], juntos[-1][2] + "\n\n" + t)
        else:
            juntos.append((sec, lin, t))
    # corta trechos enormes (ex.: tabelas sem linha em branco)
    final = []
    for sec, lin, t in juntos:
        while len(t) > TAM_TRECHO * 1.6:
            corte = t.rfind("\n", 0, TAM_TRECHO) if t.rfind("\n", 0, TAM_TRECHO) > TAM_TRECHO // 2 else TAM_TRECHO
            final.append((sec, lin, t[:corte]))
            lin = (lin or 0) + t[:corte].count("\n")
            t = t[corte:].lstrip()
        final.append((sec, lin, t))
    return final


def _trechos_linhas(texto, rotulo, por=60):
    linhas = texto.splitlines()
    return [(rotulo, i + 1, "\n".join(linhas[i:i + por])) for i in range(0, len(linhas), por)
            if "\n".join(linhas[i:i + por]).strip()]


def _ler_pdf(arq):
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(arq), "-"],
                       capture_output=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace")[:200])
    paginas = r.stdout.decode("utf-8", errors="replace").split("\f")
    trechos = []
    for n, pag in enumerate(paginas, 1):
        for sec, lin, t in _trechos_markdown(pag):
            trechos.append((f"página {n}" + (f" > {sec}" if sec else ""), lin, t))
    return trechos


def _ler_url(url):
    import requests
    r = requests.get(url, timeout=20, headers={"User-Agent": "Ultron-Neuralink/1.0"})
    r.raise_for_status()
    pagina = r.text
    titulo = re.search(r"<title[^>]*>(.*?)</title>", pagina, re.S | re.I)
    pagina = re.sub(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", " ", pagina)
    pagina = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n\n" + "#" * int(m.group(1)) + " ", pagina)
    pagina = re.sub(r"(?i)<(br|p|div|li|tr)[^>]*>", "\n", pagina)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", pagina))
    texto = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", texto)).strip()
    return (html.unescape(titulo.group(1).strip()) if titulo else url), texto


def ler_arquivo(arq):
    """-> (tipo, titulo, propriedades, trechos[(secao, linha, texto)])"""
    ext = arq.suffix.lower()
    if ext == ".pdf":
        return "pdf", arq.stem, {}, _ler_pdf(arq)
    texto = arq.read_text(encoding="utf-8", errors="replace")
    if ext in (".md", ".markdown"):
        meta, corpo, l0 = _frontmatter(texto)
        h1 = re.search(r"^#\s+(.+)$", corpo, re.M)
        return "markdown", (h1.group(1).strip() if h1 else arq.stem), meta, _trechos_markdown(corpo, l0)
    if ext in CODIGO:
        return "codigo", arq.name, {}, _trechos_linhas(texto, arq.name)
    return "texto", arq.stem, {}, _trechos_markdown(texto)


def _arquivos(raiz):
    if raiz.is_file():
        yield raiz
        return
    n = 0
    for pasta, dirs, nomes in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in IGNORAR_DIRS and not d.startswith(".")]
        for nome in sorted(nomes):
            arq = Path(pasta) / nome
            ext = arq.suffix.lower()
            if (ext not in TEXTO and ext not in CODIGO) or SEGREDOS.search(nome) or nome.startswith("."):
                continue
            try:
                tam = arq.stat().st_size
            except OSError:
                continue
            if tam > (MAX_PDF if ext == ".pdf" else MAX_ARQUIVO) or tam == 0:
                continue
            n += 1
            if n > MAX_ARQUIVOS_FONTE:
                LOG.warning("fonte %s passou de %d arquivos; o resto foi ignorado", raiz, MAX_ARQUIVOS_FONTE)
                return
            yield arq


# ------------------------------------------------------------------ indexação

def _categoria_vault(rel, meta):
    if meta.get("tipo"):
        return str(meta["tipo"])
    return rel.parts[0] if len(rel.parts) > 1 else "nota"


def _gravar_documento(c, fonte, caminho, tipo, titulo, meta, trechos, mtime, tamanho, hash_,
                      categoria=None, projeto=None):
    projeto = projeto or fonte["projeto"] or (meta.get("projeto") if isinstance(meta.get("projeto"), str) else None)
    antigo = c.execute("SELECT id FROM documentos WHERE caminho=?", (caminho,)).fetchone()
    if antigo:
        banco.apagar_documento(c, antigo[0])
    cur = c.execute("""INSERT INTO documentos(fonte_id, caminho, titulo, tipo, projeto, categoria,
                       propriedades, mtime, tamanho, hash, indexado, criado)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fonte["id"], caminho, titulo[:300], tipo, projeto, categoria,
                     json.dumps(meta, ensure_ascii=False, default=str), mtime, tamanho, hash_,
                     banco.agora(), banco.agora()))
    doc_id = cur.lastrowid
    for ordem, (secao, linha, texto) in enumerate(trechos[:MAX_TRECHOS_DOC]):
        texto = _redigir(texto)
        tid = c.execute("INSERT INTO trechos(doc_id, ordem, secao, linha, texto) VALUES (?,?,?,?,?)",
                        (doc_id, ordem, secao, linha, texto)).lastrowid
        c.execute("INSERT INTO trechos_fts(rowid, texto, secao, titulo) VALUES (?,?,?,?)",
                  (tid, texto, secao or "", titulo))
    _relacoes_documento(c, fonte, doc_id, tipo, titulo, meta, trechos, projeto, categoria)
    return doc_id, bool(antigo)


def _relacoes_documento(c, fonte, doc_id, tipo, titulo, meta, trechos, projeto, categoria):
    obsidian = fonte["tipo"] == "obsidian"
    tipo_ent = "decisao" if categoria == "decisao" else ("nota" if obsidian else "documento")
    descricao = None
    if trechos:   # sem a sintaxe de callout/citação do Obsidian
        descricao = re.sub(r"(?m)^\s*>\s*(\[![^\]]+\][-+]?\s*)?", "", trechos[0][2])
        descricao = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", descricao).strip()[:240]
    eu = banco.entidade(c, tipo_ent, titulo, descricao, doc_id)
    if projeto:
        banco.relacao(c, banco.entidade(c, "projeto", projeto), "contem", eu, doc_id)
    if categoria == "projeto":    # nota de memória que descreve um projeto
        banco.relacao(c, eu, "descreve", banco.entidade(c, "projeto", titulo.replace("Projeto ", "")), doc_id)
    if tipo == "markdown":
        texto = "\n".join(t for _, _, t in trechos) + "\n" + json.dumps(meta, ensure_ascii=False, default=str)
        for alvo in set(re.findall(r"\[\[([^\]|#]+)", texto)):
            alvo = alvo.strip()
            if alvo and alvo != titulo:
                existente = c.execute("SELECT id FROM entidades WHERE nome=? AND tipo IN ('nota','decisao')",
                                      (alvo,)).fetchone()
                banco.relacao(c, eu, "menciona", existente[0] if existente else banco.entidade(c, "nota", alvo), doc_id)
        tags = meta.get("tags") or []
        tags = [tags] if isinstance(tags, str) else tags
        for tag in set(tags) | set(re.findall(r"(?<![\w/#])#([\wÀ-ú][\w/À-ú-]+)", texto)):
            banco.relacao(c, eu, "marcado", banco.entidade(c, "tag", str(tag)), doc_id)


def _tecnologias(c, fonte):
    """Repositórios: dependências declaradas viram Projeto -> usa -> Tecnologia."""
    raiz = Path(fonte["caminho"])
    if not raiz.is_dir():
        return
    projeto = fonte["projeto"] or raiz.name
    pj = banco.entidade(c, "projeto", projeto)
    deps = set()
    try:
        if (raiz / "package.json").exists():
            d = json.loads((raiz / "package.json").read_text())
            deps |= set(d.get("dependencies", {})) | set(list(d.get("devDependencies", {}))[:15])
            deps.add("Node.js")
        if (raiz / "pyproject.toml").exists():
            import tomllib
            d = tomllib.loads((raiz / "pyproject.toml").read_text())
            deps |= {re.split(r"[<>=\[ ;~!]", x)[0] for x in d.get("project", {}).get("dependencies", [])}
            deps.add("Python")
        if (raiz / "requirements.txt").exists():
            deps |= {re.split(r"[<>=\[ ;~!]", l)[0] for l in (raiz / "requirements.txt").read_text().splitlines()
                     if l.strip() and not l.startswith("#")}
            deps.add("Python")
        if (raiz / "Cargo.toml").exists():
            deps.add("Rust")
        if (raiz / "go.mod").exists():
            deps.add("Go")
    except Exception as e:
        LOG.info("não li as dependências de %s: %s", raiz, e)
    for dep in list(deps)[:60]:
        if dep:
            banco.relacao(c, pj, "usa", banco.entidade(c, "tecnologia", dep))


def sincronizar(fonte_id=None, vetores=True):
    """Indexa as fontes (ou uma). Devolve um resumo por fonte."""
    c = banco.conexao()
    alvo = c.execute("SELECT * FROM fontes WHERE ativo=1" + (" AND id=?" if fonte_id else ""),
                     (fonte_id,) if fonte_id else ()).fetchall()
    resumo = []
    for f in alvo:
        try:
            r = _sincronizar_fonte(f)
            with banco.transacao() as w:
                w.execute("UPDATE fontes SET sincronizado=?, erro=NULL WHERE id=?", (banco.agora(), f["id"]))
            resumo.append(f"{f['nome']}: {r}")
        except Exception as e:
            LOG.warning("sincronização de %s falhou: %s", f["nome"], e, exc_info=True)
            with banco.transacao() as w:
                w.execute("UPDATE fontes SET erro=? WHERE id=?", (str(e)[:300], f["id"]))
                banco.evento(w, "erro_sincronizacao", f"Falha ao sincronizar {f['nome']}", str(e)[:300], f["projeto"])
            resumo.append(f"{f['nome']}: ERRO {e}")
    if vetores:
        n = vetorizar_pendentes()
        if n:
            resumo.append(f"{n} trechos vetorizados na GPU do desktop")
    return resumo


def _sincronizar_fonte(f):
    c = banco.conexao()
    novos = atualizados = removidos = 0
    if f["tipo"] == "url":
        titulo, texto = _ler_url(f["caminho"])
        h = hashlib.sha256(texto.encode()).hexdigest()
        doc = c.execute("SELECT hash FROM documentos WHERE caminho=?", (f["caminho"],)).fetchone()
        if not doc or doc["hash"] != h:
            with banco.transacao() as w:
                _, era = _gravar_documento(w, f, f["caminho"], "web", titulo, {"url": f["caminho"]},
                                           _trechos_markdown(texto), None, len(texto), h, "web")
                banco.evento(w, "documento_atualizado" if era else "documento_adicionado", titulo, f["caminho"], f["projeto"])
            return "página atualizada" if doc else "página indexada"
        return "sem mudanças"
    if f["tipo"] == "conversa":
        return "conversa salva (não muda)"
    raiz = Path(f["caminho"])
    if not raiz.exists():
        raise FileNotFoundError(f"{raiz} não existe mais")
    vistos = set()
    alterados = []
    for arq in _arquivos(raiz):
        caminho = str(arq)
        vistos.add(caminho)
        st = arq.stat()
        doc = c.execute("SELECT id, mtime, tamanho, hash FROM documentos WHERE caminho=?", (caminho,)).fetchone()
        if doc and doc["mtime"] == st.st_mtime and doc["tamanho"] == st.st_size:
            continue
        dados = arq.read_bytes()
        h = hashlib.sha256(dados).hexdigest()
        if doc and doc["hash"] == h:
            with banco.transacao() as w:
                w.execute("UPDATE documentos SET mtime=? WHERE id=?", (st.st_mtime, doc["id"]))
            continue
        try:
            tipo, titulo, meta, trechos = ler_arquivo(arq)
        except Exception as e:
            LOG.info("pulei %s: %s", arq, e)
            continue
        rel = arq.relative_to(raiz) if raiz.is_dir() else Path(arq.name)
        categoria = _categoria_vault(rel, meta) if f["tipo"] == "obsidian" else tipo
        with banco.transacao() as w:
            _, era = _gravar_documento(w, f, caminho, tipo, titulo, meta, trechos, st.st_mtime,
                                       st.st_size, h, categoria)
        if era:
            atualizados += 1
        else:
            novos += 1
        alterados.append(titulo)
    with banco.transacao() as w:
        for d in w.execute("SELECT id, caminho, titulo FROM documentos WHERE fonte_id=?", (f["id"],)).fetchall():
            if d["caminho"] not in vistos:
                banco.apagar_documento(w, d["id"])
                removidos += 1
        if f["tipo"] in ("pasta", "arquivo"):
            _tecnologias(w, f)
        if alterados or removidos:
            if len(alterados) <= 5 and not removidos:
                for t in alterados:
                    banco.evento(w, "documento_adicionado" if novos else "documento_atualizado", t, f["nome"], f["projeto"])
            else:
                banco.evento(w, "indexacao", f"{f['nome']}: {novos} novos, {atualizados} atualizados, "
                             f"{removidos} removidos", ", ".join(alterados[:12]), f["projeto"])
    return f"{novos} novos, {atualizados} atualizados, {removidos} removidos"


def indexar_arquivo(caminho):
    """Reindexa um arquivo de uma fonte já autorizada (usado após editar uma memória)."""
    caminho = str(Path(caminho).resolve())
    c = banco.conexao()
    for f in c.execute("SELECT * FROM fontes WHERE ativo=1 AND tipo IN ('obsidian','pasta','arquivo')"):
        if caminho == f["caminho"] or caminho.startswith(f["caminho"] + os.sep):
            arq = Path(caminho)
            with banco.transacao() as w:
                if not arq.exists():
                    d = w.execute("SELECT id FROM documentos WHERE caminho=?", (caminho,)).fetchone()
                    if d:
                        banco.apagar_documento(w, d[0])
                    return None
                tipo, titulo, meta, trechos = ler_arquivo(arq)
                rel = arq.relative_to(f["caminho"]) if Path(f["caminho"]).is_dir() else Path(arq.name)
                cat = _categoria_vault(rel, meta) if f["tipo"] == "obsidian" else tipo
                st = arq.stat()
                doc_id, _ = _gravar_documento(w, f, caminho, tipo, titulo, meta, trechos, st.st_mtime,
                                              st.st_size, hashlib.sha256(arq.read_bytes()).hexdigest(), cat)
            vetorizar_pendentes(limite=200)
            return doc_id
    raise ValueError(f"{caminho} não pertence a nenhuma fonte autorizada")


def salvar_conversa(titulo, texto, projeto=None):
    """Conversa escolhida pelo Davi vira documento pesquisável."""
    with banco.transacao() as c:
        c.execute("INSERT OR IGNORE INTO fontes(tipo, caminho, nome, criado) VALUES ('conversa','conversas','Conversas salvas',?)",
                  (banco.agora(),))
        f = c.execute("SELECT * FROM fontes WHERE caminho='conversas'").fetchone()
        caminho = f"conversa:{banco.agora()}:{titulo}"
        doc_id, _ = _gravar_documento(c, f, caminho, "conversa", titulo, {}, _trechos_markdown(texto),
                                      None, len(texto), hashlib.sha256(texto.encode()).hexdigest(),
                                      "conversa", projeto)
        banco.evento(c, "conversa_salva", titulo, None, projeto)
    vetorizar_pendentes(limite=100)
    return doc_id


def vetorizar_pendentes(limite=2000):
    """Gera vetores dos trechos que ainda não têm (para o modelo atual)."""
    modelo = embeddings.modelo()
    c = banco.conexao()
    pend = c.execute("""SELECT t.id, t.texto, t.secao, d.titulo FROM trechos t JOIN documentos d ON d.id=t.doc_id
                        WHERE t.id NOT IN (SELECT trecho_id FROM vetores WHERE modelo=?) LIMIT ?""",
                     (modelo, limite)).fetchall()
    if not pend:
        return 0
    feitos = 0
    for i in range(0, len(pend), 64):
        lote = pend[i:i + 64]
        m = embeddings.gerar([f"{r['titulo']} > {r['secao'] or ''}\n{r['texto']}" for r in lote])
        if m is None:
            break
        with banco.transacao() as w:
            for r, v in zip(lote, m):
                # o trecho pode ter sido apagado por uma reindexação enquanto o vetor era gerado
                w.execute("INSERT OR REPLACE INTO vetores(trecho_id, modelo, vetor) "
                          "SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM trechos WHERE id=?)",
                          (r["id"], modelo, v.astype(np.float32).tobytes(), r["id"]))
        feitos += len(lote)
    return feitos


def pendentes_vetor():
    c = banco.conexao()
    return c.execute("SELECT COUNT(*) FROM trechos WHERE id NOT IN (SELECT trecho_id FROM vetores WHERE modelo=?)",
                     (embeddings.modelo(),)).fetchone()[0]
