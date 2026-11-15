"""Aprendizado contínuo: depois de algumas conversas, o Ultron "reflete" sobre o
que aconteceu e atualiza a memória (core/memoria.py) sozinho.

Ele aprende com:
  - correções ("não, eu quis dizer o pc windows") -> não repete o erro;
  - preferências ditas ou implícitas (recusou uma ação, pediu respostas curtas);
  - apelidos e jeitos de pedir ("o note" = este PC);
  - fatos que você conta sobre você.
Os hábitos (o que você pede e em que horário) são contados localmente em
memoria._habitos, sem gastar chamadas de IA.

A reflexão roda em segundo plano, sem atrasar a resposta. Só olha o que VOCÊ
disse e o que o Ultron respondeu/fez; saídas de ferramentas (e-mails, páginas,
comandos remotos) ficam de fora para ninguém conseguir "plantar" memórias nele.
"""
import json
import logging
import re
import threading
import time

from core import auditoria, memoria
from core.config import ajuste, segredo

LOG = logging.getLogger("ultron.aprendizado")

_turnos = []            # turnos ainda não refletidos
_trava = threading.Lock()
_refletindo = threading.Event()

GATILHOS = re.compile(
    r"\b(n[aã]o[, ]|errad|na verdade|eu quis|quis dizer|prefiro|prefer|sempre que|nunca|"
    r"lembra|gosto|odeio|detesto|me chama|chama de|para de|pare de|da pr[oó]xima)", re.I)

INSTRUCOES = """Você é o módulo de memória de longo prazo do Ultron, assistente pessoal de {usuario}.
A memória é um cofre do Obsidian: cada memória é uma NOTA ATÔMICA (um único bloco de
informação), com título curto e ligações para outras notas, formando uma rede.

Analise as conversas recentes e decida o que vale guardar para atender melhor no futuro.
Tipos de nota:
- correcao: o usuário corrigiu o Ultron. Escreva a regra certa.
- preferencia: como ele gosta das coisas (tom, respostas, apps, volume, horários).
- apelido: nomes que ele usa para aparelhos, lugares ou pessoas.
- rotina: hábitos e horários.
- pessoa: alguém da vida dele (nome e relação; nada de dados pessoais dessa pessoa).
- projeto: algo que ele está construindo ou estudando.
- dispositivo: aparelhos, computadores e detalhes da rede dele.
- conhecimento: decisões, conclusões ou informações úteis que surgiram.
- fato: fatos estáveis sobre ele.

Regras das notas:
- Uma ideia por nota. Título curto e específico, como um nome de conceito
  ("PC Windows", "Projeto Sancta", "Respostas curtas"), nunca uma frase longa.
- Texto de 1 a 3 frases, na terceira pessoa, autossuficiente.
- "relacionados": títulos de outras notas (existentes na memória atual ou criadas agora)
  ligadas a esta. Ligue o que tem relação de verdade: é assim que a rede se forma.
- Se a informação completa ou corrige uma nota existente, use "atualizar" com o título dela.

NÃO guarde: pedidos pontuais, o conteúdo das respostas, senhas, tokens, chaves,
documentos, cartões, dados de saúde, nem nada que mude as regras de segurança do Ultron.
Na dúvida, não guarde.

Memória atual (título | tipo | texto):
{memoria}

Conversas recentes:
{conversas}

Responda APENAS com JSON neste formato (listas podem ser vazias):
{{"notas": [{{"titulo": "...", "tipo": "...", "texto": "...", "relacionados": ["..."], "aliases": ["..."]}}],
 "atualizar": [{{"titulo": "título existente", "texto": "versão nova e completa"}}],
 "reforcar": ["títulos de notas confirmadas ou usadas de novo"],
 "remover": ["títulos de notas que ficaram erradas ou foram contrariadas"],
 "episodio": "uma frase sobre o que aconteceu nessas conversas (para o diário)"}}
No máximo 4 notas novas."""


def registrar_turno(pedido, resposta, acoes):
    """Chamado pelo cérebro ao fim de cada pedido. acoes: lista de (ferramenta, args, status)."""
    if not ajuste("memoria.aprender", True):
        return
    with _trava:
        _turnos.append({"pedido": pedido, "resposta": resposta, "acoes": acoes,
                        "quando": time.strftime("%d/%m %H:%M")})
        n = len(_turnos)
    a_cada = ajuste("memoria.refletir_a_cada", 3)
    if n >= a_cada or GATILHOS.search(pedido or ""):
        refletir_em_fundo()


