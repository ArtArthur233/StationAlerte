# Modèles SQLAlchemy : la forme des tables PostgreSQL (miroir de app/schemas.py).
# Toute modification ici demande une nouvelle migration Alembic.
from datetime import datetime
from typing import get_args

from sqlalchemy import (
    CheckConstraint, DateTime, Numeric, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, case, false, func, text, true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.schemas import AvailabilityStatus, FuelType


def allowed_values(column: str, literal) -> str:
    # Réutilise les valeurs des schémas Pydantic : une seule liste à maintenir.
    values = ", ".join(f"'{value}'" for value in get_args(literal))
    return f"{column} IN ({values})"


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # identifiant officiel du flux
    name: Mapped[str]
    address: Mapped[str]
    postal_code: Mapped[str] = mapped_column(String(5))
    city: Mapped[str]
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    # Enseigne, adresse, code postal et ville passés par normalize : la recherche SQL compare des textes déjà
    # sans accents ni majuscules, sans réimplémenter normalize en SQL.
    search_text: Mapped[str]

    fuels: Mapped[list["Fuel"]] = relationship(
        back_populates="station",
        cascade="all, delete-orphan",
        # Toujours le même ordre (celui de FuelType : Gazole, SP95, E10…), quel que soit l'ordre d'insertion.
        order_by=lambda: case({fuel: rank for rank, fuel in enumerate(get_args(FuelType))}, value=Fuel.type),
    )


class Fuel(Base):
    __tablename__ = "fuels"
    __table_args__ = (
        # La base elle-même refuse un 4e état : la règle des trois états ne dépend pas que du code.
        CheckConstraint(allowed_values("status", AvailabilityStatus), name="fuel_status_allowed"),
        CheckConstraint(allowed_values("type", FuelType), name="fuel_type_allowed"),
        # Sans date, on ne peut rien affirmer : seul UNKNOWN est permis (une donnée absente n'est jamais UNAVAILABLE).
        CheckConstraint("status = 'UNKNOWN' OR updated_at IS NOT NULL", name="fuel_status_dated"),
        # Un carburant AUTRE a toujours son nom d'origine, les carburants connus jamais.
        CheckConstraint("(type = 'AUTRE') = (label IS NOT NULL)", name="fuel_label_only_for_other"),
        CheckConstraint("price > 0", name="fuel_price_positive"),
    )
    # Attention : --autogenerate ne détecte PAS les changements de CheckConstraint (ex. nouveau carburant
    # dans FuelType). Il faut alors écrire la migration à la main (op.drop_constraint + op.create_check_constraint).

    # Clé primaire composée : une seule ligne par carburant et par station.
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True)
    type: Mapped[str] = mapped_column(String(10), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(50))  # nom d'origine d'un carburant AUTRE
    status: Mapped[str] = mapped_column(String(15))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None = jamais renseignée
    # 3 décimales comme le flux (2,251 €) ; lu en float, comme le schéma Pydantic.
    price: Mapped[float | None] = mapped_column(Numeric(6, 3, asdecimal=False))

    station: Mapped[Station] = relationship(back_populates="fuels")


