"""KI-Tor (12.11.2026): Claude Code hinter einer Ollama-kompatiblen Schnittstelle.

Uebergangsloesung des Betreibers ("erst mit Claude Code bauen, dann umsteigen,
wenn wir Server haben"): Briefing und Mitschrift-Auswertung (sales-mcp/ollama.py)
sprechen weiter nur mit `OLLAMA_URL`. Zeigt die auf diesen Dienst, beantwortet
Claude Code die Anfragen ueber das Abo des Betreibers (CLAUDE_CODE_OAUTH_TOKEN),
ohne API-Budget. Zurueck zum lokalen Ollama: nur `OLLAMA_URL` umstellen.

Schnittstelle (nur, was sales-mcp/ollama.py braucht):
  GET  /api/tags  -> {"models": [{"name": KI_MODELL}]}
  POST /api/chat  -> {"model", "message": {"role": "assistant", "content"}, "done": true}
                     Eingang: {"model", "messages": [...], "format"?: "json", "options"?}

Claude Code laeuft je Anfrage als `claude -p` ohne Werkzeuge, ohne MCP, ohne
Einstellungsdateien und ohne Sitzungsspeicher in einem leeren Arbeitsordner.
Der Nutzertext geht ueber stdin (nie in die Prozessliste).

Bild-Spur: Traegt eine Nutzer-Nachricht `images` (Base64-JPEG, Ollama-Format),
laeuft `claude -p` im stream-json-Modus (eine Nutzer-Zeile mit image-Bloecken
und Text auf stdin) mit eigener Sperre und eigenem Zeitlimit, damit ein Bild
das Briefing und die Mitschrift-Auswertung nicht aufhaelt.

KUNDENTEXT: Prompts und Antworten werden nie geloggt und stehen nie in
Fehlerantworten - nur Pfad, Statuscode, Dauer und Fehlerart.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("sales-ki")

PORT_STANDARD = 11434
MODELL_STANDARD = "sonnet"
TIMEOUT_STANDARD_S = 280.0
BILD_TIMEOUT_STANDARD_S = 60.0
MAX_EINGANG = 2 * 1024 * 1024  # 2 MB: eine Mitschrift-Stueckelung bleibt weit darunter

JSON_HINWEIS = (
    "\n\nAntworte ausschliesslich mit einem einzigen JSON-Objekt. "
    "Kein Markdown, kein Codeblock, kein Text davor oder danach."
)

# Claude Code nimmt je Abo nur begrenzt viele Anfragen gleichzeitig an; der
# Taktgeber ruft ohnehin nacheinander. Eine Sperre haelt das so.
_sperre = threading.Lock()
# Eigene Sperre fuer die Bild-Spur: Text- und Bildanfragen blockieren sich nicht.
_sperre_bild = threading.Lock()


class KiFehler(Exception):
    """Claude Code lieferte keine brauchbare Antwort."""


def _modell() -> str:
    return os.environ.get("KI_MODELL", "").strip() or MODELL_STANDARD


def _timeout() -> float:
    try:
        wert = float(os.environ.get("KI_TIMEOUT_S", "") or TIMEOUT_STANDARD_S)
    except ValueError:
        return TIMEOUT_STANDARD_S
    return wert if 0 < wert < float("inf") else TIMEOUT_STANDARD_S


def _bild_timeout() -> float:
    try:
        wert = float(os.environ.get("KI_BILD_TIMEOUT_S", "") or BILD_TIMEOUT_STANDARD_S)
    except ValueError:
        return BILD_TIMEOUT_STANDARD_S
    return wert if 0 < wert < float("inf") else BILD_TIMEOUT_STANDARD_S


def _befehl() -> list[str]:
    """`KI_CLAUDE_BEFEHL` nur fuer Tests (Attrappe); sonst `claude`."""
    roh = os.environ.get("KI_CLAUDE_BEFEHL", "").strip()
    return shlex.split(roh) if roh else ["claude"]


def _bilder_aus(n: dict) -> list[str]:
    """Die `images` einer Nachricht (Liste nichtleerer Base64-Strings) oder []."""
    roh = n.get("images")
    if roh is None:
        return []
    if not isinstance(roh, list) or not all(isinstance(b, str) and b for b in roh):
        raise KiFehler("Bilder unbrauchbar")
    return roh


def _teile(nachrichten: list) -> tuple[str, str, list[str]]:
    """System- und Nutzertext sowie Bilder (in Reihenfolge) aus den
    Ollama-Nachrichten (Assistent-Nachrichten kommen bei sales-mcp nicht vor
    und werden als Verlauf mitgegeben)."""
    system, nutzer, bilder = [], [], []
    for n in nachrichten:
        if not isinstance(n, dict) or not isinstance(n.get("content"), str):
            raise KiFehler("Nachricht unbrauchbar")
        rolle = n.get("role")
        if rolle == "system":
            system.append(n["content"])
        elif rolle == "user":
            nutzer.append(n["content"])
            bilder += _bilder_aus(n)
        elif rolle == "assistant":
            nutzer.append("[Vorherige Antwort]\n" + n["content"])
        else:
            raise KiFehler("Rolle unbekannt")
    if not nutzer:
        raise KiFehler("Kein Nutzertext")
    return "\n\n".join(system), "\n\n".join(nutzer), bilder


def _json_aus(text: str) -> str:
    """Das erste vollstaendige JSON-Objekt aus der Antwort (Codeblock-Zaeune und
    Vorrede entfernt). Kein Objekt -> Antwort unveraendert (der Aufrufer
    erkennt kaputtes JSON selbst und versucht es einmal neu)."""
    ohne_zaun = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start = ohne_zaun.find("{")
    if start < 0:
        return text
    try:
        objekt, _ende = json.JSONDecoder().raw_decode(ohne_zaun[start:])
    except ValueError:
        return text
    return json.dumps(objekt, ensure_ascii=False)


_SPERR_FLAGS = [
    "--tools", "",
    "--strict-mcp-config",
    "--setting-sources", "",
    "--disable-slash-commands",
    "--no-session-persistence",
]


def claude_fragen(system: str, nutzer: str, *, als_json: bool) -> str:
    """Ein `claude -p`-Lauf; gibt den Antworttext zurueck oder wirft KiFehler."""
    if als_json:
        system = (system + JSON_HINWEIS) if system else JSON_HINWEIS.strip()
    befehl = _befehl() + [
        "-p", "--output-format", "json",
        "--model", _modell(),
        *_SPERR_FLAGS,
    ]
    if system:
        befehl += ["--system-prompt", system]
    with tempfile.TemporaryDirectory(prefix="ki-") as leer:
        try:
            lauf = subprocess.run(befehl, input=nutzer, capture_output=True,
                                  text=True, encoding="utf-8", cwd=leer,
                                  timeout=_timeout())
        except subprocess.TimeoutExpired:
            raise KiFehler("Zeitlimit") from None
        except OSError:
            raise KiFehler("claude nicht startbar") from None
    try:
        ergebnis = json.loads(lauf.stdout)
    except ValueError:
        raise KiFehler(f"Ausgabe unbrauchbar (Exit {lauf.returncode})") from None
    if not isinstance(ergebnis, dict) or ergebnis.get("is_error") \
            or not isinstance(ergebnis.get("result"), str):
        art = ergebnis.get("subtype") if isinstance(ergebnis, dict) else None
        raise KiFehler(f"claude meldet Fehler ({art or 'unbekannt'}, Exit {lauf.returncode})")
    text = ergebnis["result"]
    return _json_aus(text) if als_json else text


def claude_bild_fragen(system: str, nutzer: str, bilder: list[str], *, als_json: bool) -> str:
    """Bild-Spur: ein `claude -p`-Lauf im stream-json-Modus. Die Bilder (Base64,
    JPEG) stehen vor dem Text in einer einzigen Nutzer-Zeile auf stdin; die
    Antwort ist das `result` der letzten result-Zeile. Wirft KiFehler."""
    if als_json:
        system = (system + JSON_HINWEIS) if system else JSON_HINWEIS.strip()
    befehl = _befehl() + [
        "-p", "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose",
        "--model", _modell(),
        *_SPERR_FLAGS,
    ]
    if system:
        befehl += ["--system-prompt", system]
    bloecke: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
        for b in bilder]
    bloecke.append({"type": "text", "text": nutzer})
    zeile = json.dumps({"type": "user", "message": {"role": "user", "content": bloecke}},
                       ensure_ascii=False) + "\n"
    with tempfile.TemporaryDirectory(prefix="ki-") as leer:
        try:
            lauf = subprocess.run(befehl, input=zeile, capture_output=True,
                                  text=True, encoding="utf-8", cwd=leer,
                                  timeout=_bild_timeout())
        except subprocess.TimeoutExpired:
            raise KiFehler("Zeitlimit") from None
        except OSError:
            raise KiFehler("claude nicht startbar") from None
    ergebnis = None
    for rohzeile in lauf.stdout.splitlines():
        try:
            objekt = json.loads(rohzeile)
        except ValueError:
            continue
        if isinstance(objekt, dict) and objekt.get("type") == "result":
            ergebnis = objekt
    if ergebnis is None:
        raise KiFehler(f"Ausgabe unbrauchbar (Exit {lauf.returncode})")
    if ergebnis.get("is_error") or not isinstance(ergebnis.get("result"), str):
        raise KiFehler(f"claude meldet Fehler ({ergebnis.get('subtype') or 'unbekannt'}, "
                       f"Exit {lauf.returncode})")
    text = ergebnis["result"]
    return _json_aus(text) if als_json else text


class Tor(BaseHTTPRequestHandler):
    server_version = "sales-ki"

    def log_message(self, format, *args):  # noqa: A002 - Signatur der Basisklasse
        pass  # eigenes Log ohne Inhalte, siehe _antwort

    def _antwort(self, code: int, nutzlast: dict, beginn: float | None = None,
                 art: str = "") -> None:
        roh = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)
        if beginn is not None:
            log.info("%s %s -> %s in %.1f s%s", self.command, self.path, code,
                     time.monotonic() - beginn, f" ({art})" if art else "")

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/tags":
            self._antwort(200, {"models": [{"name": _modell(), "model": _modell()}]})
        else:
            self._antwort(404, {"error": "unbekannter Pfad"})

    def do_POST(self):  # noqa: N802
        beginn = time.monotonic()
        if self.path.split("?")[0] != "/api/chat":
            self._antwort(404, {"error": "unbekannter Pfad"}, beginn)
            return
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            laenge = -1
        if not 0 < laenge <= MAX_EINGANG:
            self._antwort(400, {"error": "Laenge unzulaessig"}, beginn)
            return
        try:
            anfrage = json.loads(self.rfile.read(laenge))
            if anfrage.get("stream"):
                raise KiFehler("stream wird nicht unterstuetzt")
            system, nutzer, bilder = _teile(anfrage.get("messages") or [])
            als_json = anfrage.get("format") == "json"
        except (ValueError, AttributeError, KiFehler) as e:
            self._antwort(400, {"error": "Anfrage unbrauchbar"}, beginn, type(e).__name__)
            return
        try:
            if bilder:
                with _sperre_bild:
                    inhalt = claude_bild_fragen(system, nutzer, bilder, als_json=als_json)
            else:
                with _sperre:
                    inhalt = claude_fragen(system, nutzer, als_json=als_json)
        except KiFehler as e:
            # Die Meldung traegt nur Art und Exit-Code, nie Kundentext.
            self._antwort(502, {"error": str(e)}, beginn, "KiFehler")
            return
        self._antwort(200, {"model": anfrage.get("model") or _modell(),
                            "message": {"role": "assistant", "content": inhalt},
                            "done": True}, beginn)


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        log.warning("CLAUDE_CODE_OAUTH_TOKEN fehlt - Anfragen werden scheitern")
    port = int(os.environ.get("KI_PORT", "") or PORT_STANDARD)
    server = ThreadingHTTPServer(("0.0.0.0", port), Tor)
    log.info("sales-ki lauscht auf :%s (Modell %s)", port, _modell())
    server.serve_forever()


if __name__ == "__main__":
    main()
