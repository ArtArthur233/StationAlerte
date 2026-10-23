from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import demo, models
from app.security import verify_password


@pytest.fixture
def stations(session) -> dict[str, list[str]]:
    # Stations d'essai dans la transaction de test (annulée à la fin) : rien n'est écrit dans la vraie base.
    now = datetime.now(UTC)
    favorites = {"TEST-STATIONTEST": ["GAZOLE", "E10"], "TEST-DEMO": ["SP98"]}
    for station_id, fuels in favorites.items():
        station = models.Station(id=station_id, name=station_id, address="1 rue Test", postal_code="42000",
                                 city="Saint-Étienne", search_text="test 42000")
        station.fuels.extend(models.Fuel(type=fuel, status="AVAILABLE", updated_at=now) for fuel in fuels)
        session.merge(station)
    session.flush()
    return favorites


def demo_user(session) -> models.User:
    return session.scalar(select(models.User).where(models.User.email == demo.DEMO_EMAIL))


def test_compte_confirme_avec_favoris_et_carburants_surveilles(session, stations):
    demo.create_account(session, stations)

    user = demo_user(session)
    assert user.email_verified_at is not None  # peut se connecter et recevoir des alertes
    assert user.notify_unavailable and user.notify_available
    assert verify_password(user.password_hash, demo.DEMO_PASSWORD)
    favorites = session.scalars(select(models.Favorite).where(models.Favorite.user_id == user.id)
                                .order_by(models.Favorite.created_at)).all()
    assert [f.station_id for f in favorites] == list(stations)  # dans l'ordre donné
    watched = session.execute(select(models.FavoriteFuel.station_id, models.FavoriteFuel.fuel_type)
                              .where(models.FavoriteFuel.user_id == user.id)).all()
    assert sorted(watched) == sorted((s, f) for s, fuels in stations.items() for f in fuels)


def test_recreer_remplace_l_ancien_compte(session, stations):
    first = demo.create_account(session, stations).id
    second = demo.create_account(session, {"TEST-DEMO": ["SP98"]}).id

    assert first != second
    assert session.get(models.User, first) is None
    assert session.scalars(select(models.Favorite.station_id).where(models.Favorite.user_id == second)).all() == ["TEST-DEMO"]


def test_supprimer_ne_touche_que_le_compte_de_demonstration(session, stations):
    other = models.User(email="autre@test.fr", password_hash="x", email_verified_at=datetime.now(UTC))
    session.add(other)
    demo.create_account(session, stations)

    assert demo.delete_account(session)
    assert demo_user(session) is None
    assert session.get(models.User, other.id) is not None
    assert not demo.delete_account(session)  # déjà supprimé : rien à faire


def test_vraies_stations_recentes_sans_la_station_de_test(session, stations):
    picked = demo.real_stations_nearby(session)

    assert len(picked) <= 2 and "TEST-STATIONTEST" not in picked
    for station_id, fuels in picked.items():
        station = session.get(models.Station, station_id)
        recent = {f.type for f in station.fuels if f.status == "AVAILABLE"
                  and f.updated_at > datetime.now(UTC) - timedelta(hours=48)}
        assert len(fuels) == 2 and set(fuels) <= recent
