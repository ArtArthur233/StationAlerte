# Synchronisation flux officiel → base. Depuis V6, seul le surveillant (app/worker.py) importe, toutes les
# 10 minutes, même sans visiteur. Les routes de l'API lisent la base, jamais le flux.
import logging
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import alerts, models, test_station
from app.config import CHECK_EVERY_MINUTES
from app.database import engine
from app.integrations.prix_carburants import fetch_stations
from app.schemas import Station
from app.services import save_stations

CHECK_EVERY = timedelta(minutes=CHECK_EVERY_MINUTES)

logger = logging.getLogger(__name__)


class ImportResult(NamedTuple):
    stations: int
    events: int  # changements de disponibilité
    alerts: int


class SourceUnavailable(Exception):
    """Aucune donnée réelle disponible : la base est vide (le surveillant n'a encore rien importé)."""


def has_stations(db: Session) -> bool:
    return db.scalar(select(models.Station.id).limit(1)) is not None


def last_import_id(db: Session) -> int | None:
    # Change à chaque import réussi : l'API sait ainsi que les données ont changé, même si l'import a eu lieu
    # dans un autre programme (le surveillant).
    return db.scalar(select(func.max(models.FeedImport.id)))


def seconds_until_next_check(db: Session) -> float:
    # Calculé depuis la base : un surveillant redémarré ne retélécharge pas le flux s'il l'a fait il y a 5 min.
    last = db.scalar(select(func.max(models.FeedImport.imported_at)))
    if last is None:
        return 0.0
    return max(0.0, (last + CHECK_EVERY - datetime.now(UTC)).total_seconds())


def save_and_alert(db: Session, stations: list[Station]) -> ImportResult:
    # Lu AVANT d'enregistrer ce nouvel import, qui deviendrait sinon le « dernier import ».
    alerts_allowed = alerts.monitoring_was_running(db)
    event_ids = save_stations(db, stations)
    # Surveillant arrêté : les changements restent dans l'historique, mais sans alerte.
    created = alerts.create_alerts(db, event_ids) if alerts_allowed else 0
    return ImportResult(len(stations), len(event_ids), created)


def import_feed() -> ImportResult:
    stations = fetch_stations()
    if not stations:
        # Un flux vide est sûrement une panne de la source : on garde la copie actuelle.
        raise ValueError("Flux prix-carburants vide")
    # Station fictive de test (app/test_station.py) : seulement si son fichier existe, donc jamais en production.
    if extra := test_station.load():
        logger.warning("Station fictive de test ajoutée au flux (%s)", test_station.TEST_STATION_PATH.name)
        stations += extra
    # session.begin() : stations, changements et alertes sont validés d'un coup, ou annulés ensemble.
    with Session(engine) as session, session.begin():
        return save_and_alert(session, stations)
