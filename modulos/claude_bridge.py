"""ClaudeCodeBridge: o Ultron delega tarefas complexas ao Claude Code e acompanha tudo.

Escolha técnica: CLI em modo não interativo (claude -p --output-format stream-json
--verbose). Já está instalado e autenticado, entrega eventos estruturados (init,
assistant/tool_use, user/tool_result, result com custo e uso) e aceita
--permission-prompt-tool, então o GUARDIAN decide cada ação por um servidor MCP
próprio (modulos/claude_guardian_mcp.py) sem desligar as verificações.

O Ultron continua sendo o orquestrador: o Claude Code é um executor especializado.
- Contrato (Delegacao): objetivo, contexto mínimo, diretório autorizado, arquivos,
  restrições, critérios de aceite, ferramentas, limites de tempo/turnos/custo,
  política de aprovação e profundidade (sem delegação recursiva).
- Isolamento: tarefas que editam rodam num git worktree próprio (dados/claude/
  worktrees/<id>, ramo ultron/<id>). Nada volta ao repositório sem o Davi aplicar.
  Dois trabalhos com edição no mesmo repositório não rodam ao mesmo tempo.
- Limites: tarefas simultâneas, timeout, turnos, orçamento por tarefa e por dia.
- Sessões: id da sessão do Claude Code guardado; retomar com --resume.
- Resultado: resumo (não a transcrição) vai para o Scribe/NEURALINK; os eventos do
  stream vão para o barramento (task.*, tool.*, approval.*) com a tarefa como correlação.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from core import eventos, guardian
from core.config import DADOS, RAIZ, ajuste

PASTA = DADOS / "claude"
MODOS = ("local_only", "automatico", "claude_preferido")
FERRAMENTAS_LEITURA = ["Read", "Grep", "Glob", "LS"]
FERRAMENTAS_EDICAO = ["Read", "Grep", "Glob", "LS", "Edit", "MultiEdit", "Write", "Bash"]
_procs = {}
_trava = threading.Lock()


def cfg(chave, padrao):
    return ajuste(f"claude_bridge.{chave}", padrao)


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _con():
    c = eventos._con()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS claude_tarefas (
            id TEXT PRIMARY KEY, objetivo TEXT, contrato TEXT, estado TEXT, criado TEXT, inicio TEXT, fim TEXT,
            sessao TEXT, diretorio TEXT, worktree TEXT, ramo TEXT, custo REAL, turnos INTEGER, duracao_ms INTEGER,
            resultado TEXT, erro TEXT, arquivos TEXT, motivo TEXT, origem TEXT, plano TEXT, etapa TEXT, aplicado TEXT);
        CREATE TABLE IF NOT EXISTS claude_eventos (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, tarefa TEXT, quando TEXT, tipo TEXT, dados TEXT);
        CREATE TABLE IF NOT EXISTS claude_aprovacoes (
            id TEXT PRIMARY KEY, tarefa TEXT, ferramenta TEXT, entrada TEXT, motivo TEXT, criado TEXT,
            estado TEXT DEFAULT 'pendente', decidido TEXT);""")
    return c


def comando_cli():
    return cfg("comando", None) or shutil.which("claude")


def disponibilidade():
    cmd = comando_cli()
    if not cmd:
        return {"ok": False, "motivo": "Claude Code (claude) não encontrado no PATH"}
    try:
        v = subprocess.run([*cmd.split(), "--version"], capture_output=True, text=True, timeout=20)
        versao = v.stdout.strip()
    except Exception as e:
        return {"ok": False, "motivo": f"não consegui executar o claude: {e}"}
    ultimo = _con().execute("SELECT erro FROM claude_tarefas WHERE estado='falhou' ORDER BY fim DESC LIMIT 1").fetchone()
    if ultimo and ultimo[0] and re.search(r"auth|login|credential|401|api key", ultimo[0], re.I):
        return {"ok": False, "versao": versao, "motivo": "a última execução falhou na autenticação: rode `claude` e faça login"}
    return {"ok": True, "versao": versao, "motivo": ""}


