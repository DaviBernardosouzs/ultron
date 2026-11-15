"""Pesquisa na web e leitura de páginas.

Usa a API do Brave Search ou do Tavily se houver chave no .env; sem chave,
lê a página de resultados do Bing, que não precisa de conta.
"""
import base64
import html
import re
from urllib.parse import parse_qs, urlparse

import requests

from core.config import segredo
from core.registro import NAO_CONFIAVEL, ferramenta

NAVEGADOR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/142.0 Safari/537.36",
             "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6"}


def _limpar(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()


def _brave(consulta, n):
    r = requests.get("https://api.search.brave.com/res/v1/web/search", timeout=15,
                     params={"q": consulta, "count": n, "country": "BR", "search_lang": "pt-br"},
                     headers={"X-Subscription-Token": segredo("BRAVE_API_KEY"),
                              "Accept": "application/json"})
    r.raise_for_status()
    return [(x["title"], x["url"], _limpar(x.get("description")))
            for x in r.json().get("web", {}).get("results", [])[:n]]


def _tavily(consulta, n):
    r = requests.post("https://api.tavily.com/search", timeout=20, json={
        "api_key": segredo("TAVILY_API_KEY"), "query": consulta, "max_results": n})
    r.raise_for_status()
    return [(x["title"], x["url"], x.get("content", "")[:300]) for x in r.json().get("results", [])]


def _link_bing(href):
    """Links do Bing passam por bing.com/ck/a?...&u=a1<base64 do destino>."""
    href = html.unescape(href)
    u = parse_qs(urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        try:
            return base64.urlsafe_b64decode(u[2:] + "=" * (-len(u[2:]) % 4)).decode()
        except Exception:
            pass
    return href


def _bing(consulta, n):
    r = requests.get("https://www.bing.com/search", headers=NAVEGADOR, timeout=15,
                     params={"q": consulta, "setlang": "pt-br", "cc": "BR"})
    r.raise_for_status()
    saida = []
    for bloco in re.findall(r'<li class="b_algo".*?</li>', r.text, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', bloco, re.S)
        if not a:
            continue
        p = re.search(r'<p[^>]*>(.*?)</p>', bloco, re.S)
        saida.append((_limpar(a.group(2)), _link_bing(a.group(1)), _limpar(p.group(1) if p else "")))
    return saida[:n]


@ferramenta(
    "pesquisar_web",
    "Pesquisa na internet e devolve os principais resultados (título, link, trecho). "
    "Use para notícias, preços, resultados de jogos, fatos recentes e tudo que você não "
    "sabe com certeza. Se os trechos não bastarem, leia a página com ler_pagina.",
    {"type": "object", "properties": {
        "consulta": {"type": "string"},
        "quantidade": {"type": "integer", "default": 5, "maximum": 10}},
     "required": ["consulta"]})
def pesquisar_web(consulta, quantidade=5):
    motores = []
    if segredo("BRAVE_API_KEY"):
        motores.append(_brave)
    if segredo("TAVILY_API_KEY"):
        motores.append(_tavily)
    motores.append(_bing)
    erro = None
    for motor in motores:
        try:
            res = motor(consulta, quantidade)
            if res:
                return NAO_CONFIAVEL + "\n\n".join(f"{i}. {t}\n{u}\n{d}" for i, (t, u, d) in
                                                   enumerate(res, 1))
        except Exception as e:
            erro = e
    return f"Nenhum resultado para '{consulta}'" + (f" ({erro})" if erro else ".")


@ferramenta(
    "ler_pagina",
    "Baixa uma página da web e devolve o texto principal (até ~6000 caracteres).",
    {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
def ler_pagina(url):
    r = requests.get(url, headers=NAVEGADOR, timeout=20)
    r.raise_for_status()
    t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", r.text)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>", "\n", t)
    t = _limpar(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return NAO_CONFIAVEL + (t[:6000] + ("\n...(cortado)" if len(t) > 6000 else ""))
