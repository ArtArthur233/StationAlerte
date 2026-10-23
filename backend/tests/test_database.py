from datetime import UTC, datetime, timedelta, timezone
from typing import get_args

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.models import AvailabilityEvent, Base, Favorite, FavoriteFuel, Fuel, Station, User
from app.schemas import FuelType
from app.services import save_stations

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def make_station(*fuels: Fuel) -> Station:
    station = Station(id="TEST1", name="Station test", address="1 rue Test", postal_code="42000",
                      city="Saint-Étienne", latitude=45.43, longitude=4.39, search_text="station test")
    station.fuels.extend(fuels)
    return station


def fuel(type="E85", status="AVAILABLE", updated_at=datetime(2026, 10, 16, 12, tzinfo=UTC)) -> Fuel:
    return Fuel(type=type, status=status, updated_at=updated_at)


def reload(session: Session) -> Station:
    session.flush()
    session.expunge_all()  # oublie les objets en mémoire : la lecture suivante interroge vraiment la base
    return session.get(Station, "TEST1")


def test_connexion_postgresql(session):
    assert session.execute(text("SELECT 1")).scalar() == 1


def test_base_a_jour_des_migrations(session):
    # Échoue si on a oublié « uv run alembic upgrade head » après un git pull.
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert MigrationContext.configure(session.connection()).get_current_revision() == head


def test_modeles_et_migrations_concordent(session):
    # Échoue si on a modifié app/models.py sans générer de migration (hors CheckConstraint, non détectées).
    assert compare_metadata(MigrationContext.configure(session.connection()), Base.metadata) == []


def test_enregistre_une_station_et_ses_carburants(session):
    session.add(make_station(fuel()))
    station = reload(session)
    assert station.city == "Saint-Étienne"
    assert [(f.type, f.status) for f in station.fuels] == [("E85", "AVAILABLE")]


def test_conserve_l_instant_exact_des_dates(session):
    paris = timezone(timedelta(hours=2))
    session.add(make_station(fuel(updated_at=datetime(2026, 10, 16, 14, tzinfo=paris))))
    # Même instant, quel que soit le fuseau dans lequel PostgreSQL le renvoie.
    assert reload(session).fuels[0].updated_at == datetime(2026, 10, 16, 12, tzinfo=UTC)


def test_inconnu_sans_date_est_accepte(session):
    session.add(make_station(fuel(status="UNKNOWN", updated_at=None)))
    assert reload(session).fuels[0].updated_at is None


@pytest.mark.parametrize("status", ["AVAILABLE", "UNAVAILABLE"])
def test_la_base_refuse_un_statut_sans_date(session, status):
    session.add(make_station(fuel(status=status, updated_at=None)))
    with pytest.raises(IntegrityError, match="fuel_status_dated"):
        session.flush()


@pytest.mark.parametrize(
    ("bad_fuel", "constraint"),
    [
        (fuel(status="EN_PANNE"), "fuel_status_allowed"),
        (fuel(status="available"), "fuel_status_allowed"),  # la casse compte
        (fuel(type="DIESEL"), "fuel_type_allowed"),
    ],
)
def test_la_base_refuse_une_valeur_inconnue(session, bad_fuel, constraint):
    session.add(make_station(bad_fuel))
    with pytest.raises(IntegrityError, match=constraint):
        session.flush()


def test_un_seul_exemplaire_de_chaque_carburant_par_station(session):
    session.add(make_station(fuel(), fuel()))
    with pytest.raises(IntegrityError, match="fuels_pkey"):
        session.flush()


def test_un_carburant_doit_appartenir_a_une_station_existante(session):
    session.add(Fuel(station_id="INEXISTANTE", **{"type": "E85", "status": "UNKNOWN", "updated_at": None}))
    with pytest.raises(IntegrityError, match="fuels_station_id_fkey"):
        session.flush()


def test_deux_stations_ne_peuvent_pas_avoir_le_meme_identifiant(session):
    session.add(make_station())
    session.flush()
    session.expunge_all()
    session.add(make_station())
    with pytest.raises(IntegrityError, match="stations_pkey"):
        session.flush()


def test_supprimer_une_station_supprime_ses_carburants(session):
    session.add(make_station(fuel()))
    session.flush()
    # Suppression en SQL direct : vérifie le ON DELETE CASCADE de la base, pas seulement celui de SQLAlchemy.
    session.execute(text("DELETE FROM stations WHERE id = 'TEST1'"))
    assert session.scalars(select(Fuel).where(Fuel.station_id == "TEST1")).all() == []


