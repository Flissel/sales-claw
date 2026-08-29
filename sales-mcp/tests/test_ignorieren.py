"""Vertragstests: `ignorieren` heisst ignorieren (29.08.2026).

Betreiber-Befund: "mir kommt es so vor als wuerden dennoch alle meine
Kontakte analysiert werden" — und das stimmte. Die Stufe filterte nur das
Antworten (antworten_faellig); Kontaktprofile und Chat-Reports liefen
fuer ignorierte Kontakte weiter, also auch fuer PRIVATE Chats.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Ein ignorierter Kontakt taucht in KEINER Faelligkeitsliste auf —
   kein Profil, kein Report, keine Antwort.
2. Die ausdrueckliche Bitte des Betreibers uebersteuert: profil_anfordern
   holt auch einen ignorierten Kontakt in die Liste — er hat es verlangt.
3. `manuell` bleibt analysiert: "ich antworte selbst, aber der Bot darf
   mir zuarbeiten" ist ein gewollter Zustand, kein Leck.
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


def _lead(stufe, name="Ines Ignoriert"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491704445566', 'whatsapp') returning id", (name,))[0]["id"])
    server.kontakt_autonomie_setzen(lead, stufe)
    for i in range(6):
        server._q(
            "insert into activities (lead_id, type, payload) values "
            "(%s, 'kundenantwort', %s) returning id",
            (lead, server._json({"text": f"private nachricht {i}"})))
    return lead


def _profil_leads():
    return {str(z["lead_id"]) for z in server._profil_faellig()}


def _report_leads():
    return {str(z["lead_id"]) for z in server._chat_faellig(schwelle=3)}


def test_ignoriert_bekommt_kein_profil():
    lead = _lead("ignorieren")
    assert lead not in _profil_leads()


def test_ignoriert_bekommt_keinen_chat_report():
    lead = _lead("ignorieren")
    assert lead not in _report_leads()


def test_manuell_wird_weiter_analysiert():
    lead = _lead("manuell", name="Momo Manuell")
    assert lead in _profil_leads()
    assert lead in _report_leads()


def test_die_ausdrueckliche_bitte_uebersteuert():
    lead = _lead("ignorieren")
    server.profil_anfordern(lead)
    assert lead in _profil_leads()


def test_das_werkzeug_meldet_dasselbe():
    lead = _lead("ignorieren")
    d = json.loads(server.profile_faellig())
    assert lead not in {str(k["lead_id"]) for k in d["kontakte"]}
    r = json.loads(server.chat_reports_faellig())
    assert lead not in {str(k["lead_id"]) for k in r["kontakte"]}
