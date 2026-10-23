import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.api import auth
from app.main import app
from app.security import hash_password, token_digest

OLD_PASSWORD = "ancien-mot-de-passe"
NEW_PASSWORD = "nouveau-mot-de-passe"
EMAIL = "alice@example.fr"
SENT = "Si un compte existe pour cette adresse, un e-mail vient d'être envoyé. Le lien est valable 30 minutes."
pytestmark = pytest.mark.usefixtures("api_db")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user(session) -> models.User:
    user = models.User(email=EMAIL, password_hash=hash_password(OLD_PASSWORD), email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    return user


def ask(client, email=EMAIL):
    return client.post("/auth/password-reset/request", json={"email": email})


def confirm(client, token, password=NEW_PASSWORD):
    return client.post("/auth/password-reset/confirm", json={"token": token, "password": password})


def token_from(mail: dict) -> str:
    return re.search(r"#reset=([\w-]+)", mail["body"]).group(1)


def login(client, password):
    return client.post("/auth/login", json={"email": EMAIL, "password": password})


# --- Demande ---


def test_demande_envoie_un_lien(client, user, outbox):
    response = ask(client)

    assert response.status_code == 202
    assert response.json() == {"detail": SENT}
    [mail] = outbox
    assert mail["to"] == EMAIL
    assert mail["subject"] == "StationAlerte : réinitialisation de votre mot de passe"
    # Le jeton est après « # » : jamais envoyé aux serveurs, ni aux autres sites (Referer).
    assert "http://localhost:5173/#reset=" in mail["body"]


def test_compte_inconnu_meme_reponse_et_aucun_email(client, outbox):
    response = ask(client, email="inconnu@example.fr")

    assert response.status_code == 202
    assert response.json() == {"detail": SENT}
    assert outbox == []


def test_seule_l_empreinte_du_jeton_est_stockee(client, user, outbox, session):
    ask(client)
    token = token_from(outbox[0])
    [stored] = session.scalars(select(models.PasswordResetToken).where(models.PasswordResetToken.user_id == user.id)).all()

    assert stored.token_hash == token_digest(token)
    assert token not in stored.token_hash


def test_nouvelle_demande_annule_l_ancien_lien(client, user, outbox):
    ask(client)
    ask(client)
    first, second = (token_from(mail) for mail in outbox)

    assert confirm(client, first).status_code == 400
    assert confirm(client, second).status_code == 204


def test_serveur_d_emails_en_panne_meme_reponse(client, user, monkeypatch):
    def broken(*args):
        raise ConnectionRefusedError("Mailpit arrêté")

    monkeypatch.setattr(auth, "send_email", broken)
    response = ask(client)
    assert response.status_code == 202  # l'erreur est notée dans le journal du serveur, rien n'est révélé
    assert response.json() == {"detail": SENT}


def test_limite_de_demandes_par_email(client, user, outbox):
    for _ in range(3):
        assert ask(client).status_code == 202
    response = ask(client)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"
    assert len(outbox) == 3  # personne ne peut inonder une boîte e-mail de liens


def test_limite_de_demandes_par_adresse_ip(client, outbox):
    for i in range(5):
        assert ask(client, email=f"n{i}@example.fr").status_code == 202
    assert ask(client, email="n5@example.fr").status_code == 429


# --- Nouveau mot de passe ---


def test_nouveau_mot_de_passe(client, user, outbox):
    ask(client)
    response = confirm(client, token_from(outbox[0]))

    assert response.status_code == 204
    assert login(client, OLD_PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200


def test_lien_utilisable_une_seule_fois(client, user, outbox):
    ask(client)
    token = token_from(outbox[0])
    confirm(client, token)

    response = confirm(client, token, password="encore-un-autre-mot")
    assert response.status_code == 400
    assert response.json() == {"detail": "Lien invalide ou expiré. Faites une nouvelle demande."}


def test_lien_expire_apres_30_minutes(client, user, outbox, session):
    ask(client)
    stored = session.scalars(select(models.PasswordResetToken).where(models.PasswordResetToken.user_id == user.id)).one()
    stored.created_at = datetime.now(UTC) - timedelta(minutes=31)
    session.flush()

    assert confirm(client, token_from(outbox[0])).status_code == 400
    assert session.scalars(select(models.PasswordResetToken).where(models.PasswordResetToken.user_id == user.id)).all() == []  # supprimé au passage


@pytest.mark.parametrize("token", ["faux-jeton", "x" * 100, "a\x00b"])
def test_jeton_invente_refuse(client, user, token):
    assert confirm(client, token).status_code in (400, 422)


@pytest.mark.parametrize(("password", "status"), [("x" * 11, 422), ("x" * 129, 422), ("x" * 12, 204)])
def test_memes_regles_qu_a_l_inscription(client, user, outbox, password, status):
    ask(client)
    assert confirm(client, token_from(outbox[0]), password=password).status_code == status


def test_toutes_les_sessions_sont_coupees(client, user, outbox, session):
    other_device = TestClient(app)
    assert login(other_device, OLD_PASSWORD).status_code == 200
    ask(client)
    confirm(client, token_from(outbox[0]))

    assert other_device.get("/me").status_code == 401
    assert session.scalars(select(models.UserSession).where(models.UserSession.user_id == user.id)).all() == []


def test_la_reinitialisation_ne_connecte_pas(client, user, outbox):
    # Recommandation OWASP : on se reconnecte avec le nouveau mot de passe.
    ask(client)
    response = confirm(client, token_from(outbox[0]))
    assert "set-cookie" not in response.headers


def test_le_mot_de_passe_n_apparait_jamais(client, user, outbox):
    ask(client)
    response = confirm(client, token_from(outbox[0]), password="court")
    assert "court" not in response.text


def test_requete_d_un_autre_site_refusee(client, user):
    response = client.post(
        "/auth/password-reset/request", json={"email": EMAIL}, headers={"Origin": "https://site-pirate.example"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("email", [EMAIL, "inconnu@example.fr"])
def test_meme_travail_avant_la_reponse_compte_ou_pas(client, user, monkeypatch, email):
    # Le lien est créé APRÈS la réponse dans les deux cas : le temps de réponse ne révèle pas qui est inscrit.
    scheduled = []
    monkeypatch.setattr(auth, "create_and_send_reset_link", lambda e: scheduled.append(e))
    ask(client, email=email)
    assert scheduled == [email]
