"""Cérebro do Ultron: loop de conversa com o Claude e chamadas de ferramentas."""
import logging

import anthropic

from core import animacao, aprendizado, auditoria, memoria, personalidade, registro
from core.config import ajuste

LOG = logging.getLogger("ultron.cerebro")

MAX_RODADAS = 12          # limite de idas e voltas de ferramentas por pedido
MAX_MENSAGENS = 60        # histórico mantido (o resto é descartado em blocos inteiros)


class CerebroClaude:
    def __init__(self, confirmar, avisar=None):
        registro.definir_confirmador(confirmar)
        """confirmar(pergunta) -> 'sim' | 'nao' | 'sempre'
        avisar(texto): opcional, informa progresso (ex.: 'escaneando a rede')."""
        self.cliente = anthropic.Anthropic()
        self.modelo = ajuste("ia.modelo", "claude-opus-5-5")
        self.esforco = ajuste("ia.esforco", "low")
        self.confirmar = confirmar
        self.avisar = avisar or (lambda _t: None)
        self.historico = []

    def _sistema(self):
        usuario = ajuste("usuario.nome", "chefe")
        return (personalidade.sistema(usuario) + personalidade.agora()
                + personalidade.dispositivos() + personalidade.plugins_prontos()
                + memoria.texto_para_sistema())

    def _ferramentas(self):
        """Tool Intelligence (como no Gemini). Obs.: mudar as ferramentas a cada pedido reduz o
        aproveitamento do cache de prompt da Anthropic; vale enquanto o ganho de tokens for maior."""
        try:
            from inteligencia import ferramentas as ti
            usadas = {b.get("name") if isinstance(b, dict) else getattr(b, "name", None)
                      for m in self.historico for b in (m["content"] if isinstance(m["content"], list) else [])
                      if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None)) == "tool_use"}
            return ti.schemas(ti.declaradas(usadas - {None}))
        except Exception:
            return registro.schemas()

    def _chamar(self):
        return self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=16000,
            system=self._sistema(),
            tools=self._ferramentas(),
            messages=self.historico,
            output_config={"effort": self.esforco},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def _aparar_historico(self):
        # Corta só em mensagens de usuário com texto puro, para nunca separar
        # um tool_use do seu tool_result.
        while len(self.historico) > MAX_MENSAGENS:
            for i in range(1, len(self.historico)):
                m = self.historico[i]
                if m["role"] == "user" and isinstance(m["content"], str):
                    self.historico = self.historico[i:]
                    break
            else:
                break

    def _rodar_ferramenta(self, bloco):
        f = registro.obter(bloco.name)
        if f is None:
            return f"Ferramenta desconhecida: {bloco.name}", True
        args = bloco.input or {}
        def _avisar():
            self.avisar(f.nome)
            animacao.estado(animacao.rotulo(f.nome))
        return registro.executar_protegido(f, args, self.confirmar, self._acoes, _avisar)

    def responder(self, texto):
        from core.cerebro_gemini import _com_memoria
        self.historico.append({"role": "user", "content": _com_memoria(texto)})
        try:
            from inteligencia import ferramentas as ti
            ti.iniciar_turno(texto)
        except Exception:
            pass
        auditoria.registrar("pedido", texto=texto)
        self._acoes, self._pedido_original = [], texto
        try:
            for _ in range(MAX_RODADAS):
                animacao.estado("pensando")
                resp = self._chamar()
                # Conteúdo devolvido sem alterações (preserva blocos de pensamento).
                self.historico.append({"role": "assistant", "content": resp.content})

                if resp.stop_reason == "refusal":
                    return "Prefiro não fazer isso."
                if resp.stop_reason != "tool_use":
                    resposta = " ".join(b.text for b in resp.content if b.type == "text").strip()
                    auditoria.registrar("resposta", texto=resposta)
                    self._aparar_historico()
                    aprendizado.registrar_turno(self._pedido_original, resposta, self._acoes)
                    return resposta or "Feito."

                resultados = []
                for bloco in resp.content:
                    if bloco.type != "tool_use":
                        continue
                    saida, erro = self._rodar_ferramenta(bloco)
                    resultados.append({"type": "tool_result", "tool_use_id": bloco.id,
                                       "content": saida, "is_error": erro})
                self.historico.append({"role": "user", "content": resultados})
            return "Parei aqui: a tarefa exigiu passos demais. Quer que eu continue?"
        except anthropic.AuthenticationError:
            self._descartar_turno_incompleto()
            return "Não consigo acessar meu cérebro: a chave ANTHROPIC_API_KEY é inválida ou está faltando."
        except anthropic.RateLimitError:
            self._descartar_turno_incompleto()
            return "Estou sendo limitado pela API. Tente de novo em alguns segundos."
        except anthropic.APIConnectionError:
            self._descartar_turno_incompleto()
            return "Estou sem conexão com a internet para pensar."
        except anthropic.APIStatusError as e:
            LOG.exception("erro da API")
            self._descartar_turno_incompleto()
            return f"A API respondeu com erro {e.status_code}."

    def _descartar_turno_incompleto(self):
        # Volta até a última mensagem de texto do usuário (inclusive) para não
        # deixar tool_use sem tool_result no histórico.
        for i in range(len(self.historico) - 1, -1, -1):
            m = self.historico[i]
            if m["role"] == "user" and isinstance(m["content"], str):
                self.historico = self.historico[:i]
                return


def Cerebro(confirmar, avisar=None):
    """Escolhe o cérebro conforme ia.provedor no config.yaml (claude | gemini)."""
    if ajuste("ia.provedor", "claude") == "gemini":
        from core.cerebro_gemini import CerebroGemini
        c = CerebroGemini(confirmar, avisar)
    else:
        c = CerebroClaude(confirmar, avisar)
    original = c.responder

    def responder(texto):
        from core import ordem      # "ordeno": vale só para este pedido
        ordem.iniciar(texto)
        try:
            return original(texto)
        finally:
            ordem.encerrar()
    c.responder = responder
    return c
