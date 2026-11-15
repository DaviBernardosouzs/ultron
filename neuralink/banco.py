"""Esquema e conexão do banco do NEURALINK (SQLite + FTS5)."""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from core.config import DADOS

ARQUIVO = Path(os.environ.get("NEURALINK_DB", DADOS / "neuralink.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fontes (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,              -- pasta | obsidian | arquivo | url | conversa | cofre
    caminho TEXT NOT NULL UNIQUE,    -- caminho absoluto, URL ou nome lógico
    nome TEXT NOT NULL,
    projeto TEXT,                    -- isola o conteúdo num projeto (NULL = global)
    ativo INTEGER NOT NULL DEFAULT 1,
    criado TEXT NOT NULL,
    sincronizado TEXT,
    erro TEXT                        -- último erro de sincronização
);
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER NOT NULL REFERENCES fontes(id) ON DELETE CASCADE,
    caminho TEXT NOT NULL UNIQUE,
    titulo TEXT NOT NULL,
    tipo TEXT NOT NULL,              -- markdown | pdf | texto | codigo | web | conversa | memoria
    projeto TEXT,
    categoria TEXT,
    propriedades TEXT,               -- frontmatter em JSON
    mtime REAL, tamanho INTEGER, hash TEXT,
    indexado TEXT NOT NULL,
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trechos (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    secao TEXT,                      -- caminho de títulos (## A > ### B)
    linha INTEGER,                   -- linha inicial no arquivo (rastreabilidade)
    texto TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS trechos_fts USING fts5(
    texto, secao, titulo, content='', contentless_delete=1,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS vetores (
    trecho_id INTEGER PRIMARY KEY REFERENCES trechos(id) ON DELETE CASCADE,
    modelo TEXT NOT NULL,
    vetor BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS entidades (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,              -- projeto documento nota tag tecnologia decisao memoria
                                     -- tarefa skill capacidade ferramenta conversa assunto
    nome TEXT NOT NULL,
    descricao TEXT,
    doc_id INTEGER REFERENCES documentos(id) ON DELETE CASCADE,
    criado TEXT NOT NULL,
    UNIQUE (tipo, nome)
);
CREATE TABLE IF NOT EXISTS relacoes (
    origem INTEGER NOT NULL REFERENCES entidades(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,              -- contem usa menciona decide justifica pertence oferece...
    destino INTEGER NOT NULL REFERENCES entidades(id) ON DELETE CASCADE,
    doc_id INTEGER REFERENCES documentos(id) ON DELETE CASCADE,   -- de onde veio a relação
    PRIMARY KEY (origem, tipo, destino)
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    quando TEXT NOT NULL,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    detalhe TEXT,
    projeto TEXT
);
CREATE TABLE IF NOT EXISTS sugestoes (            -- consolidação: só aplica com revisão
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,              -- duplicada | contradicao | desatualizada | exclusao | correcao
    alvos TEXT NOT NULL,             -- JSON com títulos/ids envolvidos
    motivo TEXT NOT NULL,
    proposta TEXT,                   -- JSON com a mudança proposta
    estado TEXT NOT NULL DEFAULT 'pendente',   -- pendente | aplicada | descartada
    criado TEXT NOT NULL,
    origem TEXT NOT NULL             -- quem sugeriu (ultron, consolidacao, usuario)
);
CREATE INDEX IF NOT EXISTS ix_trechos_doc ON trechos(doc_id);
CREATE INDEX IF NOT EXISTS ix_docs_fonte ON documentos(fonte_id);
CREATE INDEX IF NOT EXISTS ix_docs_proj ON documentos(projeto);
CREATE INDEX IF NOT EXISTS ix_rel_dest ON relacoes(destino);
CREATE INDEX IF NOT EXISTS ix_eventos_quando ON eventos(quando);
"""

_local = threading.local()
_trava_escrita = threading.RLock()


def agora():
    return datetime.now().isoformat(timespec="seconds")


def conexao():
    """Uma conexão por thread (sqlite3 não compartilha conexões entre threads)."""
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "arquivo", None) != ARQUIVO:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(ARQUIVO, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(ESQUEMA)
        _local.c, _local.arquivo = c, ARQUIVO
    return c


class transacao:
    """with transacao() as c: ...  (serializa escritas entre threads)."""

    def __enter__(self):
        _trava_escrita.acquire()
        self.c = conexao()
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, tipo, *_):
        try:
            self.c.execute("ROLLBACK" if tipo else "COMMIT")
        finally:
            _trava_escrita.release()


def evento(c, tipo, titulo, detalhe=None, projeto=None):
    c.execute("INSERT INTO eventos(quando, tipo, titulo, detalhe, projeto) VALUES (?,?,?,?,?)",
              (agora(), tipo, titulo, detalhe, projeto))


def apagar_documento(c, doc_id):
    """Exclusão real: trechos, entradas do FTS, vetores, entidades e relações derivadas."""
    for (tid,) in c.execute("SELECT id FROM trechos WHERE doc_id=?", (doc_id,)).fetchall():
        c.execute("DELETE FROM trechos_fts WHERE rowid=?", (tid,))
    c.execute("DELETE FROM documentos WHERE id=?", (doc_id,))   # cascata: trechos, vetores, relações
    # entidades que ficaram sem nenhuma relação e sem documento
    c.execute("""DELETE FROM entidades WHERE tipo IN ('tag','nota','tecnologia','assunto') AND id NOT IN
                 (SELECT origem FROM relacoes UNION SELECT destino FROM relacoes)""")


def entidade(c, tipo, nome, descricao=None, doc_id=None):
    nome = (nome or "").strip()[:200]
    if not nome:
        return None
    c.execute("""INSERT INTO entidades(tipo, nome, descricao, doc_id, criado) VALUES (?,?,?,?,?)
                 ON CONFLICT(tipo, nome) DO UPDATE SET
                   descricao=COALESCE(excluded.descricao, descricao),
                   doc_id=COALESCE(excluded.doc_id, doc_id)""",
              (tipo, nome, descricao, doc_id, agora()))
    return c.execute("SELECT id FROM entidades WHERE tipo=? AND nome=?", (tipo, nome)).fetchone()[0]


def relacao(c, origem, tipo, destino, doc_id=None):
    if origem and destino and origem != destino:
        c.execute("INSERT OR IGNORE INTO relacoes(origem, tipo, destino, doc_id) VALUES (?,?,?,?)",
                  (origem, tipo, destino, doc_id))


def jsonl(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None
