"""Senha para abrir o Ultron (modo voz e texto).

A senha nunca fica em texto puro: o .env guarda só ULTRON_SENHA_HASH (PBKDF2).
Antes de comparar, o que foi dito/digitado é normalizado: sem acentos, espaços
e pontuação, e números falados viram dígitos ("Apolo, mil novecentos e sessenta
e nove" == "apolo 1969" == "Apolo1969").

Definir/trocar:  ultron definir-senha
"""
import getpass
import hashlib
import hmac
import os
import re
import unicodedata

from core.config import RAIZ, segredo

ITERACOES = 300_000

UNIDADES = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
            "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9}
ESPECIAIS = {"dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
             "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
             "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
             "setenta": 70, "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100,
             "duzentos": 200, "trezentos": 300, "quatrocentos": 400, "quinhentos": 500,
             "seiscentos": 600, "setecentos": 700, "oitocentos": 800, "novecentos": 900}
# Grafias que o Whisper costuma trocar.
TROCAS = {"apollo": "apolo"}


def _numero(palavras):
    """Palavras de um número -> dígitos. 'um nove seis nove' -> 1969 (dígito a dígito)."""
    nums = [w for w in palavras if w != "e"]
    if all(w in UNIDADES for w in nums):
        return "".join(str(UNIDADES[w]) for w in nums)
    total, atual = 0, 0
    for w in nums:
        if w == "mil":
            total += (atual or 1) * 1000
            atual = 0
        else:
            atual += UNIDADES.get(w, ESPECIAIS.get(w, 0))
    return str(total + atual)


def normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    palavras = re.findall(r"[a-z]+|\d+", t)
    saida, numero = [], []
    numericas = set(UNIDADES) | set(ESPECIAIS) | {"mil"}
    for w in palavras:
        w = TROCAS.get(w, w)
        if w in numericas or (w == "e" and numero):
            numero.append(w)
            continue
        if numero:
            saida.append(_numero(numero))
            numero = []
        saida.append(w)
    if numero:
        saida.append(_numero(numero))
    return "".join(saida)


def _hash(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", normalizar(senha).encode(), sal, ITERACOES).hex()


def configurada():
    return bool(segredo("ULTRON_SENHA_HASH"))


def confere(tentativa):
    guardado = segredo("ULTRON_SENHA_HASH") or ""
    try:
        _, sal, esperado = guardado.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(_hash(tentativa, bytes.fromhex(sal)), esperado)


def definir(senha):
    sal = os.urandom(16)
    valor = f"pbkdf2${sal.hex()}${_hash(senha, sal)}"
    env = RAIZ / ".env"
    linhas = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    linhas = [l for l in linhas if not l.startswith("ULTRON_SENHA_HASH=")]
    linhas.append(f"ULTRON_SENHA_HASH={valor}")
    env.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.chmod(env, 0o600)
    os.environ["ULTRON_SENHA_HASH"] = valor


def definir_interativo():
    s1 = getpass.getpass("Nova senha do Ultron: ")
    if getpass.getpass("Repita: ") != s1 or not normalizar(s1):
        print("As senhas não batem.")
        return 1
    definir(s1)
    print(f"Senha definida. Ao falar, vale como: {normalizar(s1)!r}")
    return 0