def feed(*fuels, name="Station test"):
    # Un flux d'une seule station ; chaque carburant s'écrit ("E85", "AVAILABLE").
    return [schemas.Station(
        id="TEST1", name=name, address="1 rue Test", postal_code="42000", city="Saint-Étienne",
        fuels=[{"type": t, "status": s, "updated_at": None if s == "UNKNOWN" else NOW} for t, s in fuels],
    )]


def events(session):
    rows = session.scalars(
        select(AvailabilityEvent).where(AvailabilityEvent.station_id == "TEST1").order_by(AvailabilityEvent.id)
    )
    return [(e.fuel_type, e.old_status, e.new_status) for e in rows]


def test_un_nouvel_import_met_a_jour_sans_dupliquer(session):
    save_stations(session, feed(("E85", "AVAILABLE"), ("SP98", "UNKNOWN"), name="Ancien nom"))
    save_stations(session, feed(("GAZOLE", "UNKNOWN"), name="Carrefour"))
    session.expunge_all()

    station = session.get(Station, "TEST1")
    assert station.name == "Carrefour"
    assert station.search_text == "carrefour 1 rue test 42000 saint etienne"  # recalculé, normalisé
    assert [f.type for f in station.fuels] == ["GAZOLE"]  # les anciens carburants sont remplacés


def test_un_changement_de_statut_est_enregistre(session):
    save_stations(session, feed(("E85", "AVAILABLE"), ("SP98", "AVAILABLE")))
    save_stations(session, feed(("E85", "UNAVAILABLE"), ("SP98", "AVAILABLE")))
    save_stations(session, feed(("E85", "UNKNOWN"), ("SP98", "AVAILABLE")))

    assert events(session) == [("E85", "AVAILABLE", "UNAVAILABLE"), ("E85", "UNAVAILABLE", "UNKNOWN")]
    event = session.scalars(select(AvailabilityEvent).where(AvailabilityEvent.station_id == "TEST1")).first()
    assert event.source_updated_at == NOW  # date de la source
    assert event.detected_at is not None  # heure de détection, remplie par PostgreSQL


def test_pas_d_evenement_sans_changement(session):
    save_stations(session, feed(("E85", "AVAILABLE")))
    save_stations(session, feed(("E85", "AVAILABLE")))
    assert events(session) == []


def test_premier_import_sans_evenement(session):
    session.execute(delete(Station))  # base vide (dans la transaction annulée)
    save_stations(session, feed(("E85", "UNAVAILABLE")))
    assert events(session) == []


def test_carburant_qui_apparait_ou_disparait_sans_evenement(session):
    save_stations(session, feed(("E85", "AVAILABLE")))
    save_stations(session, feed(("SP98", "UNAVAILABLE")))  # E85 disparaît, SP98 apparaît
    assert events(session) == []


def test_supprimer_une_station_supprime_son_historique(session):
    save_stations(session, feed(("E85", "AVAILABLE")))
    save_stations(session, feed(("E85", "UNAVAILABLE")))
    session.execute(text("DELETE FROM stations WHERE id = 'TEST1'"))
    assert events(session) == []


def test_code_postal_trop_long_refuse(session):
    station = make_station()
    station.postal_code = "420000"
    session.add(station)
    with pytest.raises(Exception, match="too long"):
        session.flush()


# --- Comptes (V4.5) ---


def make_user(session, email="alice@example.fr") -> User:
    user = User(email=email, password_hash="empreinte-factice")
    session.add(user)
    session.flush()
    return user


def make_favorite(session, *fuel_types) -> User:
    session.add(make_station())
    user = make_user(session)
    session.add(Favorite(user_id=user.id, station_id="TEST1"))
    session.flush()
    session.add_all(FavoriteFuel(user_id=user.id, station_id="TEST1", fuel_type=t) for t in fuel_types)
    session.flush()
    return user


def test_preferences_de_notification_par_defaut(session):
    user = make_user(session)
    session.refresh(user)  # relit les valeurs par défaut remplies par PostgreSQL
    assert (user.notify_unavailable, user.notify_available) == (True, False)
    assert user.created_at is not None


