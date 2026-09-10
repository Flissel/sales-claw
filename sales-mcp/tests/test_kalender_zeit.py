"""Vertragstests der Kalender-Zeitrechnung (Stufe 1).

Ein Termin hat EINE Uhrzeit. Dass dieselbe Buchung an zwei Stellen der
Oberflaeche zwei Uhrzeiten trug (19:00 und 21:00, gemessen 10.09.2026),
lag an zwei Wegen in dieselbe Anzeige: eigene Termine liegen als
Zeichenkette im Payload, CalDAV liefert Zeitstempel.
"""
import json
import os
import re
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


# --- Fix-Runde 1: Kritisch 1 — Verschmelzen NUR quellenuebergreifend ------

def test_zwei_eigene_termine_verschmelzen_nicht_miteinander():
    """Zwei ECHTE eigene Termine desselben Kontakts, wenige Minuten
    auseinander, mit aehnlichem Titel — duerfen NICHT zu einer Zeile mit
    quellen=['store', 'store'] werden. Verschmelzen gilt ausschliesslich
    quellenuebergreifend (eigen<->importiert), nie eigen<->eigen."""
    eigene = [
        {"titel": "Erstgespräch", "lead_id": "kontakt-1",
         "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
         "ort": "Büro", "quelle": "store"},
        {"titel": "Erstgespräch", "lead_id": "kontakt-1",
         "beginn": datetime(2026, 9, 5, 19, 3, tzinfo=timezone.utc),
         "ort": "Telefon", "quelle": "store"},
    ]
    paare = ui._termine_paaren(eigene, [])
    assert len(paare) == 2, f"erwartet 2 getrennte Eintraege, bekam {len(paare)}"
    assert all(p["quellen"] == ["store"] for p in paare)


def test_zwei_importierte_termine_verschmelzen_nicht_miteinander():
    """Dieselbe Grenze auch in die andere Richtung: zwei CalDAV-Eintraege
    duerfen nicht miteinander verschmelzen, nur mit einem eigenen."""
    importierte = [
        {"titel": "Termin", "beginn": datetime(2026, 9, 5, 19, 0,
                                               tzinfo=timezone.utc),
         "ort": "", "quelle": "caldav"},
        {"titel": "Termin", "beginn": datetime(2026, 9, 5, 19, 2,
                                               tzinfo=timezone.utc),
         "ort": "", "quelle": "caldav"},
    ]
    paare = ui._termine_paaren([], importierte)
    assert len(paare) == 2
    assert all(p["quellen"] == ["caldav"] for p in paare)


# --- Fix-Runde 1: Kritisch 2 — der gemergte Ort darf nicht verworfen werden

def test_paarung_uebernimmt_importierten_ort_wenn_eigener_leer():
    """Ist der eigene Ort leer und der importierte gesetzt, muss der
    gepaarte Eintrag den importierten Ort tragen — NICHT als
    'abweichend', sondern als der einzige, gueltige Ort."""
    eigene = [{"titel": "Erstgespräch",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "", "quelle": "store"}]
    importierte = [{"titel": "Erstgespräch",
                    "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
                    "ort": "https://meet.google.com/leer-ort",
                    "quelle": "caldav"}]
    paare = ui._termine_paaren(eigene, importierte)
    assert len(paare) == 1
    assert paare[0]["ort"] == "https://meet.google.com/leer-ort"
    assert "abweichend" not in paare[0]


# --- Fix-Runde 1: Wichtig 4 — Titelvergleich ohne feste Zeichengrenze ------

def test_langer_gemeinsamer_anfang_ohne_volles_praefix_wird_nicht_gepaart():
    """Zwei ECHTE, verschiedene Termine teilen sich mehr als zwanzig
    Zeichen Anfang — keiner ist vollstaendiger Praefix des anderen, also
    KEINE Paarung (Regression der alten 20-Zeichen-Schwelle)."""
    eigene = [{"titel": "Beratungsgespräch am Telefon mit Herrn Schmidt",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "", "quelle": "store"}]
    importierte = [{"titel": "Beratungsgespräch am Telefon mit Frau Weber",
                    "beginn": datetime(2026, 9, 5, 19, 1, tzinfo=timezone.utc),
                    "ort": "", "quelle": "caldav"}]
    assert len(ui._termine_paaren(eigene, importierte)) == 2


