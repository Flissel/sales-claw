"""Sprachnachrichten im Selbst-Chat (11.11.2026): das Gateway schreibt Audio
ueber sales-stt am PC ab - lokal, nie ueber einen Cloud-Anbieter.

Geprueft werden die CLI im Gateway (echter node-Lauf gegen einen Attrappen-
Dienst), der Konfigurationsblock (Saat == Skript) und das Anbinde-Skript
(Schluessel nie in Ausgabe oder Kommandozeile, startet nichts).
"""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
CLI = WURZEL / "deploy" / "stt" / "sprachnotiz.mjs"
BLOCK = WURZEL / "deploy" / "stt" / "media-audio.json"
SKRIPT = WURZEL / "deploy" / "stt-anbinden.sh"
SCHLUESSEL = "probe-schluessel-xyz"


def _code(pfad: Path) -> str:
    return "\n".join(z for z in pfad.read_text(encoding="utf-8").splitlines()
                     if not z.lstrip().startswith("#"))


# --- CLI im Gateway --------------------------------------------------------

class _Attrappe(BaseHTTPRequestHandler):
    antwort = (200, {"text": "Hallo Welt", "sprache": "de"})
    empfangen: dict = {}

    def do_POST(self):  # noqa: N802
        laenge = int(self.headers.get("Content-Length") or 0)
        _Attrappe.empfangen = {"pfad": self.path, "schluessel": self.headers.get("X-STT-Key"),
                               "rumpf": self.rfile.read(laenge)}
        code, nutzlast = _Attrappe.antwort
        rumpf = json.dumps(nutzlast).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def log_message(self, *_):
        pass


@pytest.fixture
def dienst():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Attrappe)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _lauf(tmp_path, url, antwort=(200, {"text": "Hallo Welt"}), audio=b"OggS" + b"\0" * 2000):
    if shutil.which("node") is None:
        pytest.skip("kein node")
    _Attrappe.antwort = antwort
    zugang = tmp_path / "zugang.json"
    zugang.write_text(json.dumps({"url": url, "schluessel": SCHLUESSEL}), encoding="utf-8")
    datei = tmp_path / "notiz.ogg"
    datei.write_bytes(audio)
    return subprocess.run(["node", str(CLI), str(datei)], capture_output=True, text=True,
                          timeout=30, env={**os.environ, "STT_ZUGANG": str(zugang)})


def test_cli_gibt_nur_den_text_aus(tmp_path, dienst):
    r = _lauf(tmp_path, dienst)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "Hallo Welt\n"
    assert _Attrappe.empfangen["pfad"] == "/transkribieren"
    assert _Attrappe.empfangen["schluessel"] == SCHLUESSEL
    assert _Attrappe.empfangen["rumpf"].startswith(b"OggS")


def test_cli_fehler_ohne_schluessel_und_ohne_inhalt(tmp_path, dienst):
    r = _lauf(tmp_path, dienst, antwort=(401, {"fehler": "Schluessel fehlt oder falsch"}))
    assert r.returncode != 0 and r.stdout == ""
    assert "401" in r.stderr
    assert SCHLUESSEL not in r.stderr and "Schluessel fehlt" not in r.stderr


def test_cli_leerer_text_ist_kein_erfolg(tmp_path, dienst):
    # Leere Abschrift (Stille, Rauschen): OpenClaw soll nicht "" als Nachricht nehmen.
    r = _lauf(tmp_path, dienst, antwort=(200, {"text": "   "}))
    assert r.returncode != 0 and r.stdout == ""


def test_cli_dienst_aus(tmp_path):
    # PC aus: Verbindungsfehler, kurze Meldung, kein Absturz mit Stapel.
    r = _lauf(tmp_path, "http://127.0.0.1:9")
    assert r.returncode != 0 and r.stdout == ""
    assert "at " not in r.stderr and len(r.stderr) < 200


def test_cli_ohne_zugang(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("kein node")
    datei = tmp_path / "notiz.ogg"
    datei.write_bytes(b"x" * 2000)
    r = subprocess.run(["node", str(CLI), str(datei)], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "STT_ZUGANG": str(tmp_path / "fehlt.json")})
    assert r.returncode != 0 and r.stdout == "" and "zugang" in r.stderr.lower()


# --- Konfigurationsblock --------------------------------------------------

def test_block_nur_lokale_cli_kein_anbieter():
    b = json.loads(BLOCK.read_text(encoding="utf-8"))
    assert b["enabled"] is True
    # Ausdruecklich eingetragene Modelle = keine Auto-Erkennung (OpenClaw nimmt
    # sonst einen Cloud-Anbieter, sobald ein Schluessel in der Umgebung liegt).
    assert len(b["models"]) == 1
    m = b["models"][0]
    assert m["type"] == "cli" and "provider" not in m
    assert m["command"] == "node"
    assert m["args"] == ["/home/node/.openclaw/stt/sprachnotiz.mjs", "{{MediaPath}}"]
    assert m["timeoutSeconds"] <= 90
    assert b.get("echoTranscript", False) is False


def test_saat_hat_denselben_block():
    saat = json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))
    assert saat["tools"]["media"]["audio"] == json.loads(BLOCK.read_text(encoding="utf-8"))
    assert saat["tools"]["web"]["fetch"]["enabled"] is False          # Nachbarn unberuehrt


# --- Anbinde-Skript --------------------------------------------------------

def test_skript_hat_gueltige_bash_syntax():
    try:
        r = subprocess.run(["bash", "-n"], input=SKRIPT.read_bytes(), capture_output=True)
    except FileNotFoundError:
        pytest.skip("kein bash")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_skript_schluessel_nur_ueber_stdin_nie_ausgegeben():
    code = _code(SKRIPT)
    assert "set -x" not in code and "set -euo pipefail" in code
    assert 'grep -E "^$1="' in code
    assert "$(wert STT_SCHLUESSEL)" in code and "$(wert STT_URL)" in code
    assert "unset SCHLUESSEL" in code
    # Nie als Argument oder -e an docker: der Zugang geht per stdin in den Container.
    assert "-e STT_" not in code and "-e \"STT_" not in code
    assert "docker exec -i" in code
    for z in code.splitlines():
        if z.lstrip().startswith("echo"):
            assert "$SCHLUESSEL" not in z and "${SCHLUESSEL" not in z, z
    assert "chmod 600" in code or "mode: 0o600" in code


def test_skript_startet_nichts_und_setzt_den_block():
    code = _code(SKRIPT)
    ausgefuehrt = "\n".join(z for z in code.splitlines() if not z.lstrip().startswith("echo"))
    assert "compose" not in ausgefuehrt and "docker restart" not in ausgefuehrt
    # Per stdin als Nutzer node (docker cp legte die Datei als root an).
    assert "docker cp" not in code and "sprachnotiz.mjs" in code
    assert "umask 077" in code
    assert "media-audio.json" in code
    assert code.count('"config", "set", "tools.media.audio"') == 1
    # Nur der Basis-Laden: Sprachnachrichten anderer Laeden gehen nicht an den PC des Betreibers.
    assert 'CONTAINER="sales-claw"' in code


def test_skript_probe_vor_fertig():
    code = _code(SKRIPT)
    assert "/gesundheit" in code
    assert code.index("/gesundheit") < code.index('echo "Fertig')


def test_runbook_abschnitt():
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    i = rb.index("## Sprache zu Text: sales-stt am PC")
    abschnitt = rb[i:rb.index("\n## ", i + 5)]
    for stichwort in ("stt-anbinden.sh", "Selbst-Chat", "tools.media.audio", "Rueckweg"):
        assert stichwort in abschnitt
