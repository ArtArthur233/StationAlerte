# Envoi d'e-mails par SMTP. En local, Mailpit (docker-compose.yml) capture tout : rien ne part sur internet,
# les e-mails se lisent sur http://localhost:8025 (mode test : aucun e-mail ne sort du PC).
import smtplib
from email import policy
from email.message import EmailMessage

from app.config import MAIL_FROM, SMTP_HOST, SMTP_PORT


class MailServerDown(OSError):
    """Serveur d'e-mails injoignable : aucun e-mail ne peut partir pour l'instant, quel que soit le destinataire.
    Toute autre erreur ne concerne que ce message (adresse refusée, accents non acceptés…)."""


def send_email(to: str, subject: str, body: str, headers: dict[str, str] | None = None) -> None:
    # Refuse les retours à la ligne dans les en-têtes : pas d'injection d'en-tête. Lignes de 998 caractères
    # (limite de la norme) au lieu de 78 : sinon un lien long dans List-Unsubscribe, impossible à plier, était
    # encodé (=?utf-8?q?…) et les messageries ne le reconnaissaient plus (trouvé à l'essai réel, V7.4).
    message = EmailMessage(policy=policy.default.clone(max_line_length=998))
    message["From"] = MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(body)
    # Sans erreur ici, le serveur a ACCEPTÉ le message : c'est la seule confirmation d'envoi qui compte.
    # Un destinataire refusé lève SMTPRecipientsRefused ; serveur injoignable ou en panne : une autre OSError.
    try:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    except OSError as error:
        raise MailServerDown(f"{type(error).__name__}: {error}") from error
    # Mailpit seulement (décision de l'utilisateur, 18/10/2026) : ni chiffrement ni identifiants, rien ne sort du PC.
    with smtp:
        if refused := smtp.send_message(message):
            raise smtplib.SMTPRecipientsRefused(refused)
