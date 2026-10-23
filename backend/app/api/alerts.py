# Historique des alertes du compte connecté (V7.2). Comme pour les favoris, l'utilisateur vient TOUJOURS
# de la session, jamais de l'adresse : impossible de lire les alertes d'un autre compte.
from fastapi import APIRouter
from sqlalchemy import select

from app import models
from app.api.auth import CurrentSession, Db
from app.schemas import AlertPublic

router = APIRouter(prefix="/me/alerts", tags=["alertes"])

HISTORY_SIZE = 20  # les plus récentes : de quoi vérifier ce qui a été envoyé, sans tout l'historique


@router.get("", response_model=list[AlertPublic])
def list_alerts(session: CurrentSession, db: Db):
    alert, event, station = models.Alert, models.AvailabilityEvent, models.Station
    rows = db.execute(
        select(alert, event, station.name)
        .join(event, event.id == alert.event_id)
        .join(station, station.id == event.station_id)
        .where(alert.user_id == session.user_id)
        .order_by(alert.id.desc())
        .limit(HISTORY_SIZE)
    ).all()
    return [
        AlertPublic(
            id=a.id, created_at=a.created_at, status=a.status, sent_at=a.sent_at, station_id=e.station_id,
            station_name=name, fuel_type=e.fuel_type, label=e.label, old_status=e.old_status,
            new_status=e.new_status, source_updated_at=e.source_updated_at,
        )
        for a, e, name in rows
    ]
