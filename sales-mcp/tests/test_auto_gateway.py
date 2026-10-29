"""sales-auto gegen eine Attrappe des OpenClaw-Gateways (29.10.2026).

Echtes HTTP auf 127.0.0.1, kein Modell, keine Datenbank: geprueft wird nur der
neue Aufrufweg - Kopfzeilen, die Fail-closed-Pruefung ueber /v1/models, die
Fehlerordnung (voruebergehend vs. endgueltig) und dass der Token in keiner
Meldung steht. Dazu die Compose-Seite: jeder Laden ruft sein eigenes Gateway.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auto  # noqa: E402

TOKEN = "attrappen-token-1234567890abcdef"
WURZEL = Path(__file__).resolve().parents[2]


class Attrappe:
    def __init__(self):
        self.modelle = ["openclaw", "openclaw/default", "openclaw/main", "openclaw/auto"]
        self.status_modelle = 200
        self.status_chat = 200
        self.chat_koerper = None
        self.anfragen = []


@pytest.fixture
def gateway(monkeypatch):
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
            if a.status_modelle != 200:
                return self._senden(a.status_modelle, {"error": {"message": f"nein, {TOKEN}"}})
            self._senden(200, {"object": "list", "data": [{"id": m} for m in a.modelle]})

        def do_POST(self):
            koerper = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            a.anfragen.append(("POST", self.path, dict(self.headers), koerper))
            if a.status_chat != 200:
                return self._senden(a.status_chat, {"error": {"message": f"kaputt Bearer {TOKEN}"}})
            self._senden(200, a.chat_koerper or {"choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"function": {"name": "antwort_abgeben", "arguments": json.dumps(
                    {"antwort": "Gern!", "beraterin_noetig": False, "stopp_wunsch": False,
                     "begruendung": ""})}}]}}]})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(auto, "OPENCLAW_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(auto, "OPENCLAW_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setattr(auto, "HTTP_TIMEOUT_S", 5)
    yield a
    srv.shutdown()


SCHLUESSEL = "agent:auto:sales-auto:lead:5b0f2c3e-8a41-4d7e-9c55-0e1f2a3b4c5d:nachricht:1"


def _kopf(anfrage, name):
    return {k.lower(): v for k, v in anfrage[2].items()}.get(name.lower())


def test_aufruf_mit_token_sitzungsschluessel_und_agent(gateway):
    daten = auto._api_aufruf({"model": "openclaw/auto", "messages": []}, SCHLUESSEL)
    assert daten["choices"][0]["finish_reason"] == "tool_calls"
    get, post = gateway.anfragen
    assert (get[0], get[1]) == ("GET", "/v1/models")          # erst die Pruefung
    assert (post[0], post[1]) == ("POST", "/v1/chat/completions")
    assert _kopf(post, "Authorization") == f"Bearer {TOKEN}"
    assert _kopf(post, "x-openclaw-session-key") == SCHLUESSEL
    assert _kopf(post, "x-openclaw-agent-id") == "auto"


def test_ohne_agent_auto_wird_nichts_gesendet(gateway):
    """Fehlt `auto`, liefe der Lauf bei einem Agenten MIT Werkzeugen."""
    gateway.modelle = ["openclaw", "openclaw/main"]
    with pytest.raises(auto.AutoTransient, match="fehlt im Gateway"):
        auto._api_aufruf({}, SCHLUESSEL)
    assert [a[0] for a in gateway.anfragen] == ["GET"]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_verweigerte_pruefung_ist_voruebergehend_und_ohne_token(gateway, status):
    """Ein Konfigurationsfehler des Dienstes ist kein Fehler DIESER Kundennachricht."""
    gateway.status_modelle = status
    with pytest.raises(auto.AutoTransient) as e:
        auto._api_aufruf({}, SCHLUESSEL)
    assert TOKEN not in str(e.value)
    assert [a[0] for a in gateway.anfragen] == ["GET"]


@pytest.mark.parametrize("status,art", [(429, auto.AutoTransient), (503, auto.AutoTransient),
                                         (408, auto.AutoTransient), (400, auto.AutoFehler)])
def test_fehlerordnung_beim_chat(gateway, status, art):
    gateway.status_chat = status
    with pytest.raises(art) as e:
        auto._api_aufruf({}, SCHLUESSEL)
    assert TOKEN not in str(e.value)                            # landet sonst in DB und Log


def test_gateway_nicht_erreichbar_ist_voruebergehend(monkeypatch):
    monkeypatch.setattr(auto, "OPENCLAW_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(auto, "HTTP_TIMEOUT_S", 2)
    with pytest.raises(auto.AutoTransient, match="nicht erreichbar"):
        auto._api_aufruf({}, SCHLUESSEL)


def test_sitzungsschluessel_beginnt_mit_agent_auto():
    k = {"lead_id": "5b0f2c3e-8a41-4d7e-9c55-0e1f2a3b4c5d",
         "created_at": datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)}
    assert auto._sitzungsschluessel(k) == (
        "agent:auto:sales-auto:lead:5b0f2c3e-8a41-4d7e-9c55-0e1f2a3b4c5d:nachricht:1793264400000")


def _compose_abschnitt(dienst):
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(dienst)}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    assert m, dienst
    return "\n".join(z for z in m.group(1).splitlines() if not z.lstrip().startswith("#"))


def test_jeder_laden_ruft_sein_eigenes_gateway():
    abschnitt = _compose_abschnitt("sales-auto")
    assert "OPENCLAW_URL: http://${LADEN_PRAEFIX:-sales}-claw:18894" in abschnitt
    assert "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}" in abschnitt
    assert "AUTO_MODELL" not in abschnitt                      # das Modell kommt aus openclaw.json


def test_gateway_token_nur_bei_sales_auto():
    for dienst in ("sales-mcp", "sales-ui", "sales-dispatch", "sales-inbox", "sales-mail", "sales-claw"):
        assert "OPENCLAW_GATEWAY_TOKEN" not in _compose_abschnitt(dienst), dienst
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    anker = text[text.index("x-sales-mcp-umgebung"):text.index("services:")]
    assert "OPENCLAW_GATEWAY_TOKEN" not in anker


def test_anbinde_skript_gibt_den_token_nie_aus_und_startet_nichts():
    skript = (WURZEL / "deploy" / "auto-anbinden.sh").read_text(encoding="utf-8")
    code = "\n".join(z for z in skript.splitlines() if not z.lstrip().startswith("#"))
    assert not re.search(r"set -[a-z]*x", code)
    assert "echo \"$TOKEN\"" not in code and "echo $TOKEN" not in code
    assert 'sed "s#${TOKEN}#<token>#g"' in code and "unset TOKEN" in code
    assert '"deny": ["*"]' in code or 'deny: ["*"]' in code
    assert "docker restart" not in code.replace("(docker restart $CONTAINER, mit dem Betreiber", "")
    assert "compose up" not in code.replace("docker compose up -d sales-auto (bzw.", "")


def test_saat_kennt_agent_auto_ohne_werkzeuge_und_den_endpunkt():
    c = json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))
    agenten = {a["id"]: a for a in c["agents"]["list"]}
    assert agenten["auto"]["tools"] == {"deny": ["*"]}
    assert agenten["auto"]["workspace"] != c["agents"]["defaults"]["workspace"]
    assert c["agents"]["list"][0]["id"] == "main"               # main bleibt der Standard-Agent
    assert c["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"] is True
