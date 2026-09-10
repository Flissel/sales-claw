"""Vertragstests der Kalender-Zeitrechnung (Stufe 1).

Ein Termin hat EINE Uhrzeit. Dass dieselbe Buchung an zwei Stellen der
Oberflaeche zwei Uhrzeiten trug (19:00 und 21:00, gemessen 10.09.2026),
lag an zwei Wegen in dieselbe Anzeige: eigene Termine liegen als
Zeichenkette im Payload, CalDAV liefert Zeitstempel.
"""
import json
import os
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402
import kalender  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.leads cascade")
    yield


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def test_naiver_zeitstempel_wird_als_utc_gelesen():
    """Ein Zeitstempel ohne Zone gilt als UTC und wird nach Berlin gerechnet.

    19:00 UTC sind im September 21:00 in Berlin. Vorher blieb ein naiver
    Zeitstempel ungerechnet stehen — daher zwei Uhrzeiten fuer eine Buchung.
    """
    naiv = datetime(2026, 9, 5, 19, 0, 0)
    assert ui._zeit(naiv).endswith("21:00"), (
        f"naiver Zeitstempel wurde nicht umgerechnet: {ui._zeit(naiv)}")


def test_bewusster_zeitstempel_wird_nicht_doppelt_gerechnet():
    """Ein Zeitstempel MIT Zone wird genau einmal umgerechnet."""
    bewusst = datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc)
    assert ui._zeit(bewusst).endswith("21:00")


# ---------------------------------------------------------------------------
# Messung (Schritt 1 des Berichts, Aufgabe 3): was liefert kalender._ics_zeit
# fuer die drei moeglichen DTSTART-Formen aus RFC 5545 3.3.5?
#
# Ergebnis vor dieser Aufgabe (gemessen 10.09.2026, python -c am Code, kein
# CalDAV-Server verfuegbar): `_ics_feld` liest ausschliesslich den Wert nach
# dem letzten ":" und verwirft dabei jeden Parameter — auch TZID. `_ics_zeit`
# haengte an JEDEN so gelesenen Wert ohne 'Z'-Suffix blind UTC an. Ein
# `TZID=Europe/Berlin:...T190000` (19:00 ORTSZEIT) wurde dadurch als 19:00
# UTC gelesen — zwei Stunden zu spaet (Europe/Berlin ist im September UTC+2,
# CEST). `ui._zeit()` rechnete diesen falsch gelesenen Zeitpunkt anschliessend
# nach Berlin zurueck: 21:00. Exakt der gemessene Versatz aus dem Titel dieser
# Aufgabe, UND exakt das Muster, das die bestehenden CalDAV-Lesetests in
# tests/test_termin.py bereits als Testdaten verwenden (TZID=Europe/Berlin,
# u. a. fuer "Video Call mit Sophie & Stephane") — der reale Kalender liefert
# also nachweislich Fall 2, nicht Fall 1 (UTC mit 'Z').
#
# Ohne Aenderung an kalender.py bliebe der Kalender-Tab deshalb falsch,
# selbst nachdem ui._zeit() (oben) repariert ist: der CalDAV-Zeitstempel
# TRUG schon vorher ein tzinfo (kalender._ics_zeit setzte es immer, nur
# falsch) und durchlief damit auch VOR dieser Aufgabe bereits den
# astimezone()-Zweig von ui._zeit() — der Fehler steckte in der falsch
# gelesenen Zone, nicht im fehlenden tzinfo. Deshalb aendert diese Aufgabe
# zusaetzlich zu ui.py auch kalender.py (kalender._ics_zeit, _ics_tzid).
# ---------------------------------------------------------------------------

def test_ics_zeit_utc_mit_z_bleibt_utc():
    """Fall 1 — `DTSTART:20260905T170000Z`: bereits UTC, keine Umrechnung."""
    ergebnis = kalender._ics_zeit("20260905T170000Z")
    assert ergebnis == datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)


def test_ics_zeit_mit_tzid_wird_aus_der_ortszeit_nach_utc_gerechnet():
    """Fall 2 — `DTSTART;TZID=Europe/Berlin:20260905T190000`: 19:00 ist
    ORTSZEIT (Berlin), nicht UTC. Das ist der real gemessene Fall."""
    ergebnis = kalender._ics_zeit("20260905T190000", tzid="Europe/Berlin")
    assert ergebnis == datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)


def test_ics_zeit_floating_time_gilt_als_ortszeit():
    """Fall 3 — `DTSTART:20260905T190000` ohne 'Z' und ohne TZID
    ("floating time", RFC 5545 3.3.5): gilt als Ortszeit, nicht als UTC."""
    ergebnis = kalender._ics_zeit("20260905T190000")
    assert ergebnis == datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)


def test_tzid_termin_zeigt_dieselbe_uhrzeit_wie_der_eigene_termin():
    """Ende-zu-Ende der Produktionssymptom-Kette: ein CalDAV-Termin mit
    TZID=Europe/Berlin:...T190000 zeigt nach kalender._ics_zeit +
    ui._zeit() 19:00 — dieselbe Uhrzeit wie ein eigener Termin mit
    uhrzeit='19:00' in der Vergangen-Tabelle, nicht 21:00."""
    beginn = kalender._ics_zeit("20260905T190000", tzid="Europe/Berlin")
    assert ui._zeit(beginn).endswith("19:00")


# ---------------------------------------------------------------------------
# Aufgabe 4: doppelte Termine aus zwei Quellen als EIN Eintrag mit dem
# Hinweis "zwei Quellen" — Betreiber-Entscheidung (Spec Sec3.3): nicht
# automatisch zusammenfuehren, beide Quellen bleiben Wahrheit.
# ---------------------------------------------------------------------------

def test_gleicher_termin_aus_zwei_quellen_wird_ein_eintrag():
    """Eigener Store und Kalender-Import ergeben EINEN Eintrag."""
    eigene = [{"titel": "Video Call mit Sophie & Stephane",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "Video Call", "quelle": "store"}]
    importierte = [{"titel": "Video Call mit Sophie & Stephane",
                    "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
                    "ort": "https://meet.google.com/tin-jrqe-qwx",
                    "quelle": "caldav"}]
    paare = ui._termine_paaren(eigene, importierte)
    assert len(paare) == 1, f"erwartet 1 Eintrag, bekam {len(paare)}"
    assert sorted(paare[0]["quellen"]) == ["caldav", "store"]


def test_verschiedene_termine_bleiben_getrennt():
    """Unterschiedliche Startzeiten werden NICHT zusammengezogen."""
    eigene = [{"titel": "Erstgespräch",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "", "quelle": "store"}]
    importierte = [{"titel": "Erstgespräch",
                    "beginn": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc),
                    "ort": "", "quelle": "caldav"}]
    assert len(ui._termine_paaren(eigene, importierte)) == 2


def test_zwei_quellen_werden_in_der_seite_ausgewiesen():
    """Der Hinweis steht sichtbar am Eintrag, nicht nur in den Daten."""
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('Stephane B.', '+491701234567', 'whatsapp') returning id")[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s::jsonb)",
        (lead, json.dumps(
            {"datum": "2026-09-05", "uhrzeit": "21:00",
             "thema": "Video Call mit Sophie & Stephane",
             "ort": "Video Call", "uid": "doppelt-1"})))
    seite = _get("/kalender").text
    assert seite.count("Video Call mit Sophie &amp; Stephane") <= 2, (
        "derselbe Termin steht mehr als zweimal auf der Seite "
        "(Gitter + Liste sind erlaubt)")
