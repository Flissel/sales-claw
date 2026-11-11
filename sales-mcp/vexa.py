"""Vexa-Client: schlanker HTTP-Zugang zur selbst betriebenen Vexa-Instanz.

Vexa schickt einen Mitschrift-Bot in Jitsi-, Meet- und Teams-Gespraeche.
Hier steht nur HTTP (`urllib.request`, wie `konferenz.py`): keine Datenbank,
kein Rueckimport auf `server.py`.

GEHEIMNISSE: Der Schluessel `VEXA_API_KEY` steht nur im Header. Fehlertexte
und Logs enthalten weder ihn noch die Meeting-URL (die kann einen Passcode
tragen) noch den Antworttext, nur Methode, Pfad-Anfang und Statuscode.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("vexa")

BOT_NAME = "VibeMind Mitschrift"
SPRACHE = "de"


class VexaFehler(Exception):
    """Vexa nicht erreichbar oder lehnt ab. Die Meldung ist kurz und frei von Geheimnissen."""


class VexaNichtGefunden(VexaFehler):
    """Meeting bzw. Mitschrift ist bei Vexa unbekannt (HTTP 404 oder nicht in der Liste)."""


def _basis() -> str:
    return os.environ.get("VEXA_URL", "http://vexa-lite:8056").rstrip("/")


def _schluessel() -> str:
    # strip: ein .env mit CRLF liefert sonst "schluessel" und http.client
    # wirft ValueError MIT dem Schluessel im Text.
    return os.environ.get("VEXA_API_KEY", "").strip()


def konfiguriert() -> bool:
    return bool(_schluessel())


def _zahl(name: str, standard: int) -> int:
    try:
        return int(os.environ.get(name, "") or standard)
    except ValueError:
        return standard


def _anfrage(methode: str, pfad: str, body: dict | None = None,
             ok404: bool = False):
    schluessel = _schluessel()
    if not schluessel:
        raise VexaFehler("VEXA_API_KEY fehlt")
    kopf = {"X-API-Key": schluessel, "Accept": "application/json"}
    daten = None
    if body is not None:
        daten = json.dumps(body).encode()
        kopf["Content-Type"] = "application/json"
    # Nur der erste Pfadteil ins Log/in die Meldung (keine native_id).
    kurz = "/" + pfad.lstrip("/").split("/", 1)[0]
    try:
        req = urllib.request.Request(_basis() + pfad, data=daten, headers=kopf,
                                     method=methode)
        with urllib.request.urlopen(
                req, timeout=_zahl("VEXA_TIMEOUT_S", 20)) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as e:
        if e.code == 404 and ok404:
            return None
        log.warning("Vexa %s %s -> %s", methode, kurz, e.code)
        if e.code == 404:
            raise VexaNichtGefunden(f"Vexa kennt {kurz} nicht (404)") from None
        raise VexaFehler(f"Vexa antwortet {e.code} auf {methode} {kurz}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        log.warning("Vexa %s %s nicht erreichbar", methode, kurz)
        raise VexaFehler(f"Vexa nicht erreichbar ({methode} {kurz})") from None
    except (ValueError, http.client.HTTPException):
        # Feste Meldung: der Text dieser Ausnahmen kann Header-Werte enthalten.
        log.warning("Vexa %s %s: Anfrage/Antwort unbrauchbar", methode, kurz)
        raise VexaFehler(f"Vexa-Anfrage fehlgeschlagen ({methode} {kurz})") from None
    if not roh:
        return {}
    try:
        return json.loads(roh)
    except ValueError:
        raise VexaFehler(f"Vexa-Antwort auf {methode} {kurz} ist kein JSON") from None


def bot_schicken(meeting_url: str) -> dict:
    antwort = _anfrage("POST", "/bots", {
        "meeting_url": meeting_url,
        "bot_name": BOT_NAME,
        "language": SPRACHE,
        "recording_enabled": False,
        "automatic_leave": {
            "max_wait_for_admission": _zahl("VEXA_LOBBY_WARTEN_MS", 1800000)},
    })
    if not isinstance(antwort, dict) or "id" not in antwort:
        raise VexaFehler("Vexa-Antwort auf POST /bots ohne Meeting-Id")
    return {"meeting_id": antwort["id"],
            "plattform": antwort.get("platform", ""),
            "native_id": antwort.get("native_meeting_id", ""),
            "status": antwort.get("status", "")}


def meeting_lesen(meeting_id: int) -> dict:
    antwort = _anfrage("GET", "/meetings")
    liste = antwort.get("meetings", []) if isinstance(antwort, dict) else []
    for m in liste:
        if isinstance(m, dict) and m.get("id") == meeting_id:
            daten = m.get("data") or {}
            return {"status": m.get("status") or "",
                    "grund": daten.get("reason") or "",
                    "ende_grund": daten.get("completion_reason") or ""}
    raise VexaNichtGefunden(f"Meeting {meeting_id} bei Vexa nicht gefunden")


def segmente_holen(meeting_id: int) -> list[dict]:
    antwort = _anfrage("GET", f"/transcripts/by-id/{int(meeting_id)}")
    roh = antwort.get("segments", []) if isinstance(antwort, dict) else []
    segmente = [{"sprecher": s.get("speaker") or "",
                 "beginn": s.get("absolute_start_time") or "",
                 "text": s.get("text") or "",
                 "sprache": s.get("language") or ""} for s in roh]
    # Ohne Zeitstempel ans Ende; sort ist stabil, die Vexa-Reihenfolge bleibt.
    segmente.sort(key=lambda s: (s["beginn"] == "", s["beginn"]))
    return segmente


def bot_stoppen(plattform: str, native_id: str) -> None:
    pfad = "/bots/{}/{}".format(
        urllib.parse.quote(plattform, safe=""),
        urllib.parse.quote(native_id, safe="@."))
    _anfrage("DELETE", pfad, ok404=True)


def meeting_loeschen(meeting_id: int) -> None:
    _anfrage("DELETE", f"/meetings/{int(meeting_id)}", ok404=True)


def abbilden(vexa_status: str) -> str:
    return {"active": "laeuft", "completed": "fertig",
            "failed": "fehlgeschlagen"}.get(vexa_status, "wartet_auf_einlass")
