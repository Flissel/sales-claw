"""Telegram-Hinweis an den Betreiber (Felix): kurze Notiz, nur Senden.

Nur HTTP (`urllib.request`, wie `vexa.py`/`ollama.py`): keine Datenbank,
kein Import von `server.py`.

GEHEIMNISSE: Der Bot-Token steckt im URL-Pfad. `HTTPError`/`URLError`
tragen diese URL, deshalb wird nie ein Ausnahmeobjekt geloggt oder in
Text verwandelt; geloggt wird nur `HTTP <code>` bzw. der Typname. Weder
Text, Token noch Chat-ID erscheinen je in einem Log.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("betreiber_hinweis")

# Telegram antwortet normalerweise in unter einer Sekunde; 10 s halten den
# Aufrufer (Termin-/Mitschrift-Ablauf) nicht lange auf.
TIMEOUT_S = 10

# Log-Flut vermeiden (Final-Review I9): dieselbe Fehlermeldung steht nur
# einmal im Log, bis ein Senden gelingt oder ein anderer Fehler kommt. Die
# Meldungen sind feste Texte (nie Token, Chat-ID oder Text).
_letzter_fehler: str | None = None


def _fehler(meldung: str) -> bool:
    global _letzter_fehler
    if meldung != _letzter_fehler:
        _letzter_fehler = meldung
        log.warning("%s", meldung)
    return False


def _ok() -> bool:
    global _letzter_fehler
    if _letzter_fehler is not None:
        _letzter_fehler = None
        log.info("Telegram-Hinweis: Senden klappt wieder")
    return True


def senden(text: str, *, link_vorschau: bool = False) -> bool:
    """Schickt `text` an den Betreiber. Wahr nur bei HTTP 200 und `ok`.

    Wirft nie: jeder Fehler ergibt False.
    """
    try:
        # strip: ein .env mit CRLF haengt sonst "\r" an Token/Chat-ID.
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return _fehler("Telegram nicht konfiguriert")
        basis = (os.environ.get("TELEGRAM_API_BASIS", "").strip()
                 or "https://api.telegram.org").rstrip("/")
        daten = urllib.parse.urlencode({
            "chat_id": chat,
            "text": text,
            "disable_web_page_preview": "false" if link_vorschau else "true",
        }).encode()
        try:
            req = urllib.request.Request(
                f"{basis}/bot{token}/sendMessage", data=daten, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as antwort:
                status = antwort.status
                roh = antwort.read()
        except urllib.error.HTTPError as e:
            return _fehler(f"Telegram-Hinweis: HTTP {int(e.code)}")
        except (urllib.error.URLError, OSError, TimeoutError):
            return _fehler("Telegram-Hinweis: nicht erreichbar")
        except (ValueError, http.client.HTTPException):
            return _fehler("Telegram-Hinweis: Anfrage/Antwort unbrauchbar")
        if status != 200:
            return _fehler(f"Telegram-Hinweis: HTTP {int(status)}")
        try:
            antwort_json = json.loads(roh)
        except ValueError:
            return _fehler("Telegram-Hinweis: Antwort ist kein JSON")
        if not isinstance(antwort_json, dict) or antwort_json.get("ok") is not True:
            return _fehler("Telegram-Hinweis: Telegram meldet ok=false")
        return _ok()
    except Exception as e:  # noqa: BLE001 - senden() darf nie werfen
        # Nur der Typname: Text und URL der Ausnahme koennen den Token tragen.
        return _fehler(f"Telegram-Hinweis: unerwarteter Fehler ({type(e).__name__})")
