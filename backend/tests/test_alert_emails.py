# Envoi des alertes par e-mail (V7.1). Le serveur d'e-mails est remplacé par une fausse fonction qui note
# ce qu'on lui envoie (ou qui échoue) : pas besoin de Mailpit pour ces tests.
import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import alert_emails, models
from app.alert_emails import send_pending_alerts
from app.integrations.mailer import MailServerDown
from app.security import hash_password

NOW = datetime(2026, 10, 17, 11, 5, tzinfo=UTC)  # 13 h 05 à Paris


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_emails, "send_email", lambda to, subject, body, headers: sent.append((to, subject, body, headers)))
    return sent


@pytest.fixture
def station(session):
    station = models.Station(id="TEST-MAIL", name="stationTest", address="Station fictive de test",
                             postal_code="42000", city="Saint-Étienne", search_text="stationtest")
    session.add(station)
    session.flush()
    return station


def user(session, email: str) -> models.User:
    account = models.User(email=email, password_hash=hash_password("x" * 12), email_verified_at=datetime.now(UTC),
                          notify_unavailable=True, notify_available=True)
    session.add(account)
    session.flush()
    return account


def alert(session, account, station_id="TEST-MAIL", fuel="GAZOLE", old="AVAILABLE", new="UNAVAILABLE",
          label=None, age=timedelta(minutes=1)) -> models.Alert:
    # Le compte surveille ce carburant : sinon l'alerte serait supprimée avant l'envoi (V7.5).
    session.merge(models.Favorite(user_id=account.id, station_id=station_id))
    session.merge(models.FavoriteFuel(user_id=account.id, station_id=station_id, fuel_type=fuel))
    session.flush()
    event = models.AvailabilityEvent(station_id=station_id, fuel_type=fuel, label=label, old_status=old,
                                     new_status=new, source_updated_at=NOW)
    session.add(event)
    session.flush()
    row = models.Alert(user_id=account.id, event_id=event.id, created_at=datetime.now(UTC) - age)
    session.add(row)
    session.flush()
    return row


def only_our_alerts(session):
    # La base de développement peut contenir de vraies alertes en attente : on les met de côté dans la transaction.
    session.execute(models.Alert.__table__.update().where(models.Alert.status == "pending").values(status="sent"))


# --- Contenu ---


