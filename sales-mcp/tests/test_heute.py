"""Verträge über die Startseite „Heute“ — Schritt 2 des UI-Plans
(02.09.2026, docs/superpowers/plans/2026-09-02-ui-gruppen-und-heute.md).

Die Freigabe-Inbox zieht nach /freigaben; „/“ zeigt, was eine Entscheidung
braucht, und rechts die Lage. Jede Zahl auf der Startseite kommt aus
derselben Quelle wie die Seite, auf die sie verweist.
"""
from datetime import datetime, timedelta

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


@pytest.fixture(autouse=True)
def ohne_fremde_dienste(monkeypatch):
    """Die Startseite fragt Kalender und OpenWA — im Test antworten beide
    ohne Netz, damit der Vertrag ueber die Seite spricht, nicht ueber
    Erreichbarkeit."""
    monkeypatch.setattr(ui.kalender, "termine_lesen",
                        lambda *a, **k: ([], None))
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda pfad: (None, "Kein Nur-Lese-Zugang eingerichtet."))


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(pfad, daten):
    return CLIENT.post(pfad, data=daten, headers={"host": HOST_OK},
                       follow_redirects=False)


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, status="pending", kanal="whatsapp", text="Hallo?",
             empfaenger="+491701234567"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, %s, %s, %s, %s) returning id",
        (lead, kanal, empfaenger, text, status))[0]["id"])


def test_startseite_ist_heute():
    seite = _get("/").text
    assert "<h1>Heute</h1>" in seite
    for wort in ("Freigaben", "Wiedervorlagen", "Einordnung",
                 "Kalender", "WhatsApp", "Posteingang", "Pipeline"):
        assert wort in seite, wort
    assert '<a class="aktiv" href="/">' in seite
    assert "Nichts wartet auf dich" in seite


def test_heute_zeigt_freigaben_je_art_in_fester_reihenfolge():
    lead = _lead()
    _entwurf(lead, text="WA-Entwurf eins")
    _entwurf(lead, text="WA-Entwurf zwei")
    _entwurf(lead, kanal="linkedin", text="LI-Beitrag hier")
    _entwurf(lead, kanal="email", text="Mail-Text hier", empfaenger="x@y.de")
    seite = _get("/").text
    assert 'WhatsApp</span><b>2</b>' in seite
    assert 'LinkedIn</span><b>1</b>' in seite
    assert 'E-Mail</span><b>1</b>' in seite
    assert (seite.index("WA-Entwurf eins") < seite.index("LI-Beitrag hier")
            < seite.index("Mail-Text hier"))
    # Die Karten sind dieselben wie unter /freigaben — mit denselben Knoepfen.
    assert 'action="/aktion/freigeben"' in seite
    # Aufgabe 8 (10.09.2026): der alte Satz „4 Entscheidungen warten auf
    # dich. Alles andere laeuft." behauptete Ruhe, die es bei offenen
    # Terminanfragen/Einordnungen nicht gab. Der neue Satz schluesselt die
    # Posten auf, statt sie unter „Entscheidungen" zu verstecken.
    assert "4 Posten warten auf dich: 4 Entwürfe." in seite


def test_heute_deckelt_je_art_und_verweist_auf_freigaben():
    lead = _lead()
    for i in range(ui.HEUTE_JE_ART + 2):
        _entwurf(lead, text=f"Entwurf Nummer {i}")
    seite = _get("/").text
    assert f"+ 2 weitere WhatsApp-Entwürfe" in seite
    assert 'href="/freigaben"' in seite


def test_freigaben_wohnen_unter_freigaben_und_aktionen_kehren_dorthin_zurueck():
    lead = _lead()
    draft = _entwurf(lead, text="Pending-Text hier")
    assert "Pending-Text hier" in _get("/freigaben").text
    assert '<a class="aktiv" href="/freigaben">' in _get("/freigaben").text
    r = _post("/aktion/ablehnen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben"


def test_rechte_spalte_haelt_ausfaelle_aus(monkeypatch):
    monkeypatch.setattr(ui.kalender, "termine_lesen",
                        lambda *a, **k: ([], "CalDAV antwortet nicht"))
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda pfad: (None, "OpenWA antwortet mit HTTP 500."))
    r = _get("/")
    assert r.status_code == 200
    assert "CalDAV antwortet nicht" in r.text
    assert "OpenWA antwortet mit HTTP 500." in r.text


def test_kalenderspalte_zeigt_die_naechsten_termine_in_ortszeit(monkeypatch):
    morgen = (datetime.now(ui.ZEITZONE) + timedelta(days=1)).replace(
        hour=13, minute=0, second=0, microsecond=0)
    gestern = morgen - timedelta(days=2)
    monkeypatch.setattr(ui.kalender, "termine_lesen", lambda *a, **k: ([
        {"beginn": morgen, "titel": "Team-Meeting", "ort": "", "uid": "u1"},
        {"beginn": gestern, "titel": "Vergangenes", "ort": "", "uid": "u0"},
    ], None))
    seite = _get("/").text
    assert "Team-Meeting" in seite
    assert "13:00" in seite
    assert "Vergangenes" not in seite


def test_pipeline_kacheln_zaehlen_aktive_stufen():
    _lead(name="Neu Eins", phone="+491700000001")
    server._q("update leads set status = 'replied' where name = 'Neu Eins' "
              "returning id")
    _lead(name="Neu Zwei", phone="+491700000002")
    seite = _get("/").text
    assert '<div class="kachel"><b>1</b><span>geantwortet</span></div>' in seite
    assert '<div class="kachel"><b>1</b><span>neu</span></div>' in seite
    assert "<span>gewonnen</span>" not in seite


def test_wiedervorlagen_und_einordnung_stehen_mit_zahl_da():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'wiedervorlage', %s::jsonb, 'human') returning id",
              (lead, '{"faellig_am": "2026-01-01", "notiz": "Nachfassen"}'))
    seite = _get("/").text
    assert "<h2>Wiedervorlagen (1)</h2>" in seite
    assert "Nachfassen" in seite
    assert "<h2>Einordnung (0)</h2>" in seite
    # Aufgabe 8 (10.09.2026): bei genau einem offenen Posten nennt der Satz
    # die Art statt eines nichtssagenden „1 Entscheidung wartet".
    assert "1 Wiedervorlage wartet auf dich." in seite
