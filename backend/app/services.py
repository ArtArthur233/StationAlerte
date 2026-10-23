# Logique métier : indépendante de FastAPI, donc testable et réutilisable (routes de l'API, surveillant).
import re
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app import models
from app.integrations.geo import Commune, is_postal_code
from app.schemas import CityBounds, FuelType, Station

# Abréviations courantes dans les adresses (« ST CHAMOND », « Ste-Foy ») : remplacées par le mot entier.
# \b = limite de mot : « st » devient « saint », mais « est » ou « stade » ne changent pas.
ABBREVIATIONS = {r"\bst\b": "saint", r"\bste\b": "sainte"}


# « Saint-Étienne », « saint etienne » et « St Etienne » doivent correspondre : on ignore casse, accents,
# tirets et abréviations.
def normalize(text: str) -> str:
    without_accents = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    result = without_accents.replace("-", " ").lower().strip()
    for abbreviation, word in ABBREVIATIONS.items():
        result = re.sub(abbreviation, word, result)
    return result


def search_text(station: Station) -> str:
    return normalize(f"{station.name} {station.address} {station.postal_code} {station.city}")


def search_stations(
    session: Session, query: str = "", fuel_type: FuelType | None = None, limit: int = 50
) -> list[models.Station]:
    statement = (
        select(models.Station)
        .options(selectinload(models.Station.fuels))  # carburants chargés en 1 requête, pas 1 par station
        .order_by(models.Station.id)
        .limit(limit)
    )
    # Chaque mot doit apparaître quelque part : « carrefour lyon » = enseigne Carrefour ET ville Lyon.
    for word in normalize(query).split():
        # autoescape : un « % » ou « _ » tapé par l'utilisateur est cherché tel quel, pas comme joker SQL.
        statement = statement.where(models.Station.search_text.contains(word, autoescape=True))
    if fuel_type is not None:
        statement = statement.where(models.Station.fuels.any(models.Fuel.type == fuel_type))
    return list(session.scalars(statement))


def save_stations(session: Session, stations: list[Station]) -> list[int]:
    """Importe le flux et renvoie les identifiants des changements de disponibilité détectés."""
    # Upsert : insère les nouvelles stations, met à jour celles qui existent (même identifiant officiel).
    rows = [{**station.model_dump(exclude={"fuels"}), "search_text": search_text(station)} for station in stations]
    upsert = insert(models.Station)
    session.execute(
        upsert.on_conflict_do_update(
            index_elements=["id"], set_={column: upsert.excluded[column] for column in rows[0] if column != "id"}
        ),
        rows,
    )
    # Statuts de l'import précédent, lus avant de les effacer, pour détecter les changements.
    previous = {
        (station_id, fuel_type): status
        for station_id, fuel_type, status in session.execute(
            select(models.Fuel.station_id, models.Fuel.type, models.Fuel.status)
        )
    }
    # Les carburants sont remplacés en entier : le flux est un instantané complet.
    # shortcut: une station absente du flux perd ses carburants mais reste en base (et trouvable) ; à revoir
    # si des stations fermées gênent.
    session.execute(delete(models.Fuel))
    fuel_rows = [{"station_id": station.id, **fuel.model_dump()} for station in stations for fuel in station.fuels]
    if fuel_rows:
        session.execute(insert(models.Fuel), fuel_rows)
    # Seuls les carburants présents dans les deux imports comptent : un carburant qui apparaît ou disparaît
    # du flux n'est pas un changement de disponibilité. Base vide (premier import) = aucun événement.
    events = [
        {
            "station_id": row["station_id"],
            "fuel_type": row["type"],
            "label": row["label"],
            "old_status": previous[key],
            "new_status": row["status"],
            "source_updated_at": row["updated_at"],
        }
        for row in fuel_rows
        if (key := (row["station_id"], row["type"])) in previous and previous[key] != row["status"]
    ]
    event_ids = (
        list(session.scalars(insert(models.AvailabilityEvent).returning(models.AvailabilityEvent.id), events))
        if events else []
    )
    session.add(models.FeedImport(station_count=len(stations)))  # validé avec le reste, ou annulé avec lui
    return event_ids


def find_city_bounds(query: str, communes: list[Commune]) -> CityBounds | None:
    q = normalize(query)
    if is_postal_code(q):
        boxes = [box for _, box in communes]  # toutes les communes de ce code postal
    else:
        # L'API Géo est approximative (« lyo » renvoie Lyon, « carrefour » pourrait renvoyer un village) :
        # on ne garde que le nom exact. Entre homonymes, la première = la plus peuplée.
        boxes = [box for name, box in communes if normalize(name) == q][:1]
    if not boxes:
        return None
    south, west, north, east = zip(*boxes)
    return CityBounds(south=min(south), west=min(west), north=max(north), east=max(east))