class AvailabilityEvent(Base):
    """Changement de statut d'un carburant, détecté en comparant deux imports successifs (lu par les alertes V7)."""

    __tablename__ = "availability_events"
    __table_args__ = (
        CheckConstraint(allowed_values("old_status", AvailabilityStatus), name="event_old_status_allowed"),
        CheckConstraint(allowed_values("new_status", AvailabilityStatus), name="event_new_status_allowed"),
        CheckConstraint(allowed_values("fuel_type", FuelType), name="event_fuel_type_allowed"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)  # numéro auto-incrémenté par PostgreSQL
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"))
    fuel_type: Mapped[str] = mapped_column(String(10))
    label: Mapped[str | None] = mapped_column(String(50))  # nom d'origine si fuel_type = AUTRE
    old_status: Mapped[str] = mapped_column(String(15))
    new_status: Mapped[str] = mapped_column(String(15))
    # Date du nouveau statut selon la source (None si inconnue) ≠ moment où StationAlerte l'a remarqué.
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # now() = début de la transaction : tous les événements d'un même import ont la même heure.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedImport(Base):
    """Import réussi du flux officiel (une ligne par vérification du surveillant, V6).
    Sert à savoir quand vérifier à nouveau, et à l'API pour savoir que les données ont changé."""

    __tablename__ = "feed_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    station_count: Mapped[int]


# --- Comptes (tables créées en V4.5, remplies par V5). Le serveur vérifiera qu'un utilisateur ne lit
# et ne modifie que ses propres lignes ; les clés étrangères ci-dessous empêchent déjà les incohérences.


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Stocké en minuscules : « Alice@Mail.fr » et « alice@mail.fr » sont le même compte.
        CheckConstraint("email = lower(email)", name="user_email_lowercase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # 254 = longueur maximale d'une adresse
    # Jamais le mot de passe : seulement son empreinte (hash), calculée en V5.
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Préférences de notification (une seule par utilisateur, donc des colonnes plutôt qu'une table) :
    # disponible → indisponible activé par défaut, retour à la disponibilité en option.
    notify_unavailable: Mapped[bool] = mapped_column(server_default=true())
    notify_available: Mapped[bool] = mapped_column(server_default=false())
    # None tant que l'adresse n'est pas confirmée par le lien de l'e-mail (V7.3) : pas de connexion ni d'alerte.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Favorite(Base):
    __tablename__ = "favorites"

    # Clé composée : une station n'est qu'une fois dans les favoris d'un même utilisateur.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FavoriteFuel(Base):
    """Carburant surveillé dans une station favorite (préférence de surveillance)."""

    __tablename__ = "favorite_fuels"
    __table_args__ = (
        # Pointe sur le favori, pas sur la station : impossible de surveiller hors de ses favoris,
        # et retirer un favori retire ses carburants surveillés.
        ForeignKeyConstraint(
            ["user_id", "station_id"], ["favorites.user_id", "favorites.station_id"], ondelete="CASCADE"
        ),
        CheckConstraint(allowed_values("fuel_type", FuelType), name="favorite_fuel_type_allowed"),
    )

    user_id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    fuel_type: Mapped[str] = mapped_column(String(10), primary_key=True)


class Alert(Base):
    """Alerte à envoyer à un compte pour un changement de disponibilité (créée par le surveillant, V6 ;
    envoyée par e-mail en V7). Une seule par compte et par changement : jamais deux e-mails pour le même."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="alert_once_per_event"),
        # pending : à envoyer ; sent : accepté par le serveur d'e-mails ; failed : 5 essais ratés ;
        # expired : pas envoyée à temps (plus de 2 h), l'information est peut-être déjà fausse.
        CheckConstraint("status IN ('pending', 'sent', 'failed', 'expired')", name="alert_status_allowed"),
        # Les alertes à envoyer sont cherchées à chaque passage : index limité à celles-là (petit et rapide).
        Index("alerts_pending", "user_id", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[int] = mapped_column(ForeignKey("availability_events.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(server_default="0")  # essais d'envoi ratés
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))  # pour comprendre un échec (jamais de secret)


class UserSession(Base):
    """Session de connexion. Le jeton lui-même n'est jamais stocké : seulement son empreinte SHA-256,
    pour qu'une copie de la table ne permette pas de se connecter."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 en hexadécimal
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()


class AuthAttempt(Base):
    """Journal des connexions et inscriptions (réussies ou non), qui sert aussi à limiter les essais.
    Jamais de mot de passe ici."""

    __tablename__ = "auth_attempts"
    __table_args__ = (
        CheckConstraint("kind IN ('login', 'register', 'reset', 'confirm')", name="auth_attempt_kind_allowed"),
        # Les limites comptent les essais récents par adresse IP et par e-mail : index pour que ce soit rapide.
        Index("auth_attempts_ip_time", "ip", "attempted_at"),
        Index("auth_attempts_email_time", "email", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    ip: Mapped[str] = mapped_column(String(45))  # 45 = longueur maximale d'une adresse IPv6
    email: Mapped[str] = mapped_column(String(254))
    success: Mapped[bool]
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetToken(Base):
    """Lien de réinitialisation du mot de passe : seule l'empreinte SHA-256 du jeton est stockée.
    Valable 30 minutes, une seule fois (la ligne est supprimée à l'usage)."""

    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailConfirmationToken(Base):
    """Lien de confirmation de l'adresse e-mail (V7.3) : seule l'empreinte SHA-256 du jeton est stockée.
    Valable 24 heures, une seule fois."""

    __tablename__ = "email_confirmation_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnsubscribeToken(Base):
    """Lien « Ne plus recevoir d'alertes » d'un e-mail d'alerte (V7.4) : seule l'empreinte SHA-256 est stockée.
    Valable 60 jours, réutilisable (se désabonner deux fois n'est pas une erreur)."""

    __tablename__ = "unsubscribe_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
