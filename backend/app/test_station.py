# Station fictive « stationTest », pour tester en local la surveillance et les alertes sans attendre qu'une
# vraie station change d'état. Elle vit dans data/test_station.json (ignoré par Git) : si ce fichier existe,
# le surveillant l'ajoute au flux officiel à chaque passage, et elle suit le même chemin qu'une vraie station.
# Jamais en production : sans ce fichier, rien ne change.
#
#   uv run python -m app.test_station                              afficher la station
#   uv run python -m app.test_station modifier GAZOLE=rupture E10=dispo [--maintenant]
#   uv run python -m app.test_station supprimer
import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import TEST_STATION_FILE
from app.schemas import AvailabilityStatus, FuelType, Station

logger = logging.getLogger(__name__)
TEST_STATION_PATH = Path(TEST_STATION_FILE) if TEST_STATION_FILE else Path(__file__).resolve().parent.parent / "data" / "test_station.json"
TEST_STATION_ID = "TEST-STATIONTEST"  # les vrais identifiants du flux sont des nombres : pas de collision

# Les deux écritures sont acceptées : « GAZOLE=rupture » ou « GAZOLE=UNAVAILABLE ».
STATUS_NAMES = {
    "dispo": "AVAILABLE", "disponible": "AVAILABLE",
    "rupture": "UNAVAILABLE", "indisponible": "UNAVAILABLE",
    "inconnu": "UNKNOWN",
    **{status.lower(): status for status in get_args(AvailabilityStatus)},
}
REMOVE = "retirer"  # « SP98=retirer » : la station ne vend plus ce carburant
# Prix fictifs (€/L), affichés seulement quand le carburant est disponible : comme dans le vrai flux, une rupture
# n'a jamais de prix. Station signalée comme fictive : ces prix ne peuvent pas passer pour de vrais prix.
FAKE_PRICES = {"GAZOLE": 1.799, "SP95": 1.899, "E10": 1.849, "SP98": 1.949, "E85": 0.899, "GPLC": 0.999}

DEFAULT_STATION = {
    "id": TEST_STATION_ID,
    "name": "stationTest",
    "address": "Station fictive de test",  # affiché sur la fiche : impossible de la prendre pour une vraie
    "postal_code": "42000",
    "city": "Saint-Étienne",
    "latitude": 45.4397,
    "longitude": 4.3872,
    "fuels": [],
}


def load() -> list[Station]:
    """La station fictive à ajouter au flux, ou [] si le fichier n'existe pas (cas normal, et toujours en production)."""
    if not TEST_STATION_PATH.exists():
        return []
    try:
        station = Station.model_validate(json.loads(TEST_STATION_PATH.read_text(encoding="utf-8")))  # vérifié d'abord
        return [Station.model_validate(with_prices(station.model_dump()))]
    except (OSError, ValueError):  # ValueError couvre JSON cassé et station invalide (ValidationError)
        # Un fichier de test abîmé ne doit jamais bloquer la surveillance des vraies stations.
        logger.exception("Station de test ignorée : %s illisible", TEST_STATION_PATH)
        return []


def update(station: dict, changes: dict[str, str], **fields: str | float | None) -> dict:
    """Applique « carburant → statut » (ou « retirer ») et les champs donnés. Renvoie la station modifiée."""
    station = {**station, **{key: value for key, value in fields.items() if value is not None}}
    fuels = {fuel["type"]: fuel for fuel in station["fuels"]}
    now = datetime.now(UTC).isoformat()
    for fuel_type, status in changes.items():
        if status == REMOVE:
            fuels.pop(fuel_type, None)
        elif fuels.get(fuel_type, {}).get("status") != status:
            # Date = moment du changement, comme une vraie déclaration ; sans date, seul UNKNOWN est permis.
            fuels[fuel_type] = {"type": fuel_type, "status": status, "updated_at": None if status == "UNKNOWN" else now}
    station["fuels"] = [fuels[t] for t in get_args(FuelType) if t in fuels]
    station = with_prices(station)
    Station.model_validate(station)  # mêmes vérifications qu'une station du vrai flux
    return station


