# Le surveillant (V6) : programme séparé de l'API, qui vérifie le flux officiel toutes les 10 minutes, même sans
# visiteur. Lancement (depuis backend/) : uv run python -m app.worker — arrêt : Ctrl+C.
import logging
import time

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import sync
from app.config import CHECK_EVERY_MINUTES
from app.database import engine
from app.alert_emails import send_pending_alerts
from app.housekeeping import clean_up

RETRY_SECONDS = 5 * 60  # après un échec (source ou base en panne), nouvel essai 5 min plus tard
LOCK_ID = 6_100_001  # numéro arbitraire, propre à StationAlerte, du verrou « un seul surveillant »

logger = logging.getLogger("app.worker")


def single_instance_lock() -> Connection | None:
    """Verrou PostgreSQL gardé tant que la connexion reste ouverte : deux surveillants lancés par erreur
    importeraient deux fois. Renvoie None si un autre surveillant le détient déjà."""
    # shortcut: si la base redémarre, la connexion (et le verrou) sont perdus sans que le surveillant le voie ;
    # un 2e surveillant pourrait alors démarrer. Sans danger : PostgreSQL fait passer les imports l'un après l'autre.
    connection = engine.connect()
    # Hors de la réserve (pool) : sinon close() la remettrait dans la réserve, verrou toujours pris.
    connection.detach()
    if connection.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
        connection.commit()  # le verrou survit à la transaction : il est lié à la connexion
        return connection
    connection.close()
    return None


def check_once() -> float:
    """Vérifie le flux si c'est l'heure, envoie les alertes, et renvoie le nombre de secondes à attendre
    avant le prochain passage."""
    try:
        with Session(engine) as db:
            wait = sync.seconds_until_next_check(db)
        if wait > 0:
            logger.info("Dernière vérification récente : la prochaine aura lieu dans %d min.", wait // 60 + 1)
            return wait
        result = sync.import_feed()
        logger.info(
            "Flux importé : %d stations, %d changements, %d alertes. Prochaine vérification dans %d min.",
            *result, CHECK_EVERY_MINUTES,
        )
        with Session(engine) as db:
            if deleted := {name: count for name, count in clean_up(db).items() if count}:
                logger.info("Ménage : %s supprimé(e)s.", ", ".join(f"{count} {name}" for name, count in deleted.items()))
        wait = sync.CHECK_EVERY.total_seconds()
    except Exception:
        # Réseau, ZIP, XML ou base en erreur : la base garde l'ancienne copie (transaction annulée).
        logger.exception("Vérification impossible, nouvel essai dans %d min", RETRY_SECONDS // 60)
        wait = RETRY_SECONDS
    # Même si l'import a échoué : une panne de la source ne doit pas retenir les alertes déjà prêtes.
    send_alerts()
    return wait


def send_alerts() -> None:
    try:
        with Session(engine) as db:
            result = send_pending_alerts(db)
        if any(result):
            logger.info("E-mails d'alerte : %d envoyés, %d en échec, %d périmés (plus de 2 h).", *result)
    except Exception:
        logger.exception("Envoi des alertes impossible, nouvel essai au prochain passage")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%d/%m %H:%M:%S")
    while True:
        try:
            lock = single_instance_lock()
            break
        except OperationalError:  # base pas encore démarrée : on attend qu'elle revienne
            logger.exception("Base de données injoignable, nouvel essai dans %d min", RETRY_SECONDS // 60)
            time.sleep(RETRY_SECONDS)
    if lock is None:
        logger.error("Un autre surveillant tourne déjà : celui-ci s'arrête.")
        return
    logger.info("Surveillance démarrée : vérification du flux toutes les %d min.", CHECK_EVERY_MINUTES)
    try:
        while True:
            time.sleep(check_once())
    except KeyboardInterrupt:
        logger.info("Surveillance arrêtée.")
    finally:
        lock.close()


if __name__ == "__main__":
    main()
