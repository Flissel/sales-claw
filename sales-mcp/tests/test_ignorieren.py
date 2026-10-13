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


# ---------------------------------------------------------------------------
# Freigabe hebt Ignorieren auf (Block A, Task 4)
# ---------------------------------------------------------------------------

def _lead_mit_nummer(phone, name="Nina Nummer"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, %s, 'whatsapp') returning id", (name, phone))[0]["id"])


def _beachtet_anzahl():
    return server._q("select count(*) n from activities "
                     "where type = 'absender_beachtet'")[0]["n"]


def test_freigabe_hebt_ignorieren_auf():
    lead = _lead_mit_nummer("+4915752415952")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "4915752415952@c.us", lead)
    assert server.absender_ist_ignoriert("4915752415952@c.us")
    a = json.loads(server.kontakt_freigeben(lead))
    assert "stand auf Ignorieren – aufgehoben" in a["ignorieren_aufgehoben"]
    assert not server.absender_ist_ignoriert("4915752415952@c.us")


def test_entwurf_freigabe_hebt_auf():
    lead = _lead_mit_nummer("+4915752415953")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "4915752415953@c.us", lead)
    draft = str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'email', 'nina@example.org', 'Hallo', 'pending') "
        "returning id", (lead,))[0]["id"])
    a = json.loads(server.entwurf_freigeben(draft))
    assert a["status"] == "approved"
    assert "stand auf Ignorieren – aufgehoben" in a["ignorieren_aufgehoben"]
    assert not server.absender_ist_ignoriert("4915752415953@c.us")


def test_entwurf_freigabe_ohne_ignorieren_ohne_schluessel():
    lead = _lead_mit_nummer("+4915752415954")
    draft = str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'email', 'nina@example.org', 'Hallo', 'pending') "
        "returning id", (lead,))[0]["id"])
    a = json.loads(server.entwurf_freigeben(draft))
    assert "ignorieren_aufgehoben" not in a
    assert _beachtet_anzahl() == 0


def test_nie_ignoriert_kein_ereignis():
    lead = _lead_mit_nummer("+4915000000001")
    a = json.loads(server.kontakt_freigeben(lead))
    assert "ignorieren_aufgehoben" not in a
    assert _beachtet_anzahl() == 0


def test_kontakt_ohne_nummer():
    lead = str(server._q(
        "insert into leads (name, email, source) values "
        "('Mail Only', 'mo@example.org', 'manual') returning id")[0]["id"])
    assert server.ignorieren_aufheben(lead) is None
    a = json.loads(server.kontakt_freigeben(lead))
    assert "ignorieren_aufgehoben" not in a
    assert _beachtet_anzahl() == 0


def test_entziehen_hebt_nichts_auf():
    lead = _lead_mit_nummer("+4915752415955")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "4915752415955@c.us", lead)
    server.kontakt_freigabe_entziehen(lead)
    assert server.absender_ist_ignoriert("4915752415955@c.us")


# --- @lid-Bruecke (Spec 1.5) und Fehlertoleranz --------------------------------

def _lid_zuordnung(lid_ziffern, nummer):
    return server.lid_zuordnung_speichern(
        f"{lid_ziffern}@lid", f"{nummer}@c.us", "test", "rufnummer")


def test_freigabe_hebt_eindeutig_gebrueckte_lid_auf():
    lead = _lead_mit_nummer("+4915752415960")
    _lid_zuordnung("183000000000001", "4915752415960")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "183000000000001@lid", lead)
    assert server.absender_ist_ignoriert("4915752415960@c.us")
    a = json.loads(server.kontakt_freigeben(lead))
    assert "stand auf Ignorieren – aufgehoben" in a["ignorieren_aufgehoben"]
    assert not server.absender_ist_ignoriert("4915752415960@c.us")
    assert not server.absender_ist_ignoriert("183000000000001@lid")
    assert not server.absender_ist_ignoriert("183000000000001@lid",
                                             "4915752415960@c.us")


def test_mehrdeutige_bruecke_bleibt_ignoriert():
    lead = _lead_mit_nummer("+4915752415961")
    _lid_zuordnung("183000000000002", "4915752415961")
    _lid_zuordnung("183000000000003", "4915752415961")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "4915752415961@c.us", lead)
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "183000000000002@lid")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "183000000000003@lid")
    json.loads(server.kontakt_freigeben(lead))
    assert not server.absender_ist_ignoriert("4915752415961@c.us")
    assert server.absender_ist_ignoriert("183000000000002@lid")
    assert server.absender_ist_ignoriert("183000000000003@lid")


def test_fehler_beim_aufheben_maskiert_freigabe_nicht(monkeypatch):
    lead = _lead_mit_nummer("+4915752415962")
    draft = str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'email', 'nina@example.org', 'Hallo', 'pending') "
        "returning id", (lead,))[0]["id"])

    def kaputt(_lead_id):
        raise RuntimeError("db weg")
    monkeypatch.setattr(server, "ignorieren_aufheben", kaputt)
    a = json.loads(server.entwurf_freigeben(draft))
    assert a["status"] == "approved"
    assert "ignorieren_aufgehoben" not in a
    a = json.loads(server.kontakt_freigeben(lead))
    assert a["whatsapp_freigabe"] is True
    assert "ignorieren_aufgehoben" not in a
