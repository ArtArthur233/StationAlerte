# Suppression du compte et désabonnement depuis l'e-mail (V7.4).
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import app
from app.security import new_token

PASSWORD = "correct-horse-battery"  # celui de logged_in_client (conftest.py)
pytestmark = pytest.mark.usefixtures("api_db")


def user_of(session, client) -> models.User:
    return session.get(models.User, client.get("/me").json()["id"])


def delete_account(client, password=PASSWORD, **kwargs):
    return client.request("DELETE", "/me", json={"password": password}, **kwargs)


# --- Supprimer son compte ---


def test_suppression_du_compte_et_de_tout_ce_qui_lui_appartient(alice, camille, session, outbox):
    station = models.Station(id="TEST-SUPPR", name="Station", address="1 rue", postal_code="42000",
                             city="Saint-Étienne", search_text="station")
    session.add(station)
    session.flush()
    for client in (alice, camille):
        client.put("/me/favorites/TEST-SUPPR")
    alice_id = user_of(session, alice).id

    response = delete_account(alice)

    assert response.status_code == 204
    assert 'session=""' in response.headers["set-cookie"]  # cookie effacé
    session.expire_all()
    assert session.get(models.User, alice_id) is None
    for table in (models.Favorite, models.UserSession):
        assert session.scalars(select(table).where(table.user_id == alice_id)).all() == []
    assert alice.get("/me").status_code == 401  # même avec une copie de l'ancien cookie
    assert [s["id"] for s in camille.get("/me/favorites").json()] == ["TEST-SUPPR"]  # les autres comptes : intacts
    assert outbox[-1]["subject"] == "StationAlerte : votre compte a été supprimé"


def test_mauvais_mot_de_passe_rien_n_est_supprime(alice, session):
    response = delete_account(alice, password="pas-le-bon")
    assert response.status_code == 403
    assert response.json() == {"detail": "Mot de passe incorrect : le compte n'a pas été supprimé."}
    assert alice.get("/me").status_code == 200


def test_essais_limites_comme_la_connexion(alice):
    # Une session volée ne permet pas de deviner le mot de passe par cette route.
    for _ in range(5):
        assert delete_account(alice, password="pas-le-bon").status_code == 403
    response = delete_account(alice)  # même le bon mot de passe est refusé pendant 15 min
    assert response.status_code == 429
    assert alice.get("/me").status_code == 200


def test_connexion_requise():
    assert delete_account(TestClient(app)).status_code == 401


def test_depuis_un_autre_site_refuse(alice):
    assert delete_account(alice, headers={"Origin": "https://site-pirate.example"}).status_code == 403
    assert alice.get("/me").status_code == 200


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": "x" * 129}])
def test_corps_invalide(alice, body):
    assert alice.request("DELETE", "/me", json=body).status_code == 422


# --- Se désabonner depuis l'e-mail ---


def unsubscribe_link(session, user: models.User, age=timedelta(0)) -> str:
    token, digest = new_token()
    session.add(models.UnsubscribeToken(token_hash=digest, user_id=user.id, created_at=datetime.now(UTC) - age))
    session.flush()
    return token


def test_desabonnement_coupe_les_alertes_sans_connexion(alice, camille, session):
    alice.put("/me/notifications", json={"notifyUnavailable": True, "notifyAvailable": True})
    token = unsubscribe_link(session, user_of(session, alice))

    response = TestClient(app).post("/auth/unsubscribe", json={"token": token})  # navigateur sans session

    assert response.status_code == 200 and "vous ne recevrez plus d'alertes" in response.json()["detail"]
    assert alice.get("/me").json()["notifyUnavailable"] is False
    assert alice.get("/me").json()["notifyAvailable"] is False
    assert camille.get("/me").json()["notifyUnavailable"] is True  # seul le compte du lien est concerné
    assert TestClient(app).post("/auth/unsubscribe", json={"token": token}).status_code == 200  # deux fois : pas une erreur


def test_lien_de_desabonnement_expire_apres_60_jours(alice, session):
    token = unsubscribe_link(session, user_of(session, alice), age=timedelta(days=61))
    response = TestClient(app).post("/auth/unsubscribe", json={"token": token})
    assert response.status_code == 400
    assert alice.get("/me").json()["notifyUnavailable"] is True


@pytest.mark.parametrize("token", ["invente", "x" * 100])
def test_lien_invente_refuse(token):
    assert TestClient(app).post("/auth/unsubscribe", json={"token": token}).json() == {
        "detail": "Lien de désabonnement invalide ou expiré."
    }


def test_compte_supprime_son_lien_ne_marche_plus(alice, session):
    token = unsubscribe_link(session, user_of(session, alice))
    delete_account(alice)
    assert TestClient(app).post("/auth/unsubscribe", json={"token": token}).status_code == 400
