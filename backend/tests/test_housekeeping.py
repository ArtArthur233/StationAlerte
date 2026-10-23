# Ménage périodique (V6.3) : seules les lignes périmées partent, les autres restent.
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import models
from app.housekeeping import clean_up
from app.security import hash_password, new_token

NOW = datetime.now(UTC)


def test_menage(session):
    user = models.User(email="menage@test.fr", password_hash=hash_password("x" * 12), email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    sessions = {
        "active": (NOW - timedelta(days=1), NOW - timedelta(hours=1)),
        "inactive depuis 8 jours": (NOW - timedelta(days=10), NOW - timedelta(days=8)),
        "connectée il y a 31 jours": (NOW - timedelta(days=31), NOW - timedelta(minutes=1)),
    }
    for name, (created_at, last_seen_at) in sessions.items():
        session.add(models.UserSession(token_hash=new_token()[1], user_id=user.id,
                                       created_at=created_at, last_seen_at=last_seen_at))
    for minutes in (10, 31):
        session.add(models.PasswordResetToken(token_hash=new_token()[1], user_id=user.id,
                                              created_at=NOW - timedelta(minutes=minutes)))
    for days in (29, 31):
        session.add(models.AuthAttempt(kind="login", ip="203.0.113.7", email=user.email, success=False,
                                       attempted_at=NOW - timedelta(days=days)))
    session.flush()

    deleted = clean_up(session)

    # Seulement nos lignes : la base de développement peut contenir les vraies sessions de l'utilisateur.
    left_sessions = session.scalars(select(models.UserSession.created_at).where(models.UserSession.user_id == user.id)).all()
    left_resets = session.scalars(select(models.PasswordResetToken.created_at).where(models.PasswordResetToken.user_id == user.id)).all()
    left_attempts = session.scalars(select(models.AuthAttempt.attempted_at).where(models.AuthAttempt.email == user.email)).all()
    assert left_sessions == [sessions["active"][0]]
    assert left_resets == [NOW - timedelta(minutes=10)]  # le lien de 31 min était déjà refusé par l'API
    assert left_attempts == [NOW - timedelta(days=29)]
    assert deleted["sessions"] >= 2 and deleted["liens de réinitialisation"] >= 1 and deleted["lignes du journal"] >= 1
    assert session.get(models.User, user.id) is not None  # le compte, lui, n'est jamais touché


def test_comptes_jamais_confirmes_supprimes_apres_7_jours(session):
    old = models.User(email="vieux@test.fr", password_hash="x", created_at=NOW - timedelta(days=8))
    recent = models.User(email="recent@test.fr", password_hash="x", created_at=NOW - timedelta(days=6))
    confirmed = models.User(email="confirme@test.fr", password_hash="x", created_at=NOW - timedelta(days=60),
                            email_verified_at=NOW - timedelta(days=60))
    session.add_all([old, recent, confirmed])
    session.flush()
    session.add_all([
        models.EmailConfirmationToken(token_hash=new_token()[1], user_id=recent.id, created_at=NOW - timedelta(hours=25)),
        models.EmailConfirmationToken(token_hash=new_token()[1], user_id=recent.id, created_at=NOW - timedelta(hours=1)),
    ])
    session.flush()

    clean_up(session)

    # Seulement les comptes de ce test : la base de dev peut en avoir d'autres (ex. demo@test.fr).
    mine = [old.email, recent.email, confirmed.email]
    left = set(session.scalars(select(models.User.email).where(models.User.email.in_(mine))))
    assert left == {"recent@test.fr", "confirme@test.fr"}  # un compte confirmé n'est jamais supprimé
    tokens = session.scalars(select(models.EmailConfirmationToken).where(models.EmailConfirmationToken.user_id == recent.id)).all()
    assert len(tokens) == 1  # le lien de plus de 24 h est supprimé


def test_compte_non_confirme_garde_tant_que_son_lien_est_valable(session):
    # Nouvelle inscription au 7e jour : le lien qui vient de partir doit encore marcher (V7.5).
    late = models.User(email="tardif@test.fr", password_hash="x", created_at=NOW - timedelta(days=8))
    session.add(late)
    session.flush()
    session.add(models.EmailConfirmationToken(token_hash=new_token()[1], user_id=late.id, created_at=NOW - timedelta(hours=2)))
    session.flush()
    clean_up(session)
    assert session.get(models.User, late.id) is not None


def test_liens_de_desabonnement_de_plus_de_60_jours_supprimes(session):
    user = models.User(email="desabo@test.fr", password_hash="x", email_verified_at=NOW)
    session.add(user)
    session.flush()
    for days in (61, 59):
        session.add(models.UnsubscribeToken(token_hash=new_token()[1], user_id=user.id, created_at=NOW - timedelta(days=days)))
    session.flush()
    clean_up(session)
    left = session.scalars(select(models.UnsubscribeToken.created_at).where(models.UnsubscribeToken.user_id == user.id)).all()
    assert left == [NOW - timedelta(days=59)]


def test_historique_garde_90_jours_avec_ses_alertes(session):
    user = models.User(email="historique@test.fr", password_hash="x", email_verified_at=NOW)
    station = models.Station(id="TEST-HISTO", name="Histo", address="1 rue Test", postal_code="42000",
                             city="Saint-Étienne", search_text="test")
    session.add_all([user, station])
    session.flush()
    events = {}
    for days in (89, 91):
        events[days] = models.AvailabilityEvent(station_id=station.id, fuel_type="GAZOLE", old_status="AVAILABLE",
                                                new_status="UNAVAILABLE", detected_at=NOW - timedelta(days=days))
        session.add(events[days])
        session.flush()
        session.add(models.Alert(user_id=user.id, event_id=events[days].id, created_at=NOW - timedelta(days=days)))
    imports = [models.FeedImport(station_count=1, imported_at=NOW - timedelta(days=days)) for days in (89, 91)]
    session.add_all(imports)
    session.flush()

    clean_up(session)

    left_events = session.scalars(select(models.AvailabilityEvent.id).where(models.AvailabilityEvent.station_id == station.id)).all()
    left_alerts = session.scalars(select(models.Alert.event_id).where(models.Alert.user_id == user.id)).all()
    assert left_events == [events[89].id]
    assert left_alerts == [events[89].id]  # l'alerte part avec son changement
    assert session.get(models.FeedImport, imports[0].id) is not None
    assert session.get(models.FeedImport, imports[1].id) is None