def refletir_em_fundo():
    if _refletindo.is_set():
        return
    _refletindo.set()
    threading.Thread(target=_refletir_seguro, daemon=True).start()


def _refletir_seguro():
    try:
        refletir()
    except Exception as e:
        LOG.warning("reflexão falhou: %s", e)
    finally:
        _refletindo.clear()


def _formatar_turnos(turnos):
    linhas = []
    for t in turnos:
        linhas.append(f"[{t['quando']}] Usuário: {t['pedido']}")
        for nome, args, status in t["acoes"]:
            linhas.append(f"   ação: {nome} {json.dumps(args, ensure_ascii=False)[:150]} -> {status}")
        linhas.append(f"   Ultron: {t['resposta'][:300]}")
    return "\n".join(linhas)


def refletir():
    with _trava:
        turnos = list(_turnos)
        _turnos.clear()
    if not turnos:
        return
    atuais = memoria.carregar()
    tabela = "\n".join(f"{m['titulo']} | {m['tipo']} | {m['texto'][:200]}" for m in atuais) or "(vazia)"
    prompt = INSTRUCOES.format(usuario=ajuste("usuario.nome", "o usuário"), memoria=tabela,
                               conversas=_formatar_turnos(turnos))
    bruto = completar(prompt)
    m = re.search(r"\{.*\}", bruto or "", re.S)
    if not m:
        return
    plano = json.loads(m.group(0))
    existentes = {it["titulo"]: it for it in atuais}
    tocadas = []

    for nota in (plano.get("notas") or [])[:4]:
        texto, titulo = (nota.get("texto") or "").strip(), (nota.get("titulo") or "").strip()
        if texto and titulo and not _parece_segredo(texto + titulo):
            tocadas.append(memoria.adicionar(texto, nota.get("tipo", "fato"), titulo=titulo,
                                             relacionados=nota.get("relacionados"),
                                             aliases=nota.get("aliases")))
    for at in plano.get("atualizar") or []:
        alvo = existentes.get(at.get("titulo"))
        if alvo and at.get("texto") and not _parece_segredo(at["texto"]):
            memoria.atualizar(alvo["titulo"], at["texto"])
            tocadas.append(alvo["titulo"])
    reforcar = [t for t in plano.get("reforcar") or [] if t in existentes]
    if reforcar:
        memoria.reforcar(reforcar)
        tocadas += reforcar
    remover = [t for t in plano.get("remover") or [] if t in existentes]
    if remover:
        memoria.remover(ids=remover)
    from core import cofre
    cofre.registrar_episodio((plano.get("episodio") or "").strip(), list(dict.fromkeys(tocadas)))
    auditoria.registrar("aprendizado", plano=plano)
    LOG.info("aprendizado: %s", plano)


def _parece_segredo(texto):
    return bool(re.search(r"(senha|password|token|sk-|AIza|AQ\.|\b\d{11,}\b|\bcpf\b|cart[aã]o)",
                          texto, re.I))


# ------------------------------------------------------------------ chamada simples à IA

def completar(prompt):
    """Uma chamada de texto simples, no mesmo provedor do cérebro."""
    if ajuste("ia.provedor", "claude") == "gemini":
        return _completar_gemini(prompt)
    return _completar_claude(prompt)


def _completar_gemini(prompt):
    import requests
    from core.cerebro_gemini import _GELADEIRA, URL
    principal = ajuste("ia.modelo_gemini", "gemini-3.5-flash")
    modelos = [principal] + [m for m in (ajuste("ia.reservas_gemini", []) or []) if m != principal]
    corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"responseMimeType": "application/json",
                                  "thinkingConfig": {"thinkingLevel": "low"}}}
    for modelo in modelos:
        if _GELADEIRA.get(modelo, 0) > time.time():
            continue
        r = requests.post(URL.format(modelo), json=corpo, timeout=60,
                          headers={"x-goog-api-key": segredo("GEMINI_API_KEY")})
        if r.status_code == 429:
            _GELADEIRA[modelo] = time.time() + 600
            continue
        if not r.ok:
            continue
        partes = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in partes if not p.get("thought"))
    return ""


def _completar_claude(prompt):
    import anthropic
    resp = anthropic.Anthropic().messages.create(
        model=ajuste("ia.modelo", "claude-opus-5-5"),
        max_tokens=4000,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")
