"""Steuerseite /termine/{uid}/live (Meeting-Mittelpunkt, Task 7).

Waehrend des Meetings: grosse Zustandsanzeige, Live-Mitschrift, Bilderzahl und die
Knoepfe Pause / Weiter / Notbremse. Die Seite schreibt nur den WUNSCH
(termin_akte.aufnahme_wuenschen); den Bot steuert sales-termine und schreibt den
bestaetigten Zustand zurueck. Angezeigt wird immer der BESTAETIGTE Zustand - nie
„pausiert“, bevor der Bot es bestaetigt hat (R3/R18).

`GET /termine/{uid}/live` HTML, `GET /termine/{uid}/live.json` Zustand fuers Skript,
`POST /termine/{uid}/live` (aktion pause|weiter|notbremse + csrf), `GET
/termine/live.js` das Skript. Das Transkript ist Fremdtext: das Skript setzt es nur
per textContent, die Seite selbst enthaelt keins. Keine Inhalte und Namen in Logs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import server
import termin_akte
import ui_kalender
from ui_kalender import _gesichert_json, _grund, _ok
from ui_termin import _BILDSTATUS_LIVE, _e, _link_ok, _zone_der, pause_zeile

LIVE_JS = Path(__file__).resolve().parent / "static" / "termine" / "live.js"
SEGMENTE_MAX = 400
AKTIONEN = {"pause": "pause", "weiter": "an", "notbremse": "notbremse"}
MELDUNGEN = {"nicht_aktiv": "Die Aufnahme läuft nicht (mehr) – nichts geändert."}
# Bei welchem bestaetigten Zustand welcher Knopf sichtbar ist (live.js blendet um).
KNOEPFE = {
    "pause": ("an", "wird_fortgesetzt", "weiter_nicht_bestaetigt"),
    "weiter": ("pausiert", "wird_pausiert", "nicht_bestaetigt", "weiter_nicht_bestaetigt"),
    "notbremse": ("an", "wird_pausiert", "pausiert", "wird_fortgesetzt", "nicht_bestaetigt",
                  "weiter_nicht_bestaetigt"),
}
KNOPF_TEXT = {"pause": "⏸ Pause", "weiter": "▶ Weiter", "notbremse": "■ Notbremse"}


def zustand(z: dict) -> str:
    """Bestaetigter Zustand, erste Uebereinstimmung gewinnt (R3 + R18)."""
    wunsch, fehler = z.get("aufnahme_wunsch"), z.get("aufnahme_pause_fehler")
    seit = z.get("aufnahme_pausiert_seit")
    if wunsch == "notbremse":
        return "notbremse"
    if fehler == "nicht_bestaetigt":
        return "nicht_bestaetigt"
    if fehler == "weiter_nicht_bestaetigt":
        return "weiter_nicht_bestaetigt"
    if wunsch == "pause":
        return "pausiert" if seit else "wird_pausiert"
    if wunsch == "an" and seit:
        return "wird_fortgesetzt"
    return "an"


def zustand_text(name: str, z: dict, zone) -> str:
    seit = z.get("aufnahme_pausiert_seit")
    return {
        "an": "● Aufnahme läuft",
        "wird_pausiert": "⏳ Wird pausiert …",
        "pausiert": "⏸ Pausiert" + (f" seit {seit.astimezone(zone):%H:%M}" if seit else ""),
        "wird_fortgesetzt": "⏳ Wird fortgesetzt …",
        "nicht_bestaetigt": "⚠ Pause nicht bestätigt – Notbremse?",
        "weiter_nicht_bestaetigt": "⚠ Weiter nicht bestätigt – Aufnahme evtl. noch pausiert",
        "notbremse": "■ Notbremse – Bot hat den Raum verlassen",
    }[name]


def _pfad(uid: str) -> str:
    return f"/termine/{quote(uid, safe='')}"


def _zeile(uid: str) -> dict | None:
    z = server._q(
        "select uid, titel, thema, status, link, zeitzone, aufnahme_wunsch, "
        "aufnahme_pausiert_seit, aufnahme_pause_fehler from termin_akten where uid = %s",
        (uid,))
    return z[0] if z else None


def _iso(t) -> str | None:
    return t.astimezone(timezone.utc).isoformat() if t else None


def _live_daten(uid: str, z: dict) -> dict:
    zone = _zone_der(z)
    name = zustand(z)
    # Wie die Termin-Akte: ist jemand gesperrt, gibt es keinen Inhalt (nur den
    # Zustand, damit die Notbremse erreichbar bleibt).
    gesperrt = termin_akte.hat_gesperrte(uid)
    segmente = [] if gesperrt else server._q(
        "select beginn, sprecher, text from (select * from termin_live_segmente "
        "where uid = %s order by beginn desc, segment_id desc limit %s) s "
        "order by beginn, segment_id", (uid, SEGMENTE_MAX))
    pausen = [] if gesperrt else termin_akte.pausen(uid)
    bilder = 0 if gesperrt else server._q(
        "select count(*) as n from termin_bilder where uid = %s "
        "and beschreibung_status = 'fertig'", (uid,))[0]["n"]
    return {
        "gesperrt": gesperrt,
        "zustand": name,
        "zustand_text": zustand_text(name, z, zone),
        "pausiert_seit": _iso(z.get("aufnahme_pausiert_seit")),
        "segmente": [{"beginn": _iso(s["beginn"]), "uhr": f"{s['beginn'].astimezone(zone):%H:%M}",
                      "sprecher": s["sprecher"], "text": s["text"]} for s in segmente],
        "pausen": [{"von": _iso(p["von"]), "bis": _iso(p["bis"]),
                    "text": pause_zeile(p, zone)} for p in pausen],
        "bilder_anzahl": int(bilder),
    }


def _knoepfe(ui, uid: str, name: str) -> str:
    teile = []
    for aktion, text in KNOPF_TEXT.items():
        sichtbar = name in KNOEPFE[aktion]
        teile.append(
            f'<form method="post" action="{_e(_pfad(uid))}/live" class="aktion live-knopf" '
            f'data-bei="{" ".join(KNOEPFE[aktion])}"{"" if sichtbar else " hidden"}>'
            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
            f'<input type="hidden" name="aktion" value="{aktion}">'
            f'<button type="submit"{" class=gefahr" if aktion == "notbremse" else ""}>'
            f'{_e(text)}</button></form>')
    return f'<div class="termin-aktionen live-knoepfe">{"".join(teile)}</div>'


def routen(ui) -> list:

    @ui._gesichert_seite
    async def seite(request):
        uid = request.path_params["kennung"]
        z = _zeile(uid)
        if z is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Zu diesem Termin gibt es keine Akte.")
        schreiben = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
        name = zustand(z)
        meldung = MELDUNGEN.get(str(request.query_params.get("m") or ""))
        hinweis = f'<div class="hinweis">{_e(meldung)}</div>' if meldung else ""
        link = _link_ok(z["link"])
        meeting = (f'<a class="knopf sek" href="{_e(link)}" target="_blank" rel="noopener">'
                   'Meeting öffnen ↗</a>') if link else ""
        titel = z["titel"] or z["thema"] or "Kundentermin"
        if z["status"] in _BILDSTATUS_LIVE:
            kern = (f'<div id="live" data-json="{_e(_pfad(uid))}/live.json">'
                    f'<p class="live-zustand" id="live-zustand" data-zustand="{name}" '
                    f'role="status">{_e(zustand_text(name, z, _zone_der(z)))}</p>'
                    '<p class="fehler" id="live-verbindung" hidden>Verbindung unterbrochen</p>'
                    + (_knoepfe(ui, uid, name) if schreiben else "")
                    + ('<p class="fehler">Ein Teilnehmer ist gesperrt – die Live-Ansicht '
                       'zeigt keine Mitschrift und keine Bilder.</p>'
                       if termin_akte.hat_gesperrte(uid) else "")
                    + '<p class="meta" id="live-bilder"></p>'
                    '<h2>Live-Mitschrift</h2><div class="live-text" id="live-text"></div></div>'
                    '<script src="/termine/live.js" defer></script>')
        else:
            kern = '<p class="meta">Die Aufnahme läuft nicht – hier gibt es nichts zu steuern.</p>'
        rumpf = (hinweis + f'<h1>Live: {_e(titel)}</h1>'
                 f'<p><a href="{_e(_pfad(uid))}">← Zur Termin-Akte</a></p>{meeting}{kern}')
        antwort = ui._seite(f"Live: {titel}", rumpf, titel_zeigen=False)
        antwort.headers["Cache-Control"] = "no-store"
        antwort.headers["Content-Security-Policy"] = ui_kalender.csp_kalender(ui)
        return antwort

    @_gesichert_json
    async def live_json(request):
        uid = request.path_params["kennung"]
        z = _zeile(uid)
        if z is None:
            return _grund(404, "Keine Akte zu dieser uid.")
        return _ok(_live_daten(uid, z))

    @ui._gesichert_seite
    async def aktion(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Keine Aktion ausgeführt. Die Seite neu laden und erneut "
                                   "versuchen.")
        if ui._AKTIVE_ROLLE.get() in ("lesen", "kalender"):
            return ui._fehlerseite(403, "Nur Lesen", "Diese Anmeldung darf nichts ändern.")
        uid = request.path_params["kennung"]
        if _zeile(uid) is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Zu diesem Termin gibt es keine Akte.")
        wunsch = AKTIONEN.get(str(form.get("aktion") or ""))
        if wunsch is None:
            return ui._fehlerseite(400, "Unbekannte Aktion", "Nichts geändert.")
        wer = ui._AKTIVER_BENUTZER.get() or "termin-seite"
        ok = termin_akte.aufnahme_wuenschen(uid, wunsch, wer, datetime.now(timezone.utc))
        return RedirectResponse(_pfad(uid) + "/live" + ("" if ok else "?m=nicht_aktiv"),
                                status_code=303)

    @ui._gesichert_seite
    async def skript(request):
        return Response(LIVE_JS.read_bytes(), media_type="text/javascript",
                        headers={"cache-control": "no-cache",
                                 "X-Content-Type-Options": "nosniff"})

    return [Route("/termine/live.js", skript, methods=["GET"]),
            Route("/termine/{kennung:path}/live.json", live_json, methods=["GET"]),
            Route("/termine/{kennung:path}/live", seite, methods=["GET"]),
            Route("/termine/{kennung:path}/live", aktion, methods=["POST"])]
