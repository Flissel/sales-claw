"""Portal-Fenster hinter der Anmeldung (Portal-Abgabe, Task 11).

Der Bot im Container zeigt sein Chromium als VNC-WebSocket; sales-ui liefert noVNC (eigene
Seite, kein vnc_lite.html wegen der CSP) und reicht den WebSocket an den Container weiter -
hinter Host-, Origin-, Sitzungs- und Rollenpruefung. Fakes: die Zentrale (`bewerbung_pult.anfrage`)
und `websockets.connect` (In-Memory). Es wird nie echtes noVNC gebraucht."""
import asyncio
import base64
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
from websockets.exceptions import ConnectionClosedOK  # noqa: E402

import bewerbung_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_portal_fenster as pf  # noqa: E402
from pult_http import PultFehler  # noqa: E402

HOST = "127.0.0.1:8791"
GEHEIMNIS = "test-geheimnis-nur-fuer-die-suite"
SCHLUESSEL = "fenster-schluessel-nur-fuer-die-suite-7Q"
WS_PFAD = "/freigaben/bewerbung/fenster/ws"
PFAD = "/freigaben/bewerbung/fenster"


class FalscherUpstream:
    """Die andere Seite (websockify im Container), im Speicher."""

    def __init__(self, vorrat):
        self.gesendet = []
        self.geschlossen = None
        self._q = asyncio.Queue()
        for b in vorrat:
            self._q.put_nowait(b)

    async def send(self, daten):
        self.gesendet.append(daten)

    async def recv(self):
        r = await self._q.get()
        if r is None:
            raise ConnectionClosedOK(None, None)
        return r

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionClosedOK:
            raise StopAsyncIteration

    async def close(self, code=1000, grund=""):
        if self.geschlossen is None:
            self.geschlossen = code
        self._q.put_nowait(None)


class FalscheVerbindung:
    def __init__(self, vorrat=(b"xyz",), fehler=None):
        self.vorrat = list(vorrat)
        self.fehler = fehler
        self.aufrufe = []   # (url, kwargs)
        self.upstreams = []

    async def __call__(self, url, **kw):
        self.aufrufe.append((url, kw))
        if self.fehler:
            raise self.fehler
        u = FalscherUpstream(self.vorrat)
        self.upstreams.append(u)
        return u


class FalscheZentrale:
    def __init__(self, antwort=None, fehler=None):
        self.antwort = antwort if antwort is not None else {
            "lauf_id": "l-1", "application_id": "a-1", "zustand": "fenster_angefragt"}
        self.fehler = fehler
        self.aufrufe = []

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, zeitlimit))
        if self.fehler:
            raise self.fehler
        return self.antwort


@pytest.fixture
def novnc(tmp_path, monkeypatch):
    d = tmp_path / "novnc"
    (d / "core").mkdir(parents=True)
    (d / "vendor").mkdir()
    (d / "core" / "rfb.js").write_text("export default class RFB {}\n", encoding="utf-8")
    (d / "core" / "stil.css").write_text("body{}\n", encoding="utf-8")
    (d / "LICENSE.txt").write_text("MPL\n", encoding="utf-8")
    (tmp_path / "geheim.txt").write_text("nicht ausliefern", encoding="utf-8")
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


_ENDEN: list = []          # je Verbindung ein Ereignis: gesetzt, wenn der Handler ganz durch ist
_POOL = ThreadPoolExecutor(4)


@pytest.fixture
def upstream(monkeypatch):
    v = FalscheVerbindung()
    monkeypatch.setattr(pf.websockets, "connect", v)
    _ENDEN.clear()
    original = pf.weiterleitung

    async def umhuellt(ws, ui=None):
        ende = threading.Event()
        _ENDEN.append(ende)
        try:
            await original(ws, ui)
        finally:
            ende.set()

    monkeypatch.setattr(pf, "weiterleitung", umhuellt)
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


def _zu(ws, upstream=None, nr=-1):
    """Client macht zu und wartet, bis der Handler ganz durch ist (Ereignis am Ende seines finally):
    der TestClient bricht ihn beim Verlassen des Blocks sonst mitten im Aufraeumen ab."""
    ws.close(1000)
    assert _ENDEN[nr].wait(5), "Handler wurde nicht fertig"


def _empfange(ws, sekunden=5):
    """Naechste Nachricht, aber begrenzt: ein Fehler laesst den Test scheitern statt haengen."""
    return _POOL.submit(ws.receive).result(timeout=sekunden)


