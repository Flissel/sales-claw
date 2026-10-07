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


# --- Browser-Durchlauf 29.09.2026 (Newsletter-Editor E1, Aufgabe 0c/0d) ------
# Vorher war JEDER Eintrag aktiv, dessen Pfad Vorsilbe des aktuellen ist:
# auf /marketing/entwuerfe leuchteten "Übersicht" UND "Entwürfe".

import re  # noqa: E402

_AKTIV_A = re.compile(r'<a class="aktiv" href="([^"]+)"><span>([^<]+)</span>')


def _aktive(pfad: str, rolle: str = "freigeben") -> list:
    t_pfad = ui._AKTIVER_PFAD.set(pfad)
    t_rolle = ui._AKTIVE_ROLLE.set(rolle)
    try:
        leiste = ui._seitenleiste("")
    finally:
        ui._AKTIVER_PFAD.reset(t_pfad)
        ui._AKTIVE_ROLLE.reset(t_rolle)
    return [name for _, name in _AKTIV_A.findall(leiste)]


@pytest.mark.parametrize("pfad, erwartet", [
    ("/marketing", "Übersicht"),
    ("/marketing/entwuerfe", "Entwürfe"),
    ("/marketing/entwurf/241a281c-ebe2-4e25-b1b6-e1a84b94d66a", "Entwürfe"),
    ("/marketing/layouts", "Marke"),
    ("/marketing/layout/dunkel", "Marke"),
    ("/marketing/layout-bild/dunkel", "Marke"),
    ("/kontakte", "Kontakte"),
    ("/team/kalender", "Kalender verbinden"),
    ("/kalender", "Kalender"),
])
def test_genau_der_laengste_passende_eintrag_ist_aktiv(pfad, erwartet):
    assert _aktive(pfad) == [erwartet]


def test_detailseite_markiert_ihre_gruppe_als_aktiv_tab():
    t_pfad = ui._AKTIVER_PFAD.set("/marketing/entwurf/abc")
    t_rolle = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        leiste = ui._seitenleiste("")
    finally:
        ui._AKTIVER_PFAD.reset(t_pfad)
        ui._AKTIVE_ROLLE.reset(t_rolle)
    assert '<a class="tab aktiv" href="/marketing"><span>Marketing' in leiste


def _handy_block(css: str, selektor: str) -> str:
    """Koerper der Regel `selektor` innerhalb der Handy-Regel mit nav.tabs."""
    start = css.index("nav.tabs { display: flex; position: fixed;")
    anfang = css.index(selektor + " {", start)
    return css[anfang:css.index("}", anfang)]


def test_handy_reiter_bleiben_einzeilig():
    block = _handy_block(ui._STIL, "nav.tabs a")
    for eigenschaft in ("white-space: nowrap", "overflow: hidden",
                        "text-overflow: ellipsis", "min-width: 0"):
        assert eigenschaft in block, eigenschaft
    # Die Beschriftung ist ein <span> im Flex-Reiter: nur dort greift die
    # Auslassung, am <a> allein bricht "Monitoring" weiter um.
    span = _handy_block(ui._STIL, "nav.tabs a > span:first-child")
    for eigenschaft in ("white-space: nowrap", "overflow: hidden",
                        "text-overflow: ellipsis", "max-width: 100%"):
        assert eigenschaft in span, eigenschaft


def test_ganz_schmal_kleinere_reiterschrift():
    css = ui._STIL
    anfang = css.index("@media (max-width: 399px)")
    block = css[anfang:css.index("}", css.index("nav.tabs a", anfang))]
    assert "font-size: .62rem" in block and "letter-spacing: 0" in block
