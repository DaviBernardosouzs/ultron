"""E-mail próprio do Ultron (IMAP/SMTP) e mensagens para o celular do dono.

Configure email.endereco no config.yaml e EMAIL_SENHA no .env. No Gmail, use
uma "senha de app" (Conta Google > Segurança > Verificação em duas etapas >
Senhas de app), nunca a senha normal.
"""
import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from core.config import ajuste, segredo
from core.registro import NAO_CONFIAVEL, ferramenta


def _conta():
    end, senha = ajuste("email.endereco"), segredo("EMAIL_SENHA")
    if not end or not senha:
        raise RuntimeError("E-mail do Ultron não configurado (email.endereco e EMAIL_SENHA).")
    return end, senha


def _cabecalho(v):
    return str(make_header(decode_header(v or "")))


def _corpo(msg):
    partes = msg.walk() if msg.is_multipart() else [msg]
    for p in partes:
        if p.get_content_type() == "text/plain" and not p.get_filename():
            dados = p.get_payload(decode=True) or b""
            return dados.decode(p.get_content_charset() or "utf-8", errors="replace")
    return "(sem texto simples)"


def _enviar(para, assunto, corpo):
    end, senha = _conta()
    m = EmailMessage()
    m["From"] = f"Ultron <{end}>"
    m["To"] = para
    m["Subject"] = assunto
    m.set_content(corpo)
    with smtplib.SMTP_SSL(ajuste("email.smtp", "smtp.gmail.com"), 465, timeout=30) as s:
        s.login(end, senha)
        s.send_message(m)


@ferramenta(
    "ler_emails",
    "Lê os e-mails mais recentes da caixa de entrada do Ultron (o e-mail próprio dele).",
    {"type": "object", "properties": {
        "quantidade": {"type": "integer", "default": 5, "maximum": 20},
        "apenas_nao_lidos": {"type": "boolean", "default": True}}})
def ler_emails(quantidade=5, apenas_nao_lidos=True):
    end, senha = _conta()
    with imaplib.IMAP4_SSL(ajuste("email.imap", "imap.gmail.com"), timeout=30) as im:
        im.login(end, senha)
        im.select("INBOX")
        _, ids = im.search(None, "UNSEEN" if apenas_nao_lidos else "ALL")
        ids = ids[0].split()[-quantidade:]
        if not ids:
            return "Nenhum e-mail" + (" não lido." if apenas_nao_lidos else ".")
        saidas = []
        for i in reversed(ids):
            _, dados = im.fetch(i, "(RFC822)")
            m = email.message_from_bytes(dados[0][1])
            saidas.append(f"De: {_cabecalho(m['From'])}\nAssunto: {_cabecalho(m['Subject'])}\n"
                          f"Data: {m['Date']}\n{_corpo(m)[:1500]}")
    return NAO_CONFIAVEL + "\n\n---\n\n".join(saidas)


@ferramenta(
    "enviar_email",
    "Envia um e-mail a partir do endereço do Ultron para outra pessoa.",
    {"type": "object", "properties": {
        "para": {"type": "string"}, "assunto": {"type": "string"}, "corpo": {"type": "string"}},
     "required": ["para", "assunto", "corpo"]},
    nivel="N3",
    resumo=lambda a: f"enviar e-mail para {a.get('para')} com assunto \"{a.get('assunto')}\"")
def enviar_email(para, assunto, corpo):
    if "@" not in parseaddr(para)[1]:
        return "Endereço inválido."
    _enviar(para, assunto, corpo)
    return f"E-mail enviado para {para}."


@ferramenta(
    "me_enviar_email",
    "Envia um e-mail para o próprio usuário (relatórios, listas, lembretes longos).",
    {"type": "object", "properties": {
        "assunto": {"type": "string"}, "corpo": {"type": "string"}}, "required": ["assunto", "corpo"]})
def me_enviar_email(assunto, corpo):
    destino = ajuste("usuario.email")
    if not destino:
        return "Configure usuario.email no config.yaml."
    _enviar(destino, assunto, corpo)
    return "Mandei para o seu e-mail."


@ferramenta(
    "mandar_mensagem_celular",
    "Manda uma mensagem no Telegram para o celular do usuário (avisos, resultados).",
    {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]})
def mandar_mensagem_celular(texto):
    from core.telegram import Telegram
    t = Telegram()
    if not t.dono:
        return "Telegram sem dono configurado."
    t.enviar(texto)
    return "Mensagem enviada."
