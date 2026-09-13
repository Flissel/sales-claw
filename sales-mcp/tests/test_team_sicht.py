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
    wie test_kalender_verbinden.py::leer). `activities`/`leads` dazu (Fix-
    Runde 2, WICHTIG 1): der neue Paarungstest legt einen echten CRM-Termin
    an — ohne Truncate wuerde er in andere Testdateien durchsickern (Muster
    wie test_kalender_zeit.py::leer)."""
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen, "
                     "sales_test.activities, sales_test.leads cascade")
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


def test_monatsgitter_nennt_die_quelle():
    """W2 (Schlusspruefung 13.09.2026): der bisherige Seiten-Test
    (test_fremder_termin_traegt_den_namen oben) prueft nur 'Ivan' IRGENDWO
    auf der Seite — das trifft schon durch die LISTE weiter unten zu,
    waehrend das GITTER (das Bild, auf das ein Mensch tatsaechlich schaut)
    den Namen gar nicht trug: ein Kollegentermin war dort von einem
    eigenen CalDAV-Eintrag nicht zu unterscheiden. Direkt gegen das
    Gitter-HTML, nicht gegen die ganze Seite."""
    fremd = [{"beginn": datetime(2026, 9, 5, 9, tzinfo=timezone.utc),
              "ende": datetime(2026, 9, 5, 10, tzinfo=timezone.utc),
              "titel": "Kundentermin", "ort": "", "quelle": "Ivan"}]
    gitter = ui._monatsgitter((2026, 9), [], fremd)
    assert "Ivan" in gitter
    # Sowohl inline als auch im Tooltip, nicht nur an einer der beiden
    # Stellen (die Notiz im Ledger hatte behauptet, es stuende "nur im
    # Tooltip" — dort stand es tatsaechlich an KEINER der beiden Stellen).
    assert 'title="Ivan: Kundentermin"' in gitter
    assert "Ivan: Kundentermin</span>" in gitter


def test_monatsgitter_beschriftet_die_eigenen_termine_nicht(monkeypatch):
    """Koordinator-Fix-Runde (13.09.2026): `fremde` traegt auch die
    eigenen CalDAV-Termine (quelle == server.EIGENE_QUELLE) — die W2-Fix
    hatte sie faelschlich mit "Betreiber: ..." beschriftet. Der eigene
    Kalender braucht im eigenen Kalender keine Beschriftung; der Titel
    soll dabei auch nicht unnoetig auf 16 statt 22 Zeichen gekuerzt
    werden."""
    eigen = [{"beginn": datetime(2026, 9, 5, 9, tzinfo=timezone.utc),
             "ende": datetime(2026, 9, 5, 10, tzinfo=timezone.utc),
             "titel": "Eigener Kundentermin", "ort": "",
             "quelle": server.EIGENE_QUELLE}]
    gitter = ui._monatsgitter((2026, 9), [], eigen)
    assert "Betreiber:" not in gitter
    assert 'title="Eigener Kundentermin"' in gitter
    assert "Eigener Kundentermin</span>" in gitter


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


def test_kollegentermin_wird_nicht_mit_crm_termin_verschmolzen(monkeypatch):
    """Fix-Runde 2 (Pruefung, WICHTIG 1): 'zwei Quellen' darf nur heissen,
    dass DIESELBE Buchung im CRM UND im EIGENEN Kalender des Betreibers
    steht — nicht, dass ein CRM-Termin zufaellig aehnlich zu EINEM
    KOLLEGENTERMIN liegt. Sonst verschluckt die Paarung Ivans eigene Zeile
    und genau die Information, fuer die die Team-Sicht gebaut wurde (dass
    Ivan zu dieser Zeit belegt ist), geht verloren."""
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('Kollisionstest', '+491701112233', 'whatsapp') returning id"
    )[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s)",
        (lead, server._json({
            "datum": "2026-09-05", "uhrzeit": "19:00",
            "thema": "Video Call mit Sophie & Stephane",
            "ort": "Büro", "uid": "crm-1"})))
    monkeypatch.setattr(server, "belegungen", _belegt({
        "beginn": datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc),
        "ende": datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc),
        "titel": "Video Call mit Sophie & Stephane",
        "ort": "https://meet.google.com/ivan", "quelle": "Ivan"}))
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    seite = antwort.text
    assert "zwei Quellen" not in seite, (
        "Ivans Termin wurde mit dem CRM-Termin verschmolzen statt eine "
        "eigene Zeile zu bleiben")
    assert "Ivan" in seite


def test_verbunden_aber_leer_ist_nicht_dasselbe_wie_nichts_verbunden(
        monkeypatch):
    """Fix-Runde 2 (Pruefung, WICHTIG 2): eine aktive Quelle, die gerade
    null Termine liefert, ist etwas anderes als 'nichts verbunden' — sonst
    genau die Verwechslung, die Fix-Runde 1 fuer den umgekehrten Fall schon
    behoben hat."""
    server.kalenderquelle_speichern(
        "Ivan", "https://calendar.example.invalid/ivan.ics")
    monkeypatch.setattr(server, "belegungen", _belegt())
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    seite = antwort.text
    assert "Kein Kalender verbunden" not in seite
    assert "Keine Einträge im Zeitfenster." in seite
