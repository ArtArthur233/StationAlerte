# GET /me/alerts (V7.2) : chacun ne voit que ses alertes, les plus récentes d'abord.
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import models
from app.api import alerts
from app.main import app

pytestmark = pytest.mark.usefixtures("api_db")


@pytest.fixture
def station(session):
    session.add(models.Station(id="TEST-HISTO", name="stationTest", address="Station fictive de test",
                               postal_code="42000", city="Saint-Étienne", search_text="stationtest"))
    session.flush()


def add_alert(session, client, new_status="UNAVAILABLE", status="pending") -> None:
    user_id = client.get("/me").json()["id"]
    event = models.AvailabilityEvent(station_id="TEST-HISTO", fuel_type="GAZOLE", old_status="AVAILABLE",
                                     new_status=new_status, source_updated_at=datetime.now(UTC))
    session.add(event)
    session.flush()
    session.add(models.Alert(user_id=user_id, event_id=event.id, status=status,
                             sent_at=datetime.now(UTC) if status == "sent" else None))
    session.flush()


def test_connexion_requise():
    assert TestClient(app).get("/me/alerts").status_code == 401


def test_aucune_alerte_au_depart(alice):
    assert alice.get("/me/alerts").json() == []


def test_historique_le_plus_recent_d_abord(alice, station, session):
    add_alert(session, alice, status="sent")
    add_alert(session, alice, new_status="AVAILABLE")
    first, second = alice.get("/me/alerts").json()

    assert (first["newStatus"], first["status"], first["sentAt"]) == ("AVAILABLE", "pending", None)
    assert (second["status"], second["stationName"], second["fuelType"]) == ("sent", "stationTest", "GAZOLE")
    assert second["sentAt"] is not None and second["oldStatus"] == "AVAILABLE"


def test_chacun_ses_alertes(alice, camille, station, session):
    add_alert(session, alice)
    assert len(alice.get("/me/alerts").json()) == 1
    assert camille.get("/me/alerts").json() == []  # Camille ne voit pas celles d'Alice


def test_limite_de_l_historique(alice, station, session, monkeypatch):
    monkeypatch.setattr(alerts, "HISTORY_SIZE", 2)
    for _ in range(3):
        add_alert(session, alice)
    assert len(alice.get("/me/alerts").json()) == 2