def _ws_kopf(rolle="freigeben"):
    return {"host": HOST, "origin": f"http://{HOST}", "cookie": _benutzer(rolle)}


# ------------------------------------------------------------------ Relay

def test_fenster_ws_nur_mit_aktiver_sitzung(anmeldung, eingerichtet, zentrale, upstream):
    zentrale.antwort = {"lauf_id": None, "application_id": None, "zustand": None}
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008
    assert upstream.aufrufe == []
    assert zentrale.aufrufe == [("GET", "/portal/fenster", 3)]


@pytest.mark.parametrize("zustand", ["bereit", "abgeschickt", "fertig", "", 5])
def test_fenster_ws_nur_in_den_zwei_zustaenden(anmeldung, eingerichtet, zentrale, upstream, zustand):
    zentrale.antwort = {"lauf_id": "l", "application_id": "a", "zustand": zustand}
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008 and upstream.aufrufe == []


@pytest.mark.parametrize("fehler", [PultFehler("zeitlimit", "x"), RuntimeError("boom")])
def test_fenster_ws_zentrale_fehler_schliesst(anmeldung, eingerichtet, zentrale, upstream, fehler):
    zentrale.fehler = fehler
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008 and upstream.aufrufe == []


@pytest.mark.parametrize("antwort", [["liste"], "text", None])
def test_fenster_ws_unsinnige_antwort_schliesst(anmeldung, eingerichtet, zentrale, upstream, antwort):
    zentrale.antwort = antwort
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008 and upstream.aufrufe == []


def test_fenster_ws_reicht_bytes_durch(anmeldung, eingerichtet, zentrale, upstream):
    with TestClient(ui.app).websocket_connect(
            WS_PFAD, headers=_ws_kopf(), subprotocols=["binary"]) as ws:
        assert ws.accepted_subprotocol == "binary"
        ws.send_bytes(b"abc")
        assert ws.receive_bytes() == b"xyz"
        _zu(ws, upstream)
    # Mit dem Verlassen des Blocks ist der Handler durch.
    assert upstream.upstreams[0].gesendet == [b"abc"]
    assert upstream.upstreams[0].geschlossen is not None


def test_fenster_ws_im_zustand_im_fenster_ebenso(anmeldung, eingerichtet, zentrale, upstream):
    zentrale.antwort = {"lauf_id": "l", "application_id": "a", "zustand": "im_fenster"}
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"xyz"
        _zu(ws, upstream)


def test_upstream_bekommt_adresse_unterprotokoll_und_schluessel_im_kopf(
        anmeldung, eingerichtet, zentrale, upstream):
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        ws.receive_bytes()
        _zu(ws, upstream)
    url, kw = upstream.aufrufe[0]
    assert url == "ws://bewerbung-portal:6080/websockify"
    assert kw["subprotocols"] == ["binary"] and kw["max_size"] is None and kw["open_timeout"] == 5
    assert kw["close_timeout"] == 2
    erwartet = "Basic " + base64.b64encode(f"portal:{SCHLUESSEL}".encode()).decode()
    koepfe = [tuple(k) for k in kw["extra_headers"]]
    assert ("Authorization", erwartet) in koepfe
    assert "additional_headers" not in kw


def test_upstream_fehler_schliesst_sauber_ohne_einzelheiten(
        anmeldung, eingerichtet, zentrale, upstream, caplog):
    upstream.fehler = OSError(f"kaputt gegen ws://portal:{SCHLUESSEL}@host")
    with caplog.at_level("DEBUG"):
        with pytest.raises(WebSocketDisconnect) as e:
            with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
                ws.receive_bytes()
    assert e.value.code == 1011
    assert SCHLUESSEL not in (e.value.reason or "")
    assert SCHLUESSEL not in caplog.text and "kaputt" not in caplog.text


def test_upstream_schliesst_dann_schliesst_der_client(anmeldung, eingerichtet, zentrale, upstream):
    upstream.vorrat = [b"eins", None]   # None = der Container macht zu
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"eins"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
        assert e.value.code == 1000
    assert upstream.upstreams[0].geschlossen is not None


def test_neue_verbindung_ersetzt_alte(anmeldung, eingerichtet, zentrale, upstream):
    c = TestClient(ui.app)
    kopf = _ws_kopf()
    with c.websocket_connect(WS_PFAD, headers=kopf) as ws1:
        assert ws1.receive_bytes() == b"xyz"
        with c.websocket_connect(WS_PFAD, headers=kopf) as ws2:
            assert ws2.receive_bytes() == b"xyz"
            # Begrenzt: fehlt das Ersetzen, scheitert der Test statt zu haengen.
            m = _empfange(ws1)
            assert m["type"] == "websocket.close" and m["code"] == 1000
            _zu(ws2, upstream)
        _zu(ws1, upstream, 0)
    assert len(upstream.upstreams) == 2
    assert all(u.geschlossen is not None for u in upstream.upstreams)


