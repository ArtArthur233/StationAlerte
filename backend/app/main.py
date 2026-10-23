from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app import models
from app.api import alerts, auth, demo, favorites
from app.config import ALLOWED_ORIGINS
from app.database import get_db
from app.integrations.geo import search_communes
from app.schemas import CityBounds, FuelInfo, FuelType, Station, StationPosition
from app.security import Busy
from app.services import find_city_bounds, normalize, search_stations
from app.sync import SourceUnavailable, has_stations, last_import_id

app = FastAPI(title="StationAlerte API", description=(
        "Données officielles prix-carburants.gouv.fr (ministère de l'Économie, Licence Ouverte 2.0), "
        "interprétées par StationAlerte : les disponibilités sont déclarées par les stations. "
        "Enseignes : © les contributeurs d'OpenStreetMap (ODbL)."
    ),
)

# CORS : le navigateur bloque par défaut les appels du site (port 5173) vers l'API (port 8000).
# On autorise uniquement le site en local : lecture, POST pour les comptes, PUT et DELETE pour les favoris (V5).
# allow_credentials : le navigateur peut envoyer le cookie de session avec les appels du site.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_credentials=True,
)
app.include_router(auth.router)
app.include_router(favorites.router)
app.include_router(alerts.router)
app.include_router(demo.router)


# CSRF : un autre site peut faire envoyer une requête par ton navigateur, avec ton cookie. Toute requête qui
# modifie des données (pas GET) venant d'un autre site est refusée. Le navigateur indique l'origine
# (en-tête Origin) et si la requête vient d'un autre site (Sec-Fetch-Site) ; l'attaquant ne peut pas les changer.
# Sans ces en-têtes (curl, un autre programme), pas de cookie volé possible : la requête passe.
@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if (origin is not None and origin not in ALLOWED_ORIGINS) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "Requête refusée : origine non autorisée"})
    return await call_next(request)


# En-têtes de sécurité sur chaque réponse de l'API (V8.3). L'API ne renvoie que du JSON :
# - nosniff : le navigateur ne devine pas un autre type (un JSON piégé ne sera jamais exécuté comme script) ;
# - no-referrer : aucune adresse de page envoyée à d'autres sites ;
# - frame-ancestors 'none' : aucune page de l'API (dont /docs) ne peut être affichée dans le cadre d'un autre site.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


# Erreur 422 sans la valeur reçue : par défaut, FastAPI recopie l'entrée refusée dans la réponse,
# donc un mot de passe trop court se retrouverait en clair dans la réponse (et dans les journaux).
@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
# Compression gzip : les positions de ~9 800 stations passent de 1,5 Mo à environ 400 Ko.
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Aucune donnée encore importée (surveillant jamais lancé, ou source en panne depuis le début) : 503.
# Jamais de données fictives à la place : elles seraient prises pour des vraies.
@app.exception_handler(SourceUnavailable)
def source_unavailable(request: Request, exc: SourceUnavailable):
    return JSONResponse(status_code=503, content={"detail": "Source de données indisponible"})


# Base PostgreSQL arrêtée ou injoignable : 503 aussi, avec un message distinct pour savoir quoi relancer.
@app.exception_handler(OperationalError)
def database_unavailable(request: Request, exc: OperationalError):
    return JSONResponse(status_code=503, content={"detail": "Base de données indisponible"})


# Aucune connexion à la base libérée à temps (afflux de visiteurs) : « occupé » (503), pas une panne (500).
@app.exception_handler(PoolTimeoutError)
def database_busy(request: Request, exc: PoolTimeoutError):
    return JSONResponse(
        status_code=503, content={"detail": "Serveur occupé, réessayez dans un instant"}, headers={"Retry-After": "5"}
    )


# Afflux d'inscriptions : on refuse tout de suite plutôt que de bloquer le reste du site (voir security.py).
@app.exception_handler(Busy)
def busy(request: Request, exc: Busy):
    return JSONResponse(
        status_code=503, content={"detail": "Serveur occupé, réessayez dans un instant"}, headers={"Retry-After": "1"}
    )


