import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sqlalchemy import delete
from sqlalchemy.exc import OperationalError

from app import models
from app import main
from app.main import app, stations_db
from app.mock_data import get_mock_stations
from app.schemas import FuelInfo
from app.services import save_stations
from app.sync import SourceUnavailable

client = TestClient(app)


@pytest.fixture(autouse=True)
def stations_fictives(session):
    # Les tests de l'API ne téléchargent rien : le jeu d'essai fictif est écrit dans la base de test
    # (transaction annulée à la fin), et les routes lisent cette session au lieu de la vraie.
    # La base de développement contient les vraies stations : on les retire dans cette même transaction
    # (annulée à la fin, donc rien n'est perdu) pour que les tests ne voient que le jeu d'essai.
    session.execute(delete(models.Station))
    save_stations(session, get_mock_stations())
    main._positions_cache = None  # la réponse de la carte gardée en mémoire viendrait d'un autre test
    app.dependency_overrides[stations_db] = lambda: session
    yield
    app.dependency_overrides.clear()


def broken_db(error: Exception):
    def raise_error():
        raise error

    app.dependency_overrides[stations_db] = raise_error


def test_list_stations_renvoie_les_stations_en_camel_case():
    response = client.get("/stations")

    assert response.status_code == 200
    stations = response.json()
    assert len(stations) == 4
    assert stations[0]["postalCode"] == "69001"  # même format que le frontend
    assert "updatedAt" in stations[0]["fuels"][0]
    # Prix relu de la base (Numeric) en nombre JSON, pas en texte ; absent = null.
    assert stations[0]["fuels"][0]["price"] == 1.789
    assert stations[0]["fuels"][1]["price"] is None


def ids(response):
    return [station["id"] for station in response.json()]


def test_recherche_ignore_casse_accents_et_tirets():
    assert ids(client.get("/stations", params={"q": "SAINT ETIENNE"})) == ["demo-4"]
    assert ids(client.get("/stations", params={"q": "saint-étienne"})) == ["demo-4"]


def test_recherche_par_code_postal():
    assert ids(client.get("/stations", params={"q": "33000"})) == ["demo-2"]


def test_recherche_mot_par_mot_dans_n_importe_quel_ordre():
    assert ids(client.get("/stations", params={"q": "lyon démo station"})) == ["demo-1"]


def test_filtre_par_carburant():
    assert ids(client.get("/stations", params={"fuel": "E85"})) == ["demo-2"]


def test_combine_recherche_et_carburant():
    assert ids(client.get("/stations", params={"q": "lyon", "fuel": "SP98"})) == ["demo-1"]
    assert ids(client.get("/stations", params={"q": "lyon", "fuel": "E85"})) == []


def test_carburant_inconnu_refuse():
    assert client.get("/stations", params={"fuel": "ESSENCE"}).status_code == 422


def test_detail_d_une_station():
    response = client.get("/stations/demo-2")

    assert response.status_code == 200
    assert response.json()["city"] == "Bordeaux"


def test_station_inconnue_renvoie_404():
    response = client.get("/stations/n-existe-pas")

    assert response.status_code == 404
    assert response.json() == {"detail": "Station introuvable"}


def test_carburants_d_une_station():
    response = client.get("/stations/demo-2/fuels")

    assert response.status_code == 200
    fuels = response.json()
    assert [fuel["type"] for fuel in fuels] == ["GAZOLE", "E85", "GPLC"]
    # Le GPLc n'a jamais été renseigné : il reste UNKNOWN avec une date absente, jamais UNAVAILABLE.
    assert fuels[2] == {"type": "GPLC", "label": None, "status": "UNKNOWN", "updatedAt": None, "price": None}


def test_carburants_d_une_station_inconnue_renvoie_404():
    response = client.get("/stations/n-existe-pas/fuels")

    assert response.status_code == 404
    assert response.json() == {"detail": "Station introuvable"}


def test_cors_autorise_le_site_local_uniquement():
    autorise = client.get("/stations", headers={"Origin": "http://localhost:5173"})
    inconnu = client.get("/stations", headers={"Origin": "http://site-inconnu.example"})

    assert autorise.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in inconnu.headers


def test_date_mal_formee_refusee():
    # Une date illisible ne doit jamais passer : côté frontend elle garderait son statut au lieu de UNKNOWN.
    with pytest.raises(ValidationError):
        FuelInfo(type="GAZOLE", status="AVAILABLE", updated_at="abc")


