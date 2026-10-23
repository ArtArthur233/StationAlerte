# Données de démonstration : un compte prêt à l'emploi pour découvrir StationAlerte en local, sans rien créer
# à la main. Tout est réel sauf « stationTest », la station fictive de test (déjà signalée comme telle sur le site) :
# l'alerte du compte vient d'un vrai passage du surveillant, sur un vrai changement de cette station.
# Jamais en production : le mot de passe est écrit ici et dans la documentation.
#
#   uv run python -m app.demo creer       créer (ou recréer) le compte de démonstration et son alerte
#   uv run python -m app.demo supprimer   supprimer le compte de démonstration
import argparse
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import models, test_station
from app.config import FRONTEND_URL
from app.security import hash_password
from app.services import search_stations

DEMO_EMAIL = "demo@test.fr"  # domaine de test : rien ne part ailleurs que dans Mailpit
DEMO_PASSWORD = "demo-stationalerte"
DEMO_AREA = "42000"  # Saint-Étienne, là où se trouve stationTest
TEST_STATION_FUELS = ["GAZOLE", "E10"]


def real_stations_nearby(db: Session, count: int = 2) -> dict[str, list[str]]:
    """Quelques vraies stations près de stationTest, avec des informations récentes : identifiant → carburants."""
    fresh_after = datetime.now(UTC) - timedelta(hours=48)
    picked = {}
    for station in search_stations(db, DEMO_AREA, limit=200):
        recent = [fuel.type for fuel in station.fuels
                  if fuel.status == "AVAILABLE" and fuel.updated_at and fuel.updated_at > fresh_after]
        if station.id != test_station.TEST_STATION_ID and len(recent) >= 2:
            picked[station.id] = recent[:2]
        if len(picked) == count:
            break
    return picked


def delete_account(db: Session) -> bool:
    # Favoris, carburants surveillés, sessions et alertes partent avec le compte (ON DELETE CASCADE).
    return db.execute(delete(models.User).where(models.User.email == DEMO_EMAIL)).rowcount > 0


def create_account(db: Session, favorites: dict[str, list[str]]) -> models.User:
    """(Re)crée le compte de démonstration : confirmé, alertes activées, favoris et carburants surveillés."""
    delete_account(db)
    now = datetime.now(UTC)
    user = models.User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD), email_verified_at=now,
                       notify_unavailable=True, notify_available=True)
    db.add(user)
    db.flush()  # pour obtenir user.id
    for position, (station_id, fuels) in enumerate(favorites.items()):
        # Dates croissantes : les favoris s'affichent dans l'ordre donné (tri par date d'ajout).
        db.add(models.Favorite(user_id=user.id, station_id=station_id, created_at=now + timedelta(seconds=position)))
        db.flush()
        db.add_all(models.FavoriteFuel(user_id=user.id, station_id=station_id, fuel_type=fuel) for fuel in fuels)
    db.flush()
    return user


def set_test_station(changes: dict[str, str]) -> None:
    path = test_station.TEST_STATION_PATH
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else test_station.DEFAULT_STATION
    station = test_station.update(current, changes)
    path.write_text(json.dumps(station, ensure_ascii=False, indent=2), encoding="utf-8")


def create() -> None:
    from app import sync
    from app.alert_emails import send_pending_alerts
    from app.database import engine

    # 1. stationTest avec ses carburants disponibles, puis un vrai passage : la station est en base,
    #    et ce passage sert de « passage précédent » pour la règle « surveillant arrêté → pas d'alerte ».
    print("1/3 Passage du surveillant avec stationTest disponible (télécharge le vrai flux)…")
    # Retirer puis remettre : la date repart de maintenant (sinon un ancien « disponible » s'afficherait « Inconnu »).
    set_test_station({fuel: test_station.REMOVE for fuel in TEST_STATION_FUELS})
    set_test_station({fuel: "AVAILABLE" for fuel in TEST_STATION_FUELS})
    sync.import_feed()

    # 2. Le compte, créé APRÈS ce passage : il ne reçoit pas d'alerte pour un changement plus ancien que lui.
    print("2/3 Compte de démonstration…")
    with Session(engine) as db, db.begin():
        favorites = {test_station.TEST_STATION_ID: TEST_STATION_FUELS, **real_stations_nearby(db)}
        create_account(db, favorites)

    # 3. Rupture de gazole sur stationTest, puis un second passage : vrai changement → vraie alerte → e-mail.
    print("3/3 Rupture de gazole sur stationTest, second passage…")
    set_test_station({"GAZOLE": "UNAVAILABLE"})
    result = sync.import_feed()
    with Session(engine) as db:
        sent = send_pending_alerts(db)

    print(f"\nCompte de démonstration prêt ({len(favorites)} favoris, {result.alerts} alerte(s), {sent.sent} e-mail(s) envoyé(s)).")
    print(f"  Site     : {FRONTEND_URL}  →  « Se connecter »")  # 5173 (npm run dev) ou 4173 (Docker)
    print(f"  E-mail   : {DEMO_EMAIL}")
    print(f"  Mot de passe : {DEMO_PASSWORD}")
    print("  E-mails  : http://localhost:8025 (Mailpit)")
    if not result.alerts:
        print("Aucune alerte créée : le surveillant était-il arrêté depuis plus de 20 min ? Relance la commande.")


def remove() -> None:
    from app.database import engine

    with Session(engine) as db, db.begin():
        deleted = delete_account(db)
    print("Compte de démonstration supprimé." if deleted else "Pas de compte de démonstration.")
    print("stationTest est gardée (elle sert aussi aux tests) : uv run python -m app.test_station supprimer pour la retirer.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.demo", description="Compte de démonstration (local uniquement).")
    parser.add_argument("command", choices=["creer", "supprimer"])
    logging.basicConfig(level=logging.WARNING)
    if parser.parse_args().command == "creer":
        create()
    else:
        remove()


if __name__ == "__main__":
    main()
