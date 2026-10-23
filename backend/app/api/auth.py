# Routes des comptes : inscription, connexion, déconnexion, compte connecté.
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import COOKIE_SECURE, FRONTEND_URL
from app.database import engine, get_db
from app.integrations.mailer import send_email
from app.schemas import (
    AccountDeletion, EmailConfirmation, LoginRequest, NotificationPrefs, PasswordResetConfirm, PasswordResetRequest,
    RegisterRequest, Unsubscribe, UserPublic,
)
from app.security import dummy_hash, hash_password, needs_rehash, new_token, token_digest, verify_password

router = APIRouter(tags=["comptes"])
logger = logging.getLogger(__name__)
Db = Annotated[Session, Depends(get_db)]

SESSION_IDLE = timedelta(days=7)  # déconnecté après 7 jours sans visite
SESSION_MAX = timedelta(days=30)  # et au plus tard 30 jours après la connexion, même en restant actif
MAX_SESSIONS_PER_USER = 10  # plusieurs appareils, mais pas des millions de lignes pour un seul compte
TOUCH_EVERY = timedelta(minutes=5)  # « dernière visite » mise à jour au plus toutes les 5 min (moins d'écritures)

# Limites d'essais (journal auth_attempts) : par fenêtre de 15 min pour la connexion, d'1 h pour l'inscription.
LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_IP_AND_EMAIL = 5
MAX_FAILURES_PER_IP = 20  # un robot qui essaie beaucoup d'e-mails depuis une adresse
MAX_FAILURES_PER_EMAIL = 50  # une attaque répartie sur beaucoup d'adresses contre un même compte
REGISTER_WINDOW = timedelta(hours=1)
MAX_REGISTRATIONS_PER_IP = 10
RESET_VALID_FOR = timedelta(minutes=30)  # durée de vie d'un lien de réinitialisation
UNSUBSCRIBE_VALID_FOR = timedelta(days=60)  # lien « Ne plus recevoir d'alertes » des e-mails (V7.4)
CONFIRM_VALID_FOR = timedelta(hours=24)  # durée de vie d'un lien de confirmation de l'adresse (V7.3)
MAX_CONFIRMATION_EMAILS_PER_EMAIL = 3  # par heure : inscriptions + renvois du lien, pour ne pas inonder une boîte
RESET_WINDOW = timedelta(hours=1)
MAX_RESETS_PER_EMAIL = 3  # sinon, n'importe qui pourrait inonder une boîte e-mail de liens
MAX_RESETS_PER_IP = 5

# Préfixe __Host- en production : le navigateur exige alors HTTPS, le domaine exact et le chemin « / ».
COOKIE_NAME = "__Host-session" if COOKIE_SECURE else "session"


def client_ip(request: Request) -> str:
    # shortcut: si le site était publié derrière un serveur frontal, l'adresse réelle est dans X-Forwarded-For : lancer uvicorn
    # avec --proxy-headers et --forwarded-allow-ips, sinon toutes les requêtes auraient l'IP du proxy.
    return request.client.host if request.client else "inconnue"


def too_many(retry_after: timedelta, detail: str) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(retry_after.total_seconds()))})


def count_attempts(db: Session, kind: str, since: datetime, success: bool | None = None, **filters: str) -> int:
    statement = select(func.count()).select_from(models.AuthAttempt).where(
        models.AuthAttempt.kind == kind, models.AuthAttempt.attempted_at >= since
    )
    if success is not None:
        statement = statement.where(models.AuthAttempt.success == success)
    for column, value in filters.items():
        statement = statement.where(getattr(models.AuthAttempt, column) == value)
    return db.scalar(statement)


REGISTER_SENT = (
    "Si cette adresse est valide, un e-mail vient de vous être envoyé. Ouvrez-le pour terminer l'inscription."
)


