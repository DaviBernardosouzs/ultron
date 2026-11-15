"""Tool Factory: cria ferramentas candidatas com contrato claro, e integrações MCP.

Fluxo de uma ferramenta Python:
  contrato (entradas/saída/permissões) -> o modelo escreve ferramenta.py + testes.py
  -> checagem estática de segurança -> testes no sandbox -> se falhar, devolve os
  erros ao modelo (até evolucao.max_tentativas) -> candidato pronto para avaliação.

Integrações MCP:
  - servidor existente (npx/url): vira um candidato de plugin com nível N2;
  - servidor próprio em TypeScript: esqueleto com o SDK oficial
    (@modelcontextprotocol/sdk, McpServer + StdioServerTransport + zod),
    compilado e testado no sandbox; em produção roda dentro do bwrap.
"""
import ast
import json
import re
import shutil
import subprocess

import yaml

from evolucao import llm, sandbox
from evolucao.base import (CANDIDATOS, NOME_VALIDO, agora, animar, limite, protegido,
                           registrar, tempo_restante)

BASE_PERMITIDA = {"json", "re", "math", "cmath", "datetime", "time", "statistics", "collections",
                  "itertools", "functools", "decimal", "fractions", "random", "string", "textwrap",
                  "unicodedata", "html", "base64", "hashlib", "hmac", "typing", "dataclasses",
                  "enum", "uuid", "calendar", "zoneinfo", "bisect", "heapq", "operator", "copy",
                  "urllib.parse", "difflib", "ferramenta", "testes"}
POR_PERMISSAO = {"rede": {"requests", "urllib.request", "http.client", "xml.etree.ElementTree"},
                 "arquivos": {"pathlib", "csv", "os.path", "io", "zipfile"}}
NOMES_PROIBIDOS = {"eval", "exec", "compile", "__import__", "globals", "locals", "vars",
                   "breakpoint", "input", "memoryview", "setattr", "delattr"}


def verificar_codigo(texto, permissoes):
    """Checagem estática (defesa extra; a barreira real é o sandbox)."""
    problemas = []
    try:
        arvore = ast.parse(texto)
    except SyntaxError as e:
        return [f"erro de sintaxe: {e}"]
    permitidos = set(BASE_PERMITIDA)
    for chave, mods in POR_PERMISSAO.items():
        if (permissoes or {}).get(chave):
            permitidos |= mods
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            nomes = [a.name for a in no.names] if isinstance(no, ast.Import) else [no.module or ""]
            for n in nomes:
                if n not in permitidos and n.split(".")[0] not in {p for p in permitidos if "." not in p}:
                    problemas.append(f"import não permitido: {n}")
        elif isinstance(no, ast.Name) and no.id in NOMES_PROIBIDOS:
            problemas.append(f"uso proibido: {no.id}")
        elif isinstance(no, ast.Name) and no.id == "open" and not (permissoes or {}).get("arquivos"):
            problemas.append("open() exige a permissão 'arquivos'")
        elif isinstance(no, ast.Attribute) and no.attr.startswith("__") and no.attr != "__name__":
            problemas.append(f"acesso a atributo interno: {no.attr}")
    return sorted(set(problemas))


def validar_manifesto(m):
    erros = []
    if not NOME_VALIDO.match(str(m.get("nome", ""))):
        erros.append("nome: minúsculas, números e _ (3 a 41)")
    if not re.match(r"^\d+\.\d+\.\d+$", str(m.get("versao", ""))):
        erros.append("versao deve ser X.Y.Z")
    if len(str(m.get("descricao", ""))) < 10:
        erros.append("descricao muito curta")
    perms = m.get("permissoes") or {}
    extras = set(perms) - {"rede", "arquivos"}
    if extras:
        erros.append(f"permissões desconhecidas: {extras} (só rede e arquivos)")
    if m.get("dependencias"):
        erros.append("dependências novas exigem instalação manual aprovada; use só a biblioteca padrão "
                     "e requests")
    fs = m.get("ferramentas") or []
    if not fs:
        erros.append("nenhuma ferramenta declarada")
    for f in fs:
        if not NOME_VALIDO.match(str(f.get("nome", ""))):
            erros.append(f"ferramenta com nome inválido: {f.get('nome')}")
        if (f.get("parametros") or {}).get("type", "object") != "object":
            erros.append(f"{f.get('nome')}: parametros deve ser um JSON Schema do tipo object")
    return erros


def montar_candidato(manifesto, codigo, testes):
    nome, versao = manifesto["nome"], manifesto["versao"]
    pasta = CANDIDATOS / f"ext-{nome}-{versao}"
    if protegido(pasta):
        raise PermissionError("caminho protegido")
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    (pasta / "manifest.yaml").write_text(yaml.safe_dump(manifesto, allow_unicode=True, sort_keys=False),
                                        encoding="utf-8")
    (pasta / "ferramenta.py").write_text(codigo, encoding="utf-8")
    (pasta / "testes.py").write_text(testes, encoding="utf-8")
    return pasta


