"""Ollama-Client gegen einen lokalen HTTP-Stub (Muster: test_vexa).

Die Schranken-Tests ueber briefing/auswertung (einziger Endpunkt, keine
fremden KI-Importe) kommen in Task 10; hier nur ollama.py selbst.
"""
import ast
import json
import logging
import pathlib
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
        "options": {"temperature": 0.2},
    }


def test_chat_body_als_json_und_modell(stub, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELL", "anderes:3b")
    stub.antworten[("POST", "/api/chat")] = _antwort("{}")
    ollama.chat("s", "n", als_json=True)
    body = json.loads(stub.anfragen[0][2])
    assert body["format"] == "json"
    assert body["model"] == "anderes:3b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.2}


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
    stub.verzoegerung = 1.5
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


def test_ollama_py_ohne_fremde_ki_importe():
    quelle = pathlib.Path(ollama.__file__).read_text(encoding="utf-8")
    verboten = {"gateway", "openai", "anthropic", "requests", "httpx"}
    gefunden = set()
    for knoten in ast.walk(ast.parse(quelle)):
        if isinstance(knoten, ast.Import):
            gefunden |= {a.name.split(".")[0] for a in knoten.names}
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            gefunden.add(knoten.module.split(".")[0])
    assert not (gefunden & verboten)
