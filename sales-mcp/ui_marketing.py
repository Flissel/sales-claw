"""Seiten des Marketing-Pults (Spec 2026-09-29-marketing-pult-design.md
§3.1, Stufe 1): Uebersicht, Entwuerfe, Entwurf. Alle Daten kommen ueber
marketing_pult; diese Datei kennt keine Marketing-Tabelle.

Wie der Rest von sales-ui: kein JavaScript (die Seiten-CSP sagt
`default-src 'none'`). Die Wahl Mail/Handy ist deshalb ein normaler Verweis,
der die Seite mit `format=` neu laedt; das PDF wird verlinkt, nicht
eingebettet (wie auf der Medienseite)."""
from __future__ import annotations

import urllib.parse

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_pult

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
STATUS = {"entwurf": "Zur Freigabe", "freigegeben": "Freigegeben", "abgelehnt": "Abgelehnt"}
# Was im Rahmen gezeigt wird; das PDF bekommt einen Verweis (s. oben).
RAHMEN_FORMATE = {"mail": "Mail", "handy": "Handy"}

# Die Vorschau ist fremdes, gerendertes HTML: `sandbox` nimmt ihm Skripte,
# Formulare und die eigene Herkunft. `frame-ancestors 'self'` erlaubt genau
# den eigenen Entwurfsrahmen (die Seiten-CSP sagt sonst 'none').
_CSP_VORSCHAU = ("sandbox; default-src 'none'; img-src data:; "
                 "style-src 'unsafe-inline'; frame-ancestors 'self'")