def with_prices(station: dict) -> dict:
    """Prix fictif pour chaque carburant disponible, aucun sinon (aussi pour un fichier écrit avant les prix)."""
    fuels = [{**fuel, "price": FAKE_PRICES.get(fuel["type"]) if fuel["status"] == "AVAILABLE" else None}
             for fuel in station["fuels"]]
    return {**station, "fuels": fuels}


def apply_now(db: Session, changes: dict[str, str]) -> list[int]:
    """Change stationTest tout de suite, en base et dans son fichier, sans attendre le surveillant (espace de
    démonstration du site). Mêmes règles qu'un import : renvoie les identifiants des changements de disponibilité.
    Le fichier est écrit aussi, sinon le passage suivant du surveillant remettrait l'ancien état."""
    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert

    from app import models
    from app.services import search_text

    row = db.get(models.Station, TEST_STATION_ID, with_for_update=True)  # deux clics simultanés : l'un attend l'autre
    if row is None:
        station = Station.model_validate(DEFAULT_STATION)
        # ON CONFLICT : deux premiers clics simultanés ne créent qu'une station.
        db.execute(insert(models.Station).values(**station.model_dump(exclude={"fuels"}), search_text=search_text(station))
                   .on_conflict_do_nothing())
        row = db.get(models.Station, TEST_STATION_ID, with_for_update=True, populate_existing=True)
    current = Station.model_validate(row).model_dump(mode="json")
    station = Station.model_validate(update(current, changes))

    previous = {fuel.type: fuel.status for fuel in row.fuels}
    db.execute(delete(models.Fuel).where(models.Fuel.station_id == TEST_STATION_ID))
    db.add_all(models.Fuel(station_id=TEST_STATION_ID, **fuel.model_dump()) for fuel in station.fuels)
    # Comme un import : un carburant qui apparaît ou disparaît n'est pas un changement de disponibilité.
    events = [
        models.AvailabilityEvent(station_id=TEST_STATION_ID, fuel_type=fuel.type, label=fuel.label,
                                 old_status=previous[fuel.type], new_status=fuel.status, source_updated_at=fuel.updated_at)
        for fuel in station.fuels if fuel.type in previous and previous[fuel.type] != fuel.status
    ]
    db.add_all(events)
    db.flush()
    db.expire(row, ["fuels"])  # relus depuis la base au prochain accès
    TEST_STATION_PATH.write_text(json.dumps(station.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return [event.id for event in events]


def parse_change(text: str) -> tuple[str, str]:
    fuel, _, status = text.partition("=")
    fuel, status = fuel.strip().upper(), status.strip().lower()
    if fuel not in get_args(FuelType) or fuel == "AUTRE":
        raise argparse.ArgumentTypeError(f"carburant inconnu : {fuel} (choix : GAZOLE, SP95, E10, SP98, E85, GPLC)")
    if status != REMOVE and status not in STATUS_NAMES:
        raise argparse.ArgumentTypeError(f"statut inconnu : {status} (choix : dispo, rupture, inconnu, {REMOVE})")
    return fuel, REMOVE if status == REMOVE else STATUS_NAMES[status]


def show() -> None:
    stations = load()
    if not stations:
        print("Aucune station de test. Pour la créer : uv run python -m app.test_station modifier GAZOLE=dispo")
        return
    station = stations[0]
    print(f"{station.name} ({station.id}) — {station.address}, {station.postal_code} {station.city}")
    for fuel in station.fuels:
        date = fuel.updated_at.astimezone().strftime("%d/%m %H:%M") if fuel.updated_at else "sans date"
        print(f"  {fuel.type:7} {fuel.status:12} {date}")
    print("Le surveillant prendra ces valeurs à son prochain passage (au plus 10 min), ou tout de suite avec --maintenant.")


def remove() -> None:
    from app import models
    from app.database import engine

    TEST_STATION_PATH.unlink(missing_ok=True)
    # La station quitte aussi la base, avec ses favoris, son historique et ses alertes (ON DELETE CASCADE).
    with Session(engine) as db, db.begin():
        if station := db.get(models.Station, TEST_STATION_ID):
            db.delete(station)
    print("Station de test supprimée (fichier et base).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.test_station", description="Station fictive stationTest (tests en local).")
    commands = parser.add_subparsers(dest="command")
    change = commands.add_parser("modifier", help="créer ou modifier la station et le statut de ses carburants")
    change.add_argument("changes", nargs="*", type=parse_change, metavar="CARBURANT=STATUT",
                        help="ex. GAZOLE=rupture E10=dispo SP98=inconnu SP95=retirer")
    change.add_argument("--nom", dest="name")
    change.add_argument("--adresse", dest="address")
    change.add_argument("--code-postal", dest="postal_code")
    change.add_argument("--ville", dest="city")
    change.add_argument("--latitude", type=float)
    change.add_argument("--longitude", type=float)
    change.add_argument("--maintenant", action="store_true",
                        help="lancer tout de suite un passage du surveillant (télécharge le vrai flux, environ 2 s)")
    commands.add_parser("supprimer", help="supprimer la station (fichier et base)")
    args = parser.parse_args()

    if args.command == "supprimer":
        remove()
        return
    if args.command == "modifier":
        current = json.loads(TEST_STATION_PATH.read_text(encoding="utf-8")) if TEST_STATION_PATH.exists() else DEFAULT_STATION
        fields = {key: getattr(args, key) for key in ("name", "address", "postal_code", "city", "latitude", "longitude")}
        station = update(current, dict(args.changes), **fields)
        TEST_STATION_PATH.write_text(json.dumps(station, ensure_ascii=False, indent=2), encoding="utf-8")
    show()
    if args.command == "modifier" and args.maintenant:
        from app import models, sync
        from app.alert_emails import send_pending_alerts
        from app.database import engine

        logging.basicConfig(level=logging.WARNING)
        with Session(engine) as db:
            # Lu AVANT l'import : c'est ce que la règle « surveillant arrêté » va regarder.
            last = db.scalar(select(func.max(models.FeedImport.imported_at)))
        result = sync.import_feed()
        print(f"Passage fait : {result.stations} stations, {result.events} changements, {result.alerts} alertes.")
        with Session(engine) as db:
            sent = send_pending_alerts(db)
        print(f"E-mails : {sent.sent} envoyés, {sent.failed} en échec (à lire sur http://localhost:8025).")
        if not result.alerts:
            print(explain_no_alert(last, datetime.now(UTC)))


def explain_no_alert(last_import: datetime | None, now: datetime) -> str:
    """Pourquoi un passage n'a créé aucune alerte, en clair (la cause la plus fréquente d'abord)."""
    from app.alerts import MAX_GAP

    minutes = int(MAX_GAP.total_seconds() // 60)
    if last_import is None:
        return "0 alerte : c'était le tout premier passage, il n'y avait rien à comparer. Relance --maintenant."
    if now - last_import > MAX_GAP:
        ago = int((now - last_import).total_seconds() // 60)
        return (f"0 alerte : le passage précédent date d'il y a {ago} min (plus de {minutes} min = surveillant arrêté),"
                " donc pas d'alerte pour ce passage. Le changement est enregistré. Relance --maintenant avec"
                " un autre statut : ce passage-là créera les alertes.")
    return ("0 alerte : vérifie que le carburant est coché « Surveiller » dans tes favoris, que la préférence"
            " (« devient indisponible » ou « redevient disponible ») est cochée, et que le statut a vraiment changé.")


if __name__ == "__main__":
    main()
