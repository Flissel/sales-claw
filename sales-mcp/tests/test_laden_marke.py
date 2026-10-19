"""Aussehen der Laden-Oberflaeche je Firma (Paket C4): Farbrechnung, CSS, Holen ohne Blockieren, Logo."""
import base64
import re
import time

import pytest

import laden_marke as lm

FIN = {"name": "fin2gether", "akzent": "#f66c1e", "zweitfarbe": "#95c11f", "grund": "#ffffff", "text": "#383838",
       "schrift_anzeige": "montserrat", "schrift_text": "dm-sans",
       "logo": "data:image/png;base64," + base64.b64encode(b"\x89PNGfin").decode(), "logo_dunkel": None}
VM = {"name": "VibeMind", "akzent": "#5b3fd6", "zweitfarbe": "#f3e6e3", "schrift_anzeige": "oxanium",
      "schrift_text": "dm-sans", "logo": None, "logo_dunkel": None}


def _vars(css: str, block: int) -> dict:
    teile = re.findall(r":root \{([^}]*)\}", css)
    return dict(re.findall(r"--([a-z_]+): ([^;]+);", teile[block]))


def test_kontrast_rechnet_wie_wcag():
    assert round(lm.kontrast("#000000", "#ffffff"), 1) == 21.0
    assert round(lm.kontrast("#f66c1e", "#ffffff"), 2) < 3.0      # fin2gether-Orange mit weisser Schrift: zu schwach


def test_fin2gether_hell_ist_lesbar():
    v = _vars(lm.stil(FIN), 0)
    assert lm.kontrast(v["akzent"], v["akzent_auf"]) >= 4.5      # Knopf / aktive Navigation
    assert lm.kontrast(v["akzent_text"], v["aktiv"]) >= 4.5
    assert lm.kontrast(v["akzent_text"], v["grund"]) >= 4.5
    assert lm.kontrast(v["blush_text"], v["blush"]) >= 4.5
    assert v["akzent"] != "#f66c1e" and v["akzent"].startswith("#")   # abgedunkelt


def test_fin2gether_dunkel_ist_lesbar():
    v = _vars(lm.stil(FIN), 1)
    assert lm.kontrast(v["akzent"], v["akzent_auf"]) >= 4.5
    assert lm.kontrast(v["akzent_text"], v["aktiv"]) >= 4.5
    assert lm.kontrast(v["akzent_text"], v["flaeche"]) >= 4.5
    assert lm.kontrast(v["blush_text"], v["blush"]) >= 4.5


def test_schriften_der_marke():
    css = lm.stil(FIN)
    assert 'font-family: "Montserrat"' in css and "/marketing/schrift/montserrat-600-normal.woff2" in css
    v = _vars(css, 0)
    assert v["schrift_anzeige"].startswith('"Montserrat"') and v["schrift_text"].startswith('"DM Sans"')


def test_vibemind_bleibt_grundgestaltung():
    assert lm.stil(VM) == ""
    assert lm.stil({**VM, "akzent": "#5B3FD6"}) == ""


@pytest.mark.parametrize("m", [None, {}, {"akzent": None}, {"akzent": "red"},
                               {"akzent": "#123456;}body{display:none"}])
def test_ohne_gueltigen_akzent_nichts(m):
    assert lm.stil(m) == ""


def test_kaputte_zweitfarbe_und_schrift_werden_ignoriert():
    css = lm.stil({**FIN, "zweitfarbe": "x;}", "schrift_anzeige": "<b>", "schrift_text": "comic"})
    assert "x;}" not in css and "<b>" not in css and "schrift_anzeige" not in css


def test_holen_blockiert_nie_und_haelt_den_stand(monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setattr(lm, "_zustand", {"wert": None, "bis": 0.0, "laeuft": False})
    aufrufe = []

    monkeypatch.delenv("MARKETING_AUSSEHEN_KEY", raising=False)

    def anfrage(methode, pfad, zeitlimit=None):
        aufrufe.append(pfad)
        return dict(FIN)
    monkeypatch.setattr(lm.marketing_pult, "anfrage", anfrage)
    assert lm.aussehen() is None                     # erster Aufruf: sofort, noch ohne Marke
    for _ in range(100):
        if lm._zustand["wert"]:
            break
        time.sleep(0.01)
    assert lm.aussehen()["name"] == "fin2gether" and lm.name() == "fin2gether"
    assert aufrufe == ["/marke/aussehen?mandant=fin2gether"]   # danach aus dem Speicher


def test_api_fehler_behaelt_alten_stand(monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setattr(lm, "_zustand", {"wert": dict(FIN), "bis": 0.0, "laeuft": False})

    def kaputt(*a, **k):
        raise lm.marketing_pult.PultFehler("nicht_erreichbar", "weg")
    monkeypatch.delenv("MARKETING_AUSSEHEN_KEY", raising=False)
    monkeypatch.setattr(lm.marketing_pult, "anfrage", kaputt)
    lm.aussehen()
    for _ in range(100):
        if not lm._zustand["laeuft"]:
            break
        time.sleep(0.01)
    assert lm.aussehen()["name"] == "fin2gether"


def test_ohne_firma_vibemind(monkeypatch):
    monkeypatch.delenv("MARKETING_MANDANT", raising=False)
    assert lm.aussehen() is None and lm.name() == "VibeMind" and lm.stil_aktuell() == "" and lm.logo() is None


def test_logo_dunkle_fassung_zuerst(monkeypatch):
    dunkel = "data:image/png;base64," + base64.b64encode(b"\x89PNGdunkel").decode()
    monkeypatch.setattr(lm, "aussehen", lambda: {**FIN, "logo_dunkel": dunkel})
    assert lm.logo() == (b"\x89PNGdunkel", "image/png")
    monkeypatch.setattr(lm, "aussehen", lambda: dict(FIN))
    assert lm.logo() == (b"\x89PNGfin", "image/png")
    monkeypatch.setattr(lm, "aussehen", lambda: {**FIN, "logo": "data:image/svg+xml;base64,PHN2Zz4="})
    assert lm.logo() is None



def test_laden_marke_vor_marketing_mandant(monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "vibemind")
    monkeypatch.setenv("LADEN_MARKE", "fin2gether")
    assert lm.mandant() == "fin2gether"
    monkeypatch.delenv("LADEN_MARKE")
    assert lm.mandant() == "vibemind"


def test_schmaler_schluessel_statt_pult(monkeypatch):
    """Ivans Laden: kein Pult-Zugang, nur X-Aussehen-Key - und der Kopf folgt keiner Umleitung."""
    monkeypatch.setenv("MARKETING_AUSSEHEN_KEY", "aussehen-k")
    monkeypatch.setenv("MARKETING_AUSSEHEN_URL", "https://vm.example:8446/")
    monkeypatch.setattr(lm.marketing_pult, "anfrage", lambda *a, **k: pytest.fail("kein Pult-Weg"))
    gesehen = {}

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"name": "fin2gether"}'

    def urlopen(req, timeout=None):
        gesehen["url"], gesehen["kopf"] = req.full_url, req.unredirected_hdrs
        return Antwort()
    monkeypatch.setattr(lm.urllib.request, "urlopen", urlopen)
    assert lm._abrufen("fin2gether") == {"name": "fin2gether"}
    assert gesehen["url"] == "https://vm.example:8446/api/pult/marke/aussehen?mandant=fin2gether"
    assert gesehen["kopf"] == {"X-aussehen-key": "aussehen-k"}