@router.post("/auth/register", status_code=202)
def register(body: RegisterRequest, request: Request, background: BackgroundTasks, db: Db):
    ip = client_ip(request)
    if count_attempts(db, "register", datetime.now(UTC) - REGISTER_WINDOW, ip=ip) >= MAX_REGISTRATIONS_PER_IP:
        raise too_many(REGISTER_WINDOW, "Trop d'inscriptions depuis cette adresse. Réessayez dans une heure.")
    if count_confirmation_emails(db, body.email) >= MAX_CONFIRMATION_EMAILS_PER_EMAIL:
        raise too_many(REGISTER_WINDOW, "Trop de demandes pour cette adresse e-mail. Réessayez dans une heure.")
    # Même travail et même réponse, que l'adresse ait déjà un compte ou non (V7.3) : l'empreinte Argon2 est
    # toujours calculée, et tout ce qui dépend du compte est fait APRÈS la réponse, en tâche de fond.
    # Avant : « Un compte existe déjà » (409) permettait de tester qui est inscrit.
    password_hash = hash_password(body.password.get_secret_value())
    db.add(models.AuthAttempt(kind="register", ip=ip, email=body.email, success=True))
    db.commit()
    background.add_task(register_in_background, body.email, password_hash)
    return {"detail": REGISTER_SENT}


def count_confirmation_emails(db: Session, email: str) -> int:
    since = datetime.now(UTC) - REGISTER_WINDOW
    return count_attempts(db, "register", since, email=email) + count_attempts(db, "confirm", since, email=email)


def register_in_background(email: str, password_hash: str) -> None:
    with background_session() as db:
        user = db.scalar(select(models.User).where(models.User.email == email))
        if user is not None and user.email_verified_at is not None:
            send_already_registered_email(email)  # aucun compte créé, mot de passe inchangé
            return
        if user is None:
            user = models.User(email=email, password_hash=password_hash)
            db.add(user)
        else:
            # Compte jamais confirmé : le nouveau mot de passe remplace l'ancien. Sinon, quelqu'un qui aurait
            # inscrit TON adresse avec SON mot de passe t'empêcherait de t'inscrire ; c'est celui qui ouvre
            # le lien (donc qui a accès à la boîte) qui gagne.
            user.password_hash = password_hash
        try:
            db.flush()
        except IntegrityError:
            return  # deux inscriptions simultanées de la même adresse : l'autre crée le compte et envoie le lien
        token = new_confirmation_token(db, user)
        db.commit()
    send_confirmation_email(email, token)


def new_confirmation_token(db: Session, user: models.User) -> str:
    # Un seul lien valable à la fois : le nouveau annule les précédents.
    db.execute(delete(models.EmailConfirmationToken).where(models.EmailConfirmationToken.user_id == user.id))
    token, digest = new_token()
    db.add(models.EmailConfirmationToken(token_hash=digest, user_id=user.id))
    return token


def send_confirmation_email(to: str, token: str) -> None:
    body = (
        "Bonjour,\n\n"
        "Pour terminer votre inscription à StationAlerte, confirmez votre adresse en ouvrant ce lien"
        " (valable 24 heures, une seule fois) :\n"
        f"{FRONTEND_URL}/#confirm={token}\n\n"
        "Si vous n'êtes pas à l'origine de cette inscription, ignorez cet e-mail : aucun compte ne sera activé.\n\n"
        "L'équipe StationAlerte"
    )
    try_send(to, "StationAlerte : confirmez votre adresse e-mail", body)


def send_already_registered_email(to: str) -> None:
    body = (
        "Bonjour,\n\n"
        "Quelqu'un (sans doute vous) a voulu créer un compte StationAlerte avec cette adresse, mais vous en avez"
        " déjà un. Rien n'a changé : votre mot de passe est le même.\n\n"
        f"Pour vous connecter, ou si vous avez oublié votre mot de passe : {FRONTEND_URL}\n\n"
        "L'équipe StationAlerte"
    )
    try_send(to, "StationAlerte : vous avez déjà un compte", body)


def try_send(to: str, subject: str, body: str) -> None:
    try:
        send_email(to, subject, body)
    except (OSError, ValueError):  # serveur injoignable, erreur SMTP, ou adresse impossible à encoder
        logger.exception("Envoi de l'e-mail « %s » impossible", subject)


@router.post("/auth/confirm-email", status_code=204)
def confirm_email(body: EmailConfirmation, db: Db):
    # Verrouillé : deux clics simultanés sur le même lien, le second attend puis le trouve supprimé (usage unique).
    confirmation = db.get(models.EmailConfirmationToken, token_digest(body.token), with_for_update=True)
    if confirmation is None or confirmation.created_at < datetime.now(UTC) - CONFIRM_VALID_FOR:
        if confirmation is not None:
            db.delete(confirmation)
            db.commit()
        raise HTTPException(
            status_code=400, detail="Lien invalide ou expiré. Connectez-vous pour en recevoir un nouveau."
        )
    user = db.get(models.User, confirmation.user_id)
    user.email_verified_at = datetime.now(UTC)
    db.delete(confirmation)  # une seule utilisation
    db.commit()
    # Pas de connexion automatique : un lien intercepté ne donne pas accès au compte sans le mot de passe.


