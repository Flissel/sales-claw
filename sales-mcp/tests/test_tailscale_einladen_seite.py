"""Rollen-Tor und Formular fuer '/team/tailscale-einladen'.

WELCHE KAPUTTE FASSUNG FAENGT JEDER TEST?
-------------------------------------------------------------------------
* test_nur_freigeben_und_basis_laden_duerfen — eine Fassung, die
  _ADMIN_BASIS_PFADE vergisst und nur "/team/laden-anlegen" prueft, wuerde
  diesen Pfad fuer JEDE Rolle in JEDEM Laden oeffnen.
* test_schlechte_adresse_wird_serverseitig_abgewiesen — ein Formular, das
  dem type="email"-Attribut des Browsers vertraut, laesst jede Zeichenkette
  durch, die jemand ohne Browser (curl, ein Skript) schickt.
* test_zeile_traegt_den_angemeldeten_namen — dieselbe Kopierfalle wie bei
  '/team/laden-anlegen': eine Fassung, die den Namen hart auf
  'betreiber-ui' setzt, wuerde nie zeigen, WER eine Einladung angefordert
  hat.
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
    assert ui._pfad_erlaubt("freigeben", "/team/tailscale-einladen") is True
    assert ui._pfad_erlaubt("lesen", "/team/tailscale-einladen") is False
    assert ui._pfad_erlaubt("kalender", "/team/tailscale-einladen") is False


def test_freigeben_ausserhalb_des_basis_ladens_darf_nicht(monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/tailscale-einladen") is False
    assert ui._pfad_erlaubt(
        "freigeben", "/team/tailscale-einladen/anfordern") is False


@pytest.mark.parametrize("schlechte_adresse", [
    "keineadresse", "ohne-punkt@domain", "mit leerzeichen@domain.de", "",
    "zwei@at@zeichen.de"])
def test_schlechte_adresse_wird_serverseitig_abgewiesen(schlechte_adresse):
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": schlechte_adresse, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_ohne_csrf_token_wird_nichts_angelegt():
    r = _post("/team/tailscale-einladen/anfordern", {"email": "kolleg@example.com"})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_gute_adresse_legt_eine_zeile_mit_status_offen_an():
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": "kolleg@example.com", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    zeilen = server._q(
        "select email, status, angefordert_von from admin_auftraege")
    assert len(zeilen) == 1
    assert zeilen[0]["email"] == "kolleg@example.com"
    assert zeilen[0]["status"] == "offen"
    assert zeilen[0]["angefordert_von"] == "betreiber-ui"


def test_seite_traegt_auffrischen_solange_ein_auftrag_offen_ist():
    server._q(
        "insert into admin_auftraege (art, email, angefordert_von) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' in r.text


def test_seite_traegt_kein_auffrischen_wenn_alles_erledigt_ist():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, erledigt_am) values "
        "('tailscale_einladen', 'kolleg@example.com', 'test', 'erfolg', now())")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' not in r.text


def test_seite_ohne_javascript():
    r = _get("/team/tailscale-einladen")
    assert "<script" not in r.text.lower()


def test_seite_zeigt_erfolgsergebnis_mit_echtem_json_ohne_absturz():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, ergebnis, erledigt_am) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test', 'erfolg', "
        "%s::jsonb, now())",
        ('{"inviteUrl": "https://login.tailscale.com/admin/invite/probe123"}',))
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert "probe123" in r.text


def test_seite_zeigt_fehlerergebnis_ohne_absturz():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, fehler, erledigt_am) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test', 'fehler', "
        "'HTTP 400: bereits eingeladen', now())")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert "bereits eingeladen" in r.text


def test_scharfe_anmeldung_traegt_den_echten_namen(scharf):
    _benutzer("lena")
    login = _post("/login", {"name": "lena", "passwort": "korrekt-pferd-9",
                             "csrf": ui.CSRF_TOKEN})
    assert login.status_code == 303
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": "kolleg@example.com", "csrf": ui.CSRF_TOKEN},
              client=TestClient(ui.app, cookies=login.cookies))
    assert r.status_code == 303
    zeilen = server._q("select angefordert_von from admin_auftraege")
    assert zeilen[0]["angefordert_von"] == "lena"