def test_kuerzerer_titel_als_vollstaendiges_praefix_wird_gepaart():
    """Store-Titel mit Zusatz in Klammern gegen den knapperen CalDAV-Titel
    bleibt gepaart, weil der kuerzere Titel vollstaendig Praefix ist."""
    eigene = [{"titel": "VibeMind Gespräch (Scalosoft)",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "", "quelle": "store"}]
    importierte = [{"titel": "VibeMind Gespräch",
                    "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
                    "ort": "", "quelle": "caldav"}]
    assert len(ui._termine_paaren(eigene, importierte)) == 1


# --- Fix-Runde 1: Wichtig 3 — der Seiten-Test muss den Pfad tatsaechlich
# durchlaufen. In der Testumgebung ist kein CALDAV_URL gesetzt, deshalb
# liefert kalender.termine_lesen() im echten Betrieb immer ([], None) — der
# Paarungs- und Badge-Pfad in kalender_seite waere sonst NIE erreicht und
# ein seite.count(...)-Check wuerde auch bei kaputter Logik gruen bleiben.
# Die CalDAV-Quelle wird deshalb hier ersetzt statt weggelassen.
#
# Das ersetzt nur den Rueckgabewert von termine_lesen(), NICHT die
# Konfiguration selbst: kalender_seite() prueft an anderer Stelle separat
# `kalender.konfiguration()[0]` (ui.py:3643) — das liest CALDAV_URL/-USER/
# -PASSWORT direkt aus der Umgebung und ist vom Monkeypatch hier unberuehrt.
# Deshalb zeigt die Seite trotz nicht-leerer Attrappe weiterhin „Kein
# Kalender verbunden" statt der rohen „Kalender (N)"-Tabelle — siehe die
# genauere Erklaerung unten bei der Zaehl-Pruefung.

