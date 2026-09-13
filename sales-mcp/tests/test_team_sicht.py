"""Fremde Termine erscheinen benannt — Spec §2.5, Pruefung 2."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
# Wie test_kalender_verbinden.py (Aufgabe 5, RED-Befund des Umsetzers): ohne
# expliziten Host-Header antwortet die HostWache mit 421 (Falscher Host) —
# TestClient() setzt sonst "testserver" als Host, und jede Zusicherung liefe
# in Wirklichkeit gegen die Fehlerseite statt gegen die Kalenderseite.
HOST_OK = "127.0.0.1:8791"


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


@pytest.fixture(autouse=True)
def ohne_kollegenquellen():
    """`kalenderquellen_lesen()` fragt echte Zeilen ab — ohne eigene
    Aufraeumung koennten liegen gebliebene Zeilen anderer Testdateien den
    'nichts verbunden'-Test unten faelschlich gruen ODER rot machen (Muster
    wie test_kalender_verbinden.py::leer)."""
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def _bald(stunden):
    return datetime.now(timezone.utc) + timedelta(hours=stunden)


def _belegt(*eintraege, luecken=()):
    return lambda tage_voraus=60: (list(eintraege), list(luecken))


def test_fremder_termin_traegt_den_namen(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        {"beginn": _bald(24), "ende": _bald(25), "titel": "Kundentermin",
         "ort": "", "quelle": "Ivan"}))
    antwort = _get("/kalender")
    # Zusicherung auf einer 421/404-Seite beweist nichts (Aufgabe 5) — erst
    # sicherstellen, dass wirklich die Kalenderseite geantwortet hat.
    assert antwort.status_code == 200
    seite = antwort.text
    assert "Kundentermin" in seite
    assert "Ivan" in seite


def test_stumme_quelle_wird_auf_der_seite_genannt(monkeypatch):
    """Eine Luecke, die niemand sieht, ist schlimmer als keine Sicht."""
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    seite = antwort.text
    assert "Ivan" in seite
    assert "erreichbar" in seite


def test_fremddaten_erscheinen_escaped(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        {"beginn": _bald(24), "ende": _bald(25),
         "titel": "<script>alert(1)</script>", "ort": "",
         "quelle": "<b>Ivan</b>"}))
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    seite = antwort.text
    assert "<script>alert(1)</script>" not in seite
    assert "&lt;script&gt;" in seite
    assert "<b>Ivan</b>" not in seite


def test_ohne_jede_quelle_sagt_die_seite_es_statt_zu_schweigen(monkeypatch):
    """Fix-Runde 1 (Auftraggeber-Frage): nichts konfiguriert, nichts
    verbunden — vorher gab es dafuer die Meldung 'Kein Kalender verbunden
    (CALDAV_URL in der .env)'. Mit dem entfernten Konfigurations-Tor sah
    dieser Zustand genauso aus wie 'alles verbunden, aber gerade nichts
    los' ('Keine Eintraege im Zeitfenster.') — eine Seite, die schweigt,
    obwohl sie weiss, dass keine einzige Quelle angeschlossen ist, ist
    schlechter als eine, die es sagt."""
    monkeypatch.setattr(server, "belegungen", _belegt())
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    seite = antwort.text
    assert "Kein Kalender verbunden" in seite
    assert "Keine Einträge im Zeitfenster." not in seite
