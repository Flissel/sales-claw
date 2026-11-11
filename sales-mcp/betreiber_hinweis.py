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


def senden(text: str, *, link_vorschau: bool = False) -> bool:
    """Schickt `text` an den Betreiber. Wahr nur bei HTTP 200 und `ok`.

    Wirft nie: jeder Fehler ergibt False.
    """
    try:
        # strip: ein .env mit CRLF haengt sonst "\r" an Token/Chat-ID.
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            log.warning("Telegram nicht konfiguriert")
            return False
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
            log.warning("Telegram-Hinweis: HTTP %s", e.code)
            return False
        except (urllib.error.URLError, OSError, TimeoutError):
            log.warning("Telegram-Hinweis: nicht erreichbar")
            return False
        except (ValueError, http.client.HTTPException):
            log.warning("Telegram-Hinweis: Anfrage/Antwort unbrauchbar")
            return False
        if status != 200:
            log.warning("Telegram-Hinweis: HTTP %s", status)
            return False
        try:
            antwort_json = json.loads(roh)
        except ValueError:
            log.warning("Telegram-Hinweis: Antwort ist kein JSON")
            return False
        if not isinstance(antwort_json, dict) or antwort_json.get("ok") is not True:
            log.warning("Telegram-Hinweis: Telegram meldet ok=false")
            return False
        return True
    except Exception as e:  # noqa: BLE001 - senden() darf nie werfen
        # Nur der Typname: Text und URL der Ausnahme koennen den Token tragen.
        log.warning("Telegram-Hinweis: unerwarteter Fehler (%s)", type(e).__name__)
        return False
