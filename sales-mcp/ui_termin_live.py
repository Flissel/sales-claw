"""Steuerseite /termine/{uid}/live (Meeting-Mittelpunkt, Task 7).

Waehrend des Meetings: grosse Zustandsanzeige, Live-Mitschrift, Bilder live (Kacheln)
und die Knoepfe Pause / Weiter / Notbremse. Die Seite schreibt nur den WUNSCH
(termin_akte.aufnahme_wuenschen); den Bot steuert sales-termine und schreibt den
bestaetigten Zustand zurueck. Angezeigt wird immer der BESTAETIGTE Zustand - nie
„pausiert“, bevor der Bot es bestaetigt hat (R3/R18).

`GET /termine/{uid}/live` HTML, `GET /termine/{uid}/live.json` Zustand fuers Skript,
`POST /termine/{uid}/live` (aktion pause|weiter|notbremse + csrf), `GET
/termine/live.js` das Skript. Das Transkript ist Fremdtext: das Skript setzt es nur
per textContent, die Seite selbst enthaelt keins. Keine Inhalte und Namen in Logs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import bildschirm
import server
import termin_akte
import ui_kalender
from ui_kalender import _gesichert_json, _grund, _ok
from ui_termin import _BILDSTATUS_LIVE, _bild_json, _e, _link_ok, _zone_der, pause_zeile

LIVE_JS = Path(__file__).resolve().parent / "static" / "termine" / "live.js"
SEGMENTE_MAX = 400
BILDER_MAX = 24          # Kacheln: die neuesten gepruefte Bilder (die Akte zeigt alle)
AKTIONEN = {"pause": "pause", "weiter": "an", "notbremse": "notbremse"}
MELDUNGEN = {"nicht_aktiv": "Die Aufnahme läuft nicht (mehr) – nichts geändert.",
             "notbremse": "Die Notbremse ist gezogen – nichts geändert."}
# I2: so lange nach Klick ohne Bestaetigung wird die Seite von selbst laut, auch wenn
# sales-termine (die Wache, die den Fehler schreibt) gar nicht laeuft. Wache: 10 s.
ANZEIGE_FRIST = timedelta(seconds=12)
# Akte-Status, in denen der Taktgeber das Ende bei Vexa erkannt hat: Bot ist weg.
BOT_WEG = ("fertig", "fehlgeschlagen")
# Bei welchem bestaetigten Zustand welcher Knopf sichtbar ist (live.js blendet um).
# In den Notbremse-Zustaenden keiner: die Notbremse ist endgueltig (M2).
KNOEPFE = {
    "pause": ("an", "wird_fortgesetzt", "weiter_nicht_bestaetigt"),
    "weiter": ("pausiert", "wird_pausiert", "nicht_bestaetigt", "weiter_nicht_bestaetigt"),
    "notbremse": ("an", "wird_pausiert", "pausiert", "wird_fortgesetzt", "nicht_bestaetigt",
                  "weiter_nicht_bestaetigt"),
}
KNOPF_TEXT = {"pause": "⏸ Pause", "weiter": "▶ Weiter", "notbremse": "■ Notbremse"}


def _ueberfaellig(klick, jetzt: datetime) -> bool:
    """Ohne Klickzeit gibt es nichts zu pruefen: laut (fail loud)."""
    return klick is None or jetzt - klick > ANZEIGE_FRIST


def zustand(z: dict, jetzt: datetime | None = None) -> str:
    """Bestaetigter Zustand, erste Uebereinstimmung gewinnt (R3 + R18, Final-Review
    C1/I1/I2): notbremse (bestaetigt) / notbremse_nicht_bestaetigt /
    notbremse_angefordert > nicht_bestaetigt > weiter_nicht_bestaetigt > pausiert /
    wird_pausiert / wird_fortgesetzt / an. "Nicht bestaetigt" kommt aus der Spalte der
    Wache ODER aus der Zeit seit dem Klick (`ANZEIGE_FRIST`) - die Seite wird auch
    laut, wenn die Wache gar nicht laeuft. Klickzeiten: `pause_von` (offene Zeile),
    `weiter_am` (bis der zuletzt geschlossenen Zeile, sonst aufnahme_wunsch_am),
    `aufnahme_wunsch_am` (Notbremse)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    wunsch, fehler = z.get("aufnahme_wunsch"), z.get("aufnahme_pause_fehler")
    seit = z.get("aufnahme_pausiert_seit")
    if wunsch == "notbremse":
        if z.get("aufnahme_notbremse_am") or z.get("status") in BOT_WEG:
            return "notbremse"
        if (fehler == "notbremse_nicht_bestaetigt"
                or _ueberfaellig(z.get("aufnahme_wunsch_am"), jetzt)):
            return "notbremse_nicht_bestaetigt"
        return "notbremse_angefordert"
    if fehler == "nicht_bestaetigt":
        return "nicht_bestaetigt"
    if fehler == "weiter_nicht_bestaetigt":
        return "weiter_nicht_bestaetigt"
    if wunsch == "pause":
        if seit:
            return "pausiert"
        # Ohne offene Zeile (I1) gibt es keine Klickzeit: laut.
        return "nicht_bestaetigt" if _ueberfaellig(z.get("pause_von"), jetzt) else "wird_pausiert"
    if wunsch == "an" and seit:
        klick = z.get("weiter_am") or z.get("aufnahme_wunsch_am")
        return "weiter_nicht_bestaetigt" if _ueberfaellig(klick, jetzt) else "wird_fortgesetzt"
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
        "notbremse_angefordert": "■ Notbremse angefordert – Bot wird entfernt …",
        "notbremse_nicht_bestaetigt": "⚠ Notbremse nicht bestätigt – Bot evtl. noch im Raum",
        "notbremse": "■ Notbremse – Bot hat den Raum verlassen",
    }[name]


