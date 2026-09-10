"""Vertragstests der Darstellung (Stufe 1): Escaping, Umlaute, Kuerzung, Zaehlungen.

Diese Datei prueft nicht, WAS die Oberflaeche kann, sondern ob das, was sie
zeigt, stimmt: ein kaufmaennisches Und bleibt ein kaufmaennisches Und, ein
Umlaut bleibt ein Umlaut, ein Satz endet nicht mitten im Wort.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def _lead(name="Max Bestand"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491701234567', 'whatsapp') returning id", (name,))[0]["id"])


def _termin_aktivitaet(lead_id, datum="2026-09-05", uhrzeit="19:00",
                       thema="Video Call mit Sophie & Stephane", ort=""):
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'termin', %s::jsonb)",
        (lead_id, json.dumps(
            {"datum": datum, "uhrzeit": uhrzeit, "thema": thema, "ort": ort,
             "uid": f"test-{datum}-{uhrzeit}"})))


def test_kaufmaennisches_und_erscheint_einmal_escapet():
    """`&` im Termin-Thema wird genau einmal escapet — nie `&amp;amp;`."""
    _termin_aktivitaet(_lead("Stephane B."))
    seite = _get("/kalender").text
    assert "&amp;amp;" not in seite, "doppelt escapet"
    assert "&amp;amp\\;" not in seite, "dreifach escapet"
    assert "Sophie &amp; Stephane" in seite, (
        "das kaufmaennische Und fehlt oder ist falsch escapet")


# Wortliste statt Regex auf `ae|oe|ue`: ein Muster wuerde bei jedem
# englischen Wort und jeder E-Mail-Adresse anschlagen. Diese Liste
# enthaelt nur Woerter, die in der laufenden Oberflaeche gemessen wurden.
WOERTER_ASCII = [
    "aelteste", "naechste", "oeffnen", "Entwuerfe", "Entwuerfen",
    "Oberflaeche", "laedt", "Aendern", "aendern", "Groesse", "Loeschen",
    "loeschen", "gehoert", "klaert", "noetig", "moeglich", "zurueck",
    "Verlaeufe", "heisst", "Eingaenge", "Faellig", "Rueckruf",
    "Begruendung", "ausdruecklich", "Schluessel",
]

SEITEN = ["/", "/freigaben", "/einordnung", "/kalender", "/kontakte",
          "/pipeline", "/ergebnisse", "/posteingang", "/medien", "/whatsapp"]


@pytest.mark.parametrize("pfad", SEITEN)
def test_seite_zeigt_echte_umlaute(pfad):
    """Keine ASCII-Umschreibung erreicht den Browser."""
    lead = _lead("Ena Ottenschläger")
    _termin_aktivitaet(lead)
    seite = _get(pfad).text
    gefunden = [w for w in WOERTER_ASCII if w in seite]
    assert not gefunden, (
        f"{pfad} zeigt ASCII-Umschreibungen: {gefunden}")
