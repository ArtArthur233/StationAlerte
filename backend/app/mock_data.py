# DONNÉES FICTIVES : stations inventées pour le prototype, aucune n'existe réellement.
# Depuis la V3, l'API sert les vraies données : ce module ne sert plus qu'aux tests (jeu d'essai hors ligne).
from datetime import UTC, datetime, timedelta

from app.schemas import Station


def hours_ago(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


# Fonction et non constante : les dates sont recalculées à chaque appel pour que la démo ne vieillisse pas.
def get_mock_stations() -> list[Station]:
    return [
        Station(
            id="demo-1",
            name="Station Démo du Centre",
            address="12 rue Imaginaire",
            postal_code="69001",
            city="Lyon",
            latitude=45.767,
            longitude=4.834,
            fuels=[
                {"type": "GAZOLE", "status": "AVAILABLE", "updated_at": hours_ago(1), "price": 1.789},
                {"type": "E10", "status": "UNAVAILABLE", "updated_at": hours_ago(3)},
                {"type": "SP98", "status": "AVAILABLE", "updated_at": hours_ago(1)},
            ],
        ),
        Station(
            id="demo-2",
            name="Relais Fictif des Quais",
            address="4 quai de l’Exemple",
            postal_code="33000",
            city="Bordeaux",
            latitude=44.841,
            longitude=-0.570,
            fuels=[
                {"type": "GAZOLE", "status": "UNAVAILABLE", "updated_at": hours_ago(5)},
                {"type": "E85", "status": "AVAILABLE", "updated_at": hours_ago(2)},
                {"type": "GPLC", "status": "UNKNOWN", "updated_at": None},
            ],
        ),
        Station(
            id="demo-3",
            name="Aire Test de l’Autoroute",
            address="Aire de Démonstration, A0",
            postal_code="21000",
            city="Dijon",
            fuels=[
                {"type": "GAZOLE", "status": "AVAILABLE", "updated_at": hours_ago(120)},  # ancienne → affichée inconnue
                {"type": "SP95", "status": "AVAILABLE", "updated_at": hours_ago(4)},
                {"type": "E10", "status": "AVAILABLE", "updated_at": hours_ago(4)},
            ],
        ),
        Station(
            id="demo-4",
            name="Station Exemple Saint-Étienne",
            address="8 avenue du Prototype",
            postal_code="42000",
            city="Saint-Étienne",
            fuels=[
                {"type": "SP98", "status": "UNKNOWN", "updated_at": None},
                {"type": "E10", "status": "AVAILABLE", "updated_at": hours_ago(6)},
            ],
        ),
    ]
