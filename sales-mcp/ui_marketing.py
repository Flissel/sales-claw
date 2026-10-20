"""Seiten des Marketing-Pults (Spec 2026-09-29-marketing-pult-design.md
§3.1, Stufe 1): Uebersicht, Entwuerfe, Entwurf. Alle Daten kommen ueber
marketing_pult; diese Datei kennt keine Marketing-Tabelle.

Wie der Rest von sales-ui: kein JavaScript (die Seiten-CSP sagt
`default-src 'none'`). Die Wahl Mail/Handy ist deshalb ein normaler Verweis,
der die Seite mit `format=` neu laedt; das PDF (Collagen, Felder) wird
verlinkt, nicht eingebettet (wie auf der Medienseite).

Collagen (Freie Flaeche Stufe 4): mail/handy sind die echte Mail - die API
erzeugt sie bei Bedarf (Chromium, langsam, kann mit Grund scheitern). Rahmen,
die von selbst laden (Galeriekarten, Entwurfsseite ohne Wahl), zeigen deshalb
die billige Seite (`format=seite`); die Mail nur auf Klick ("Mail-Vorschau").

Marke (Task 6): ui_marke.py - Profil, Chat, Vorschlag; die alten Layout-Pfade
leiten dorthin.
"""
from __future__ import annotations

import html as _html
import math
import re
import urllib.parse
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import ui_editor
import ui_marke
import ui_muster

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
# Anzeige-Status in Worten (Spec 2026-10-07 §5): "zurückgegeben" ist kein DB-Status,
# sondern ein Entwurf mit offener Rückmeldung (status_wort).
STATUS = {"entwurf": "in Arbeit", "zurueckgegeben": "zurückgegeben", "eingereicht": "zur Freigabe",
          "freigegeben": "freigegeben", "abgelehnt": "verworfen"}


# Loeschbar sind nur Entwuerfe (auch "zurueckgegeben") und verworfene; die DB
# prueft es nochmals (marketing.pult_inhalt_loeschen). Hoechstens so viele je Durchgang.
LOESCHBAR = ("entwurf", "abgelehnt")
LOESCH_MAX = 50
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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
    klasse = "rueckgabe" if wort == STATUS["zurueckgegeben"] else e(str(inhalt.get("status") or ""))
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
# Collagen: die Seite (Vorgabe, billig) und die echte Mail nur auf Klick.
RAHMEN_FORMATE_COLLAGE = {"seite": "Seite", "mail": "Mail-Vorschau", "handy": "Handy"}
# Was die Vorschau-Route annimmt. "karte" (Galerie): sales-ui waehlt selbst - Seite fuer eine
# Collage, sonst Mail -, weil die Liste der API das Format nicht nennt.
VORSCHAU_FORMATE = ("mail", "handy", "pdf", "seite", "karte")

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


def _fassung_zahl(roh) -> int | None:
    try:
        n = int(str(roh))
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


# Newsletter-Galerie (/marketing): Karten je Seite.
GALERIE_SEITE = 12


def _ganzzahl(roh) -> int | None:
    """Ganzzahl aus Abfrage oder API, sonst None (kein bool, keine Kommazahl)."""
    if isinstance(roh, bool):
        return None
    try:
        return int(str(roh))
    except (TypeError, ValueError):
        return None


def _tag_monat(roh) -> str:
    """Datum der API als TT.MM. (2026-10-01 -> 01.10.); Unlesbares bleibt gekuerzt stehen."""
    try:
        d = datetime.fromisoformat(str(roh)[:10])
    except ValueError:
        return str(roh or "")[:10]
    return d.strftime("%d.%m.")


