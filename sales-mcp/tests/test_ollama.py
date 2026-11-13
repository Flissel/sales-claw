"""Ollama-Client gegen einen lokalen HTTP-Stub (Muster: test_vexa).

Die Schranken-Tests (einziger Endpunkt, keine fremden KI-Importe, auch fuer
ollama.py) stehen in test_ki_schranke.py.
"""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import ollama

GEHEIM = "kundentext-streng-vertraulich"


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _antwort(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        koerper = self.rfile.read(laenge).decode() if laenge else ""
        self.server.anfragen.append((self.command, self.path, koerper))
        if self.server.verzoegerung:
            time.sleep(self.server.verzoegerung)
        status, roh = self.server.antworten.get(
            (self.command, self.path), (200, b"{}"))
        if not isinstance(roh, bytes):
            roh = json.dumps(roh).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)
        except OSError:
            pass

    do_GET = do_POST = _antwort


@pytest.fixture
def stub(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    server.anfragen, server.antworten, server.verzoegerung = [], {}, 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.delenv("OLLAMA_MODELL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_S", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_BRIEFING_TIMEOUT_S", raising=False)
    yield server
    server.shutdown()
    server.server_close()


def _antwort(text):
    return (200, {"message": {"role": "assistant", "content": text}, "done": True})


def test_nicht_konfiguriert(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert ollama.erreichbar() is False
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")
    monkeypatch.setenv("OLLAMA_URL", "  ")
    assert ollama.erreichbar() is False
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")


def test_chat_body(stub):
    stub.antworten[("POST", "/api/chat")] = _antwort("hallo")
    assert ollama.chat("Systemtext", "Nutzertext") == "hallo"
    methode, pfad, koerper = stub.anfragen[0]
    assert (methode, pfad) == ("POST", "/api/chat")
    assert json.loads(koerper) == {
        "model": "qwen2.5:7b",
        "messages": [{"role": "system", "content": "Systemtext"},
                     {"role": "user", "content": "Nutzertext"}],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }


def test_chat_body_als_json_und_modell(stub, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELL", "anderes:3b")
    stub.antworten[("POST", "/api/chat")] = _antwort("{}")
    ollama.chat("s", "n", als_json=True)
    body = json.loads(stub.anfragen[0][2])
    assert body["format"] == "json"
    assert body["model"] == "anderes:3b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.2, "num_ctx": 8192}


def test_erreichbar_ok_und_pfad(stub):
    assert ollama.erreichbar() is True
    assert stub.anfragen[0][:2] == ("GET", "/api/tags")


def test_erreichbar_wirft_nie(stub, monkeypatch):
    stub.antworten[("GET", "/api/tags")] = (500, b"{}")
    assert ollama.erreichbar() is False
    stub.shutdown()
    stub.server_close()
    assert ollama.erreichbar() is False  # Verbindung verweigert
    monkeypatch.setenv("OLLAMA_URL", "ht!tp://::garbage")
    assert ollama.erreichbar() is False
    monkeypatch.setenv("OLLAMA_URL", "kein-schema")
    assert ollama.erreichbar() is False


def test_chat_fehlerfaelle(stub, monkeypatch):
    stub.antworten[("POST", "/api/chat")] = (500, b"{}")
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")
    stub.antworten[("POST", "/api/chat")] = (200, b"kein json")
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")
    stub.antworten[("POST", "/api/chat")] = (200, {"ohne": "message"})
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")
    stub.antworten[("POST", "/api/chat")] = (200, {"message": {"content": 5}})
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")
    # Zeitueberschreitung
    stub.antworten[("POST", "/api/chat")] = _antwort("spaet")
    stub.verzoegerung = 3
    monkeypatch.setenv("OLLAMA_TIMEOUT_S", "1")
    with pytest.raises(ollama.OllamaFehler):
        ollama.chat("s", "n")


def test_kein_kundentext_im_log_oder_fehler(stub, caplog):
    caplog.set_level(logging.DEBUG)
    stub.antworten[("POST", "/api/chat")] = (500, GEHEIM.encode())
    with pytest.raises(ollama.OllamaFehler) as fehler:
        ollama.chat(GEHEIM, GEHEIM)
    assert GEHEIM not in str(fehler.value)
    assert GEHEIM not in caplog.text
    stub.antworten[("POST", "/api/chat")] = _antwort(GEHEIM)
    ollama.chat(GEHEIM, GEHEIM)
    assert GEHEIM not in caplog.text


def test_timeout_aus_umgebung(monkeypatch):
    for roh, erwartet in [("", 300), ("abc", 300), ("0", 300), ("-5", 300),
                          ("nan", 300), ("inf", 300), ("2.5", 2.5), ("40", 40)]:
        monkeypatch.setenv("OLLAMA_TIMEOUT_S", roh)
        assert ollama._timeout() == erwartet, roh


def test_erreichbar_nutzt_3s_limit(stub, monkeypatch):
    gesehen = []
    echt = ollama.urllib.request.urlopen

    def spion(req, timeout=None):
        gesehen.append(timeout)
        return echt(req, timeout=timeout)

    monkeypatch.setattr(ollama.urllib.request, "urlopen", spion)
    assert ollama.erreichbar() is True
    assert gesehen == [3]


# --- Final-Review I8/I9/I7c --------------------------------------------------

def test_i8_num_ctx_in_jedem_chat(stub, monkeypatch):
    stub.antworten[("POST", "/api/chat")] = _antwort("x")
    ollama.chat("s", "n")
    ollama.chat("s", "n", als_json=True)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    ollama.chat("s", "n")
    for kaputt in ("abc", "0", "-1"):
        monkeypatch.setenv("OLLAMA_NUM_CTX", kaputt)
        ollama.chat("s", "n")
    werte = [json.loads(a[2])["options"]["num_ctx"] for a in stub.anfragen]
    assert werte == [8192, 8192, 16384, 8192, 8192, 8192]


def test_i9_erreichbar_ist_leise(stub, caplog):
    caplog.set_level(logging.DEBUG)
    stub.antworten[("GET", "/api/tags")] = (500, b"{}")
    assert ollama.erreichbar() is False
    stub.shutdown()
    stub.server_close()
    assert ollama.erreichbar() is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_i7c_eigenes_zeitlimit_je_aufruf(stub, monkeypatch):
    gesehen = []
    echt = ollama.urllib.request.urlopen

    def spion(req, timeout=None):
        gesehen.append(timeout)
        return echt(req, timeout=timeout)

    monkeypatch.setattr(ollama.urllib.request, "urlopen", spion)
    stub.antworten[("POST", "/api/chat")] = _antwort("x")
    ollama.chat("s", "n")
    ollama.chat("s", "n", timeout_s=ollama.briefing_timeout())
    monkeypatch.setenv("OLLAMA_BRIEFING_TIMEOUT_S", "15")
    ollama.chat("s", "n", timeout_s=ollama.briefing_timeout())
    assert gesehen == [300, 60, 15]
    for kaputt in ("", "abc", "0", "nan"):
        monkeypatch.setenv("OLLAMA_BRIEFING_TIMEOUT_S", kaputt)
        assert ollama.briefing_timeout() == 60


def test_ollama_chat_haengt_bilder_an(stub):
    import base64
    stub.antworten[("POST", "/api/chat")] = _antwort("ok")
    assert ollama.chat("S", "N", bilder=[b"\xff\xd8abc", b"\x00\x01"]) == "ok"
    body = json.loads(stub.anfragen[0][2])
    assert body["messages"][0] == {"role": "system", "content": "S"}
    assert body["messages"][1] == {
        "role": "user", "content": "N",
        "images": [base64.b64encode(b"\xff\xd8abc").decode(),
                   base64.b64encode(b"\x00\x01").decode()]}


def test_ollama_chat_ohne_bilder_hat_kein_images_feld(stub):
    stub.antworten[("POST", "/api/chat")] = _antwort("ok")
    ollama.chat("S", "N", bilder=None)
    ollama.chat("S", "N", bilder=[])
    for _m, _p, k in stub.anfragen:
        assert "images" not in json.loads(k)["messages"][1]
