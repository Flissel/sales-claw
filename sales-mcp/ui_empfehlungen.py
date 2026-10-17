"""Oberflaeche der Empfehlungslisten (C4): Uebersicht, Liste, PDF, Zeilen."""
import uuid
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import empfehlungen as em

_FELDER_ZEILE = ("vorname", "name", "beruf", "alter", "ort", "telefon",
                 "zeichnet_aus", "interessiert")
_HINWEIS_MAX = 300


def _uuid(w):
    try:
        return str(uuid.UUID(str(w)))
    except (ValueError, TypeError):
        return None


def _weiter(lid, hinweise):
    """Redirect zur Liste; Hinweise des Moduls reisen als kurzer Text mit
    (Anzeige immer escaped, siehe `seite`)."""
    ziel = f"/empfehlungen/{lid}" if lid else "/empfehlungen"
    text = " · ".join(h for h in (hinweise or []) if h)[:_HINWEIS_MAX]
    if text:
        ziel += f"?hinweis={quote(text)}"
    return RedirectResponse(ziel, status_code=303)


def routen(ui):
    e = ui._e

    @ui._gesichert_seite
    async def uebersicht(request):
        zeilen = [[
            e(f"{l['datum']:%d.%m.%Y}"),
            f'<a href="/empfehlungen/{e(l["id"])}">{e(em.VORDRUCKE[l["art"]]["titel"])}</a>',
            (f'<a href="/kontakte/{e(l["empfohlen_von_lead"])}">{e(l["empfohlen_von_name"])}</a>'
             if l["empfohlen_von_lead"] else e(l["empfohlen_von_name"])),
            e(l["anzahl"]), e(l["schon_bekannt"]), e(l["offen"]), e(l["termin"]),
            e(l["abschluss"])]
            for l in em.listen()]
        rumpf = (ui._tabelle(["Datum", "Vordruck", "Empfohlen von", "Anzahl", "schon bekannt",
                              "offen", "Termin", "Abschluss"], zeilen) if zeilen else
                 '<p class="meta">Noch keine Liste. Schick dem Agenten ein Foto einer '
                 'Pole Position oder einer Liste Mitarbeitervorschläge.</p>')
        return ui._seite("Empfehlungen", rumpf)

    @ui._gesichert_seite
    async def seite(request):
        lid = _uuid(request.path_params["liste_id"])
        l = em.liste(lid) if lid else None
        if l is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Liste gibt es nicht.")
        k, art = l["kopf"], l["kopf"]["art"]
        schreiben = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
        hinweis = str(request.query_params.get("hinweis") or "")[:_HINWEIS_MAX]
        flash = f'<div class="hinweis">{e(hinweis)}</div>' if hinweis else ""
        datum_text = f"{k['datum']:%d.%m.%Y}"
        kopf = (flash +
                f'<p class="meta">{e(em.VORDRUCKE[art]["untertitel"])}</p>'
                f'<p>Empfohlen von <b>{e(k["empfohlen_von_name"])}</b> · '
                f'{e(datum_text)} · '
                f'Name: {e(k["berater_name"])} · Struktur: {e(k["struktur"])} · '
                f'Einwilligung: {"ja" if k["einwilligung"] else "nein"}</p>'
                f'<p><a href="/empfehlungen/{e(lid)}/pdf">PDF</a></p>')
        spalten = (["Name", "Vorname", "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis"]
                   if art == "pole_position" else
                   ["Vorname, Name", "Alter (ab 22)", "Beruf", "Telefon", "Was zeichnet aus",
                    "Was interessiert", "Termin", "Ergebnis"])
        zeilen = []
        for z in l["zeilen"]:
            name = f'<a href="/kontakte/{e(z["lead_id"])}">{e(z["nachname"] or z["name"])}</a>'
            termin = (e(f"{z['termin_datum'][8:10]}.{z['termin_datum'][5:7]}.") if z["termin_datum"]
                      else (f'<a href="/kalender?neu=kunde&amp;lead_id={e(z["lead_id"])}">Termin</a>'
                            if schreiben and not z["fremd"] else ""))
            if z["fremd"]:
                wann = (f" (Liste vom {z['fremd_liste_datum']:%d.%m.%Y})"
                        if z["fremd_liste_datum"] else "")
                ergebnis = (f'schon bekannt{e(wann)} · '
                            f'<a href="/kontakte/{e(z["lead_id"])}">Kontakt</a>')
            elif schreiben:
                auswahl = "".join(
                    f'<option value="{s}"{" selected" if s == z["ergebnis"] else ""}>{e(t)}</option>'
                    for s, t in em.ERGEBNISSE.items())
                if z["einwilligung_widerrufen"]:
                    # Kontakt hat widerrufen/abbestellt: kein Haken; Speichern
                    # laesst die Einwilligung unberuehrt (siehe `zeile`).
                    haken = ('<input type="hidden" name="einwilligung" value="widerrufen">'
                             '<span class="meta">Einwilligung widerrufen</span> ')
                else:
                    haken = (f'<label><input type="checkbox" name="einwilligung" value="1"'
                             f'{" checked" if z["einwilligung"] else ""}> darf kontaktiert '
                             f'werden</label> ')
                ergebnis = (f'<form method="post" action="/empfehlungen/zeile">'
                            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
                            f'<input type="hidden" name="lead_id" value="{e(z["lead_id"])}">'
                            f'<input type="hidden" name="liste_id" value="{e(lid)}">'
                            f'<select name="ergebnis">{auswahl}</select> '
                            f'<input name="notiz" maxlength="200" value="{e(z["notiz"])}" placeholder="Notiz"> '
                            f'{haken}<button type="submit">Speichern</button></form>')
            else:
                ergebnis = e(z["ergebnis_text"]) + (f" · {e(z['notiz'])}" if z["notiz"] else "")
            if art == "pole_position":
                zeilen.append([name, e(z["vorname"]), e(z["beruf"]), e(z["alter"] or ""),
                               e(z["ort"]), e(z["telefon"]), termin, ergebnis])
            else:
                zeilen.append([name, e(z["alter"] or ""), e(z["beruf"]), e(z["telefon"]),
                               e(z["zeichnet_aus"]), e(z["interessiert"]), termin, ergebnis])
        neu = ""
        if schreiben:
            felder = "".join(f'<input name="{f}" placeholder="{f}" maxlength="200"> '
                             for f in _FELDER_ZEILE)
            neu = (f'<h2>Zeile hinzufügen</h2><div class="karte"><form method="post" '
                   f'action="/empfehlungen/{e(lid)}/zeile">'
                   f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">{felder}'
                   + ('<label><input type="checkbox" name="firma" value="1"> Firma</label> '
                      if art == "pole_position" else "") +
                   '<label><input type="checkbox" name="einwilligung" value="1"> '
                   'vorab gefragt (darf kontaktiert werden)</label> '
                   f'<button type="submit">Hinzufügen</button></form></div>')
        return ui._seite(em.VORDRUCKE[art]["titel"], kopf + ui._tabelle(spalten, zeilen) + neu)

    @ui._gesichert_seite
    async def pdf(request):
        lid = _uuid(request.path_params["liste_id"])
        b = em.pdf(lid) if lid else None
        if b is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Liste gibt es nicht.")
        return Response(b, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="empfehlungsliste-{lid[:8]}.pdf"'})

    @ui._gesichert_seite
    async def zeile(request):
        form, lead_id, abbruch = await ui._kontakt_vorspann(request)
        if abbruch:
            return abbruch
        lid = _uuid(form.get("liste_id"))
        if not lid:
            return ui._fehlerseite(422, "Nicht gespeichert", "Liste fehlt oder ist unbekannt.")
        ein = form.get("einwilligung")
        r = em.zeile_setzen(lead_id, ergebnis=str(form.get("ergebnis") or "offen"),
                            notiz=str(form.get("notiz") or "")[:200],
                            einwilligung=None if ein == "widerrufen" else ein == "1",
                            liste_id=lid, quelle="ui")
        if "fehler" in r:
            return ui._fehlerseite(422, "Nicht gespeichert", e(r["fehler"]))
        return _weiter(lid, r.get("hinweise"))

    @ui._gesichert_seite
    async def zeile_neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgelehnt", "Fehlende oder falsche CSRF-Marke.")
        lid = _uuid(request.path_params["liste_id"])
        z = {f: str(form.get(f) or "") for f in _FELDER_ZEILE}
        z["firma"] = form.get("firma") == "1"
        r = (em.zeile_hinzufuegen(lid, z, einwilligung=form.get("einwilligung") == "1",
                                  quelle="ui") if lid else {"fehler": "Liste unbekannt."})
        if "fehler" in r:
            return ui._fehlerseite(422, "Nicht hinzugefügt", e(r["fehler"]))
        return _weiter(lid, r.get("hinweise"))

    return [
        Route("/empfehlungen", uebersicht),
        Route("/empfehlungen/zeile", zeile, methods=["POST"]),
        Route("/empfehlungen/{liste_id}/pdf", pdf),
        Route("/empfehlungen/{liste_id}/zeile", zeile_neu, methods=["POST"]),
        Route("/empfehlungen/{liste_id}", seite),
    ]