def test_une_rupture_un_e_mail(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    row = alert(session, alice)

    assert send_pending_alerts(session) == (1, 0, 0)
    [(to, subject, body, headers)] = outbox
    assert to == "alice@test.fr"
    assert subject == "StationAlerte : Gazole indisponible à stationTest"
    assert "• stationTest — Station fictive de test, 42000 Saint-Étienne" in body
    assert "Gazole : Déclaré disponible → Indisponible (déclaré le 17/10 à 13:05)" in body  # heure de Paris
    assert "vérifiez avant de vous déplacer" in body
    # Désabonnement (V7.4) : lien personnel dans le texte et dans l'en-tête standard List-Unsubscribe.
    link = body.split("Ne plus recevoir d'alertes : ")[1].strip()
    assert link.startswith("http://localhost:5173/#unsubscribe=")
    assert headers == {"List-Unsubscribe": f"<{link}>"}
    assert (row.status, row.attempts) == ("sent", 0) and row.sent_at is not None


def test_retour_a_la_disponibilite(session, station, outbox):
    only_our_alerts(session)
    alert(session, user(session, "alice@test.fr"), old="UNAVAILABLE", new="AVAILABLE")
    send_pending_alerts(session)
    assert outbox[0][1] == "StationAlerte : Gazole de nouveau disponible à stationTest"


def test_un_seul_e_mail_par_compte_et_par_passage(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    alert(session, alice, fuel="GAZOLE")
    alert(session, alice, fuel="AUTRE", label="B100", old="UNAVAILABLE", new="AVAILABLE")

    assert send_pending_alerts(session).sent == 1
    [(_, subject, body, _)] = outbox
    assert subject == "StationAlerte : 2 changements dans vos stations"
    assert body.count("• stationTest") == 1  # une seule fois la station, ses deux carburants dessous
    assert "Autre carburant (B100) : Indisponible → Déclaré disponible" in body


def test_chaque_compte_recoit_le_sien(session, station, outbox):
    only_our_alerts(session)
    alert(session, user(session, "alice@test.fr"))
    alert(session, user(session, "camille@test.fr"))
    assert send_pending_alerts(session).sent == 2
    assert sorted(mail[0] for mail in outbox) == ["alice@test.fr", "camille@test.fr"]


def test_deja_envoyee_pas_renvoyee(session, station, outbox):
    only_our_alerts(session)
    alert(session, user(session, "alice@test.fr"))
    send_pending_alerts(session)
    assert send_pending_alerts(session) == (0, 0, 0)
    assert len(outbox) == 1


def test_nom_avec_retour_a_la_ligne(session, outbox):
    # Un nom piégé dans le flux ne doit ni casser l'envoi, ni ajouter un en-tête à l'e-mail.
    only_our_alerts(session)
    session.add(models.Station(id="TEST-PIEGE", name="Piège\r\nBcc: pirate@x.fr", address="1 rue\nTest",
                               postal_code="42000", city="Saint-Étienne", search_text="piege"))
    session.flush()
    alert(session, user(session, "alice@test.fr"), station_id="TEST-PIEGE")
    send_pending_alerts(session)
    assert outbox[0][1] == "StationAlerte : Gazole indisponible à Piège Bcc: pirate@x.fr"
    assert "\n" not in outbox[0][1]


# --- Pas d'envoi d'une information périmée ---


def test_alerte_de_plus_de_2_h_non_envoyee(session, station, outbox):
    only_our_alerts(session)
    row = alert(session, user(session, "alice@test.fr"), age=timedelta(hours=2, minutes=1))
    assert send_pending_alerts(session) == (0, 0, 1)
    assert outbox == [] and row.status == "expired"


# --- Échecs ---


def failing(monkeypatch, error: Exception, only_for: str | None = None):
    sent = []

    def send(to, subject, body, headers):
        if only_for is None or to == only_for:
            raise error
        sent.append(to)

    monkeypatch.setattr(alert_emails, "send_email", send)
    return sent


def test_serveur_injoignable_nouvel_essai_puis_echec(session, station, monkeypatch):
    only_our_alerts(session)
    failing(monkeypatch, MailServerDown("ConnectionRefusedError: Mailpit arrêté"))
    row = alert(session, user(session, "alice@test.fr"))

    for attempt in range(1, alert_emails.MAX_ATTEMPTS):
        assert send_pending_alerts(session) == (0, 1, 0)
        assert (row.status, row.attempts) == ("pending", attempt)  # réessayée au passage suivant
    send_pending_alerts(session)
    assert (row.status, row.attempts) == ("failed", 5)
    assert row.last_error == "MailServerDown: ConnectionRefusedError: Mailpit arrêté" and row.sent_at is None


def test_serveur_injoignable_on_n_insiste_pas(session, station, monkeypatch):
    only_our_alerts(session)
    failing(monkeypatch, MailServerDown("ConnectionRefusedError: Mailpit arrêté"))
    first = alert(session, user(session, "alice@test.fr"))
    second = alert(session, user(session, "camille@test.fr"))
    assert send_pending_alerts(session) == (0, 1, 0)  # arrêt après le premier échec, pas 2 délais de 10 s
    assert (first.attempts, second.attempts) == (1, 0)


def test_destinataire_refuse_les_autres_recoivent_quand_meme(session, station, monkeypatch):
    only_our_alerts(session)
    refused = smtplib.SMTPRecipientsRefused({"alice@test.fr": (550, b"Mailbox unavailable")})
    sent = failing(monkeypatch, refused, only_for="alice@test.fr")
    alice_alert = alert(session, user(session, "alice@test.fr"))
    alert(session, user(session, "camille@test.fr"))

    assert send_pending_alerts(session) == (1, 1, 0)
    assert sent == ["camille@test.fr"]
    assert alice_alert.status == "pending" and "SMTPRecipientsRefused" in alice_alert.last_error


@pytest.mark.parametrize("error", [
    smtplib.SMTPNotSupportedError("SMTPUTF8 not supported by server"),  # adresse à accents, fournisseur sans SMTPUTF8
    UnicodeEncodeError("ascii", "é", 0, 1, "ordinal not in range"),
    smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),  # coupure pendant CE message
])
def test_erreur_propre_a_un_compte_n_arrete_pas_les_autres(session, station, monkeypatch, error):
    only_our_alerts(session)
    sent = failing(monkeypatch, error, only_for="élodie@test.fr")
    alert(session, user(session, "élodie@test.fr"))
    alert(session, user(session, "camille@test.fr"))
    assert send_pending_alerts(session) == (1, 1, 0)
    assert sent == ["camille@test.fr"]


# --- Désabonné ou plus surveillé entre la création et l'envoi (V7.5) ---


def test_desabonne_avant_l_envoi_rien_n_est_envoye(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    alert_id = alert(session, alice).id
    alice.notify_unavailable = False  # lien « Ne plus recevoir d'alertes » cliqué entre-temps
    session.flush()
    assert send_pending_alerts(session) == (0, 0, 0) and outbox == []
    assert session.get(models.Alert, alert_id) is None  # supprimée : elle ne sera jamais envoyée


def test_carburant_plus_surveille_avant_l_envoi(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    alert(session, alice, fuel="GAZOLE")
    alert(session, alice, fuel="E10")
    session.delete(session.get(models.FavoriteFuel, (alice.id, "TEST-MAIL", "GAZOLE")))
    session.flush()
    assert send_pending_alerts(session) == (1, 0, 0)
    assert "E10" in outbox[0][1] and "Gazole" not in outbox[0][2]


def test_retour_a_la_disponibilite_plus_demande(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    alert(session, alice, old="UNAVAILABLE", new="AVAILABLE")
    alice.notify_available = False
    session.flush()
    assert send_pending_alerts(session) == (0, 0, 0) and outbox == []


def test_seule_une_vraie_acceptation_compte_comme_envoyee(session, station, monkeypatch):
    # Le serveur accepte la connexion mais refuse le message : l'alerte n'est PAS marquée envoyée.
    only_our_alerts(session)
    failing(monkeypatch, smtplib.SMTPDataError(554, b"Message refused"))
    row = alert(session, user(session, "alice@test.fr"))
    send_pending_alerts(session)
    assert row.status == "pending" and row.sent_at is None


def test_compte_supprime_pendant_l_attente(session, station, outbox):
    only_our_alerts(session)
    alice = user(session, "alice@test.fr")
    alert(session, alice)
    session.delete(alice)  # ses alertes partent avec lui (ON DELETE CASCADE)
    session.flush()
    assert send_pending_alerts(session) == (0, 0, 0) and outbox == []
    assert session.scalars(select(models.Alert).where(models.Alert.user_id == alice.id)).all() == []
