from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import alerts, config, models, test_station
from app.api import demo
from app.main import app

pytestmark = pytest.mark.usefixtures("api_db")
ID = test_station.TEST_STATION_ID
client = TestClient(app)


@pytest.fixture(autouse=True)
def demo_mode(session, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(test_station, "TEST_STATION_PATH", tmp_path / "test_station.json")  # jamais le vrai fichier
    # Départ sans stationTest (la base de dev peut en avoir une) : supprimée dans la transaction de test, annulée à la fin.
    session.execute(delete(models.Station).where(models.Station.id == ID))
    # Surveillant « en marche » : un import récent.
    session.add(models.FeedImport(station_count=1, imported_at=datetime.now(UTC)))
    session.flush()


@pytest.fixture
def sent(monkeypatch) -> list[int]:
    calls = []
    monkeypatch.setattr(demo, "send_now", lambda db: calls.append(1) or SimpleNamespace(sent=1))
    return calls


def change(fuel: str, status: str, **headers):
    return client.put(f"/demo/test-station/fuels/{fuel}", json={"status": status}, headers=headers)


def watcher(session) -> models.User:
    user = models.User(email="demo-api@test.fr", password_hash="x", email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    session.add(models.Favorite(user_id=user.id, station_id=ID))
    session.flush()
    session.add(models.FavoriteFuel(user_id=user.id, station_id=ID, fuel_type="GAZOLE"))
    session.flush()
    return user


def test_routes_absentes_sans_mode_demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/demo/test-station").status_code == 404
    assert change("GAZOLE", "AVAILABLE").status_code == 404


def test_station_pas_encore_creee():
    response = client.get("/demo/test-station")
    assert response.status_code == 200
    assert response.json() is None


def test_premier_changement_cree_la_station_sans_evenement(session, sent):
    response = change("GAZOLE", "AVAILABLE")

    assert response.status_code == 200
    body = response.json()
    assert body["events"] == 0 and body["alerts"] == 0 and sent == []
    assert body["station"]["address"] == "Station fictive de test"  # impossible de la prendre pour une vraie
    assert [(f["type"], f["status"]) for f in body["station"]["fuels"]] == [("GAZOLE", "AVAILABLE")]
    assert client.get("/demo/test-station").json()["fuels"][0]["status"] == "AVAILABLE"


def test_rupture_surveillee_cree_une_alerte_et_envoie_l_e_mail(session, sent):
    change("GAZOLE", "AVAILABLE")
    user = watcher(session)

    body = change("GAZOLE", "UNAVAILABLE").json()

    assert (body["events"], body["alerts"], body["emailsSent"], body["alertsAllowed"]) == (1, 1, 1, True)
    assert sent == [1]
    alert = session.scalar(select(models.Alert).where(models.Alert.user_id == user.id))
    event = session.get(models.AvailabilityEvent, alert.event_id)
    assert (event.station_id, event.old_status, event.new_status) == (ID, "AVAILABLE", "UNAVAILABLE")


def test_surveillant_arrete_changement_enregistre_sans_alerte(session, sent, monkeypatch):
    change("GAZOLE", "AVAILABLE")
    watcher(session)
    monkeypatch.setattr(alerts, "monitoring_was_running", lambda db: False)

    body = change("GAZOLE", "UNAVAILABLE").json()

    assert (body["events"], body["alerts"], body["alertsAllowed"]) == (1, 0, False)
    assert sent == []


def test_inconnu_n_alerte_jamais(session, sent):
    change("GAZOLE", "UNAVAILABLE")
    watcher(session)

    body = change("GAZOLE", "UNKNOWN").json()

    assert (body["events"], body["alerts"]) == (1, 0)
    assert body["station"]["fuels"][0]["updatedAt"] is None  # sans date, comme l'exige la règle des trois états


def test_non_vendu_retire_le_carburant_sans_evenement(sent):
    change("GAZOLE", "AVAILABLE")
    change("E10", "AVAILABLE")

    body = change("GAZOLE", "NOT_SOLD").json()

    assert body["events"] == 0
    assert [f["type"] for f in body["station"]["fuels"]] == ["E10"]


def test_fichier_ecrit_pour_que_le_surveillant_garde_le_meme_etat(sent):
    change("GAZOLE", "UNAVAILABLE")

    [station] = test_station.load()  # ce que le prochain import du surveillant ajoutera au flux
    assert station.id == ID
    assert [(f.type, f.status) for f in station.fuels] == [("GAZOLE", "UNAVAILABLE")]


@pytest.mark.parametrize("fuel, status", [("AUTRE", "AVAILABLE"), ("FIOUL", "AVAILABLE"), ("GAZOLE", "RUPTURE"),
                                          ("GAZOLE", ""), ("GAZOLE", None)])
def test_valeurs_invalides_refusees(fuel, status):
    assert change(fuel, status).status_code == 422


def test_aucune_route_ne_vise_une_autre_station():
    # La station n'est jamais dans l'adresse : impossible de viser une vraie station.
    paths = [path for path in app.openapi()["paths"] if path.startswith("/demo")]
    assert paths == ["/demo/test-station", "/demo/test-station/fuels/{fuel_type}"]


def test_refuse_depuis_un_autre_site(sent):
    assert change("GAZOLE", "AVAILABLE", Origin="http://site-inconnu.example").status_code == 403
