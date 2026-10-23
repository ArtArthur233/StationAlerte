from app.integrations.osm import parse_overpass


def test_enseignes_par_identifiant_officiel():
    data = {
        "elements": [
            {"tags": {"ref:FR:prix-carburants": "1000002", "brand": "Carrefour"}},
            {"tags": {"ref:FR:prix-carburants": "1000004; 1000005", "brand": "Total"}},  # plusieurs identifiants
            {"tags": {"ref:FR:prix-carburants": "1000006"}},  # sans enseigne : ignorée
        ]
    }
    assert parse_overpass(data) == {"1000002": "Carrefour", "1000004": "Total", "1000005": "Total"}
