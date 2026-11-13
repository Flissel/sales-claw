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
if "--input-format" in args:  # Bild-Spur: stream-json
    zeile = json.loads(eingabe.strip().splitlines()[0])
    bloecke = zeile["message"]["content"]
    text = [b["text"] for b in bloecke if b["type"] == "text"][0]
    print(json.dumps({"type": "system", "subtype": "init"}))
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "zwischen"}]}}))
    if modus == "bild-fehler":
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "x"}))
        sys.exit(1)
    if modus == "bild-ohne-result":
        sys.exit(0)
    if modus == "bild-warten":
        import time
        time.sleep(30)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": "Bild: %d Bilder, Text %s" % (sum(b["type"] == "image" for b in bloecke), text[:12])}))
    sys.exit(0)
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


BILD_A = "QUFB"  # Base64-Platzhalter; das Tor reicht nur durch
BILD_B = "QkJC"


def _chat_bild(nutzer: str, bilder: list[str], *, als_json: bool = False) -> dict:
    body = _chat(nutzer, als_json=als_json)
    body["messages"][1]["images"] = bilder
    return body


def test_chat_mit_bild_nutzt_stream_json(tor, attrappe):
    status, antwort = tor("POST", "/api/chat", _chat_bild("Beschreibe das Bild", [BILD_A]))
    assert status == 200
    assert antwort["message"]["content"] == "Bild: 1 Bilder, Text Beschreibe d"
    lauf = attrappe()
    args = lauf["args"]
    assert args[:1] == ["-p"]
    assert args[args.index("--input-format") + 1] == "stream-json"
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--system-prompt") + 1] == "Du bist knapp."
    for schalter in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert schalter in args
    assert args[args.index("--setting-sources") + 1] == ""
    zeilen = lauf["stdin"].strip().splitlines()
    assert len(zeilen) == 1
    nachricht = json.loads(zeilen[0])
    assert nachricht["type"] == "user" and nachricht["message"]["role"] == "user"
    assert nachricht["message"]["content"] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": BILD_A}},
        {"type": "text", "text": "Beschreibe das Bild"},
    ]
    assert "Beschreibe das Bild" not in " ".join(args)


def test_mehrere_bilder_in_reihenfolge_vor_dem_text(tor, attrappe):
    body = {"model": "m", "stream": False, "messages": [
        {"role": "user", "content": "erst", "images": [BILD_A]},
        {"role": "user", "content": "dann", "images": [BILD_B]}]}
    status, _ = tor("POST", "/api/chat", body)
    assert status == 200
    bloecke = json.loads(attrappe()["stdin"].strip())["message"]["content"]
    assert [b["type"] for b in bloecke] == ["image", "image", "text"]
    assert [b["source"]["data"] for b in bloecke[:2]] == [BILD_A, BILD_B]
    assert bloecke[2]["text"] == "erst\n\ndann"


def test_bild_json_hinweis_und_extraktion(tor, attrappe):
    status, _ = tor("POST", "/api/chat", _chat_bild("x", [BILD_A], als_json=True))
    assert status == 200
    args = attrappe()["args"]
    assert "ausschliesslich mit einem einzigen JSON-Objekt" in args[args.index("--system-prompt") + 1]


@pytest.mark.parametrize("modus", ["bild-fehler", "bild-ohne-result"])
def test_bild_fehler_ist_502_ohne_inhalt(tor, attrappe, monkeypatch, caplog, modus):
    monkeypatch.setenv("ATTRAPPE_MODUS", modus)
    with caplog.at_level(logging.DEBUG):
        status, antwort = tor("POST", "/api/chat", _chat_bild(GEHEIM, [BILD_A]))
    assert status == 502
    assert GEHEIM not in json.dumps(antwort) and BILD_A not in json.dumps(antwort)
    assert GEHEIM not in caplog.text and BILD_A not in caplog.text


def test_bild_zeitlimit_ist_502(tor, attrappe, monkeypatch):
    monkeypatch.setenv("ATTRAPPE_MODUS", "bild-warten")
    monkeypatch.setenv("KI_BILD_TIMEOUT_S", "1")
    status, antwort = tor("POST", "/api/chat", _chat_bild("x", [BILD_A]))
    assert status == 502
    assert "Zeitlimit" in antwort["error"]


def test_bild_timeout_standard_60(monkeypatch):
    monkeypatch.delenv("KI_BILD_TIMEOUT_S", raising=False)
    assert ki_tor._bild_timeout() == 60.0
    monkeypatch.setenv("KI_BILD_TIMEOUT_S", "nan")
    assert ki_tor._bild_timeout() == 60.0


def test_bild_spur_wartet_nicht_auf_text_sperre(tor, attrappe):
    with ki_tor._sperre:  # Text-Spur belegt
        status, antwort = tor("POST", "/api/chat", _chat_bild("x", [BILD_A]))
    assert status == 200
    assert antwort["message"]["content"].startswith("Bild: 1 Bilder")


def test_text_spur_wartet_nicht_auf_bild_sperre(tor, attrappe):
    with ki_tor._sperre_bild:
        status, _ = tor("POST", "/api/chat", _chat("x"))
    assert status == 200


def test_bild_log_ohne_inhalt(tor, attrappe, caplog):
    with caplog.at_level(logging.DEBUG):
        status, _ = tor("POST", "/api/chat", _chat_bild(GEHEIM, [BILD_A]))
    assert status == 200
    assert "POST /api/chat -> 200" in caplog.text
    assert BILD_A not in caplog.text and "Erika" not in caplog.text and "Bild:" not in caplog.text


@pytest.mark.parametrize("bilder", ["QUFB", [1], [""], []])
def test_bilder_unbrauchbar_oder_leer(tor, attrappe, bilder):
    status, _ = tor("POST", "/api/chat", _chat_bild("x", bilder))
    # leere Liste = Textpfad (200); alles andere ist eine unbrauchbare Anfrage
    assert status == (200 if bilder == [] else 400)
