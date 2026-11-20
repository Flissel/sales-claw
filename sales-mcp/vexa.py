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
from datetime import datetime, timedelta, timezone

log = logging.getLogger("vexa")

_EPOCHE = datetime(1970, 1, 1, tzinfo=timezone.utc)

BOT_NAME = "VibeMind Mitschrift"
SPRACHE = "de"


class VexaFehler(Exception):
    """Vexa nicht erreichbar oder lehnt ab. Die Meldung ist kurz und frei von Geheimnissen."""


class VexaNichtGefunden(VexaFehler):
    """Meeting bzw. Mitschrift ist bei Vexa unbekannt (HTTP 404 oder nicht in der Liste)."""


class VexaNichtErreichbar(VexaFehler):
    """Keine Verbindung zu Vexa (Netz, Zeitlimit). Wird nur beim Wechsel geloggt."""


# Log-Flut vermeiden (Final-Review I9): "nicht erreichbar" steht nur beim
# Wechsel erreichbar -> weg im Log, die Rueckkehr einmal als Info.
_unerreichbar_gemeldet = False


def _erreichbar_merken(ok: bool, methode: str = "", kurz: str = "") -> None:
    global _unerreichbar_gemeldet
    if ok:
        if _unerreichbar_gemeldet:
            _unerreichbar_gemeldet = False
            log.info("Vexa wieder erreichbar")
    elif not _unerreichbar_gemeldet:
        _unerreichbar_gemeldet = True
        log.warning("Vexa %s %s nicht erreichbar (weitere Fehlversuche ohne Log)",
                    methode, kurz)


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
             ok404: bool = False, timeout_s: float | None = None):
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
                req, timeout=timeout_s or _zahl("VEXA_TIMEOUT_S", 20)) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as e:
        _erreichbar_merken(True)
        if e.code == 404 and ok404:
            return None
        log.warning("Vexa %s %s -> %s", methode, kurz, e.code)
        if e.code == 404:
            raise VexaNichtGefunden(f"Vexa kennt {kurz} nicht (404)") from None
        raise VexaFehler(f"Vexa antwortet {e.code} auf {methode} {kurz}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        _erreichbar_merken(False, methode, kurz)
        raise VexaNichtErreichbar(f"Vexa nicht erreichbar ({methode} {kurz})") from None
    except (ValueError, http.client.HTTPException):
        # Feste Meldung: der Text dieser Ausnahmen kann Header-Werte enthalten.
        log.warning("Vexa %s %s: Anfrage/Antwort unbrauchbar", methode, kurz)
        raise VexaFehler(f"Vexa-Anfrage fehlgeschlagen ({methode} {kurz})") from None
    _erreichbar_merken(True)
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
    # `ende` und `segment_id` dienen nur dem Pausenfilter und der Live-Ablage
    # (termin_pause); die gespeicherte Mitschrift behaelt das alte Schema.
    segmente = [{"sprecher": s.get("speaker") or "",
                 "beginn": s.get("absolute_start_time") or "",
                 "ende": s.get("absolute_end_time") or "",
                 "segment_id": str(s.get("segment_id") or ""),
                 "text": s.get("text") or "",
                 "sprache": s.get("language") or ""} for s in roh]
    # Ohne Zeitstempel ans Ende; sort ist stabil, die Vexa-Reihenfolge bleibt.
    segmente.sort(key=lambda s: (s["beginn"] == "", s["beginn"]))
    return segmente


def _bot_pfad(plattform: str, native_id: str) -> str:
    return "/bots/{}/{}".format(
        urllib.parse.quote(plattform, safe=""),
        urllib.parse.quote(native_id, safe="@."))


def bot_stoppen(plattform: str, native_id: str) -> None:
    _anfrage("DELETE", _bot_pfad(plattform, native_id), ok404=True)


def _pause_timeout() -> int:
    # Der schnelle Pausenweg laeuft jede Sekunde: ein haengendes Vexa darf ihn
    # nicht 20 s lang blockieren.
    return _zahl("VEXA_PAUSE_TIMEOUT_S", 5)


def pause_setzen(plattform: str, native_id: str, ab: datetime | None) -> None:
    """Aufnahme anhalten ab der Klickzeit `ab` (POST .../pause, `at_ms` als
    ganze Epoch-Millisekunden) bzw. mit `ab=None` fortsetzen (POST .../resume).
    VexaFehler bei Fehler (404: VexaNichtGefunden)."""
    pfad = _bot_pfad(plattform, native_id)
    if ab is None:
        _anfrage("POST", pfad + "/resume", timeout_s=_pause_timeout())
        return
    if ab.tzinfo is None:
        ab = ab.replace(tzinfo=timezone.utc)
    at_ms = (ab - _EPOCHE) // timedelta(milliseconds=1)
    _anfrage("POST", pfad + "/pause", {"at_ms": int(at_ms)}, timeout_s=_pause_timeout())


def pause_zustand(meeting_id: int) -> dict | None:
    """Vom Bot bestaetigter Pausenzustand `{"pausiert": bool, "seit_ms": int|None}`
    aus `data.aufnahme_pause` von GET /meetings/{id}; None, wenn (noch) keine
    gueltige Bestaetigung vorliegt. VexaFehler bei Fehler."""
    antwort = _anfrage("GET", f"/meetings/{int(meeting_id)}", timeout_s=_pause_timeout())
    daten = antwort.get("data") if isinstance(antwort, dict) else None
    p = daten.get("aufnahme_pause") if isinstance(daten, dict) else None
    if not isinstance(p, dict) or not isinstance(p.get("pausiert"), bool):
        return None
    seit = p.get("seit_ms")
    if isinstance(seit, bool) or not isinstance(seit, (int, float)):
        seit = None
    return {"pausiert": p["pausiert"], "seit_ms": int(seit) if seit is not None else None}


def bot_status(meeting_id: int) -> str:
    """Status des Meetings bei Vexa (`status` aus GET /meetings/{id}, z. B. active,
    stopping, completed, failed) - fuer die Bestaetigung der Notbremse (Final-Review
    C1), mit dem kurzen Pausen-Zeitlimit. VexaFehler bei Fehler."""
    antwort = _anfrage("GET", f"/meetings/{int(meeting_id)}", timeout_s=_pause_timeout())
    return str((antwort.get("status") if isinstance(antwort, dict) else "") or "")


def meeting_loeschen(meeting_id: int) -> None:
    _anfrage("DELETE", f"/meetings/{int(meeting_id)}", ok404=True)


def abbilden(vexa_status: str) -> str:
    return {"active": "laeuft", "completed": "fertig",
            "failed": "fehlgeschlagen"}.get(vexa_status, "wartet_auf_einlass")