def test_zwei_quellen_zeigt_hinweis_und_beide_orte(monkeypatch):
    """Wired: die Kalenderseite zeigt EINE Zeile mit dem Hinweis
    'zwei Quellen' und beiden abweichenden Ortsangaben."""
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('Stephane B.', '+491701234567', 'whatsapp') returning id")[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s::jsonb)",
        (lead, json.dumps(
            {"datum": "2026-09-05", "uhrzeit": "19:00",
             "thema": "Video Call mit Sophie & Stephane",
             "ort": "Video Call", "uid": "doppelt-1"})))
    monkeypatch.setattr(
        kalender, "termine_lesen",
        lambda *a, **k: ([{
            "beginn": datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc),
            "titel": "Video Call mit Sophie & Stephane",
            "ort": "https://meet.google.com/tin-jrqe-qwx",
            "uid": "caldav-x"}], None))
    seite = _get("/kalender").text
    assert "zwei Quellen" in seite, "Hinweis fehlt auf der Seite"
    assert "Video Call" in seite, "eigene Ortsangabe fehlt"
    assert "https://meet.google.com/tin-jrqe-qwx" in seite, (
        "importierte Ortsangabe fehlt — Quelle stillschweigend verworfen")
    # Aufgabe 7 (10.09.2026): Terminkarten tragen den vollen Text jetzt
    # zusaetzlich als `title`-Attribut (Kuerzung an Wortgrenzen). Dasselbe
    # Thema steht dadurch an JEDER Anzeigestelle bewusst zweimal — sichtbar
    # (ggf. gekuerzt) UND voll im title. Ein reiner `seite.count(...)` auf
    # den escapten Volltext zaehlt damit auch legitime title-Wiederholungen
    # mit und kann eine echte Doppelrenderung nicht mehr von der Kuerzung
    # unterscheiden (siehe Fix-Runde 2, Bericht Aufgabe 7).
    #
    # Praeziser (Fix-Runde 3 — der Grund war zuvor falsch benannt): die
    # separate rohe „Kalender"-Tabelle (reine CalDAV-Liste, `t["titel"]`
    # UNGEKUERZT) rendert hier NICHT etwa, weil termine_lesen() oben leer
    # waere — die Attrappe liefert bewusst einen echten Eintrag. Sie bleibt
    # aus, weil kalender_seite() VOR dieser Tabelle separat
    # `kalender.konfiguration()[0]` prueft (ui.py:3643) — das liest
    # CALDAV_URL/-USER/-PASSWORT direkt aus der Prozessumgebung, unabhaengig
    # vom `termine_lesen`-Ruecklauf, und ist in dieser Umgebung nicht
    # gesetzt. Deshalb bleibt genau EIN Ort uebrig, an dem eine doppelt
    # gerenderte BUCHUNG als doppelte Tabellenzeile sichtbar wuerde: die
    # Kommende/Vergangen-Tabelle (die vom Monatsgitter unabhaengige
    # „Liste"). Das Gitter selbst zeigt fuer einen gepaarten Termin
    # ABSICHTLICH zwei Kaestchen (eigene + CalDAV-Quelle, Aufgabe 4) — das
    # ist keine Dopplung, sondern Design, und wird hier bewusst nicht
    # mitgezaehlt (das Gitter ist `<div>`-basiert, `<tr>` kommt dort nicht
    # vor).
    #
    # Wichtig fuer spaeter: diese Zaehlung `== 1` haengt an genau dieser
    # Konfigurationssperre. Faellt `kalender.konfiguration()[0]` weg (oder
    # wird hier zusaetzlich gemockt, sodass sie erfuellt ist), rendert die
    # rohe „Kalender"-Tabelle MIT — leer nachgemessen: ein zweites,
    # LEGITIMES `<tr>` mit demselben Volltext kommt hinzu, `len(treffer)`
    # steigt von 1 auf 2, und dieser Test schlaegt fehl, OHNE dass irgendein
    # Bug vorliegt. Wer `konfiguration()` in `kalender_seite` aendert oder
    # entfernt, muss diese Zaehlung dann auf die Kommende/Vergangen-Tabelle
    # einschraenken (statt auf alle `<tr>` der Seite), sonst verliert der
    # Test entweder seine Trennschaerfe oder faengt sich einen falschen
    # Fehlschlag ein.
    zeilen_html = re.findall(r"<tr>.*?</tr>", seite, flags=re.S)
    treffer = [z for z in zeilen_html
              if "Video Call mit Sophie &amp; Stephane" in z]
    assert len(treffer) == 1, (
        f"der Termin steht in {len(treffer)} Tabellenzeilen statt einer "
        "— echte Doppelrenderung in Kommende/Vergangen")


def test_zwei_quellen_mit_leerem_eigenem_ort_verwirft_importierten_ort_nicht(
        monkeypatch):
    """Kritisch 2 direkt am gerenderten HTML: der eigene Ort ist leer, nur
    der importierte ist gesetzt. Die Zeile darf keine leere Ortsspalte
    zeigen, waehrend sie 'zwei Quellen' behauptet."""
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('Ohne Ort', '+491709999999', 'whatsapp') returning id")[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s::jsonb)",
        (lead, json.dumps(
            {"datum": "2026-09-05", "uhrzeit": "19:00",
             "thema": "Erstgespräch ohne Ort",
             "ort": "", "uid": "doppelt-2"})))
    monkeypatch.setattr(
        kalender, "termine_lesen",
        lambda *a, **k: ([{
            "beginn": datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc),
            "titel": "Erstgespräch ohne Ort",
            "ort": "https://meet.google.com/nur-caldav",
            "uid": "caldav-y"}], None))
    seite = _get("/kalender").text
    assert "zwei Quellen" in seite
    assert "https://meet.google.com/nur-caldav" in seite, (
        "der einzige Ort (aus CalDAV) wurde stillschweigend verworfen, "
        "weil die Anzeige noch die leere eigene Zeile gelesen hat")
