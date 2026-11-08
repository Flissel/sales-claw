"""Abschnitt "Eingang" auf /freigaben (Plan 2026-11-08, Task 6).

Zeigt, was Dienste im Freigabe-Eingang abgelegt haben (Debugger-PRs, Selbstbild-
Rueckfragen, Kursfreigaben) samt Rowboat-Vermerk, und bietet je Art die Knoepfe.
Kein JavaScript, CSRF-Marke in jedem Formular. Eintraege der Art `entwurf` stehen
schon als Entwurfskarte da; sie bekommen nur den Vermerk (`rowboat_vermerk`) und
den Sprungpunkt fuer den Sales-Link in Rowboat (`/freigaben#<kennung>`).

Stufe 2 (Annehmen in Rowboat fuehrt aus) ist je Art aus und gesperrt; die Route
antwortet immer 409 und aendert nichts. `ui` wird nie importiert, sondern bei
`abschnitt(ui, ...)` / `routen(ui)` hereingereicht.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

import psycopg
from starlette.responses import RedirectResponse
from starlette.routing import Route

import freigabe_eingang as fe
import server

LOG = logging.getLogger("sales-ui")

_ROWBOAT_TEXT = {
    "ungesichtet": "noch nicht gesichtet",
    "vorgeschlagen": "noch nicht gesichtet",
    "angenommen": "in Rowboat angenommen",
    "abgelehnt": "in Rowboat abgelehnt",
    "abgehakt": "in Rowboat abgehakt",
}
_ART_NAME = {
    "debugger_pr": "Debugger-PRs",
    "selbstbild_rueckfrage": "Selbstbild-Rückfragen",
    "kursfreigabe": "Kursfreigaben",
    "entwurf": "Entwürfe",
}
_LABEL_KNOEPFE = (("antwort:weg", "kann weg"), ("antwort:bleibt", "soll bleiben"),
                  ("antwort:benutzt", "wird benutzt"))
_QUELLE = re.compile(r"^(?P<repo>[^#\s]+)#(?P<nummer>[0-9]{1,9})$")
_HINWEISE = {
    "auftrag": ("hinweis", "Auftrag angelegt – der PC holt ihn ab."),
    "verworfen": ("hinweis", "Eintrag verworfen."),
    "geschlossen": ("warnung", "Dieser Eintrag ist schon abgeschlossen. Es wurde kein Auftrag angelegt."),
    "abgewiesen": ("warnung", "Der Auftrag wurde abgewiesen (falsche Art oder es läuft schon einer). "
                              "Nichts wurde getan."),
    "quelle": ("warnung", "Die Quelle des Eintrags ist nicht lesbar. Nichts wurde getan."),
}

def rowboat_text(stand) -> str:
    return _ROWBOAT_TEXT.get(stand, "noch nicht gesichtet")


def rowboat_vermerk(draft_id) -> str:
    """Fuer die Entwurfskarte: Sprungpunkt mit der Kennung (Ziel des Sales-Links in Rowboat)
    und der Rowboat-Stand; "" ohne offenen Eintrag oder solange die Tabelle fehlt."""
    try:
        z = server._q("select kennung, rowboat_stand from freigabe_eintraege "
                      "where draft_id = %s and art = 'entwurf' and status = 'offen' "
                      "order by erstellt_am desc limit 1", (str(draft_id),))
    except psycopg.errors.UndefinedTable:
        return ""
    except psycopg.errors.InvalidTextRepresentation:
        return ""
    if not z:
        return ""
    return (f'<span id="{z[0]["kennung"]}"></span>'
            f'<div class="meta">Rowboat: {rowboat_text(z[0]["rowboat_stand"])}</div>')


def _hinweis(ui, request) -> str:
    code = request.query_params.get("eg_hinweis") if request is not None else None
    if code in _HINWEISE:
        klasse, text = _HINWEISE[code]
        return f'<div class="{klasse}">{text}</div>'
    return ""


def _knopf(ui, aktion: str, kennung: str, text: str, klasse: str = "", **extra) -> str:
    felder = "".join(f'<input type="hidden" name="{n}" value="{ui._e(w)}">'
                     for n, w in extra.items())
    return (f'<form class="aktion {klasse}" method="post" action="/aktion/{aktion}">'
            f'<input type="hidden" name="kennung" value="{ui._e(kennung)}">'
            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
            f'{felder}<button class="{klasse}">{text}</button></form>')


def _karte(ui, e: dict, auftrag: dict | None, darf: bool) -> str:
    e_ = ui._e
    kennung = e["kennung"]
    art = e["art"]
    herkunft = fe.HERKUNFT_ANZEIGE.get(e["herkunft"], e["herkunft"])
    details = e["details"] if isinstance(e.get("details"), dict) else {}
    teile = [f'<div class="karte" id="{kennung}">',
             f'<div><b>{e_(herkunft)}</b> · {e_(e["titel"])}</div>']
    if e.get("link"):
        text = "auf GitHub ansehen" if art == "debugger_pr" else "Ansehen"
        teile.append(f'<div><a href="{e_(e["link"])}" target="_blank" rel="noopener">{text}</a></div>')
    if art == "debugger_pr" and details.get("tests") not in (None, ""):
        teile.append(f'<div class="meta">Teststand: {e_(str(details["tests"])[:200])}</div>')
    teile.append(f'<div class="meta">Rowboat: {rowboat_text(e["rowboat_stand"])}</div>')
    if e.get("vermerk"):
        teile.append(f'<div class="meta">{e_(e["vermerk"])}</div>')
    wartet = bool(auftrag and auftrag["status"] in ("offen", "laeuft"))
    if auftrag and auftrag["status"] == "fehler":
        teile.append(f'<div class="fehler">fehlgeschlagen: {e_(auftrag["fehler"] or "ohne Angabe")}</div>')
    if wartet:
        teile.append('<div class="meta">wartet auf PC</div>')
    elif darf:
        knoepfe = []
        if art == "selbstbild_rueckfrage":
            knoepfe += [_knopf(ui, "eingang-label", kennung, text, label=label)
                        for label, text in _LABEL_KNOEPFE]
        elif art == "kursfreigabe":
            knoepfe.append(_knopf(ui, "eingang-kurs", kennung, "Freigabe-Seite schicken"))
        knoepfe.append(_knopf(ui, "eingang-verwerfen", kennung, "verwerfen", "gefahr"))
        teile.append(f'<div class="aktionen">{"".join(knoepfe)}</div>')
    teile.append("</div>")
    return "".join(teile)


def _stufe2(stufe2: dict) -> str:
    zeilen = "".join(
        f'<li><label class="haken"><input type="checkbox" disabled'
        f'{" checked" if stufe2.get(a) else ""}> Annehmen in Rowboat führt aus '
        f'({name})</label> <span class="meta">gesperrt, bis nur ein Klick des Betreibers zählt</span></li>'
        for a, name in _ART_NAME.items())
    return f'<h3>Stufe 2</h3><ul class="stufe2">{zeilen}</ul>'


async def abschnitt(ui, request=None) -> str:
    """HTML des Abschnitts "Eingang"; "" solange die Tabellen fehlen."""
    try:
        eintraege = [e for e in fe.offene() if e["art"] != "entwurf"]
        auftraege = fe.letzte_auftraege()
        stufe2 = fe.stufe2_lesen()
    except psycopg.errors.UndefinedTable:
        return ""
    darf = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
    n = len(eintraege)
    karten = "".join(_karte(ui, e, auftraege.get(str(e["id"])), darf) for e in eintraege)
    leer = '' if n else '<p class="meta">Im Eingang wartet nichts auf dich.</p>'
    return (f'<section class="block" id="eingang"><h2>Eingang '
            f'<span class="zaehler{" offen" if n else ""}">{n}</span></h2>'
            f'{_hinweis(ui, request)}{leer}{karten}{_stufe2(stufe2)}</section>')


def routen(ui) -> list:
    def ziel(code: str) -> RedirectResponse:
        return RedirectResponse(
            f"/freigaben?{urllib.parse.urlencode({'eg_hinweis': code})}#eingang", status_code=303)

    async def formular(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return None, ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        return form, None

    def offener(kennung):
        z = server._q("select kennung, art, status, quelle_ref, details from freigabe_eintraege "
                      "where kennung = %s", (kennung,)) if fe._KENNUNG_RE.match(kennung) else []
        return z[0] if z and z[0]["status"] == "offen" else None

    def anlegen(request, kennung, art, nutzlast):
        try:
            fe.auftrag_anlegen(kennung, art, nutzlast, ui._ui_akteur(request))
        except fe.EingabeFehler:
            return ziel("abgewiesen")
        return ziel("auftrag")

    @ui._gesichert_seite
    async def label(request):
        form, fehler = await formular(request)
        if fehler is not None:
            return fehler
        kennung, wahl = str(form.get("kennung") or ""), str(form.get("label") or "")
        if wahl not in fe._LABELS:
            return ui._fehlerseite(422, "Abgewiesen", "Unbekanntes Label. Nichts wurde getan.")
        e = offener(kennung)
        if e is None:
            return ziel("geschlossen")
        treffer = _QUELLE.match(str(e["quelle_ref"]))
        if e["art"] != "selbstbild_rueckfrage" or not treffer:
            return ziel("quelle" if e["art"] == "selbstbild_rueckfrage" else "abgewiesen")
        return anlegen(request, kennung, "selbstbild_label",
                       {"repo": treffer["repo"], "nummer": int(treffer["nummer"]), "label": wahl})

    @ui._gesichert_seite
    async def kurs(request):
        form, fehler = await formular(request)
        if fehler is not None:
            return fehler
        kennung = str(form.get("kennung") or "")
        e = offener(kennung)
        if e is None:
            return ziel("geschlossen")
        details = e["details"] if isinstance(e["details"], dict) else {}
        kurs_id = details.get("course_id")
        if e["art"] != "kursfreigabe" or not isinstance(kurs_id, str) or not kurs_id:
            return ziel("quelle" if e["art"] == "kursfreigabe" else "abgewiesen")
        return anlegen(request, kennung, "kurs_freigabe_zeigen", {"course_id": kurs_id})

    @ui._gesichert_seite
    async def verwerfen(request):
        form, fehler = await formular(request)
        if fehler is not None:
            return fehler
        ok = fe.schliessen_kennung(str(form.get("kennung") or ""), "verworfen",
                                   ui._ui_akteur(request))
        return ziel("verworfen" if ok else "geschlossen")

    @ui._gesichert_seite
    async def stufe2(request):
        _, fehler = await formular(request)
        if fehler is not None:
            return fehler
        return ui._fehlerseite(409, "Gesperrt", "Stufe 2 ist gesperrt, bis nur ein Klick des "
                                                "Betreibers zählt. Nichts wurde geändert.")

    return [Route("/aktion/eingang-label", label, methods=["POST"]),
            Route("/aktion/eingang-kurs", kurs, methods=["POST"]),
            Route("/aktion/eingang-verwerfen", verwerfen, methods=["POST"]),
            Route("/aktion/eingang-stufe2", stufe2, methods=["POST"])]
