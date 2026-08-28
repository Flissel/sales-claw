"""Vertragstests fuer die Pipeline-Stufen.

Befund vom 27.08.2026: `leads.status` existierte von Anfang an (samt
score-Spalten), aber ALLE 34 Leads standen auf `new` — kein Werkzeug hat
je ein Stadium bewegt. Der Betreiber will eine gelebte Pipeline.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Es gibt GENAU die acht Stufen des Schema-Constraints, und nur die.
   Ein Tippfehler wird zur
   Meldung, nie zu einem stillen Phantasie-Stadium in der Datenbank.
2. Jeder Wechsel ist ein Beweis: leads.status UND eine activities-Zeile
   mit von/nach/Begruendung. Ein Feld, das sich aendert, ohne dass das
   Protokoll sagt warum, gibt es nicht.
3. Der Altbestand (`new`) wird beim Lesen als `neu` gedeutet — keine
   Migration noetig, kein Kontakt faellt aus der Ansicht.
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


def _lead(status="new"):
    return str(server._q(
        "insert into leads (name, phone, source, status) values "
        "('Pia Pipeline', '+491701112233', 'whatsapp', %s) returning id",
        (status,))[0]["id"])


def _status(lead):
    return server._q("select status from leads where id = %s",
                     (lead,))[0]["status"]


# ---------------------------------------------------------------------------
# Der Vertrag: acht Stufen, Begruendung Pflicht, Beweiszeile
# ---------------------------------------------------------------------------

def test_die_stufen_folgen_dem_schema_wortschatz():
    """Das Schema kannte die Pipeline laengst: leads_status_check erlaubt
    acht Werte (gemessen 27.08.2026). Der deutsche Satz bildet GENAU sie
    ab — keine Parallelwelt neben dem Constraint."""
    assert server.PIPELINE_STUFEN == (
        "neu", "recherchiert", "qualifiziert", "kontaktiert",
        "geantwortet", "termin", "gewonnen", "verloren")
    assert set(server.STUFEN_DB.values()) == {
        "new", "researched", "qualified", "contacted", "replied",
        "meeting", "won", "lost"}


def test_die_datenbank_traegt_den_constraint_wert():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin am Freitag 10 Uhr")
    assert _status(lead) == "meeting"


def test_wechsel_schreibt_feld_und_beweis():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Erstnachricht am 27.08. beantwortet"))
    assert antwort["von"] == "neu"
    assert antwort["nach"] == "kontaktiert"
    assert _status(lead) == "contacted"
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'stufenwechsel'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["von"] == "neu"
    assert zeilen[0]["payload"]["nach"] == "kontaktiert"
    assert "Erstnachricht" in zeilen[0]["payload"]["begruendung"]


def test_unbekannte_stufe_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "vielleicht", "egal"))
    assert "fehler" in antwort
    assert "neu" in antwort["fehler"]  # die Meldung nennt die gueltigen
    assert _status(lead) == "new"      # nichts geschrieben


def test_ohne_begruendung_kein_wechsel():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(lead, "termin", "  "))
    assert "fehler" in antwort
    assert "Begruendung" in antwort["fehler"]
    assert _status(lead) == "new"


def test_gleiche_stufe_ist_eine_meldung():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin steht")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "termin", "nochmal"))
    assert "fehler" in antwort
    assert "steht schon" in antwort["fehler"]


def test_rueckwaertsgang_ist_erlaubt_und_belegt():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin vereinbart")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Angebot zurueckgezogen, Kunde ueberlegt neu"))
    assert "fehler" not in antwort
    assert _status(lead) == "contacted"


def test_unbekannter_kontakt_ist_eine_meldung():
    antwort = json.loads(server.kontakt_stufe_setzen(
        "00000000-0000-0000-0000-000000000000", "termin", "egal"))
    assert "fehler" in antwort


def test_altbestand_new_wird_als_neu_gedeutet():
    lead = _lead(status="new")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Altbestand angefasst"))
    assert antwort["von"] == "neu"


# ---------------------------------------------------------------------------
# Digest zaehlt je Stufe
# ---------------------------------------------------------------------------

def test_digest_zaehlt_die_pipeline():
    a = _lead()
    _lead()
    server.kontakt_stufe_setzen(a, "termin", "Termin am Freitag")
    d = json.loads(server.digest())
    assert d["pipeline"]["neu"] == 1
    assert d["pipeline"]["termin"] == 1