def _pfad(uid: str) -> str:
    return f"/termine/{quote(uid, safe='')}"


def _zeile(uid: str) -> dict | None:
    z = server._q(
        "select a.uid, a.titel, a.thema, a.status, a.link, a.zeitzone, a.aufnahme_wunsch, "
        "a.aufnahme_wunsch_am, a.aufnahme_pausiert_seit, a.aufnahme_pause_fehler, "
        "a.aufnahme_notbremse_am, "
        "(select p.von from termin_pausen p where p.uid = a.uid and p.bis is null) as pause_von, "
        "(select max(q.bis) from termin_pausen q where q.uid = a.uid) as weiter_am "
        "from termin_akten a where a.uid = %s", (uid,))
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
    # Bilder live (Kacheln, Final-Review I5): dieselben Bilder wie im Bildschirm-Reiter
    # der Akte (nur gepruefte, R11; Bytes ueber dieselbe gesicherte Route, same origin),
    # zusaetzlich nie eins aus einem Pausenfenster (R17 loescht sie ohnehin).
    alle = [] if gesperrt else [b for b in bildschirm.bilder(uid)
                                if not termin_akte.in_pause(b["aufgenommen_am"], pausen)]
    kacheln = [_bild_json(uid, b, zone) for b in alle[-BILDER_MAX:]]
    return {
        "gesperrt": gesperrt,
        "zustand": name,
        "zustand_text": zustand_text(name, z, zone),
        "pausiert_seit": _iso(z.get("aufnahme_pausiert_seit")),
        "segmente": [{"beginn": _iso(s["beginn"]), "uhr": f"{s['beginn'].astimezone(zone):%H:%M}",
                      "sprecher": s["sprecher"], "text": s["text"]} for s in segmente],
        "pausen": [{"von": _iso(p["von"]), "bis": _iso(p["bis"]),
                    "text": pause_zeile(p, zone)} for p in pausen],
        "bilder": kacheln,
        "bilder_anzahl": len(alle),
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
                    + '<div class="live-spalten"><section>'
                    '<h2>Live-Mitschrift</h2><div class="live-text" id="live-text"></div>'
                    '</section><section><h2>Bilder live</h2>'
                    '<p class="meta" id="live-bilder"></p>'
                    '<ul class="bild-raster live-bilder" id="live-bilder-raster"></ul>'
                    '</section></div></div>'
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
        meldung = ""
        if not ok:
            # M2: nach der Notbremse aendert nichts mehr etwas - eigene Meldung.
            z = _zeile(uid)
            meldung = ("?m=notbremse" if z and z["aufnahme_wunsch"] == "notbremse"
                       else "?m=nicht_aktiv")
        return RedirectResponse(_pfad(uid) + "/live" + meldung, status_code=303)

    @ui._gesichert_seite
    async def skript(request):
        return Response(LIVE_JS.read_bytes(), media_type="text/javascript",
                        headers={"cache-control": "no-cache",
                                 "X-Content-Type-Options": "nosniff"})

    return [Route("/termine/live.js", skript, methods=["GET"]),
            Route("/termine/{kennung:path}/live.json", live_json, methods=["GET"]),
            Route("/termine/{kennung:path}/live", seite, methods=["GET"]),
            Route("/termine/{kennung:path}/live", aktion, methods=["POST"])]
