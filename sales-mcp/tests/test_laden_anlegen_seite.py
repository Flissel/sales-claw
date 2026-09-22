"""Rollen-Tor und Formular fuer '/team/laden-anlegen'.

WELCHE KAPUTTE FASSUNG FAENGT JEDER TEST?
-------------------------------------------------------------------------
* test_nur_freigeben_und_basis_laden_duerfen  — eine Fassung, die nur die
  Rolle prueft (nicht auch server.SCHEMA), wuerde Ivan den Knopf zeigen,
  saehe er ihn ueberhaupt (er sieht ihn wegen der Schema-Pruefung NIE).
* test_falscher_name_wird_serverseitig_abgewiesen — ein Formular, das dem
  Browser-Muster vertraut, laesst jeden Namen durch, den jemand ohne
  Browser (curl, ein Skript) schickt.
* test_zeile_traegt_den_angemeldeten_namen — eine Fassung, die den Namen
  hart auf 'betreiber-ui' setzt (Kopiereffekt aus anderen Routen), wuerde
  nie zeigen, WER einen Laden angefordert hat.

ERGAENZUNG (bei der Abnahme dieser Datei nachtraeglich gefunden): der Test
oben (hier: test_guter_name_legt_eine_zeile_mit_status_offen_an) laeuft
OHNE Sitzung — in dieser Lage liefert _ui_akteur(request) 'betreiber-ui'
GENAUSO wie ein hart einprogrammierter String. Er kann die im Docstring
behauptete Kopiefalle also gar nicht fangen; nur eine SCHARFE Anmeldung
(echter Benutzer, echte Sitzung) unterscheidet die beiden Fassungen — siehe
test_scharfe_anmeldung_traegt_den_echten_namen unten (Muster aus
test_login.py::test_rolle_freigeben_hinterlaesst_ihren_namen /
test_ohne_anmeldung_bleibt_der_alte_stempel, dieselbe Zweiteilung).
"""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

import pytest
from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.admin_auftraege, sales_test.benutzer cascade")


