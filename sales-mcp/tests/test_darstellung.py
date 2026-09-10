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


def _post(pfad, daten, host=HOST_OK):
    return CLIENT.post(pfad, data=daten, headers={"host": host},
                       follow_redirects=False)


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
#
# Fix-Runde 2 (10.09.2026): ganze Woerter allein liessen Wortformen wie
# 'geaendert'/'unveraendert' oder 'ausgefuehrt' durchrutschen — keines der
# damaligen 25 Woerter ist Teilstring davon. Die untere Zeile ergaenzt
# Wortstaemme, die mehrere Formen auf einmal fangen, geprueft gegen echte
# Bezeichner in ui.py (Formularfeld-Namen, Routen), damit kein Stamm einen
# Bezeichner faelschlich trifft: 'bestaetig' etwa kollidiert mit
# `name="bestaetigt"`/`name="name_bestaetigt"` und bleibt deshalb draussen —
# 'Bestaetigung' (Grossschreibung, laengere Form) faengt denselben Fehler,
# ohne das Formularfeld zu treffen.
WOERTER_ASCII = [
    "aelteste", "naechste", "oeffnen", "Entwuerfe", "Entwuerfen",
    "Oberflaeche", "laedt", "Aendern", "aendern", "Groesse", "Loeschen",
    "loeschen", "gehoert", "klaert", "noetig", "moeglich", "zurueck",
    "Verlaeufe", "heisst", "Eingaenge", "Faellig", "Rueckruf",
    "Begruendung", "ausdruecklich", "Schluessel",
    # Wortstaemme (Fix-Runde 2): fangen Wortformen, die die Woerter oben
    # nicht als Teilstring enthalten.
    "aender", "Aender", "gueltig", "waehl", "staendig", "pruef",
    "ausgefuehr", "Bestaetigung",
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


def test_csrf_fehlerseite_zeigt_echte_umlaute():
    """Der meisterreichte Fehlerpfad der ganzen Oberflaeche — ein POST ohne
    gueltiges CSRF-Token — steht auf keiner der zehn GET-Seiten und blieb
    deshalb in Fix-Runde 1 unentdeckt ASCII (Fix-Runde 2, 10.09.2026)."""
    antwort = _post("/aktion/freigeben",
                    {"draft_id": "00000000-0000-0000-0000-000000000000",
                     "csrf": "falsch"})
    seite = antwort.text
    gefunden = [w for w in WOERTER_ASCII if w in seite]
    assert not gefunden, (
        f"CSRF-Fehlerseite zeigt ASCII-Umschreibungen: {gefunden}")


def test_whatsapp_seite_nennt_aktive_und_archivierte_getrennt():
    """Zwei Zahlen, zwei Namen — nicht zweimal 'Kontakte'.

    Der Archiv-Schluessel ist verschachtelt (`enrichment -> ARCHIV_SCHLUESSEL
    -> 'archiviert'`, siehe `server._archiv_sql`/`server.ARCHIV_SCHLUESSEL`),
    nicht der flache `{"archiviert": true}` aus der ersten Fassung dieses
    Tests — der schrieb am Merkmal vorbei und zaehlte den Kontakt weiterhin
    als aktiv. `archiviert` ist hier ein echter jsonb-Boolean (`true`), keine
    Zeichenkette, damit die `jsonb_typeof`-Pruefung in `_archiv_sql` greift."""
    _lead("Aktiv Eins")
    archiv = _lead("Archiviert Eins")
    server._q(
        "update leads set enrichment = coalesce(enrichment, '{}'::jsonb) || "
        "jsonb_build_object(%s::text, jsonb_build_object('archiviert', true)) "
        "where id = %s", (server.ARCHIV_SCHLUESSEL, archiv))
    seite = _get("/whatsapp").text
    assert "1 aktive Kontakte" in seite or "1 aktiver Kontakt" in seite, (
        "die WhatsApp-Seite benennt die aktiven Kontakte nicht")
    assert "1 archiviert" in seite, (
        "die archivierten Kontakte werden nicht getrennt ausgewiesen")


def test_pipeline_hat_genau_eine_ueberschrift():
    seite = _get("/pipeline").text
    assert seite.count("<h1") == 1, (
        f"{seite.count('<h1')} h1-Elemente auf /pipeline, erwartet 1")


def test_favicon_wird_beantwortet():
    """Kein 404 bei jedem Seitenaufruf."""
    antwort = _get("/favicon.ico")
    assert antwort.status_code in (200, 204), (
        f"/favicon.ico antwortet mit {antwort.status_code}")
