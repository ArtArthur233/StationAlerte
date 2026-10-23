# Envoi SMTP vers Mailpit (integrations/mailer.py) avec un faux serveur : confirmation, en-têtes, pannes.
import smtplib

import pytest

from app.integrations import mailer


class FakeSMTP:
    calls: list = []
    refused: dict = {}

    def __init__(self, host, port, timeout):
        FakeSMTP.calls = [("connect", host, port)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send_message(self, message):
        FakeSMTP.calls.append(("send", message["To"]))
        FakeSMTP.last = message
        return FakeSMTP.refused


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.refused = {}
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)


def test_mailpit_sans_chiffrement_ni_identifiants():
    mailer.send_email("a@test.fr", "Objet", "Texte")
    assert [call[0] for call in FakeSMTP.calls] == ["connect", "send"]


def test_destinataire_refuse_leve_une_erreur():
    FakeSMTP.refused = {"a@test.fr": (550, b"Mailbox unavailable")}
    with pytest.raises(smtplib.SMTPRecipientsRefused):  # jamais compté comme « envoyé »
        mailer.send_email("a@test.fr", "Objet", "Texte")


def test_en_tetes_supplementaires_transmis():
    mailer.send_email("a@test.fr", "Objet", "Texte", headers={"List-Unsubscribe": "<http://localhost:5173/#unsubscribe=x>"})
    assert FakeSMTP.last["List-Unsubscribe"] == "<http://localhost:5173/#unsubscribe=x>"


def test_lien_long_de_list_unsubscribe_pas_encode():
    link = "<http://localhost:5173/#unsubscribe=" + "x" * 43 + ">"
    mailer.send_email("a@test.fr", "Objet", "Texte", headers={"List-Unsubscribe": link})
    assert f"List-Unsubscribe: {link}" in FakeSMTP.last.as_string()  # lisible par les messageries


def test_retour_a_la_ligne_dans_un_en_tete_refuse():
    with pytest.raises(ValueError):  # injection d'en-tête impossible (Bcc caché…)
        mailer.send_email("a@test.fr", "Objet" + chr(13) + chr(10) + "Bcc: pirate@x.fr", "Texte")


def test_serveur_injoignable_signale_comme_tel(monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError("Mailpit arrêté")

    monkeypatch.setattr(mailer.smtplib, "SMTP", refuse)
    with pytest.raises(mailer.MailServerDown):  # l'envoi des alertes s'arrête pour ce passage
        mailer.send_email("a@test.fr", "Objet", "Texte")


def test_message_refuse_n_est_pas_une_panne_du_serveur():
    FakeSMTP.refused = {"a@test.fr": (550, b"Mailbox unavailable")}
    with pytest.raises(smtplib.SMTPRecipientsRefused) as error:
        mailer.send_email("a@test.fr", "Objet", "Texte")
    assert not isinstance(error.value, mailer.MailServerDown)  # les autres comptes recevront le leur
