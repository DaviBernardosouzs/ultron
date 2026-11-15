"""Cérebro do Ultron usando a API Gemini (Google AI Studio), via REST.

Mesma interface do cérebro do Claude: Cerebro(confirmar, avisar).responder(texto).
As partes devolvidas pelo modelo voltam intactas ao histórico, para preservar
as thoughtSignature exigidas pelos modelos Gemini 3 nas chamadas de ferramenta.
"""
import logging
import time

import requests

from core import animacao, aprendizado, auditoria, memoria, personalidade, registro
from core.config import ajuste, segredo

LOG = logging.getLogger("ultron.cerebro")

URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MAX_RODADAS = 12
MAX_MENSAGENS = 60
TENTATIVAS = 2            # por modelo, em erros temporários (500/503)

# modelo -> horário (epoch) até quando ele fica de fora por falta de cota.
_GELADEIRA = {}


def _espera_sugerida(erro, msg):
    """Quanto tempo deixar um modelo sem cota de fora (segundos)."""
    if "per day" in msg.lower() or "PerDay" in msg:
        return 3600
    for d in erro.get("details", []) or []:
        atraso = d.get("retryDelay")
        if atraso and atraso.endswith("s"):
            try:
                return max(10, int(float(atraso[:-1])))
            except ValueError:
                pass
    return 600


