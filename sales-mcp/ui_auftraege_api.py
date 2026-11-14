"""Annahme `POST /api/auftraege/video`: Rowboat bereitet die Uebergabe eines Videokonzepts an die Video-Werkbank vor.

Eigener Bearer-Schluessel (Herkunft `rowboat`, s. freigabe_eingang), keine Sitzung, kein CSRF; die
Anmelde-Wache in ui.py laesst genau diesen Pfad durch. Die Annahme legt KEINEN Auftrag an, sondern eine
vorbereitete Uebergabe (video_uebergabe.py). Das verbindliche Ja gibt der Betreiber auf der Werkbank-Seite
unter seinem Login; erst dann entsteht der Auftrag (mit Tagesgrenze). Der Rowboat-Schluessel kann diese
Aktionen nicht ausloesen: sie haengen an der Sitzung und an der CSRF-Marke der Seite.

Antworten: 200 {status: "vorbereitet", vorgang: <8 Hex>, link}; Fehler {fehler: "<Satz>"} mit 400 (Pruefung),
401 (Schluessel), 409 (schon vorbereitet), 413 (Rumpf), 429 (5 Uebergaben offen), 503 (Tabelle fehlt). Weder Schluessel noch Rumpf
gelangen ins Log.
"""
from __future__ import annotations

import json
import logging
import os

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import ui_freigabe_api
import ui_werkbank
import video_konzept
import video_uebergabe

PFAD = "/api/auftraege/video"
HERKUNFT = "rowboat"
MAX_RUMPF = 64 * 1024
LOG = logging.getLogger("sales-ui")


def _fehler(status: int, satz: str) -> JSONResponse:
    return JSONResponse({"fehler": satz}, status_code=status)


def _keine_konstante(name: str):
    raise ValueError(f"{name} ist kein JSON")          # NaN, Infinity, -Infinity


async def _rumpf(request: Request):
    """-> (dict | None, Fehlerantwort | None); liest hoechstens MAX_RUMPF Byte."""
    zu_gross = _fehler(413, "Der Rumpf ist größer als 64 KiB.")
    laenge = request.headers.get("content-length", "")
    if laenge.isdigit() and int(laenge) > MAX_RUMPF:
        return None, zu_gross
    puffer = bytearray()
    async for stueck in request.stream():
        puffer += stueck
        if len(puffer) > MAX_RUMPF:
            return None, zu_gross
    try:
        daten = json.loads(bytes(puffer).decode("utf-8"), parse_constant=_keine_konstante)
    except (ValueError, UnicodeDecodeError, RecursionError):      # RecursionError: sehr tief verschachtelt
        return None, _fehler(400, "Der Rumpf ist kein gültiges JSON.")
    if not isinstance(daten, dict):
        return None, _fehler(400, "Der Rumpf muss ein JSON-Objekt sein.")
    try:
        json.dumps(daten, ensure_ascii=False).encode("utf-8")      # einzelne Surrogate lassen sich nicht kodieren
    except (UnicodeEncodeError, RecursionError):
        return None, _fehler(400, "Der Rumpf enthält ungültige Zeichen.")
    return daten, None


def routen(ui) -> list[Route]:
    async def video(request: Request):
        herkunft = await run_in_threadpool(ui_freigabe_api._herkunft, request)
        if herkunft != HERKUNFT:
            return _fehler(401, "Nicht berechtigt.")
        daten, fehler = await _rumpf(request)
        if fehler:
            return fehler
        server = ui.server
        if server.SCHEMA not in server._AUFTRAG_SCHEMAS:
            return _fehler(400, "Aufträge gibt es in diesem Laden noch nicht.")
        thema, beschreibung = daten.get("thema"), daten.get("beschreibung")
        zielgruppe, konzept = daten.get("zielgruppe"), daten.get("konzept")
        if (not isinstance(thema, str) or not all(w is None or isinstance(w, str)
                                                  for w in (beschreibung, zielgruppe))):
            return _fehler(400, "Thema, Beschreibung und Zielgruppe müssen Text sein.")
        satz = server.video_auftrag_pruefen(thema, daten.get("minuten"), zielgruppe, beschreibung) \
            or video_konzept.pruefen(konzept)
        if satz:
            return _fehler(400, satz)
        # Die Angaben oben muessen genau die des Konzepts sein, das der Betreiber gleich sieht.
        if (thema.strip() != konzept["thema"].strip() or daten["minuten"] != konzept["minuten"]
                or (zielgruppe or "").strip() != konzept["zielgruppe"].strip()
                or (beschreibung or "") != video_konzept.beschreibung_aus(konzept)):
            return _fehler(400, "Die Angaben passen nicht zum Konzept.")
        mandant = os.environ.get("MARKETING_MANDANT", "").strip()
        if not mandant:
            return _fehler(400, video_uebergabe.SATZ_KEINE_FIRMA)
        firma = konzept.get("firma")
        if isinstance(firma, str) and firma.strip() and firma.strip() != mandant:
            return _fehler(400, video_uebergabe.SATZ_FIRMA)
        konzept = video_konzept.bereinigen(konzept)           # nur bekannte Felder werden gespeichert
        sha = video_konzept.block_hash(konzept)
        try:
            vorgang, satz = await run_in_threadpool(video_uebergabe.anlegen, konzept, sha)
        except video_uebergabe.NICHT_EINGERICHTET as f:      # Tabelle oder Recht fehlt: Ausfall, keine Ablehnung
            LOG.error("Uebergabe nicht eingerichtet: %s", type(f).__name__)
            return _fehler(503, video_uebergabe.SATZ_NICHT_EINGERICHTET)
        if satz:
            return _fehler(409 if satz == video_uebergabe.SATZ_DOPPELT else 429, satz)
        basis = ui.UI_BASIS_URL.rstrip("/")
        return JSONResponse({"status": "vorbereitet", "vorgang": vorgang,
                             "link": f"{basis}{ui_werkbank.BASIS}#uebergaben"})

    return [Route(PFAD, video, methods=["POST"])]
