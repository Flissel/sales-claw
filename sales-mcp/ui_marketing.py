"""Seiten des Marketing-Pults (Spec 2026-09-29-marketing-pult-design.md
§3.1, Stufe 1): Uebersicht, Entwuerfe, Entwurf. Alle Daten kommen ueber
marketing_pult; diese Datei kennt keine Marketing-Tabelle.

Wie der Rest von sales-ui: kein JavaScript (die Seiten-CSP sagt
`default-src 'none'`). Die Wahl Mail/Handy ist deshalb ein normaler Verweis,
der die Seite mit `format=` neu laedt; das PDF wird verlinkt, nicht
eingebettet (wie auf der Medienseite).

Layouts (Task 5): Galerie und Editor. Die Vorschau der Regler ist ein
zweiter Absende-Knopf im Reglerformular (`formaction` auf
/marketing/layout-vorschau, `formtarget` = der Vorschau-Rahmen) - ohne
Skript, also nicht bei jedem Tastendruck, sondern per Klick."""
from __future__ import annotations

import base64
import html as _html
import math
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import ui_editor

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
STATUS = {"entwurf": "Zur Freigabe", "freigegeben": "Freigegeben", "abgelehnt": "Abgelehnt"}
def _messung_html(messung):
    """Messung je Platz als Themen-Aehnlichkeit (CLIP-Kosinus des alten zum neuen Bild)."""
    teile = []
    if isinstance(messung, dict):
        for platz, m in messung.items():
            w = m.get("aehnlich_original") if isinstance(m, dict) else None
            if isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w):
                teile.append(f" &middot; {_html.escape(str(platz))}: {round(w * 100)} % Themen-Ähnlichkeit")
    return "".join(teile)


# Bild-Auftraege (Marketing-API: marketing.bildauftraege.status).
BILD_STATUS = {"offen": "wartet (PC muss laufen)", "in_arbeit": "wird erzeugt", "fertig": "fertig",
               "fehler": "fehlgeschlagen", "verworfen": "verworfen"}
# Was im Rahmen gezeigt wird; das PDF bekommt einen Verweis (s. oben).
RAHMEN_FORMATE = {"mail": "Mail", "handy": "Handy"}

# Die Vorschau ist fremdes, gerendertes HTML: `sandbox` nimmt ihm Skripte,
# Formulare und die eigene Herkunft. `frame-ancestors 'self'` erlaubt genau
# den eigenen Entwurfsrahmen (die Seiten-CSP sagt sonst 'none').
# `img-src 'self'` (Newsletter-Editor, 29.09.2026): Bilder der Editor-
# Newsletter kommen ueber die signierten Adressen /marketing/bild/...
# (ui_editor.bild_basis) - weiter nichts von fremden Adressen.
_CSP_VORSCHAU = ("sandbox; default-src 'none'; img-src 'self' data:; "
                 "font-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'")


# Layout-Regler (Task 5). Die Farben kommen aus `type="color"`-Feldern, die
# Pruefung der Werte macht die DB (`pult_gestalt_fehler`) - hier wird nur
# gelesen, was eine Zahl oder Datei sein muss.
FARBEN = ("grund", "text", "akzent", "flaeche", "text_hell", "text_leise", "gold", "handlung_text")
FARB_NAMEN = {"grund": "Grund", "text": "Text", "akzent": "Akzent", "flaeche": "Fläche",
              "text_hell": "Text hell", "text_leise": "Text leise", "gold": "Hervorhebung",
              "handlung_text": "Knopf-Text"}
SCHRIFTEN = (("system", "Klar"), ("serif", "Klassisch"), ("mono", "Technisch"))
ABSTAENDE = (("eng", "eng"), ("mittel", "mittel"), ("weit", "weit"))
LOGO_MAX = 150 * 1024
LOGO_STUECK = 64 * 1024


def _gerahmt(inhalt, typ: str = "text/html; charset=utf-8", status: int = 200) -> Response:
    """Antwort, die in einen eigenen, gesandboxten Rahmen gehoert: dieselben
    Koepfe wie die Entwurfs-Vorschau (_CSP_VORSCHAU + SAMEORIGIN). Auch
    Fehler gehen so hinaus - mit den Seiten-Koepfen (DENY) bliebe der Rahmen
    leer und niemand saehe den Grund."""
    return Response(inhalt, status_code=status, media_type=typ,
                    headers={"Content-Security-Policy": _CSP_VORSCHAU,
                             "X-Frame-Options": "SAMEORIGIN",
                             "Cache-Control": "private, no-store"})


