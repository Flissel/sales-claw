"""Vertragstests: eine Ablehnung haelt den Bot zurueck (03.09.2026).

Betreiber: „es werden immer wieder Entwuerfe gemacht, die ich abgelehnt
hatte — das soll dazu fuehren, dass der Bot nicht mehr drauf eingeht."
Gemessen: `antworten_faellig` zaehlte unbeantwortete Kundennachrichten und
uebersprang nur Kontakte mit offenem (pending/approved) Entwurf. Ein
abgelehnter Entwurf beantwortet nichts — der Kontakt blieb faellig und bekam
beim naechsten Lauf denselben Entwurf noch einmal.

Regel seitdem: Liegt fuer die juengste Kundennachricht eine Ablehnung vor
(ein abgelehnter Entwurf, der NACH ihr entstand), setzt der Bot nicht neu
an. Erst wenn der Kunde wieder schreibt, ist der Kontakt wieder faellig.
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


def _wartender(name="Wanda Wartend", phone="+491702223344", vor_minuten=60):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, %s, 'whatsapp') returning id", (name, phone))[0]["id"])
    server.kontakt_freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "halbauto")
    _kundenantwort(lead, "Passt Donnerstag?", vor_minuten)
    return lead


def _kundenantwort(lead, text, vor_minuten):
    server._q(
        "insert into activities (lead_id, type, payload, created_at) values "
        "(%s, 'kundenantwort', %s::jsonb, now() - (%s || ' minutes')::interval) "
        "returning id", (lead, json.dumps({"text": text}), str(vor_minuten)))


def _entwurf(lead, vor_minuten=0):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, created_at) "
        "values (%s, 'whatsapp', '+491702223344', 'Entwurf', 'pending', "
        "now() - (%s || ' minutes')::interval) returning id",
        (lead, str(vor_minuten)))[0]["id"])


def test_abgelehnter_entwurf_haelt_den_bot_zurueck():
    lead = _wartender()
    draft = _entwurf(lead, vor_minuten=30)
    antwort = json.loads(server.entwurf_ablehnen(draft))
    assert "fehler" not in antwort
    daten = json.loads(server.antworten_faellig())
    assert daten["anzahl"] == 0
    assert daten["uebersprungen_weil_abgelehnt"] == 1
    assert daten["uebersprungen_weil_manuell"] == 0
    assert "abgelehnt" in daten["hinweis"].lower()


def test_neue_kundennachricht_hebt_die_sperre_auf():
    lead = _wartender()
    server.entwurf_ablehnen(_entwurf(lead, vor_minuten=30))
    _kundenantwort(lead, "Und, wie sieht es aus?", 5)
    daten = json.loads(server.antworten_faellig())
    assert daten["anzahl"] == 1
    assert daten["uebersprungen_weil_abgelehnt"] == 0
    assert daten["eintraege"][0]["lead_id"] == lead


def test_ablehnung_von_frueher_zaehlt_nicht():
    """Ein abgelehnter Entwurf, der VOR der juengsten Kundennachricht
    entstand, gehoert zu einer aelteren Frage — die neue ist offen."""
    lead = _wartender(vor_minuten=20)
    server.entwurf_ablehnen(_entwurf(lead, vor_minuten=90))
    daten = json.loads(server.antworten_faellig())
    assert daten["anzahl"] == 1
    assert daten["uebersprungen_weil_abgelehnt"] == 0
