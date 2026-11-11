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
NUM_CTX_STANDARD = 8192
BRIEFING_TIMEOUT_STANDARD_S = 60.0


class OllamaFehler(Exception):
    """Ollama nicht konfiguriert, nicht erreichbar oder Antwort unbrauchbar."""


def _basis() -> str:
    return os.environ.get("OLLAMA_URL", "").strip().rstrip("/")


def _modell() -> str:
    return os.environ.get("OLLAMA_MODELL", "").strip() or MODELL_STANDARD


def _sekunden(name: str, standard: float) -> float:
    try:
        wert = float(os.environ.get(name, "") or standard)
    except ValueError:
        return standard
    # nan, inf und <= 0 sind unbrauchbar
    return wert if 0 < wert < float("inf") else standard


def _timeout() -> float:
    return _sekunden("OLLAMA_TIMEOUT_S", 300.0)


def briefing_timeout() -> float:
    """Kurzes Zeitlimit fuer den Briefing-Kurztext (`OLLAMA_BRIEFING_TIMEOUT_S`,
    Vorgabe 60 s): das Briefing haelt den Takt sonst bis zu 300 s auf."""
    return _sekunden("OLLAMA_BRIEFING_TIMEOUT_S", BRIEFING_TIMEOUT_STANDARD_S)


def _num_ctx() -> int:
    """Kontextfenster (`OLLAMA_NUM_CTX`, Vorgabe 8192). Ollamas eigene Vorgabe
    ist kleiner und schneidet lange Mitschrift-Stuecke still ab."""
    try:
        wert = int(os.environ.get("OLLAMA_NUM_CTX", "") or NUM_CTX_STANDARD)
    except ValueError:
        return NUM_CTX_STANDARD
    return wert if wert > 0 else NUM_CTX_STANDARD


def _anfrage(methode: str, pfad: str, body: dict | None, timeout: float,
             leise: bool = False) -> bytes:
    """`leise`: Fehler nur auf DEBUG (Erreichbarkeits-Probe, Final-Review I9) -
    den Wechsel meldet der Aufrufer einmal."""
    melden = log.debug if leise else log.warning
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
        melden("Ollama %s %s -> %s", methode, pfad, e.code)
        raise OllamaFehler(f"Ollama antwortet {e.code} auf {methode} {pfad}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        melden("Ollama %s %s nicht erreichbar", methode, pfad)
        raise OllamaFehler(f"Ollama nicht erreichbar ({methode} {pfad})") from None
    except (ValueError, http.client.HTTPException):
        melden("Ollama %s %s: Anfrage/Antwort unbrauchbar", methode, pfad)
        raise OllamaFehler(f"Ollama-Anfrage fehlgeschlagen ({methode} {pfad})") from None


def erreichbar() -> bool:
    """GET /api/tags mit 3 s Zeitlimit. Wirft nie und loggt nicht (der
    Taktgeber meldet nur den Wechsel)."""
    try:
        _anfrage("GET", "/api/tags", None, ERREICHBAR_TIMEOUT_S, leise=True)
        return True
    except Exception:  # noqa: BLE001 - Vertrag: nie eine Ausnahme
        return False


def chat(system: str, nutzer: str, *, als_json: bool = False,
         timeout_s: float | None = None) -> str:
    """POST /api/chat; gibt `message.content` zurueck. `timeout_s` ersetzt
    `OLLAMA_TIMEOUT_S` fuer diesen Aufruf (Briefing: `briefing_timeout()`)."""
    body: dict = {
        "model": _modell(),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": nutzer}],
        "stream": False,
        "options": {"temperature": TEMPERATUR, "num_ctx": _num_ctx()},
    }
    if als_json:
        body["format"] = "json"
    roh = _anfrage("POST", "/api/chat", body,
                   timeout_s if timeout_s is not None else _timeout())
    try:
        inhalt = json.loads(roh)["message"]["content"]
    except (ValueError, KeyError, TypeError):
        raise OllamaFehler("Ollama-Antwort auf POST /api/chat ist unbrauchbar") from None
    if not isinstance(inhalt, str):
        raise OllamaFehler("Ollama-Antwort auf POST /api/chat ist unbrauchbar")
    return inhalt