def test_limit_borne_le_nombre_de_resultats():
    assert len(client.get("/stations", params={"limit": 2}).json()) == 2
    assert client.get("/stations", params={"limit": 101}).status_code == 422


def test_source_indisponible_renvoie_503():
    broken_db(SourceUnavailable())
    response = client.get("/stations")

    assert response.status_code == 503
    assert response.json() == {"detail": "Source de données indisponible"}


def test_base_indisponible_renvoie_503():
    broken_db(OperationalError("SELECT 1", {}, Exception("connexion refusée")))
    response = client.get("/stations/demo-1")

    assert response.status_code == 503
    assert response.json() == {"detail": "Base de données indisponible"}


@pytest.mark.parametrize("joker", ["%", "_", "%%", "\\"])
def test_les_jokers_sql_sont_cherches_tels_quels(joker):
    # Sans échappement, « % » trouverait toutes les stations.
    assert ids(client.get("/stations", params={"q": joker})) == []


def test_recherche_vide_renvoie_les_stations_par_identifiant():
    assert ids(client.get("/stations")) == ["demo-1", "demo-2", "demo-3", "demo-4"]


def test_carburants_toujours_dans_le_meme_ordre():
    # demo-4 déclare SP98 puis E10 ; l'ordre renvoyé suit FuelType, pas l'ordre d'insertion.
    fuels = client.get("/stations/demo-4/fuels").json()
    assert [fuel["type"] for fuel in fuels] == ["E10", "SP98"]


def test_positions_pour_la_carte():
    response = client.get("/stations/positions")

    assert response.status_code == 200  # pas pris pour l'identifiant d'une station « positions »
    positions = response.json()
    assert [p["id"] for p in positions] == ["demo-1", "demo-2"]  # les stations sans coordonnées sont exclues
    assert positions[0] == {
        "id": "demo-1", "name": "Station Démo du Centre", "address": "12 rue Imaginaire",
        "postalCode": "69001", "city": "Lyon", "latitude": 45.767, "longitude": 4.834,
    }  # sans les carburants : réponse légère


def test_st_et_saint_sont_equivalents():
    assert ids(client.get("/stations", params={"q": "st etienne"})) == ["demo-4"]


def test_abreviation_seulement_pour_un_mot_entier():
    from app.services import normalize

    assert normalize("Rue de l'Est") == "rue de l'est"  # « est » et « stade » ne deviennent pas « saint »
    assert normalize("Stade") == "stade"


@pytest.mark.parametrize("url", ["/stations?q=lyon%00", "/stations/demo%00", "/stations/demo%00/fuels"])
def test_octet_nul_refuse_sans_planter(url):
    # PostgreSQL refuse « \x00 » dans un texte : c'est une requête invalide (400), pas une panne (500).
    response = client.get(url)
    assert response.status_code == 400
    assert response.json() == {"detail": "Requête invalide"}


def test_recherche_limitee_a_200_caracteres():
    assert client.get("/stations", params={"q": "a " * 100}).status_code == 200  # 200 caractères
    assert client.get("/stations", params={"q": "a " * 100 + "b"}).status_code == 422


def test_positions_gardees_en_memoire_jusqu_au_prochain_import(session):
    first = client.get("/stations/positions")
    assert first.headers["cache-control"] == "max-age=300"  # le navigateur peut la réutiliser 5 min
    session.execute(delete(models.Station).where(models.Station.id == "demo-1"))
    session.flush()

    assert client.get("/stations/positions").json() == first.json()  # même version de données : copie en mémoire
    session.add(models.FeedImport(station_count=1))  # le surveillant vient d'importer
    session.flush()
    assert [p["id"] for p in client.get("/stations/positions").json()] == ["demo-2"]  # recalculée


@pytest.mark.parametrize("path", ["/stations", "/stations/inconnue", "/docs"])
def test_en_tetes_de_securite_sur_chaque_reponse(path):
    response = client.get(path)  # réussite, erreur 404 et page de documentation

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_en_tetes_de_securite_meme_sur_un_refus_csrf():
    response = client.post("/auth/logout", headers={"Origin": "http://site-inconnu.example"})

    assert response.status_code == 403
    assert response.headers["x-content-type-options"] == "nosniff"


def test_cors_autorise_la_version_compilee_du_site():
    response = client.get("/stations", headers={"Origin": "http://localhost:4173"})  # npm run preview

    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"
