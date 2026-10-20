"""sales-stt zieht auf den PC (20.10.2026, Betreiber-Regel: keine Modelle auf der VM).

Der Dienst laeuft am PC und ist nur ueber das Tailnet erreichbar; ein Schluessel (X-STT-Key) schuetzt ihn dort.
Ohne gesetzten Schluessel verhaelt er sich wie bisher (Container im eigenen Netz)."""
import importlib.util
import io
import json
import pathlib
import threading
import urllib.error
import urllib.request

import pytest

STT_PFAD = pathlib.Path(__file__).resolve().parents[2] / "sales-stt" / "stt.py"


def _stt_laden(monkeypatch, **umgebung):
    for k in ("STT_SCHLUESSEL", "STT_HOST"):
        monkeypatch.delenv(k, raising=False)
    for k, v in umgebung.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("stt_probe", STT_PFAD)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _starten(stt, monkeypatch):
    monkeypatch.setattr(stt, "transkribieren", lambda audio: {"text": "hallo", "sprache": "de", "dauer_s": 1.0})
    dienst = stt.Dienst(("127.0.0.1", 0), stt.Handler)
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    return dienst, f"http://127.0.0.1:{dienst.server_address[1]}"


def _post(url, kopf=None):
    req = urllib.request.Request(url + "/transkribieren", data=b"OggS-audio", method="POST",
                                 headers={"Content-Type": "application/octet-stream", **(kopf or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_mit_schluessel_nur_mit_richtigem_kopf(monkeypatch):
    stt = _stt_laden(monkeypatch, STT_SCHLUESSEL="geheim-123")
    dienst, url = _starten(stt, monkeypatch)
    try:
        assert _post(url)[0] == 401
        assert _post(url, {"X-STT-Key": "falsch"})[0] == 401
        code, antwort = _post(url, {"X-STT-Key": "geheim-123"})
        assert code == 200 and antwort["text"] == "hallo"
        # Gesundheit bleibt ohne Schluessel lesbar (verraet nichts) - fuer Waechter und Probe
        with urllib.request.urlopen(url + "/gesundheit", timeout=10) as r:
            assert r.status == 200
    finally:
        dienst.shutdown()


def test_ohne_schluessel_wie_bisher(monkeypatch):
    stt = _stt_laden(monkeypatch)
    dienst, url = _starten(stt, monkeypatch)
    try:
        assert _post(url)[0] == 200
    finally:
        dienst.shutdown()


def test_bindadresse_ist_einstellbar(monkeypatch):
    assert _stt_laden(monkeypatch).HOST == "0.0.0.0"                       # Container: wie bisher
    assert _stt_laden(monkeypatch, STT_HOST="127.0.0.1").HOST == "127.0.0.1"   # PC: nur lokal, Tailnet davor


def test_sales_mcp_schickt_den_schluessel_mit(monkeypatch):
    import server
    gesehen = {}

    class Antwort(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        gesehen["kopf"] = dict(req.header_items())
        gesehen["url"] = req.full_url
        return Antwort(json.dumps({"text": "ok"}).encode())

    monkeypatch.setattr(server, "STT_SCHLUESSEL", "geheim-123")
    monkeypatch.setattr(server.urllib.request, "urlopen", urlopen)
    assert server._stt_aufrufen(b"audio") == {"text": "ok"}
    assert gesehen["kopf"].get("X-stt-key") == "geheim-123"
    monkeypatch.setattr(server, "STT_SCHLUESSEL", "")
    server._stt_aufrufen(b"audio")
    assert "X-stt-key" not in gesehen["kopf"]
