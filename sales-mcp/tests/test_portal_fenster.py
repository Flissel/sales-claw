"""Portal-Fenster: seit Schritt A der Direktlink-Umstellung nur noch ein Stumpf (Plan 2026-11-20, Task 10).

Das Relay zum noVNC-Fenster des Bots ist entfernt: dieselben Pfade, aber HTTP antwortet 410 und der
WebSocket schliesst vor dem Annehmen mit Code 1008. Nichts fragt die Zentrale oder den Container.
Fakes: die Zentrale (`bewerbung_pult.anfrage`) und `websockets.connect`; beide muessen unberuehrt bleiben.
Bleiben: `trennen` (Abmelden, ui.py), `eingerichtet` und der festgenagelte websockets-Logger."""
import asyncio
import logging
import os
import time

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
import websockets  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import bewerbung_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_portal_fenster as pf  # noqa: E402

HOST = "127.0.0.1:8791"
GEHEIMNIS = "test-geheimnis-nur-fuer-die-suite"
SCHLUESSEL = "fenster-schluessel-nur-fuer-die-suite-7Q"
WS_PFAD = "/freigaben/bewerbung/fenster/ws"
PFAD = "/freigaben/bewerbung/fenster"


class FalscheVerbindung:
    """`websockets.connect`: jeder Aufruf wird notiert; gebraucht wird er nie."""

    def __init__(self):
        self.aufrufe = []

    async def __call__(self, url, **kw):
        self.aufrufe.append((url, kw))
        raise AssertionError("das Relay darf den Container nicht anrufen")


class FalscheZentrale:
    def __init__(self):
        self.aufrufe = []

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, zeitlimit))
        raise AssertionError("das Relay darf die Zentrale nicht fragen")


@pytest.fixture
def novnc(tmp_path, monkeypatch):
    d = tmp_path / "novnc"
    (d / "core").mkdir(parents=True)
    (d / "core" / "rfb.js").write_text("export default class RFB {}\n", encoding="utf-8")
    monkeypatch.setattr(pf, "NOVNC_DIR", d)
    return d


@pytest.fixture
def eingerichtet(novnc, monkeypatch):
    monkeypatch.setattr(pf, "FENSTER_WS", "ws://bewerbung-portal:6080")
    monkeypatch.setattr(pf, "FENSTER_SCHLUESSEL", SCHLUESSEL)
    monkeypatch.setattr(bewerbung_pult, "eingerichtet", lambda: True)


@pytest.fixture
def zentrale(monkeypatch):
    z = FalscheZentrale()
    monkeypatch.setattr(bewerbung_pult, "anfrage", z.anfrage)
    return z


@pytest.fixture
def upstream(monkeypatch):
    v = FalscheVerbindung()
    monkeypatch.setattr(websockets, "connect", v)
    return v


@pytest.fixture
def anmeldung(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _benutzer(rolle):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    return "sitzung=" + ui._sitzung_bauen("mira", time.time() + 3600)


def _http(rolle="freigeben"):
    cookie = _benutzer(rolle)
    return TestClient(ui.app, headers={"host": HOST, "cookie": cookie})


def _ws_kopf(rolle="freigeben"):
    return {"host": HOST, "origin": f"http://{HOST}", "cookie": _benutzer(rolle)}


# ------------------------------------------------------------------ Relay: 410

@pytest.mark.parametrize("pfad", ["/seite", "/fenster.js", "/novnc/core/rfb.js"])
def test_relay_http_410(anmeldung, eingerichtet, zentrale, upstream, pfad):
    r = _http().get(PFAD + pfad)
    assert r.status_code == 410 and r.text == "Fenster entfernt"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/plain")
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


@pytest.mark.parametrize("pfad", ["/seite", "/fenster.js", "/novnc/core/rfb.js", "/novnc/gibt/es/nicht.js"])
def test_relay_http_410_auch_ohne_einrichtung_und_nur_fuer_freigeben(anmeldung, novnc, zentrale, upstream, pfad):
    # Ohne Einrichtung bleibt es bei 410; wer die Rolle `freigeben` nicht hat, kommt schon an der Wache nicht vorbei.
    assert _http("freigeben").get(PFAD + pfad).status_code == 410
    assert _http("lesen").get(PFAD + pfad).status_code == 403
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


def test_relay_ws_schliesst_ohne_zentrale_und_container(anmeldung, eingerichtet, zentrale, upstream):
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008          # vor dem Annehmen: der Handshake scheitert
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


@pytest.mark.parametrize("rolle", ["freigeben", "lesen"])
def test_relay_ws_schliesst_auch_ohne_einrichtung(anmeldung, novnc, zentrale, upstream, rolle):
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf(rolle)):
            pass
    assert e.value.code == 1008
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


def test_relay_ws_nimmt_nie_an(anmeldung, eingerichtet, zentrale, upstream):
    """Der Handler schliesst, bevor er `accept` aufruft."""
    schritte = []

    class Ws:
        scope = {"subprotocols": ["binary"], "benutzer_name": "mira"}

        async def accept(self, *a, **kw):
            schritte.append("accept")

        async def close(self, code=1000):
            schritte.append(("close", code))

    for route in pf.routen(ui):
        if getattr(route, "path", "") == WS_PFAD:
            asyncio.run(route.endpoint(Ws()))
    assert schritte == [("close", 1008)]
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


def test_routen_haben_dieselben_pfade_wie_vorher():
    pfade = sorted(r.path for r in pf.routen(ui))
    assert pfade == sorted([PFAD + "/seite", PFAD + "/fenster.js", PFAD + "/novnc/{pfad:path}", WS_PFAD])


# ------------------------------------------------------------------ trennen

def test_trennen_ohne_offenes_fenster_ist_harmlos():
    pf._AKTUELL = None
    pf.trennen("mira")
    pf.trennen(None)


@pytest.mark.parametrize("name", [None, "", "olga"])
def test_trennen_beendet_nur_das_fenster_des_eigenen_benutzers(name):
    async def lauf():
        v = pf._Verbindung("mira")
        pf._AKTUELL = v
        pf.trennen(name)
        await asyncio.sleep(0)
        offen = not v.ende.is_set()
        pf.trennen("mira")
        await asyncio.sleep(0)
        return offen, v.ende.is_set()
    try:
        assert asyncio.run(lauf()) == (True, True)
    finally:
        pf._AKTUELL = None


def test_websockets_logger_bleibt_ueber_debug():
    # Auf DEBUG druckt websockets die Kopfzeilen (Authorization) ins Log.
    assert logging.getLogger("websockets").level == logging.INFO


# ------------------------------------------------------------------ eingerichtet()

@pytest.mark.parametrize("schluessel,erwartet", [
    (SCHLUESSEL, True), ("", False), ("mit leerzeichen", False), ("ümlaut", False),
    ("tab\there", False),
])
def test_eingerichtet_prueft_den_schluessel(eingerichtet, monkeypatch, schluessel, erwartet):
    monkeypatch.setattr(pf, "FENSTER_SCHLUESSEL", schluessel)
    assert pf.eingerichtet() is erwartet


def test_eingerichtet_braucht_alles(eingerichtet, monkeypatch):
    assert pf.eingerichtet() is True
    monkeypatch.setattr(pf, "FENSTER_WS", "")
    assert pf.eingerichtet() is False