@pytest.mark.parametrize("fehlt", ["ws", "schluessel", "rfb", "pult"])
def test_relay_ohne_einrichtung_schliesst_ohne_jemanden_zu_fragen(
        anmeldung, eingerichtet, zentrale, upstream, monkeypatch, fehlt):
    if fehlt == "ws":
        monkeypatch.setattr(pf, "FENSTER_WS", "")
    elif fehlt == "schluessel":
        monkeypatch.setattr(pf, "FENSTER_SCHLUESSEL", "")
    elif fehlt == "rfb":
        (pf.NOVNC_DIR / "core" / "rfb.js").unlink()
    else:
        monkeypatch.setattr(bewerbung_pult, "eingerichtet", lambda: False)
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()):
            pass
    assert e.value.code == 1008
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


def test_relay_nur_fuer_freigeben(anmeldung, eingerichtet, zentrale, upstream):
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf("lesen")):
            pass
    assert e.value.code == 1008
    assert zentrale.aufrufe == [] and upstream.aufrufe == []


# ------------------------------------------------------------------ Nachpruefen im offenen Fenster

@pytest.fixture
def schnell(monkeypatch):
    monkeypatch.setattr(pf, "NACHPRUEFEN_S", 0.05)


def _bis_geschlossen(ws, upstream):
    m = _empfange(ws)
    assert m["type"] == "websocket.close" and m["code"] == 1008, m
    assert _ENDEN[-1].wait(5), "Handler wurde nicht fertig"
    assert upstream.upstreams[0].geschlossen is not None


def test_offenes_fenster_bleibt_offen_solange_alles_gilt(
        anmeldung, eingerichtet, zentrale, upstream, schnell):
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"xyz"
        for _ in range(500):
            if len(zentrale.aufrufe) >= 4:
                break
            time.sleep(0.01)
        assert len(zentrale.aufrufe) >= 4        # es wird wirklich nachgefragt
        assert upstream.upstreams[0].geschlossen is None
        ws.send_bytes(b"noch da")
        _zu(ws)
    assert upstream.upstreams[0].gesendet == [b"noch da"]


def test_zustand_wechselt_mitten_in_der_sitzung(anmeldung, eingerichtet, zentrale, upstream, schnell):
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"xyz"
        zentrale.antwort = {"lauf_id": "l-1", "application_id": "a-1", "zustand": "bereit"}
        _bis_geschlossen(ws, upstream)


@pytest.mark.parametrize("fehler", [PultFehler("zeitlimit", "x"), RuntimeError("boom")])
def test_zentrale_faellt_mitten_in_der_sitzung_aus(
        anmeldung, eingerichtet, zentrale, upstream, schnell, fehler):
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"xyz"
        zentrale.fehler = fehler
        _bis_geschlossen(ws, upstream)


@pytest.mark.parametrize("wie", ["benutzer_aus", "rolle_lesen", "geheimnis_gedreht", "sitzung_abgelaufen"])
def test_sitzung_endet_mitten_in_der_sitzung(
        anmeldung, eingerichtet, zentrale, upstream, schnell, monkeypatch, wie):
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert ws.receive_bytes() == b"xyz"
        if wie == "benutzer_aus":
            server._q("update benutzer set aktiv = false where name = %s", ("mira",))
        elif wie == "rolle_lesen":
            server._q("update benutzer set rolle = 'lesen' where name = %s", ("mira",))
        elif wie == "geheimnis_gedreht":
            monkeypatch.setattr(ui, "UI_SESSION_SECRET", "ein-ganz-anderes-geheimnis")
        else:
            monkeypatch.setattr(ui, "_sitzung_pruefen", lambda wert: None)
        _bis_geschlossen(ws, upstream)


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


def test_ohne_einrichtung_kein_rahmen(anmeldung, eingerichtet, monkeypatch):
    assert "<iframe" in pf.fenster_rahmen(ui)
    monkeypatch.setattr(pf, "FENSTER_WS", "")
    assert pf.fenster_rahmen(ui) == ""
    c = _http()
    for p in ("/seite", "/fenster.js", "/novnc/core/rfb.js"):
        assert c.get(PFAD + p).status_code == 404


