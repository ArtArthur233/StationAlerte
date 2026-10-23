from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models, security
from app.api import auth
from app.main import app
from app.security import hash_password, token_digest

PASSWORD = "correct-horse-battery"
EMAIL = "alice@example.fr"
pytestmark = pytest.mark.usefixtures("api_db")


@pytest.fixture
def client():
    # Un client neuf par test : chacun a son propre « navigateur », donc ses propres cookies.
    return TestClient(app)


@pytest.fixture
def user(session) -> models.User:
    user = models.User(email=EMAIL, password_hash=hash_password(PASSWORD), email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    return user


def login(client, email=EMAIL, password=PASSWORD, **headers):
    return client.post("/auth/login", json={"email": email, "password": password}, headers=headers)


def sessions_of(session, user) -> list[models.UserSession]:
    return session.scalars(select(models.UserSession).where(models.UserSession.user_id == user.id)).all()


def failures(session, n, ip="testclient", email=EMAIL):
    # Simule n échecs récents dans le journal (plus rapide que n vraies tentatives avec Argon2).
    session.add_all(models.AuthAttempt(kind="login", ip=ip, email=email, success=False) for _ in range(n))
    session.flush()


# --- Connexion ---


def test_connexion_puis_compte_connecte(client, user):
    response = login(client)

    assert response.status_code == 200
    expected = {"id": user.id, "email": EMAIL, "notifyUnavailable": True, "notifyAvailable": False}
    assert response.json() == expected
    assert client.get("/me").json() == expected


def test_cookie_protege(client, user):
    set_cookie = login(client).headers["set-cookie"].lower()

    assert set_cookie.startswith("session=")
    assert "httponly" in set_cookie  # illisible par JavaScript
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=2592000" in set_cookie  # 30 jours
    assert "secure" not in set_cookie  # en local seulement (COOKIE_SECURE=false)


def test_email_en_majuscules_accepte(client, user):
    assert login(client, email="ALICE@Example.fr").status_code == 200


@pytest.mark.parametrize(("email", "password"), [(EMAIL, PASSWORD + "x"), ("inconnu@example.fr", PASSWORD)])
def test_meme_reponse_pour_mauvais_mot_de_passe_et_compte_inconnu(client, user, email, password):
    response = login(client, email=email, password=password)

    assert response.status_code == 401
    assert response.json() == {"detail": auth.LOGIN_FAILED}
    assert "set-cookie" not in response.headers


def test_compte_inconnu_fait_quand_meme_un_calcul_argon2(client, monkeypatch):
    # Même temps de réponse qu'avec un vrai compte : le chrono ne révèle pas qui est inscrit.
    calls = []
    monkeypatch.setattr(auth, "verify_password", lambda h, p: calls.append(h) or False)
    login(client, email="inconnu@example.fr")
    assert calls == [security.dummy_hash()]


def test_le_jeton_n_est_stocke_que_sous_forme_d_empreinte(client, user, session):
    login(client)
    token = client.cookies["session"]
    [stored] = sessions_of(session, user)

    assert stored.token_hash == token_digest(token)
    assert token not in stored.token_hash
    assert len(token) >= 43  # 32 octets aléatoires en base64 : 256 bits


def test_nouvelle_session_a_chaque_connexion(client, user, session):
    login(client)
    first = client.cookies["session"]
    login(client)
    second = client.cookies["session"]

    assert first != second
    # Fixation de session : l'ancienne session de ce navigateur est supprimée, pas seulement remplacée.
    assert [s.token_hash for s in sessions_of(session, user)] == [token_digest(second)]


def test_deux_appareils_deux_sessions(user, session):
    phone, laptop = TestClient(app), TestClient(app)
    login(phone)
    login(laptop)
    assert len(sessions_of(session, user)) == 2


def test_empreinte_recalculee_si_reglages_anciens(client, session):
    weak = security.PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    user = models.User(email=EMAIL, password_hash=weak.hash(PASSWORD), email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()

    assert login(client).status_code == 200
    session.refresh(user)
    assert "m=65536,t=3,p=4" in user.password_hash  # réglages actuels
    assert security.verify_password(user.password_hash, PASSWORD)


def test_journal_des_connexions_sans_mot_de_passe(client, user, session):
    login(client, password="mauvais-mot-de-passe")
    login(client)
    attempts = session.scalars(select(models.AuthAttempt).where(models.AuthAttempt.email == EMAIL)).all()

    assert [(a.kind, a.success, a.ip) for a in attempts] == [("login", False, "testclient"), ("login", True, "testclient")]
    assert not any(PASSWORD in str(vars(a)) for a in attempts)


def test_afflux_de_connexions_503(client, user, monkeypatch):
    import threading

    monkeypatch.setattr(security, "_slots", threading.BoundedSemaphore(1))
    security._slots.acquire()
    assert login(client).status_code == 503


# --- Compte connecté, déconnexion, expiration ---


def test_sans_connexion_401(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Connexion requise"}


@pytest.mark.parametrize("token", ["faux-jeton", "", "x" * 10_000, "a\x00b"])
def test_jeton_invente_refuse(client, token):
    client.cookies.set("session", token)
    assert client.get("/me").status_code == 401


def test_deconnexion(client, user, session):
    login(client)
    token = client.cookies["session"]
    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert 'session=""' in response.headers["set-cookie"] or "max-age=0" in response.headers["set-cookie"].lower()
    assert sessions_of(session, user) == []
    # Même si quelqu'un avait copié le jeton, il ne vaut plus rien.
    client.cookies.set("session", token)
    assert client.get("/me").status_code == 401


def test_deconnexion_sans_session(client):
    assert client.post("/auth/logout").status_code == 204


@pytest.mark.parametrize(("column", "age"), [("last_seen_at", timedelta(days=8)), ("created_at", timedelta(days=31))])
def test_session_expiree(client, user, session, column, age):
    login(client)
    [stored] = sessions_of(session, user)
    setattr(stored, column, datetime.now(UTC) - age)
    session.flush()

    assert client.get("/me").status_code == 401
    assert sessions_of(session, user) == []  # supprimée au passage


def test_activite_repousse_l_expiration(client, user, session):
    login(client)
    [stored] = sessions_of(session, user)
    stored.last_seen_at = datetime.now(UTC) - timedelta(days=6)
    session.flush()

    assert client.get("/me").status_code == 200
    session.refresh(stored)
    assert stored.last_seen_at > datetime.now(UTC) - timedelta(minutes=1)


def test_suppression_du_compte_supprime_ses_sessions(client, user, session):
    login(client)
    session.delete(user)
    session.flush()
    assert client.get("/me").status_code == 401


# --- Limitation des essais ---


def test_cinq_echecs_bloquent_meme_le_bon_mot_de_passe(client, user):
    for _ in range(5):
        assert login(client, password="mauvais-mot-de-passe").status_code == 401
    response = login(client)

    assert response.status_code == 429
    assert response.json() == {"detail": "Trop d'essais de connexion. Réessayez dans 15 minutes."}
    assert response.headers["retry-after"] == "900"


def test_vingt_echecs_par_adresse_ip(client, user, session):
    for i in range(20):
        session.add(models.AuthAttempt(kind="login", ip="testclient", email=f"autre{i}@example.fr", success=False))
    session.flush()
    assert login(client).status_code == 429


def test_cinquante_echecs_sur_un_compte_depuis_plusieurs_adresses(client, user, session):
    for i in range(50):
        session.add(models.AuthAttempt(kind="login", ip=f"10.0.0.{i}", email=EMAIL, success=False))
    session.flush()
    assert login(client).status_code == 429


def test_les_echecs_d_une_autre_adresse_ne_bloquent_pas(client, user, session):
    failures(session, 10, ip="10.0.0.1")  # attaque depuis une autre adresse, sous le seuil par compte
    assert login(client).status_code == 200


def test_les_vieux_echecs_ne_comptent_plus(client, user, session):
    failures(session, 5)
    for attempt in session.scalars(select(models.AuthAttempt)):
        attempt.attempted_at = datetime.now(UTC) - timedelta(minutes=16)
    session.flush()
    assert login(client).status_code == 200


def test_dix_inscriptions_par_heure_et_par_adresse(client):
    for i in range(10):
        assert client.post("/auth/register", json={"email": f"n{i}@example.fr", "password": PASSWORD}).status_code == 202
    response = client.post("/auth/register", json={"email": "n10@example.fr", "password": PASSWORD})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"


# --- CSRF : requêtes qui modifient des données venant d'un autre site ---


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://site-pirate.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}],
)
@pytest.mark.parametrize("path", ["/auth/login", "/auth/logout", "/auth/register"])
def test_requete_d_un_autre_site_refusee(client, user, headers, path):
    response = client.post(path, json={"email": EMAIL, "password": PASSWORD}, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Requête refusée : origine non autorisée"}


@pytest.mark.parametrize(
    "headers", [{"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}, {}]  # le site ; une appli mobile
)
def test_requete_du_site_ou_d_une_appli_acceptee(client, user, headers):
    assert login(client, **headers).status_code == 200


def test_lecture_depuis_un_autre_site_non_bloquee(client):
    # Les GET ne modifient rien : le CORS suffit (le navigateur cache la réponse à l'autre site).
    assert client.get("/me", headers={"Origin": "https://site-pirate.example"}).status_code == 401  # pas 403


def test_au_plus_dix_sessions_par_compte(user, session, monkeypatch):
    # Sans limite, un compte pourrait créer des millions de sessions en se connectant en boucle.
    monkeypatch.setattr(auth, "MAX_SESSIONS_PER_USER", 3)
    devices = [TestClient(app) for _ in range(5)]
    for device in devices:
        assert login(device).status_code == 200

    assert len(sessions_of(session, user)) == 3
    assert [d.get("/me").status_code for d in devices] == [401, 401, 200, 200, 200]  # les plus anciennes coupées
