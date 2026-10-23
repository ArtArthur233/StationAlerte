# Espace de démonstration (V8, demandé par l'utilisateur) : depuis le site, n'importe quel visiteur change l'état
# des carburants de la station fictive stationTest, pour essayer surveillance, alertes et e-mails sans terminal.
# Garde-fous : routes absentes (404) sans DEMO_MODE=true ; seule stationTest peut changer, jamais une vraie
# station ; sans compte (aucune donnée personnelle), mais protégé contre les autres sites (CSRF, main.py).
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import alerts, config, models, test_station
from app.alert_emails import send_pending_alerts
from app.api.auth import Db
from app.schemas import DemoChangeResult, DemoFuelChange, Station

# Les six carburants connus ; AUTRE n'a pas de sens pour une station fictive.
DemoFuel = Literal["GAZOLE", "SP95", "E10", "SP98", "E85", "GPLC"]


def demo_enabled() -> None:
    if not config.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Not Found")  # même réponse qu'une route qui n'existe pas


router = APIRouter(prefix="/demo", tags=["démonstration"], dependencies=[Depends(demo_enabled)])


@router.get("/test-station", response_model=Station | None)
def get_test_station(db: Db):
    return db.get(models.Station, test_station.TEST_STATION_ID)  # null : pas encore créée


@router.put("/test-station/fuels/{fuel_type}", response_model=DemoChangeResult)
def change_test_station_fuel(fuel_type: DemoFuel, change: DemoFuelChange, db: Db):
    status = test_station.REMOVE if change.status == "NOT_SOLD" else change.status
    # Mêmes règles que le surveillant : changements enregistrés, alertes seulement s'il tourne (V6.2).
    allowed = alerts.monitoring_was_running(db)
    event_ids = test_station.apply_now(db, {fuel_type: status})
    created = alerts.create_alerts(db, event_ids) if allowed else 0
    db.commit()
    # Envoi tout de suite, pour voir l'e-mail sans attendre le passage du surveillant (Mailpit répond en
    # quelques millisecondes ; serveur d'e-mails en panne : alertes gardées pour le passage suivant).
    sent = send_now(db).sent if created else 0
    station = db.get(models.Station, test_station.TEST_STATION_ID)
    return DemoChangeResult(station=station, events=len(event_ids), alerts=created, emails_sent=sent, alerts_allowed=allowed)


def send_now(db: Session):
    return send_pending_alerts(db)  # fonction à part : les tests la remplacent
