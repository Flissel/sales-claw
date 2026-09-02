"""Verträge über die Freigabe-Seite in vier Blöcken mit Verlauf je Art —
Schritt 3 des UI-Plans (02.09.2026). Betreiber: „WhatsApp-, LinkedIn-,
E-Mail- und Kalender-Freigaben gesondert … und auch die History aufteilen,
damit alles seine Ordnung hat.“
"""
import pytest
from starlette.testclient import TestClient

import server
import ui

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


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, status="pending", kanal="whatsapp", text="Hallo?",
             fehler=None, empfaenger="+491701234567"):
    draft = str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, error) "
        "values (%s, %s, %s, %s, %s, %s) returning id",
        (lead, kanal, empfaenger, text, status, fehler))[0]["id"])
    if status == "sent":
        server._q("update drafts set sent_at = now() where id = %s "
                  "returning id", (draft,))
    return draft


def _aktivitaet(lead, typ, payload):
    return server._q(
        "insert into activities (lead_id, type, payload, actor) values "
        "(%s, %s, %s::jsonb, 'agent') returning id",
        (lead, typ, payload))[0]["id"]


def test_vier_bloecke_in_fester_reihenfolge_mit_zaehlern():
    lead = _lead()
    _entwurf(lead, text="WA offen eins")
    _entwurf(lead, text="WA offen zwei")
    _entwurf(lead, kanal="linkedin", text="LI offen")
    seite = _get("/freigaben").text
    assert (seite.index("Verlauf WhatsApp") < seite.index("Verlauf LinkedIn")
            < seite.index("Verlauf E-Mail") < seite.index("Verlauf Termine"))
    assert 'WhatsApp <span class="zaehler offen">2</span>' in seite
    assert 'LinkedIn <span class="zaehler offen">1</span>' in seite
    assert 'E-Mail <span class="zaehler">0</span>' in seite
    assert 'Termine <span class="zaehler">0</span>' in seite
    # Die offenen Karten stehen in ihrem Block, vor dem Verlauf der Art.
    assert seite.index("WA offen eins") < seite.index("Verlauf WhatsApp")
    assert (seite.index("Verlauf WhatsApp") < seite.index("LI offen")
            < seite.index("Verlauf LinkedIn"))


def test_verlauf_je_art_trennt_gesendetes_abgelehntes_und_gescheitertes():
    lead = _lead()
    _entwurf(lead, status="sent", text="Schon raus per WhatsApp")
    _entwurf(lead, status="rejected", kanal="linkedin",
             text="Abgelehnter Beitrag")
    _entwurf(lead, status="failed", kanal="email", text="Mail kaputt",
             fehler="SMTP antwortet nicht", empfaenger="x@y.de")
    seite = _get("/freigaben").text
    assert (seite.index("Verlauf WhatsApp") < seite.index("Schon raus per WhatsApp")
            < seite.index("Verlauf LinkedIn") < seite.index("Abgelehnter Beitrag")
            < seite.index("Verlauf E-Mail"))
    assert 'class="badge zustand rejected">abgelehnt</span>' in seite
    # Gescheitertes ist offen (Erneut freigeben / Verwerfen), nicht Verlauf.
    assert "SMTP antwortet nicht" in seite
    assert seite.index("Mail kaputt") < seite.index("Verlauf E-Mail")
    assert 'action="/aktion/erneut-freigeben"' in seite


def test_verlauf_seite_je_art_und_unbekannte_art():
    lead = _lead()
    _entwurf(lead, status="sent", text="Gesendeter WhatsApp-Text")
    _entwurf(lead, status="sent", kanal="linkedin", text="Gesendeter Beitrag")
    seite = _get("/freigaben/verlauf/whatsapp")
    assert seite.status_code == 200
    assert "<h1>Verlauf WhatsApp</h1>" in seite.text
    assert "Gesendeter WhatsApp-Text" in seite.text
    assert "Gesendeter Beitrag" not in seite.text
    assert '<a class="aktiv" href="/freigaben">' in seite.text
    assert _get("/freigaben/verlauf/fax").status_code == 404


def test_termine_block_mit_offenem_und_verlauf():
    lead = _lead(name="Lisa Beispiel")
    _aktivitaet(lead, "termin",
                '{"inhalt": "Donnerstag 16 Uhr, Datum noch offen"}')
    _aktivitaet(lead, "termin",
                '{"datum": "2026-09-04", "uhrzeit": "13:00", '
                '"thema": "Erstgespraech Video", "uid": "u1"}')
    _aktivitaet(lead, "termin_abgesagt",
                '{"uid": "u1", "grund": "Kunde krank"}')
    seite = _get("/freigaben").text
    assert 'Termine <span class="zaehler offen">1</span>' in seite
    assert "Datum noch offen" in seite
    assert seite.index("Datum noch offen") < seite.index("Verlauf Termine")
    verlauf = seite[seite.index("Verlauf Termine"):]
    assert "Erstgespraech Video" in verlauf
    assert "bestaetigt" in verlauf
    assert "abgesagt" in verlauf
    assert "Kunde krank" in verlauf
    ganze = _get("/freigaben/verlauf/termine")
    assert ganze.status_code == 200
    assert "Erstgespraech Video" in ganze.text


def test_freigabe_seite_frischt_weiter_alle_30_s_auf():
    assert 'http-equiv="refresh" content="30"' in _get("/freigaben").text
