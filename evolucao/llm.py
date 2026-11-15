"""Chamada simples (sem ferramentas) ao modelo configurado, para as fábricas."""
import json
import re

import requests

from core.config import ajuste, segredo


def gerar(prompt, sistema="", max_tokens=8000):
    if ajuste("ia.provedor", "claude") == "gemini":
        return _gemini(prompt, sistema)
    return _claude(prompt, sistema, max_tokens)


def _gemini(prompt, sistema):
    chave = segredo("GEMINI_API_KEY")
    modelos = [ajuste("ia.modelo_gemini", "gemini-3.5-flash")] + list(ajuste("ia.reservas_gemini", []) or [])
    erro = None
    for m in modelos:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                          headers={"x-goog-api-key": chave}, timeout=120, json={
                              "systemInstruction": {"parts": [{"text": sistema}]} if sistema else None,
                              "contents": [{"role": "user", "parts": [{"text": prompt}]}]})
        if r.status_code == 200:
            partes = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in partes if not p.get("thought"))
        erro = f"{m}: HTTP {r.status_code} {r.text[:200]}"
    raise RuntimeError(f"modelo indisponível ({erro})")


def _claude(prompt, sistema, max_tokens):
    import anthropic
    c = anthropic.Anthropic(api_key=segredo("ANTHROPIC_API_KEY"))
    r = c.messages.create(model=ajuste("ia.modelo", "claude-opus-5-5"), max_tokens=max_tokens,
                          system=sistema or anthropic.NOT_GIVEN,
                          messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in r.content if b.type == "text")


def json_da_resposta(texto):
    """Extrai o primeiro objeto JSON da resposta (aceita bloco ```json)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto, re.S)
    bruto = m.group(1) if m else texto[texto.find("{"): texto.rfind("}") + 1]
    return json.loads(bruto)