# Auswahlwert "nur leere Bildplaetze": sendet platz None + nur_leere True. Editor-Block-IDs
# beginnen nie mit "__", eine Kollision mit einem echten Platz ist daher nicht zu erwarten.
NUR_LEERE = "__leere__"


def _bildplaetze(bloecke) -> list[tuple[str, str]]:
    """(id, alt) je Bildplatz (Image mit Breite und Hoehe) - wie
    bildplaetze.finde in der Marketing-API, hier nur fuer die Auswahl."""
    if not isinstance(bloecke, dict):
        return []
    aus = []
    for bid, b in bloecke.items():
        p = ((b or {}).get("data") or {}).get("props") or {}
        if (b or {}).get("type") == "Image" and isinstance(p.get("width"), (int, float)) and p.get("width", 0) > 0 \
                and isinstance(p.get("height"), (int, float)) and p.get("height", 0) > 0:
            aus.append((str(bid), str(p.get("alt") or bid)))
    return aus


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
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def von(request) -> str:
        return ui._ui_akteur(request)

    def umschalter(m: str, liste: list[dict], zurueck: str) -> str:
        return marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, zurueck)

    @ui._gesichert_seite
    async def mandant_waehlen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        wahl = str(form.get("mandant") or "")
        try:
            liste = await run_in_threadpool(marketing_mandant.mandanten)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not any(m.get("id") == wahl and m.get("aktiv") for m in liste):
            return ui._fehlerseite(422, "Nicht möglich", "Diese Firma gibt es nicht oder sie ist nicht aktiv.")
        zurueck = str(form.get("zurueck") or "")
        antwort = RedirectResponse(zurueck if marketing_mandant.ziel_ok(zurueck) else "/marketing",
                                   status_code=303)
        antwort.set_cookie(marketing_mandant.COOKIE, wahl, max_age=365 * 24 * 3600,
                           httponly=True, samesite="lax", path="/marketing")
        return antwort

    @ui._gesichert_seite
    async def uebersicht(request):
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/uebersicht?mandant={urllib.parse.quote(m)}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        z = d["zaehler"]
        karten = "".join(
            f'<a class="kachel" href="/marketing/entwuerfe?status={k}"><b>{int(z.get(k, 0))}</b>'
            f'<span>{e(t)}</span></a>' for k, t in STATUS.items())
        return ui._seite("Marketing", umschalter(m, liste, "/marketing") +
                                      f'<div class="kacheln">{karten}</div>'
                                      '<p><a class="knopf" href="/marketing/vorlagen">'
                                      'Neuer Newsletter aus Vorlage</a></p>')

    @ui._gesichert_seite
    async def entwuerfe(request):
        art = request.query_params.get("art", "")
        if art not in ARTEN:
            art = ""
        # Ohne Angabe zeigt die Liste, was auf ein Urteil wartet; "alle" hebt
        # den Status-Filter auf.
        status = request.query_params.get("status", "") or "entwurf"
        if status not in STATUS and status != "alle":
            status = "entwurf"
        api_status = "" if status == "alle" else status
        try:
            m, liste = await marketing_mandant.firma(request)
            q = urllib.parse.urlencode({k: v for k, v in (("mandant", m), ("art", art), ("status", api_status)) if v})
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)

        def verweis(a: str, st: str) -> str:
            return "/marketing/entwuerfe?" + e(urllib.parse.urlencode(
                [(k, v) for k, v in (("art", a), ("status", st)) if v]))

        # Art-Verweise behalten den Status, Status-Verweise die Art.
        filter_ = "".join(
            f'<a class="{"aktiv" if art == k else ""}" href="{verweis(k, status)}">{e(t)}</a>'
            for k, t in (("", "Alle"), *ARTEN.items()))
        filter_status = "".join(
            f'<a class="{"aktiv" if status == k else ""}" href="{verweis(art, k)}">{e(t)}</a>'
            for k, t in (*STATUS.items(), ("alle", "Alle")))
        zeilen = "".join(
            f'<tr><td><a href="/marketing/entwurf/{e(i["id"])}">{e(i["titel"])}</a></td>'
            f'<td>{e(ARTEN.get(i["art"], i["art"]))}</td><td>{e(STATUS.get(i["status"], i["status"]))}</td>'
            f'<td>{e(i["layout"] or "")}</td><td>{int(i["fassungen"])}</td><td>{e(str(i["erstellt_am"])[:10])}</td></tr>'
            for i in d["inhalte"]) or '<tr><td colspan="6">Keine Entwürfe.</td></tr>'
        return ui._seite("Entwürfe", umschalter(m, liste, "/marketing/entwuerfe?" + urllib.parse.urlencode(
                                       [(k, v) for k, v in (("art", art), ("status", status)) if v])) +
                         f'<div class="filter">{filter_}</div>'
                         f'<div class="filter">{filter_status}</div>'
                         '<table><tr><th>Titel</th><th>Art</th><th>Status</th><th>Layout</th>'
                         f'<th>Fassungen</th><th>Datum</th></tr>{zeilen}</table>')

    @ui._gesichert_seite
    async def entwurf(request):
        iid = request.path_params["iid"]
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{urllib.parse.quote(iid)}")
            # Die Layouts gehoeren der Firma des INHALTS, nicht der Cookie-Wahl.
            # Ohne Firma kein Rueckfall auf eine andere: Fehlerseite statt 500.
            inhalt = d.get("inhalt") if isinstance(d, dict) else None
            mandant = inhalt.get("mandant") if isinstance(inhalt, dict) else None
            if not isinstance(mandant, str) or not mandant:
                return ui._fehlerseite(422, "Nicht möglich", "Dieser Inhalt gehört zu keiner Firma.")
            lay = await run_in_threadpool(
                marketing_pult.anfrage, "GET", f"/layouts?mandant={urllib.parse.quote(mandant)}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        i, fassungen = d["inhalt"], d["fassungen"]
        if not fassungen:
            return ui._fehlerseite(422, "Nicht möglich", "Dieser Inhalt hat noch keine Fassung.")
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
            f'<fieldset><input name="abschnitt_titel" value="{e(a.get("titel"))}" placeholder="Überschrift">'
            f'<textarea name="abschnitt_text" rows="6">{e(a.get("text"))}</textarea></fieldset>'
            for a in fe.get("abschnitte") or [{"titel": "", "text": ""}])
        # Das Layout der gezeigten Fassung ist immer vorgewaehlt; steht es
        # nicht mehr in der Liste, wird es eigens angeboten - sonst waere
        # still ein anderes gewaehlt und Speichern wechselte das Layout.
        akt_layout = str(akt.get("layout") or "")
        namen = [str(l.get("name") or "") for l in lay.get("layouts") or []]
        layouts = "".join(
            f'<option value="{e(n)}"{" selected" if n == akt_layout else ""}>{e(n)}</option>'
            for n in namen)
        if akt_layout and akt_layout not in namen:
            layouts = (f'<option value="{e(akt_layout)}" selected>'
                       f'{e(akt_layout)} (nicht mehr in der Liste)</option>') + layouts
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
        # Die Bruecke spiegelt nur alt -> Pult: ein Urteil hier stoppt einen
        # noch offenen Vorschlag im alten Weg (Telegram -> n8n) nicht.
        alter_weg = d.get("alter_weg") or {}
        alter_hinweis = (
            f'<div class="warnung">Dieser Entwurf liegt noch im alten Freigabeweg '
            f'({e(alter_weg.get("kanal") or "")}). Ablehnen hier stoppt ihn dort nicht, und Änderungen '
            f'hier werden dort nicht verschickt. Im alten Weg ablehnen, falls er nicht rausgehen soll.</div>'
        ) if alter_weg.get("status") in ("draft", "pending_approval") else ""
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
        # Editor-Newsletter (format "bloecke"): Inhalt nur im Editor; das
        # Feldformular wuerde die Bloecke nicht kennen (die DB lehnt eine
        # Felder-Fassung darauf ohnehin ab). Urteilen bleibt hier. Massgeblich
        # ist das Format der NEUESTEN Fassung - auch wenn eine aeltere gezeigt
        # wird, denn gespeichert wird immer obendrauf.
        im_editor = fassungen[0].get("format") == "bloecke"
        # Feld-Newsletter (z.B. aus dem alten Weg ueber die Bruecke): einmalig
        # ins Editor-Format uebernehmen (marketing.pult_in_bloecke_uebernehmen).
        in_bloecke = "" if im_editor or i["art"] != "newsletter" else (
            f'<form method="post" action="{basis}/in-bloecke" class="aktion">{csrf}'
            f'<button type="submit">Ins Editor-Format übernehmen</button>'
            f'<span class="meta">Legt eine neue Fassung im Editor-Format an; danach wird dieser '
            f'Newsletter nur noch im Editor bearbeitet.</span></form>')
        felder_formular = (
            f'<p>Dieser Newsletter wird im Editor bearbeitet.</p>'
            f'<p><a class="knopf" href="/marketing/editor/{e(i["id"])}">Im Editor öffnen</a></p>'
        ) if im_editor else in_bloecke + (
            f'<form method="post" action="{basis}/speichern" class="pult-felder">{csrf}'
            f'<label>{betreff} <input name="betreff" value="{e(fe.get("betreff"))}"></label>'
            f'<label>Vorschautext <input name="vorschautext" value="{e(fe.get("vorschautext"))}"></label>'
            f'{abschnitte}'
            f'<label>Knopf-Text <input name="knopf_text" value="{e(fe.get("knopf_text"))}"></label>'
            f'<label>Knopf-Link <input name="knopf_link" value="{e(fe.get("knopf_link"))}"></label>'
            f'<label>Layout <select name="layout">{layouts}</select></label>'
            f'<button type="submit">Als neue Fassung speichern</button></form>')
        formular = f'{felder_formular}{entscheiden}' if offen else (
            f'<p>{e(STATUS.get(i["status"], i["status"]))}.</p>')
        bilder_html = ""
        neu_laden = False
        if im_editor and offen:
            try:
                stand = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                                f"/inhalte/{urllib.parse.quote(iid)}/bilder")
                auftraege = stand.get("auftraege") or []
                neu_laden = any(a.get("status") in ("offen", "in_arbeit") for a in auftraege)
                zeilen_b = "".join(
                    f'<li>{e(a.get("platz") or ("alle leeren" if a.get("nur_leere") else "alle"))} &middot; '
                    f'{e("wird überarbeitet" if a.get("status") == "in_arbeit" and a.get("modus") == "ueberarbeiten" else BILD_STATUS.get(a.get("status"), a.get("status") or ""))}'
                    f'{_messung_html(a.get("messung"))}'
                    f'{(" &middot; " + e(a.get("befund"))) if a.get("befund") else ""}'
                    f'{(" &middot; Hinweis: " + e(a.get("hinweis"))) if a.get("hinweis") else ""}</li>'
                    for a in auftraege[:10]) or "<li>Noch keine Bild-Aufträge.</li>"
            except marketing_pult.PultFehler:
                zeilen_b = "<li>Bildstand gerade nicht abrufbar.</li>"
            optionen = ('<option value="">alle Bildplätze (auch belegte)</option>'
                        f'<option value="{NUR_LEERE}">nur leere Bildplätze</option>') + "".join(
                f'<option value="{e(bid)}">{e(alt)}</option>' for bid, alt in _bildplaetze(fassungen[0].get("bloecke")))
            bilder_html = (
                f'<h2>Bilder</h2><ul>{zeilen_b}</ul>'
                f'<form method="post" action="{basis}/bilder" class="aktion">{csrf}'
                f'<label>Platz <select name="platz">{optionen}</select></label>'
                f'<label>Hinweis <input name="hinweis" maxlength="500" placeholder="z. B. wärmer, mehr Menschen"></label>'
                f'<label>Stärke <select name="staerke">'
                f'<option value="35" selected>nah am Original</option><option value="75">freier</option>'
                f'<option value="100">ganz neu</option></select></label>'
                f'<button type="submit">Bild überarbeiten</button>'
                f'<span class="meta">Erzeugt wird am PC, sobald er läuft. Das Ergebnis ist eine neue Fassung.</span></form>')
        wahl_links = "".join(
            f'<a class="{"aktiv" if k == fmt else ""}" href="{basis}?fassung={nr}&amp;format={k}">{t}</a>'
            for k, t in RAHMEN_FORMATE.items())
        if akt.get("format") != "bloecke":
            # Fuer Editor-Fassungen gibt es (noch) kein PDF - die API sagt 422.
            wahl_links += (f'<a href="{basis}/vorschau?fassung={nr}&amp;format=pdf" target="_blank" '
                           f'rel="noopener noreferrer">PDF &#8599;</a>')
        rumpf = (
            f'<p class="meta">{e(ARTEN.get(i["art"], i["art"]))} &middot; '
            f'{e(STATUS.get(i["status"], i["status"]))} &middot; Fassung {nr}</p>{hinweis}{alter_hinweis}'
            f'<div class="pult"><div class="pult-links">{formular}{bilder_html}<h2>Fassungen</h2><ul>{verlauf}</ul></div>'
            f'<div class="pult-rechts"><div class="vorschau-wahl">{wahl_links}</div>'
            f'<iframe class="vorschau {fmt}" sandbox title="Vorschau" '
            f'src="{basis}/vorschau?fassung={nr}&amp;format={fmt}"></iframe>'
            f'</div></div>')
        antwort = ui._seite(i["titel"], rumpf, refresh=20 if neu_laden else None)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

    @ui._gesichert_seite
    async def bilder(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        iid = request.path_params["iid"]
        platz = str(form.get("platz") or "").strip() or None
        nur_leere = platz == NUR_LEERE
        if nur_leere:
            platz = None
        hinweis = str(form.get("hinweis") or "").strip()
        roh_staerke = str(form.get("staerke") or "").strip()
        if not roh_staerke:
            staerke = 55
        elif roh_staerke.isascii() and roh_staerke.isdigit() and int(roh_staerke) <= 100:
            staerke = int(roh_staerke)
        else:
            return ui._fehlerseite(422, "Nicht möglich", "Die Stärke muss 0 bis 100 sein.")
        if platz is not None and not ui_editor.PLATZ_ID.match(platz):
            return ui._fehlerseite(422, "Nicht möglich", "Unbekannter Bildplatz.")
        if len(hinweis) > ui_editor.HINWEIS_MAX:
            return ui._fehlerseite(422, "Nicht möglich", "Der Hinweis ist zu lang.")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{urllib.parse.quote(iid)}/bilder",
                                    {"platz": platz, "hinweis": hinweis, "nur_leere": nur_leere,
                                     "staerke": staerke, "modus": "neu" if staerke == 100 else "ueberarbeiten"})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{urllib.parse.quote(iid)}", status_code=303)

    @ui._gesichert_seite
    async def vorschau(request):
        iid = urllib.parse.quote(request.path_params["iid"])
        fassung = _fassung_zahl(request.query_params.get("fassung", "1"))
        fmt = request.query_params.get("format", "mail")
        if fassung is None or fmt not in ("mail", "handy", "pdf"):
            return ui._fehlerseite(400, "Ungültige Vorschau", "Fassung oder Format fehlt.")
        q_teile = {"fassung": fassung, "format": fmt}
        # Bilder der Editor-Newsletter: signierte Adresse, weil der
        # abgeschottete Rahmen keine Anmelde-Cookies schickt. Leer (kein
        # Geheimnis, kein https) -> weglassen, die API zeigt Platzhalter.
        if (bild_basis := ui_editor.bild_basis()):
            q_teile["bild_basis"] = bild_basis
        q = urllib.parse.urlencode(q_teile)
        try:
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "GET", f"/inhalte/{iid}/vorschau?{q}", roh=True)
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
            r = await run_in_threadpool(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/fassungen",
                {"felder": felder, "layout": str(form.get("layout") or ""), "von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}?fassung={int(r['fassung'])}", status_code=303)

    @ui._gesichert_seite
    async def in_bloecke(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/in_bloecke",
                                    {"von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/editor/{iid}", status_code=303)

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
            await run_in_threadpool(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/entscheiden",
                {"fassung": fassung, "urteil": str(form.get("urteil") or ""),
                 "von": von(request), "grund": str(form.get("grund") or "").strip()})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}", status_code=303)

    # --- Layouts (Task 5) -------------------------------------------------

    def gerahmter_fehler(f: marketing_pult.PultFehler) -> Response:
        """Wie fehler(), aber fuer den Vorschau-Rahmen (s. _gerahmt)."""
        if f.art == "abgelehnt":
            return _gerahmt(f"<p>Vorschau nicht möglich: {e(f.grund)}</p>", status=422)
        if f.art == "nicht_verbunden":
            return _gerahmt("<p>Marketing nicht verbunden.</p>", status=503)
        return _gerahmt("<p>Marketing gerade nicht erreichbar.</p>", status=503)

    async def alle_layouts(m: str) -> list:
        lay = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/layouts?mandant={urllib.parse.quote(m)}")
        return lay.get("layouts") or []

    def layout_von(layouts: list, name: str) -> dict | None:
        return next((l for l in layouts if l.get("name") == name), None)

    def pfad(name: str) -> str:
        return urllib.parse.quote(name, safe="")

    async def regler_lesen(form, bisher: dict | None, logo_lesen: bool = True) -> tuple[dict | None, str]:
        """Liest die Regler aus dem Formular. `bisher` ist die gespeicherte
        Gestalt: ohne neue Datei bleibt deren Logo (ausser „Logo entfernen").
        Die Vorschau liest keine Datei (logo_lesen=False) - ohne Skript kaeme
        sie nicht bei jedem Klick erneut mit."""
        g: dict = {k: str(form.get(k) or "").strip().lower() for k in FARBEN}
        g["schrift"] = str(form.get("schrift") or "system")
        g["abstand"] = str(form.get("abstand") or "mittel")
        try:
            g["rundung"] = int(str(form.get("rundung") or "8"))
        except ValueError:
            return None, "Rundung muss eine Zahl sein."
        for k in ("kopf_text", "fuss_text"):
            if (w := str(form.get(k) or "").strip()):
                g[k] = w
        datei = form.get("logo") if logo_lesen else None
        if getattr(datei, "filename", ""):
            # In Stuecken lesen und abbrechen, sobald die Grenze ueberschritten
            # ist - wie aktion_medien_hochladen in ui.py. Ein riesiger Upload
            # landet so nie ganz im Speicher.
            teile: list[bytes] = []
            gelesen = 0
            while (stueck := await datei.read(LOGO_STUECK)):
                if not teile and not stueck.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
                    return None, "Das Logo muss ein PNG oder JPEG sein."
                gelesen += len(stueck)
                if gelesen > LOGO_MAX:
                    return None, "Das Logo ist größer als 150 KB."
                teile.append(stueck)
            roh = b"".join(teile)
            if roh.startswith(b"\x89PNG\r\n\x1a\n"):
                typ = "png"
            elif roh.startswith(b"\xff\xd8\xff"):
                typ = "jpeg"
            else:
                return None, "Das Logo muss ein PNG oder JPEG sein."
            g["logo"] = f"data:image/{typ};base64," + base64.b64encode(roh).decode("ascii")
        elif bisher and bisher.get("logo") and not form.get("logo_entfernen"):
            g["logo"] = bisher["logo"]
        return g, ""

    @ui._gesichert_seite
    async def layouts(request):
        try:
            m, liste = await marketing_mandant.firma(request)
            alle = await alle_layouts(m)
        except marketing_pult.PultFehler as f:
            return fehler(f)

        def karte(l: dict) -> str:
            n = str(l.get("name") or "")
            standard = '<span class="abzeichen">Standard</span> ' if l.get("standard") else ""
            return (f'<div class="layout-karte"><div class="layout-rahmen">'
                    f'<iframe class="layout-bild" sandbox tabindex="-1" title="Vorschau {e(n)}" '
                    f'src="/marketing/layout-bild/{e(pfad(n))}"></iframe></div>'
                    f'<a href="/marketing/layout/{e(pfad(n))}"><b>{e(n)}</b></a>'
                    f'<span class="meta">{standard}Fassung {int(l.get("fassung") or 1)}'
                    f'{" &middot; " + e(l["beschreibung"]) if l.get("beschreibung") else ""}</span></div>')

        reihenfolge = [*ARTEN, *sorted({str(l.get("inhaltsart") or "") for l in alle} - set(ARTEN))]
        gruppen = []
        for art in reihenfolge:
            teil = [l for l in alle if str(l.get("inhaltsart") or "") == art]
            if not teil:
                continue
            teil.sort(key=lambda l: (not l.get("standard"), str(l.get("name") or "")))
            gruppen.append(f'<h2>{e(ARTEN.get(art, art or "Ohne Art"))}</h2>'
                           f'<div class="galerie">{"".join(karte(l) for l in teil)}</div>')
        antwort = ui._seite("Layouts", umschalter(m, liste, "/marketing/layouts") +
                            ("".join(gruppen) or "<p>Keine Layouts.</p>"))
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

    @ui._gesichert_seite
    async def layout_bild(request):
        try:
            m, _liste = await marketing_mandant.firma(request)
            l = layout_von(await alle_layouts(m), request.path_params["name"])
            if not l:
                return _gerahmt("<p>Unbekanntes Layout.</p>", status=404)
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "POST", "/layouts/vorschau",
                {"gestalt": l.get("gestalt") or {}, "mandant": m, "format": "mail"}, roh=True)
        except marketing_pult.PultFehler as f:
            return gerahmter_fehler(f)
        return _gerahmt(inhalt, typ)

    @ui._gesichert_seite
    async def layout_editor(request):
        name = request.path_params["name"]
        try:
            m, _liste = await marketing_mandant.firma(request)
            l = layout_von(await alle_layouts(m), name)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not l:
            return ui._fehlerseite(404, "Unbekanntes Layout", "")
        g = l.get("gestalt") or {}
        csrf = f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
        basis = f"/marketing/layout/{e(pfad(name))}"

        def auswahl(feld, werte, aktuell):
            return (f'<select name="{feld}">' + "".join(
                f'<option value="{w}"{" selected" if w == aktuell else ""}>{t}</option>'
                for w, t in werte) + "</select>")

        try:
            rundung = int(g.get("rundung", 8))
        except (TypeError, ValueError):
            rundung = 8
        farben = "".join(
            f'<label>{FARB_NAMEN[k]} <input type="color" name="{k}" value="{e(g.get(k) or "#000000")}"></label>'
            for k in FARBEN)
        regler = (
            f'<fieldset class="farben"><legend>Farben</legend>{farben}</fieldset>'
            f'<label>Schrift {auswahl("schrift", SCHRIFTEN, g.get("schrift", "system"))}</label>'
            f'<label>Abstände {auswahl("abstand", ABSTAENDE, g.get("abstand", "mittel"))}</label>'
            f'<label>Rundung (0–24) <input type="range" min="0" max="24" name="rundung" value="{rundung}"></label>'
            f'<label>Kopfzeile <input name="kopf_text" maxlength="120" value="{e(g.get("kopf_text") or "")}"></label>'
            f'<label>Fußzeile <input name="fuss_text" maxlength="300" value="{e(g.get("fuss_text") or "")}"></label>'
            f'<label>Logo (PNG/JPEG, max. 150 KB) <input type="file" name="logo" accept="image/png,image/jpeg"></label>'
            f'<p class="meta">Das Logo erscheint in der Vorschau nach dem Speichern.</p>'
            + ('<label class="haken"><input type="checkbox" name="logo_entfernen" value="1"> Logo entfernen</label>'
               if g.get("logo") else ""))
        formate = "".join(
            f'<label class="haken"><input type="radio" name="format" value="{k}"'
            f'{" checked" if k == "mail" else ""}> {t}</label>' for k, t in RAHMEN_FORMATE.items())
        art = str(l.get("inhaltsart") or "")
        if l.get("standard"):
            standard = f'<p class="meta">Standard für {e(ARTEN.get(art, art or "diese Art"))}.</p>'
        else:
            standard = (f'<form method="post" action="{basis}/standard" class="aktion">{csrf}'
                        f'<button type="submit">Als Standard für {e(ARTEN.get(art, art or "diese Art"))}</button></form>')
        # Der erste Absende-Knopf ist die Vorschau: Enter in einem Textfeld
        # speichert so nichts aus Versehen.
        knoepfe = (
            f'<div class="aktionen">'
            f'<button type="submit" formaction="/marketing/layout-vorschau" formtarget="vorschau" '
            f'formmethod="post" formenctype="multipart/form-data">Vorschau aktualisieren</button>'
            f'<button class="primaer" type="submit">Als neue Fassung speichern</button></div>')
        rumpf = (
            f'<p class="meta">{e(ARTEN.get(art, art))} &middot; Fassung {int(l.get("fassung") or 1)}'
            f'{" &middot; " + e(l["beschreibung"]) if l.get("beschreibung") else ""}</p>'
            f'<div class="pult"><div class="pult-links">'
            f'<form id="regler" method="post" enctype="multipart/form-data" action="{basis}/speichern" '
            f'class="pult-felder">{csrf}<input type="hidden" name="layout" value="{e(name)}">'
            f'{regler}<fieldset class="vorschau-wahl"><legend>Vorschau als</legend>{formate}</fieldset>'
            f'{knoepfe}</form>{standard}'
            f'<p><a href="/marketing/layouts">Zurück zu allen Layouts</a></p></div>'
            f'<div class="pult-rechts">'
            f'<iframe class="vorschau" name="vorschau" sandbox title="Vorschau" '
            f'src="/marketing/layout-bild/{e(pfad(name))}"></iframe></div></div>')
        antwort = ui._seite(f"Layout {name}", rumpf)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

    @ui._gesichert_seite
    async def layout_vorschau(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return _gerahmt("<p>Abgewiesen: fehlende oder falsche CSRF-Marke.</p>", status=403)
        try:
            m, _liste = await marketing_mandant.firma(request)
            bisher = None
            if (name := str(form.get("layout") or "")):
                bisher = (layout_von(await alle_layouts(m), name) or {}).get("gestalt")
            g, grund = await regler_lesen(form, bisher, logo_lesen=False)
            if g is None:
                return _gerahmt(f"<p>Vorschau nicht möglich: {e(grund)}</p>", status=422)
            fmt = "handy" if form.get("format") == "handy" else "mail"
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "POST", "/layouts/vorschau",
                {"gestalt": g, "mandant": m, "format": fmt}, roh=True)
        except marketing_pult.PultFehler as f:
            return gerahmter_fehler(f)
        return _gerahmt(inhalt, typ)

    @ui._gesichert_seite
    async def layout_speichern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        name = request.path_params["name"]
        try:
            m, _liste = await marketing_mandant.firma(request)
            l = layout_von(await alle_layouts(m), name)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not l:
            return ui._fehlerseite(404, "Unbekanntes Layout", "")
        g, grund = await regler_lesen(form, l.get("gestalt"))
        if g is None:
            return ui._fehlerseite(422, "Regler ungültig", e(grund))
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/layouts/{pfad(name)}/fassungen",
                                    {"gestalt": g, "von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/layout/{pfad(name)}", status_code=303)

    @ui._gesichert_seite
    async def layout_standard(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST",
                                    f"/layouts/{pfad(request.path_params['name'])}/standard", {})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/layouts", status_code=303)

    return [
        Route("/marketing", uebersicht),
        Route("/marketing/mandant", mandant_waehlen, methods=["POST"]),
        Route("/marketing/entwuerfe", entwuerfe),
        Route("/marketing/entwurf/{iid}", entwurf),
        Route("/marketing/entwurf/{iid}/vorschau", vorschau),
        Route("/marketing/entwurf/{iid}/speichern", speichern, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/entscheiden", entscheiden, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/in-bloecke", in_bloecke, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/bilder", bilder, methods=["POST"]),
        Route("/marketing/layouts", layouts),
        Route("/marketing/layout-bild/{name}", layout_bild),
        Route("/marketing/layout-vorschau", layout_vorschau, methods=["POST"]),
        Route("/marketing/layout/{name}", layout_editor),
        Route("/marketing/layout/{name}/speichern", layout_speichern, methods=["POST"]),
        Route("/marketing/layout/{name}/standard", layout_standard, methods=["POST"]),
    ]