@pytest.fixture
def scharf():
    """Anmeldung fuer die Dauer eines Tests scharf schalten — dasselbe
    Muster wie test_login.py::scharf, hier gebraucht, um _ui_akteur(request)
    von einem hart einprogrammierten 'betreiber-ui' zu unterscheiden."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _benutzer(name, rolle="freigeben", passwort="korrekt-pferd-9"):
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv) values "
        "(%s, %s, %s, true) returning name",
        (name, rolle, ui._passwort_hashen(passwort)))
    return name


def _post(pfad, daten, host=HOST_OK, client=None):
    return (client or CLIENT).post(
        pfad, data=daten, headers={"host": host}, follow_redirects=False)


def _get(pfad, host=HOST_OK, client=None):
    return (client or CLIENT).get(pfad, headers={"host": host})


def test_nur_freigeben_und_basis_laden_duerfen():
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen") is True
    assert ui._pfad_erlaubt("lesen", "/team/laden-anlegen") is False
    assert ui._pfad_erlaubt("kalender", "/team/laden-anlegen") is False


def test_freigeben_ausserhalb_des_basis_ladens_darf_nicht(monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen") is False
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen/anfordern") is False


@pytest.mark.parametrize("schlechter_name", [
    "Ivan", "ivan-mit-bindestrich", "1ivan", "", "a" * 32])
def test_falscher_name_wird_serverseitig_abgewiesen(schlechter_name):
    r = _post("/team/laden-anlegen/anfordern",
              {"name": schlechter_name, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_guter_name_legt_eine_zeile_mit_status_offen_an():
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    zeilen = server._q(
        "select name, status, angefordert_von from admin_auftraege")
    assert len(zeilen) == 1
    assert zeilen[0]["name"] == "lena"
    assert zeilen[0]["status"] == "offen"
    # Ohne scharfe Anmeldung (Testlage) greift der dokumentierte
    # Uebergangs-Sammelstempel — derselbe wie bei jeder anderen Route.
    assert zeilen[0]["angefordert_von"] == "betreiber-ui"


def test_ohne_csrf_token_wird_nichts_angelegt():
    r = _post("/team/laden-anlegen/anfordern", {"name": "lena"})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_seite_traegt_auffrischen_solange_ein_auftrag_offen_ist():
    server._q(
        "insert into admin_auftraege (art, name, angefordert_von) "
        "values ('laden_anlegen', 'lena', 'test')")
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' in r.text


def test_seite_traegt_kein_auffrischen_wenn_alles_erledigt_ist():
    server._q(
        "insert into admin_auftraege "
        "(art, name, angefordert_von, status, erledigt_am) "
        "values ('laden_anlegen', 'lena', 'test', 'erfolg', now())")
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' not in r.text


def test_seite_ohne_javascript():
    r = _get("/team/laden-anlegen")
    assert "<script" not in r.text.lower()


def test_seite_zeigt_ergebnis_mit_echtem_json_ohne_absturz():
    """K1 der Schlusspruefung: ergebnis kommt aus der DB bereits als dict
    (psycopg3 deserialisiert jsonb automatisch) — json.loads() darauf war
    ein TypeError, den keine Vorgaengerpruefung sah, weil kein Test je ein
    nicht-leeres ergebnis eingefuegt hatte."""
    server._q(
        "insert into admin_auftraege "
        "(art, name, angefordert_von, status, ergebnis, erledigt_am) "
        "values ('laden_anlegen', 'lena', 'test', 'erfolg', "
        "%s::jsonb, now())",
        ('{"passwort": "Probe-XYZ123", "port_serve": 8446, "hinweis": "x"}',))
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert "Probe-XYZ123" in r.text


def test_seite_zeigt_ergebnis_bei_fehler_mit_echtem_json_ohne_absturz():
    """Ergaenzt die K1-Pruefung oben: der urspruengliche Befund war ein
    TypeError auf JEDEM nicht-leeren `ergebnis`, nicht nur bei 'erfolg' —
    fehler_melden() in deploy/admin-auftrag-ausfuehren.sh schreibt bei
    einem Abbruch ebenfalls ein ergebnis::jsonb (die ERLEDIGT-Liste)."""
    server._q(
        "insert into admin_auftraege "
        "(art, name, angefordert_von, status, ergebnis, fehler, erledigt_am) "
        "values ('laden_anlegen', 'lena', 'test', 'fehler', "
        "%s::jsonb, 'Abbruch nach Schritt umgebungsdatei (Exit 1)', now())",
        ('{"erledigt": ["aufnahme", "ports", "umgebungsdatei"]}',))
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert "aufnahme, ports, umgebungsdatei" in r.text


@pytest.mark.parametrize("reservierter_name", ["sales", "test"])
def test_reservierte_namen_werden_abgewiesen(reservierter_name):
    r = _post("/team/laden-anlegen/anfordern",
              {"name": reservierter_name, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_scharfe_anmeldung_traegt_den_echten_namen(scharf):
    """Deckt die Luecke aus der Ergaenzung oben: nur mit einer echten
    Sitzung unterscheidet sich _ui_akteur(request) ueberhaupt von einem
    hart einprogrammierten 'betreiber-ui'. Faengt genau die Fassung, die
    _ui_akteur(request) durch das feste Wort 'betreiber-ui' ersetzt —
    diese wuerde hier trotzdem gruen bleiben, WENN dieser Test fehlte."""
    client = TestClient(ui.app)
    _benutzer("mira", rolle="freigeben")
    login = client.post(
        "/login", data={"name": "mira", "passwort": "korrekt-pferd-9",
                        "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert login.status_code == 303, login.text
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "csrf": ui.CSRF_TOKEN}, client=client)
    assert r.status_code == 303
    zeile = server._q(
        "select angefordert_von from admin_auftraege")[0]
    assert zeile["angefordert_von"] == "mira"
