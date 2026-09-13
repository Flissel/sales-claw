"""Der Kollege verbindet selbst — Spec §2.7, Pruefung 1 (Torschritt)."""
import os

import psycopg
import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalenderquellen  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
# RED-Befund (Umsetzer, Task 5): ohne expliziten Host-Header antwortet die
# HostWache mit 421 (Falscher Host) — TestClient() setzt sonst "testserver"
# als Host. Jede andere Testdatei hier (test_freigaben.py, test_heute.py,
# test_darstellung.py, ...) setzt deshalb denselben Header von Hand; der
# Plantext hatte ihn hier vergessen.
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(daten):
    return CLIENT.post("/team/kalender/verbinden", data=daten,
                       headers={"host": HOST_OK}, follow_redirects=False)


def test_seite_erklaert_den_weg_je_anbieter():
    seite = _get("/team/kalender").text
    assert "Google" in seite and "Apple" in seite and "Outlook" in seite
    # Der genaue Klickweg, nicht nur der Name des Anbieters.
    assert "Geheime Adresse im iCal-Format" in seite


def test_verbinden_meldet_die_zahl_der_termine(monkeypatch):
    """Der Kern von §2.7: sofortige Rueckmeldung im Klartext."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": __import__("datetime").datetime(2026, 10, 1, 9,
         tzinfo=__import__("datetime").timezone.utc),
         "ende": __import__("datetime").datetime(2026, 10, 1, 10,
         tzinfo=__import__("datetime").timezone.utc),
         "titel": "A", "ort": "", "uid": "x"}], None))
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    assert "1 Termin" in antwort.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"


def test_falscher_link_wird_benannt_nicht_nur_abgewiesen(monkeypatch):
    """Der haeufigste Bedienfehler. 'Ungueltig' hilft niemandem weiter."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: (
        [], "Dort liegt kein Kalender, sondern eine Webseite."))
    antwort = _post({"name": "Ivan", "url": "https://example.test/",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200
    assert "Webseite" in antwort.text
    assert server.kalenderquellen_lesen() == []


def test_die_adresse_erscheint_nach_dem_speichern_nirgends(monkeypatch):
    """Spec §4: sie ist ein Schluessel, kein Anzeigewert — auch nicht fuer
    den Betreiber."""
    geheim = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    _post({"name": "Ivan", "url": geheim, "csrf": ui.CSRF_TOKEN})
    assert "GEHEIM123" not in _get("/team/kalender").text


def test_ohne_csrf_passiert_nichts():
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics"})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen() == []


def test_leerer_name_wird_abgewiesen(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    antwort = _post({"name": "  ", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen() == []


def test_rolle_kalender_darf_die_seite_und_sonst_nichts():
    """Die vorhandene Rolle `lesen` 'sieht alles' — also auch saemtliche
    Kontakte und den Posteingang. Fuer einen Kollegen ist das zu viel."""
    assert ui._pfad_erlaubt("kalender", "/team/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kontakte") is False
    assert ui._pfad_erlaubt("kalender", "/posteingang") is False
    assert ui._pfad_erlaubt("kalender", "/freigaben") is False
    assert ui._pfad_erlaubt("lesen", "/kontakte") is True


def test_db_fehler_beim_speichern_traegt_die_adresse_nicht_nach_aussen(
        monkeypatch):
    """Aufgabe 1, offener Punkt: ein unbehandelter Datenbankfehler aus den
    Kalenderquellen-Helfern darf die geheime Adresse nicht in die
    Fehlerseite tragen — auch nicht ueber die DB-Fehlermeldung (DETAIL
    einer Unique-Verletzung nennt z.B. den Wert der Spalte)."""
    geheim = "https://calendar.google.com/ical/GEHEIM999/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))

    def _wirft(name, url):
        raise psycopg.errors.UniqueViolation(
            f"duplicate key value violates unique constraint "
            f'"kalender_quellen_url_key" DETAIL: Key (url)=({geheim}) '
            f"already exists.")
    monkeypatch.setattr(server, "kalenderquelle_speichern", _wirft)
    antwort = _post({"name": "Ivan", "url": geheim, "csrf": ui.CSRF_TOKEN})
    assert geheim not in antwort.text
    assert "GEHEIM999" not in antwort.text
