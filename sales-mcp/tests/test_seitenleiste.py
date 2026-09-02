"""Verträge über die Seitenleiste — Schritt 1 des UI-Plans (02.09.2026,
docs/superpowers/plans/2026-09-02-ui-gruppen-und-heute.md).

Zehn gleichrangige Reiter werden zu vier Gruppen. Die Zähler am Menü
kommen aus denselben Abfragen wie die Seiten selbst — und wenn eine davon
scheitert, fehlt der Zähler, nicht die Seite.
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


def _entwurf(lead, status="pending", kanal="whatsapp", text="Hallo?"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, %s, %s, %s, %s) returning id",
        (lead, kanal, "+491701234567", text, status))[0]["id"])


def test_vier_gruppen_mit_allen_seiten():
    seite = _get("/kontakte").text
    for gruppe in ("Aufgaben", "Analyse", "Daten", "Monitoring"):
        assert f'<div class="gruppenname">{gruppe}</div>' in seite, gruppe
    for pfad in ("/", "/freigaben", "/wiedervorlagen", "/einordnung", "/kalender",
                 "/kontakte", "/pipeline", "/ergebnisse", "/posteingang",
                 "/medien", "/whatsapp"):
        assert f'href="{pfad}"' in seite, pfad
    # Reihenfolge der Gruppen ist Teil des Entwurfs.
    assert (seite.index('<div class="gruppenname">Aufgaben')
            < seite.index('<div class="gruppenname">Analyse')
            < seite.index('<div class="gruppenname">Daten')
            < seite.index('<div class="gruppenname">Monitoring'))


def test_aktiver_menuepunkt_ist_markiert():
    seite = _get("/kontakte").text
    assert '<a class="aktiv" href="/kontakte">' in seite
    assert seite.count('class="aktiv"') == 1
    assert '<a class="aktiv" href="/pipeline">' in _get("/pipeline").text


def test_offene_freigaben_zaehlen_am_menue():
    lead = _lead()
    _entwurf(lead)
    _entwurf(lead, text="Zweiter")
    _entwurf(lead, status="sent", text="Schon raus")
    seite = _get("/kontakte").text
    # Offenes traegt die Achtung-Farbe, Bestand die neutrale.
    assert 'Freigaben</span><span class="zaehler offen">2</span>' in seite
    # „Heute" ist die Summe der Aufgaben-Zaehler.
    assert 'Heute</span><span class="zaehler offen">2</span>' in seite
    assert 'Kontakte</span><span class="zaehler">1</span>' in seite


def test_nichts_offen_ist_ein_neutraler_nullzaehler():
    seite = _get("/kontakte").text
    assert 'Freigaben</span><span class="zaehler">0</span>' in seite
    assert 'Heute</span><span class="zaehler">0</span>' in seite
    assert 'zaehler offen' not in seite


def test_zaehler_fallen_leise_aus(monkeypatch):
    def kaputt():
        raise RuntimeError("Zaehlabfrage kaputt")
    monkeypatch.setattr(ui, "_zaehler_abfragen", kaputt)
    antwort = _get("/kontakte")
    assert antwort.status_code == 200
    assert 'class="zaehler' not in antwort.text
    assert '<div class="gruppenname">Aufgaben</div>' in antwort.text


def test_auf_dem_handy_wird_die_leiste_zur_zeile():
    """Unter 768 px gibt es keine Seitenleiste; die Gruppen werden zur
    umbrechenden Zeile wie bisher (die Vier-Tab-Leiste ist Schritt 7)."""
    seite = _get("/kontakte").text
    assert ("nav.seite { display: flex; flex-direction: row; flex-wrap: wrap;"
            in seite)
    assert "@media (max-width: 767px)" in seite
