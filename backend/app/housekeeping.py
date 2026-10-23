# Ménage périodique (V6.3), fait par le surveillant après chaque import : supprime ce qui ne sert plus.
# Mêmes durées que les routes des comptes (app/api/auth.py) : une ligne supprimée ici était déjà refusée là-bas.
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, or_
from sqlalchemy.orm import Session

from app import models
from app.api.auth import CONFIRM_VALID_FOR, RESET_VALID_FOR, SESSION_IDLE, SESSION_MAX, UNSUBSCRIBE_VALID_FOR

# Journal des connexions gardé 30 jours : assez pour enquêter sur une attaque, et les limites d'essais
# ne regardent que la dernière heure au plus.
KEEP_AUTH_ATTEMPTS = timedelta(days=30)
# Inscription jamais confirmée : le compte est supprimé au bout de 7 jours (choix de l'utilisateur, V7.3).
KEEP_UNCONFIRMED_ACCOUNTS = timedelta(days=7)
# Historique des changements (environ 1 000 par jour), leurs alertes et la liste des imports : 90 jours.
# Les alertes ne regardent que le dernier import, et « Mes dernières alertes » n'en montre que 20.
KEEP_HISTORY = timedelta(days=90)


def clean_up(db: Session) -> dict[str, int]:
    """Supprime sessions et liens expirés, vieux journal, vieil historique et comptes jamais confirmés. Renvoie les nombres."""
    now = datetime.now(UTC)
    session, reset, attempt = models.UserSession, models.PasswordResetToken, models.AuthAttempt
    confirm, user, unsubscribe = models.EmailConfirmationToken, models.User, models.UnsubscribeToken
    event, feed_import = models.AvailabilityEvent, models.FeedImport
    deleted = {
        "sessions": db.execute(
            delete(session).where(or_(session.last_seen_at < now - SESSION_IDLE, session.created_at < now - SESSION_MAX))
        ).rowcount,
        "liens de réinitialisation": db.execute(delete(reset).where(reset.created_at < now - RESET_VALID_FOR)).rowcount,
        "lignes du journal": db.execute(delete(attempt).where(attempt.attempted_at < now - KEEP_AUTH_ATTEMPTS)).rowcount,
        "liens de confirmation": db.execute(delete(confirm).where(confirm.created_at < now - CONFIRM_VALID_FOR)).rowcount,
        "liens de désabonnement": db.execute(
            delete(unsubscribe).where(unsubscribe.created_at < now - UNSUBSCRIBE_VALID_FOR)
        ).rowcount,
        # Les alertes de ces changements partent avec eux (ON DELETE CASCADE).
        "changements de disponibilité": db.execute(delete(event).where(event.detected_at < now - KEEP_HISTORY)).rowcount,
        "imports": db.execute(delete(feed_import).where(feed_import.imported_at < now - KEEP_HISTORY)).rowcount,
        # Après la ligne précédente : un compte dont le lien de confirmation (moins de 24 h) vient de partir est
        # gardé, sinon ce lien ne marcherait plus (nouvelle inscription au 7e jour, V7.5).
        "comptes jamais confirmés": db.execute(
            delete(user).where(
                user.email_verified_at.is_(None), user.created_at < now - KEEP_UNCONFIRMED_ACCOUNTS,
                ~exists().where(confirm.user_id == user.id),
            )
        ).rowcount,
    }
    db.commit()
    return deleted
