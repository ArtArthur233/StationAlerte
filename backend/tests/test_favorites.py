import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.api import favorites
from app.main import app
pytestmark = pytest.mark.usefixtures("api_db")


@pytest.fixture
def stations(session) -> list[str]:
    # Stations d'essai (identifiants qui n'existent pas dans le vrai flux), dans la transaction de test.
    ids = ["TEST-A", "TEST-B", "TEST-C"]
    for station_id in ids:
        station = models.Station(id=station_id, name=f"Station {station_id}", address="1 rue Test",
                                 postal_code="42000", city="Saint-Étienne", search_text="test")
        station.fuels.append(models.Fuel(type="GAZOLE", status="UNKNOWN", updated_at=None))
        station.fuels.append(models.Fuel(type="E10", status="UNKNOWN", updated_at=None))
        session.add(station)
    session.flush()
    return ids


def favorite_ids(client) -> list[str]:
    response = client.get("/me/favorites")
    assert response.status_code == 200
    return [station["id"] for station in response.json()]


# --- Connexion obligatoire ---


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/me/favorites"), ("PUT", "/me/favorites/TEST-A"), ("DELETE", "/me/favorites/TEST-A"),
     ("PUT", "/me/favorites/TEST-A/fuels")],
)
def test_connexion_requise(stations, method, path):
    response = TestClient(app).request(method, path, json={"fuels": []})
    assert response.status_code == 401
    assert response.json() == {"detail": "Connexion requise"}


# --- Ajouter, lister, retirer ---


def test_aucun_favori_au_depart(alice):
    assert favorite_ids(alice) == []


def test_ajouter_puis_lister_avec_les_carburants(alice, stations):
    assert alice.put("/me/favorites/TEST-A").status_code == 204
    [station] = alice.get("/me/favorites").json()

    assert station["id"] == "TEST-A"
    assert station["postalCode"] == "42000"  # même format que /stations : le site réutilise ses fiches
    assert [fuel["type"] for fuel in station["fuels"]] == ["GAZOLE", "E10"]
    assert station["fuels"][0] == {"type": "GAZOLE", "label": None, "status": "UNKNOWN", "updatedAt": None, "price": None}
    assert station["watchedFuels"] == []  # choix (a) : rien n'est surveillé tant que l'utilisateur ne coche rien


def test_ordre_d_ajout(alice, stations):
    for station_id in ["TEST-C", "TEST-A", "TEST-B"]:
        alice.put(f"/me/favorites/{station_id}")
    assert favorite_ids(alice) == ["TEST-C", "TEST-A", "TEST-B"]


def test_ajouter_deux_fois_ne_cree_pas_de_doublon(alice, stations):
    assert alice.put("/me/favorites/TEST-A").status_code == 204
    assert alice.put("/me/favorites/TEST-A").status_code == 204
    assert favorite_ids(alice) == ["TEST-A"]


def test_retirer(alice, stations):
    alice.put("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-B")
    assert alice.delete("/me/favorites/TEST-A").status_code == 204
    assert favorite_ids(alice) == ["TEST-B"]


def test_retirer_une_station_qui_n_est_pas_en_favori(alice, stations):
    assert alice.delete("/me/favorites/TEST-A").status_code == 204


def test_station_inconnue(alice):
    response = alice.put("/me/favorites/N-EXISTE-PAS")
    assert response.status_code == 404
    assert response.json() == {"detail": "Station introuvable"}


@pytest.mark.parametrize("station_id", ["a%00b", "x" * 5000])
def test_identifiant_piege(alice, station_id):
    # Octet nul : 400 (pas 500) ; identifiant énorme : simplement introuvable.
    assert alice.put(f"/me/favorites/{station_id}").status_code in (400, 404)
    assert alice.delete(f"/me/favorites/{station_id}").status_code in (400, 204)


def test_limite_de_favoris(alice, stations, session, monkeypatch):
    monkeypatch.setattr(favorites, "MAX_FAVORITES", 2)
    alice.put("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-B")
    response = alice.put("/me/favorites/TEST-C")

    assert response.status_code == 409
    assert response.json() == {"detail": "Limite de 2 stations favorites atteinte."}
    assert alice.put("/me/favorites/TEST-A").status_code == 204  # déjà favori : pas bloqué par la limite


# --- Carburants surveillés (V5.4) ---


def watched(client, station_id: str) -> list[str]:
    return next(station["watchedFuels"] for station in client.get("/me/favorites").json() if station["id"] == station_id)


def test_choisir_les_carburants_surveilles(alice, stations):
    alice.put("/me/favorites/TEST-A")
    assert alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["E10", "GAZOLE", "E10"]}).status_code == 204
    assert watched(alice, "TEST-A") == ["GAZOLE", "E10"]  # ordre de FuelType, sans doublon


def test_la_liste_envoyee_remplace_l_ancienne(alice, stations):
    alice.put("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE", "E10"]})
    alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["E10"]})
    assert watched(alice, "TEST-A") == ["E10"]
    alice.put("/me/favorites/TEST-A/fuels", json={"fuels": []})
    assert watched(alice, "TEST-A") == []


def test_surveiller_hors_des_favoris_refuse(alice, stations):
    response = alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE"]})
    assert response.status_code == 404
    assert response.json() == {"detail": "Station absente de vos favoris"}


def test_carburant_non_vendu_refuse(alice, stations):
    alice.put("/me/favorites/TEST-A")
    response = alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE", "SP98"]})
    assert response.status_code == 400
    assert response.json() == {"detail": "Carburant non vendu par cette station : SP98"}
    assert watched(alice, "TEST-A") == []  # rien n'a été enregistré


