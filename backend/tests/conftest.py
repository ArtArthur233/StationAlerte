# Fixtures partagées : pytest les rend disponibles dans tous les fichiers de tests.
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import models
from app.api import auth
from app.database import engine, get_db
from app.main import app
from app.security import hash_password
from app.test_station import TEST_STATION_ID

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def connection():
    # Une seule tentative pour toute la série : base arrêtée = tests de base ignorés en quelques secondes.
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("PostgreSQL ne tourne pas : lancer « docker compose up -d --wait » à la racine")
    yield connection
    connection.close()


@pytest.fixture
def session(connection):
    # Tout se passe dans une transaction annulée à la fin : le test ne laisse rien dans la base.
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()


@pytest.fixture
def outbox(monkeypatch) -> list[dict]:
    # Les e-mails des routes de comptes sont capturés ici au lieu d'être envoyés (même pas vers Mailpit).
    sent = []
    monkeypatch.setattr(auth, "send_email", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}))
    return sent


@pytest.fixture
def api_db(session, monkeypatch, outbox):
    # Les routes écrivent dans la transaction de test, annulée à la fin : aucun compte ne reste en base.
    app.dependency_overrides[get_db] = lambda: session
    # Le travail fait après la réponse (inscription, mot de passe oublié) aussi : sans ça, les tests créaient
    # de vrais comptes dans la base de développement (trouvé en V7.3).
    monkeypatch.setattr(auth, "background_session", lambda: nullcontext(session))
    # La vraie stationTest de la base de dev serait le favori permanent de chaque compte de test : retirée ici
    # (transaction annulée à la fin) ; les tests qui en ont besoin la créent.
    session.execute(delete(models.Station).where(models.Station.id == TEST_STATION_ID))
    yield
    app.dependency_overrides.clear()


# Deux comptes connectés (chacun son navigateur, donc son cookie) pour vérifier que chacun ne touche qu'à ses données.
def logged_in_client(session, email: str) -> TestClient:
    session.add(models.User(email=email, password_hash=hash_password(PASSWORD), email_verified_at=datetime.now(UTC)))
    session.flush()
    client = TestClient(app)
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return client


@pytest.fixture
def alice(session, api_db) -> TestClient:
    return logged_in_client(session, "alice@example.fr")


@pytest.fixture
def camille(session, api_db) -> TestClient:
    return logged_in_client(session, "camille@example.fr")
