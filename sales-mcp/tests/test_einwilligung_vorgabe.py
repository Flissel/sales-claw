"""Betreiber-Vorgabe zur Werbe-Einwilligung (30.10.2026).

Betreiber-Wunsch: „diese Einwilligungen sollten ab sofort erstmal immer auf
ja gesetzt sein ... das soll beim Einordnen mit abgehakt werden", ausdruecklich
auch fuer alle bestehenden Kontakte. Gebucht wird `betreiber_auftrag` (der
Betreiber verantwortet die Grundlage) - NICHT opt_in, denn das hiesse, der
Kontakt selbst habe eingewilligt.

Was diese Suite verteidigt: die Vorgabe bucht nur auf `unknown` und nie bei
Loeschantrag, Privat, Verbotsliste oder nach einem Widerruf.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    yield


def _lead(name="Vera Vorgabe", phone="+491705550101", email="vera@example.org",
          consent="unknown", enrichment=None):
    return str(server._q(
        "insert into leads (name, phone, email, source, consent_status, enrichment) "
        "values (%s, %s, %s, 'recherche', %s, %s::jsonb) returning id",
        (name, phone, email, consent, json.dumps(enrichment or {})))[0]["id"])


def _status(lead):
    return server._q("select consent_status from leads where id = %s",
                     (lead,))[0]["consent_status"]


def _einwilligungen(lead):
    return [z["payload"] for z in server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'werbe_einwilligung' order by created_at", (lead,))]


# --- kontakt_anlegen --------------------------------------------------------

def test_neuer_kontakt_bekommt_die_grundlage_mit_quelle():
    antwort = json.loads(server.kontakt_anlegen("Nina Neu", phone="+491705550202"))
    lead = antwort["lead_id"]
    assert antwort["einwilligung"] is True
    assert _status(lead) == "betreiber_auftrag"
    (eintrag,) = _einwilligungen(lead)
    assert eintrag["art"] == "betreiber_auftrag"
    assert eintrag["quelle"].startswith("Betreiber-Vorgabe ab 30.10.2026")


def test_neuer_kontakt_darf_ohne_grundlage_angelegt_werden():
    lead = json.loads(server.kontakt_anlegen(
        "Otto Ohne", phone="+491705550303", einwilligung=False))["lead_id"]
    assert _status(lead) == "unknown"
    assert _einwilligungen(lead) == []


def test_erstansprache_an_neuen_kontakt_geht_durch_das_tor():
    lead = json.loads(server.kontakt_anlegen(
        "Paula Post", phone="+491705550404", email="paula@example.org"))["lead_id"]
    server.kontakt_freigeben(lead)
    antwort = json.loads(server.entwurf_erstellen(lead, "email", "Hallo Paula"))
    assert "fehler" not in antwort, antwort


def test_dublette_bucht_nichts_nach():
    alt = _lead(phone="+491705550505")
    antwort = json.loads(server.kontakt_anlegen("Vera Doppelt", phone="+491705550505"))
    assert antwort["lead_id"] == alt and antwort["angelegt"] is False
    assert _status(alt) == "unknown"


# --- _grundlage_vorgabe: die Ausnahmen --------------------------------------

def test_vorgabe_bucht_auf_unknown():
    lead = _lead()
    assert server._grundlage_vorgabe(lead, "Test-Quelle") is True
    assert _status(lead) == "betreiber_auftrag"
    assert _einwilligungen(lead)[0]["quelle"] == "Test-Quelle"


@pytest.mark.parametrize("vorher", ["opt_in", "existing_customer", "inbound"])
def test_vorhandene_grundlage_bleibt(vorher):
    lead = _lead(consent=vorher)
    assert server._grundlage_vorgabe(lead, "Test") is False
    assert _status(lead) == vorher
    assert _einwilligungen(lead) == []


def test_nie_bei_loeschantrag():
    lead = _lead(enrichment={server.LOESCH_SCHLUESSEL: {"at": "2026-10-01"}})
    assert server._grundlage_vorgabe(lead, "Test") is False
    assert _status(lead) == "unknown"


def test_nie_bei_privat():
    lead = _lead(enrichment={server.PRIVAT_SCHLUESSEL: {"privat": True}})
    assert server._grundlage_vorgabe(lead, "Test") is False
    assert _status(lead) == "unknown"


def test_nie_nach_widerruf():
    lead = _lead()
    server.einwilligung_erfassen(lead, "opt_in", "Formular")
    server.einwilligung_widerrufen(lead, "keine Werbung mehr")
    assert _status(lead) == "unknown"
    assert server._grundlage_vorgabe(lead, "Test") is False
    assert _status(lead) == "unknown"


def test_nie_bei_verbotsliste():
    lead = _lead(email="gesperrt@example.org")
    server._lead_sperren(lead, quelle="test", grund="abgemeldet")
    assert server._grundlage_vorgabe(lead, "Test") is False
    assert _status(lead) == "unknown"


def test_unbekannter_kontakt():
    assert server._grundlage_vorgabe("00000000-0000-0000-0000-000000000000", "Test") is False
