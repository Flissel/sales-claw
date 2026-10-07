"""Seiten des Marketing-Pults (Spec 2026-09-29-marketing-pult-design.md
§3.1, Stufe 1): Uebersicht, Entwuerfe, Entwurf. Alle Daten kommen ueber
marketing_pult; diese Datei kennt keine Marketing-Tabelle.

Wie der Rest von sales-ui: kein JavaScript (die Seiten-CSP sagt
`default-src 'none'`). Die Wahl Mail/Handy ist deshalb ein normaler Verweis,
der die Seite mit `format=` neu laedt; das PDF wird verlinkt, nicht
eingebettet (wie auf der Medienseite).

Marke (Task 6): ui_marke.py - Profil, Chat, Vorschlag; die alten Layout-Pfade
leiten dorthin.
"""
from __future__ import annotations

import html as _html
import math
import urllib.parse
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import ui_editor
import ui_marke

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
# Anzeige-Status in Worten (Spec 2026-10-07 §5): "zurückgegeben" ist kein DB-Status,
# sondern ein Entwurf mit offener Rückmeldung (status_wort).
STATUS = {"entwurf": "in Arbeit", "zurueckgegeben": "zurückgegeben", "eingereicht": "zur Freigabe",
          "freigegeben": "freigegeben", "abgelehnt": "verworfen"}


def _offen(rueckmeldungen) -> list[dict]:
    return [r for r in rueckmeldungen or [] if isinstance(r, dict) and not r.get("erledigt")]


def _wann(ui, roh) -> str:
    """ISO-Zeitpunkt der API lesbar in Ortszeit ("07.10.2026 14:32", ui._zeit);
    Unlesbares bleibt gekuerzt stehen."""
    try:
        dt = datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
    except ValueError:
        return str(roh or "")[:16]
    return ui._zeit(dt)


def _hat_offene(inhalt, rueckmeldungen=None) -> bool:
    """Offene Rückmeldung: aus der Liste (Entwurfsseite) oder dem Zähler je Zeile
    (`offene_rueckmeldungen` in /inhalte)."""
    if rueckmeldungen is None:
        rueckmeldungen = inhalt.get("rueckmeldungen")
    if _offen(rueckmeldungen):
        return True
    n = inhalt.get("offene_rueckmeldungen")
    return isinstance(n, int) and not isinstance(n, bool) and n > 0


def status_wort(inhalt, rueckmeldungen=None) -> str:
    """Status in Worten: entwurf + offene Rückmeldung = zurückgegeben, entwurf = in Arbeit,
    eingereicht = zur Freigabe, freigegeben, abgelehnt = verworfen."""
    st = str(inhalt.get("status") or "")
    if st == "entwurf" and _hat_offene(inhalt, rueckmeldungen):
        return STATUS["zurueckgegeben"]
    return STATUS.get(st, st)