def _newsletter_karte(e, i: dict) -> str:
    """Eine Karte der Galerie: verkleinerte, gesandboxte Vorschau der neuesten
    Fassung (E11, dieselbe Route wie die Entwurfsseite), Titel, Fassung, Datum,
    Status. Ohne Fassung nur der Platzhalter. In Arbeit oeffnet den Editor,
    alles andere die Entwurfsseite."""
    iid = urllib.parse.quote(str(i.get("id") or ""), safe="")
    titel = str(i.get("titel") or "")
    n = _ganzzahl(i.get("fassungen")) or 0
    # Collagen nie als echte Mail (Chromium je Karte): die Seite. Ohne Format in der Liste waehlt die Route.
    fmt = {"seite": "seite", "bloecke": "mail", "felder": "mail"}.get(str(i.get("format") or ""), "karte")
    rahmen = (f'<iframe class="layout-bild" sandbox tabindex="-1" loading="lazy" '
              f'title="Vorschau {e(titel)}" '
              f'src="{e(f"/marketing/entwurf/{iid}/vorschau?fassung={n}&format={fmt}")}"></iframe>'
              if n >= 1 else "")
    if i.get("status") == "entwurf":
        ziel, wort = f"/marketing/editor/{iid}", "Öffnen"
    else:
        ziel, wort = f"/marketing/entwurf/{iid}", "Ansehen"
    fassung = f"Fassung {n}" if n >= 1 else "Noch keine Fassung"
    return (f'<div class="layout-karte nl-karte"><div class="layout-rahmen">'
            f'<span class="layout-platzhalter">{e(titel)}</span>{rahmen}</div>'
            f'<strong>{e(titel)}</strong>'
            f'<span class="meta">{fassung} &middot; erstellt {e(_tag_monat(i.get("erstellt_am")))}</span>'
            f'<div class="fuss">{_pill(i, None, e)}'
            f'<a class="knopf sek" href="{e(ziel)}">{wort}</a></div></div>')


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
        # Newsletter-Galerie (Design-Review S3, E10): Status-Reiter und Karten aus EINER
        # Liste aller Newsletter der Firma - so zaehlt ein Reiter genau die Karten darunter
        # (/uebersicht zaehlt alle Arten). Beide Abfrageparameter laufen gegen Whitelist
        # bzw. Klemme und werden nie roh zurueckgespiegelt.
        status = request.query_params.get("status", "")
        if status not in STATUS:
            status = "entwurf"
        try:
            m, liste = await marketing_mandant.firma(request)
            q = urllib.parse.urlencode({"mandant": m, "art": "newsletter"})
            dl = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        alle = [i for i in dl.get("inhalte") or []
                if isinstance(i, dict) and i.get("art") == "newsletter"]

        def reiter_von(i: dict) -> str:
            # Wie in entwuerfe: "zurueckgegeben" ist ein Entwurf mit offener Rueckmeldung.
            st = i.get("status")
            return "zurueckgegeben" if st == "entwurf" and _hat_offene(i) else str(st)
        zahlen = {k: sum(1 for i in alle if reiter_von(i) == k) for k in STATUS}
        inhalte = [i for i in alle if reiter_von(i) == status]
        letzte = max(1, math.ceil(len(inhalte) / GALERIE_SEITE))
        seite = min(max(_ganzzahl(request.query_params.get("seite")) or 1, 1), letzte)

        def verweis(st: str, s: int = 1) -> str:
            # Nur aus geprueften Werten; die Vorgabe (in Arbeit, Seite 1) ist /marketing selbst.
            if st == "entwurf" and s <= 1:
                return "/marketing"
            return "/marketing?" + urllib.parse.urlencode(
                [("status", st)] + ([("seite", str(s))] if s > 1 else []))

        reiter = ui_muster.reiter([(k, t, zahlen[k]) for k, t in STATUS.items()],
                                  status, verweis)
        karten = "".join(_newsletter_karte(e, i) for i in
                         inhalte[(seite - 1) * GALERIE_SEITE:seite * GALERIE_SEITE])
        leer = "" if karten else '<p class="meta">Keine Newsletter mit diesem Status.</p>'
        # Nur noch Collagen (Stufe 5): mit einer freigegebenen Collage-Vorlage fuehren die Knoepfe zu
        # Collage-Vorlagen. Die Liste ist ein Zusatz - nicht lesbar heisst: Knoepfe wie bisher.
        try:
            dv = await run_in_threadpool(marketing_pult.anfrage, "GET", "/vorlagen?" + urllib.parse.urlencode(
                {"mandant": m, "status": "freigegeben"}))
            nur_collagen = bool(ui_editor.vorlagen_teilen(dv.get("vorlagen") if isinstance(dv, dict) else None)[0])
        except marketing_pult.PultFehler:
            nur_collagen = False
        aus_vorlage = "Neu aus Collage-Vorlage" if nur_collagen else "Neuer Newsletter aus Vorlage"
        aus_vorlage_karte = "+ Aus Collage-Vorlage starten" if nur_collagen else "+ Aus Vorlage starten"
        rumpf = (umschalter(m, liste, verweis(status, seite))
                 + '<div class="nl-kopf"><a class="knopf" href="/marketing/vorlagen">'
                 f'{aus_vorlage}</a>'
                 f'<form method="post" action="/marketing/neue-collage" class="aktion">'
                 f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
                 f'<label>Titel <input name="titel" required maxlength="{ui_editor.TITEL_MAX_COLLAGE}" placeholder="Titel der Collage"></label>'
                 '<button type="submit">Neue Collage</button></form>'
                 '<a href="/marketing/entwuerfe">Alle Entwürfe als Liste</a></div>'
                 + reiter + leer
                 + f'<div class="galerie">{karten}'
                 f'<a class="layout-karte neu" href="/marketing/vorlagen">{aus_vorlage_karte}</a></div>'
                 + ui_muster.blaettern(seite, letzte, lambda s: verweis(status, s)))
        antwort = ui._seite("Newsletter", rumpf)
        # Die Vorschauen sind eigene, gesandboxte Rahmen (wie die Vorlagen-Galerie).
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

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
        def haken(i) -> str:
            if i.get("status") not in LOESCHBAR:
                return ""
            return (f'<label class="haken"><input type="checkbox" name="iid" value="{e(i["id"])}" '
                    f'aria-label="Auswählen: {e(i["titel"])}"></label>')
        zeilen = [[haken(i), f'<a href="/marketing/entwurf/{e(i["id"])}">{e(i["titel"])}</a>',
                   e(ARTEN.get(i["art"], i["art"])), e(status_wort(i)), e(i["layout"] or ""),
                   str(int(i["fassungen"])), e(str(i["erstellt_am"])[:10])] for i in inhalte]
        tabelle = ui._tabelle([" ", "Titel", "Art", "Status", "Layout", "Fassungen", "Datum"],
                              zeilen, leer="Keine Entwürfe.")
        if any(i.get("status") in LOESCHBAR for i in inhalte):
            tabelle = (f'<form method="post" action="/marketing/entwuerfe/loeschen">'
                       f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">{tabelle}'
                       f'<p><button class="gefahr" type="submit">Ausgewählte löschen …</button></p></form>')
        return ui._seite("Entwürfe", umschalter(m, liste, "/marketing/entwuerfe?" + urllib.parse.urlencode(
                                       [(k, v) for k, v in (("art", art), ("status", status)) if v])) +
                         f'<div class="filter">{filter_}</div>'
                         f'<div class="filter">{filter_status}</div>{tabelle}')

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
        collage = akt.get("format") == "seite"
        rahmen_formate = RAHMEN_FORMATE_COLLAGE if collage else RAHMEN_FORMATE
        fmt = request.query_params.get("format", "")
        if fmt not in rahmen_formate:
            fmt = "seite" if collage else "mail"
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
        im_editor = fassungen[0].get("format") in ("bloecke", "seite")
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
        if status in LOESCHBAR:
            aktionen += (
                f'<details class="gefahr"><summary>Löschen …</summary>'
                f'<form method="post" action="/marketing/entwuerfe/loeschen" class="aktion">{csrf}'
                f'<input type="hidden" name="iid" value="{e(i["id"])}">'
                f'<button class="gefahr" type="submit">Löschen …</button>'
                f'<span class="meta">Du siehst vorher, was verschwindet.</span></form></details>')
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
        if fassungen[0].get("format") == "bloecke" and in_arbeit:
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
            bilder_html = f'<div class="karte"><h2>Bilder</h2><ul class="bildstand">{zeilen_b}</ul></div>'
        wahl_links = "".join(
            f'<a class="{"aktiv" if k == fmt else ""}" href="{basis}?fassung={nr}&amp;format={k}">{t}</a>'
            for k, t in rahmen_formate.items())
        if akt.get("format") != "bloecke":
            # Bloecke-Fassungen haben kein PDF (die API sagt 422); Collagen und Felder schon.
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
    async def vorschau(request):
        iid = urllib.parse.quote(request.path_params["iid"])
        fassung = _fassung_zahl(request.query_params.get("fassung", "1"))
        fmt = request.query_params.get("format", "mail")
        if fassung is None or fmt not in VORSCHAU_FORMATE:
            return ui._fehlerseite(400, "Ungültige Vorschau", "Fassung oder Format fehlt.")

        def im_rahmen(f: marketing_pult.PultFehler) -> Response:
            # Fehler einer gerahmten Vorschau stehen IM Rahmen (mit den Seiten-Koepfen, DENY, bliebe er
            # leer). Eine Collage-Mail kann mit Grund scheitern ("Die Anrede steht in einem Bildbereich ...").
            if f.art == "abgelehnt":
                return _gerahmt(f"<p>Vorschau nicht möglich: {e(f.grund)}</p>", status=422)
            if f.art == "nicht_verbunden":
                return _gerahmt("<p>Marketing nicht verbunden.</p>", status=503)
            return _gerahmt("<p>Marketing gerade nicht erreichbar.</p>", status=503)

        if fmt == "karte":
            # Galeriekarte: Collage -> die Seite (kein Chromium je Karte), alles andere -> die Mail.
            try:
                d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}")
            except marketing_pult.PultFehler as f:
                return im_rahmen(f)
            fassungen = [f for f in (d.get("fassungen") if isinstance(d, dict) else None) or []
                         if isinstance(f, dict)]
            # die gefragte Fassung, sonst die neueste (fassungen[0]) - eine Collage nie als Mail
            treffer = next((f for f in fassungen if _ganzzahl(f.get("fassung")) == fassung),
                           fassungen[0] if fassungen else None)
            fmt = "seite" if isinstance(treffer, dict) and treffer.get("format") == "seite" else "mail"
        q_teile = {"fassung": fassung, "format": fmt}
        # Bilder der Editor-Newsletter: signierte Adresse, weil der
        # abgeschottete Rahmen keine Anmelde-Cookies schickt. Leer (kein
        # Geheimnis, kein https) -> weglassen, die API zeigt Platzhalter.
        if (bild_basis := ui_editor.bild_basis()):
            q_teile["bild_basis"] = bild_basis
        q = urllib.parse.urlencode(q_teile)
        try:
            # mail/handy einer Collage rendern beim ersten Mal die Bildstuecke (Chromium): langes Zeitlimit
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "GET", f"/inhalte/{iid}/vorschau?{q}", roh=True,
                zeitlimit=marketing_pult.LANG_ZEITLIMIT_S if fmt in ("mail", "handy") else None)
        except marketing_pult.PultFehler as f:
            # Das PDF oeffnet als eigene Seite (neuer Tab): dort die normale Fehlerseite.
            return fehler(f) if fmt == "pdf" else im_rahmen(f)
        if str(typ).startswith("application/pdf"):
            # Wie die Medienseite: eigene Datei-Richtlinie, verlinkt statt gerahmt.
            return Response(inhalt, media_type="application/pdf",
                            headers={"Content-Security-Policy": ui._CSP_DATEI,
                                     "Content-Disposition": 'inline; filename="vorschau.pdf"',
                                     "Cache-Control": "private, no-store"})
        return _gerahmt(inhalt, typ)

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

    def _iids(form) -> list[str] | Response:
        """Die angehakten ids: ohne Haken, zu viele oder eine ungueltige = 400, ohne
        dass irgendein Aufruf hinausgeht. Doppelte fallen weg (Reihenfolge bleibt)."""
        roh = [str(x) for x in form.getlist("iid")]
        if not roh:
            return ui._fehlerseite(400, "Nichts gewählt", "Es wurde kein Entwurf angehakt. Nichts wurde gelöscht.")
        ids = list(dict.fromkeys(x.lower() for x in roh))
        if len(ids) > LOESCH_MAX:
            return ui._fehlerseite(400, "Zu viele auf einmal",
                                   f"Höchstens {LOESCH_MAX} Entwürfe je Durchgang. Nichts wurde gelöscht.")
        if not all(_UUID.match(x) for x in ids):
            return ui._fehlerseite(400, "Abgewiesen", "Eine Entwurfs-ID ist ungültig. Nichts wurde gelöscht.")
        return ids

    def _titel_laden(ids: list[str], mandant: str) -> list[dict]:
        """Anzeige fuer Schritt 1: je id Titel und Status (nur Lesen). Eine fremde Firma
        bekommt keinen Titel."""
        aus = []
        for iid in ids:
            try:
                d = marketing_pult.anfrage("GET", f"/inhalte/{urllib.parse.quote(iid, safe='')}")
                inh = d.get("inhalt") if isinstance(d, dict) else None
                if not isinstance(inh, dict):
                    raise marketing_pult.PultFehler("unbekannt", "Antwort ohne Inhalt")
            except marketing_pult.PultFehler as f:
                if f.art in ("nicht_verbunden", "nicht_erreichbar"):
                    raise
                aus.append({"id": iid, "titel": "", "grund": "nicht gefunden"})
                continue
            if inh.get("mandant") != mandant:
                aus.append({"id": iid, "titel": "", "grund": "nicht löschbar: gehört einer anderen Firma"})
            elif inh.get("status") not in LOESCHBAR:
                wort = {"eingereicht": "zur Freigabe", "freigegeben": "freigegeben"}.get(
                    str(inh.get("status")), str(inh.get("status") or "?"))
                aus.append({"id": iid, "titel": str(inh.get("titel") or ""), "grund": f"nicht löschbar: {wort}"})
            else:
                aus.append({"id": iid, "titel": str(inh.get("titel") or ""), "grund": ""})
        return aus

    @ui._gesichert_seite
    async def entwuerfe_loeschen(request):
        """Schritt 1: zeigt, was weg ginge. Loescht nichts."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        ids = _iids(form)
        if isinstance(ids, Response):
            return ids
        try:
            m, _ = await marketing_mandant.firma(request)
            zeilen = await run_in_threadpool(_titel_laden, ids, m)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        ok = [z for z in zeilen if not z["grund"]]
        liste_html = "".join(
            f'<li>{e(z["titel"]) if z["titel"] else "<i>unbekannter Entwurf</i>"}'
            f'{(" &middot; <b>" + e(z["grund"]) + "</b>") if z["grund"] else ""}</li>' for z in zeilen)
        if ok:
            versteckt = "".join(f'<input type="hidden" name="iid" value="{e(z["id"])}">'
                                f'<input type="hidden" name="titel" value="{e(z["titel"])}">' for z in ok)
            formular = (
                f'<form method="post" action="/marketing/entwuerfe/loeschen-bestaetigen" class="aktion">'
                f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">{versteckt}'
                f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja" required> '
                f'Ja, endgültig löschen</label>'
                f'<button class="gefahr" type="submit">Löschen</button></form>')
        else:
            formular = "<p>Nichts davon lässt sich löschen.</p>"
        rumpf = (f'<div class="karte">'
                 f'<p>Das ist ein echtes Löschen: Fassungen, Rückmeldungen und Aufträge dieser Entwürfe '
                 f'verschwinden. Erzeugte Bilder bleiben in den Medien.</p>'
                 f'<ul>{liste_html}</ul>{formular}'
                 f'<p><a href="/marketing/entwuerfe">Abbrechen, nichts tun</a></p></div>')
        return ui._seite("Entwürfe löschen", rumpf)

    @ui._gesichert_seite
    async def entwuerfe_loeschen_bestaetigt(request):
        """Schritt 2: loescht je id ueber die API (die DB prueft Status, Firma, laufenden
        Assistenten). Alles geloescht = zurueck zur Liste; sonst eine Ergebnisseite mit Gruenden."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if str(form.get("bestaetigt") or "") != "ja":
            return ui._fehlerseite(400, "Nicht bestätigt", "Ohne den Haken „Ja, endgültig löschen“ wird nichts gelöscht.")
        ids = _iids(form)
        if isinstance(ids, Response):
            return ids
        try:
            m, _ = await marketing_mandant.firma(request)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        wer = von(request)
        # Die Titel kennt nur Schritt 1; sie stehen nur zur Anzeige im Formular (keine Berechtigung).
        titel_roh = [str(x) for x in form.getlist("titel")]
        id_roh = [str(x).lower() for x in form.getlist("iid")]
        titel_von = dict(zip(id_roh, titel_roh)) if len(titel_roh) == len(id_roh) else {}

        def lauf():
            weg, fehl, stopp = [], [], False
            for iid in ids:
                if stopp:
                    fehl.append((iid, "nicht versucht (Marketing nicht erreichbar)"))
                    continue
                try:
                    r = marketing_pult.inhalt_loeschen(iid, m, wer)
                except marketing_pult.PultFehler as f:
                    if f.art in ("nicht_verbunden", "nicht_erreichbar"):
                        stopp = True
                        fehl.append((iid, "Marketing gerade nicht erreichbar"))
                    else:
                        fehl.append((iid, f.grund or "abgelehnt"))
                    continue
                ui.LOG.warning("Marketing: Entwurf %s gelöscht von %s", iid, wer)
                weg.append(str(r.get("titel") or iid))
            return weg, fehl
        weg, fehl = await run_in_threadpool(lauf)
        if not fehl:
            return RedirectResponse("/marketing/entwuerfe", status_code=303)
        n = len(weg)
        kopf = f'{n} {"Entwurf" if n == 1 else "Entwürfe"} gelöscht'
        weg_html = "".join(f"<li>{e(t)}</li>" for t in weg)
        fehl_html = "".join(
            f'<li>{e(titel_von.get(i) or "Unbekannter Inhalt")} &middot; {e(g)}</li>' for i, g in fehl)
        rumpf = (f'<div class="karte"><h2>{kopf}</h2>'
                 f'{("<ul>" + weg_html + "</ul>") if weg else ""}'
                 f'<h3>Nicht gelöscht</h3><ul>{fehl_html}</ul>'
                 f'<p><a class="knopf" href="/marketing/entwuerfe">Zurück zu den Entwürfen</a></p></div>')
        return ui._seite("Entwürfe löschen", rumpf)

    def einfache_aktion(aktion: str):
        """einreichen / zurueckziehen: nur {von}, die Regeln liegen in der DB."""
        @ui._gesichert_seite
        async def handler(request):
            form = await request.form()
            if not ui._csrf_ok(form):
                return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
            iid = urllib.parse.quote(request.path_params["iid"], safe="")
            try:
                await run_in_threadpool(
                    marketing_pult.anfrage, "POST", f"/inhalte/{iid}/{aktion}", {"von": von(request)},
                    zeitlimit=marketing_pult.LANG_ZEITLIMIT_S if aktion == "einreichen" else None)
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
        Route("/marketing/entwuerfe/loeschen", entwuerfe_loeschen, methods=["POST"]),
        Route("/marketing/entwuerfe/loeschen-bestaetigen", entwuerfe_loeschen_bestaetigt, methods=["POST"]),
        Route("/marketing/entwurf/{iid}", entwurf),
        Route("/marketing/entwurf/{iid}/vorschau", vorschau),
        Route("/marketing/entwurf/{iid}/speichern", speichern, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/entscheiden", entscheiden, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/in-bloecke", in_bloecke, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/einreichen", einreichen, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/zurueckziehen", zurueckziehen, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/verwerfen", verwerfen, methods=["POST"]),
        *ui_marke.routen(ui),
    ]
