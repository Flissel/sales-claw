"""API des Freigabe-Eingangs fuer Dienste (Plan 2026-11-08, Task 5).

Jeder Dienst (debugger-claw, selbstbild, werkstatt) hat einen eigenen Schluessel
(`Authorization: Bearer ...`). Die Herkunft kommt immer aus dem Schluessel, nie
aus dem Rumpf. Die Routen brauchen weder Sitzung noch CSRF: die AnmeldeWache nimmt
den Praefix /api/freigaben/ aus. Weder Schluessel noch Rumpf stehen in Antwort oder Log.
`ui` wird nie importiert, sondern bei `routen(ui)` hereingereicht.
"""
from __future__ import annotations

import json
import logging

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import freigabe_eingang as fe

PRAEFIX = "/api/freigaben/"
MAX_RUMPF = 8 * 1024
LOG = logging.getLogger("sales-ui")


def _fehler(status: int, kurz: str) -> JSONResponse:
    return JSONResponse({"fehler": kurz}, status_code=status)


def _herkunft(request: Request) -> str | None:
    kopf = request.headers.get("authorization", "")
    teile = kopf.split(None, 1)
    if len(teile) != 2 or teile[0].lower() != "bearer":
        return None
    return fe.schluessel_herkunft(teile[1].strip())


async def _rumpf(request: Request):
    """-> (dict | None, Fehlerantwort | None); liest hoechstens MAX_RUMPF Byte."""
    laenge = request.headers.get("content-length", "")
    if laenge.isdigit() and int(laenge) > MAX_RUMPF:
        return None, _fehler(413, "rumpf_zu_gross")
    puffer = bytearray()
    async for stueck in request.stream():
        puffer += stueck
        if len(puffer) > MAX_RUMPF:
            return None, _fehler(413, "rumpf_zu_gross")
    try:
        daten = json.loads(bytes(puffer).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, _fehler(422, "kein_json")
    if not isinstance(daten, dict):
        return None, _fehler(422, "rumpf_kein_objekt")
    return daten, None


def _str(daten: dict, name: str, pflicht: bool = True):
    wert = daten.get(name)
    if wert is None and not pflicht:
        return None
    if not isinstance(wert, str) or (pflicht and not wert.strip()):
        raise fe.EingabeFehler(f"{name}_ungueltig")
    return wert


def routen(ui) -> list[Route]:
    def gesichert(handler):
        async def huelle(request: Request):
            herkunft = await run_in_threadpool(_herkunft, request)
            if herkunft is None:
                return _fehler(401, "nicht_berechtigt")
            LOG.info("freigabe-api herkunft=%s pfad=%s", herkunft, request.url.path)
            return await handler(request, herkunft)
        return huelle

    async def eintrag(request, herkunft):
        daten, fehler = await _rumpf(request)
        if fehler:
            return fehler
        try:
            art = _str(daten, "art")
            ref = _str(daten, "quelle_ref")
            titel = _str(daten, "titel")
            link = _str(daten, "link", False)
            details = daten.get("details")
            if details is not None and not isinstance(details, dict):
                raise fe.EingabeFehler("details_ungueltig")
            if fe.ART_JE_HERKUNFT.get(herkunft) != art:
                return _fehler(403, "art_nicht_erlaubt")
            kennung, neu = await run_in_threadpool(
                fe.eintragen, herkunft, art, ref, titel, link, details)
        except fe.EingabeFehler:
            return _fehler(422, "ungueltig")
        return JSONResponse({"kennung": kennung, "neu": neu}, status_code=201 if neu else 200)

    async def schliessen(request, herkunft):
        daten, fehler = await _rumpf(request)
        if fehler:
            return fehler
        try:
            ref = _str(daten, "quelle_ref")
            status = _str(daten, "status")
            n = await run_in_threadpool(fe.schliessen, herkunft, ref, status, herkunft)
        except fe.EingabeFehler:
            return _fehler(422, "ungueltig")
        return JSONResponse({"geschlossen": n})

    async def offen(request, herkunft):
        zeilen = await run_in_threadpool(fe.offene, herkunft)
        return JSONResponse({"eintraege": [
            {"kennung": z["kennung"], "art": z["art"], "quelle_ref": z["quelle_ref"],
             "details": z["details"], "rowboat_stand": z["rowboat_stand"],
             "vermerk": z["vermerk"]} for z in zeilen]})

    async def auftraege(request, herkunft):
        zeilen = await run_in_threadpool(fe.auftraege_abholen, herkunft)
        return JSONResponse({"auftraege": [
            {"id": str(z["id"]), "art": z["art"], "nutzlast": z["nutzlast"]}
            for z in zeilen]})

    async def auftrag_ergebnis(request, herkunft):
        daten, fehler = await _rumpf(request)
        if fehler:
            return fehler
        ok = daten.get("ok")
        meldung = daten.get("fehler")
        if not isinstance(ok, bool) or not (meldung is None or isinstance(meldung, str)):
            return _fehler(422, "ungueltig")
        gefunden = await run_in_threadpool(
            fe.auftrag_ergebnis, request.path_params["id"], herkunft, ok, meldung)
        if not gefunden:
            return _fehler(404, "unbekannt")
        return JSONResponse({"ok": True})

    return [
        Route(PRAEFIX + "eintrag", gesichert(eintrag), methods=["POST"]),
        Route(PRAEFIX + "schliessen", gesichert(schliessen), methods=["POST"]),
        Route(PRAEFIX + "offen", gesichert(offen), methods=["GET"]),
        Route(PRAEFIX + "auftraege", gesichert(auftraege), methods=["GET"]),
        Route(PRAEFIX + "auftraege/{id}", gesichert(auftrag_ergebnis), methods=["POST"]),
    ]
