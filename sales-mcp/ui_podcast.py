"""Podcast im Marketing-Pult (19.10.2026, Podcast-Seite).

Gleiche Form wie die Reels (ui_reels.py): bestellen koennen der Betreiber (hier) und der Marketing-Agent,
gebaut wird am PC vom Ton-Arbeiter, die fertige Folge liegt als pod-<id>-<titel>.mp3 in den Medien. Die Seite
zeigt Folgen, Bau-Stand, Freigabe-Stand (aus den Sales-Entwuerfen), Player und Skript. Es gibt KEINEN
Versand-Knopf (der Versand laeuft ueber den Assistenten) und KEIN Loeschen - Folgen lassen sich nur abbrechen.
Wie der Rest von sales-ui ohne JavaScript.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import marketing_mandant
import marketing_pult

STATUS = {"offen": "wartet", "in_arbeit": "wird gesprochen", "fertig": "fertig", "fehler": "Fehler",
          "abgebrochen": "abgebrochen"}
# Freigabe-Stand fertiger Folgen (Woerter wie ZUSTAND_TITEL in ui.py); ohne Entwurf: "noch kein Entwurf".
STAND = {"pending": "zur Freigabe", "approved": "freigegeben", "sent": "gesendet", "rejected": "abgelehnt",
         "failed": "fehlgeschlagen"}
KEIN_ENTWURF = "noch kein Entwurf"
STAND_UNLESBAR = "Freigabe-Stand gerade nicht lesbar"
STANDARD_SPRECHER = "Sprecher"
LIMIT = 50
_DATEI = re.compile(r"^pod-[0-9a-f]{8}-[a-z0-9-]{1,60}\.mp3$")
_SPRACHE = re.compile(r"^[a-z]{2}$")


def _sprecher_name(name: str) -> bool:
    """Name aus Buchstaben, Punkt, Bindestrich und Leerzeichen, hoechstens 30 Zeichen."""
    n = name.strip()
    return 1 <= len(n) <= 30 and any(c.isalpha() for c in n) and all(
        c.isalpha() or c in ". -" for c in n)


def skript_aus_text(text: str, standard: str) -> list[dict[str, str]]:
    """Zeilen "Name: Text" -> Abschnitte {sprecher, text}. Leerzeilen entfallen. Als Name gilt nur, was vor
    dem ersten ':' steht, hoechstens 30 Zeichen lang ist und aus Buchstaben/Punkt/Bindestrich/Leerzeichen
    besteht - sonst geht die ganze Zeile an `standard`. Ein Web-Link ("Siehe https://x") ist kein Sprecher."""
    aus: list[dict[str, str]] = []
    for zeile in str(text or "").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        kopf, doppelpunkt, rest = zeile.partition(":")
        if doppelpunkt and _sprecher_name(kopf) and rest.strip() and not rest.startswith("//"):
            aus.append({"sprecher": kopf.strip(), "text": rest.strip()})
        else:
            aus.append({"sprecher": standard, "text": zeile})
    return aus


def _dauer(sekunden) -> str:
    try:
        s = int(round(float(sekunden)))
    except (TypeError, ValueError):
        return ""
    return f"{s // 60}:{s % 60:02d}" if s >= 0 else ""


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

    def chip(text: str, klasse: str = "") -> str:
        return f'<span class="plan-chip {klasse}">{e(text)}</span>'

    def datum(roh) -> str:
        try:
            return datetime.fromisoformat(str(roh)).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return str(roh or "")[:16]

    def zeile(a: dict, staende: dict | None) -> str:
        aid_url = e(urllib.parse.quote(str(a.get("id") or ""), safe=""))
        status = str(a.get("status") or "")
        datei = str(a.get("datei") or "")
        gueltig = bool(_DATEI.fullmatch(datei))
        skript = [x for x in (a.get("skript") if isinstance(a.get("skript"), list) else []) if isinstance(x, dict)]
        sprecher = list(dict.fromkeys(str(x.get("sprecher") or "") for x in skript if x.get("sprecher")))
        klasse = {"fertig": "erledigt", "in_arbeit": "gesprochen", "fehler": "fehler"}.get(status, "abgebrochen"
                                                                                       if status == "abgebrochen" else "")
        chips = [chip(STATUS.get(status, status), klasse)]
        if status == "fertig" and gueltig:
            if staende is None:
                chips.append(chip(STAND_UNLESBAR))
            else:
                roh = staende.get(datei)
                chips.append(chip(STAND.get(roh, roh) if roh else KEIN_ENTWURF,
                                  "erledigt" if roh in ("approved", "sent") else
                                  "verschoben" if roh in ("failed", "rejected") else
                                  "vorschlag" if roh == "pending" else ""))
        teile = []
        if status == "fertig" and gueltig:
            quelle = f"/medien/datei/{e(urllib.parse.quote(datei, safe=''))}"
            laenge = _dauer(a.get("dauer_s"))
            teile.append(f'<audio controls preload="none" src="{quelle}"></audio>'
                         f'<p><small>{e(datei)}{" · " + e(laenge) + " min" if laenge else ""}</small></p>')
        elif status == "fertig":
            teile.append('<p class="fehler"><small>Datei nicht abspielbar</small></p>')
        if a.get("befund"):
            teile.append(f'<p class="fehler"><small>{e(str(a["befund"]))}</small></p>')
        if skript:
            text = "\n".join(f'{x.get("sprecher") or ""}: {x.get("text") or ""}' for x in skript)
            teile.append(f"<details><summary>Skript</summary><pre>{e(text)}</pre></details>")
        if status in ("offen", "in_arbeit"):
            teile.append(f'<form method="post" action="/marketing/podcast/{aid_url}/abbrechen" class="aktion">'
                         f'{csrf()}<button type="submit">Abbrechen</button></form>')
        von = "Agent" if a.get("angelegt_von") == "agent" else "Betreiber"
        meta = " · ".join(x for x in (e(datum(a.get("erstellt_am"))), e(str(a.get("sprache") or "")), von) if x)
        if sprecher:
            meta += f' · Sprecher: {e(", ".join(sprecher))}'
        return (f'<article class="plan-karte pod-karte"><div class="plan-chips">{"".join(chips)}</div>'
                f'<p class="plan-titel"><b>{e(str(a.get("titel") or ""))}</b></p>'
                f'<p class="plan-notiz"><small>{meta}</small></p>{"".join(teile)}</article>')

    @ui._gesichert_seite
    async def podcast(request):
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        "/ton?" + urllib.parse.urlencode({"mandant": m, "limit": LIMIT}))
        except marketing_pult.PultFehler as f:
            return fehler(f)
        auftraege = [a for a in (d.get("auftraege") if isinstance(d, dict) else None) or [] if isinstance(a, dict)]
        fertige = [str(a.get("datei")) for a in auftraege
                   if a.get("status") == "fertig" and _DATEI.fullmatch(str(a.get("datei") or ""))]
        staende: dict | None = {}
        if fertige:
            try:
                staende = await run_in_threadpool(ui.server.entwurf_staende_zu_medien, fertige)
            except Exception:  # noqa: BLE001 - ohne Stand bleibt die Seite brauchbar
                ui.LOG.warning("Podcast: Freigabe-Stand nicht lesbar", exc_info=True)
                staende = None
        karten = "".join(zeile(a, staende) for a in auftraege) or (
            '<div class="plan-leer"><p>Noch keine Folgen.</p></div>')
        formular = (
            f'<section class="plan-form"><h2>Neue Folge</h2>'
            f'<form method="post" action="/marketing/podcast/neu">{csrf()}'
            '<div class="pod-zeile"><label>Titel <input type="text" name="titel" required maxlength="120"></label>'
            '<label>Sprache <input type="text" name="sprache" value="de" maxlength="2" '
            'pattern="[a-z]{2}" required></label></div>'
            f'<label>Standardsprecher (für Zeilen ohne „Name:“) <input type="text" name="sprecher" '
            f'value="{STANDARD_SPRECHER}" maxlength="30" required></label>'
            '<label>Skript (eine Zeile je Abschnitt: „Name: Text“) '
            '<textarea name="skript" rows="10" required></textarea></label>'
            '<button type="submit">Folge bestellen</button></form>'
            '<ul class="pod-hinweis">'
            '<li>Eine Folge dauert bis etwa 12 Minuten, ein Absatz hat höchstens 1000 Zeichen.</li>'
            '<li>Stimme: KI. Gesprochen wird am PC, das dauert einige Minuten.</li>'
            '<li>Zum Versenden den Assistenten bitten. Der Stand der Freigabe steht danach an der Folge.</li>'
            '<li>Folgen lassen sich nicht löschen, nur abbrechen, solange sie nicht fertig sind.</li></ul>'
            '</section>')
        liste_html = ('<div class="pod-kopf"><h2>Folgen</h2>'
                      '<a href="/marketing/podcast">Aktualisieren</a></div>' + karten)
        return ui._seite("Podcast", marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, "/marketing/podcast")
                         + f'<div class="plan-spalten"><div>{liste_html}</div>{formular}</div>')

    @ui._gesichert_seite
    async def neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        titel = str(form.get("titel") or "").strip()
        sprache = str(form.get("sprache") or "de").strip() or "de"
        standard = str(form.get("sprecher") or "").strip() or STANDARD_SPRECHER
        if not titel or len(titel) > 120:
            return ui._fehlerseite(422, "Nicht möglich", "Ein Titel mit höchstens 120 Zeichen ist nötig.")
        if not _SPRACHE.fullmatch(sprache):
            return ui._fehlerseite(422, "Nicht möglich", "Die Sprache besteht aus zwei Kleinbuchstaben, z. B. de.")
        if not _sprecher_name(standard):
            return ui._fehlerseite(422, "Nicht möglich",
                                   "Der Standardsprecher besteht aus Buchstaben und hat höchstens 30 Zeichen.")
        skript = skript_aus_text(str(form.get("skript") or ""), standard)
        if not skript:
            return ui._fehlerseite(422, "Nicht möglich", "Das Skript ist leer.")
        try:
            m, _ = await marketing_mandant.firma(request)
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/ton",
                                    {"mandant": m, "titel": titel, "sprache": sprache, "skript": skript})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/podcast", status_code=303)

    @ui._gesichert_seite
    async def abbrechen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        aid = urllib.parse.quote(request.path_params["aid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/ton/{aid}/abbrechen", {})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/podcast", status_code=303)

    return [
        Route("/marketing/podcast", podcast),
        Route("/marketing/podcast/neu", neu, methods=["POST"]),
        Route("/marketing/podcast/{aid}/abbrechen", abbrechen, methods=["POST"]),
    ]
