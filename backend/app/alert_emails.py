# Envoi des alertes par e-mail (V7.1), fait par le surveillant après chaque passage.
# Un seul e-mail par compte et par passage, qui regroupe tous ses changements (choix de l'utilisateur).
# Une alerte n'est « envoyée » que si le serveur d'e-mails a accepté le message (règle du projet).
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.orm import Session

from app import models
from app.alerts import wanted_alerts
from app.config import FRONTEND_URL
from app.integrations.mailer import MailServerDown, send_email
from app.security import new_token

MAX_AGE = timedelta(hours=2)  # plus vieille, l'alerte n'est plus envoyée : la rupture est peut-être finie
MAX_ATTEMPTS = 5  # puis l'alerte passe à « failed » (un essai par passage, soit environ 50 min)
PARIS = ZoneInfo("Europe/Paris")

logger = logging.getLogger(__name__)

# Mêmes noms que le site (frontend/src/types/station.ts et utils/stations.ts).
FUEL_NAMES = {"GAZOLE": "Gazole", "SP95": "SP95", "E10": "SP95-E10", "SP98": "SP98", "E85": "E85", "GPLC": "GPLc",
              "AUTRE": "Autre carburant"}
STATUS_NAMES = {"AVAILABLE": "Déclaré disponible", "UNAVAILABLE": "Indisponible", "UNKNOWN": "Inconnu"}


class SendResult(NamedTuple):
    sent: int  # e-mails acceptés par le serveur
    failed: int  # e-mails refusés ou serveur injoignable (nouvel essai au passage suivant)
    expired: int  # alertes trop vieilles, abandonnées sans envoi


def one_line(text: str) -> str:
    # Un nom venu du flux avec un retour à la ligne ferait refuser l'objet de l'e-mail (protection contre
    # l'injection d'en-têtes) : on le remet sur une ligne.
    return " ".join(text.split())


def fuel_name(event: models.AvailabilityEvent) -> str:
    name = FUEL_NAMES[event.fuel_type]
    return f"{name} ({one_line(event.label)})" if event.label else name


def compose(rows: list[tuple[models.AvailabilityEvent, models.Station]], unsubscribe_link: str) -> tuple[str, str]:
    """Objet et texte de l'e-mail d'un compte, à partir de ses changements (dans l'ordre de détection)."""
    if len(rows) == 1:
        event, station = rows[0]
        what = "indisponible" if event.new_status == "UNAVAILABLE" else "de nouveau disponible"
        subject = f"StationAlerte : {fuel_name(event)} {what} à {one_line(station.name)}"
    else:
        subject = f"StationAlerte : {len(rows)} changements dans vos stations"
    by_station = defaultdict(list)
    for event, station in rows:
        by_station[station].append(event)
    lines = ["Bonjour,", "", "Changement dans vos stations surveillées :" if len(rows) == 1 else
             "Changements dans vos stations surveillées :", ""]
    for station, events in by_station.items():
        lines.append(f"• {one_line(station.name)} — {one_line(station.address)}, {station.postal_code} {one_line(station.city)}")
        for event in events:
            # La date vient de la source (déclaration de la station) ; un statut connu en a toujours une.
            when = event.source_updated_at.astimezone(PARIS).strftime("%d/%m à %H:%M") if event.source_updated_at else "date inconnue"
            lines.append(f"  {fuel_name(event)} : {STATUS_NAMES[event.old_status]} → {STATUS_NAMES[event.new_status]}"
                         f" (déclaré le {when})")
        lines.append("")
    lines += [
        "Ces informations sont déclarées par les stations sur prix-carburants.gouv.fr :",
        "vérifiez avant de vous déplacer.",
        "",
        f"Modifier vos stations et vos alertes : {FRONTEND_URL}",
        f"Ne plus recevoir d'alertes : {unsubscribe_link}",
    ]
    return subject[:200], "\n".join(lines)