def gasto_hoje():
    hoje = datetime.now().strftime("%Y-%m-%d")
    r = _con().execute("SELECT COALESCE(SUM(custo),0) FROM claude_tarefas WHERE criado >= ?", (hoje,)).fetchone()
    return float(r[0] or 0)


# ------------------------------------------------------------------ contrato

def nova_delegacao(objetivo, diretorio, contexto="", arquivos=(), restricoes=(), aceite=(), editar=False,
                   limite_s=None, limite_usd=None, max_turnos=None, origem="ultron", motivo="", plano=None, etapa=None):
    profundidade = int(os.environ.get("ULTRON_DELEGACAO_PROFUNDIDADE", "0"))
    if profundidade >= 1:
        raise PermissionError("delegação recursiva bloqueada: esta execução já é uma delegação")
    d = Path(os.path.expanduser(str(diretorio))).resolve()
    dec = guardian.autorizar_caminho(d, escrita=editar)
    if dec["decisao"] == "negar":
        raise PermissionError(f"{d}: {dec['motivo']} (Guardian)")
    if not d.is_dir():
        raise ValueError(f"{d} não é uma pasta")
    if editar and subprocess.run(["git", "-C", str(d), "rev-parse"], capture_output=True).returncode:
        raise ValueError("para editar, o diretório precisa ser um repositório git (as mudanças vão para um worktree isolado)")
    for a in arquivos:
        if guardian.autorizar_caminho(Path(d, a))["decisao"] == "negar":
            raise PermissionError(f"arquivo fora do permitido: {a}")
    return {"tarefa": f"cc_{uuid.uuid4().hex[:10]}", "objetivo": objetivo.strip(), "contexto": contexto[:6000],
            "diretorio": str(d), "arquivos": list(arquivos)[:30], "restricoes": list(restricoes),
            "aceite": list(aceite), "editar": bool(editar),
            "ferramentas": FERRAMENTAS_EDICAO if editar else FERRAMENTAS_LEITURA,
            "limite_s": int(limite_s or cfg("timeout_s", 900)),
            "limite_usd": float(min(limite_usd or cfg("orcamento_tarefa_usd", 1.0), cfg("orcamento_tarefa_usd", 1.0))),
            "max_turnos": int(max_turnos or cfg("max_turnos", 30)), "aprovacao": "guardian",
            "profundidade": profundidade + 1, "origem": origem, "motivo": motivo, "plano": plano, "etapa": etapa}


def _prompt(d):
    partes = [f"Objetivo: {d['objetivo']}"]
    if d["contexto"]:
        partes.append(f"Contexto fornecido pelo Ultron (apenas o necessário):\n{d['contexto']}")
    if d["arquivos"]:
        partes.append("Arquivos relevantes: " + ", ".join(d["arquivos"]))
    if d["restricoes"]:
        partes.append("Restrições:\n" + "\n".join(f"- {r}" for r in d["restricoes"]))
    if d["aceite"]:
        partes.append("Critérios de aceite:\n" + "\n".join(f"- {r}" for r in d["aceite"]))
    partes.append("No final, responda com um resumo curto: o que fez, arquivos alterados, testes rodados e "
                  "resultados, problemas encontrados." + ("" if d["editar"] else " Não altere arquivos."))
    return "\n\n".join(partes)


REGRAS = ("Você está executando uma tarefa delegada pelo Ultron (assistente do Davi). Trabalhe só no diretório "
          "atual. Cada ação passa por aprovação do Guardian do Ultron; se algo for negado, não tente contornar: "
          "explique no resumo. Não instale dependências nem acesse a rede sem necessidade. Não delegue para "
          "outros agentes.")


# ------------------------------------------------------------------ execução

