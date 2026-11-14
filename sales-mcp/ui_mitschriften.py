"""Hauptpunkt „Mitschriften“: Berichte der Kundentermine, nach Rubrik in Reitern.

`GET /mitschriften[?rubrik=]` zeigt die Reiter mit Anzahl und die Liste (neueste
zuerst); `GET /mitschriften/bericht?uid=[&download=1]` liefert die HTML-Datei aus
(nur angemeldet, mit eigener strenger CSP); `POST /mitschriften/verschieben`
legt eine Mitschrift von Hand in eine (auch neue) Rubrik. Die uid steht als
Query-/Formularwert (sie kann `@` oder `/` enthalten). Fremdtexte gehen ueber
html.escape. Logs: nur gekuerzte uid und Fehlerart."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import mitschrift_bericht as mb
import server
from ui_termin import _e

log = logging.getLogger("ui_mitschriften")

MAX_JE_REITER = 200
KURZ_MAX = 240
# Der Bericht ist ein eigenes Dokument: Bilder nur als data:-URI, kein Skript.
BERICHT_CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _json(wert) -> dict:
    if isinstance(wert, str):
        try:
            wert = json.loads(wert or "{}")
        except ValueError:
            return {}
    return wert if isinstance(wert, dict) else {}


def _kuerzen(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= KURZ_MAX else text[:KURZ_MAX].rstrip() + "…"


def _reiter_sortiert(zahlen: dict[str, int]) -> list[str]:
    namen = sorted((n for n in zahlen if n != mb.UNSORTIERT), key=str.casefold)
    return namen + ([mb.UNSORTIERT] if mb.UNSORTIERT in zahlen else [])


def _url(rubrik: str) -> str:
    return f"/mitschriften?rubrik={quote(rubrik, safe='')}"


def _zahlen() -> dict[str, int]:
    return {z["rubrik"]: int(z["n"]) for z in server._q(
        "select m.rubrik, count(*) as n from termin_mitschriften m "
        "join termin_akten a on a.uid = m.uid "
        "where m.auswertung_status = 'fertig' and m.rubrik is not null group by m.rubrik")}


def _eintraege(rubrik: str) -> list[dict]:
    return server._q(
        "select m.uid, m.rubrik, m.bericht_pfad, m.auswertung_json, a.titel, a.thema, a.beginn "
        "from termin_mitschriften m join termin_akten a on a.uid = m.uid "
        "where m.auswertung_status = 'fertig' and m.rubrik = %s "
        "order by a.beginn desc nulls last, m.id desc limit %s", (rubrik, MAX_JE_REITER))


def _karte(z: dict, rubriken: list[str], csrf: str | None) -> str:
    uid = z["uid"]
    aj = _json(z["auswertung_json"])
    titel = z["titel"] or z["thema"] or "Termin"
    datum = z["beginn"].astimezone(mb.TZ).strftime("%d.%m.%Y, %H:%M") if isinstance(
        z["beginn"], datetime) else "ohne Datum"
    beteiligte = aj.get("beteiligte")
    wer = ", ".join(str(b) for b in beteiligte if b) if isinstance(beteiligte, list) else ""
    kurz = _kuerzen(aj.get("kurzfassung") if isinstance(aj.get("kurzfassung"), str) else "")
    q = quote(uid, safe="")
    if z["bericht_pfad"]:
        aktionen = (f'<a class="knopf" href="/mitschriften/bericht?uid={q}">Bericht öffnen</a> '
                    f'<a href="/mitschriften/bericht?uid={q}&amp;download=1">'
                    'HTML herunterladen</a> ')
    else:
        aktionen = '<span class="meta">Bericht wird erstellt …</span> '
    aktionen += f'<a href="/termine/{q}">Akte</a>'
    verschieben = ""
    if csrf:
        optionen = "".join(
            f'<option value="{_e(r)}"{" selected" if r == z["rubrik"] else ""}>{_e(r)}</option>'
            for r in rubriken)
        verschieben = (
            '<form method="post" action="/mitschriften/verschieben" class="verschieben">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            f'<input type="hidden" name="uid" value="{_e(uid)}">'
            f'<label>Verschieben nach <select name="rubrik">{optionen}</select></label> '
            '<label>oder neue Rubrik <input type="text" name="neue_rubrik" maxlength="40"></label> '
            '<button type="submit">Verschieben</button></form>')
    return (f'<article class="karte"><h3>{_e(titel)}</h3>'
            f'<p class="meta">{_e(datum)}{" · " + _e(wer) if wer else ""}</p>'
            + (f'<p>{_e(kurz)}</p>' if kurz else "")
            + f'<p>{aktionen}</p>{verschieben}</article>')


def routen(ui) -> list:

    def _schreiben() -> bool:
        return ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")

    @ui._gesichert_seite
    async def seite(request):
        import ui_muster
        zahlen = _zahlen()
        namen = _reiter_sortiert(zahlen)
        if not namen:
            rumpf = ('<p class="meta">Noch keine Mitschriften. Berichte entstehen, sobald '
                     'ein Termin ausgewertet ist.</p>')
            return _kopfzeilen(ui._seite("Mitschriften", rumpf))
        aktiv = str(request.query_params.get("rubrik") or "")
        if aktiv not in zahlen:
            aktiv = namen[0]
        reiter = ui_muster.reiter([(n, n, zahlen[n]) for n in namen], aktiv, _url)
        karten = "".join(_karte(z, namen, ui.CSRF_TOKEN if _schreiben() else None) for z in _eintraege(aktiv))
        rumpf = (reiter + (karten or '<p class="meta">Keine Mitschriften in dieser Rubrik.</p>')
                 + ('<p class="meta">Berichte sind intern und enthalten Kundendaten. '
                    'Als PDF: Bericht aufrufen und im Browser drucken.</p>'))
        return _kopfzeilen(ui._seite("Mitschriften", rumpf))

    @ui._gesichert_seite
    async def bericht(request):
        uid = str(request.query_params.get("uid") or "")
        zeile = server._q("select bericht_pfad from termin_mitschriften where uid = %s",
                          (uid,)) if uid else []
        rel = zeile[0]["bericht_pfad"] if zeile else None
        ziel = mb.sicherer_pfad(rel) if rel else None
        inhalt = None
        if ziel is not None:
            try:
                inhalt = ziel.read_bytes() if ziel.is_file() else None
            except OSError as err:
                log.warning("Bericht nicht lesbar uid=%s (%s)", mb.uid8(uid), type(err).__name__)
        if inhalt is None:
            return ui._fehlerseite(404, "Nicht gefunden",
                                   "Zu dieser Mitschrift gibt es keinen Bericht (mehr).")
        koepfe = {"Cache-Control": "private, no-store", "Content-Security-Policy": BERICHT_CSP}
        if request.query_params.get("download"):
            koepfe["Content-Disposition"] = f'attachment; filename="{ziel.name}"'
        return Response(inhalt, media_type="text/html; charset=utf-8", headers=koepfe)

    @ui._gesichert_seite
    async def verschieben(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts verschoben. Die Seite neu laden und erneut versuchen.")
        if not _schreiben():
            return ui._fehlerseite(403, "Nur Lesen", "Diese Anmeldung darf nichts ändern.")
        uid = str(form.get("uid") or "")
        if not uid or not server._q("select 1 from termin_mitschriften where uid = %s", (uid,)):
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Mitschrift gibt es nicht (mehr).")
        roh = str(form.get("neue_rubrik") or "").strip() or str(form.get("rubrik") or "")
        if mb.rubrik_normalisieren(roh) is None:
            return ui._fehlerseite(400, "Rubrik ungültig",
                                   "Erlaubt sind Buchstaben, Ziffern, Leerzeichen und Bindestrich "
                                   "(höchstens 40 Zeichen). Nichts verschoben.")
        try:
            neu = mb.verschieben(uid, roh)
        except Exception as err:  # Rubrik ist gespeichert; der Takt legt die Datei neu an
            log.warning("Verschieben: Ablegen fehlgeschlagen uid=%s (%s)",
                        mb.uid8(uid), type(err).__name__)
            neu = mb.rubrik_normalisieren(roh)
            gespeichert = server._q("select rubrik from termin_mitschriften where uid = %s",
                                    (uid,))
            neu = gespeichert[0]["rubrik"] if gespeichert and gespeichert[0]["rubrik"] else neu
        if neu is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Mitschrift gibt es nicht (mehr).")
        return RedirectResponse(_url(neu), status_code=303)

    def _kopfzeilen(antwort):
        antwort.headers["Cache-Control"] = "private, no-store"
        return antwort

    return [Route("/mitschriften", seite, methods=["GET"]),
            Route("/mitschriften/bericht", bericht, methods=["GET"]),
            Route("/mitschriften/verschieben", verschieben, methods=["POST"])]