def send_pending_alerts(db: Session) -> SendResult:
    now = datetime.now(UTC)
    alert = models.Alert
    expired = db.execute(
        update(alert).where(alert.status == "pending", alert.created_at < now - MAX_AGE).values(status="expired")
    ).rowcount
    db.commit()

    sent = failed = 0
    done: set[int] = set()  # comptes déjà traités pendant ce passage (même en échec : un essai par passage)
    while True:
        user_id = db.scalar(
            select(alert.user_id).where(alert.status == "pending", alert.user_id.not_in(done)).order_by(alert.id).limit(1)
        )
        if user_id is None:
            break
        done.add(user_id)
        # Un compte à la fois, verrouillé (V7.5) : un autre envoi lancé en même temps (--maintenant) le saute
        # (SKIP LOCKED) au lieu d'envoyer le même e-mail deux fois ; une suppression du compte ou un changement de
        # préférences attend la fin de cet e-mail. Avant, seules les alertes étaient verrouillées et une
        # suppression pendant l'envoi finissait en blocage mutuel (deadlock, reproduit le 17/10/2026).
        # NO KEY UPDATE : la création d'alertes par l'import, elle, n'attend pas.
        if db.scalar(
            select(models.User.id).where(models.User.id == user_id).with_for_update(key_share=True, skip_locked=True)
        ) is None:
            continue  # pris par l'autre envoi, ou compte supprimé
        # Désabonné, préférence décochée ou carburant plus surveillé depuis la création : alerte supprimée, jamais envoyée.
        db.execute(
            delete(alert).where(
                alert.user_id == user_id, alert.status == "pending",
                tuple_(alert.user_id, alert.event_id).not_in(wanted_alerts().where(models.FavoriteFuel.user_id == user_id)),
            )
        )
        rows = db.execute(
            select(alert, models.AvailabilityEvent, models.Station, models.User.email)
            .join(models.AvailabilityEvent, models.AvailabilityEvent.id == alert.event_id)
            .join(models.Station, models.Station.id == models.AvailabilityEvent.station_id)
            .join(models.User, models.User.id == alert.user_id)
            .where(alert.user_id == user_id, alert.status == "pending")
            .order_by(alert.id)
            .with_for_update(of=alert, skip_locked=True)
        ).all()
        if not rows:
            db.commit()  # plus rien à envoyer à ce compte (alertes supprimées ci-dessus, ou envoyées par l'autre envoi)
            continue
        email = rows[0][3]
        # Lien personnel, nouveau à chaque e-mail (seule son empreinte est stockée, comme les autres jetons).
        token, digest = new_token()
        db.add(models.UnsubscribeToken(token_hash=digest, user_id=user_id))
        link = f"{FRONTEND_URL}/#unsubscribe={token}"
        subject, body = compose([(event, station) for _, event, station, _ in rows], link)
        try:
            # List-Unsubscribe : les messageries affichent alors un bouton « Se désabonner ».
            send_email(email, subject, body, headers={"List-Unsubscribe": f"<{link}>"})
        # OSError : réseau et SMTP ; ValueError : adresse ou texte impossible à encoder. Ne doit jamais arrêter
        # l'envoi des autres comptes (une adresse à accents refusée par le fournisseur bloquait tout, V7.5).
        except (OSError, ValueError) as error:
            failed += 1
            for row in rows:
                row[0].attempts += 1
                row[0].last_error = f"{type(error).__name__}: {error}"[:200]
                if row[0].attempts >= MAX_ATTEMPTS:
                    row[0].status = "failed"
            db.commit()
            logger.warning("Envoi de l'alerte au compte %d impossible : %s", user_id, type(error).__name__)
            if isinstance(error, MailServerDown):
                break  # serveur injoignable : inutile d'essayer les autres comptes maintenant
            continue
        for row in rows:
            row[0].status, row[0].sent_at = "sent", datetime.now(UTC)
        db.commit()  # chaque e-mail noté tout de suite : un arrêt brutal ne renverra que l'e-mail en cours
        sent += 1
    return SendResult(sent, failed, expired)
