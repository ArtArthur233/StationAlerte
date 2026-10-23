# Préférences de notification du compte connecté (V5.4). Les e-mails eux-mêmes arrivent en V7.
import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.usefixtures("api_db")

BOTH = {"notifyUnavailable": True, "notifyAvailable": True}


def test_valeurs_par_defaut(alice):
    # Règle du projet : alerte de rupture par défaut, retour à la disponibilité en option.
    user = alice.get("/me").json()
    assert (user["notifyUnavailable"], user["notifyAvailable"]) == (True, False)


def test_changer_ses_preferences(alice):
    response = alice.put("/me/notifications", json={"notifyUnavailable": False, "notifyAvailable": True})
    assert response.status_code == 200
    assert response.json()["notifyAvailable"] is True  # le compte à jour est renvoyé
    assert alice.get("/me").json()["notifyUnavailable"] is False  # et bien enregistré


def test_connexion_requise():
    response = TestClient(app).put("/me/notifications", json=BOTH)
    assert response.status_code == 401


def test_chacun_ses_preferences(alice, camille):
    alice.put("/me/notifications", json=BOTH)
    assert camille.get("/me").json()["notifyAvailable"] is False


@pytest.mark.parametrize("body", [{"notifyUnavailable": True}, {"notifyUnavailable": "peut-être", "notifyAvailable": True}])
def test_preferences_invalides(alice, body):
    assert alice.put("/me/notifications", json=body).status_code == 422


def test_depuis_un_autre_site_refuse(alice):
    response = alice.put("/me/notifications", json=BOTH, headers={"Origin": "https://site-pirate.example"})
    assert response.status_code == 403
    assert alice.get("/me").json()["notifyAvailable"] is False
