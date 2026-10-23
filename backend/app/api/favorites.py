# Stations favorites du compte connecté (V5.3) et carburants surveillés dans chacune (V5.4).
# Droits : l'utilisateur vient TOUJOURS de la session, jamais de l'adresse (« /me/… ») : impossible de
# lire ou modifier les favoris de quelqu'un d'autre, même en changeant l'URL.
from collections import defaultdict
from datetime import UTC, datetime
from typing import get_args

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import models
from app.api.auth import CurrentSession, Db
from app.schemas import FavoriteStation, FuelType, Station, WatchedFuels
from app.test_station import TEST_STATION_ID

router = APIRouter(prefix="/me/favorites", tags=["favoris"])

# Au-delà, un compte pourrait remplir la base ; largement assez pour suivre ses stations habituelles.
MAX_FAVORITES = 50
FUEL_ORDER = get_args(FuelType)  # carburants surveillés renvoyés dans le même ordre que ceux de la station


def ensure_test_station_favorite(db: Db, user_id: int) -> None:
    """stationTest (station fictive de démonstration) est un favori permanent de chaque compte, dès qu'elle existe :
    rien à chercher pour tester les alertes. Ajoutée à la première lecture des favoris (aussi pour les comptes
    créés avant cette règle) ; elle ne surveille rien tant qu'on ne coche pas « Surveiller »."""
    if db.get(models.Station, TEST_STATION_ID) is None:
        return  # pas de station de test (cas normal hors démonstration)
    db.execute(insert(models.Favorite).values(user_id=user_id, station_id=TEST_STATION_ID, created_at=datetime.now(UTC))
               .on_conflict_do_nothing())  # déjà là (ou deux lectures simultanées) : rien à faire
    db.commit()


@router.get("", response_model=list[FavoriteStation])
def list_favorites(session: CurrentSession, db: Db):
    ensure_test_station_favorite(db, session.user_id)
    watched = defaultdict(list)
    for station_id, fuel_type in db.execute(
        select(models.FavoriteFuel.station_id, models.FavoriteFuel.fuel_type)
        .where(models.FavoriteFuel.user_id == session.user_id)
    ):
        watched[station_id].append(fuel_type)
    stations = db.scalars(
        select(models.Station)
        .join(models.Favorite, models.Favorite.station_id == models.Station.id)
        .where(models.Favorite.user_id == session.user_id)
        .options(selectinload(models.Station.fuels))  # carburants chargés en 1 requête
        # stationTest d'abord (False avant True), puis dans l'ordre d'ajout.
        .order_by(models.Station.id != TEST_STATION_ID, models.Favorite.created_at, models.Station.id)
    ).all()
    return [
        FavoriteStation(
            **Station.model_validate(station).model_dump(),
            watched_fuels=sorted(watched[station.id], key=FUEL_ORDER.index),
        )
        for station in stations
    ]


# PUT et non POST : ajouter deux fois la même station donne le même résultat (pas de doublon, pas d'erreur).
@router.put("/{station_id}", status_code=204)
def add_favorite(station_id: str, session: CurrentSession, db: Db):
    if db.get(models.Station, station_id) is None:
        raise HTTPException(status_code=404, detail="Station introuvable")
    if db.get(models.Favorite, (session.user_id, station_id)) is not None:
        return  # déjà dans les favoris
    count = db.scalar(select(func.count()).select_from(models.Favorite).where(models.Favorite.user_id == session.user_id))
    if count >= MAX_FAVORITES:
        raise HTTPException(status_code=409, detail=f"Limite de {MAX_FAVORITES} stations favorites atteinte.")
    # Heure fixée ici et non par PostgreSQL : now() donne la même heure à toute une transaction.
    db.add(models.Favorite(user_id=session.user_id, station_id=station_id, created_at=datetime.now(UTC)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # deux clics simultanés : la clé primaire a refusé le doublon, le favori existe déjà


@router.delete("/{station_id}", status_code=204)
def remove_favorite(station_id: str, session: CurrentSession, db: Db):
    if station_id == TEST_STATION_ID:
        raise HTTPException(status_code=400, detail="stationTest est un favori permanent : elle sert à essayer les alertes.")
    # Toujours 204 : retirer une station qui n'est pas (ou plus) en favori n'est pas une erreur.
    db.execute(
        delete(models.Favorite).where(models.Favorite.user_id == session.user_id, models.Favorite.station_id == station_id)
    )
    db.commit()


# PUT : la liste envoyée remplace l'ancienne (une liste vide = plus rien de surveillé).
@router.put("/{station_id}/fuels", status_code=204)
def set_watched_fuels(station_id: str, body: WatchedFuels, session: CurrentSession, db: Db):
    ensure_test_station_favorite(db, session.user_id)  # stationTest se surveille même avant la 1re lecture des favoris
    # Verrou sur le favori : deux envois simultanés passent l'un après l'autre (sinon doublon → erreur 500).
    if db.get(models.Favorite, (session.user_id, station_id), with_for_update=True) is None:
        raise HTTPException(status_code=404, detail="Station absente de vos favoris")
    sold = {fuel.type for fuel in db.get(models.Station, station_id).fuels}
    if unsold := [fuel for fuel in body.fuels if fuel not in sold]:
        raise HTTPException(status_code=400, detail=f"Carburant non vendu par cette station : {unsold[0]}")
    db.execute(
        delete(models.FavoriteFuel).where(
            models.FavoriteFuel.user_id == session.user_id, models.FavoriteFuel.station_id == station_id
        )
    )
    for fuel in set(body.fuels):  # set : un carburant envoyé deux fois n'est enregistré qu'une fois
        db.add(models.FavoriteFuel(user_id=session.user_id, station_id=station_id, fuel_type=fuel))
    db.commit()
