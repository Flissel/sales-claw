"""Ollama-Client: einziger KI-Zugang fuer Briefing und Auswertung (Meeting-Mittelpunkt).

Kundentext geht ausschliesslich an `OLLAMA_URL` (Ollama auf dem PC des
Betreibers, ueber Tailscale erreichbar). Dieses Modul importiert weder
`gateway` noch einen anderen KI-Client; nur `urllib.request` (wie `vexa.py`).

KUNDENTEXT: Prompts und Antworten werden nie geloggt und stehen nie in
Fehlertexten, nur Methode, Pfad und Statuscode.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("ollama")

MODELL_STANDARD = "qwen2.5:7b"
TEMPERATUR = 0.2
ERREICHBAR_TIMEOUT_S = 3


class OllamaFehler(Exception):
    """Ollama nicht konfiguriert, nicht erreichbar oder Antwort unbrauchbar."""


def _basis() -> str:
    return os.environ.get("OLLAMA_URL", "").strip().rstrip("/")


def _modell() -> str:
    return os.environ.get("OLLAMA_MODELL", "").strip() or MODELL_STANDARD


def _timeout() -> float:
    try:
        wert = float(os.environ.get("OLLAMA_TIMEOUT_S", "") or 300)
    except ValueError:
        return 300.0
    # nan, inf und <= 0 sind unbrauchbar
    return wert if 0 < wert < float("inf") else 300.0


def _anfrage(methode: str, pfad: str, body: dict | None, timeout: float) -> bytes:
    basis = _basis()
    if not basis:
        raise OllamaFehler("OLLAMA_URL nicht konfiguriert")
    try:
        daten = None
        kopf = {"Accept": "application/json"}
        if body is not None:
            daten = json.dumps(body).encode()
            kopf["Content-Type"] = "application/json"
        req = urllib.request.Request(basis + pfad, data=daten, headers=kopf,
                                     method=methode)
        with urllib.request.urlopen(req, timeout=timeout) as antwort:
            return antwort.read()
    except urllib.error.HTTPError as e:
        log.warning("Ollama %s %s -> %s", methode, pfad, e.code)
        raise OllamaFehler(f"Ollama antwortet {e.code} auf {methode} {pfad}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        log.warning("Ollama %s %s nicht erreichbar", methode, pfad)
        raise OllamaFehler(f"Ollama nicht erreichbar ({methode} {pfad})") from None
    except (ValueError, http.client.HTTPException):
        log.warning("Ollama %s %s: Anfrage/Antwort unbrauchbar", methode, pfad)
        raise OllamaFehler(f"Ollama-Anfrage fehlgeschlagen ({methode} {pfad})") from None


def erreichbar() -> bool:
    """GET /api/tags mit 3 s Zeitlimit. Wirft nie."""
    try:
        _anfrage("GET", "/api/tags", None, ERREICHBAR_TIMEOUT_S)
        return True
    except Exception:  # noqa: BLE001 - Vertrag: nie eine Ausnahme
        return False


def chat(system: str, nutzer: str, *, als_json: bool = False) -> str:
    """POST /api/chat; gibt `message.content` zurueck."""
    body: dict = {
        "model": _modell(),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": nutzer}],
        "stream": False,
        "options": {"temperature": TEMPERATUR},
    }
    if als_json:
        body["format"] = "json"
    roh = _anfrage("POST", "/api/chat", body, _timeout())
    try:
        inhalt = json.loads(roh)["message"]["content"]
    except (ValueError, KeyError, TypeError):
        raise OllamaFehler("Ollama-Antwort auf POST /api/chat ist unbrauchbar") from None
    if not isinstance(inhalt, str):
        raise OllamaFehler("Ollama-Antwort auf POST /api/chat ist unbrauchbar")
    return inhalt