SISTEMA = """Você escreve extensões Python para o assistente Ultron. Regras obrigatórias:
- Responda SÓ com um JSON: {"manifesto": {...}, "ferramenta_py": "...", "testes_py": "..."}.
- manifesto: nome (snake_case), versao "X.Y.Z", descricao, origem, permissoes {rede: bool, arquivos: bool},
  dependencias: [], ferramentas: [{nome, descricao (diga quando usar), parametros (JSON Schema object)}],
  cenarios: [{ferramenta, argumentos, espera_contem}] com 2 a 4 exemplos reais.
- ferramenta.py: uma função por ferramenta, com o mesmo nome, argumentos nomeados iguais ao schema,
  devolvendo str ou dict serializável. Só biblioteca padrão (json, re, math, datetime, decimal...);
  requests apenas se permissoes.rede = true; pathlib/open apenas se permissoes.arquivos = true, e só
  dentro de /dados. Proibido: os, sys, subprocess, socket, eval, exec, importar módulos do Ultron.
- testes.py: from ferramenta import ...; funções teste_* com assert; pelo menos 4 testes, incluindo
  casos de erro. Testes que precisariam de rede devem testar só a lógica local.
- Valide entradas e lance ValueError com mensagem clara em português."""


def gerar_ferramenta(nome, objetivo, entradas, saida, rede=False, versao="1.0.0", origem="Ultron"):
    """Gera, verifica e testa no sandbox, corrigindo até max_tentativas. Devolve (pasta, resultado)."""
    if not NOME_VALIDO.match(nome):
        raise ValueError("nome inválido (snake_case, 3 a 41)")
    pedido = (f"Crie a extensão '{nome}' versão {versao}.\nObjetivo: {objetivo}\n"
              f"Entradas: {entradas}\nSaída esperada: {saida}\n"
              f"Permissão de rede: {'sim' if rede else 'não'}. Origem: {origem}.")
    historico_erros = ""
    for tentativa in range(1, int(limite("max_tentativas", 3)) + 1):
        if tempo_restante() <= 0:
            raise TimeoutError("tempo máximo da tarefa de evolução esgotado")
        animar("desenvolvendo")
        resposta = llm.gerar(pedido + historico_erros, SISTEMA)
        try:
            dados = llm.json_da_resposta(resposta)
            man = dados["manifesto"]
            man.update(nome=nome, versao=versao, origem=origem, dependencias=[])
            man["permissoes"] = {"rede": bool(rede), "arquivos": False}
            codigo, testes = dados["ferramenta_py"], dados["testes_py"]
        except Exception as e:
            historico_erros = f"\n\nA resposta anterior não era um JSON válido ({e}). Responda só o JSON."
            continue
        problemas = validar_manifesto(man) + [f"ferramenta.py: {p}" for p in
                                              verificar_codigo(codigo, man["permissoes"])]
        problemas += [f"testes.py: {p}" for p in verificar_codigo(testes, man["permissoes"])]
        pasta = montar_candidato(man, codigo, testes)
        registrar("ferramenta_gerada", nome=nome, versao=versao, resumo=f"tentativa {tentativa}")
        if problemas:
            historico_erros = "\n\nCorrija estes problemas:\n- " + "\n- ".join(problemas)
            continue
        animar("testando")
        r = sandbox.python(pasta, "testar", {}, rede=False)
        res = (r.get("resultado") or {})
        falhas = [x for x in res.get("resultados", []) if not x["ok"]]
        if res.get("ok") and res.get("resultados") and not falhas:
            return pasta, res
        historico_erros = ("\n\nOs testes falharam no sandbox. Corrija o código (não apague testes "
                           "válidos):\n" + json.dumps(falhas or res or r["erro"][-1500:],
                                                      ensure_ascii=False)[:3000])
    raise RuntimeError(f"não consegui uma versão que passe nos testes em "
                       f"{limite('max_tentativas', 3)} tentativas")


# ------------------------------------------------------------------ MCP

def propor_plugin_mcp(nome, descricao, comando=None, args=None, url=None, requer=None, origem=""):
    """Candidato a plugin MCP existente (npx/uvx/url). Ativado com nível N2 em todas as ferramentas."""
    if not NOME_VALIDO.match(nome.replace("-", "_")):
        raise ValueError("nome inválido")
    if not (comando or url):
        raise ValueError("informe comando (+args) ou url")
    pasta = CANDIDATOS / f"mcp-{nome}"
    pasta.mkdir(parents=True, exist_ok=True)
    cfg = {"descricao": descricao, "nivel": "N2"}
    if url:
        cfg["url"] = url
    else:
        cfg.update(comando=comando, args=list(args or []))
    if requer:
        cfg["requer"] = list(requer)
    (pasta / "plugin.yaml").write_text(yaml.safe_dump({"nome": nome, "origem": origem, "criado": agora(),
                                                      "config": cfg}, allow_unicode=True, sort_keys=False),
                                      encoding="utf-8")
    registrar("mcp_candidato", nome=nome, resumo=descricao[:100])
    return pasta


