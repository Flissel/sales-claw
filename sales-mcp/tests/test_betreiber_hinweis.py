"""Telegram-Hinweis an den Betreiber gegen einen lokalen HTTP-Stub."""
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import betreiber_hinweis

TOKEN = "123456:streng-geheimer-bot-token"
CHAT = "987654321"
TEXT = "Briefing bereit fuer Kundin Zeppelin-Muster"


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        koerper = self.rfile.read(laenge).decode() if laenge else ""
        self.server.anfragen.append(
            (self.path, self.headers.get("Content-Type"), koerper))
        status, daten = self.server.antwort
        roh = json.dumps(daten).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)


@pytest.fixture(autouse=True)
def _zustand_frisch(monkeypatch):
    # I9: Warnungen nur beim Zustandswechsel - jeder Test beginnt frisch.
    monkeypatch.setattr(betreiber_hinweis, "_letzter_fehler", None, raising=False)


@pytest.fixture
def stub(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    srv.anfragen = []
    srv.antwort = (200, {"ok": True, "result": {}})
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("TELEGRAM_API_BASIS",
                       "http://127.0.0.1:%d" % srv.server_port)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    yield srv
    srv.shutdown()
    srv.server_close()


def _felder(srv):
    pfad, ctype, koerper = srv.anfragen[-1]
    return pfad, ctype, dict(urllib.parse.parse_qsl(koerper))


def test_senden_ok(stub):
    assert betreiber_hinweis.senden(TEXT) is True
    pfad, ctype, f = _felder(stub)
    assert pfad == f"/bot{TOKEN}/sendMessage"
    assert ctype == "application/x-www-form-urlencoded"
    assert f["chat_id"] == CHAT
    assert f["text"] == TEXT
    assert f["disable_web_page_preview"] == "true"


def test_link_vorschau_an(stub):
    assert betreiber_hinweis.senden(TEXT, link_vorschau=True) is True
    assert _felder(stub)[2]["disable_web_page_preview"] == "false"


def test_crlf_in_env_wird_gestrippt(stub, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN + "\r\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT + "\r\n")
    assert betreiber_hinweis.senden(TEXT) is True
    pfad, _, f = _felder(stub)
    assert pfad == f"/bot{TOKEN}/sendMessage"
    assert f["chat_id"] == CHAT


@pytest.mark.parametrize("fehlt", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_ohne_konfiguration_false(stub, monkeypatch, fehlt):
    monkeypatch.delenv(fehlt)
    assert betreiber_hinweis.senden(TEXT) is False
    assert stub.anfragen == []


def test_ok_false_ist_false(stub):
    stub.antwort = (200, {"ok": False, "description": "x"})
    assert betreiber_hinweis.senden(TEXT) is False


def test_kein_json_ist_false(stub):
    stub.antwort = (200, ["nicht", "ok"])
    assert betreiber_hinweis.senden(TEXT) is False


def test_kein_import_von_server():
    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys, betreiber_hinweis; "
         "assert 'server' not in sys.modules"],
        cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _kein_geheimnis(caplog):
    gesamt = "\n".join(r.getMessage() for r in caplog.records)
    for geheim in (TOKEN, CHAT, TEXT, "streng-geheimer"):
        assert geheim not in gesamt
    # auch Ausnahme-Infos (exc_text/exc_info) duerfen nichts tragen
    for r in caplog.records:
        assert r.exc_info is None
    return gesamt


def test_log_ohne_token_und_text_http_500(stub, caplog):
    stub.antwort = (500, {"ok": False})
    with caplog.at_level(logging.DEBUG):
        assert betreiber_hinweis.senden(TEXT) is False
    assert "HTTP 500" in _kein_geheimnis(caplog)


def test_log_ohne_token_und_text_verbindung_abgelehnt(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_API_BASIS", "http://127.0.0.1:1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    with caplog.at_level(logging.DEBUG):
        assert betreiber_hinweis.senden(TEXT) is False
    _kein_geheimnis(caplog)


def test_log_ohne_token_und_text_ok_false(stub, caplog):
    stub.antwort = (200, {"ok": False, "description": "Bad Request"})
    with caplog.at_level(logging.DEBUG):
        assert betreiber_hinweis.senden(TEXT) is False
    _kein_geheimnis(caplog)


def test_unerwartete_ausnahme_wirft_nie(stub, monkeypatch, caplog):
    def boese(*a, **k):
        raise RuntimeError(TOKEN + TEXT)
    monkeypatch.setattr(betreiber_hinweis.urllib.request, "urlopen", boese)
    with caplog.at_level(logging.DEBUG):
        assert betreiber_hinweis.senden(TEXT) is False
    assert "RuntimeError" in _kein_geheimnis(caplog)


# --- Final-Review I9: Warnung nur beim Zustandswechsel ---------------------

def test_i9_nicht_konfiguriert_nur_einmal(monkeypatch, caplog):
    monkeypatch.setattr(betreiber_hinweis, "_letzter_fehler", None, raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with caplog.at_level(logging.DEBUG, logger="betreiber_hinweis"):
        for _ in range(3):
            assert betreiber_hinweis.senden(TEXT) is False
    warn = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warn) == 1 and "nicht konfiguriert" in warn[0].getMessage()


def test_i9_sendefehler_einmal_je_zustand(stub, monkeypatch, caplog):
    monkeypatch.setattr(betreiber_hinweis, "_letzter_fehler", None, raising=False)
    stub.antwort = (500, {"ok": False})
    with caplog.at_level(logging.DEBUG, logger="betreiber_hinweis"):
        for _ in range(3):
            assert betreiber_hinweis.senden(TEXT) is False
        stub.antwort = (200, {"ok": True})
        assert betreiber_hinweis.senden(TEXT) is True
        stub.antwort = (500, {"ok": False})
        assert betreiber_hinweis.senden(TEXT) is False
    warn = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn == ["Telegram-Hinweis: HTTP 500", "Telegram-Hinweis: HTTP 500"]
    _kein_geheimnis(caplog)
