"""Kalender-Seite und ihre JSON-Schnittstelle (Spec 2026-10-14-kalender-pflegen).

Die Seite /kalender bettet das Paket /static/kalender/kalender.js ein (die
zweite Seite mit Skript nach dem Newsletter-Editor) und zeigt darunter die
bisherigen, serverseitig gebauten Abschnitte (ui.kalender_abschnitte, R5).

Schreibwege fuer Kundentermine laufen ueber dieselben Werkzeuge wie der Chat
(server.termin_bestaetigen / termin_aendern / termin_absagen); jede Aenderung
oder Absage legt danach per server.kunde_benachrichtigen einen PENDING-Entwurf
an den Kunden an oder meldet, dass es keinen Kanal gibt. Versendet wird nichts.
Konflikte kommen VOR jedem Schreiben (409); erst ein zweiter Aufruf mit
`trotzdem: true` schreibt und legt den Entwurf an.

Rollen `lesen` und `kalender` schreiben nie: die AnmeldeWache weist jeden
Nicht-GET dieser Rollen ab (403), bevor eine Route hier laeuft."""
from __future__ import annotations

import functools
import hmac
import json
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

import kalender
import kalender_sicht
import konferenz
import server
import termine_eigen
from ui_editor import _json_im_html

STATIK = Path(__file__).resolve().parent / "static" / "kalender"
STATIK_DATEIEN = {"kalender.js": "text/javascript", "kalender.css": "text/css"}
# Zusaetze zu ui._CSP - genau das, was das Paket braucht: eigenes Skript,
# eigenes Stylesheet, Abrufe an dieselbe Herkunft.
_CSP_ZUSAETZE = {"script-src": "script-src 'self'", "connect-src": "connect-src 'self'",
                 "style-src": "style-src 'self' 'unsafe-inline'"}


def csp_kalender(ui) -> str:
    """ui._CSP mit ersetzten/ergaenzten Direktiven aus _CSP_ZUSAETZE. Aus
    ui._CSP abgeleitet, damit jede Verschaerfung dort hier mitgeht."""
    teile, gesehen = [], set()
    for d in (t.strip() for t in ui._CSP.split(";")):
        if not d:
            continue
        name = d.split()[0]
        gesehen.add(name)
        teile.append(_CSP_ZUSAETZE.get(name, d))
    teile += [w for n, w in _CSP_ZUSAETZE.items() if n not in gesehen]
    return "; ".join(teile)
ANSICHTEN = ("woche", "tag", "monat", "liste")
SPANNE_MAX_TAGE = 62
KOERPER_MAX = 32 * 1024
TEXT_MAX = 200
KONTAKTE_MAX = 10

NICHT_IM_HANDY = "nicht im Handy-Kalender"
VERALTET = "inzwischen geändert – neu laden"
NICHT_BENACHRICHTIGT = ("Entwurf an den Kunden nicht angelegt – bitte selbst "
                        "Bescheid geben")
_KENNUNG = re.compile(r"^(eigen|kunde):(.+)$")


