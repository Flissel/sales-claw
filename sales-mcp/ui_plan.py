"""Kampagnenkalender im Marketing-Pult (17.10.2026, Marketing-Migration 071).

Betreiber-Entscheid: eigene Seite /marketing/plan, der Agent darf nur
vorschlagen, bestaetigt wird hier. Ein Planeintrag versendet nichts - was
hinausgeht, laeuft weiter ueber Entwurf und Freigabe. Alle Daten kommen ueber
marketing_pult (/api/pult/plan); diese Datei kennt keine Marketing-Tabelle.
Wie der Rest von sales-ui ohne JavaScript: jede Aktion ist ein eigenes Formular.
"""
from __future__ import annotations

import urllib.parse
from datetime import date, timedelta

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import marketing_mandant
import marketing_pult

ARTEN = {"newsletter": "Newsletter", "post": "Post", "podcast": "Podcast", "video": "Video",
         "aktion": "Aktion", "sonstiges": "Sonstiges"}
STATUS = {"vorschlag": "Vorschlag vom Agenten", "geplant": "geplant", "verschoben": "verschoben",
          "erledigt": "erledigt", "abgesagt": "abgesagt"}
# Knopf -> Status an die API. "verschieben" schickt stattdessen das neue Datum.
AKTIONEN = {"uebernehmen": "geplant", "erledigt": "erledigt", "absagen": "abgesagt"}
MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember")
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def monat_lesen(roh: str | None, heute: date | None = None) -> date:
    """'JJJJ-MM' -> erster Tag des Monats; alles andere -> aktueller Monat."""
    heute = heute or date.today()
    try:
        j, m = (int(x) for x in str(roh or "").split("-"))
        if 2000 <= j <= 2100 and 1 <= m <= 12:
            return date(j, m, 1)
    except ValueError:
        pass
    return heute.replace(day=1)


