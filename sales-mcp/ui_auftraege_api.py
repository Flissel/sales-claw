"""Annahme `POST /api/auftraege/video`: Rowboat gibt ein fertiges Videokonzept an die Video-Werkbank.

Eigener Bearer-Schluessel (Herkunft `rowboat`, s. freigabe_eingang), keine Sitzung, kein CSRF; die
Anmelde-Wache in ui.py laesst genau diesen Pfad durch. Sales sieht nur, DASS der Rowboat-Schluessel
benutzt wurde, nicht, wer im Chat zugestimmt hat - das Ja setzt Rowboats Freigabeschicht durch.

Die Zeile im Auftragsbuch bleibt `von='sales'` (die Tagesgrenze zaehlt Rowboat und Salesman zusammen);
die Herkunft steht in `eingabe.von = "rowboat"`. Antworten: 200 {auftrag, id, link}; Fehler
{fehler: "<Satz>"} mit 400 (Pruefung), 401 (Schluessel), 409 (Doppelte Uebergabe), 413 (Rumpf), 429 (Tagesgrenze).
Weder Schluessel noch Rumpf gelangen ins Log.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import auftrag_buch
import ui_freigabe_api
import ui_werkbank
import video_konzept

PFAD = "/api/auftraege/video"
HERKUNFT = "rowboat"
MAX_RUMPF = 64 * 1024
DOPPELT_FENSTER = timedelta(minutes=10)
# Staende, in denen ein Auftrag noch "lebt": ein abgebrochener oder fehlgeschlagener darf neu uebergeben werden.
LEBENDE_STAENDE = ["offen", "in_arbeit", "erzeugt", "wartet_freigabe", "fertig", "werkbank"]
LOG = logging.getLogger("sales-ui")

# Pruefen und Anlegen bilden zusammen einen Schritt: zwei gleichzeitige Aufrufe (zwei Werkzeugaufrufe in einer
# Modellantwort, Wiederholen nach Zeitueberschreitung) sollen hoechstens einen Auftrag ergeben. Gilt je Prozess;
# die Oberflaeche eines Ladens laeuft in einem Prozess.
_SCHRITT = threading.Lock()


def _fehler(status: int, satz: str) -> JSONResponse:
    return JSONResponse({"fehler": satz}, status_code=status)


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
        daten = json.loads(bytes(puffer).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, _fehler(400, "Der Rumpf ist kein gültiges JSON.")
    if not isinstance(daten, dict):
        return None, _fehler(400, "Der Rumpf muss ein JSON-Objekt sein.")
    return daten, None


def _zeit(wert) -> datetime | None:
    try:
        z = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except ValueError:
        return None
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


def _vorhandener(server, laden: str, sha: str) -> str | None:
    """Auftragsnummer (8 Hex) eines lebenden Video-Auftrags dieses Ladens mit demselben Konzept-Hash, angelegt
    vor hoechstens 10 Minuten; sonst None. Liest nur ueber auftrag_buch.eigene (sales_eigene)."""
    jetzt = datetime.now(timezone.utc)
    for z in auftrag_buch.eigene(server._q, laden, LEBENDE_STAENDE):
        eingabe = z.get("eingabe") if isinstance(z, dict) else None
        if not isinstance(z, dict) or z.get("art") != "video" or not isinstance(eingabe, dict):
            continue
        if eingabe.get("konzept_sha") != sha:
            continue
        angelegt = _zeit(z.get("angelegt"))
        if angelegt is None or jetzt - angelegt <= DOPPELT_FENSTER:   # unlesbare Zeit: lieber ablehnen
            return str(z.get("id", ""))[:8]
    return None


def _uebergeben(server, laden: str, mandant: str, eingabe: dict, sha: str):
    """-> (Auftrags-UUID, None) oder (None, Fehlerantwort)."""
    with _SCHRITT:
        vorhanden = _vorhandener(server, laden, sha)
        if vorhanden:
            return None, _fehler(409, f"Dieses Konzept wurde vor weniger als 10 Minuten schon übergeben: "
                                      f"Auftrag {vorhanden}.")
        try:
            return auftrag_buch.anlegen(server._q, laden, mandant, "video", eingabe), None
        except auftrag_buch.AuftragAbgelehnt as e:
            grenze = "zwei Videos" in e.grund or "Tagesgrenze" in e.grund
            return None, _fehler(429 if grenze else 400, e.grund)


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
        mandant = os.environ.get("MARKETING_MANDANT", "").strip()
        if not mandant:
            return _fehler(400, "Für diesen Laden ist keine Marketing-Firma eingetragen.")
        firma = konzept.get("firma")
        if isinstance(firma, str) and firma.strip() and firma.strip() != mandant:
            return _fehler(400, "Das Konzept gehört zu einer anderen Firma als dieser Laden.")
        laden = os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"
        sha = video_konzept.block_hash(konzept)
        eingabe = {"thema": thema.strip(), "beschreibung": beschreibung or "", "minuten": daten["minuten"],
                   "zielgruppe": (zielgruppe or "").strip() or server.VIDEO_ZIELGRUPPE_VORGABE,
                   "von": HERKUNFT, "konzept": konzept, "konzept_sha": sha}
        aid, fehler = await run_in_threadpool(_uebergeben, server, laden, mandant, eingabe, sha)
        if fehler:
            return fehler
        LOG.info("auftraege-api herkunft=%s art=video auftrag=%s", HERKUNFT, aid[:8])
        basis = ui.UI_BASIS_URL.rstrip("/")
        return JSONResponse({"auftrag": aid[:8], "id": aid, "link": f"{basis}{ui_werkbank.BASIS}/{aid}"})

    return [Route(PFAD, video, methods=["POST"])]
