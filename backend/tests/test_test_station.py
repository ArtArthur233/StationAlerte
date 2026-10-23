# Station fictive de test : fichier local lu par l'import, refus des valeurs invalides, chemin complet jusqu'à l'alerte.
from datetime import UTC, datetime
import argparse
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import models, sync, test_station
from app.mock_data import get_mock_stations
from app.security import hash_password


@pytest.fixture
def station_file(tmp_path, monkeypatch):
    # Fichier temporaire : les tests ne touchent jamais au vrai data/test_station.json de l'utilisateur.
    path = tmp_path / "test_station.json"
    monkeypatch.setattr(test_station, "TEST_STATION_PATH", path)
    return path


def write(path, changes: dict[str, str]) -> None:
    station = test_station.update(test_station.DEFAULT_STATION, changes)
    path.write_text(json.dumps(station), encoding="utf-8")


def test_sans_fichier_rien_n_est_ajoute(station_file):
    assert test_station.load() == []  # cas normal, et toujours en production


@pytest.mark.parametrize("content", ["{ cassé", "", '{"id": "X"}'])
def test_fichier_abime_ignore_sans_bloquer_la_surveillance(station_file, content, caplog):
    station_file.write_text(content, encoding="utf-8")
    assert test_station.load() == []  # les vraies stations continuent d'être importées
    assert "illisible" in caplog.text


def test_explication_surveillant_arrete():
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert "il y a 40 min (plus de 20 min" in test_station.explain_no_alert(now - timedelta(minutes=40), now)
    assert "premier passage" in test_station.explain_no_alert(None, now)
    assert "Surveiller" in test_station.explain_no_alert(now - timedelta(minutes=5), now)  # autre cause


def test_statuts_dates_et_ordre(station_file):
    write(station_file, {"SP98": "UNAVAILABLE", "GAZOLE": "AVAILABLE", "E10": "UNKNOWN"})
    [station] = test_station.load()

    assert station.name == "stationTest" and station.address == "Station fictive de test"
    assert [(f.type, f.status) for f in station.fuels] == [("GAZOLE", "AVAILABLE"), ("E10", "UNKNOWN"), ("SP98", "UNAVAILABLE")]
    assert station.fuels[1].updated_at is None  # UNKNOWN : jamais de date (règle des trois états)
    assert station.fuels[0].updated_at is not None


def test_prix_fictif_seulement_si_disponible(station_file):
    write(station_file, {"GAZOLE": "AVAILABLE", "E10": "UNAVAILABLE", "SP98": "UNKNOWN"})
    [station] = test_station.load()

    # Comme dans le vrai flux : une rupture n'a jamais de prix.
    assert [(f.type, f.price) for f in station.fuels] == [("GAZOLE", 1.799), ("E10", None), ("SP98", None)]


def test_prix_ajoutes_a_un_fichier_ecrit_avant_les_prix(station_file):
    station_file.write_text(json.dumps({**test_station.DEFAULT_STATION, "fuels": [
        {"type": "E10", "status": "AVAILABLE", "updated_at": datetime.now(UTC).isoformat()}]}), encoding="utf-8")
    assert test_station.load()[0].fuels[0].price == test_station.FAKE_PRICES["E10"]


def test_date_gardee_si_le_statut_ne_change_pas():
    first = test_station.update(test_station.DEFAULT_STATION, {"GAZOLE": "AVAILABLE"})
    again = test_station.update(first, {"GAZOLE": "AVAILABLE", "E10": "AVAILABLE"})
    assert again["fuels"][0] == first["fuels"][0]


def test_retirer_un_carburant():
    station = test_station.update(test_station.DEFAULT_STATION, {"GAZOLE": "AVAILABLE", "E10": "AVAILABLE"})
    assert [f["type"] for f in test_station.update(station, {"E10": test_station.REMOVE})["fuels"]] == ["GAZOLE"]


@pytest.mark.parametrize(("text", "expected"), [
    ("gazole=rupture", ("GAZOLE", "UNAVAILABLE")), ("E10=dispo", ("E10", "AVAILABLE")),
    ("SP98=inconnu", ("SP98", "UNKNOWN")), ("SP95=UNAVAILABLE", ("SP95", "UNAVAILABLE")), ("E85=retirer", ("E85", "retirer")),
])
def test_ecritures_acceptees(text, expected):
    assert test_station.parse_change(text) == expected


@pytest.mark.parametrize("text", ["DIESEL=dispo", "GAZOLE=peut-etre", "GAZOLE", "AUTRE=dispo"])
def test_ecritures_refusees(text):
    with pytest.raises(argparse.ArgumentTypeError):
        test_station.parse_change(text)


def test_champs_invalides_refuses():
    with pytest.raises(ValidationError):
        test_station.update(test_station.DEFAULT_STATION, {}, postal_code="123456")  # 6 chiffres


def test_ajoutee_au_flux_par_l_import(station_file, monkeypatch, connection):
    # save_and_alert remplacée : on regarde seulement ce qui lui est envoyé, rien n'est écrit en base.
    write(station_file, {"GAZOLE": "AVAILABLE"})
    saved = []
    monkeypatch.setattr(sync, "fetch_stations", get_mock_stations)
    monkeypatch.setattr(sync, "save_and_alert", lambda db, stations: saved.extend(stations) or sync.ImportResult(0, 0, 0))
    sync.import_feed()
    assert saved[-1].id == test_station.TEST_STATION_ID
    assert len(saved) == len(get_mock_stations()) + 1


def test_flux_vide_reste_refuse_meme_avec_la_station_de_test(station_file, monkeypatch):
    write(station_file, {"GAZOLE": "AVAILABLE"})
    monkeypatch.setattr(sync, "fetch_stations", lambda: [])
    with pytest.raises(ValueError, match="vide"):  # la station fictive ne masque pas une panne de la source
        sync.import_feed()


def test_de_la_station_de_test_jusqu_a_l_alerte(session, station_file):
    # Le chemin que l'utilisateur suivra à la main : créer la station, la mettre en favori, changer un statut.
    write(station_file, {"GAZOLE": "AVAILABLE"})
    sync.save_and_alert(session, get_mock_stations() + test_station.load())
    user = models.User(email="testeur@test.fr", password_hash=hash_password("x" * 12), email_verified_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    session.add(models.Favorite(user_id=user.id, station_id=test_station.TEST_STATION_ID))
    session.flush()
    session.add(models.FavoriteFuel(user_id=user.id, station_id=test_station.TEST_STATION_ID, fuel_type="GAZOLE"))
    session.flush()

    write(station_file, {"GAZOLE": "UNAVAILABLE"})
    sync.save_and_alert(session, get_mock_stations() + test_station.load())
    # Seulement nos alertes : l'utilisateur surveille peut-être lui aussi la vraie stationTest.
    mine = session.scalars(select(models.Alert).where(models.Alert.user_id == user.id)).all()
    assert len(mine) == 1

