# Surveillant (V6) : rythme des vérifications, pannes, un seul surveillant à la fois.
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app import models, sync, worker
from app.main import stations_db
from app.mock_data import get_mock_stations
from app.services import save_stations


def only_import(session, ago: timedelta | None) -> None:
    # Remplace les vrais imports de la base, dans la transaction de test (annulée à la fin).
    session.execute(models.FeedImport.__table__.delete())
    if ago is None:
        return
    session.add(models.FeedImport(station_count=1, imported_at=datetime.now(UTC) - ago))
    session.flush()


# --- Quand vérifier ---


def test_jamais_importe_verifie_tout_de_suite(session):
    only_import(session, ago=None)
    assert sync.seconds_until_next_check(session) == 0


def test_import_recent_attend_le_prochain_passage(session):
    only_import(session, ago=timedelta(minutes=4))
    assert 5 * 60 < sync.seconds_until_next_check(session) <= 6 * 60


def test_import_ancien_verifie_tout_de_suite(session):
    only_import(session, ago=timedelta(hours=3))  # surveillant arrêté pendant 3 h
    assert sync.seconds_until_next_check(session) == 0


def test_rythme_d_une_heure_par_defaut():
    assert sync.CHECK_EVERY == timedelta(minutes=10)  # rythme de la source, choix de l'utilisateur (17/10/2026)


def test_chaque_import_est_enregistre(session):
    before = sync.last_import_id(session)
    save_stations(session, get_mock_stations())
    assert sync.last_import_id(session) != before  # l'API sait que les données ont changé


# --- Un passage du surveillant ---


@pytest.fixture
def fake_check(monkeypatch):
    calls = {"imports": 0}

    def fake_import():
        calls["imports"] += 1
        return sync.ImportResult(9800, 3, 1)

    monkeypatch.setattr(sync, "import_feed", fake_import)
    # Le ménage est testé à part (test_housekeeping.py) : ici, il ne doit pas toucher à la vraie base.
    monkeypatch.setattr(worker, "clean_up", lambda db: calls.__setitem__("cleanups", calls.get("cleanups", 0) + 1) or {})
    monkeypatch.setattr(worker, "send_alerts", lambda: calls.__setitem__("sends", calls.get("sends", 0) + 1))
    return calls


def test_passage_a_l_heure_importe(monkeypatch, fake_check):
    monkeypatch.setattr(sync, "seconds_until_next_check", lambda db: 0.0)
    assert worker.check_once() == 600
    assert fake_check["imports"] == 1
    assert fake_check["cleanups"] == 1  # ménage après chaque import réussi
    assert fake_check["sends"] == 1  # puis envoi des alertes


def test_passage_trop_tot_n_importe_pas(monkeypatch, fake_check):
    monkeypatch.setattr(sync, "seconds_until_next_check", lambda db: 240.0)
    assert worker.check_once() == 240  # il attend le prochain passage
    assert fake_check["imports"] == 0


def test_source_en_panne_reessaie_dans_5_minutes(monkeypatch, caplog, fake_check):
    def broken():
        raise ConnectionError("prix-carburants.gouv.fr injoignable")

    monkeypatch.setattr(sync, "seconds_until_next_check", lambda db: 0.0)
    monkeypatch.setattr(sync, "import_feed", broken)
    assert worker.check_once() == worker.RETRY_SECONDS == 300  # pas de plantage, pas de rafale d'essais
    assert "Vérification impossible" in caplog.text
    assert fake_check["sends"] == 1  # les alertes déjà prêtes partent quand même


def test_base_en_panne_reessaie_dans_5_minutes(monkeypatch, fake_check):
    def broken(db):
        raise OSError("base arrêtée")

    monkeypatch.setattr(sync, "seconds_until_next_check", broken)
    assert worker.check_once() == worker.RETRY_SECONDS
    assert fake_check["imports"] == 0


def test_flux_vide_refuse(monkeypatch):
    # Un flux vide ne doit jamais effacer la base : import_feed lève une erreur avant d'y toucher.
    monkeypatch.setattr(sync, "fetch_stations", lambda: [])
    with pytest.raises(ValueError, match="vide"):
        sync.import_feed()


# --- Un seul surveillant ---


def test_un_seul_surveillant_a_la_fois(connection):
    first = worker.single_instance_lock()
    if first is None:
        pytest.skip("le vrai surveillant tourne et détient le verrou")
    try:
        assert worker.single_instance_lock() is None  # le 2e surveillant s'arrêtera
    finally:
        first.close()
    second = worker.single_instance_lock()  # le 1er arrêté, le verrou est libéré
    assert second is not None
    second.close()


def test_api_sans_donnees_repond_503(session):
    # Surveillant jamais lancé : une liste vide ferait croire qu'il n'y a aucune station.
    session.execute(delete(models.Station))  # dans la transaction de test, annulée à la fin
    with pytest.raises(sync.SourceUnavailable):
        stations_db(session)
