"""sales-stt — Sprachnachrichten zu Text, LOKAL (01.09.2026).

Warum lokal und nicht per API: eine Sprachnachricht ist die Stimme eines
Kunden. Sie an einen Fremddienst zu geben waere eine Auftragsverarbeitung
mehr im AVV, eine Uebermittlung mehr in den TOMs und ein Gespraech mehr
mit dem Datenschutz. Das Modell laeuft auf der VM (gemessen: 12 s Audio
in 4 s auf 4 Kernen) — die Stimme verlaesst das Haus nicht.

Schnittstelle, bewusst winzig:

    POST /transkribieren   (Rumpf: die Audiodatei, roh)
        -> {"text": "...", "sprache": "de", "dauer_s": 12.3}
    GET  /gesundheit       -> {"bereit": true, "modell": "base"}

Der Dienst hat KEINE Datenbank, KEINE Schluessel, KEINEN Zugang nach
draussen. Er bekommt Audio, gibt Text — mehr kann er nicht, und das ist
die Absicht (dieselbe T5a-Ueberlegung wie bei sales-ui).

Das Modell wird beim ERSTEN Aufruf geladen (~15 s), nicht beim Start:
so ist der Container sofort gesund, und wer nie transkribiert, zahlt
keinen Speicher.
"""
import json
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = logging.getLogger("sales-stt")

PORT = int(os.environ.get("STT_PORT", "2790"))
MODELL = os.environ.get("STT_MODELL", "base")
SPRACHE = os.environ.get("STT_SPRACHE", "de")
# 25 MB: eine WhatsApp-Sprachnachricht ist typisch 10-60 kB je Minute.
# Der Deckel schuetzt vor einem Rumpf, den der Absender bestimmt.
MAX_BYTES = int(os.environ.get("STT_MAX_BYTES", str(25 * 1024 * 1024)))

_MODELL = None
_SPERRE = threading.Lock()


def modell():
    """Lazy und genau einmal — das Laden kostet ~15 s und 300 MB."""
    global _MODELL
    if _MODELL is None:
        with _SPERRE:
            if _MODELL is None:
                from faster_whisper import WhisperModel
                beginn = time.monotonic()
                _MODELL = WhisperModel(MODELL, device="cpu",
                                       compute_type="int8")
                LOG.info("Modell '%s' geladen (%.1f s)", MODELL,
                         time.monotonic() - beginn)
    return _MODELL


def transkribieren(audio: bytes) -> dict:
    """Audio -> {text, sprache, dauer_s}. Wirft bei kaputtem Audio."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as datei:
        datei.write(audio)
        pfad = datei.name
    try:
        beginn = time.monotonic()
        segmente, info = modell().transcribe(
            pfad, language=SPRACHE or None, vad_filter=True)
        text = " ".join(s.text.strip() for s in segmente).strip()
        return {"text": text,
                "sprache": getattr(info, "language", SPRACHE),
                "dauer_s": round(getattr(info, "duration", 0.0), 1),
                "gerechnet_s": round(time.monotonic() - beginn, 1)}
    finally:
        try:
            os.unlink(pfad)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _antwort(self, code: int, nutzlast: dict):
        rumpf = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def do_GET(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        if self.path == "/gesundheit":
            # Absichtlich OHNE Modell-Ladung: der Container ist gesund,
            # sobald er antwortet — das Laden passiert beim ersten Auftrag.
            self._antwort(200, {"bereit": True, "modell": MODELL,
                                "geladen": _MODELL is not None})
            return
        self._antwort(404, {"fehler": "unbekannter Pfad"})

    def do_POST(self):  # noqa: N802
        if self.path != "/transkribieren":
            self._antwort(404, {"fehler": "unbekannter Pfad"})
            return
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            laenge = 0
        if laenge <= 0:
            self._antwort(400, {"fehler": "leerer Rumpf"})
            return
        if laenge > MAX_BYTES:
            self._antwort(413, {"fehler": f"Audio groesser als {MAX_BYTES} "
                                          f"Bytes — nicht verarbeitet."})
            return
        audio = self.rfile.read(laenge)
        try:
            self._antwort(200, transkribieren(audio))
        except Exception as e:  # noqa: BLE001 — kaputtes Audio, kein Absturz
            LOG.warning("Transkription gescheitert: %s", type(e).__name__)
            self._antwort(422, {"fehler": (
                f"Audio nicht verarbeitbar ({type(e).__name__}).")})

    def log_message(self, *_):
        pass        # kein Zugriffslog: Pfade ohne Erkenntniswert


class Dienst(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dienst = Dienst(("0.0.0.0", PORT), Handler)
    signal.signal(signal.SIGTERM, lambda *_: dienst.shutdown())
    signal.signal(signal.SIGINT, lambda *_: dienst.shutdown())
    LOG.info("Start: Port %d, Modell '%s' (wird beim ersten Auftrag "
             "geladen), Sprache '%s'", PORT, MODELL, SPRACHE)
    dienst.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
