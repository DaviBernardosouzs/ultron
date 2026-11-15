"""Configuração: config.yaml (ajustes) + .env (segredos)."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
DADOS.mkdir(exist_ok=True)
ARQUIVO = RAIZ / "config.yaml"

load_dotenv(RAIZ / ".env")

_cache = None


def _carregar():
    global _cache
    if _cache is None:
        if ARQUIVO.exists():
            _cache = yaml.safe_load(ARQUIVO.read_text(encoding="utf-8")) or {}
        else:
            _cache = {}
    return _cache


def ajuste(caminho, padrao=None):
    """Lê 'secao.chave' do config.yaml; devolve padrao se não existir."""
    no = _carregar()
    for parte in caminho.split("."):
        if not isinstance(no, dict) or parte not in no:
            return padrao
        no = no[parte]
    return no


def definir(caminho, valor):
    """Grava 'secao.chave' no config.yaml preservando comentários e ordem."""
    global _cache
    from ruamel.yaml import YAML
    ry = YAML()
    ry.preserve_quotes = True
    dados = ry.load(ARQUIVO.read_text(encoding="utf-8")) if ARQUIVO.exists() else {}
    no = dados
    partes = caminho.split(".")
    for parte in partes[:-1]:
        if no.get(parte) is None:
            no[parte] = {}
        no = no[parte]
    no[partes[-1]] = valor
    with ARQUIVO.open("w", encoding="utf-8") as f:
        ry.dump(dados, f)
    _cache = None


def segredo(nome):
    return os.environ.get(nome)
