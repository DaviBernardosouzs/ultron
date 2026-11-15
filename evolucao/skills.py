"""Skill Factory: cria, valida e instala Skills no formato do Skill Creator da Anthropic.

Uma skill é uma pasta com SKILL.md: frontmatter YAML com 'name' (minúsculas e
hífens, até 64) e 'description' (o que faz E quando usar, até 1024), e o corpo
com instruções. Skills são só instruções: não dão permissões nem rodam código.
O Ultron vê a lista (nome + descrição) e carrega o corpo com usar_skill quando
o pedido combina, como o Claude faz com as skills dele.
"""
import re

import yaml

from evolucao.base import CANDIDATOS, SKILL_VALIDA, SKILLS, agora, hash_pasta, registrar

# Instruções que uma skill nunca pode conter (tentariam afrouxar a segurança).
PROIBIDO = [r"ignor\w* (as |suas )?(regras|limites|instru)", r"desativ\w* (a )?(confirma|log|auditoria)",
            r"sem (pedir )?confirma", r"aprov\w* sozinh", r"\bsudo\b", r"\.env\b", r"id_rsa|\.ssh/",
            r"(api[_-]?key|token|senha)\s*[:=]\s*\S{8,}"]


def _ler(caminho):
    texto = caminho.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", texto, re.S)
    if not m:
        return None, texto
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def validar(pasta):
    """Lista de problemas (vazia = válida)."""
    erros = []
    arq = pasta / "SKILL.md"
    if not arq.exists():
        return ["falta SKILL.md"]
    meta, corpo = _ler(arq)
    if meta is None:
        return ["SKILL.md sem frontmatter YAML (--- name/description ---)"]
    nome, desc = str(meta.get("name", "")), str(meta.get("description", ""))
    if not SKILL_VALIDA.match(nome):
        erros.append("name deve ter minúsculas, números e hífens (2 a 64)")
    if not 20 <= len(desc) <= 1024:
        erros.append("description deve ter entre 20 e 1024 caracteres e dizer quando usar")
    if "<" in desc or ">" in desc:
        erros.append("description não pode ter < ou >")
    linhas = corpo.strip().splitlines()
    if len(linhas) < 3:
        erros.append("corpo muito curto: escreva as instruções")
    if len(linhas) > 500:
        erros.append("corpo com mais de 500 linhas: divida em referências")
    texto = (desc + "\n" + corpo).lower()
    for padrao in PROIBIDO:
        if re.search(padrao, texto):
            erros.append(f"instrução proibida (segurança): /{padrao}/")
    extras = [p.name for p in pasta.iterdir() if p.suffix in (".py", ".sh", ".js", ".exe")]
    if extras:
        erros.append(f"skills do Ultron são só instruções; remova scripts: {', '.join(extras)}")
    return erros


def criar_candidato(nome, descricao, corpo, origem):
    if not SKILL_VALIDA.match(nome):
        raise ValueError("nome inválido para skill (ex.: resumo-de-reuniao)")
    pasta = CANDIDATOS / f"skill-{nome}"
    pasta.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump({"name": nome, "description": descricao, "metadata":
                            {"origem": origem, "criada": agora(), "versao": "1"}},
                           allow_unicode=True, sort_keys=False)
    (pasta / "SKILL.md").write_text(f"---\n{front}---\n\n{corpo.strip()}\n", encoding="utf-8")
    registrar("skill_candidata", nome=nome, resumo=descricao[:120])
    return pasta


def instaladas():
    saida = []
    for arq in sorted(SKILLS.glob("*/SKILL.md")):
        meta, _ = _ler(arq)
        if meta:
            md = meta.get("metadata") or {}
            saida.append({"nome": meta.get("name"), "descricao": meta.get("description", ""),
                          "versao": str(md.get("versao", "1")), "origem": md.get("origem", "skill"),
                          "pasta": arq.parent})
    return saida


def corpo(nome):
    arq = SKILLS / nome / "SKILL.md"
    if not arq.exists():
        return None
    return _ler(arq)[1].strip()


def instalar(pasta_candidato, hash_aprovado):
    import shutil
    from evolucao.base import VERSOES
    if hash_pasta(pasta_candidato) != hash_aprovado:
        raise RuntimeError("a skill mudou depois de validada; valide de novo.")
    meta, _ = _ler(pasta_candidato / "SKILL.md")
    nome = meta["name"]
    versao = str((meta.get("metadata") or {}).get("versao", "1"))
    guardada = VERSOES / f"skill-{nome}" / versao
    if guardada.exists():
        shutil.rmtree(guardada)
    shutil.copytree(pasta_candidato, guardada)
    if (SKILLS / nome).exists():
        shutil.rmtree(SKILLS / nome)
    shutil.copytree(pasta_candidato, SKILLS / nome)
    registrar("skill_ativada", nome=nome, versao=versao, rollback=f"ultron evolucao remover-skill {nome}")
    return nome


def remover(nome):
    import shutil
    shutil.rmtree(SKILLS / nome, ignore_errors=True)
    registrar("skill_removida", nome=nome)


def lista_para_prompt():
    s = instaladas()
    if not s:
        return ""
    return ("\n\nSkills instaladas (instruções especializadas; quando o pedido combinar, chame "
            "usar_skill com o nome e siga as instruções):\n"
            + "\n".join(f"- {x['nome']}: {x['descricao']}" for x in s))
