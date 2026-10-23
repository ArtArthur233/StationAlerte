# Intégration de la source officielle « Prix des carburants » (prix-carburants.gouv.fr).
# Seul fichier qui connaît le format du flux : le reste de l'application ne manipule que nos schémas.
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.integrations.osm import load_brands
from app.schemas import FuelInfo, FuelType, Station

FEED_URL = "https://donnees.roulez-eco.fr/opendata/instantane_ruptures"

logger = logging.getLogger(__name__)

# Une rupture déclarée il y a plus longtemps a sans doute été oubliée par le gérant → UNKNOWN.
RUPTURE_TRUSTED_FOR = timedelta(days=7)

# Les dates du flux sont à l'heure de Paris, sans fuseau : on le précise pour les comparer correctement.
PARIS = ZoneInfo("Europe/Paris")

FUEL_TYPES: dict[str, FuelType] = {
    "Gazole": "GAZOLE",
    "SP95": "SP95",
    "E10": "E10",
    "SP98": "SP98",
    "E85": "E85",
    "GPLc": "GPLC",
}


def parse_date(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=PARIS)


# Le flux donne les degrés multipliés par 100 000 (« 4365100 » = 43,651°).
def parse_coordinate(text: str | None) -> float | None:
    try:
        return float(text) / 100_000 or None  # 0 = position non renseignée
    except (TypeError, ValueError):
        return None


# Prix en euros (« 2.251 ») ; absent, illisible, nul ou aberrant → pas de prix, la station reste lue.
def parse_price(text: str | None) -> float | None:
    try:
        price = float(text)
    except (TypeError, ValueError):
        return None
    return price if 0 < price < 1000 else None  # exclut aussi nan et inf


def parse_fuels(pdv: ET.Element, now: datetime) -> list[FuelInfo]:
    fuels: dict[FuelType, FuelInfo] = {}

    def keep(name: str, status: str, updated_at: datetime, price: float | None = None) -> None:
        if not name:
            return
        # Nom inconnu (carburant ajouté un jour au flux) : catégorie fourre-tout AUTRE, avec son nom d'origine.
        fuel_type, label = (FUEL_TYPES[name], None) if name in FUEL_TYPES else ("AUTRE", name[:50])
        if fuel_type in fuels and fuels[fuel_type].label != label:
            # shortcut: un seul « autre » carburant par station (le flux du 16/10/2026 n'en a aucun) ;
            # les suivants sont ignorés. Passer à une ligne par nom si des stations en déclarent plusieurs.
            return
        fuels[fuel_type] = FuelInfo(type=fuel_type, label=label, status=status, updated_at=updated_at, price=price)

    # Un prix récent = la station a déclaré ce carburant en vente ; la règle des 48 h s'applique ensuite.
    for price in pdv.findall("prix"):
        keep(price.get("nom", ""), "AVAILABLE", parse_date(price.get("maj")), parse_price(price.get("valeur")))
    for rupture in pdv.findall("rupture"):
        # « definitive » = carburant non vendu (pas une panne) ; type vide = déclaration inexploitable.
        if rupture.get("type") != "temporaire":
            continue
        started = parse_date(rupture.get("debut"))
        status = "UNAVAILABLE" if now - started <= RUPTURE_TRUSTED_FOR else "UNKNOWN"
        keep(rupture.get("nom", ""), status, started)
    return list(fuels.values())


# brands : enseignes par identifiant officiel (OpenStreetMap), passées en paramètre pour tester sans fichier.
def parse_feed(zip_bytes: bytes, now: datetime | None = None, brands: dict[str, str] | None = None) -> list[Station]:
    now = now or datetime.now(UTC)
    brands = brands or {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        # ET lit l'encodage (ISO-8859-1) dans l'en-tête du XML : on lui passe des octets, pas du texte.
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    stations: dict[str, Station] = {}  # par identifiant : un doublon dans le flux remplace le précédent
    for pdv in root.findall("pdv"):
        address = pdv.findtext("adresse", "").strip()
        try:
            station = Station(
                id=pdv.get("id"),
                # le flux ne fournit ni nom ni enseigne : on prend celle d'OSM quand elle existe
                name=brands.get(pdv.get("id"), f"Station — {address}"),
                address=address,
                postal_code=pdv.get("cp", ""),
                city=pdv.findtext("ville", "").strip(),
                fuels=parse_fuels(pdv, now),
                latitude=parse_coordinate(pdv.get("latitude")),
                longitude=parse_coordinate(pdv.get("longitude")),
            )
        except (ValueError, TypeError) as error:  # ValidationError est une ValueError
            # Une station abîmée (date illisible, identifiant absent…) est ignorée, pas tout le flux :
            # sinon une seule erreur du ministère bloquerait toutes les mises à jour.
            logger.warning("Station %s ignorée, illisible dans le flux : %s", pdv.get("id"), error)
            continue
        stations[station.id] = station
    return list(stations.values())


def fetch_stations() -> list[Station]:
    response = httpx.get(FEED_URL, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return parse_feed(response.content, brands=load_brands())
