"""ARCHIVE: organizador de arquivos dos diretórios autorizados pelo Guardian.

- catalogar: nome, pasta, tamanho, data, categoria e hash (só para quem tem tamanho
  repetido) na tabela arquivos de dados/ultron.db. Só lê.
- duplicatas: mesmo tamanho + mesmo SHA-256 (conteúdo idêntico, não nome parecido).
- sugerir_organizacao: monta um PLANO (lista de movimentos) e grava como sugestão.
  Nada é movido, renomeado ou apagado sem o Davi aplicar a sugestão na janela; ao
  aplicar, cada movimento passa pelo Guardian (escrita) e fica em 'alteracoes',
  o que permite desfazer.
- versões: para arquivos dentro de repositórios git, lista o histórico e recupera uma
  versão antiga como CÓPIA ao lado (o arquivo atual não é sobrescrito).
"""
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core import eventos, guardian

CATEGORIAS = {
    "documento": {".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".epub"},
    "planilha": {".xls", ".xlsx", ".ods", ".csv"},
    "apresentacao": {".ppt", ".pptx", ".odp", ".key"},
    "imagem": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".heic", ".avif"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "audio": {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"},
    "codigo": {".py", ".js", ".ts", ".tsx", ".java", ".kt", ".go", ".rs", ".c", ".cpp", ".h", ".sh", ".html",
               ".css", ".json", ".yaml", ".yml", ".toml", ".sql", ".dart"},
    "compactado": {".zip", ".tar", ".gz", ".xz", ".7z", ".rar", ".zst", ".bz2"},
    "instalador": {".deb", ".rpm", ".appimage", ".exe", ".msi", ".apk", ".aab", ".dmg", ".pkg"},
    "fonte_tipografica": {".ttf", ".otf", ".woff", ".woff2"},
}
PULAR = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build", ".next", "target"}
NOME_PASTA = {"documento": "Documentos", "planilha": "Planilhas", "apresentacao": "Apresentações",
              "imagem": "Imagens", "video": "Vídeos", "audio": "Áudios", "codigo": "Código",
              "compactado": "Compactados", "instalador": "Instaladores", "fonte_tipografica": "Fontes"}


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS arquivos (
            caminho TEXT PRIMARY KEY, raiz TEXT, nome TEXT, pasta TEXT, ext TEXT, categoria TEXT,
            tamanho INTEGER, mtime REAL, hash TEXT, catalogado TEXT);
        CREATE INDEX IF NOT EXISTS ix_arq_tam ON arquivos(tamanho);
        CREATE INDEX IF NOT EXISTS ix_arq_raiz ON arquivos(raiz);
        CREATE TABLE IF NOT EXISTS sugestoes_arquivos (
            id INTEGER PRIMARY KEY, criado TEXT, raiz TEXT, motivo TEXT, plano TEXT,
            estado TEXT DEFAULT 'pendente', decidido TEXT);
        CREATE TABLE IF NOT EXISTS alteracoes (
            id INTEGER PRIMARY KEY, quando TEXT, sugestao INTEGER, de TEXT, para TEXT, desfeita TEXT);""")
    return c


def categoria(ext):
    ext = ext.lower()
    return next((c for c, exts in CATEGORIAS.items() if ext in exts), "outro")


def _autorizado(caminho, escrita=False):
    d = guardian.autorizar_caminho(caminho, escrita=escrita)
    if d["decisao"] == "negar":
        raise PermissionError(f"{caminho}: {d['motivo']} (Guardian)")
    return d


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def catalogar(diretorio, limite=50000):
    raiz = Path(os.path.expanduser(str(diretorio))).resolve()
    _autorizado(raiz)
    if not raiz.is_dir():
        raise ValueError(f"não é uma pasta: {raiz}")
    c = _con()
    agora = datetime.now().isoformat(timespec="seconds")
    vistos, n = set(), 0
    for pasta, dirs, nomes in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in PULAR and not d.startswith(".")]
        for nome in nomes:
            if nome.startswith("."):
                continue
            p = Path(pasta) / nome
            try:
                st = p.stat()
            except OSError:
                continue
            vistos.add(str(p))
            c.execute("""INSERT INTO arquivos(caminho, raiz, nome, pasta, ext, categoria, tamanho, mtime, catalogado)
                         VALUES (?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(caminho) DO UPDATE SET tamanho=excluded.tamanho, mtime=excluded.mtime,
                         categoria=excluded.categoria, catalogado=excluded.catalogado,
                         hash=CASE WHEN arquivos.mtime=excluded.mtime THEN arquivos.hash END""",
                      (str(p), str(raiz), nome, str(Path(pasta)), p.suffix.lower(), categoria(p.suffix),
                       st.st_size, st.st_mtime, agora))
            n += 1
            if n >= limite:
                break
    sumidos = [r[0] for r in c.execute("SELECT caminho FROM arquivos WHERE raiz=?", (str(raiz),))
               if r[0] not in vistos]
    c.executemany("DELETE FROM arquivos WHERE caminho=?", [(x,) for x in sumidos])
    # hash só onde há tamanho repetido (candidatos a duplicata)
    for (cam,) in c.execute("""SELECT caminho FROM arquivos WHERE raiz=? AND hash IS NULL AND tamanho > 0 AND tamanho IN
                               (SELECT tamanho FROM arquivos WHERE raiz=? GROUP BY tamanho HAVING COUNT(*) > 1)""",
                            (str(raiz), str(raiz))).fetchall():
        try:
            c.execute("UPDATE arquivos SET hash=? WHERE caminho=?", (_sha(cam), cam))
        except OSError:
            pass
    c.commit()
    eventos.emitir("module.status_changed", "archive", {"modulo": "archive", "mudanca": "catalogado",
                                                        "raiz": str(raiz), "arquivos": n, "removidos": len(sumidos)})
    return {"raiz": str(raiz), "arquivos": n, "removidos": len(sumidos)}


def _linha(r):
    d = dict(r)
    d["mtime_iso"] = datetime.fromtimestamp(d["mtime"]).isoformat(timespec="seconds") if d.get("mtime") else ""
    return d


def resumo(raiz=None):
    c = _con()
    filtro, args = ("WHERE raiz=?", (raiz,)) if raiz else ("", ())
    return [dict(r) for r in c.execute(f"""SELECT categoria, COUNT(*) AS n, SUM(tamanho) AS bytes FROM arquivos
                                           {filtro} GROUP BY categoria ORDER BY bytes DESC""", args)]


def buscar(texto, categoria_=None, raiz=None, limite=50):
    """Por nome: cada termo conta; os que casam mais termos vêm primeiro."""
    import re
    termos = [t for t in re.findall(r"[\wÀ-ú]{2,}", texto.lower())][:8] or [texto.strip().lower()]
    c = _con()
    cond = ["(" + " OR ".join("lower(nome) LIKE ?" for _ in termos) + ")"]
    args = [f"%{t}%" for t in termos]
    if categoria_:
        cond.append("categoria=?")
        args.append(categoria_)
    if raiz:
        cond.append("raiz=?")
        args.append(raiz)
    linhas = [_linha(r) for r in c.execute(f"SELECT * FROM arquivos WHERE {' AND '.join(cond)} "
                                           "ORDER BY mtime DESC LIMIT ?", args + [limite * 4])]
    linhas.sort(key=lambda r: -sum(t in r["nome"].lower() for t in termos))
    return linhas[:limite]


def duplicatas(raiz=None, limite=100):
    c = _con()
    filtro, args = ("AND raiz=?", [raiz]) if raiz else ("", [])
    grupos = []
    for h, n, tam in c.execute(f"""SELECT hash, COUNT(*), MAX(tamanho) FROM arquivos WHERE hash IS NOT NULL {filtro}
                                   GROUP BY hash HAVING COUNT(*) > 1 ORDER BY MAX(tamanho) * (COUNT(*) - 1) DESC
                                   LIMIT ?""", args + [limite]).fetchall():
        caminhos = [r[0] for r in c.execute("SELECT caminho FROM arquivos WHERE hash=? ORDER BY mtime", (h,))]
        grupos.append({"hash": h, "copias": n, "tamanho": tam, "desperdicio": tam * (n - 1), "caminhos": caminhos})
    return grupos


def sugerir_organizacao(raiz):
    """Plano: arquivos soltos na raiz vão para subpastas por categoria. Só sugere."""
    raiz = str(Path(os.path.expanduser(raiz)).resolve())
    _autorizado(raiz)
    c = _con()
    plano = []
    for r in c.execute("SELECT * FROM arquivos WHERE raiz=? AND pasta=? ORDER BY categoria", (raiz, raiz)):
        if r["categoria"] == "outro":
            continue
        destino = Path(raiz) / NOME_PASTA[r["categoria"]] / r["nome"]
        if not destino.exists():
            plano.append({"de": r["caminho"], "para": str(destino), "categoria": r["categoria"]})
    if not plano:
        return None
    motivo = f"{len(plano)} arquivos soltos em {raiz} agrupados por tipo"
    sid = c.execute("INSERT INTO sugestoes_arquivos(criado, raiz, motivo, plano) VALUES (?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), raiz, motivo,
                     json.dumps(plano, ensure_ascii=False))).lastrowid
    c.commit()
    eventos.emitir("approval.requested", "archive", {"sugestao": sid, "motivo": motivo, "movimentos": len(plano)})
    return sid


def sugestoes(estado="pendente"):
    return [dict(r) | {"plano": json.loads(r["plano"])}
            for r in _con().execute("SELECT * FROM sugestoes_arquivos WHERE estado=? ORDER BY id DESC", (estado,))]


def aplicar(sid, por="Davi"):
    """Só a janela chama (decisão do Davi). Move sem sobrescrever e registra para desfazer."""
    c = _con()
    s = c.execute("SELECT * FROM sugestoes_arquivos WHERE id=? AND estado='pendente'", (sid,)).fetchone()
    if not s:
        raise ValueError(f"sugestão {sid} não está pendente")
    feitos = 0
    for m in json.loads(s["plano"]):
        de, para = Path(m["de"]), Path(m["para"])
        _autorizado(de, escrita=True)
        _autorizado(para, escrita=True)
        if not de.exists() or para.exists():
            continue
        para.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(de), str(para))
        c.execute("INSERT INTO alteracoes(quando, sugestao, de, para) VALUES (?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), sid, str(de), str(para)))
        c.execute("UPDATE arquivos SET caminho=?, pasta=? WHERE caminho=?", (str(para), str(para.parent), str(de)))
        feitos += 1
    c.execute("UPDATE sugestoes_arquivos SET estado='aplicada', decidido=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), sid))
    c.commit()
    eventos.emitir("approval.granted", "archive", {"sugestao": sid, "movidos": feitos, "por": por})
    return feitos


def descartar(sid):
    c = _con()
    c.execute("UPDATE sugestoes_arquivos SET estado='descartada', decidido=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), sid))
    c.commit()
    eventos.emitir("approval.denied", "archive", {"sugestao": sid})


def alteracoes(limite=200):
    return [dict(r) for r in _con().execute("SELECT * FROM alteracoes ORDER BY id DESC LIMIT ?", (limite,))]


def desfazer(alteracao_id):
    c = _con()
    a = c.execute("SELECT * FROM alteracoes WHERE id=? AND desfeita IS NULL", (alteracao_id,)).fetchone()
    if not a:
        raise ValueError("alteração não encontrada ou já desfeita")
    de, para = Path(a["para"]), Path(a["de"])
    if not de.exists() or para.exists():
        raise ValueError("o arquivo mudou de lugar depois; desfaça manualmente")
    shutil.move(str(de), str(para))
    c.execute("UPDATE alteracoes SET desfeita=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), alteracao_id))
    c.execute("UPDATE arquivos SET caminho=?, pasta=? WHERE caminho=?", (str(para), str(para.parent), str(de)))
    c.commit()
    return True


# ------------------------------------------------------------------ versões (git)

def _repo(caminho):
    p = Path(caminho).resolve()
    r = subprocess.run(["git", "-C", str(p.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def versoes(caminho, limite=20):
    _autorizado(caminho)
    repo = _repo(caminho)
    if not repo:
        return []
    rel = str(Path(caminho).resolve().relative_to(repo))
    r = subprocess.run(["git", "-C", str(repo), "log", f"-{limite}", "--format=%h|%ad|%an|%s", "--date=short",
                        "--follow", "--", rel], capture_output=True, text=True)
    return [dict(zip(("commit", "data", "autor", "mensagem"), l.split("|", 3))) for l in r.stdout.splitlines() if l]


def recuperar_versao(caminho, commit):
    """Grava a versão antiga como cópia ao lado: <nome>.versao-<commit><ext>."""
    if not commit.isalnum():
        raise ValueError("commit inválido")
    p = Path(caminho).resolve()
    destino = p.with_name(f"{p.stem}.versao-{commit}{p.suffix}")
    _autorizado(destino, escrita=True)
    repo = _repo(p)
    if not repo:
        raise ValueError("o arquivo não está num repositório git")
    r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{p.relative_to(repo)}"], capture_output=True)
    if r.returncode:
        raise ValueError(r.stderr.decode(errors="replace")[:200])
    destino.write_bytes(r.stdout)
    return str(destino)