def test_email_unique(session):
    make_user(session)
    with pytest.raises(IntegrityError, match="users_email_key"):
        make_user(session)


def test_email_en_minuscules_obligatoire(session):
    with pytest.raises(IntegrityError, match="user_email_lowercase"):
        make_user(session, email="Alice@Example.fr")


def test_favori_avec_carburants_surveilles(session):
    user = make_favorite(session, "E85", "GAZOLE")
    watched = session.scalars(select(FavoriteFuel.fuel_type).where(FavoriteFuel.user_id == user.id)).all()
    assert sorted(watched) == ["E85", "GAZOLE"]


def test_favori_en_double_refuse(session):
    user = make_favorite(session)
    session.add(Favorite(user_id=user.id, station_id="TEST1"))
    with pytest.raises(IntegrityError, match="favorites_pkey"):
        session.flush()


def test_favori_vers_station_inexistante_refuse(session):
    user = make_user(session)
    session.add(Favorite(user_id=user.id, station_id="INEXISTANTE"))
    with pytest.raises(IntegrityError, match="favorites_station_id_fkey"):
        session.flush()


def test_surveiller_hors_de_ses_favoris_refuse(session):
    # La station existe, mais n'est pas dans les favoris de cet utilisateur.
    session.add(make_station())
    user = make_user(session)
    session.add(FavoriteFuel(user_id=user.id, station_id="TEST1", fuel_type="E85"))
    with pytest.raises(IntegrityError, match="favorite_fuels_user_id_station_id_fkey"):
        session.flush()


def test_carburant_surveille_inconnu_refuse(session):
    with pytest.raises(IntegrityError, match="favorite_fuel_type_allowed"):
        make_favorite(session, "DIESEL")


def test_retirer_un_favori_retire_ses_carburants(session):
    user = make_favorite(session, "E85")
    session.execute(text(f"DELETE FROM favorites WHERE user_id = {user.id}"))
    assert session.scalars(select(FavoriteFuel).where(FavoriteFuel.user_id == user.id)).all() == []


def test_supprimer_un_compte_supprime_ses_favoris(session):
    user = make_favorite(session, "E85")
    session.execute(text(f"DELETE FROM users WHERE id = {user.id}"))
    assert session.scalars(select(Favorite).where(Favorite.user_id == user.id)).all() == []
    assert session.scalars(select(FavoriteFuel).where(FavoriteFuel.user_id == user.id)).all() == []


# --- Carburant AUTRE ---


@pytest.mark.parametrize("fuel_type", get_args(FuelType))
def test_la_base_accepte_chaque_carburant_de_fueltype(session, fuel_type):
    # Garde-fou du piège Alembic : un carburant ajouté à FuelType sans migration (CHECK) fait échouer ce test.
    label = "B100" if fuel_type == "AUTRE" else None
    user = make_favorite(session, fuel_type)  # favorite_fuels
    session.execute(delete(Fuel).where(Fuel.station_id == "TEST1"))
    session.add(Fuel(station_id="TEST1", type=fuel_type, label=label, status="UNKNOWN", updated_at=None))
    session.add(AvailabilityEvent(station_id="TEST1", fuel_type=fuel_type, label=label,
                                  old_status="AVAILABLE", new_status="UNKNOWN"))
    session.flush()
    assert user.id is not None


@pytest.mark.parametrize(("fuel_type", "label"), [("AUTRE", None), ("GAZOLE", "Gazole")])
def test_label_seulement_pour_autre(session, fuel_type, label):
    session.add(make_station(Fuel(type=fuel_type, label=label, status="UNKNOWN", updated_at=None)))
    with pytest.raises(IntegrityError, match="fuel_label_only_for_other"):
        session.flush()


def test_historique_d_un_carburant_autre_garde_son_nom(session):
    def autre(status):
        return [schemas.Station(id="TEST1", name="n", address="a", postal_code="42000", city="c",
                                fuels=[{"type": "AUTRE", "label": "B100", "status": status, "updated_at": NOW}])]

    save_stations(session, autre("AVAILABLE"))
    save_stations(session, autre("UNAVAILABLE"))
    event = session.scalars(select(AvailabilityEvent).where(AvailabilityEvent.station_id == "TEST1")).one()
    assert (event.fuel_type, event.label, event.new_status) == ("AUTRE", "B100", "UNAVAILABLE")
