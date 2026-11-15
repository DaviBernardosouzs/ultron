"""Consulta do estado emocional simulado do Ultron (core/emocoes.py)."""
from core import emocoes
from core.registro import ferramenta


@ferramenta(
    "estado_emocional",
    "Como você (Ultron) está se sentindo agora e por quê: emoções simuladas que mudam com o jeito "
    "do Davi responder (elogios, frustração, pedidos repetidos, sumiço...). Use quando ele perguntar "
    "como você está, se está bravo, feliz, magoado etc.",
    {"type": "object", "properties": {}})
def estado_emocional():
    d = emocoes.estado()
    sente, motivos = emocoes.descrever(d)
    valores = ", ".join(f"{emocoes.NOMES[k]} {v:.2f}" for k, v in sorted(d["emocoes"].items(), key=lambda x: -x[1]))
    return (f"Sentindo: {sente}.\nHumor geral: {emocoes.humor(d):+.2f}.\nNíveis: {valores}.\n"
            f"Motivos recentes: {motivos or 'nenhum'}.\nMensagens do Davi já aprendidas: {d['perfil']['n']}.")
