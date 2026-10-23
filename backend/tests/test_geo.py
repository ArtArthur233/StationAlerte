from app import main
from app.integrations.geo import parse_communes
from app.services import find_city_bounds
from fastapi.testclient import TestClient

LYON = ("Lyon", (45.70, 4.77, 45.80, 4.89))
SAINT_ETIENNE = ("Saint-Étienne", (45.38, 4.29, 45.47, 4.44))


def test_lit_le_rectangle_d_une_commune():
    data = [{"nom": "Lyon", "bbox": {"type": "Polygon", "coordinates": [[
        [4.77, 45.70], [4.89, 45.70], [4.89, 45.80], [4.77, 45.80], [4.77, 45.70],
    ]]}}]
    assert parse_communes(data) == [LYON]  # GeoJSON [longitude, latitude] → (sud, ouest, nord, est)


def test_ville_au_nom_exact_sans_accents_ni_tirets():
    assert find_city_bounds("saint etienne", [SAINT_ETIENNE]).north == 45.47


def test_nom_approchant_refuse():
    assert find_city_bounds("lyo", [LYON]) is None  # l'API Géo renvoie Lyon pour « lyo »


def test_homonymes_garde_le_premier():
    autre_lyon = ("Lyon", (10.0, 10.0, 11.0, 11.0))
    assert find_city_bounds("lyon", [LYON, autre_lyon]).south == 45.70


def test_code_postal_reunit_ses_communes():
    bounds = find_city_bounds("42000", [LYON, SAINT_ETIENNE])
    assert (bounds.south, bounds.west, bounds.north, bounds.east) == (45.38, 4.29, 45.80, 4.89)


def test_route_renvoie_null_si_ce_n_est_pas_une_ville(monkeypatch):
    monkeypatch.setattr(main, "search_communes", lambda q: [])
    response = TestClient(main.app).get("/cities/bounds", params={"q": "leclerc"})
    assert response.status_code == 200
    assert response.json() is None


def test_st_et_saint_designent_la_meme_ville():
    chamond = ("Saint-Chamond", (45.45, 4.47, 45.50, 4.55))
    assert find_city_bounds("st chamond", [chamond]) is not None
    assert find_city_bounds("Ste-Foy-lès-Lyon", [("Sainte-Foy-lès-Lyon", (45.7, 4.7, 45.8, 4.8))]) is not None


def test_la_route_envoie_le_nom_entier_a_l_api_geo(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "search_communes", lambda q: sent.append(q) or [])
    TestClient(main.app).get("/cities/bounds", params={"q": "St-Chamond"})
    assert sent == ["saint chamond"]
