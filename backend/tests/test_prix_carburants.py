import io
import zipfile
from datetime import UTC, datetime

import pytest

from app.integrations.prix_carburants import parse_feed

# Extrait réduit du vrai flux (même structure, même encodage ISO-8859-1), pour tester sans réseau.
SAMPLE_XML = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<pdv_liste>
  <pdv id="34150003" latitude="4365100" longitude="354700" cp="34150" pop="R">
    <adresse>Route de Pézenas</adresse>
    <ville>GIGNAC</ville>
    <prix nom="Gazole" id="1" maj="2026-10-15 08:30:00" valeur="2.251"/>
    <prix nom="GPLc" id="4" maj="2026-10-14 09:00:00" valeur="1.099"/>
    <rupture nom="SP95" id="2" debut="2018-06-08 11:20:23" fin="" type="definitive"/>
    <rupture nom="E10" id="5" debut="2026-10-13 10:00:00" fin="" type="temporaire"/>
    <rupture nom="SP98" id="6" debut="2026-09-01 10:00:00" fin="" type="temporaire"/>
    <rupture nom="E85" id="3" debut="2019-01-01 10:00:00" fin="" type=""/>
  </pdv>
</pdv_liste>
""".encode("iso-8859-1")

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)


def zipped(xml: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("PrixCarburants_instantane_ruptures.xml", xml)
    return buffer.getvalue()


def statuses():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW)
    return {fuel.type: fuel.status for fuel in station.fuels}


def test_lit_la_station_et_ses_accents():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW)
    assert station.id == "34150003"
    assert station.address == "Route de Pézenas"  # encodage ISO-8859-1 correctement décodé
    assert station.name == "Station — Route de Pézenas"
    assert (station.postal_code, station.city) == ("34150", "GIGNAC")


def test_position_gps_en_degres():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW)
    assert (station.latitude, station.longitude) == (43.651, 3.547)


def test_position_absente_ou_illisible():
    xml = SAMPLE_XML.replace(b'latitude="4365100"', b'latitude=""').replace(b'longitude="354700"', b"")
    [station] = parse_feed(zipped(xml), now=NOW)
    assert (station.latitude, station.longitude) == (None, None)


def test_nom_tire_de_l_enseigne_openstreetmap():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW, brands={"34150003": "Intermarché"})
    assert station.name == "Intermarché"


def test_prix_declare_disponible():
    assert statuses()["GAZOLE"] == "AVAILABLE"
    assert statuses()["GPLC"] == "AVAILABLE"


def test_prix_lu_et_absent_en_rupture():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW)
    prices = {fuel.type: fuel.price for fuel in station.fuels}
    assert prices == {"GAZOLE": 2.251, "GPLC": 1.099, "E10": None, "SP98": None}


@pytest.mark.parametrize("value", ["", "abc", "0", "-1", "nan", "inf", "1000"])
def test_prix_illisible_ignore_sans_perdre_le_carburant(value):
    [station] = parse_feed(feed_with(pdv().replace('valeur="1"', f'valeur="{value}"')), now=NOW)
    assert [(f.type, f.status, f.price) for f in station.fuels] == [("GAZOLE", "AVAILABLE", None)]


def test_rupture_temporaire_recente_est_indisponible():
    assert statuses()["E10"] == "UNAVAILABLE"


def test_rupture_temporaire_de_plus_de_7_jours_est_inconnue():
    assert statuses()["SP98"] == "UNKNOWN"


def test_rupture_definitive_ou_sans_type_n_est_pas_une_panne():
    # Carburant non vendu : absent de la liste, jamais « indisponible ».
    assert "SP95" not in statuses()
    assert "E85" not in statuses()


def test_dates_converties_depuis_l_heure_de_paris():
    [station] = parse_feed(zipped(SAMPLE_XML), now=NOW)
    gazole = next(f for f in station.fuels if f.type == "GAZOLE")
    assert gazole.updated_at == datetime(2026, 10, 15, 6, 30, tzinfo=UTC)  # 8 h 30 à Paris (UTC+2 en octobre)


def feed_with(*pdvs: str) -> bytes:
    return zipped(f'<?xml version="1.0" encoding="ISO-8859-1"?><pdv_liste>{"".join(pdvs)}</pdv_liste>'.encode("iso-8859-1"))


def pdv(id_="1", cp="42000", maj="2026-10-15 08:30:00", extra=""):
    return (f'<pdv id="{id_}" cp="{cp}"><adresse>1 rue</adresse><ville>X</ville>'
            f'<prix nom="Gazole" maj="{maj}" valeur="1"/>{extra}</pdv>')


@pytest.mark.parametrize(
    "broken",
    [
        pdv(maj="n'importe quoi"),  # date illisible
        '<pdv id="1" cp="42000"><adresse>a</adresse><ville>b</ville><prix nom="Gazole" valeur="1"/></pdv>',  # sans date
        pdv(extra='<rupture nom="E10" type="temporaire" debut=""/>'),  # rupture sans début
        '<pdv cp="42000"><adresse>a</adresse><ville>b</ville></pdv>',  # sans identifiant
        pdv(cp="420000"),  # code postal trop long pour la base
        pdv(id_="1" * 21),  # identifiant trop long pour la base
    ],
)
def test_une_station_abimee_est_ignoree_pas_tout_le_flux(broken):
    # Une seule erreur du ministère ne doit pas bloquer la mise à jour des 9 800 autres stations.
    stations = parse_feed(feed_with(pdv(id_="999"), broken), now=NOW)
    assert [station.id for station in stations] == ["999"]


def test_identifiant_en_double_garde_une_seule_station():
    stations = parse_feed(feed_with(pdv(cp="11111"), pdv(cp="22222")), now=NOW)
    assert [(s.id, s.postal_code) for s in stations] == [("1", "22222")]  # la dernière l'emporte


def fuels_of(*elements: str):
    [station] = parse_feed(feed_with(f'<pdv id="1" cp="42000"><adresse>a</adresse><ville>b</ville>{"".join(elements)}</pdv>'), now=NOW)
    return [(f.type, f.label, f.status) for f in station.fuels]


def test_carburant_inconnu_range_dans_autre_avec_son_nom():
    assert fuels_of('<prix nom="B100" maj="2026-10-15 08:30:00"/>') == [("AUTRE", "B100", "AVAILABLE")]


def test_rupture_d_un_carburant_inconnu():
    assert fuels_of(
        '<prix nom="B100" maj="2026-10-10 08:30:00"/>',
        '<rupture nom="B100" type="temporaire" debut="2026-10-14 10:00:00"/>',
    ) == [("AUTRE", "B100", "UNAVAILABLE")]


def test_rupture_definitive_d_un_carburant_inconnu_ignoree():
    assert fuels_of('<rupture nom="B100" type="definitive" debut="2020-01-01 10:00:00"/>') == []


def test_un_seul_autre_carburant_par_station():
    # Limite assumée : le premier carburant inconnu est gardé, les suivants ignorés.
    assert fuels_of(
        '<prix nom="B100" maj="2026-10-15 08:30:00"/>', '<prix nom="H2" maj="2026-10-15 08:30:00"/>'
    ) == [("AUTRE", "B100", "AVAILABLE")]


def test_carburant_connu_sans_label():
    assert fuels_of('<prix nom="Gazole" maj="2026-10-15 08:30:00"/>') == [("GAZOLE", None, "AVAILABLE")]
