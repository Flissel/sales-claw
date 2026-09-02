"""Verträge über die Handy-Navigation — Schritt 7 des UI-Plans (02.09.2026):
unter 768 px wird die Seitenleiste zur Vier-Tab-Leiste am unteren Rand
(Aufgaben, Analyse, Daten, Monitoring); oben bleibt nur die aktive Gruppe
als Zeile. Alles ohne JavaScript — die Leiste ist immer im HTML, das CSS
entscheidet, was wo erscheint.
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


def test_tab_leiste_traegt_die_vier_gruppen():
    seite = _get("/pipeline").text
    assert '<nav class="tabs">' in seite
    for pfad, name in (("/", "Aufgaben"), ("/kontakte", "Analyse"),
                       ("/medien", "Daten"), ("/whatsapp", "Monitoring")):
        assert f'href="{pfad}"><span>{name}</span>' in seite, name
    assert '<a class="tab aktiv" href="/kontakte"><span>Analyse</span>' in seite
    assert seite.count('class="tab aktiv"') == 1


def test_aktive_gruppe_ist_markiert_und_einzig():
    seite = _get("/pipeline").text
    assert ('<div class="gruppe aktiv-gruppe"><div class="gruppenname">Analyse'
            in seite)
    assert seite.count('class="gruppe aktiv-gruppe"') == 1   # das CSS nennt die Klasse auch
    seite = _get("/").text
    assert ('<div class="gruppe aktiv-gruppe"><div class="gruppenname">Aufgaben'
            in seite)


def test_offene_aufgaben_zaehlen_am_aufgaben_tab():
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "('Tab Person', '+491700000009', 'whatsapp') returning id")[0]["id"])
    server._q("insert into drafts (lead_id, channel, recipient, body, status) "
              "values (%s, 'whatsapp', '+491700000009', 'Hi', 'pending') "
              "returning id", (lead,))
    seite = _get("/kontakte").text
    assert ('href="/"><span>Aufgaben</span><span class="zaehler offen">1</span>'
            in seite)


def test_css_zeigt_die_leiste_nur_auf_dem_handy():
    seite = _get("/kontakte").text
    assert ".tabs { display: none; }" in seite
    assert "nav.tabs { display: flex; position: fixed; bottom: 0;" in seite
    assert "nav.seite .gruppe:not(.aktiv-gruppe) { display: none; }" in seite