class ErroAPI(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


class CerebroGemini:
    def __init__(self, confirmar, avisar=None):
        registro.definir_confirmador(confirmar)
        self.chave = segredo("GEMINI_API_KEY")
        principal = ajuste("ia.modelo_gemini", "gemini-3.5-flash")
        reservas = ajuste("ia.reservas_gemini", ["gemini-3.6-flash", "gemini-3.1-flash-lite"]) or []
        self.modelos = [principal] + [m for m in reservas if m != principal]
        # "minimal" é o mais rápido no Gemini Flash; "low"/"medium" raciocinam mais.
        self.esforco = ajuste("ia.esforco_gemini", "minimal")
        self.sessao = requests.Session()  # reaproveita a conexão TLS entre chamadas
        self.confirmar = confirmar
        self.avisar = avisar or (lambda _t: None)
        self.historico = []

    def _sistema(self):
        usuario = ajuste("usuario.nome", "chefe")
        return (personalidade.sistema(usuario) + personalidade.agora()
                + personalidade.dispositivos() + personalidade.plugins_prontos()
                + memoria.texto_para_sistema())

    def _usadas_no_historico(self):
        return {p["functionCall"]["name"] for m in self.historico for p in m.get("parts", []) if "functionCall" in p}

    def _ferramentas(self):
        # Tool Intelligence: só as relevantes ao pedido (+ usadas no histórico + descobertas no turno)
        try:
            from inteligencia import ferramentas as ti
            fs = ti.declaradas(self._usadas_no_historico())
        except Exception as e:
            LOG.warning("seleção de ferramentas falhou, mandando todas: %s", e)
            fs = registro.todas()
        return [{"functionDeclarations": [
            {"name": f.nome, "description": f.descricao, "parametersJsonSchema": f.parametros} for f in fs]}]

    def _corpo(self):
        return {
            "systemInstruction": {"parts": [{"text": self._sistema()}]},
            "contents": self.historico,
            "tools": self._ferramentas(),
            "generationConfig": {"thinkingConfig": {"thinkingLevel": getattr(self, "_esforco_turno", None) or self.esforco}},
        }

    def _chamar(self):
        """Tenta os modelos em ordem. Modelo sem cota (429) vai para a "geladeira"
        e é pulado direto nas próximas chamadas, sem esperas."""
        corpo = self._corpo()
        ultimo = None
        agora = time.time()
        disponiveis = [m for m in self.modelos if _GELADEIRA.get(m, 0) <= agora] or self.modelos
        try:
            from inteligencia import roteador
            disponiveis = roteador.ordenar_modelos(disponiveis)     # reservas pela taxa de sucesso observada
        except Exception:
            pass
        for modelo in disponiveis:
            for tentativa in range(TENTATIVAS):
                try:
                    r = self.sessao.post(URL.format(modelo), json=corpo,
                                         timeout=(5, ajuste("ia.tempo_limite", 15)),
                                         headers={"x-goog-api-key": self.chave})
                except requests.Timeout:
                    # Servidor lento (comum no plano gratuito): tenta o próximo modelo.
                    LOG.warning("%s demorou demais; tentando o próximo", modelo)
                    ultimo = ErroAPI(503, "tempo esgotado")
                    break
                except requests.RequestException as e:
                    raise ErroAPI(0, str(e)) from e
                if r.ok:
                    self.modelo_usado = modelo
                    return r.json()
                try:
                    erro = r.json()["error"]
                    msg = erro["message"]
                except Exception:
                    erro, msg = {}, r.text[:200]
                ultimo = ErroAPI(r.status_code, msg)
                if r.status_code not in (429, 500, 503):
                    raise ultimo
                if r.status_code == 429:
                    pausa = _espera_sugerida(erro, msg)
                    _GELADEIRA[modelo] = time.time() + pausa
                    LOG.warning("%s sem cota; pulando por %ds", modelo, pausa)
                    break
                if tentativa == TENTATIVAS - 1:
                    break
                LOG.warning("%s respondeu %s (%s); tentando de novo", modelo, r.status_code, msg)
                time.sleep(0.5 * (tentativa + 1))
        raise ultimo

    def _aparar_historico(self):
        # Corta só em mensagens do usuário com texto puro, para nunca separar
        # um functionCall do seu functionResponse.
        while len(self.historico) > MAX_MENSAGENS:
            for i in range(1, len(self.historico)):
                if _texto_do_usuario(self.historico[i]):
                    self.historico = self.historico[i:]
                    break
            else:
                break

    def _rodar_ferramenta(self, nome, args):
        f = registro.obter(nome)
        if f is None:
            return f"Ferramenta desconhecida: {nome}", True
        def _avisar():
            self.avisar(f.nome)
            animacao.estado(animacao.rotulo(f.nome))
        return registro.executar_protegido(f, args, self.confirmar, self._acoes, _avisar)

    def responder(self, texto):
        if not self.chave:
            return "Não consigo acessar meu cérebro: falta GEMINI_API_KEY no .env."
        try:
            from inteligencia import ferramentas as ti
            ti.iniciar_turno(texto)
        except Exception:
            pass
        auditoria.registrar("pedido", texto=texto)
        # HIVE MIND: modelo e esforço para este pedido
        t0 = time.time()
        try:
            from inteligencia import intencao, roteador
            classe = intencao.classificar(texto)["classe"]
            decisao = roteador.decidir(texto, classe)
        except Exception as e:
            LOG.warning("roteador indisponível: %s", e)
            classe, decisao = "?", {"executor": "gemini", "esforco": None, "motivo": "padrão"}
        if decisao["executor"] == "bloqueado":
            auditoria.registrar("resposta", texto=decisao["motivo"])
            return decisao["motivo"][0].upper() + decisao["motivo"][1:] + "."
        if decisao["executor"] == "local":
            return self._responder_local(texto, classe, decisao, t0)
        self._esforco_turno = decisao["esforco"]
        self.modelo_usado = None
        self.historico.append({"role": "user", "parts": [{"text": _com_memoria(texto)}]})
        self._acoes, self._pedido_original = [], texto
        try:
            for _ in range(MAX_RODADAS):
                animacao.estado("pensando")
                resp = self._chamar()
                candidatos = resp.get("candidates") or []
                if not candidatos or "content" not in candidatos[0]:
                    motivo = (resp.get("promptFeedback") or {}).get("blockReason") \
                        or (candidatos[0].get("finishReason") if candidatos else "vazio")
                    self._descartar_turno_incompleto()
                    return "Prefiro não fazer isso." if motivo in ("SAFETY", "PROHIBITED_CONTENT") \
                        else f"Não obtive resposta do modelo ({motivo})."
                conteudo = candidatos[0]["content"]
                conteudo.setdefault("role", "model")
                partes = conteudo.get("parts") or []
                self.historico.append(conteudo)

                chamadas = [p["functionCall"] for p in partes if "functionCall" in p]
                if not chamadas:
                    resposta = " ".join(p["text"] for p in partes
                                        if "text" in p and not p.get("thought")).strip()
                    auditoria.registrar("resposta", texto=resposta)
                    try:
                        roteador.registrar(self.modelo_usado, True, (time.time() - t0) * 1000, self._esforco_turno,
                                           classe, decisao["motivo"])
                    except Exception:
                        pass
                    self._aparar_historico()
                    aprendizado.registrar_turno(self._pedido_original, resposta, self._acoes)
                    return resposta or "Feito."

                resultados = []
                for c in chamadas:
                    saida, erro = self._rodar_ferramenta(c["name"], c.get("args") or {})
                    retorno = {"functionResponse": {
                        "name": c["name"],
                        "response": {"error": saida} if erro else {"result": saida}}}
                    if "id" in c:
                        retorno["functionResponse"]["id"] = c["id"]
                    resultados.append(retorno)
                self.historico.append({"role": "user", "parts": resultados})
            return "Parei aqui: a tarefa exigiu passos demais. Quer que eu continue?"
        except ErroAPI as e:
            LOG.error("erro da API Gemini %s: %s", e.status, e)
            try:
                from inteligencia import roteador as _r
                _r.registrar(getattr(self, "modelo_usado", None) or self.modelos[0], False, (time.time() - t0) * 1000,
                             getattr(self, "_esforco_turno", None), classe, f"erro {e.status}")
            except Exception:
                pass
            self._descartar_turno_incompleto()
            if e.status in (401, 403) or (e.status == 400 and "API key" in str(e)):
                return "Não consigo acessar meu cérebro: a chave GEMINI_API_KEY é inválida."
            if e.status == 429:
                return "Estou sendo limitado pela API. Tente de novo em alguns segundos."
            if e.status in (500, 503):
                return "Os servidores do Gemini estão sobrecarregados agora. Tente de novo daqui a pouco."
            if e.status == 0:
                return "Estou sem conexão com a internet para pensar."
            return f"A API respondeu com erro {e.status}."

    def _responder_local(self, texto, classe, decisao, t0):
        """Pedido sensível ou modo LOCAL ONLY: modelo local do desktop, sem ferramentas e sem nuvem."""
        from inteligencia import roteador
        hist = [{"role": "user" if m["role"] == "user" else "assistant",
                 "content": " ".join(p.get("text", "") for p in m.get("parts", []) if "text" in p)}
                for m in self.historico if any("text" in p for p in m.get("parts", []))]
        try:
            resposta, modelo, ms = roteador.responder_local(hist, texto)
            ok = True
        except Exception as e:
            resposta, modelo, ms, ok = f"O modelo local não respondeu ({e}).", "local", (time.time() - t0) * 1000, False
        roteador.registrar(modelo, ok, ms, None, classe, decisao["motivo"])
        self.historico += [{"role": "user", "parts": [{"text": texto}]}, {"role": "model", "parts": [{"text": resposta}]}]
        auditoria.registrar("resposta", texto=f"[modelo local] {resposta}")
        return resposta

    def _descartar_turno_incompleto(self):
        for i in range(len(self.historico) - 1, -1, -1):
            if _texto_do_usuario(self.historico[i]):
                self.historico = self.historico[:i]
                return


def _texto_do_usuario(m):
    return m.get("role") == "user" and all("text" in p for p in m.get("parts", []))


def _com_memoria(texto):
    """Context Budget Manager: escolhe as fontes pela intenção do pedido e respeita um orçamento.
    Conversa simples não busca documentos; pergunta factual traz biblioteca e documentos; tarefa com
    ferramenta traz só memórias. Cada fonte é cortada para caber; o uso vai para o barramento."""
    from core.config import ajuste
    try:
        from inteligencia import intencao
        cls = intencao.classificar(texto)
    except Exception:
        cls = {"classe": "pesquisa", "sinais": ["classificador indisponível"]}
    perfil = intencao.PERFIL_CONTEXTO.get(cls["classe"]) if "intencao" in dir() else None
    perfil = perfil or {"memorias": True, "documentos": True, "biblioteca": True}
    orcamento = int(ajuste("inteligencia.orcamento_contexto", 6000))
    partes, usado = [], {}

    def acrescentar(nome, fn, fatia):
        try:
            bloco = fn(texto) or ""
        except Exception as e:
            LOG.warning("contexto %s falhou: %s", nome, e)
            return
        limite = int(orcamento * fatia)
        if len(bloco) > limite:
            bloco = bloco[:limite].rsplit("\n", 1)[0] + "\n[... cortado pelo orçamento de contexto]\n"
        usado[nome] = len(bloco)
        partes.append(bloco)
    try:
        from core import workspaces
        partes.append(workspaces.linha_para_prompt())
    except Exception:
        pass
    try:
        from core import autoaprovar, emocoes, ordem
        emocoes.registrar_mensagem(texto)
        partes.append(emocoes.linha_para_prompt())
        partes.append(autoaprovar.linha_para_prompt())
        partes.append(ordem.linha_para_prompt())
    except Exception as e:
        LOG.warning("emoções/auto-aprovar: %s", e)
    if perfil["memorias"]:
        from core import cofre
        acrescentar("memorias", cofre.contexto_para_pedido, 0.35)
    if perfil["biblioteca"]:
        from core import biblioteca
        acrescentar("biblioteca", biblioteca.contexto_para_pedido, 0.30)
    if perfil["documentos"]:
        from neuralink import contexto
        acrescentar("documentos", contexto.montar, 0.35)
    try:
        from inteligencia import ferramentas as ti, reflex
        partes.append(reflex.avisos([f.nome for f in ti.declaradas()]))     # não repetir erro conhecido
    except Exception:
        pass
    try:
        from core import eventos
        from inteligencia import ferramentas as ti
        enviadas = ti.declaradas()
        eventos.emitir("task.progress", "contexto", {
            "etapa": "contexto", "intencao": cls["classe"], "sinais": cls.get("sinais"),
            "contexto_chars": sum(usado.values()), "fontes": usado,
            "ferramentas": len(enviadas), "ferramentas_peso_aprox": len(str(ti.schemas(enviadas))) // 4})
    except Exception:
        pass
    return "".join(partes) + texto
