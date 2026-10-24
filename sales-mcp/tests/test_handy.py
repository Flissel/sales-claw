"""Verträge über die Handy-Navigation (Stand Design-Review S4, 19.10.2026:
fünf feste Ziele unten, der Rest auf /mehr - siehe Tests unten).

Ursprung — Schritt 7 des UI-Plans (02.09.2026):
unter 768 px wird die Seitenleiste zur Vier-Tab-Leiste am unteren Rand
(Aufgaben, Analyse, Daten, Monitoring); oben bleibt nur die aktive Gruppe
als Zeile. Alles ohne JavaScript — die Leiste ist immer im HTML, das CSS
entscheidet, was wo erscheint.
"""
import re

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


def _lead_mit_offenem_entwurf():
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "('Tab Person', '+491700000009', 'whatsapp') returning id")[0]["id"])
    server._q("insert into drafts (lead_id, channel, recipient, body, status) "
              "values (%s, 'whatsapp', '+491700000009', 'Hi', 'pending') "
              "returning id", (lead,))
    return lead


# --- Design-Review S4 (19.10.2026, Plan 2026-10-19-design-s3-s4 Task 6, E13):
# am Handy EINE Navigation - die Tab-Leiste unten mit fuenf festen Zielen,
# alles Weitere auf /mehr. Oben steht nur noch das <h1> der Seite.

def test_tab_leiste_hat_fuenf_ziele():
    s = _get("/kontakte").text
    leiste = s.split('<nav class="tabs">')[1].split("</nav>")[0]
    assert re.findall(r'href="([^"]+)"', leiste) == [
        "/", "/freigaben", "/kontakte", "/kalender", "/mehr"]
    assert '<a class="tab aktiv" href="/kontakte"><span>Kontakte</span>' in leiste
    assert leiste.count('class="tab aktiv"') == 1


def test_unbekannte_seite_markiert_mehr():
    assert '<a class="tab aktiv" href="/mehr">' in _get("/pipeline").text
    assert '<a class="tab aktiv" href="/mehr">' in _get("/mehr").text


def test_offene_aufgaben_zaehlen_am_heute_tab():
    _lead_mit_offenem_entwurf()
    s = _get("/kontakte").text
    assert ('<a class="tab" href="/"><span>Heute</span>'
            '<span class="zaehler offen">1</span></a>' in s)
    assert ('<a class="tab" href="/freigaben"><span>Freigaben</span>'
            '<span class="zaehler offen">1</span></a>' in s)


def test_mehr_zeigt_das_ganze_menue_und_abmelden(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")
    antwort = _get("/mehr")
    assert antwort.status_code == 200
    s = antwort.text
    haupt = s.split("<main>")[1]
    assert "<h1>Mehr</h1>" in haupt
    for pfad in ("/pipeline", "/medien", "/whatsapp", "/einordnung"):
        assert f'href="{pfad}"' in haupt, pfad
    for gruppe in ("Aufgaben", "Analyse", "Daten", "Monitoring"):
        assert f'<span class="gruppentitel">{gruppe}</span>' in haupt, gruppe
    # Abmelden nur bei scharfer Anmeldung - wie in der Seitenleiste.
    assert 'action="/logout"' not in haupt
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "scharf")
    assert 'action="/logout"' in ui._mehr_rumpf()
    assert "Abmelden" in ui._mehr_rumpf()


def test_mehr_zaehler_wie_in_der_seitenleiste():
    _lead_mit_offenem_entwurf()
    haupt = _get("/mehr").text.split("<main>")[1]
    assert 'Freigaben</span><span class="zaehler offen">1</span>' in haupt


def test_css_nur_eine_navigation_am_handy():
    s = _get("/").text
    assert ".tabs { display: none; }" in s
    assert "nav.tabs { display: flex; position: fixed; bottom: 0;" in s
    assert "nav.seite { display: none; }" in s and "aktiv-gruppe" not in s


def test_tabs_folgen_der_rolle():
    t = ui._AKTIVE_ROLLE.set("kalender")
    try:
        leiste = ui._seitenleiste("").split('<nav class="tabs">')[1]
        assert 'href="/kalender"' in leiste and 'href="/mehr"' in leiste
        assert 'href="/kontakte"' not in leiste
        assert 'href="/freigaben"' not in leiste
        assert 'href="/"' not in leiste
    finally:
        ui._AKTIVE_ROLLE.reset(t)
    assert ui._pfad_erlaubt("kalender", "/mehr") is True
    t = ui._AKTIVE_ROLLE.set("lesen")
    try:
        leiste = ui._seitenleiste("").split('<nav class="tabs">')[1]
        assert len(re.findall(r'href="', leiste.split("</nav>")[0])) == 5
    finally:
        ui._AKTIVE_ROLLE.reset(t)


def test_mehr_fuer_rolle_kalender_nur_erlaubte_eintraege():
    t = ui._AKTIVE_ROLLE.set("kalender")
    try:
        rumpf = ui._mehr_rumpf()
    finally:
        ui._AKTIVE_ROLLE.reset(t)
    assert 'href="/kalender"' in rumpf and 'href="/kontakte"' not in rumpf
