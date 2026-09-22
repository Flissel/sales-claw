"""Vertragstests: ein offener Entwurf blockiert den naechsten (29.08.2026).

Befund am 29.08.: Ivan hatte DREI wartende Entwuerfe (44 h, 24 h, 12 h
alt), waehrend neun andere Kontakte gar keinen bekamen. `antworten_faellig`
zaehlt unbeantwortete KUNDENnachrichten — ein Entwurf, den noch niemand
freigegeben hat, beantwortet nichts, also blieb der Kontakt faellig und
bekam bei jedem Lauf einen weiteren Entwurf.

ZWEI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Solange ein Entwurf auf Freigabe wartet, entsteht fuer diesen Kontakt
   kein zweiter. Der Ball liegt beim Menschen, nicht beim Agenten.
2. Das Ueberspringen wird GEZAEHLT und benannt — eine stille Auslassung
   sieht aus wie „niemand wartet", und genau das war der Fehler.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _wartender(name="Wanda Wartend", phone="+491702223344"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, %s, 'whatsapp') returning id", (name, phone))[0]["id"])
    server.kontakt_freigeben(lead)
    # `auto` statt `halbauto` seit 22.09.2026: die Faelligkeitsliste
    # nimmt nur noch ausdruecklich automatische Kontakte. Dieser Test
    # prueft etwas anderes — er braucht hier bloss einen Kontakt, der
    # ueberhaupt in der Liste steht.
    server.kontakt_autonomie_setzen(lead, "auto")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'kundenantwort', %s) returning id",
        (lead, server._json({"text": "Passt Donnerstag?"})))
    return lead


def _faellige_ids():
    d = json.loads(server.antworten_faellig())
    return {str(e["lead_id"]) for e in d["eintraege"]}


def test_ohne_entwurf_steht_der_kontakt_in_der_liste():
    lead = _wartender()
    assert lead in _faellige_ids()


def test_ein_wartender_entwurf_nimmt_den_kontakt_heraus():
    lead = _wartender()
    server.entwurf_erstellen(lead, "whatsapp", "Donnerstag passt mir gut.")
    assert lead not in _faellige_ids()


def test_das_ueberspringen_wird_benannt():
    lead = _wartender()
    server.entwurf_erstellen(lead, "whatsapp", "Donnerstag passt mir gut.")
    d = json.loads(server.antworten_faellig())
    assert d["uebersprungen_weil_entwurf_offen"] == 1
    assert "wartet" in d["hinweis"].lower() or "freigabe" in d["hinweis"].lower()


def test_nach_der_freigabe_ist_der_kontakt_nicht_mehr_faellig():
    """Freigegeben heisst: der Dispatcher stellt zu — der Kunde bekommt
    seine Antwort. Ein zweiter Entwurf waere doppelt."""
    lead = _wartender()
    d = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Ja, gerne."))
    server.entwurf_freigeben(d["draft_id"])
    assert lead not in _faellige_ids()


def test_ein_abgelehnter_entwurf_haelt_bis_der_kunde_wieder_schreibt():
    """UMGEDREHT am 03.09.2026 (Betreiber: „es werden immer wieder Entwuerfe
    gemacht, die ich abgelehnt hatte"): Abgelehnt heisst, der Betreiber will
    auf DIESE Nachricht keine Antwort — kein neuer Versuch, bis der Kunde
    wieder schreibt. Ausfuehrlich: tests/test_ablehnung_haelt.py."""
    lead = _wartender()
    d = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Unpassend."))
    server.entwurf_ablehnen(d["draft_id"])
    assert lead not in _faellige_ids()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "Und nun?"})))
    assert lead in _faellige_ids()


def test_ein_entwurf_an_einen_anderen_kontakt_blockiert_nicht():
    a = _wartender("Anton", "+491701111111")
    b = _wartender("Berta", "+491702222222")
    server.entwurf_erstellen(a, "whatsapp", "Antwort fuer Anton.")
    ids = _faellige_ids()
    assert a not in ids and b in ids
