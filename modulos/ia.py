"""Geração estruturada (JSON) para os módulos (Cortex, Vector, Oracle...).

Ordem: modelo local no desktop (Ollama, format=json, grátis, na GPU) e, se não der,
o modelo da nuvem configurado no Ultron. Devolve (dados, quem_gerou). Quem gerou
sempre vai junto com o resultado, para nada parecer produzido por outro modelo.
Testes trocam GERADOR por uma função determinística.
"""
import json
import re

import requests

from core.config import ajuste

GERADOR = None   # testes: fn(prompt) -> (texto, quem)


def _local(prompt, modelo):
    from ferramentas.computacao import _maquina, _no_ar, _ollama_url
    if not _no_ar(_maquina()[1]):
        return None
    r = requests.post(_ollama_url() + "/api/generate", timeout=420, json={
        "model": modelo, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "30m",
        "options": {"num_ctx": 16384, "temperature": 0.2}})
    if r.ok and r.json().get("response", "").strip():
        return r.json()["response"], f"IA local ({modelo}, desktop)"
    return None


def _extrair(texto):
    texto = re.sub(r"(?s)^.*?```(?:json)?\s*|```.*$", "", texto) if "```" in texto else texto
    ini = min([i for i in (texto.find("{"), texto.find("[")) if i >= 0], default=-1)
    if ini < 0:
        raise ValueError("a IA não devolveu JSON")
    return json.loads(texto[ini:texto.rfind("}" if texto[ini] == "{" else "]") + 1])


def gerar_json(prompt, modelo=None):
    prompt = prompt + "\n\nResponda APENAS com JSON válido, sem texto fora do JSON."
    if GERADOR:
        texto, quem = GERADOR(prompt)
        return _extrair(texto), quem
    modelo = modelo or ajuste("modulos.modelo_local", "qwen2.5-coder:14b")
    erros = []
    try:
        r = _local(prompt, modelo)
        if r:
            return _extrair(r[0]), r[1]
    except Exception as e:
        erros.append(f"local: {e}")
    try:
        from core import aprendizado
        texto = aprendizado.completar(prompt)
        return _extrair(texto), "modelo da nuvem (" + str(ajuste("ia.provedor", "?")) + ")"
    except Exception as e:
        erros.append(f"nuvem: {e}")
    raise RuntimeError("nenhuma IA disponível para gerar a análise: " + "; ".join(erros))