def _grund(status: int, grund: str, **mehr) -> JSONResponse:
    return JSONResponse({**mehr, "grund": grund}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _ok(daten: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(daten, status_code=status, headers={"Cache-Control": "no-store"})


def _gesichert_json(fn):
    """DB-Ausfall wird zur JSON-Antwort 503, nie zum Traceback."""
    @functools.wraps(fn)
    async def innen(request):
        try:
            return await fn(request)
        except psycopg.OperationalError:
            return _grund(503, "Datenbank nicht erreichbar")
        except psycopg.Error as e:
            # Nur der SQLSTATE - Fehlertexte der DB koennen Fremddaten tragen.
            return _grund(503, f"Datenbankfehler (SQLSTATE {e.sqlstate})")
    return innen


def _csrf_ok(request, ui) -> bool:
    # Bytes statt str: compare_digest wirft bei Nicht-ASCII-str einen
    # TypeError (Starlette dekodiert Koepfe als latin-1) -> waere ein 500.
    marke = request.headers.get("x-csrf", "")
    return bool(marke) and hmac.compare_digest(marke.encode("latin-1", "replace"),
                                               ui.CSRF_TOKEN.encode())


async def _koerper(request):
    """-> (dict, None) oder (None, Fehlerantwort)."""
    roh = bytearray()
    async for stueck in request.stream():
        roh += stueck
        if len(roh) > KOERPER_MAX:
            return None, _grund(413, "Die Anfrage ist zu groß")
    if not roh.strip():
        return {}, None
    try:
        body = json.loads(bytes(roh))
    except (ValueError, UnicodeDecodeError):
        return None, _grund(422, "Die Anfrage ist kein gültiges JSON")
    if not isinstance(body, dict):
        return None, _grund(422, "Die Anfrage ist kein JSON-Objekt")
    return body, None


def _zeitpunkt(wert, mit_offset: bool = True):
    """ISO-Zeitpunkt -> aware datetime oder None. Ohne Offset ungueltig,
    ausser `mit_offset=False` (dann gilt die Ortszeit)."""
    if not isinstance(wert, str) or not wert:
        return None
    try:
        t = datetime.fromisoformat(wert)
    except ValueError:
        return None
    if t.tzinfo is None:
        if mit_offset:
            return None
        t = t.replace(tzinfo=kalender_sicht._zone())
    return t


def _ganzzahl(wert, unten: int, oben: int) -> bool:
    return isinstance(wert, int) and not isinstance(wert, bool) and unten <= wert <= oben


def _text(wert, leer_erlaubt: bool = True) -> bool:
    return isinstance(wert, str) and len(wert) <= TEXT_MAX and (leer_erlaubt or wert.strip())


def _fehler_antwort(fehler: str) -> JSONResponse:
    """Fehlertext eines Werkzeugs -> 503 bei DB-Ausfall, sonst 422."""
    if fehler == server.DB_FEHLER or fehler.startswith("Datenbankfehler"):
        return _grund(503, fehler)
    return _grund(422, fehler)


def _stand_hinweis(stand) -> str:
    # NULL = unbekannt (noch nicht abgeglichen) -> kein Hinweis.
    return NICHT_IM_HANDY if str(stand or "").startswith(kalender.FEHLGESCHLAGEN) else ""


def _mit_hinweisen(daten: dict, hinweise: list) -> dict:
    hinweise = [h for h in hinweise if h]
    if hinweise:
        daten["hinweis"] = " · ".join(hinweise)
    return daten


# --- Ereignisse in der Form von kalender_sicht.ereignisse ---------------------

def _ereignis_eigen(t: dict) -> dict:
    beginn = t["beginn"].astimezone(kalender_sicht._zone())
    e = {"id": f"eigen:{t['uid']}", "art": "eigen", "uid": t["uid"], "titel": t["titel"],
         "beginn": beginn.isoformat(),
         "ende": (beginn + timedelta(minutes=t["dauer_minuten"])).isoformat(),
         "bearbeitbar": True, "geaendert_am": t["geaendert_am"]}
    for feld in ("ort", "notiz"):
        if t.get(feld):
            e[feld] = t[feld]
    return e


def _ereignis_kunde(termin: dict, lead_id: str, name: str) -> dict:
    beginn = kalender_sicht._beginn(termin)
    dauer = kalender_sicht._dauer(termin)
    kontakt = (name or "").strip() or kalender_sicht.OHNE_KONTAKT
    e = {"id": f"kunde:{termin['uid']}", "art": "kunde", "uid": termin["uid"],
         "lead_id": lead_id, "kontakt": kontakt,
         "titel": f"{termin.get('thema') or ''} – {kontakt}",
         "beginn": beginn.isoformat() if beginn else "",
         "ende": (beginn + timedelta(minutes=dauer)).isoformat() if beginn else "",
         "bearbeitbar": bool(lead_id and (name or "").strip())}
    if termin.get("ort"):
        e["ort"] = termin["ort"]
    return e


def _kundentermin(uid: str):
    """Juengste `termin`-Zeile mit dieser uid -> {lead_id, name, payload} oder None."""
    z = server._q(
        "select a.lead_id::text as lead_id, a.payload, l.name from activities a "
        "left join leads l on l.id = a.lead_id where a.type = 'termin' "
        "and a.payload->>'uid' = %s order by a.created_at desc limit 1", (uid,))
    return z[0] if z else None


def _eigen_stand(uid: str):
    z = server._q("select beginn, dauer_minuten, geaendert_am from eigene_termine "
                  "where uid = %s", (uid,))
    return z[0] if z else None


def _name(lead_id: str) -> str:
    z = server._q("select name from leads where id = %s", (lead_id,))
    return (z[0]["name"] or "") if z else ""


async def _konflikt(beginn: datetime, dauer: int, ausser_uid: str = ""):
    """-> 409-Antwort bei Treffern, sonst None."""
    k = await run_in_threadpool(kalender_sicht.konflikte, beginn, dauer, ausser_uid)
    if k["konflikte"]:
        return _grund(409, "Konflikt", konflikte=k["konflikte"],
                      unvollstaendig=k["unvollstaendig"])
    return None


async def _benachrichtigen(lead_id: str, alt: dict, neu, grund: str = ""):
    """kunde_benachrichtigen ist nicht gegen DB-Fehler gesichert -> (dict|None, ok)."""
    try:
        return await run_in_threadpool(server.kunde_benachrichtigen, lead_id, alt, neu, grund), True
    except psycopg.Error:
        return None, False


def _benachrichtigung_anhaengen(daten: dict, b: dict) -> dict:
    if "draft_id" in b:
        daten["entwurf"] = {"draft_id": str(b["draft_id"]), "kanal": b["kanal"]}
    elif b.get("hinweis"):
        daten["hinweis"] = b["hinweis"]
    elif b.get("fehler"):
        daten["hinweis"] = f"{b['fehler']} – {NICHT_BENACHRICHTIGT}"
    return daten


def _ortszeit(beginn: datetime) -> tuple[str, str]:
    t = beginn.astimezone(kalender_sicht._zone())
    return t.date().isoformat(), f"{t:%H:%M}"


def routen(ui) -> list:

    @ui._gesichert_seite
    async def seite(request):
        roh = request.query_params.get("datum", "")
        try:
            tag = date.fromisoformat(roh) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", roh) else None
        except ValueError:
            tag = None
        tag = tag or datetime.now(kalender_sicht._zone()).date()
        ansicht = request.query_params.get("ansicht", "")
        rolle = str(request.scope.get("benutzer_rolle") or "")
        start = {"csrf": ui.CSRF_TOKEN, "rolle": rolle,
                 "darf_schreiben": rolle not in ("lesen", "kalender"),
                 "datum": tag.isoformat(),
                 "ansicht": ansicht if ansicht in ANSICHTEN else "woche",
                 "freigaben_url": "/freigaben"}
        rumpf = ('<link rel="stylesheet" href="/static/kalender/kalender.css">'
                 '<div id="kalender"></div>'
                 f'<script type="application/json" id="kalender-start">{_json_im_html(start)}</script>'
                 '<script src="/static/kalender/kalender.js" defer></script>'
                 + ui.kalender_abschnitte())
        antwort = ui._seite("Kalender", rumpf)
        antwort.headers["Content-Security-Policy"] = csp_kalender(ui)
        antwort.headers["Cache-Control"] = "no-store"
        return antwort

    async def statik(request):
        datei = request.path_params["datei"]
        typ = STATIK_DATEIEN.get(datei)
        pfad = STATIK / datei
        if not typ or not pfad.is_file():
            return Response("Nicht gefunden", status_code=404, media_type="text/plain")
        return FileResponse(pfad, media_type=typ, headers={"Cache-Control": "no-cache"})

    @_gesichert_json
    async def termine_json(request):
        von = _zeitpunkt(request.query_params.get("von", ""))
        bis = _zeitpunkt(request.query_params.get("bis", ""))
        if von is None or bis is None:
            return _grund(422, "von und bis müssen ISO-Zeitpunkte mit Zeitzone sein")
        if bis <= von:
            return _grund(422, "bis muss nach von liegen")
        if bis - von > timedelta(days=SPANNE_MAX_TAGE):
            return _grund(422, f"Höchstens {SPANNE_MAX_TAGE} Tage auf einmal")
        return _ok(await run_in_threadpool(kalender_sicht.ereignisse, von, bis))

    @_gesichert_json
    async def kontakte_json(request):
        # Die schmale Rolle sieht Termine, nicht den Kundenstamm (W5).
        if str(request.scope.get("benutzer_rolle") or "") == "kalender":
            return _grund(403, "Nicht für diese Anmeldung")
        q = request.query_params.get("q", "").strip()[:100]
        if not q:
            return _ok({"kontakte": []})
        d = json.loads(await run_in_threadpool(server.kontakt_suchen, q))
        if "fehler" in d:
            return _fehler_antwort(d["fehler"])
        return _ok({"kontakte": [{"lead_id": str(k["lead_id"]), "name": k["name"]}
                                 for k in d["kontakte"] if not k.get("archiviert")][:KONTAKTE_MAX]})

    @_gesichert_json
    async def anlegen(request):
        if not _csrf_ok(request, ui):
            return _grund(403, "Fehlende oder falsche CSRF-Marke")
        body, fehler = await _koerper(request)
        if fehler:
            return fehler
        art = body.get("art")
        beginn = _zeitpunkt(body.get("beginn"))
        dauer = body.get("dauer_minuten")
        ort = body.get("ort", "")
        trotzdem = body.get("trotzdem", False)
        if beginn is None:
            return _grund(422, "Beginn fehlt oder hat keine Zeitzone")
        if not isinstance(trotzdem, bool):
            return _grund(422, "trotzdem muss true oder false sein")
        if not _text(ort):
            return _grund(422, "Ort ist ungültig oder zu lang (höchstens 200 Zeichen)")

        if art == "eigen":
            titel, notiz = body.get("titel"), body.get("notiz", "")
            f = termine_eigen._pruefen(titel, beginn, dauer, ort, notiz)
            if f:
                return _grund(422, f)
            k = None if trotzdem else await _konflikt(beginn, dauer)
            if k:
                return k
            r = await run_in_threadpool(termine_eigen.anlegen, titel, beginn, dauer, ort, notiz)
            if "fehler" in r:
                return _grund(422, r["fehler"])
            return _ok(_mit_hinweisen({"ereignis": _ereignis_eigen(r["termin"])},
                                      [_stand_hinweis(r["termin"].get("kalender_stand"))]), 201)

        if art != "kunde":
            return _grund(422, "art muss eigen oder kunde sein")
        lead_id, thema = body.get("lead_id"), body.get("thema", "")
        einladung = body.get("einladung", False)
        try:
            lead_id = str(uuid.UUID(str(lead_id)))
        except ValueError:
            return _grund(422, "lead_id fehlt oder ist ungültig")
        if not _text(thema, leer_erlaubt=False):
            return _grund(422, "Thema fehlt oder ist zu lang (höchstens 200 Zeichen)")
        if not _ganzzahl(dauer, server.TERMIN_DAUER_MIN, server.TERMIN_DAUER_MAX):
            return _grund(422, f"Dauer muss {server.TERMIN_DAUER_MIN}–"
                               f"{server.TERMIN_DAUER_MAX} Minuten sein")
        if not isinstance(einladung, bool):
            return _grund(422, "einladung muss true oder false sein")
        k = None if trotzdem else await _konflikt(beginn, dauer)
        if k:
            return k
        datum, uhrzeit = _ortszeit(beginn)
        b = json.loads(await run_in_threadpool(
            server.termin_bestaetigen, lead_id, datum, uhrzeit, dauer, thema.strip(), ort))
        if "termin" not in b:
            return _fehler_antwort(str(b.get("fehler") or "Termin nicht angelegt"))
        daten = {"ereignis": _ereignis_kunde(b["termin"], lead_id, await run_in_threadpool(_name, lead_id))}
        hinweise = [_stand_hinweis(b.get("kalender"))]
        if einladung:
            t = b["termin"]
            try:
                e = json.loads(await run_in_threadpool(
                    functools.partial(server._termin_einladen, lead_id, t["datum"], t["uhrzeit"],
                                      t["dauer_minuten"], t["thema"], t.get("ort") or "",
                                      termin_bezug=True)))
            except psycopg.Error:
                e = {"fehler": "Datenbank nicht erreichbar"}
            if "draft_id" in e:
                daten["entwurf"] = {"draft_id": str(e["draft_id"]), "kanal": "email"}
            else:
                hinweise.append(f"Einladung nicht angelegt: {e.get('fehler') or 'unbekannt'}")
        return _ok(_mit_hinweisen(daten, hinweise), 201)

    def _kennung(request):
        m = _KENNUNG.match(request.path_params["kennung"])
        return (m.group(1), m.group(2)) if m else (None, None)

    @_gesichert_json
    async def aendern(request):
        if not _csrf_ok(request, ui):
            return _grund(403, "Fehlende oder falsche CSRF-Marke")
        art, uid = _kennung(request)
        if not art:
            return _grund(422, "Dieser Termin lässt sich hier nicht bearbeiten")
        body, fehler = await _koerper(request)
        if fehler:
            return fehler
        trotzdem = body.get("trotzdem", False)
        if not isinstance(trotzdem, bool):
            return _grund(422, "trotzdem muss true oder false sein")
        beginn = None
        if "beginn" in body:
            beginn = _zeitpunkt(body["beginn"])
            if beginn is None:
                return _grund(422, "Beginn hat kein gültiges Format oder keine Zeitzone")

        if art == "eigen":
            alt = await run_in_threadpool(_eigen_stand, uid)
            if alt is None:
                return _grund(404, "Diesen Termin gibt es nicht.")
            alt = [alt]
            stempel = body.get("geaendert_am")
            if not isinstance(stempel, str) or not stempel:
                return _grund(422, "geaendert_am fehlt")
            if alt[0]["geaendert_am"].isoformat() != stempel:
                return _grund(409, VERALTET)
            felder = {k: body[k] for k in ("titel", "dauer_minuten", "ort", "notiz") if k in body}
            if beginn is not None:
                felder["beginn"] = beginn
            neu_beginn = felder.get("beginn", alt[0]["beginn"])
            neu_dauer = felder.get("dauer_minuten", alt[0]["dauer_minuten"])
            if (not trotzdem and _ganzzahl(neu_dauer, termine_eigen.DAUER_MIN, termine_eigen.DAUER_MAX)
                    and (neu_beginn != alt[0]["beginn"] or neu_dauer != alt[0]["dauer_minuten"])):
                k = await _konflikt(neu_beginn, neu_dauer, uid)
                if k:
                    return k
            r = await run_in_threadpool(functools.partial(termine_eigen.aendern, uid, stempel, **felder))
            if r.get("veraltet"):
                return _grund(409, VERALTET)
            if "fehler" in r:
                return _grund(422, r["fehler"])
            return _ok(_mit_hinweisen({"ereignis": _ereignis_eigen(r["termin"])},
                                      [_stand_hinweis(r["termin"].get("kalender_stand"))]))

        zeile = await run_in_threadpool(_kundentermin, uid)
        if zeile is None:
            return _grund(404, "Diesen Termin gibt es nicht.")
        lead_id, alt = zeile["lead_id"], zeile["payload"] or {}
        if not lead_id:
            return _grund(422, "Dieser Termin hat keinen Kontakt und lässt sich nicht bearbeiten")
        # Inzwischen ersetzt (zweiter Tab, Chat) oder abgesagt -> neu laden (Spec §3).
        if await run_in_threadpool(server._termin_abgesagt, lead_id, uid):
            return _grund(409, VERALTET)
        dauer = body.get("dauer_minuten", 0)
        thema, ort = body.get("titel", ""), body.get("ort", "")
        if "dauer_minuten" in body and not _ganzzahl(dauer, server.TERMIN_DAUER_MIN,
                                                     server.TERMIN_DAUER_MAX):
            return _grund(422, f"Dauer muss {server.TERMIN_DAUER_MIN}–"
                               f"{server.TERMIN_DAUER_MAX} Minuten sein")
        if not _text(thema) or not _text(ort):
            return _grund(422, "Thema oder Ort ungültig oder zu lang (höchstens 200 Zeichen)")
        alt_beginn, alt_dauer = kalender_sicht._beginn(alt), kalender_sicht._dauer(alt)
        neu_beginn, neu_dauer = beginn or alt_beginn, dauer or alt_dauer
        if (not trotzdem and neu_beginn is not None
                and (neu_beginn != alt_beginn or neu_dauer != alt_dauer)):
            k = await _konflikt(neu_beginn, neu_dauer, uid)
            if k:
                return k
        datum, uhrzeit = _ortszeit(beginn) if beginn else ("", "")
        r = json.loads(await run_in_threadpool(
            server.termin_aendern, lead_id, uid, datum, uhrzeit, dauer, thema, ort))
        if "termin" not in r:
            return _fehler_antwort(str(r.get("fehler") or "Termin nicht geändert"))
        daten = {"ereignis": _ereignis_kunde(r["termin"], lead_id, zeile["name"] or ""),
                 "ersetzt": f"kunde:{uid}"}
        hinweise = [_stand_hinweis(r.get("kalender"))]
        b, ok = await _benachrichtigen(lead_id, alt, r["termin"])
        if not ok:
            return _grund(503, f"Termin geändert, aber {NICHT_BENACHRICHTIGT}", **daten)
        return _ok(_mit_hinweisen(_benachrichtigung_anhaengen(daten, b), hinweise))

    @_gesichert_json
    async def loeschen(request):
        if not _csrf_ok(request, ui):
            return _grund(403, "Fehlende oder falsche CSRF-Marke")
        art, uid = _kennung(request)
        if not art:
            return _grund(422, "Dieser Termin lässt sich hier nicht löschen")
        body, fehler = await _koerper(request)
        if fehler:
            return fehler
        if art == "eigen":
            r = await run_in_threadpool(termine_eigen.loeschen, uid)
            if "fehler" in r:
                return _grund(404, r["fehler"])
            daten = {"geloescht": True}
            if str(r.get("kalender") or "").startswith(kalender.FEHLGESCHLAGEN):
                daten["hinweis"] = "im Handy-Kalender nicht gelöscht – dort bitte selbst entfernen"
            return _ok(daten)

        grund = body.get("grund", "")
        if not isinstance(grund, str) or not grund.strip() or len(grund) > TEXT_MAX:
            return _grund(422, "Für eine Absage braucht es einen Grund (höchstens 200 Zeichen)")
        zeile = await run_in_threadpool(_kundentermin, uid)
        if zeile is None or not zeile["lead_id"]:
            return _grund(404, "Diesen Termin gibt es nicht.")
        lead_id, alt = zeile["lead_id"], zeile["payload"] or {}
        if await run_in_threadpool(server._termin_abgesagt, lead_id, uid):
            return _grund(409, VERALTET)
        r = json.loads(await run_in_threadpool(server.termin_absagen, lead_id, uid, grund.strip()))
        if "abgesagt" not in r:
            return _fehler_antwort(str(r.get("fehler") or "Termin nicht abgesagt"))
        daten = {"geloescht": True}
        b, ok = await _benachrichtigen(lead_id, alt, None, grund.strip())
        if not ok:
            return _grund(503, f"Termin abgesagt, aber {NICHT_BENACHRICHTIGT}", **daten)
        return _ok(_benachrichtigung_anhaengen(daten, b))

    @_gesichert_json
    async def videoraum(request):
        if not _csrf_ok(request, ui):
            return _grund(403, "Fehlende oder falsche CSRF-Marke")
        link, hinweis = await run_in_threadpool(konferenz.raum)
        return _ok({"link": link, **({"hinweis": hinweis} if hinweis else {})})

    return [
        Route("/kalender", seite),
        Route("/kalender/termine.json", termine_json),
        Route("/kalender/kontakte.json", kontakte_json),
        Route("/kalender/termine", anlegen, methods=["POST"]),
        Route("/kalender/termine/{kennung:path}", aendern, methods=["PATCH"]),
        Route("/kalender/termine/{kennung:path}", loeschen, methods=["DELETE"]),
        Route("/kalender/videoraum", videoraum, methods=["POST"]),
        Route("/static/kalender/{datei}", statik),
    ]
