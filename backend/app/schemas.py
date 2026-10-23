# Schémas Pydantic : la forme des données échangées par l'API (miroir de frontend/src/types/station.ts).
import unicodedata
from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, SecretStr
from pydantic.alias_generators import to_camel

# AUTRE = fourre-tout pour un carburant que StationAlerte ne connaît pas encore (son nom est dans label).
# Ajouter une valeur ici demande une migration écrite à la main (contraintes CHECK, voir models.py).
FuelType = Literal["GAZOLE", "SP95", "E10", "SP98", "E85", "GPLC", "AUTRE"]

# Trois états seulement : une donnée absente n'est JAMAIS « indisponible ».
AvailabilityStatus = Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]


class CamelModel(BaseModel):
    # snake_case en Python, camelCase dans le JSON : le frontend garde ses noms (postalCode, updatedAt).
    # from_attributes : FastAPI peut convertir directement les objets lus en base (app/models.py).
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class FuelInfo(CamelModel):
    type: FuelType
    label: str | None = Field(default=None, max_length=50)  # nom donné par le flux, seulement pour AUTRE
    status: AvailabilityStatus
    updated_at: datetime | None  # None si jamais renseignée ; une date mal formée est refusée
    # Prix au litre en euros, à la date updated_at ; None si le flux n'en donne pas (toujours le cas en rupture).
    price: float | None = Field(default=None, gt=0, lt=1000)


class Station(CamelModel):
    # Mêmes limites que les colonnes de la base : une station hors limites est refusée dès la lecture du flux.
    id: str = Field(min_length=1, max_length=20)
    name: str
    address: str
    postal_code: str = Field(max_length=5)
    city: str
    fuels: list[FuelInfo]
    # Position GPS en degrés (pour la carte) ; None si la source ne la donne pas.
    latitude: float | None = None
    longitude: float | None = None


# Rectangle (en degrés) qui contient une ville : la carte zoome dessus.
class CityBounds(CamelModel):
    south: float
    west: float
    north: float
    east: float


# Version allégée pour la carte : toutes les stations d'un coup, donc sans les carburants.
class StationPosition(CamelModel):
    id: str
    name: str
    address: str
    postal_code: str
    city: str
    latitude: float
    longitude: float


# --- Comptes (V5) ---

def _nfkc(value: object) -> object:
    # Formes « sosies » ramenées à la forme courante AVANT la validation : « Ａlice » (A pleine largeur des
    # claviers asiatiques) = « Alice », « ﬁ » (ligature) = « fi ». Sinon, deux comptes presque identiques.
    return unicodedata.normalize("NFKC", value) if isinstance(value, str) else value


# E-mail normalisé, validé (format, longueur ≤ 254), puis mis en minuscules : « Alice@Mail.fr » = « alice@mail.fr ».
Email = Annotated[EmailStr, BeforeValidator(_nfkc), AfterValidator(str.lower)]


class RegisterRequest(CamelModel):
    email: Email
    # 12 caractères minimum (la longueur protège mieux que « une majuscule obligatoire ») ; 128 au maximum
    # pour qu'on ne puisse pas faire calculer Argon2 sur un « mot de passe » de 10 Mo.
    # SecretStr : affiché « ********** » si on l'écrit par erreur dans un journal.
    password: SecretStr = Field(min_length=12, max_length=128)


class LoginRequest(CamelModel):
    email: Email
    # Pas de minimum de 12 ici : si la règle change un jour, les anciens comptes doivent pouvoir se connecter.
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordResetRequest(CamelModel):
    email: Email


class PasswordResetConfirm(CamelModel):
    token: str = Field(min_length=1, max_length=100)  # jeton du lien reçu par e-mail (43 caractères)
    password: SecretStr = Field(min_length=12, max_length=128)  # mêmes règles qu'à l'inscription


class EmailConfirmation(CamelModel):
    token: str = Field(min_length=1, max_length=100)  # jeton du lien de confirmation (43 caractères)


class AccountDeletion(CamelModel):
    password: SecretStr = Field(min_length=1, max_length=128)  # redemandé : une session volée ne suffit pas


class Unsubscribe(CamelModel):
    token: str = Field(min_length=1, max_length=100)  # jeton du lien de l'e-mail d'alerte (43 caractères)


class UserPublic(CamelModel):
    """Ce qu'on renvoie d'un compte : jamais le mot de passe ni son empreinte."""

    id: int
    email: str
    notify_unavailable: bool
    notify_available: bool


class NotificationPrefs(CamelModel):
    """Événements qui déclencheront un e-mail (envois en V7). Les deux champs sont obligatoires : PUT remplace tout."""

    notify_unavailable: bool  # disponible → indisponible
    notify_available: bool  # indisponible → disponible


class FavoriteStation(Station):
    """Station favorite, avec les carburants que l'utilisateur surveille (vide = aucune alerte)."""

    watched_fuels: list[FuelType]


class WatchedFuels(CamelModel):
    # Au plus un de chaque : la liste ne peut pas grossir sans limite.
    fuels: list[FuelType] = Field(max_length=len(get_args(FuelType)))


class AlertPublic(CamelModel):
    """Une alerte de l'historique « Mes dernières alertes » (V7.2) : le changement et l'état de son envoi."""

    id: int
    created_at: datetime
    status: Literal["pending", "sent", "failed", "expired"]
    sent_at: datetime | None
    station_id: str
    station_name: str
    fuel_type: FuelType
    label: str | None  # nom d'origine si fuel_type = AUTRE
    old_status: AvailabilityStatus
    new_status: AvailabilityStatus
    source_updated_at: datetime | None


# Espace de démonstration (V8) : état voulu pour un carburant de stationTest. NOT_SOLD = la station ne le vend pas.
class DemoFuelChange(CamelModel):
    status: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN", "NOT_SOLD"]


class DemoChangeResult(CamelModel):
    station: Station
    events: int  # changements de disponibilité enregistrés
    alerts: int  # alertes créées (0 si personne ne surveille, ou si le surveillant est arrêté)
    emails_sent: int
    alerts_allowed: bool  # False : surveillant arrêté depuis plus de 20 min, donc aucune alerte (règle V6.2)
