"""WebSocket nur mit Anmeldung, Rolle und eigener Herkunft (Portal-Abgabe, Task 10).

Beide Wachen liessen bisher jeden Nicht-HTTP-Scope ungeprueft durch. Eine Echo-Route
unter /freigaben/bewerbung/test-ws (Admin-Basis-Pfad, also Rolle `freigeben`) macht
sichtbar, ob eine Verbindung bis zur Route kommt."""
import os
import time

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.routing import WebSocketRoute  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import server  # noqa: E402
import ui  # noqa: E402

PFAD = "/freigaben/bewerbung/test-ws"
HOST = "127.0.0.1:8791"
GEHEIMNIS = "test-geheimnis-nur-fuer-die-suite"


async def _echo(ws):
    await ws.accept()
    await ws.send_text("hallo")
    await ws.close()


@pytest.fixture
def echo_route():
    route = WebSocketRoute(PFAD, _echo)
    ui.app.router.routes.insert(0, route)
    yield
    ui.app.router.routes.remove(route)


def _cookie(rolle: str) -> str:
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    return "sitzung=" + ui._sitzung_bauen("mira", time.time() + 3600)


def _kopf(host=HOST, origin="default", cookie=None):
    k = {"host": host}
    k["origin"] = f"http://{host}" if origin == "default" else origin
    if cookie:
        k["cookie"] = cookie
    return k


def _geschlossen(headers):
    c = TestClient(ui.app)
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect(PFAD, headers=headers):
            pass
    assert e.value.code == 1008


def test_websocket_ohne_anmeldung_wird_geschlossen(echo_route, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    _geschlossen(_kopf())


def test_websocket_mit_rolle_lesen_wird_geschlossen(echo_route, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    _geschlossen(_kopf(cookie=_cookie("lesen")))


def test_websocket_mit_fremdem_origin_wird_geschlossen(echo_route, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    cookie = _cookie("freigeben")
    _geschlossen(_kopf(origin="https://boese.example", cookie=cookie))
    # Fehlender Origin zaehlt wie ein fremder.
    k = _kopf(cookie=cookie)
    del k["origin"]
    _geschlossen(k)


def test_websocket_mit_falschem_host_wird_geschlossen(echo_route, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    cookie = _cookie("freigeben")
    _geschlossen(_kopf(host="boese.example", cookie=cookie))


def test_websocket_ohne_sitzungsgeheimnis_wird_geschlossen(echo_route):
    # conftest setzt UI_SESSION_SECRET leer: HTTP ist dann offen, WebSocket nicht.
    assert ui.UI_SESSION_SECRET == ""
    _geschlossen(_kopf())


def test_websocket_mit_freigeben_und_eigenem_origin_kommt_an(echo_route, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", GEHEIMNIS)
    c = TestClient(ui.app)
    with c.websocket_connect(PFAD, headers=_kopf(cookie=_cookie("freigeben"))) as ws:
        assert ws.receive_text() == "hallo"


def test_websocket_mit_gefaelschtem_cookie_ohne_sitzungsgeheimnis_wird_geschlossen(echo_route, monkeypatch):
    # SC-I1: HTTP ist ohne Geheimnis absichtlich offen; diese Wache haelt WebSockets zu. Mit leerem
    # Schluessel baut jeder, der den Namen eines aktiven `freigeben`-Benutzers kennt, ein gueltiges Cookie.
    assert ui.UI_SESSION_SECRET == ""
    monkeypatch.setattr(ui, "_benutzer_lesen",
                        lambda name: {"name": name, "rolle": "freigeben"})
    cookie = f"{ui.SITZUNG_COOKIE}=" + ui._sitzung_bauen("felix", time.time() + 3600)
    assert ui._sitzung_pruefen(cookie.split("=", 1)[1]) == "felix"      # das Cookie waere "gueltig"
    _geschlossen(_kopf(cookie=cookie))