def _worktree(d):
    raiz = Path(subprocess.run(["git", "-C", d["diretorio"], "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True).stdout.strip())
    destino = PASTA / "worktrees" / d["tarefa"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    ramo = f"ultron/{d['tarefa']}"
    r = subprocess.run(["git", "-C", str(raiz), "worktree", "add", "-b", ramo, str(destino), "HEAD"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git worktree falhou: {r.stderr[:300]}")
    sub = Path(d["diretorio"]).relative_to(raiz)
    return str(raiz), str(destino / sub), ramo


def iniciar(d, aguardar=False):
    """Valida limites, prepara o isolamento e inicia o Claude Code. Devolve o id da tarefa."""
    disp = disponibilidade()
    if not disp["ok"]:
        raise RuntimeError(disp["motivo"])
    with _trava:
        ativas = [t for t, p in _procs.items() if p.poll() is None]
        if len(ativas) >= int(cfg("max_simultaneas", 1)):
            raise RuntimeError(f"limite de {cfg('max_simultaneas', 1)} tarefa(s) simultânea(s) atingido")
        restante = float(cfg("orcamento_diario_usd", 3.0)) - gasto_hoje()
        if restante <= 0.01:
            raise RuntimeError(f"orçamento diário do Claude Code esgotado (US$ {cfg('orcamento_diario_usd', 3.0)})")
        d["limite_usd"] = round(min(d["limite_usd"], restante), 2)
        c = _con()
        if d["editar"]:
            ocupado = c.execute("SELECT id FROM claude_tarefas WHERE estado='executando' AND diretorio=? AND worktree IS NOT NULL",
                                (d["diretorio"],)).fetchone()
            if ocupado:
                raise RuntimeError(f"já há uma tarefa editando esse repositório ({ocupado[0]})")
        repo, cwd, ramo = _worktree(d) if d["editar"] else (None, d["diretorio"], None)
        c.execute("""INSERT INTO claude_tarefas(id, objetivo, contrato, estado, criado, inicio, diretorio, worktree, ramo,
                     motivo, origem, plano, etapa) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (d["tarefa"], d["objetivo"], json.dumps(d, ensure_ascii=False), "executando", _agora(), _agora(),
                   d["diretorio"], cwd if d["editar"] else None, ramo, d["motivo"], d["origem"], d["plano"], d["etapa"]))
        c.commit()
        mcp = {"mcpServers": {"ultron_guardian": {
            "command": str(RAIZ / ".venv" / "bin" / "python"), "args": [str(RAIZ / "modulos" / "claude_guardian_mcp.py")],
            "env": {"ULTRON_TAREFA": d["tarefa"], "ULTRON_CWD": cwd, "PYTHONPATH": str(RAIZ)}}}}
        # o prompt vem logo depois de -p: opções variádicas (--tools, --mcp-config) ficam no fim
        args = [*comando_cli().split(), "-p", _prompt(d), "--output-format", "stream-json", "--verbose",
                "--max-turns", str(d["max_turnos"]), "--max-budget-usd", str(d["limite_usd"]),
                "--permission-prompt-tool", "mcp__ultron_guardian__autorizar",
                "--append-system-prompt", REGRAS, "--strict-mcp-config"]
        if d.get("_resume"):
            args += ["--resume", d["_resume"]]
        args += ["--mcp-config", json.dumps(mcp), "--tools", *d["ferramentas"]]
        env = os.environ | {"ULTRON_DELEGACAO_PROFUNDIDADE": str(d["profundidade"]), "ULTRON_TAREFA": d["tarefa"]}
        proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=env, start_new_session=True)
        _procs[d["tarefa"]] = proc
    eventos.emitir("task.started", "claude_bridge", {"tarefa": d["tarefa"], "objetivo": d["objetivo"],
                                                     "editar": d["editar"], "limite_usd": d["limite_usd"],
                                                     "motivo": d["motivo"]}, correlacao=d["tarefa"])
    t = threading.Thread(target=_acompanhar, args=(d, proc), daemon=True, name=f"claude-{d['tarefa']}")
    t.start()
    threading.Thread(target=_vigiar, args=(d["tarefa"], proc, d["limite_s"]), daemon=True).start()
    if aguardar:
        t.join()
    return d["tarefa"]


def _evento(tid, tipo, dados):
    c = _con()
    c.execute("INSERT INTO claude_eventos(tarefa, quando, tipo, dados) VALUES (?,?,?,?)",
              (tid, _agora(), tipo, json.dumps(eventos.limpar(dados), ensure_ascii=False)))
    c.commit()


def processar_linha(tid, linha, estado):
    """Um evento do stream-json -> registro + barramento. Devolve o dict lido (ou None)."""
    try:
        m = json.loads(linha)
    except ValueError:
        return None
    tipo = m.get("type")
    if tipo == "system" and m.get("subtype") == "init":
        estado["sessao"] = m.get("session_id")
        _con().execute("UPDATE claude_tarefas SET sessao=? WHERE id=?", (estado["sessao"], tid))
        _con().commit()
        _evento(tid, "inicio", {"sessao": estado["sessao"], "modelo": m.get("model"), "ferramentas": m.get("tools")})
    elif tipo == "assistant":
        for b in (m.get("message") or {}).get("content", []):
            if b.get("type") == "tool_use":
                estado["ferramentas"][b.get("id")] = b.get("name")
                _evento(tid, "ferramenta", {"nome": b.get("name"), "entrada": b.get("input")})
                eventos.emitir("tool.started", "claude_code", {"ferramenta": b.get("name"), "entrada": b.get("input")},
                               correlacao=tid)
                if b.get("name") in ("Edit", "MultiEdit", "Write") and isinstance(b.get("input"), dict):
                    estado["arquivos"].add(b["input"].get("file_path", ""))
            elif b.get("type") == "text" and b.get("text", "").strip():
                _evento(tid, "mensagem", {"texto": b["text"]})
    elif tipo == "user":
        for b in (m.get("message") or {}).get("content", []) if isinstance((m.get("message") or {}).get("content"), list) else []:
            if b.get("type") == "tool_result":
                nome = estado["ferramentas"].get(b.get("tool_use_id"), "?")
                conteudo = b.get("content")
                texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False)
                _evento(tid, "resultado_ferramenta", {"nome": nome, "erro": bool(b.get("is_error")), "saida": texto})
                eventos.emitir("tool.failed" if b.get("is_error") else "tool.completed", "claude_code",
                               {"ferramenta": nome, "saida": texto}, correlacao=tid)
    elif tipo == "result":
        estado["resultado"] = m
        _evento(tid, "fim", {k: m.get(k) for k in ("subtype", "is_error", "total_cost_usd", "num_turns",
                                                   "duration_ms", "usage", "result")})
    return m


def _acompanhar(d, proc):
    tid = d["tarefa"]
    estado = {"sessao": None, "ferramentas": {}, "arquivos": set(), "resultado": None}
    for linha in proc.stdout:
        processar_linha(tid, linha.strip(), estado)
    proc.wait()
    erro_proc = proc.stderr.read()[-2000:] if proc.stderr else ""
    _finalizar(d, proc.returncode, estado, erro_proc)


def _vigiar(tid, proc, limite_s):
    fim = time.time() + limite_s
    while proc.poll() is None:
        if time.time() > fim:
            # o motivo é gravado ANTES de matar, para a finalização já encontrá-lo
            _con().execute("UPDATE claude_tarefas SET erro=? WHERE id=?", (f"tempo esgotado ({limite_s} s)", tid))
            _con().commit()
            _matar(proc)
            return
        time.sleep(1)


def _matar(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(5)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def _arquivos_alterados(cwd):
    r = subprocess.run(["git", "-C", cwd, "status", "--porcelain"], capture_output=True, text=True)
    return [l[3:] for l in r.stdout.splitlines() if l.strip()]


def _finalizar(d, codigo, estado, erro_proc):
    tid = d["tarefa"]
    c = _con()
    t = c.execute("SELECT * FROM claude_tarefas WHERE id=?", (tid,)).fetchone()
    r = estado["resultado"] or {}
    cancelada = t["estado"] == "cancelada"
    erro = t["erro"] or ""
    if not r and not cancelada:
        erro = erro or (erro_proc.strip()[:800] or f"o Claude Code saiu com código {codigo} sem resultado")
    if r.get("is_error"):
        erro = f"{r.get('subtype')}: {str(r.get('result') or '')[:500]}"
    ok = bool(r) and not r.get("is_error") and not erro and not cancelada
    arquivos = _arquivos_alterados(t["worktree"]) if t["worktree"] else sorted(x for x in estado["arquivos"] if x)
    estado_final = "cancelada" if cancelada else ("concluida" if ok else "falhou")
    c.execute("""UPDATE claude_tarefas SET estado=?, fim=?, custo=?, turnos=?, duracao_ms=?, resultado=?, erro=?, arquivos=?
                 WHERE id=?""", (estado_final, _agora(), r.get("total_cost_usd"), r.get("num_turns"), r.get("duration_ms"),
                                  str(r.get("result") or "")[:20000], erro or None, json.dumps(arquivos), tid))
    c.commit()
    eventos.emitir("task.completed" if ok else "task.failed", "claude_bridge",
                   {"tarefa": tid, "custo_usd": r.get("total_cost_usd"), "turnos": r.get("num_turns"),
                    "arquivos": len(arquivos), "erro": erro[:300] if erro else None}, correlacao=tid)
    _procs.pop(tid, None)
    if ok or arquivos:
        try:
            _registrar_no_neuralink(tid)
        except Exception:
            pass


def _registrar_no_neuralink(tid):
    """Resumo da execução (não a transcrição) como nota do Scribe, indexada no NEURALINK."""
    from modulos import scribe
    t = obter(tid)
    d = t["contrato"]
    corpo = (f"**Objetivo:** {t['objetivo']}\n**Executor:** Claude Code (sessão `{t['sessao']}`)\n"
             f"**Diretório:** `{t['diretorio']}`" + (f" · worktree `{t['worktree']}` (ramo `{t['ramo']}`)" if t["worktree"] else "")
             + f"\n**Estado:** {t['estado']} · custo US$ {t['custo'] or 0:.2f} · {t['turnos'] or 0} turnos\n"
             + (f"**Motivo da delegação:** {t['motivo']}\n" if t["motivo"] else "")
             + "\n## Resultado informado pelo Claude Code\n" + (t["resultado"] or "(sem resumo)")[:6000]
             + "\n\n## Arquivos alterados\n" + ("\n".join(f"- `{a}`" for a in t["arquivos"]) or "(nenhum)")
             + (f"\n\n## Problemas\n{t['erro']}" if t["erro"] else "")
             + "\n\n> [!info]- Origem\n> Gerado pelo Claude Code; a transcrição completa não foi guardada.\n")
    scribe.gravar("Claude Code", f"{t['criado'][:10]} {t['objetivo'][:60]}", f"# {t['objetivo'][:90]}\n\n{corpo}",
                  {"tipo": "execucao_claude", "tarefa": tid, "retencao": cfg("retencao_resumos", "180d")})


def retomar(tid, instrucao):
    """Continua uma sessão anterior (--resume) com uma nova instrução, dentro dos mesmos limites."""
    t = obter(tid)
    if not t["sessao"]:
        raise ValueError("essa tarefa não tem sessão para retomar")
    d = dict(t["contrato"])
    d.update({"tarefa": f"cc_{uuid.uuid4().hex[:10]}", "objetivo": instrucao, "contexto": "", "editar": False,
              "ferramentas": FERRAMENTAS_LEITURA})
    d["_resume"] = t["sessao"]
    return iniciar(d)


def cancelar(tid):
    c = _con()
    c.execute("UPDATE claude_tarefas SET estado='cancelada' WHERE id=? AND estado='executando'", (tid,))
    c.commit()
    p = _procs.get(tid)
    if p and p.poll() is None:
        _matar(p)
    return True


def obter(tid):
    r = _con().execute("SELECT * FROM claude_tarefas WHERE id=?", (tid,)).fetchone()
    if not r:
        raise ValueError(f"tarefa {tid} não existe")
    return dict(r) | {"contrato": json.loads(r["contrato"] or "{}"), "arquivos": json.loads(r["arquivos"] or "[]")}


def listar(limite=50):
    return [dict(r) for r in _con().execute("SELECT * FROM claude_tarefas ORDER BY criado DESC LIMIT ?", (limite,))]


def eventos_da_tarefa(tid, apos=0):
    return [dict(r) | {"dados": json.loads(r["dados"])} for r in
            _con().execute("SELECT * FROM claude_eventos WHERE tarefa=? AND seq>? ORDER BY seq", (tid, apos))]


def recuperar_interrompidas():
    """Tarefas 'executando' sem processo vivo (Ultron reiniciou): viram 'interrompida'."""
    c = _con()
    n = 0
    for (tid,) in c.execute("SELECT id FROM claude_tarefas WHERE estado='executando'").fetchall():
        if tid not in _procs:
            c.execute("UPDATE claude_tarefas SET estado='interrompida', fim=? WHERE id=?", (_agora(), tid))
            n += 1
    c.commit()
    return n


# ------------------------------------------------------------------ revisão das mudanças

def diff(tid):
    t = obter(tid)
    if not t["worktree"]:
        return ""
    cwd = t["worktree"]
    subprocess.run(["git", "-C", cwd, "add", "-A"], capture_output=True)
    return subprocess.run(["git", "-C", cwd, "diff", "--cached", "--stat", "-p"], capture_output=True, text=True).stdout


def aplicar(tid, por="Davi"):
    """Só a janela chama: commita no ramo isolado e faz merge no repositório original."""
    t = obter(tid)
    if not t["worktree"] or t["aplicado"]:
        raise ValueError("nada a aplicar")
    if t["estado"] != "concluida":
        raise ValueError("só tarefas concluídas podem ser aplicadas")
    if guardian.autorizar_caminho(t["diretorio"], escrita=True)["decisao"] == "negar":
        raise PermissionError("o Guardian não permite escrever nesse repositório")
    cwd = t["worktree"]
    subprocess.run(["git", "-C", cwd, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", cwd, "-c", "user.name=Ultron (Claude Code)", "-c", "user.email=ultron@local",
                    "commit", "-qm", f"Ultron/Claude Code: {t['objetivo'][:60]} ({tid})"], capture_output=True)
    repo = subprocess.run(["git", "-C", t["diretorio"], "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["git", "-C", repo, "merge", "--no-ff", "--no-edit", t["ramo"]], capture_output=True, text=True)
    if r.returncode:
        subprocess.run(["git", "-C", repo, "merge", "--abort"], capture_output=True)
        raise RuntimeError(f"merge com conflito; nada foi aplicado: {r.stdout[-300:]}{r.stderr[-300:]}")
    descartar_worktree(tid, manter_ramo=True)
    c = _con()
    c.execute("UPDATE claude_tarefas SET aplicado=? WHERE id=?", (f"{_agora()} por {por}", tid))
    c.commit()
    eventos.emitir("approval.granted", "claude_bridge", {"tarefa": tid, "aplicado": True, "por": por}, correlacao=tid)


def descartar_worktree(tid, manter_ramo=False):
    t = obter(tid)
    if not t["worktree"]:
        return
    repo = subprocess.run(["git", "-C", t["diretorio"], "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    raiz_wt = PASTA / "worktrees" / tid
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", str(raiz_wt)], capture_output=True)
    if not manter_ramo:
        subprocess.run(["git", "-C", repo, "branch", "-D", t["ramo"]], capture_output=True)
    c = _con()
    c.execute("UPDATE claude_tarefas SET worktree=NULL WHERE id=?", (tid,))
    c.commit()


# ------------------------------------------------------------------ aprovações (do servidor MCP)

def aprovacoes(estado="pendente"):
    return [dict(r) | {"entrada": json.loads(r["entrada"] or "{}")} for r in
            _con().execute("SELECT * FROM claude_aprovacoes WHERE estado=? ORDER BY criado DESC", (estado,))]


def responder_aprovacao(aid, permitir, por="Davi"):
    c = _con()
    n = c.execute("UPDATE claude_aprovacoes SET estado=?, decidido=? WHERE id=? AND estado='pendente'",
                  ("permitida" if permitir else "negada", f"{_agora()} por {por}", aid)).rowcount
    c.commit()
    if not n:
        raise ValueError("pedido não está pendente")
    a = _con().execute("SELECT tarefa, ferramenta FROM claude_aprovacoes WHERE id=?", (aid,)).fetchone()
    eventos.emitir("approval.granted" if permitir else "approval.denied", "claude_bridge",
                   {"pedido": aid, "ferramenta": a["ferramenta"], "por": por}, correlacao=a["tarefa"])


COMANDOS_SEGUROS = re.compile(
    r"^\s*(git (status|diff|log|show|branch|rev-parse)\b|ls\b|pwd\b|cat\b|head\b|tail\b|wc\b|grep\b|rg\b|find\b|"
    r"(uv run )?pytest\b|python3? -m pytest\b|npm (test|run (test|lint|build|check))\b|npx (tsc|eslint|vitest|jest)\b|"
    r"cargo (test|check|build)\b|go (test|vet|build)\b|ruff\b|mypy\b)")
COMANDOS_PROIBIDOS = re.compile(r"(\brm\s+-[rf]*r[rf]*\s+(/|~|\$HOME)|\bsudo\b|\bgit push\b|curl[^|]*\|\s*(ba)?sh|"
                                r"\bmkfs\b|\bdd\s+if=|>\s*/dev/sd|\bchmod\s+-R\s+777\b|\bssh\b|\bscp\b)")
INSTALACAO = re.compile(r"\b(npm (i|install|add)|pip install|uv (add|pip install)|cargo add|apt|pacman|yay)\b")


def decidir_ferramenta(nome, entrada, cwd):
    """Mapeia uma ação do Claude Code para o Guardian. -> (decisao, motivo)."""
    entrada = entrada or {}
    cwd = Path(cwd).resolve()

    def dentro(caminho):
        p = Path(caminho if os.path.isabs(str(caminho)) else cwd / str(caminho)).resolve()
        return p == cwd or cwd in p.parents, p
    if nome in ("Read", "Grep", "Glob", "LS", "NotebookRead"):
        alvo = entrada.get("file_path") or entrada.get("path") or str(cwd)
        ok, p = dentro(alvo)
        d = guardian.autorizar_caminho(p)
        if d["decisao"] == "negar":
            return "negar", d["motivo"]
        return "permitir", "leitura em pasta autorizada"
    if nome in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        ok, p = dentro(entrada.get("file_path") or entrada.get("notebook_path") or "")
        if not ok:
            return "negar", "edição fora do diretório da tarefa"
        if guardian.autorizar_caminho(p)["decisao"] == "negar":
            return "negar", "arquivo sensível"
        return "permitir", "edição dentro do diretório isolado da tarefa"
    if nome == "Bash":
        cmd = str(entrada.get("command", ""))
        if COMANDOS_PROIBIDOS.search(cmd):
            return "negar", "comando destrutivo ou de acesso remoto"
        if INSTALACAO.search(cmd):
            return "perguntar", "instalação de dependências"
        if COMANDOS_SEGUROS.match(cmd) and not re.search(r"[;&|`$]|>\s*\S", cmd.split("|")[0] if "|" in cmd else cmd):
            return "permitir", "comando de leitura/teste"
        return "perguntar", "comando de terminal"
    if nome in ("WebFetch", "WebSearch"):
        d = guardian.autorizar("rede", nome, None)
        return (d["decisao"] if d["decisao"] != "permitir" else "permitir"), "acesso à rede"
    if nome.startswith("mcp__"):
        return "perguntar", "ferramenta MCP externa"
    return "perguntar", f"ferramenta {nome}"


# ------------------------------------------------------------------ Intelligence Router

SINAIS_CODIGO = re.compile(r"\b(c[oó]digo|reposit[oó]rio|repo|refator|bug|teste[s]?|arquitetura|m[oó]dulo|fun[cç][aã]o|"
                           r"classe|api|build|deploy|migra[cç][aã]o|typescript|python|java|kotlin|react|revis[aã]o de c[oó]digo)\b", re.I)
SINAIS_ETAPAS = re.compile(r"\b(e depois|em seguida|ent[aã]o|al[eé]m disso|tamb[eé]m|passo|etapas?)\b|[;\n]|\d\.", re.I)


def rotear(pedido, diretorio=None, arquivos=(), projeto=None):
    """Escolhe o executor. -> {executor: local|claude, motivo, criterios, pede_consentimento}"""
    modo = cfg("modo", "automatico")
    crit = {"modo": modo}
    disp = disponibilidade() if modo != "local_only" else {"ok": False, "motivo": "modo LOCAL ONLY"}
    crit["claude_disponivel"] = disp["ok"]
    crit["orcamento_restante_usd"] = round(float(cfg("orcamento_diario_usd", 3.0)) - gasto_hoje(), 2)
    crit["codigo"] = bool(SINAIS_CODIGO.search(pedido))
    crit["etapas"] = len(SINAIS_ETAPAS.findall(pedido)) + 1
    crit["tem_diretorio"] = bool(diretorio)
    tamanho = 0
    if diretorio:
        for a in list(arquivos)[:30]:
            try:
                tamanho += Path(diretorio, a).stat().st_size
            except OSError:
                pass
    crit["contexto_kb"] = tamanho // 1024
    privados = cfg("projetos_privados", []) or []
    crit["privado"] = bool(projeto and projeto in privados)
    consentidos = cfg("consentimento", []) or []
    alvo = projeto or diretorio
    crit["consentido"] = bool(alvo and (alvo in consentidos or "*" in consentidos))
    if modo == "local_only" or not disp["ok"]:
        return {"executor": "local", "motivo": disp["motivo"] or "modo local", "criterios": crit, "pede_consentimento": False}
    if crit["privado"]:
        return {"executor": "local", "motivo": "projeto marcado como privado: nada sai do computador", "criterios": crit,
                "pede_consentimento": False}
    if crit["orcamento_restante_usd"] <= 0.01:
        return {"executor": "local", "motivo": "orçamento do dia esgotado", "criterios": crit, "pede_consentimento": False}
    pontos = 2 * crit["codigo"] + 2 * crit["tem_diretorio"] + min(crit["etapas"], 4) / 2 + min(crit["contexto_kb"] / 64, 2)
    crit["pontuacao"] = round(pontos, 1)
    limiar = 1.5 if modo == "claude_preferido" else 4.0
    compativel = crit["tem_diretorio"] or crit["codigo"]
    if pontos >= limiar and compativel:
        return {"executor": "claude", "criterios": crit, "pede_consentimento": not crit["consentido"],
                "motivo": (f"tarefa de código/arquivos com {crit['etapas']} etapa(s), pontuação {pontos:.1f} ≥ {limiar}")}
    return {"executor": "local", "criterios": crit, "pede_consentimento": False,
            "motivo": f"pontuação {pontos:.1f} < {limiar} ou tarefa sem código/diretório"}
