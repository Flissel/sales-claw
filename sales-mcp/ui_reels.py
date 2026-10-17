"""Reels im Marketing-Pult (17.10.2026, Video-Claw, Marketing-Migration 072).

Betreiber-Entscheid E4: bestellen koennen der Betreiber (hier) und der Marketing-Agent. Gebaut wird am PC
vom Video-Claw mit Laura; das fertige MP4 liegt in den erzeugten Medien (vid-<id>-<titel>.mp4). Hinaus
geht es nur als Entwurf ueber die Freigaben - der Knopf "Als LinkedIn-Post vorbereiten" legt genau so
einen Entwurf an (post_entwurf_erstellen), und nur fuer die Firma dieses Ladens (MARKETING_MANDANT, wie
beim Newsletter-Versand). Wie der Rest von sales-ui ohne JavaScript.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import marketing_mandant
import marketing_pult

ARTEN = {"bilder": "Aus Bildern", "material": "Aus Videomaterial", "kurzfassung": "Kurzfassung eines Videos"}
STATUS = {"offen": "wartet", "in_arbeit": "wird gebaut", "fertig": "fertig", "fehler": "Fehler",
          "abgebrochen": "abgebrochen"}
_DATEI = re.compile(r"^vid-[0-9a-f]{8}-[a-z0-9-]{1,40}\.mp4$")
POST_TEXT_MAX = 3000


def _liste(roh: str) -> list[str]:
    return [t.strip() for t in str(roh or "").replace("\n", ",").split(",") if t.strip()]


def briefing_aus_formular(form) -> tuple[str, str, dict]:
    """(art, titel, briefing) aus dem Formular; geprueft wird in der Marketing-API (eine Wahrheit)."""
    art = str(form.get("art") or "")
    titel = str(form.get("titel") or "").strip()
    try:
        dauer = int(str(form.get("dauer_s") or "30"))
    except ValueError:
        dauer = 30
    b: dict = {"thema": str(form.get("thema") or "").strip(),
               "sprechertext": str(form.get("sprechertext") or "").strip(),
               "hook": str(form.get("hook") or "").strip(), "dauer_s": dauer,
               "stimme": str(form.get("stimme") or "").strip() or "standard"}
    if art == "bilder":
        b["bilder"] = _liste(form.get("bilder"))
        if str(form.get("logo") or "").strip():
            b["logo"] = str(form.get("logo")).strip()
        farben = {k: str(form.get(f"farbe_{k}") or "").strip() for k in ("hintergrund", "text")}
        farben = {k: v for k, v in farben.items() if v}
        if farben:
            b["farben"] = farben
    elif art == "material":
        b["videos"] = _liste(form.get("videos"))
    elif art == "kurzfassung":
        b["video"] = str(form.get("video") or "").strip()
    return art, titel, b


def eigene_firma() -> str:
    return os.environ.get("MARKETING_MANDANT", "").strip()


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def csrf() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def zeile(a: dict, m: str) -> str:
        aid = str(a.get("id") or "")
        aid_url = e(urllib.parse.quote(aid, safe=""))
        status = str(a.get("status") or "")
        briefing = a.get("briefing") if isinstance(a.get("briefing"), dict) else {}
        protokoll = a.get("protokoll") if isinstance(a.get("protokoll"), list) else []
        notizen = "".join(f"<li>{e(str(p.get('text') or ''))}</li>" for p in protokoll[-4:] if isinstance(p, dict))
        teile = [f'<p><small>{e(str(briefing.get("thema") or ""))}</small></p>']
        if notizen:
            teile.append(f"<ul>{notizen}</ul>")
        if a.get("befund"):
            teile.append(f"<p><small>{e(str(a['befund']))}</small></p>")
        datei = str(a.get("datei") or "")
        if status == "fertig" and _DATEI.fullmatch(datei):
            quelle = f"/medien/datei/{e(urllib.parse.quote(datei, safe=''))}"
            mb = f'{(a.get("bytes") or 0) / 1_000_000:.1f}'.replace(".", ",")
            teile.append(f'<video controls preload="metadata" width="270" src="{quelle}"></video>'
                         f'<p><small>{e(datei)} · {e(str(a.get("dauer_s") or "?"))} s · {mb} MB</small></p>')
            if m == eigene_firma():
                vorschlag = str(briefing.get("sprechertext") or briefing.get("thema") or "")
                teile.append(
                    f'<form method="post" action="/marketing/reels/post" class="aktion">{csrf()}'
                    f'<input type="hidden" name="datei" value="{e(datei)}">'
                    f'<input type="hidden" name="thema" value="{e(str(a.get("titel") or ""))}">'
                    f'<label>Text zum Post <textarea name="text" rows="3" maxlength="{POST_TEXT_MAX}">'
                    f'{e(vorschlag)}</textarea></label>'
                    '<button type="submit">Als LinkedIn-Post vorbereiten</button></form>'
                    '<p><small>Legt einen Entwurf in die Freigaben - gepostet wird erst nach deiner Freigabe.</small></p>')
            else:
                teile.append("<p><small>Posten kann nur der Laden dieser Firma.</small></p>")
        if status in ("offen", "in_arbeit"):
            teile.append(f'<form method="post" action="/marketing/reels/{aid_url}/abbrechen" class="aktion">'
                         f'{csrf()}<button type="submit">Abbrechen</button></form>')
        return (f'<tr><td><b>{e(str(a.get("titel") or ""))}</b><br><small>{e(str(a.get("erstellt_am") or "")[:16])}'
                f' · {e(ARTEN.get(str(a.get("art")), str(a.get("art") or "")))}'
                f' · {"Agent" if a.get("angelegt_von") == "agent" else "Betreiber"}</small></td>'
                f'<td>{e(STATUS.get(status, status))}</td><td>{"".join(teile)}</td></tr>')

    @ui._gesichert_seite
    async def reels(request):
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/video?{urllib.parse.urlencode({'mandant': m})}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        auftraege = [a for a in (d.get("auftraege") if isinstance(d, dict) else None) or [] if isinstance(a, dict)]
        zeilen = "".join(zeile(a, m) for a in auftraege) or '<tr><td colspan="3">Noch keine Reels.</td></tr>'
        arten = "".join(f'<option value="{k}">{e(t)}</option>' for k, t in ARTEN.items())
        formular = (
            f'<h2>Neues Reel</h2><form method="post" action="/marketing/reels/neu" class="aktion">{csrf()}'
            f'<label>Art <select name="art">{arten}</select></label>'
            '<label>Titel <input type="text" name="titel" required maxlength="120"></label>'
            '<label>Thema <input type="text" name="thema" required maxlength="300"></label>'
            '<label>Sprechertext <textarea name="sprechertext" rows="4" maxlength="900"></textarea></label>'
            '<label>Einstieg (eine Zeile) <input type="text" name="hook" maxlength="120"></label>'
            '<label>Länge in Sekunden <input type="number" name="dauer_s" min="15" max="60" value="30"></label>'
            '<label>Stimme <input type="text" name="stimme" value="standard" maxlength="40"></label>'
            '<fieldset><legend>Aus Bildern</legend>'
            '<label>Bilder (Dateinamen aus den <a href="/medien">Medien</a>, mit Komma getrennt) '
            '<input type="text" name="bilder"></label>'
            '<label>Logo <input type="text" name="logo"></label>'
            '<label>Hintergrundfarbe <input type="text" name="farbe_hintergrund" placeholder="#0f2422" maxlength="7"></label>'
            '<label>Textfarbe <input type="text" name="farbe_text" placeholder="#e9fbf6" maxlength="7"></label>'
            '</fieldset><fieldset><legend>Aus Videomaterial / Kurzfassung</legend>'
            '<label>Laura-Videos (IDs, leer = passende suchen) <input type="text" name="videos"></label>'
            '<label>Langes Video für die Kurzfassung (ID) <input type="text" name="video"></label>'
            '</fieldset><button type="submit">Reel bestellen</button></form>'
            '<p><small>Gebaut wird am PC mit Laura, das dauert einige Minuten. Das Reel bekommt Untertitel '
            'und den Hinweis „Stimme: KI“. Versendet wird nichts ohne deine Freigabe.</small></p>')
        return ui._seite("Reels", marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, "/marketing/reels")
                         + "<table><tr><th>Reel</th><th>Status</th><th></th></tr>" + zeilen + "</table>"
                         + formular, refresh=30 if any(a.get("status") in ("offen", "in_arbeit")
                                                         for a in auftraege) else None)

    @ui._gesichert_seite
    async def neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        art, titel, briefing = briefing_aus_formular(form)
        if art not in ARTEN or not titel or not briefing["thema"]:
            return ui._fehlerseite(422, "Nicht möglich", "Art, Titel und Thema sind nötig.")
        try:
            m, _ = await marketing_mandant.firma(request)
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/video",
                                    {"mandant": m, "art": art, "titel": titel, "briefing": briefing})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/reels", status_code=303)

    @ui._gesichert_seite
    async def abbrechen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        aid = urllib.parse.quote(request.path_params["aid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/abbrechen", {})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/reels", status_code=303)

    @ui._gesichert_seite
    async def post_vorbereiten(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        datei = str(form.get("datei") or "")
        thema = str(form.get("thema") or "").strip()
        text = str(form.get("text") or "").strip()
        if not _DATEI.fullmatch(datei) or not thema or not text or len(text) > POST_TEXT_MAX:
            return ui._fehlerseite(422, "Nicht möglich", "Reel-Datei, Thema und Text (bis 3000 Zeichen) sind nötig.")
        firma = eigene_firma()
        if not firma:
            return ui._fehlerseite(422, "Nicht möglich", "Dieser Laden ist keiner Marketing-Firma zugeordnet.")
        try:
            m, _ = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/video?{urllib.parse.urlencode({'mandant': firma})}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        eigene = {str(a.get("datei")) for a in (d.get("auftraege") or []) if isinstance(a, dict)
                  and a.get("status") == "fertig"}
        if m != firma or datei not in eigene:
            return ui._fehlerseite(422, "Nicht möglich", "Dieses Reel gehört nicht zur Firma dieses Ladens.")
        ergebnis = json.loads(await run_in_threadpool(ui.server.post_entwurf_erstellen, thema, text, datei))
        if ergebnis.get("fehler"):
            return ui._fehlerseite(422, "Nicht möglich", e(str(ergebnis["fehler"])))
        return RedirectResponse("/freigaben", status_code=303)

    return [
        Route("/marketing/reels", reels),
        Route("/marketing/reels/neu", neu, methods=["POST"]),
        Route("/marketing/reels/post", post_vorbereiten, methods=["POST"]),
        Route("/marketing/reels/{aid}/abbrechen", abbrechen, methods=["POST"]),
    ]