@pytest.mark.parametrize("body", [{"fuels": ["DIESEL"]}, {"fuels": ["GAZOLE"] * 8}, {"fuels": "GAZOLE"}, {}])
def test_liste_invalide(alice, stations, body):
    alice.put("/me/favorites/TEST-A")
    assert alice.put("/me/favorites/TEST-A/fuels", json=body).status_code == 422


def test_retirer_le_favori_retire_ses_carburants_surveilles(alice, stations, session):
    alice.put("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE"]})
    alice.delete("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-A")
    assert watched(alice, "TEST-A") == []  # le favori revient « vierge »


# --- Chacun ses favoris ---


def test_chacun_ne_voit_que_ses_favoris(alice, camille, stations):
    alice.put("/me/favorites/TEST-A")
    camille.put("/me/favorites/TEST-B")

    assert favorite_ids(alice) == ["TEST-A"]
    assert favorite_ids(camille) == ["TEST-B"]


def test_retirer_ne_touche_pas_aux_favoris_des_autres(alice, camille, stations):
    alice.put("/me/favorites/TEST-A")
    assert camille.delete("/me/favorites/TEST-A").status_code == 204  # Camille retire... ses propres favoris

    assert favorite_ids(alice) == ["TEST-A"]


def test_chacun_ses_carburants_surveilles(alice, camille, stations):
    alice.put("/me/favorites/TEST-A")
    camille.put("/me/favorites/TEST-A")
    alice.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE"]})
    camille.put("/me/favorites/TEST-A/fuels", json={"fuels": ["E10"]})

    assert watched(alice, "TEST-A") == ["GAZOLE"]
    assert watched(camille, "TEST-A") == ["E10"]


def test_impossible_de_surveiller_dans_les_favoris_d_un_autre(alice, camille, stations):
    alice.put("/me/favorites/TEST-A")
    # Camille n'a pas TEST-A en favori : elle ne peut pas modifier celui d'Alice.
    assert camille.put("/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE"]}).status_code == 404
    assert watched(alice, "TEST-A") == []


def test_aucune_route_ne_prend_un_identifiant_d_utilisateur():
    # Les droits reposent sur la session : aucune adresse ne permet de désigner un autre compte.
    paths = [path for path in app.openapi()["paths"] if path.startswith("/me")]
    assert paths and all("user" not in path for path in paths)


def test_apres_deconnexion_plus_d_acces(alice, stations):
    alice.put("/me/favorites/TEST-A")
    alice.post("/auth/logout")
    assert alice.get("/me/favorites").status_code == 401


# --- CSRF et CORS ---


def test_carburants_surveilles_depuis_un_autre_site_refuses(alice, stations):
    alice.put("/me/favorites/TEST-A")
    response = alice.put(
        "/me/favorites/TEST-A/fuels", json={"fuels": ["GAZOLE"]}, headers={"Origin": "https://site-pirate.example"}
    )
    assert response.status_code == 403
    assert watched(alice, "TEST-A") == []


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_modification_depuis_un_autre_site_refusee(alice, stations, session, method):
    response = alice.request(method, "/me/favorites/TEST-A", headers={"Origin": "https://site-pirate.example"})

    assert response.status_code == 403
    favorites_in_db = session.scalars(select(models.Favorite).where(models.Favorite.station_id == "TEST-A")).all()
    assert favorites_in_db == []


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_le_site_peut_envoyer_put_et_delete(method):
    response = TestClient(app).options(
        "/me/favorites/TEST-A", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": method}
    )
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


def test_toutes_les_routes_privees_demandent_une_connexion():
    # Garde-fou automatique : une future route /me… oubliée sans CurrentSession ferait échouer ce test.
    client = TestClient(app)
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/me"):
            continue
        for method in operations:
            response = client.request(method, path.replace("{station_id}", "TEST-A"), json={})
            assert response.status_code == 401, f"{method.upper()} {path} répond {response.status_code} sans connexion"


@pytest.fixture
def test_station(session) -> str:
    station = models.Station(id="TEST-STATIONTEST", name="stationTest", address="Station fictive de test",
                             postal_code="42000", city="Saint-Étienne", search_text="stationtest")
    station.fuels.append(models.Fuel(type="GAZOLE", status="UNKNOWN", updated_at=None))
    session.add(station)
    session.flush()
    return station.id


def test_station_de_test_favori_permanent_en_premier(alice, stations, test_station):
    alice.put("/me/favorites/TEST-A")

    assert favorite_ids(alice) == [test_station, "TEST-A"]  # présente sans avoir été ajoutée, et en premier
    assert favorite_ids(alice) == [test_station, "TEST-A"]  # pas de doublon à la lecture suivante


def test_station_de_test_ne_se_retire_pas(alice, test_station):
    response = alice.delete(f"/me/favorites/{test_station}")

    assert response.status_code == 400
    assert "favori permanent" in response.json()["detail"]
    assert favorite_ids(alice) == [test_station]


def test_station_de_test_surveillable_sans_lecture_prealable(alice, test_station, session):
    assert alice.put(f"/me/favorites/{test_station}/fuels", json={"fuels": ["GAZOLE"]}).status_code == 204
    assert alice.get("/me/favorites").json()[0]["watchedFuels"] == ["GAZOLE"]  # ne surveille rien par défaut, sauf choix


def test_sans_station_de_test_rien_n_est_ajoute(alice):
    assert favorite_ids(alice) == []  # hors démonstration (aucune stationTest), aucun favori imposé
