"""Connexion à PostgreSQL via SQLAlchemy.

L'URL vient de DATABASE_URL (app/config.py, lue dans backend/.env) : jamais de mot de passe dans le code.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import DATABASE_URL

# pool_pre_ping : vérifie qu'une connexion est vivante avant de la réutiliser.
# connect_timeout : sans lui, une connexion à une base arrêtée bloque indéfiniment (constaté sous Windows).
# Connexions : jusqu'à 40, autant que de fils où FastAPI exécute les routes (réglage par défaut d'anyio).
# Avec moins (15 par défaut), sous la charge les fils en trop attendaient une connexion, et les requêtes
# servies ne pouvaient plus la rendre faute de fil libre : tout se bloquait 30 s (constaté le 17/10/2026).
# PostgreSQL accepte 100 connexions par défaut. pool_timeout : en cas d'attente quand même, 503 après 10 s.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=30,
    pool_timeout=10,
    connect_args={"connect_timeout": 5},
)


# Dépendance FastAPI : une session par requête, fermée automatiquement après la réponse.
def get_db() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