# Valeur refusée par PostgreSQL (ex. octet nul « \x00 » dans une recherche ou un identifiant) : c'est la
# requête qui est invalide, pas le serveur qui plante → 400 au lieu de 500.
@app.exception_handler(DataError)
def invalid_value(request: Request, exc: DataError):
    return JSONResponse(status_code=400, content={"detail": "Requête invalide"})


# Dépendance des routes /stations… : la session de la base, ou 503 si le surveillant n'a encore rien importé
# (sinon, une liste vide ferait croire qu'il n'y a aucune station). Les tests la remplacent par une base d'essai.
def stations_db(db: Annotated[Session, Depends(get_db)]) -> Session:
    if not has_stations(db):
        raise SourceUnavailable()
    return db


Db = Annotated[Session, Depends(stations_db)]


# response_model : FastAPI valide la réponse et la décrit dans la documentation interactive (/docs).
# q et fuel sont facultatifs. Un carburant inconnu est refusé (erreur 422).
# limit : la France compte près de 10 000 stations, on n'envoie jamais tout au navigateur.
# q limité à 200 caractères : chaque mot ajoute une condition SQL (2 000 mots coûtaient 0,7 s par requête).
# 200 et non 100 : le texte écrit par un clic sur la carte atteint déjà 100 caractères (mesure du 16/10/2026).
@app.get("/stations", response_model=list[Station])
def list_stations(
    db: Db, q: str = Query("", max_length=200), fuel: FuelType | None = None, limit: int = Query(50, ge=1, le=100)
):
    return search_stations(db, q, fuel, limit)


# Rectangle de la ville cherchée, pour zoomer la carte. null (et non 404) si q n'est pas une ville :
# c'est une réponse normale (« leclerc »), pas une erreur.
@app.get("/cities/bounds", response_model=CityBounds | None)
def get_city_bounds(q: str):
    # normalize avant l'appel : l'API Géo ne trouve rien pour « st chamond », mais trouve « saint chamond ».
    return find_city_bounds(q, search_communes(normalize(q)))


# Déclarée avant /stations/{station_id} : sinon FastAPI prendrait « positions » pour un identifiant.
# Les stations sans coordonnées sont absentes de la carte (elles restent trouvables par la recherche).
# Réponse gardée en mémoire jusqu'au prochain import : (version des données, JSON prêt à envoyer).
# Avant : 9 800 stations relues et converties à chaque ouverture de page (300 requêtes simultanées : 24 s).
_positions_cache: tuple[int | None, bytes] | None = None
_positions_json = TypeAdapter(list[StationPosition])


@app.get("/stations/positions", response_model=list[StationPosition])
def list_station_positions(db: Db):
    global _positions_cache
    version = last_import_id(db)  # numéro du dernier import du surveillant
    if _positions_cache is None or _positions_cache[0] != version:
        stations = db.scalars(
            select(models.Station)
            .where(models.Station.latitude.is_not(None), models.Station.longitude.is_not(None))
            .order_by(models.Station.id)
        ).all()
        _positions_cache = (version, _positions_json.dump_json(stations, by_alias=True))
    # Le navigateur peut la réutiliser 5 min : les positions ne changent qu'avec un import (toutes les 10 min).
    return Response(_positions_cache[1], media_type="application/json", headers={"Cache-Control": "max-age=300"})


@app.get("/stations/{station_id}", response_model=Station)
def get_station(station_id: str, db: Db):
    station = db.get(models.Station, station_id)  # lecture par clé primaire : instantanée
    if station is None:
        # 404 = « cette ressource n'existe pas » : le client sait qu'il ne sert à rien de réessayer.
        raise HTTPException(status_code=404, detail="Station introuvable")
    return station


@app.get("/stations/{station_id}/fuels", response_model=list[FuelInfo])
def list_station_fuels(station_id: str, db: Db):
    # On réutilise get_station : la 404 « Station introuvable » vient avec, sans la recopier.
    return get_station(station_id, db).fuels