def _fassung_zahl(roh) -> int | None:
    try:
        n = int(str(roh))
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schluessel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht moeglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales laeuft normal weiter.")

    def von(request) -> str:
        return ui._ui_akteur(request)

    @ui._gesichert_seite
    async def uebersicht(request):
        try:
            d = marketing_pult.anfrage("GET", "/uebersicht?mandant=vibemind")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        mandanten = "".join(
            f'<span class="mandant{"" if m["aktiv"] else " aus"}">{e(m["name"])}'
            f'{"" if m["aktiv"] else " &middot; kommt"}</span>' for m in d["mandanten"])
        z = d["zaehler"]
        karten = "".join(
            f'<a class="kachel" href="/marketing/entwuerfe?status={k}"><b>{int(z.get(k, 0))}</b>'
            f'<span>{e(t)}</span></a>' for k, t in STATUS.items())
        return ui._seite("Marketing", f'<div class="mandanten">{mandanten}</div>'
                                      f'<div class="kacheln">{karten}</div>')

    @ui._gesichert_seite
    async def entwuerfe(request):
        art = request.query_params.get("art", "")
        status = request.query_params.get("status", "")
        q = urllib.parse.urlencode({k: v for k, v in (("mandant", "vibemind"), ("art", art), ("status", status)) if v})
        try:
            d = marketing_pult.anfrage("GET", f"/inhalte?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        filter_ = "".join(
            f'<a class="{"aktiv" if art == k else ""}" href="/marketing/entwuerfe?art={k}">{e(t)}</a>'
            for k, t in (("", "Alle"), *ARTEN.items()))
        zeilen = "".join(
            f'<tr><td><a href="/marketing/entwurf/{e(i["id"])}">{e(i["titel"])}</a></td>'
            f'<td>{e(ARTEN.get(i["art"], i["art"]))}</td><td>{e(STATUS.get(i["status"], i["status"]))}</td>'
            f'<td>{e(i["layout"] or "")}</td><td>{int(i["fassungen"])}</td><td>{e(str(i["erstellt_am"])[:10])}</td></tr>'
            for i in d["inhalte"]) or '<tr><td colspan="6">Keine Entwuerfe.</td></tr>'
        return ui._seite("Entwürfe", f'<div class="filter">{filter_}</div>'
                         '<table><tr><th>Titel</th><th>Art</th><th>Status</th><th>Layout</th>'
                         f'<th>Fassungen</th><th>Datum</th></tr>{zeilen}</table>')

    @ui._gesichert_seite
    async def entwurf(request):
        iid = request.path_params["iid"]
        try:
            d = marketing_pult.anfrage("GET", f"/inhalte/{urllib.parse.quote(iid)}")
            lay = marketing_pult.anfrage("GET", "/layouts?mandant=vibemind")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        i, fassungen = d["inhalt"], d["fassungen"]
        if not fassungen:
            return ui._fehlerseite(422, "Nicht moeglich", "Dieser Inhalt hat noch keine Fassung.")
        neueste = int(fassungen[0]["fassung"])
        wahl = _fassung_zahl(request.query_params.get("fassung")) or neueste
        akt = next((f for f in fassungen if int(f["fassung"]) == wahl), fassungen[0])
        nr = int(akt["fassung"])
        ist_neueste = nr == neueste
        fmt = request.query_params.get("format", "mail")
        if fmt not in RAHMEN_FORMATE:
            fmt = "mail"
        fe = akt["felder"] or {}
        abschnitte = "".join(
            f'<fieldset><input name="abschnitt_titel" value="{e(a.get("titel"))}" placeholder="Ueberschrift">'
            f'<textarea name="abschnitt_text" rows="6">{e(a.get("text"))}</textarea></fieldset>'
            for a in fe.get("abschnitte") or [{"titel": "", "text": ""}])
        layouts = "".join(
            f'<option value="{e(l["name"])}"{" selected" if l["name"] == akt["layout"] else ""}>{e(l["name"])}</option>'
            for l in lay["layouts"])
        verlauf = "".join(
            f'<li><a href="?fassung={int(f["fassung"])}">Fassung {int(f["fassung"])}</a> '
            f'&middot; {"Agent" if f["urheber"] == "agent" else "du"} &middot; {e(str(f["erstellt_am"])[:16])}</li>'
            for f in fassungen)
        offen = i["status"] == "entwurf"
        csrf = f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
        basis = f"/marketing/entwurf/{e(i['id'])}"
        betreff = "Betreff" if i["art"] == "newsletter" else "Betreff (optional)"
        hinweis = "" if ist_neueste else (
            f'<div class="warnung">Das ist nicht die neueste Fassung (Fassung {nr} von {neueste}). '
            f'Freigeben geht nur für die <a href="{basis}?fassung={neueste}">neueste Fassung</a>; '
            f'Speichern legt aus dieser eine neue an.</div>')
        # Freigeben/Ablehnen nennen die Fassung, die hier zu sehen ist - die
        # DB lehnt ab, wenn inzwischen eine neuere existiert.
        fassung_feld = f'<input type="hidden" name="fassung" value="{nr}">'
        entscheiden = (
            f'<div class="aktionen">'
            f'<form method="post" action="{basis}/entscheiden" class="aktion">{csrf}{fassung_feld}'
            f'<input type="hidden" name="urteil" value="freigeben">'
            f'<button class="primaer" type="submit">Freigeben (ablegen)</button></form>'
            f'<form method="post" action="{basis}/entscheiden" class="aktion gefahr">{csrf}{fassung_feld}'
            f'<input type="hidden" name="urteil" value="ablehnen">'
            f'<input type="text" name="grund" placeholder="Grund">'
            f'<button type="submit">Ablehnen</button></form></div>') if ist_neueste else ""
        formular = (
            f'<form method="post" action="{basis}/speichern" class="pult-felder">{csrf}'
            f'<label>{betreff} <input name="betreff" value="{e(fe.get("betreff"))}"></label>'
            f'<label>Vorschautext <input name="vorschautext" value="{e(fe.get("vorschautext"))}"></label>'
            f'{abschnitte}'
            f'<label>Knopf-Text <input name="knopf_text" value="{e(fe.get("knopf_text"))}"></label>'
            f'<label>Knopf-Link <input name="knopf_link" value="{e(fe.get("knopf_link"))}"></label>'
            f'<label>Layout <select name="layout">{layouts}</select></label>'
            f'<button type="submit">Als neue Fassung speichern</button></form>'
            f'{entscheiden}') if offen else (
            f'<p>{e(STATUS.get(i["status"], i["status"]))}.</p>')
        wahl_links = "".join(
            f'<a class="{"aktiv" if k == fmt else ""}" href="{basis}?fassung={nr}&amp;format={k}">{t}</a>'
            for k, t in RAHMEN_FORMATE.items())
        wahl_links += (f'<a href="{basis}/vorschau?fassung={nr}&amp;format=pdf" target="_blank" '
                       f'rel="noopener noreferrer">PDF &#8599;</a>')
        rumpf = (
            f'<p class="meta">{e(ARTEN.get(i["art"], i["art"]))} &middot; '
            f'{e(STATUS.get(i["status"], i["status"]))} &middot; Fassung {nr}</p>{hinweis}'
            f'<div class="pult"><div class="pult-links">{formular}<h2>Fassungen</h2><ul>{verlauf}</ul></div>'
            f'<div class="pult-rechts"><div class="vorschau-wahl">{wahl_links}</div>'
            f'<iframe class="vorschau {fmt}" sandbox title="Vorschau" '
            f'src="{basis}/vorschau?fassung={nr}&amp;format={fmt}"></iframe>'
            f'</div></div>')
        antwort = ui._seite(i["titel"], rumpf)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

    @ui._gesichert_seite
    async def vorschau(request):
        iid = urllib.parse.quote(request.path_params["iid"])
        fassung = _fassung_zahl(request.query_params.get("fassung", "1"))
        fmt = request.query_params.get("format", "mail")
        if fassung is None or fmt not in ("mail", "handy", "pdf"):
            return ui._fehlerseite(400, "Ungueltige Vorschau", "Fassung oder Format fehlt.")
        q = urllib.parse.urlencode({"fassung": fassung, "format": fmt})
        try:
            inhalt, typ = marketing_pult.anfrage("GET", f"/inhalte/{iid}/vorschau?{q}", roh=True)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if str(typ).startswith("application/pdf"):
            # Wie die Medienseite: eigene Datei-Richtlinie, verlinkt statt gerahmt.
            return Response(inhalt, media_type="application/pdf",
                            headers={"Content-Security-Policy": ui._CSP_DATEI,
                                     "Content-Disposition": 'inline; filename="vorschau.pdf"',
                                     "Cache-Control": "private, no-store"})
        return Response(inhalt, media_type=typ,
                        headers={"Content-Security-Policy": _CSP_VORSCHAU,
                                 "X-Frame-Options": "SAMEORIGIN",
                                 "Cache-Control": "private, no-store"})

    @ui._gesichert_seite
    async def speichern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        titel, texte = form.getlist("abschnitt_titel"), form.getlist("abschnitt_text")
        felder = {
            "betreff": str(form.get("betreff") or "").strip(),
            "vorschautext": str(form.get("vorschautext") or "").strip(),
            "abschnitte": [{"titel": str(t).strip(), "text": str(x).strip()}
                           for t, x in zip(titel, texte) if str(t).strip() or str(x).strip()],
            "knopf_text": str(form.get("knopf_text") or "").strip(),
            "knopf_link": str(form.get("knopf_link") or "").strip(),
        }
        iid = urllib.parse.quote(request.path_params["iid"])
        try:
            r = marketing_pult.anfrage("POST", f"/inhalte/{iid}/fassungen",
                                       {"felder": felder, "layout": str(form.get("layout") or ""), "von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}?fassung={int(r['fassung'])}", status_code=303)

    @ui._gesichert_seite
    async def entscheiden(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        fassung = _fassung_zahl(form.get("fassung"))
        if fassung is None:
            return ui._fehlerseite(400, "Abgewiesen",
                                   "Welche Fassung gemeint ist, fehlt. Nichts wurde entschieden - "
                                   "Seite neu laden und erneut.")
        iid = urllib.parse.quote(request.path_params["iid"])
        try:
            marketing_pult.anfrage("POST", f"/inhalte/{iid}/entscheiden",
                                   {"fassung": fassung, "urteil": str(form.get("urteil") or ""),
                                    "von": von(request), "grund": str(form.get("grund") or "").strip()})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}", status_code=303)

    return [
        Route("/marketing", uebersicht),
        Route("/marketing/entwuerfe", entwuerfe),
        Route("/marketing/entwurf/{iid}", entwurf),
        Route("/marketing/entwurf/{iid}/vorschau", vorschau),
        Route("/marketing/entwurf/{iid}/speichern", speichern, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/entscheiden", entscheiden, methods=["POST"]),
    ]
