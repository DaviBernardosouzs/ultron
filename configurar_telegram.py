"""Assistente de configuração do bot do Telegram do Ultron.

1. Pede o token do @BotFather (sem mostrar na tela) e testa.
2. Espera você mandar uma mensagem para o bot e grava o seu ID como dono.
3. Liga o serviço que mantém o Ultron atendendo no Telegram.
"""
import getpass
import re
import subprocess
import sys
import time

import requests

from core.config import RAIZ, definir

ENV = RAIZ / ".env"
API = "https://api.telegram.org/bot{}/{}"


def api(token, metodo, **json):
    r = requests.post(API.format(token, metodo), json=json, timeout=40).json()
    if not r.get("ok"):
        raise RuntimeError(r.get("description", "erro desconhecido"))
    return r["result"]


def gravar_token(token):
    texto = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    if re.search(r"^TELEGRAM_TOKEN=.*$", texto, flags=re.M):
        texto = re.sub(r"^TELEGRAM_TOKEN=.*$", f"TELEGRAM_TOKEN={token}", texto, flags=re.M)
    else:
        texto += f"\nTELEGRAM_TOKEN={token}\n"
    ENV.write_text(texto, encoding="utf-8")
    ENV.chmod(0o600)


def main():
    print("== Configurando o Ultron no Telegram ==\n")
    subprocess.run(["systemctl", "--user", "stop", "ultron-telegram"], stderr=subprocess.DEVNULL)

    while True:
        token = getpass.getpass("Cole o token do @BotFather (não aparece na tela): ").strip()
        try:
            bot = api(token, "getMe")
            break
        except Exception as e:
            print(f"  Token recusado ({e}). Tente de novo.\n")
    print(f"  ✓ Bot @{bot['username']} encontrado.")
    gravar_token(token)

    api(token, "deleteWebhook", drop_pending_updates=True)
    print(f"\nAgora abra https://t.me/{bot['username']} no celular e mande qualquer mensagem.")
    print("Aguardando...", flush=True)
    offset, limite = None, time.time() + 300
    while time.time() < limite:
        params = {"timeout": 25, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset
        for u in api(token, "getUpdates", **params):
            offset = u["update_id"] + 1
            msg = u.get("message")
            if not msg:
                continue
            quem = msg["from"]
            nome = quem.get("first_name", "") + (f" (@{quem['username']})" if quem.get("username") else "")
            resp = input(f"\n  Mensagem de {nome}, ID {quem['id']}. É você? [s/n] ").strip().lower()
            if resp.startswith("s"):
                definir("telegram.dono_id", quem["id"])
                api(token, "getUpdates", offset=offset, timeout=0)  # descarta o que já foi lido
                api(token, "sendMessage", chat_id=quem["id"],
                    text="Configuração concluída. Eu sou o Ultron, e agora só respondo a você.")
                print(f"  ✓ Dono definido: {quem['id']}")
                break
        else:
            continue
        break
    else:
        print("Tempo esgotado sem mensagem. Rode de novo.")
        sys.exit(1)

    print("\nLigando o serviço (atende mesmo com o terminal fechado)...")
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    r = subprocess.run(["systemctl", "--user", "enable", "--now", "ultron-telegram"])
    if r.returncode == 0:
        print("  ✓ Serviço ultron-telegram ativo.")
    subprocess.run(["loginctl", "enable-linger"], stderr=subprocess.DEVNULL)
    print("\nPronto! Mande no Telegram, por exemplo: 'quem está na minha rede?'")
    print("Logs: journalctl --user -u ultron-telegram -f")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