def monat_ende(erster: date) -> date:
    return (erster.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def nachbar(erster: date, schritt: int) -> str:
    if schritt < 0:
        return (erster - timedelta(days=1)).strftime("%Y-%m")
    return (monat_ende(erster) + timedelta(days=1)).strftime("%Y-%m")


def datum_ok(roh) -> str | None:
    try:
        return date.fromisoformat(str(roh or "")).isoformat()
    except ValueError:
        return None


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

    def zurueck_ziel(form) -> str:
        z = str(form.get("zurueck") or "")
        return z if marketing_mandant.ziel_ok(z) and z.startswith("/marketing/plan") else "/marketing/plan"

    def knoepfe(p: dict, zurueck: str) -> str:
        pid = e(urllib.parse.quote(str(p.get("id") or ""), safe=""))
        status = p.get("status")
        if status in ("erledigt", "abgesagt"):
            return ""

        def knopf(aktion: str, text: str) -> str:
            return (f'<form method="post" action="/marketing/plan/{pid}" class="aktion">{csrf()}'
                    f'<input type="hidden" name="zurueck" value="{e(zurueck)}">'
                    f'<button type="submit" name="aktion" value="{aktion}">{text}</button></form>')
        teile = ([knopf("uebernehmen", "Übernehmen"), knopf("absagen", "Verwerfen")] if status == "vorschlag"
                 else [knopf("erledigt", "Erledigt"), knopf("absagen", "Absagen")])
        teile.append(f'<form method="post" action="/marketing/plan/{pid}" class="aktion">{csrf()}'
                     f'<input type="hidden" name="zurueck" value="{e(zurueck)}">'
                     f'<input type="date" name="datum" value="{e(str(p.get("datum") or ""))}" '
                     f'aria-label="Neues Datum">'
                     f'<button type="submit" name="aktion" value="verschieben">Verschieben</button></form>')
        return "".join(teile)

    @ui._gesichert_seite
    async def plan(request):
        erster = monat_lesen(request.query_params.get("monat"))
        letzter = monat_ende(erster)
        try:
            m, liste = await marketing_mandant.firma(request)
            q = urllib.parse.urlencode({"mandant": m, "von": erster.isoformat(), "bis": letzter.isoformat()})
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/plan?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        eintraege = [p for p in (d.get("eintraege") if isinstance(d, dict) else None) or [] if isinstance(p, dict)]
        hier = f"/marketing/plan?monat={erster:%Y-%m}"
        vorschlaege = sum(1 for p in eintraege if p.get("status") == "vorschlag")
        zeilen = []
        for p in eintraege:
            try:
                tag = date.fromisoformat(str(p.get("datum"))[:10])
                wann = f"{WOCHENTAGE[tag.weekday()]} {tag:%d.%m.}"
            except ValueError:
                wann = e(str(p.get("datum") or ""))
            notiz = str(p.get("notiz") or "")
            zeilen.append(
                f'<tr class="plan-{e(str(p.get("status") or ""))}"><td>{e(wann)}</td>'
                f'<td>{e(ARTEN.get(p.get("art"), str(p.get("art") or "")))}</td>'
                f'<td><b>{e(str(p.get("titel") or ""))}</b>'
                + (f'<br><small>{e(notiz)}</small>' if notiz else "")
                + (f'<br><a href="/marketing/entwurf/{e(urllib.parse.quote(str(p["inhalt"]), safe=""))}">'
                   'Zum Entwurf</a>' if p.get("inhalt") else "")
                + f'</td><td>{e(STATUS.get(p.get("status"), str(p.get("status") or "")))}</td>'
                f'<td>{knoepfe(p, hier)}</td></tr>')
        tabelle = ("<table><tr><th>Tag</th><th>Art</th><th>Was</th><th>Status</th><th></th></tr>"
                   + ("".join(zeilen) or '<tr><td colspan="5">In diesem Monat ist nichts geplant.</td></tr>')
                   + "</table>")
        blaettern = (f'<div class="filter"><a href="/marketing/plan?monat={nachbar(erster, -1)}">&larr; Vormonat</a>'
                     f'<a class="aktiv" href="{e(hier)}">{MONATE[erster.month - 1]} {erster.year}</a>'
                     f'<a href="/marketing/plan?monat={nachbar(erster, 1)}">Nächster Monat &rarr;</a></div>')
        hinweis = (f'<p><b>{vorschlaege} Vorschlag{"" if vorschlaege == 1 else "e"} vom Agenten</b> '
                   'warten auf dich: übernehmen oder verwerfen.</p>' if vorschlaege else "")
        arten = "".join(f'<option value="{k}">{e(t)}</option>' for k, t in ARTEN.items())
        formular = (f'<h2>Neuer Eintrag</h2><form method="post" action="/marketing/plan/neu" class="aktion">{csrf()}'
                    f'<input type="hidden" name="zurueck" value="{e(hier)}">'
                    f'<label>Datum <input type="date" name="datum" required min="{date.today().isoformat()}"></label>'
                    f'<label>Art <select name="art">{arten}</select></label>'
                    '<label>Titel <input type="text" name="titel" required maxlength="120"></label>'
                    '<label>Notiz <textarea name="notiz" maxlength="1000" rows="2"></textarea></label>'
                    '<button type="submit">Eintragen</button></form>'
                    '<p><small>Ein Eintrag ist nur ein Plan, er verschickt nichts. Hinaus geht weiterhin nur, '
                    'was über Entwurf und Freigabe läuft.</small></p>')
        return ui._seite("Kampagnenplan", marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, hier)
                         + blaettern + hinweis + tabelle + formular)

    @ui._gesichert_seite
    async def neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        datum = datum_ok(form.get("datum"))
        art = str(form.get("art") or "")
        titel = str(form.get("titel") or "").strip()
        if not datum or art not in ARTEN or not titel:
            return ui._fehlerseite(422, "Nicht möglich", "Datum, Art und Titel sind nötig.")
        try:
            m, _ = await marketing_mandant.firma(request)
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/plan",
                                    {"mandant": m, "datum": datum, "art": art, "titel": titel,
                                     "notiz": str(form.get("notiz") or "")})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/plan?monat={datum[:7]}", status_code=303)

    @ui._gesichert_seite
    async def aendern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        aktion = str(form.get("aktion") or "")
        if aktion == "verschieben":
            datum = datum_ok(form.get("datum"))
            if not datum:
                return ui._fehlerseite(422, "Nicht möglich", "Bitte ein gültiges neues Datum wählen.")
            daten = {"datum": datum}
        elif aktion in AKTIONEN:
            daten = {"status": AKTIONEN[aktion]}
        else:
            return ui._fehlerseite(422, "Nicht möglich", "Unbekannte Aktion.")
        pid = urllib.parse.quote(request.path_params["pid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/plan/{pid}", daten)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(zurueck_ziel(form), status_code=303)

    return [
        Route("/marketing/plan", plan),
        Route("/marketing/plan/neu", neu, methods=["POST"]),
        Route("/marketing/plan/{pid}", aendern, methods=["POST"]),
    ]