TESTE_MCP = r'''
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command=sys.argv[1], args=sys.argv[2:])
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            ts = (await s.list_tools()).tools
            print(json.dumps({"ok": True, "ferramentas": [t.name for t in ts]}))
asyncio.run(asyncio.wait_for(main(), 120))
'''


def testar_plugin_mcp(pasta):
    """Sobe o servidor no sandbox (com rede, sem credenciais) e lista as ferramentas."""
    cfg = yaml.safe_load((pasta / "plugin.yaml").read_text())["config"]
    if cfg.get("url"):
        return {"ok": None, "aviso": "servidor remoto: testado na primeira conexão, após aprovação"}
    if cfg.get("requer"):
        return {"ok": None, "aviso": f"precisa de {cfg['requer']}; credenciais não entram no sandbox"}
    (pasta / "_teste_mcp.py").write_text(TESTE_MCP)
    r = sandbox.rodar(pasta, [str(sandbox.VENV / "bin/python"), "-I", "/codigo/_teste_mcp.py",
                              shutil.which(cfg["comando"]) or cfg["comando"], *cfg.get("args", [])],
                      rede=True, tempo=180)
    (pasta / "_teste_mcp.py").unlink()
    try:
        return json.loads(r["saida"].strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "erro": (r["erro"] or r["saida"])[-800:]}


def versao_sdk_mcp_ts():
    r = subprocess.run(["npm", "view", "@modelcontextprotocol/sdk", "version"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() or "1"


def esqueleto_mcp_ts(nome, descricao, ferramentas):
    """Projeto TypeScript com o SDK oficial. ferramentas: [{nome, descricao, parametros: {campo: tipo}}]."""
    pasta = CANDIDATOS / f"mcpts-{nome}"
    if pasta.exists():
        shutil.rmtree(pasta)
    (pasta / "src").mkdir(parents=True)
    sdk = versao_sdk_mcp_ts()
    (pasta / "package.json").write_text(json.dumps({
        "name": f"ultron-mcp-{nome}", "version": "1.0.0", "type": "module", "private": True,
        "bin": {f"ultron-mcp-{nome}": "dist/index.js"},
        "scripts": {"build": "tsc"},
        "dependencies": {"@modelcontextprotocol/sdk": f"^{sdk}", "zod": "^3"},
        "devDependencies": {"typescript": "^5", "@types/node": "^22"}}, indent=2))
    (pasta / "tsconfig.json").write_text(json.dumps({"compilerOptions": {
        "target": "ES2022", "module": "Node16", "moduleResolution": "Node16", "outDir": "dist",
        "rootDir": "src", "strict": True, "esModuleInterop": True, "skipLibCheck": True}}, indent=2))
    zod = {"string": "z.string()", "number": "z.number()", "integer": "z.number().int()",
           "boolean": "z.boolean()"}
    blocos = []
    for f in ferramentas:
        campos = ", ".join(f'{k}: {zod.get(t, "z.string()")}' for k, t in (f.get("parametros") or {}).items())
        blocos.append(f'''server.registerTool(
  {json.dumps(f["nome"])},
  {{ title: {json.dumps(f["nome"])}, description: {json.dumps(f.get("descricao", ""))},
    inputSchema: {{ {campos} }} }},
  async (args) => {{
    // TODO: implementar. Devolva texto para o Ultron.
    return {{ content: [{{ type: "text", text: JSON.stringify(args) }}] }};
  }}
);''')
    (pasta / "src/index.ts").write_text(f'''#!/usr/bin/env node
// Servidor MCP "{nome}" gerado pelo Ultron. {descricao}
import {{ McpServer }} from "@modelcontextprotocol/sdk/server/mcp.js";
import {{ StdioServerTransport }} from "@modelcontextprotocol/sdk/server/stdio.js";
import {{ z }} from "zod";

const server = new McpServer({{ name: {json.dumps(nome)}, version: "1.0.0" }});

{chr(10).join(blocos)}

await server.connect(new StdioServerTransport());
''')
    registrar("mcp_ts_esqueleto", nome=nome, resumo=f"SDK {sdk}")
    return pasta


def compilar_testar_mcp_ts(pasta):
    """npm install + tsc + listar ferramentas, tudo no sandbox (com rede para o npm)."""
    script = ("set -e; cp -r /codigo /tmp/p; cd /tmp/p; npm install --no-audit --no-fund --silent "
              f">/dev/null; npx tsc; {sandbox.VENV}/bin/python -I - node dist/index.js <<'EOF'\n"
              + TESTE_MCP + "\nEOF")
    r = sandbox.rodar(pasta, ["/usr/bin/bash", "-c", script], rede=True, tempo=300)
    try:
        return json.loads(r["saida"].strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "erro": (r["erro"] or r["saida"])[-1500:]}
