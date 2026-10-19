"""Aussehen je Laden in der Oberflaeche (Paket C4, 19.10.2026): zweites Stylesheet aus der Marke, Name und Logo
in der Seitenleiste; ohne Marke (oder mit der VibeMind-Grundgestaltung) bleibt alles wie in S2."""
import base64

import pytest
from starlette.testclient import TestClient

import laden_marke
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
FIN = {"name": "fin2gether", "akzent": "#f66c1e", "zweitfarbe": "#95c11f", "grund": "#ffffff", "text": "#383838",
       "schrift_anzeige": "montserrat", "schrift_text": "dm-sans",
       "logo": "data:image/png;base64," + base64.b64encode(b"\x89PNGfin").decode(), "logo_dunkel": None}


def _seite(monkeypatch, aussehen):
    monkeypatch.setattr(laden_marke, "aussehen", lambda: aussehen)
    return ui._seite("Probe", "<p>x</p>").body.decode("utf-8")


def test_stylesheet_nutzt_schrift_variablen():
    assert '--schrift_anzeige: "Oxanium", "DM Sans", system-ui, sans-serif;' in ui._STIL
    assert "font-family: var(--schrift_text)" in ui._STIL and "font-family: var(--schrift_anzeige)" in ui._STIL
    assert 'font-family: "Oxanium", "DM Sans", system-ui' not in ui._STIL.split("--schrift_anzeige:")[1]


def test_fin2gether_bekommt_eigenes_aussehen(monkeypatch):
    s = _seite(monkeypatch, dict(FIN))
    zweites = s.split("</style>")[1]
    assert "<style>" in zweites and "--akzent: #b85116" in zweites and '"Montserrat"' in zweites
    assert "url(/static/marke/laden-logo)" in zweites
    assert "<span>fin2gether</span>" in s and "<span>VibeMind</span>" not in s


def test_vibemind_und_ohne_marke_wie_bisher(monkeypatch):
    for aussehen in (None, {"name": "VibeMind", "akzent": "#5b3fd6", "zweitfarbe": "#f3e6e3",
                            "schrift_anzeige": "oxanium", "schrift_text": "dm-sans", "logo": None,
                            "logo_dunkel": None}):
        s = _seite(monkeypatch, aussehen)
        assert s.count("<style>") == 1 and "laden-logo" not in s and "<span>VibeMind</span>" in s


def test_name_wird_escaped(monkeypatch):
    s = _seite(monkeypatch, {**FIN, "name": "<b>x</b>"})
    assert "<b>x</b>" not in s and "&lt;b&gt;x&lt;/b&gt;" in s


def test_logo_route(monkeypatch):
    monkeypatch.setattr(laden_marke, "aussehen", lambda: dict(FIN))
    r = CLIENT.get("/static/marke/laden-logo", headers={"host": HOST_OK})
    assert r.status_code == 200 and r.content == b"\x89PNGfin" and r.headers["content-type"] == "image/png"
    assert "max-age=300" in r.headers["cache-control"] and r.headers["x-content-type-options"] == "nosniff"
    monkeypatch.setattr(laden_marke, "aussehen", lambda: None)
    assert CLIENT.get("/static/marke/laden-logo", headers={"host": HOST_OK}).status_code == 404
    assert CLIENT.get("/static/marke/vibemind-logo-hell.png", headers={"host": HOST_OK}).status_code == 200