def test_rahmen_zeigt_auf_eigene_seite(eingerichtet):
    html = pf.fenster_rahmen(ui)
    assert f'src="{PFAD}/seite"' in html
    assert 'class="fenster"' in html and 'title="Portal-Fenster"' in html
    assert "Groß öffnen" in html and 'target="_blank"' in html and 'rel="noopener noreferrer"' in html
    assert "vnc_lite" not in html


# ------------------------------------------------------------------ HTTP

def test_novnc_dateien_mit_eigener_csp_und_ohne_ausbruch(anmeldung, eingerichtet):
    c = _http()
    r = c.get(PFAD + "/novnc/core/rfb.js")
    assert r.status_code == 200 and "RFB" in r.text
    assert r.headers["content-security-policy"] == pf.CSP_NOVNC
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["cache-control"] == "private, max-age=3600"
    assert r.headers["content-type"].startswith("text/javascript")
    assert c.get(PFAD + "/novnc/core/stil.css").headers["content-type"].startswith("text/css")
    for boes in ("..%2Fui.py", "..%2F..%2Fui.py", "..%2Fgeheim.txt", "%2e%2e%2fgeheim.txt",
                 "core", "gibt-es-nicht.js", "core%00.js"):
        assert c.get(f"{PFAD}/novnc/{boes}").status_code == 404, boes
    assert c.get(PFAD + "/novnc/../geheim.txt").status_code == 404


def test_absoluter_pfad_und_symlink_fuehren_nicht_hinaus(anmeldung, eingerichtet, tmp_path):
    c = _http()
    geheim = tmp_path / "geheim.txt"
    assert c.get(f"{PFAD}/novnc/{geheim.as_posix()}").status_code == 404
    assert c.get(f"{PFAD}/novnc//etc/passwd").status_code == 404
    link = pf.NOVNC_DIR / "core" / "raus.txt"
    try:
        link.symlink_to(geheim)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks hier nicht erlaubt")
    assert c.get(f"{PFAD}/novnc/core/raus.txt").status_code == 404


def test_novnc_nur_fuer_rolle_freigeben(anmeldung, eingerichtet):
    c = _http("lesen")
    for p in ("/novnc/core/rfb.js", "/seite", "/fenster.js"):
        assert c.get(PFAD + p).status_code == 403, p


def test_ohne_anmeldung_keine_dateien(anmeldung, eingerichtet):
    c = TestClient(ui.app, headers={"host": HOST})
    for p in ("/novnc/core/rfb.js", "/seite", "/fenster.js"):
        r = c.get(PFAD + p, follow_redirects=False)
        assert r.status_code in (303, 401, 403), p


def test_seite_ohne_inline_skript_mit_eigener_csp(anmeldung, eingerichtet):
    r = _http().get(PFAD + "/seite")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == pf.CSP_NOVNC
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="fenster.js"></script>' in r.text
    assert r.text.count("<script") == 1
    assert "onclick" not in r.text and "onload" not in r.text and "vnc_lite" not in r.text


def test_fenster_js_ist_modul_ohne_zugangsdaten(anmeldung, eingerichtet):
    r = _http().get(PFAD + "/fenster.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["content-security-policy"] == pf.CSP_NOVNC
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["cache-control"] == "no-store"
    t = r.text
    assert 'import RFB from "./novnc/core/rfb.js"' in t
    assert "/freigaben/bewerbung/fenster/ws" in t and "scaleViewport" in t
    assert "wss:" in t and "Verbunden" in t and "Getrennt" in t
    assert "Authorization" not in t and "portal:" not in t


def test_schluessel_erreicht_den_browser_nie(anmeldung, eingerichtet, zentrale, upstream):
    c = _http()
    alles = [pf.fenster_rahmen(ui)]
    for p in ("/seite", "/fenster.js", "/novnc/core/rfb.js"):
        r = c.get(PFAD + p)
        alles.append(r.text)
        alles.append(str(dict(r.headers)))
    b64 = base64.b64encode(f"portal:{SCHLUESSEL}".encode()).decode()
    for text in alles:
        assert SCHLUESSEL not in text and b64 not in text
    # ... und oben im WebSocket: auch die Antwort-Koepfe des Handshakes sind sauber.
    with TestClient(ui.app).websocket_connect(WS_PFAD, headers=_ws_kopf()) as ws:
        assert SCHLUESSEL.encode() not in ws.receive_bytes()
        _zu(ws, upstream)
    assert upstream.aufrufe[0][1]["extra_headers"]   # er geht nur nach innen