def check_password_limits(db: Session, ip: str, email: str) -> None:
    # Vérifié AVANT le mot de passe : une fois la limite atteinte, même le bon mot de passe est refusé,
    # sinon un robot pourrait continuer à essayer et repérer la seule réponse différente.
    # Utilisé par la connexion et par la suppression du compte (qui redemande le mot de passe).
    since = datetime.now(UTC) - LOGIN_WINDOW
    if (
        count_attempts(db, "login", since, success=False, ip=ip, email=email) >= MAX_FAILURES_PER_IP_AND_EMAIL
        or count_attempts(db, "login", since, success=False, ip=ip) >= MAX_FAILURES_PER_IP
        or count_attempts(db, "login", since, success=False, email=email) >= MAX_FAILURES_PER_EMAIL
    ):
        raise too_many(LOGIN_WINDOW, "Trop d'essais de connexion. Réessayez dans 15 minutes.")


LOGIN_FAILED = (
    "E-mail ou mot de passe incorrect. Si vous venez de vous inscrire, confirmez d'abord votre adresse"
    " avec le lien reçu par e-mail : en vous connectant avec le bon mot de passe, vous en recevez un nouveau."
)


def resend_confirmation_link(email: str, ip: str) -> None:
    """Fait APRÈS la réponse, comme pour le mot de passe oublié : le temps de réponse ne trahit rien."""
    with background_session() as db:
        if count_confirmation_emails(db, email) >= MAX_CONFIRMATION_EMAILS_PER_EMAIL:
            return  # au plus 3 e-mails de confirmation par adresse et par heure
        user = db.scalar(select(models.User).where(models.User.email == email))
        if user is None or user.email_verified_at is not None:
            return
        db.add(models.AuthAttempt(kind="confirm", ip=ip, email=email, success=True))
        token = new_confirmation_token(db, user)
        db.commit()
    send_confirmation_email(email, token)


@router.post("/auth/login", response_model=UserPublic)
def login(body: LoginRequest, request: Request, response: Response, db: Db):
    ip = client_ip(request)
    check_password_limits(db, ip, body.email)

    user = db.scalar(select(models.User).where(models.User.email == body.email))
    password = body.password.get_secret_value()
    # Compte inconnu : on calcule quand même une vérification, pour un temps de réponse identique.
    valid = verify_password(user.password_hash if user else dummy_hash(), password) and user is not None
    unconfirmed = valid and user.email_verified_at is None
    db.add(models.AuthAttempt(kind="login", ip=ip, email=body.email, success=valid and not unconfirmed))
    if not valid or unconfirmed:
        db.commit()
        # Un seul message et la même réponse 401, même pour un compte pas encore confirmé (V7.5) : avant, un 403
        # « pas confirmée » permettait de savoir qui est inscrit (s'inscrire avec l'adresse d'un autre et SON
        # propre mot de passe, puis se connecter : 403 = pas de compte, 401 = compte existant).
        # Réponse renvoyée et non « raise » : FastAPI abandonne les tâches de fond d'une erreur levée.
        return JSONResponse(
            status_code=401,
            content={"detail": LOGIN_FAILED},
            background=BackgroundTask(resend_confirmation_link, user.email, ip) if unconfirmed else None,
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)  # réglages Argon2 renforcés depuis l'inscription
    now = datetime.now(UTC)
    # Fixation de session : l'éventuelle session déjà présente dans ce navigateur est supprimée, et on en
    # crée toujours une nouvelle. Au passage, ménage des sessions expirées de ce compte.
    if old_token := request.cookies.get(COOKIE_NAME):
        db.execute(delete(models.UserSession).where(models.UserSession.token_hash == token_digest(old_token)))
    db.execute(
        delete(models.UserSession).where(
            models.UserSession.user_id == user.id,
            or_(models.UserSession.last_seen_at < now - SESSION_IDLE, models.UserSession.created_at < now - SESSION_MAX),
        )
    )
    token, digest = new_token()
    # Heures fixées ici : now() de PostgreSQL est identique dans toute une transaction, et le tri ci-dessous
    # doit reconnaître la session la plus récente.
    db.add(models.UserSession(token_hash=digest, user_id=user.id, created_at=now, last_seen_at=now))
    db.flush()
    # Au-delà de MAX_SESSIONS_PER_USER, les plus anciennes sont supprimées (déconnexion de ces appareils).
    oldest = (
        select(models.UserSession.token_hash)
        .where(models.UserSession.user_id == user.id)
        .order_by(models.UserSession.created_at.desc())
        .offset(MAX_SESSIONS_PER_USER)
    )
    db.execute(delete(models.UserSession).where(models.UserSession.token_hash.in_(oldest)))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_MAX.total_seconds()),
        httponly=True,  # illisible par JavaScript : un script injecté ne peut pas le voler
        samesite="lax",  # pas envoyé quand un autre site déclenche une requête qui modifie des données
        secure=COOKIE_SECURE,  # HTTPS uniquement en production
        path="/",
    )
    return user


