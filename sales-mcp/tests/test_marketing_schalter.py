"""Schalter Sales <-> Marketing (Spec docs/superpowers/specs/
2026-09-25-marketing-schalter-design.md). Zwei Huerden: MARKETING_URL
gesetzt UND Rolle freigeben im Basis-Laden."""
import urllib.parse

import pytest

import server
import ui

MKT = "https://vibemind-offload-1.tail6c7d61.ts.net:8446"
SALES = "https://vibemind-offload-1.tail6c7d61.ts.net"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture
def gesetzt(monkeypatch):
    monkeypatch.setattr(ui, "MARKETING_URL", MKT)
    monkeypatch.setattr(ui, "_BASIS_URL", SALES)


def _leiste(rolle):
    token = ui._AKTIVE_ROLLE.set(rolle)
    try:
        return ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(token)


def test_ohne_adresse_kein_schalter(monkeypatch):
    monkeypatch.setattr(ui, "MARKETING_URL", "")
    assert ui._marketing_link("freigeben") == ""
    assert "Marketing" not in _leiste("freigeben")


@pytest.mark.parametrize("rolle", ["", "lesen", "kalender"])
def test_andere_rolle_kein_schalter(gesetzt, rolle):
    assert ui._marketing_link(rolle) == ""
    assert "Marketing" not in _leiste(rolle)


def test_anderer_laden_kein_schalter(gesetzt, monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._marketing_link("freigeben") == ""


def test_link_traegt_rueckweg_kodiert(gesetzt):
    link = ui._marketing_link("freigeben")
    teile = urllib.parse.urlsplit(link)
    assert f"{teile.scheme}://{teile.netloc}{teile.path}" == MKT + "/mockup/"
    assert urllib.parse.parse_qs(teile.query) == {"zurueck": [SALES]}


def test_schalter_in_seitenleiste_und_tableiste(gesetzt):
    leiste = _leiste("freigeben")
    href = ui._e(ui._marketing_link("freigeben"))
    assert '<div class="schalter">' in leiste
    # einmal oben (Desktop), einmal in der Tableiste (Handy — die .marke
    # ist dort verborgen)
    assert leiste.count(f'href="{href}"') == 2
    tabs = leiste[leiste.index('<nav class="tabs">'):]
    assert f'href="{href}"' in tabs


def test_schalter_stiehlt_nicht_die_aktiv_klasse(gesetzt):
    # test_seitenleiste.py zaehlt genau ein class="aktiv" (der aktive
    # Menuepunkt); der Schalter traegt deshalb eine eigene Klasse.
    token = ui._AKTIVER_PFAD.set("/kontakte")
    try:
        leiste = _leiste("freigeben")
    finally:
        ui._AKTIVER_PFAD.reset(token)
    assert '<div class="schalter">' in leiste
    assert leiste.count('class="aktiv"') == 1
    assert '<a class="aktiv" href="/kontakte">' in leiste
    assert '<span class="schalter-aktiv">Sales</span>' in leiste


@pytest.mark.parametrize("basis", ["", "http://127.0.0.1:8791"])
def test_ohne_https_basis_kein_rueckweg(gesetzt, monkeypatch, basis):
    monkeypatch.setattr(ui, "_BASIS_URL", basis)
    assert ui._marketing_link("freigeben") == MKT + "/mockup/"


def test_schraegstrich_und_anfuehrungszeichen(monkeypatch):
    monkeypatch.setattr(ui, "_BASIS_URL", "")
    monkeypatch.setattr(ui, "MARKETING_URL",
                        ui._marketing_url_lesen('https://x.ts.net:8446/"x/'))
    assert "//mockup" not in ui._marketing_link("freigeben").split("://", 1)[1]
    leiste = _leiste("freigeben")
    assert '"x' not in leiste.replace("&quot;x", "")
