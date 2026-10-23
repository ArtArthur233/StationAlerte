# Règles d'alerte (V6.2) : quels changements de disponibilité donnent une alerte, et à qui.
# Ici seulement la décision ; la collecte est dans sync.py, l'envoi des e-mails dans alert_emails.py.
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import models
from app.config import CHECK_EVERY_MINUTES

# Dernier import plus vieux que ça = surveillant arrêté (ou source en panne) : les changements vus maintenant
# sont peut-être anciens ou déjà faux, donc pas d'alerte (choix de l'utilisateur, 17/10/2026).
MAX_GAP = timedelta(minutes=2 * CHECK_EVERY_MINUTES)  # 20 min par défaut


def monitoring_was_running(db: Session) -> bool:
    """À appeler AVANT d'enregistrer le nouvel import."""
    last = db.scalar(select(func.max(models.FeedImport.imported_at)))
    return last is not None and datetime.now(UTC) - last <= MAX_GAP


def wanted_alerts() -> Select:
    """(user_id, event_id) de chaque alerte voulue : compte confirmé qui surveille ce carburant dans cette station
    et a demandé ce type de changement. Vérifié à la création ET juste avant l'envoi (V7.5) : un compte qui s'est
    désabonné entre-temps ne reçoit plus rien."""
    event, watch, user = models.AvailabilityEvent, models.FavoriteFuel, models.User
    wanted = or_(
        # Rupture déclarée (depuis n'importe quel état) : c'est une vraie déclaration datée de la station.
        and_(event.new_status == "UNAVAILABLE", user.notify_unavailable),
        # Retour seulement après une rupture connue : UNKNOWN → AVAILABLE n'est pas un « retour ».
        and_(event.old_status == "UNAVAILABLE", event.new_status == "AVAILABLE", user.notify_available),
    )  # → UNKNOWN n'apparaît dans aucune règle : une information absente n'alerte jamais.
    return (
        select(watch.user_id, event.id)
        .join(watch, and_(watch.station_id == event.station_id, watch.fuel_type == event.fuel_type))
        .join(user, user.id == watch.user_id)
        # Adresse confirmée seulement (V7.3) : jamais d'e-mail vers une boîte dont le propriétaire n'a rien demandé.
        .where(wanted, user.email_verified_at.is_not(None))
    )


def create_alerts(db: Session, event_ids: list[int]) -> int:
    """Crée les alertes des changements donnés, pour chaque compte qui surveille ce carburant dans
    cette station et l'a demandé. Renvoie le nombre d'alertes créées."""
    if not event_ids:
        return 0
    matches = wanted_alerts().where(models.AvailabilityEvent.id.in_(event_ids))
    statement = (
        insert(models.Alert)
        .from_select(["user_id", "event_id"], matches)
        # Contrainte alert_once_per_event : un même changement traité deux fois ne crée pas de doublon.
        .on_conflict_do_nothing(constraint="alert_once_per_event")
        .returning(models.Alert.id)  # rowcount vaut -1 pour un INSERT … SELECT : on compte les lignes renvoyées
    )
    return len(db.scalars(statement).all())