def _pill(inhalt, rueckmeldungen, e) -> str:
    wort = status_wort(inhalt, rueckmeldungen)
    klasse = "zurueckgegeben" if wort == STATUS["zurueckgegeben"] else e(str(inhalt.get("status") or ""))
    return f'<span class="status-pill st-{klasse}">{e(wort)}</span>'


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
                                      f'<div class="kacheln fuenf">{karten}</div>'
                                      '<p><a class="knopf" href="/marketing/vorlagen">'
                                      'Neuer Newsletter aus Vorlage</a></p>')

    @ui._gesichert_seite
    async def entwuerfe(request):
        art = request.query_params.get("art", "")
        if art not in ARTEN:
            art = ""
        # Ohne Angabe zeigt die Liste, was in Arbeit ist; "alle" hebt den
        # Status-Filter auf.
        status = request.query_params.get("status", "") or "entwurf"
        if status not in STATUS and status != "alle":
            status = "entwurf"
        # "zurueckgegeben" ist kein DB-Status: die API liefert dafuer entwurf, die Zeilen
        # tragen `offene_rueckmeldungen`, danach wird hier getrennt (wie der Uebersichts-Zaehler).
        api_status = "entwurf" if status == "zurueckgegeben" else ("" if status == "alle" else status)
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
        inhalte = d["inhalte"]
        if status in ("entwurf", "zurueckgegeben"):
            inhalte = [i for i in inhalte if _hat_offene(i) == (status == "zurueckgegeben")]
        zeilen = "".join(
            f'<tr><td><a href="/marketing/entwurf/{e(i["id"])}">{e(i["titel"])}</a></td>'
            f'<td>{e(ARTEN.get(i["art"], i["art"]))}</td><td>{e(status_wort(i))}</td>'
            f'<td>{e(i["layout"] or "")}</td><td>{int(i["fassungen"])}</td><td>{e(str(i["erstellt_am"])[:10])}</td></tr>'
            for i in inhalte) or '<tr><td colspan="6">Keine Entwürfe.</td></tr>'
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
        try:
            firma = marketing_mandant.name_von(
                mandant, await run_in_threadpool(marketing_mandant.mandanten))
        except marketing_pult.PultFehler:
            firma = mandant          # nur das Etikett - wie im Editor kein Grund fuer eine Fehlerseite
        i, fassungen = d["inhalt"], d["fassungen"]
        if not fassungen:
            return ui._fehlerseite(422, "Nicht möglich", "Dieser Inhalt hat noch keine Fassung.")
        rueck = d.get("rueckmeldungen") or []
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
        freigegeben_nr = i.get("freigegebene_fassung")
        eingereicht_nr = i.get("eingereichte_fassung") if i["status"] == "eingereicht" else None

        def zeitleiste_zeile(f) -> str:
            n = int(f["fassung"])
            freigegeben = freigegeben_nr is not None and n == int(freigegeben_nr)
            marke = " &middot; <b>freigegeben</b>" if freigegeben else ""
            if eingereicht_nr is not None and n == int(eingereicht_nr):
                marke += " &middot; <b>zur Freigabe</b>"
            return (f'<li class="{"freigegeben" if freigegeben else ""}">'
                    f'<a href="?fassung={n}">Fassung {n}</a> '
                    f'&middot; {"Agent" if f["urheber"] == "agent" else "du"} &middot; {e(str(f["erstellt_am"])[:16])}'
                    f'{marke}</li>')
        verlauf = "".join(zeitleiste_zeile(f) for f in fassungen)
        status = i["status"]
        in_arbeit = status == "entwurf"
        csrf = f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
        basis = f"/marketing/entwurf/{e(i['id'])}"
        betreff = "Betreff" if i["art"] == "newsletter" else "Betreff (optional)"
        hinweis = "" if ist_neueste else (
            f'<div class="warnung">Das ist nicht die neueste Fassung (Fassung {nr} von {neueste}). '
            f'Einreichen geht nur für die <a href="{basis}?fassung={neueste}">neueste Fassung</a>; '
            f'Speichern legt aus dieser eine neue an.</div>')
        # Die Bruecke spiegelt nur alt -> Pult: ein Urteil hier stoppt einen
        # noch offenen Vorschlag im alten Weg (Telegram -> n8n) nicht.
        alter_weg = d.get("alter_weg") or {}
        alter_hinweis = (
            f'<div class="warnung">Dieser Entwurf liegt noch im alten Freigabeweg '
            f'({e(alter_weg.get("kanal") or "")}). Ablehnen hier stoppt ihn dort nicht, und Änderungen '
            f'hier werden dort nicht verschickt. Im alten Weg ablehnen, falls er nicht rausgehen soll.</div>'
        ) if alter_weg.get("status") in ("draft", "pending_approval") else ""
        # Feedback-Band: neueste offene Rueckmeldung offen, aeltere eingeklappt.
        offene = _offen(rueck)
        band = ""
        if offene:
            def zeile(r) -> str:
                return (f'<b>Zurückgegeben von {e(r.get("von"))} am {e(_wann(ui, r.get("am")))}:</b>'
                        f'<blockquote>{e(r.get("text"))}</blockquote>')
            aeltere = "".join(f'<div>{zeile(r)}</div>' for r in offene[1:])
            band = (f'<div class="feedback-band">{zeile(offene[0])}'
                    + (f'<details><summary>Ältere Rückmeldungen ({len(offene) - 1})</summary>{aeltere}</details>'
                       if aeltere else "") + '</div>')
        # Verwerfen nennt die gesehene Fassung; der Grund ist Pflicht und das Feld
        # klappt erst beim Klick auf.
        fassung_feld = f'<input type="hidden" name="fassung" value="{nr}">'
        verwerfen_karte = (
            f'<details class="gefahr"><summary>Verwerfen</summary>'
            f'<form method="post" action="{basis}/verwerfen" class="aktion">{csrf}{fassung_feld}'
            f'<input type="hidden" name="urteil" value="ablehnen">'
            f'<label>Grund (Pflicht)<input type="text" name="grund" required maxlength="500"></label>'
            f'<button class="gefahr" type="submit">Verwerfen</button></form></details>')
        # Editor-Newsletter (format "bloecke"): Inhalt nur im Editor; das
        # Feldformular wuerde die Bloecke nicht kennen (die DB lehnt eine
        # Felder-Fassung darauf ohnehin ab). Massgeblich ist das Format der
        # NEUESTEN Fassung - auch wenn eine aeltere gezeigt wird.
        im_editor = fassungen[0].get("format") == "bloecke"
        editor_knopf = (f'<a class="knopf" href="/marketing/editor/{e(i["id"])}">'
                        f'{"Im Editor öffnen" if in_arbeit else "Im Editor ansehen"}</a>') if im_editor else ""
        if status == "eingereicht":
            wann = e(str(i.get("eingereicht_am") or "")[:16])
            vom = e(i.get("eingereicht_von") or "")
            zeile_status = (f'<p class="meta">Liegt zur Freigabe seit {wann}'
                            f'{" (eingereicht von " + vom + ")" if vom else ""}. '
                            f'Freigegeben wird in den <a href="/freigaben#marketing">Freigaben</a>.</p>')
            haupt = (f'<form method="post" action="{basis}/zurueckziehen" class="aktion">{csrf}'
                     f'<button type="submit">Zurückziehen</button></form>')
        elif in_arbeit:
            zeile_status = '<p>Dieser Newsletter wird im Editor bearbeitet.</p>' if im_editor else ""
            haupt = (f'<form method="post" action="{basis}/einreichen" class="aktion">{csrf}'
                     f'<button type="submit">Zur Freigabe einreichen</button></form>')
        else:
            zeile_status = f'<p class="meta">{e(status_wort(i, rueck))[:1].upper()}{e(status_wort(i, rueck))[1:]}.' \
                           f'{(" Grund: " + e(i.get("grund"))) if status == "abgelehnt" and i.get("grund") else ""}</p>'
            haupt = ""
        if ist_neueste and status in ("entwurf", "eingereicht"):
            aktionen = (f'{zeile_status}<div class="aktionen">{editor_knopf}{haupt}</div>{verwerfen_karte}')
        else:
            aktionen = f'{zeile_status}<div class="aktionen">{editor_knopf}</div>' if (zeile_status or editor_knopf) else ""
        aktionskarte = f'<div class="karte"><h2>Aktionen</h2>{aktionen}</div>' if aktionen else ""
        # Feld-Newsletter (z.B. aus dem alten Weg ueber die Bruecke): einmalig
        # ins Editor-Format uebernehmen (marketing.pult_in_bloecke_uebernehmen).
        in_bloecke = "" if im_editor or i["art"] != "newsletter" else (
            f'<form method="post" action="{basis}/in-bloecke" class="aktion">{csrf}'
            f'<button type="submit">Ins Editor-Format übernehmen</button>'
            f'<span class="meta">Legt eine neue Fassung im Editor-Format an; danach wird dieser '
            f'Newsletter nur noch im Editor bearbeitet.</span></form>')
        # Felder-Fassungen (Posts, Material, alte Newsletter) behalten das Formular - solange sie in Arbeit sind.
        feldkarte = ""
        if in_arbeit and not im_editor:
            feldkarte = (
                f'<div class="karte"><h2>Inhalt</h2>{in_bloecke}'
                f'<form method="post" action="{basis}/speichern" class="pult-felder">{csrf}'
                f'<label>{betreff} <input name="betreff" value="{e(fe.get("betreff"))}"></label>'
                f'<label>Vorschautext <input name="vorschautext" value="{e(fe.get("vorschautext"))}"></label>'
                f'{abschnitte}'
                f'<label>Knopf-Text <input name="knopf_text" value="{e(fe.get("knopf_text"))}"></label>'
                f'<label>Knopf-Link <input name="knopf_link" value="{e(fe.get("knopf_link"))}"></label>'
                f'<label>Layout <select name="layout">{layouts}</select></label>'
                f'<button type="submit">Als neue Fassung speichern</button></form></div>')
        bilder_html = ""
        neu_laden = False
        if im_editor and in_arbeit:
            try:
                stand = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                                f"/inhalte/{urllib.parse.quote(iid)}/bilder")
                auftraege = stand.get("auftraege") or []
                neu_laden = any(a.get("status") in ("offen", "in_arbeit") for a in auftraege)
                zeilen_b = "".join(
                    f'<li><span class="punkt bs-{e(a.get("status") or "offen")}" aria-hidden="true"></span>'
                    f'{e(a.get("platz") or ("alle leeren" if a.get("nur_leere") else "alle"))} &middot; '
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
                f'<div class="karte"><h2>Bilder</h2><ul class="bildstand">{zeilen_b}</ul>'
                f'<form method="post" action="{basis}/bilder" class="aktion">{csrf}'
                f'<div class="bild-zeile">'
                f'<label>Platz <select name="platz">{optionen}</select></label>'
                f'<label>Stärke <select name="staerke">'
                f'<option value="35" selected>nah am Original</option><option value="75">freier</option>'
                f'<option value="100">ganz neu</option></select></label>'
                f'<label>Hinweis <input type="text" name="hinweis" maxlength="500" placeholder="z. B. wärmer, mehr Menschen"></label>'
                f'<button type="submit">Bild überarbeiten</button></div>'
                f'<span class="meta">Erzeugt wird am PC, sobald er läuft. Das Ergebnis ist eine neue Fassung.</span></form></div>')
        wahl_links = "".join(
            f'<a class="{"aktiv" if k == fmt else ""}" href="{basis}?fassung={nr}&amp;format={k}">{t}</a>'
            for k, t in RAHMEN_FORMATE.items())
        if akt.get("format") != "bloecke":
            # Fuer Editor-Fassungen gibt es (noch) kein PDF - die API sagt 422.
            wahl_links += (f'<a href="{basis}/vorschau?fassung={nr}&amp;format=pdf" target="_blank" '
                           f'rel="noopener noreferrer">PDF &#8599;</a>')
        kopf = (f'<div class="entwurf-kopf">'
                f'<p class="kopfzeile"><span class="firma">{e(firma)}</span>{_pill(i, rueck, e)}'
                f'<span class="meta">{e(ARTEN.get(i["art"], i["art"]))} &middot; Fassung {nr}</span></p></div>')
        rumpf = (
            f'{kopf}{band}{hinweis}{alter_hinweis}'
            f'<div class="pult"><div class="pult-links">{aktionskarte}{feldkarte}{bilder_html}'
            f'<div class="karte"><h2>Fassungen</h2><ul class="zeitleiste">{verlauf}</ul></div></div>'
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
        # Freigeben passiert in den Sales-Freigaben (Spec 2026-10-07), nicht hier.
        if str(form.get("urteil") or "") == "freigeben":
            return ui._fehlerseite(422, "Nicht möglich",
                                   'Freigeben geht über die Freigaben. '
                                   '<a href="/freigaben#marketing">Zu den Freigaben</a>')
        return await verwerfen_senden(request, form)

    async def verwerfen_senden(request, form):
        """Verwerfen = urteil ablehnen. Der Grund ist Pflicht - die API sagt sonst 422;
        hier wird vorher geprueft, damit gar kein Aufruf hinausgeht."""
        fassung = _fassung_zahl(form.get("fassung"))
        if fassung is None:
            return ui._fehlerseite(400, "Abgewiesen",
                                   "Welche Fassung gemeint ist, fehlt. Nichts wurde entschieden - "
                                   "Seite neu laden und erneut.")
        if str(form.get("urteil") or "") != "ablehnen":
            return ui._fehlerseite(422, "Nicht möglich", "Unbekanntes Urteil.")
        grund = str(form.get("grund") or "").strip()
        if not grund:
            return ui._fehlerseite(422, "Nicht möglich", "Bitte gib einen Grund an.")
        iid = urllib.parse.quote(request.path_params["iid"])
        try:
            await run_in_threadpool(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/entscheiden",
                {"fassung": fassung, "urteil": "ablehnen", "von": von(request), "grund": grund})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}", status_code=303)

    @ui._gesichert_seite
    async def verwerfen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        form = {"fassung": form.get("fassung"), "grund": form.get("grund"), "urteil": "ablehnen"}
        return await verwerfen_senden(request, form)

    def einfache_aktion(aktion: str):
        """einreichen / zurueckziehen: nur {von}, die Regeln liegen in der DB."""
        @ui._gesichert_seite
        async def handler(request):
            form = await request.form()
            if not ui._csrf_ok(form):
                return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
            iid = urllib.parse.quote(request.path_params["iid"], safe="")
            try:
                await run_in_threadpool(marketing_pult.anfrage, "POST",
                                        f"/inhalte/{iid}/{aktion}", {"von": von(request)})
            except marketing_pult.PultFehler as f:
                return fehler(f)
            return RedirectResponse(f"/marketing/entwurf/{iid}", status_code=303)
        return handler

    einreichen = einfache_aktion("einreichen")
    zurueckziehen = einfache_aktion("zurueckziehen")

    return [
        Route("/marketing", uebersicht),
        Route("/marketing/mandant", mandant_waehlen, methods=["POST"]),
        Route("/marketing/entwuerfe", entwuerfe),
        Route("/marketing/entwurf/{iid}", entwurf),
        Route("/marketing/entwurf/{iid}/vorschau", vorschau),
        Route("/marketing/entwurf/{iid}/speichern", speichern, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/entscheiden", entscheiden, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/in-bloecke", in_bloecke, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/einreichen", einreichen, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/zurueckziehen", zurueckziehen, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/verwerfen", verwerfen, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/bilder", bilder, methods=["POST"]),
        *ui_marke.routen(ui),
    ]
