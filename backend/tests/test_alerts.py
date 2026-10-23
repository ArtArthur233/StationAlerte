# Règles d'alerte (V6.2) : deux imports successifs simulés, puis on regarde quelles alertes ont été créées.
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app import models
from app.schemas import FuelInfo, Station
from app.security import hash_password
from app.sync import save_and_alert

STATION = "TEST-ALERTE"


def feed(status: str, fuel: str = "GAZOLE") -> list[Station]:
    # Flux simulé d'une seule station ; un statut connu a toujours une date (règle des trois états).
    updated_at = None if status == "UNKNOWN" else datetime.now(UTC)
    return [Station(id=STATION, name="Station test", address="1 rue Test", postal_code="42000", city="Saint-Étienne",
                    fuels=[FuelInfo(type=fuel, status=status, updated_at=updated_at)])]


def watcher(session, email: str, fuels=("GAZOLE",), notify_unavailable=True, notify_available=False) -> models.User:
    user = models.User(email=email, password_hash=hash_password("x" * 12), email_verified_at=datetime.now(UTC),
                       notify_unavailable=notify_unavailable, notify_available=notify_available)
    session.add(user)
    session.flush()
    if fuels is not None:  # None = la station n'est même pas en favori
        session.add(models.Favorite(user_id=user.id, station_id=STATION))
        session.flush()
        session.add_all(models.FavoriteFuel(user_id=user.id, station_id=STATION, fuel_type=f) for f in fuels)
        session.flush()
    return user


def alerts_of(session, user: models.User) -> list[tuple[str, str]]:
    rows = session.execute(
        select(models.AvailabilityEvent.old_status, models.AvailabilityEvent.new_status, models.Alert.status)
        .join(models.Alert, models.Alert.event_id == models.AvailabilityEvent.id)
        .where(models.Alert.user_id == user.id)
    ).all()
    assert all(status == "pending" for *_, status in rows)  # en attente d'envoi (V7)
    return [(old, new) for old, new, _ in rows]


@pytest.fixture
def first_import(session):
    """Premier import : la station apparaît. Renvoie une fonction qui fait le second import."""

    def start(status: str):
        save_and_alert(session, feed(status))
        session.flush()

    return start


# --- Les règles ---


@pytest.mark.parametrize(
    ("before", "after", "notify_unavailable", "notify_available", "expected"),
    [
        ("AVAILABLE", "UNAVAILABLE", True, False, True),  # rupture
        ("UNKNOWN", "UNAVAILABLE", True, False, True),  # rupture déclarée après une période sans info
        ("AVAILABLE", "UNAVAILABLE", False, False, False),  # « devient indisponible » décoché
        ("UNAVAILABLE", "AVAILABLE", True, True, True),  # retour, demandé
        ("UNAVAILABLE", "AVAILABLE", True, False, False),  # retour, non demandé (réglage par défaut)
        ("UNKNOWN", "AVAILABLE", True, True, False),  # pas un « retour » : on ne savait pas qu'il manquait
        ("AVAILABLE", "UNKNOWN", True, True, False),  # information absente : jamais d'alerte
        ("UNAVAILABLE", "UNKNOWN", True, True, False),  # rupture de plus de 7 jours : jamais d'alerte
    ],
)
def test_regles_d_alerte(session, first_import, before, after, notify_unavailable, notify_available, expected):
    first_import(before)
    user = watcher(session, "a@test.fr", notify_unavailable=notify_unavailable, notify_available=notify_available)
    result = save_and_alert(session, feed(after))

    assert result.events == 1  # le changement est toujours dans l'historique
    assert alerts_of(session, user) == ([(before, after)] if expected else [])
    assert result.alerts == int(expected)


def test_carburant_non_surveille(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr", fuels=["E10"])  # surveille le E10, pas le Gazole
    save_and_alert(session, feed("UNAVAILABLE"))
    assert alerts_of(session, user) == []


def test_favori_sans_carburant_surveille(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr", fuels=[])  # choix (a) de V5.4 : rien de surveillé par défaut
    save_and_alert(session, feed("UNAVAILABLE"))
    assert alerts_of(session, user) == []


def test_adresse_non_confirmee_pas_d_alerte(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    user.email_verified_at = None  # jamais d'e-mail vers une boîte dont le propriétaire n'a rien confirmé
    session.flush()
    assert save_and_alert(session, feed("UNAVAILABLE")).alerts == 0


def test_station_pas_en_favori(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr", fuels=None)
    save_and_alert(session, feed("UNAVAILABLE"))
    assert alerts_of(session, user) == []


def test_une_alerte_par_compte_concerne(session, first_import):
    first_import("AVAILABLE")
    alice = watcher(session, "alice@test.fr")
    camille = watcher(session, "camille@test.fr")
    other = watcher(session, "autre@test.fr", notify_unavailable=False)
    assert save_and_alert(session, feed("UNAVAILABLE")).alerts == 2

    assert alerts_of(session, alice) == alerts_of(session, camille) == [("AVAILABLE", "UNAVAILABLE")]
    assert alerts_of(session, other) == []


# --- Pas de doublon, pas d'alerte périmée ---


def test_reimport_identique_sans_nouvelle_alerte(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    save_and_alert(session, feed("UNAVAILABLE"))
    result = save_and_alert(session, feed("UNAVAILABLE"))  # rien n'a changé depuis

    assert (result.events, result.alerts) == (0, 0)
    assert len(alerts_of(session, user)) == 1


def test_meme_changement_traite_deux_fois_sans_doublon(session, first_import):
    from app.alerts import create_alerts

    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    save_and_alert(session, feed("UNAVAILABLE"))
    event_ids = list(session.scalars(select(models.Alert.event_id).where(models.Alert.user_id == user.id)))

    assert create_alerts(session, event_ids) == 0  # contrainte alert_once_per_event
    assert len(alerts_of(session, user)) == 1


def test_surveillant_arrete_pas_d_alerte(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    # Dernière vérification il y a 21 min (plus de 2 × 10 min) : le surveillant était arrêté.
    session.execute(update(models.FeedImport).values(imported_at=datetime.now(UTC) - timedelta(minutes=21)))
    result = save_and_alert(session, feed("UNAVAILABLE"))

    assert (result.events, result.alerts) == (1, 0)  # changement enregistré, mais pas d'alerte
    assert alerts_of(session, user) == []


def test_un_echec_de_la_source_n_empeche_pas_les_alertes(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    # Un essai raté puis un nouvel essai 5 min après : 15 min d'écart, sous la limite de 20 min.
    session.execute(update(models.FeedImport).values(imported_at=datetime.now(UTC) - timedelta(minutes=15)))
    assert save_and_alert(session, feed("UNAVAILABLE")).alerts == 1
    assert alerts_of(session, user) == [("AVAILABLE", "UNAVAILABLE")]


def test_compte_supprime_ses_alertes_aussi(session, first_import):
    first_import("AVAILABLE")
    user = watcher(session, "a@test.fr")
    save_and_alert(session, feed("UNAVAILABLE"))
    session.delete(user)
    session.flush()
    assert session.scalars(select(models.Alert).where(models.Alert.user_id == user.id)).all() == []