def current_session(request: Request, db: Db) -> models.UserSession:
    """Dépendance des routes privées : la session du cookie, ou 401."""
    token = request.cookies.get(COOKIE_NAME)
    session = db.get(models.UserSession, token_digest(token)) if token else None
    if session is None:
        raise HTTPException(status_code=401, detail="Connexion requise")
    now = datetime.now(UTC)
    if session.last_seen_at < now - SESSION_IDLE or session.created_at < now - SESSION_MAX:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="Connexion requise")
    if session.last_seen_at < now - TOUCH_EVERY:
        session.last_seen_at = now
        db.commit()
    return session


CurrentSession = Annotated[models.UserSession, Depends(current_session)]


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Db):
    # Toujours 204, même sans session : se déconnecter deux fois n'est pas une erreur.
    if token := request.cookies.get(COOKIE_NAME):
        db.execute(delete(models.UserSession).where(models.UserSession.token_hash == token_digest(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")


@router.get("/me", response_model=UserPublic)
def me(session: CurrentSession):
    return session.user


@router.delete("/me", status_code=204)
def delete_account(body: AccountDeletion, session: CurrentSession, request: Request, response: Response,
                   background: BackgroundTasks, db: Db):
    """Supprime le compte et tout ce qui lui appartient (favoris, alertes, sessions, liens : ON DELETE CASCADE)."""
    user, ip = session.user, client_ip(request)
    check_password_limits(db, ip, user.email)
    if not verify_password(user.password_hash, body.password.get_secret_value()):
        # Compté comme un échec de connexion : une session volée ne permet pas de deviner le mot de passe ici.
        db.add(models.AuthAttempt(kind="login", ip=ip, email=user.email, success=False))
        db.commit()
        raise HTTPException(status_code=403, detail="Mot de passe incorrect : le compte n'a pas été supprimé.")
    email = user.email
    db.delete(user)
    db.commit()
    # shortcut: le journal auth_attempts garde l'e-mail jusqu'à 30 jours (sécurité : enquête sur une attaque),
    # puis le ménage l'efface ; à mentionner dans la politique de confidentialité (V8).
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")
    background.add_task(send_account_deleted_email, email)


def send_account_deleted_email(to: str) -> None:
    body = (
        "Bonjour,\n\n"
        "Votre compte StationAlerte a été supprimé, avec vos stations favorites, vos alertes et vos préférences.\n"
        "Vous ne recevrez plus aucun e-mail de notre part.\n\n"
        "Si vous n'êtes pas à l'origine de cette suppression, quelqu'un connaissait votre mot de passe : changez-le"
        " partout où vous l'utilisez.\n\n"
        "L'équipe StationAlerte"
    )
    try_send(to, "StationAlerte : votre compte a été supprimé", body)


@router.post("/auth/unsubscribe", status_code=200)
def unsubscribe(body: Unsubscribe, db: Db):
    """Lien « Ne plus recevoir d'alertes » des e-mails : sans connexion, le jeton du lien suffit (V7.4).
    Coupe les deux préférences ; le compte est gardé et les alertes peuvent être réactivées sur le site."""
    link = db.get(models.UnsubscribeToken, token_digest(body.token))
    if link is None or link.created_at < datetime.now(UTC) - UNSUBSCRIBE_VALID_FOR:
        raise HTTPException(status_code=400, detail="Lien de désabonnement invalide ou expiré.")
    user = db.get(models.User, link.user_id)
    user.notify_unavailable = user.notify_available = False
    db.commit()
    return {"detail": "C'est fait : vous ne recevrez plus d'alertes par e-mail. Pour les réactiver, connectez-vous"
                      " et cochez vos préférences dans « Mes stations favorites »."}


@router.put("/me/notifications", response_model=UserPublic)
def set_notifications(body: NotificationPrefs, session: CurrentSession, db: Db):
    # Renvoie le compte à jour : le site n'a pas besoin de le redemander.
    session.user.notify_unavailable = body.notify_unavailable
    session.user.notify_available = body.notify_available
    db.commit()
    return session.user


# --- Mot de passe oublié ---

RESET_SENT = (
    "Si un compte existe pour cette adresse, un e-mail vient d'être envoyé. Le lien est valable 30 minutes."
)


def send_reset_email(to: str, token: str) -> None:
    # Le jeton est après « # » : cette partie de l'adresse n'est jamais envoyée à un serveur, ni aux autres
    # sites que la page appelle (fond de carte IGN…) dans l'en-tête Referer. Le site la lit puis l'efface.
    link = f"{FRONTEND_URL}/#reset={token}"
    body = (
        "Bonjour,\n\n"
        "Quelqu'un (sans doute vous) a demandé à réinitialiser le mot de passe de votre compte StationAlerte.\n\n"
        "Pour choisir un nouveau mot de passe, ouvrez ce lien (valable 30 minutes, une seule fois) :\n"
        f"{link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail : votre mot de passe ne change pas.\n\n"
        "L'équipe StationAlerte"
    )
    try_send(to, "StationAlerte : réinitialisation de votre mot de passe", body)


def background_session() -> Session:
    # Le travail fait après la réponse a besoin de sa propre session : celle de la requête est déjà fermée.
    # Les tests la remplacent par la session de test.
    return Session(engine)


def create_and_send_reset_link(email: str) -> None:
    """Fait APRÈS la réponse : sinon le temps de réponse trahirait qu'un compte existe (mesuré le 17/10/2026 :
    11 ms avec compte, 4 ms sans, à cause de la création du lien en base)."""
    with background_session() as db:
        user = db.scalar(select(models.User).where(models.User.email == email))
        if user is None:
            return
        # Une nouvelle demande annule les liens précédents : un seul lien valable à la fois.
        db.execute(delete(models.PasswordResetToken).where(models.PasswordResetToken.user_id == user.id))
        token, digest = new_token()
        db.add(models.PasswordResetToken(token_hash=digest, user_id=user.id))
        db.commit()
    send_reset_email(email, token)


@router.post("/auth/password-reset/request", status_code=202)
def request_password_reset(body: PasswordResetRequest, request: Request, background: BackgroundTasks, db: Db):
    ip = client_ip(request)
    since = datetime.now(UTC) - RESET_WINDOW
    if (
        count_attempts(db, "reset", since, ip=ip) >= MAX_RESETS_PER_IP
        or count_attempts(db, "reset", since, email=body.email) >= MAX_RESETS_PER_EMAIL
    ):
        raise too_many(RESET_WINDOW, "Trop de demandes de réinitialisation. Réessayez dans une heure.")
    # Exactement le même travail avant la réponse, que le compte existe ou non : ni le message ni le temps de
    # réponse ne permettent de savoir qui est inscrit. Le lien est créé et envoyé ensuite, en tâche de fond.
    exists = db.scalar(select(models.User.id).where(models.User.email == body.email)) is not None
    db.add(models.AuthAttempt(kind="reset", ip=ip, email=body.email, success=exists))
    db.commit()
    background.add_task(create_and_send_reset_link, body.email)
    return {"detail": RESET_SENT}


@router.post("/auth/password-reset/confirm", status_code=204)
def confirm_password_reset(body: PasswordResetConfirm, db: Db):
    # Verrouillé : deux envois simultanés du même lien ne changent pas deux fois le mot de passe (usage unique).
    reset = db.get(models.PasswordResetToken, token_digest(body.token), with_for_update=True)
    if reset is None or reset.created_at < datetime.now(UTC) - RESET_VALID_FOR:
        if reset is not None:
            db.delete(reset)
            db.commit()
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré. Faites une nouvelle demande.")
    user = db.get(models.User, reset.user_id)
    user.password_hash = hash_password(body.password.get_secret_value())
    # Avoir reçu le lien prouve l'accès à la boîte e-mail : l'adresse est confirmée du même coup.
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    db.delete(reset)  # une seule utilisation
    # Toutes les sessions sont coupées : si quelqu'un d'autre était connecté au compte, il ne l'est plus.
    db.execute(delete(models.UserSession).where(models.UserSession.user_id == user.id))
    db.commit()
