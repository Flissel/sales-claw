"""Tests fuer sales-ki/ki_tor.py mit einer claude-Attrappe (kein Netz, kein Abo)."""
from __future__ import annotations

import http.client
import json
import logging
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ki_tor  # noqa: E402

ATTRAPPE = r'''
import json, os, sys
args = sys.argv[1:]
eingabe = sys.stdin.read()
protokoll = os.environ["ATTRAPPE_PROTOKOLL"]
with open(protokoll, "w", encoding="utf-8") as f:
    json.dump({"args": args, "stdin": eingabe, "cwd": os.getcwd()}, f)
modus = os.environ.get("ATTRAPPE_MODUS", "text")
if modus == "fehler":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}))
    sys.exit(1)
if modus == "kaputt":
    print("kein json")
    sys.exit(0)
if modus == "json":
    antwort = 'Hier:\n```json\n{"a": 1, "b": ["x"]}\n```'
elif modus == "json-ohne":
    antwort = "Leider kein Objekt."
else:
    antwort = "Antwort zu: " + eingabe[:20]
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": antwort}))
'''

GEHEIM = "Kundin Erika sagt: unser Lager kostet 40000 Euro"


@pytest.fixture
def attrappe(tmp_path, monkeypatch):
    skript = tmp_path / "claude_attrappe.py"
    skript.write_text(ATTRAPPE, encoding="utf-8")
    protokoll = tmp_path / "protokoll.json"
    monkeypatch.setenv("KI_CLAUDE_BEFEHL", f'"{sys.executable}" "{skript}"')
    monkeypatch.setenv("ATTRAPPE_PROTOKOLL", str(protokoll))
    monkeypatch.delenv("KI_MODELL", raising=False)

    def lesen() -> dict:
        return json.loads(protokoll.read_text(encoding="utf-8"))
    return lesen


@pytest.fixture
def tor():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ki_tor.Tor)
    faden = threading.Thread(target=server.serve_forever, daemon=True)
    faden.start()

    def anfrage(methode: str, pfad: str, body: dict | bytes | None = None):
        verb = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        roh = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        verb.request(methode, pfad, body=roh,
                     headers={"Content-Type": "application/json"} if roh else {})
        r = verb.getresponse()
        daten = r.read()
        verb.close()
        return r.status, json.loads(daten)
    yield anfrage
    server.shutdown()


def _chat(nutzer: str, *, als_json: bool = False) -> dict:
    body = {"model": "qwen2.5:7b", "stream": False,
            "messages": [{"role": "system", "content": "Du bist knapp."},
                         {"role": "user", "content": nutzer}],
            "options": {"temperature": 0.2, "num_ctx": 8192}}
    if als_json:
        body["format"] = "json"
    return body


def test_tags_wie_ollama(tor):
    status, antwort = tor("GET", "/api/tags")
    assert status == 200
    assert antwort["models"][0]["name"] == "sonnet"


def test_chat_text_ueber_stdin_ohne_werkzeuge(tor, attrappe):
    status, antwort = tor("POST", "/api/chat", _chat(GEHEIM))
    assert status == 200
    assert antwort["done"] is True
    assert antwort["message"]["role"] == "assistant"
    assert antwort["message"]["content"].startswith("Antwort zu: Kundin Erika")
    lauf = attrappe()
    assert lauf["stdin"] == GEHEIM
    assert GEHEIM not in " ".join(lauf["args"])  # Kundentext nie in der Prozessliste
    args = lauf["args"]
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--system-prompt") + 1] == "Du bist knapp."
    for schalter in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert schalter in args
    assert args[args.index("--setting-sources") + 1] == ""
    assert Path(lauf["cwd"]).name.startswith("ki-")


def test_chat_json_wird_aus_codeblock_geholt(tor, attrappe, monkeypatch):
    monkeypatch.setenv("ATTRAPPE_MODUS", "json")
    status, antwort = tor("POST", "/api/chat", _chat("x", als_json=True))
    assert status == 200
    assert json.loads(antwort["message"]["content"]) == {"a": 1, "b": ["x"]}
    system = attrappe()["args"]
    assert "ausschliesslich mit einem einzigen JSON-Objekt" in system[system.index("--system-prompt") + 1]


def test_json_ohne_objekt_bleibt_text(tor, attrappe, monkeypatch):
    monkeypatch.setenv("ATTRAPPE_MODUS", "json-ohne")
    status, antwort = tor("POST", "/api/chat", _chat("x", als_json=True))
    assert status == 200
    assert antwort["message"]["content"] == "Leider kein Objekt."


@pytest.mark.parametrize("modus", ["fehler", "kaputt"])
def test_claude_fehler_ist_502_ohne_kundentext(tor, attrappe, monkeypatch, caplog, modus):
    monkeypatch.setenv("ATTRAPPE_MODUS", modus)
    with caplog.at_level(logging.DEBUG):
        status, antwort = tor("POST", "/api/chat", _chat(GEHEIM))
    assert status == 502
    assert GEHEIM not in json.dumps(antwort)
    assert "Erika" not in caplog.text and "40000" not in caplog.text


def test_modell_aus_umgebung(tor, attrappe, monkeypatch):
    monkeypatch.setenv("KI_MODELL", "opus")
    tor("POST", "/api/chat", _chat("x"))
    args = attrappe()["args"]
    assert args[args.index("--model") + 1] == "opus"


@pytest.mark.parametrize("body", [
    b"kein json",
    json.dumps({"messages": []}).encode(),
    json.dumps({"messages": [{"role": "system", "content": "nur system"}]}).encode(),
    json.dumps({"messages": [{"role": "user", "content": "x"}], "stream": True}).encode(),
    json.dumps({"messages": [{"role": "tool", "content": "x"}]}).encode(),
])
def test_unbrauchbare_anfrage_400(tor, body):
    status, _ = tor("POST", "/api/chat", body)
    assert status == 400


def test_unbekannter_pfad_404(tor):
    assert tor("GET", "/api/ps")[0] == 404
    assert tor("POST", "/api/generate", {"x": 1})[0] == 404


def test_log_nur_metadaten(tor, attrappe, caplog):
    with caplog.at_level(logging.DEBUG):
        tor("POST", "/api/chat", _chat(GEHEIM))
    assert "POST /api/chat -> 200" in caplog.text
    assert "Erika" not in caplog.text and "Antwort zu" not in caplog.text


def test_ollama_client_spricht_mit_dem_tor(attrappe, monkeypatch):
    """Der echte sales-mcp-Client (ollama.py) funktioniert unveraendert gegen das Tor."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sales-mcp"))
    import ollama  # noqa: PLC0415
    server = ThreadingHTTPServer(("127.0.0.1", 0), ki_tor.Tor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{server.server_address[1]}")
        monkeypatch.setenv("ATTRAPPE_MODUS", "json")
        assert ollama.erreichbar() is True
        assert json.loads(ollama.chat("sys", "nutzer", als_json=True)) == {"a": 1, "b": ["x"]}
    finally:
        server.shutdown()
