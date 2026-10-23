# Enseignes des stations (Carrefour, E.Leclerc…) tirées d'OpenStreetMap : le flux officiel n'en fournit pas.
# OSM relie chaque station à l'identifiant officiel par l'étiquette « ref:FR:prix-carburants ».
# Données © les contributeurs d'OpenStreetMap, licence ODbL (https://www.openstreetmap.org/copyright).
#
# Mise à jour du fichier (depuis backend/) : uv run python -m app.integrations.osm
# shortcut: fichier mis à jour à la main ; à automatiser (tâche quotidienne) si les enseignes vieillissent trop.
import json
from functools import cache
from pathlib import Path

import httpx

BRANDS_FILE = Path(__file__).parents[2] / "data" / "osm_brands.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Toutes les stations OSM portant l'identifiant officiel ; « out tags » = sans la géométrie, plus léger.
QUERY = '[out:json][timeout:300];nwr["ref:FR:prix-carburants"];out tags;'


def parse_overpass(data: dict) -> dict[str, str]:
    brands = {}
    for element in data["elements"]:
        tags = element.get("tags", {})
        brand = tags.get("brand", "").strip()
        if brand:
            # Une même station OSM peut porter plusieurs identifiants officiels séparés par « ; ».
            for station_id in tags["ref:FR:prix-carburants"].split(";"):
                brands[station_id.strip()] = brand
    return brands


def download_brands() -> None:
    # Overpass est un serveur bénévole : il exige un User-Agent (ASCII seulement) et refuse les appels trop fréquents.
    response = httpx.post(
        OVERPASS_URL, data={"data": QUERY}, headers={"User-Agent": "StationAlerte/0.1 (student project)"}, timeout=400
    )
    response.raise_for_status()
    brands = parse_overpass(response.json())
    BRANDS_FILE.parent.mkdir(exist_ok=True)
    content = {"licence": "© les contributeurs d'OpenStreetMap, ODbL", "brands": dict(sorted(brands.items()))}
    BRANDS_FILE.write_text(json.dumps(content, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(brands)} enseignes enregistrées dans {BRANDS_FILE}")


# Lu une seule fois par processus : le fichier ne change pas pendant que le serveur tourne.
@cache
def load_brands() -> dict[str, str]:
    if not BRANDS_FILE.exists():
        return {}  # sans fichier, les stations gardent leur nom « Station — adresse »
    return json.loads(BRANDS_FILE.read_text(encoding="utf-8"))["brands"]


if __name__ == "__main__":
    download_brands()
