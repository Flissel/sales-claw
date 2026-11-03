"""gateway.funktion_aufrufen gegen eine Attrappe des OpenClaw-Gateways.

Echtes HTTP auf 127.0.0.1, kein Modell, keine Datenbank.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import gateway

TOKEN = "attrappen-token-1234567890abcdef"
SCHLUESSEL = "agent:post:sales-post:mail:1"
FUNKTION = {"type": "function", "function": {
    "name": "einordnen", "description": "x",
    "parameters": {"type": "object", "properties": {"art": {"type": "string"}}}}}


class Attrappe:
    def __init__(self):
        self.modelle = ["openclaw", "openclaw/main", "openclaw/post"]
        self.status_chat = 200
        self.chat_fehler = None
        self.anfragen = []


@pytest.fixture
def gw():
    a = Attrappe()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _senden(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            a.anfragen.append(("GET", self.path, dict(self.headers), None))
            self._senden(200, {"data": [{"id": m} for m in a.modelle]})

        def do_POST(self):
            k = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            a.anfragen.append(("POST", self.path, dict(self.headers), k))
            if a.status_chat != 200:
                return self._senden(a.status_chat, {"error": {
                    "message": a.chat_fehler or f"kaputt Bearer {TOKEN}"}})
            self._senden(200, {"choices": [{"message": {"tool_calls": [{"function": {
                "name": "einordnen", "arguments": json.dumps({"art": "rechnung"})}}]}}]})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    a.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield a
    srv.shutdown()


def _aufruf(gw, schluessel=SCHLUESSEL):
    return gateway.funktion_aufrufen("post", schluessel, "System", "Auftrag", FUNKTION,
                                     url=gw.url, token=TOKEN, timeout_s=5)


def _kopf(anfrage, name):
    return {k.lower(): v for k, v in anfrage[2].items()}.get(name.lower())


def test_aufruf_liefert_argumente(gw):
    assert _aufruf(gw) == {"art": "rechnung"}
    get, post = gw.anfragen
    assert get[1] == "/v1/models"
    assert post[1] == "/v1/chat/completions"
    assert _kopf(post, "Authorization") == f"Bearer {TOKEN}"
    assert _kopf(post, "x-openclaw-session-key") == SCHLUESSEL
    assert _kopf(post, "x-openclaw-agent-id") == "post"
    k = post[3]
    assert k["model"] == "openclaw/post"
    assert k["messages"] == [{"role": "system", "content": "System"},
                             {"role": "user", "content": "Auftrag"}]
    assert k["tools"] == [FUNKTION]
    assert k["tool_choice"] == {"type": "function", "function": {"name": "einordnen"}}


def test_fehlender_agent_sendet_nichts(gw):
    gw.modelle = ["openclaw", "openclaw/main"]
    with pytest.raises(gateway.GatewayTransient, match="fehlt im Gateway"):
        _aufruf(gw)
    assert [a[0] for a in gw.anfragen] == ["GET"]


def test_schluessel_ohne_agent_praefix_wird_abgelehnt(gw):
    with pytest.raises(ValueError):
        _aufruf(gw, "sales-post:mail:1")
    assert gw.anfragen == []


def test_did_not_produce_one_ist_endgueltig(gw):
    gw.status_chat = 502
    gw.chat_fehler = "Model did not produce one valid call"
    with pytest.raises(gateway.GatewayFehler):
        _aufruf(gw)


def test_429_ist_voruebergehend(gw):
    gw.status_chat = 429
    with pytest.raises(gateway.GatewayTransient):
        _aufruf(gw)


def test_token_in_keiner_meldung(gw):
    for status, art in [(429, gateway.GatewayTransient), (400, gateway.GatewayFehler),
                        (503, gateway.GatewayTransient)]:
        gw.status_chat = status
        with pytest.raises(art) as e:
            _aufruf(gw)
        assert TOKEN not in str(e.value)
