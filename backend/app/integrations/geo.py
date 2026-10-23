# Communes de France : API Géo de l'État (geo.api.gouv.fr), gratuite, sans clé, Licence Ouverte.
# Sert à zoomer la carte sur la ville cherchée. Seul fichier qui connaît le format de cette API.
import logging
from functools import lru_cache

import httpx

GEO_URL = "https://geo.api.gouv.fr/communes"

logger = logging.getLogger(__name__)

# (nom, (sud, ouest, nord, est)) : la « bbox » est le plus petit rectangle qui contient la commune.
Commune = tuple[str, tuple[float, float, float, float]]


def parse_communes(data: list[dict]) -> list[Commune]:
    communes = []
    for commune in data:
        lons, lats = zip(*commune["bbox"]["coordinates"][0])  # GeoJSON écrit [longitude, latitude]
        communes.append((commune["nom"], (min(lats), min(lons), max(lats), max(lons))))
    return communes


# Une même ville cherchée plusieurs fois = un seul appel. Les erreurs (exceptions) ne sont pas mises en cache.
@lru_cache(maxsize=1000)
def _fetch(params: tuple[tuple[str, str], ...]) -> list[Commune]:
    response = httpx.get(GEO_URL, params=dict(params) | {"fields": "nom,bbox"}, timeout=5)
    response.raise_for_status()
    return parse_communes(response.json())


def is_postal_code(query: str) -> bool:
    return len(query) == 5 and query.isdigit()


def search_communes(query: str) -> list[Commune]:
    # Un code postal peut couvrir plusieurs communes ; un nom : les 5 communes ressemblantes les plus peuplées.
    if is_postal_code(query):
        params = (("codePostal", query),)
    else:
        params = (("nom", query), ("boost", "population"), ("limit", "5"))
    try:
        return _fetch(params)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        # API injoignable ou réponse inattendue : la carte se cadrera sur les stations trouvées, rien de grave.
        logger.exception("Échec de la recherche de commune")
        return []
