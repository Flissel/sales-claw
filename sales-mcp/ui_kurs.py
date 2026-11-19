"""Kurse und Handbuecher in der Mitschriften-Oberflaeche (Task 7).

Dateirouten: `/mitschriften/kurs` (HTML Felix/Lernende), `/mitschriften/kurs.pdf`,
`/mitschriften/handbuch`, `/mitschriften/handbuch.pdf` - geliefert wird die abgelegte Datei,
der Pfad kommt nur aus der DB und nur unter dem Mitschriften-Ordner (wie
`/mitschriften/bericht`). Schreibend (CSRF, nicht fuer `lesen`/`kalender`): Lernenden
setzen/suchen, Kapitel umbenennen/umsortieren, Handbuch ausgeben. Nichts wird versendet.
Fremdtexte gehen ueber html.escape; Logs nur uid8/lead8 und Anzahlen, nie Namen."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import kurs_handbuch
import kurs_mitschrift
import kurs_pdf
import mitschrift_bericht as mb
import server
from ui_termin import _e

log = logging.getLogger("ui_kurs")

DATEI_CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
TITEL_MAX = 80
SUCHE_MAX = 80
MAX_TREFFER = 20
MAX_HANDBUECHER = 100


def status_text(z: dict) -> str:
    """Status-Text einer Kurs-Mitschrift (nur Rubrik Kurse)."""
    if z.get("kurs_status") == "fertig":
        text = "fertig"
    elif z.get("kurs_status") == "fehler":
        text = "Fehler"
    else:
        text = "wird erzeugt"
    if not z.get("kurs_lead_id"):
        text += " · Lernenden wählen"
    return text


def kurs_block(z: dict, csrf: str | None) -> str:
    """Zusatz der Karte in der Rubrik Kurse: Links, Status, Lernenden-Wahl."""
    uid = z["uid"]
    q = quote(uid, safe="")
    links = []
    if z.get("kurs_pfad"):
        links.append(f'<a class="knopf" href="/mitschriften/kurs?uid={q}&amp;fassung=felix">'
                     'Kursmitschrift (Felix)</a>')
    if z.get("kurs_pfad_lernend"):
        links.append(f'<a href="/mitschriften/kurs?uid={q}&amp;fassung=lernend">'
                     'Kursmitschrift (Lernende)</a> '
                     f'<a href="/mitschriften/kurs?uid={q}&amp;fassung=lernend&amp;download=1">'
                     'herunterladen</a>')
    if z.get("kurs_pdf"):
        links.append(f'<a href="/mitschriften/kurs.pdf?uid={q}">Kursmitschrift PDF</a>')
    name = z.get("kurs_lead_name")
    teile = [f'<p class="meta">Kurs: {_e(status_text(z))}</p>']
    if links:
        teile.append("<p>" + " ".join(links) + "</p>")
    teile.append(f'<p class="meta">Lernende/r: {_e(name) if name else "noch nicht gewählt"}</p>')
    if csrf:
        optionen = ['<option value="">– keiner –</option>']
        gesehen: set[str] = set()
        aktuell = str(z["kurs_lead_id"]) if z.get("kurs_lead_id") else None
        liste = kurs_mitschrift.vorschlaege(uid)
        if aktuell and aktuell not in {v["lead_id"] for v in liste}:
            liste = [{"lead_id": aktuell, "name": name}] + liste
        for v in liste:
            if v["lead_id"] in gesehen:
                continue
            gesehen.add(v["lead_id"])
            sel = " selected" if v["lead_id"] == aktuell else ""
            optionen.append(f'<option value="{_e(v["lead_id"])}"{sel}>'
                            f'{_e(v["name"] or "ohne Namen")}</option>')
        teile.append(
            '<form method="post" action="/mitschriften/kurs/lernender" class="verschieben">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            f'<input type="hidden" name="uid" value="{_e(uid)}">'
            f'<label>Lernende/r <select name="lead_id">{"".join(optionen)}</select></label> '
            '<button type="submit">Speichern</button></form>'
            '<form method="post" action="/mitschriften/kurs/suche" class="verschieben">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            f'<input type="hidden" name="uid" value="{_e(uid)}">'
            f'<label>oder Kontakt suchen <input type="text" name="q" maxlength="{SUCHE_MAX}">'
            '</label> <button type="submit">Suchen</button></form>')
    return '<div class="kurs">' + "".join(teile) + "</div>"


def _tag(t: datetime | None) -> str:
    return t.astimezone(mb.TZ).strftime("%d.%m.%Y") if isinstance(t, datetime) else ""


def _iso_tag(t: datetime | None) -> str:
    t = t if isinstance(t, datetime) else datetime.now(mb.TZ)
    return t.astimezone(mb.TZ).strftime("%Y-%m-%d")


def handbuch_zahl() -> int:
    z = server._q("select count(distinct lead_id) as n from kurs_handbuch_kapitel")
    return int(z[0]["n"]) if z else 0


def _handbuecher_rumpf(csrf: str | None) -> str:
    leads = server._q(
        "select l.id, l.name, h.pfad, h.pdf, h.stand_am from leads l "
        "left join kurs_handbuch h on h.lead_id = l.id "
        "where exists (select 1 from kurs_handbuch_kapitel k where k.lead_id = l.id) "
        "order by l.name nulls last, l.id limit %s", (MAX_HANDBUECHER,))
    if not leads:
        return ('<p class="meta">Noch keine Handbücher. Sie entstehen aus Kursmitschriften '
                'mit gewähltem Lernenden.</p>')
    teile = []
    for lead in leads:
        lid = str(lead["id"])
        kap = server._q(
            "select k.id, k.titel, k.aktuelle_fassung, f.quellen, "
            "(select count(*) from kurs_handbuch_fassung x where x.kapitel_id = k.id) as n "
            "from kurs_handbuch_kapitel k "
            "left join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung "
            "where k.lead_id = %s order by k.reihenfolge, k.erstellt_am", (lid,))
        sitzungen = {u for k in kap for u in (k["quellen"] or [])}
        beginne = kurs_handbuch.sitzungs_beginne(sorted(sitzungen))
        stand = _tag(lead["stand_am"]) or "noch nicht ausgegeben"
        n = len(sitzungen)
        aktionen = []
        if lead["pfad"]:
            aktionen.append(f'<a class="knopf" href="/mitschriften/handbuch?lead={lid}">'
                            'Handbuch öffnen</a>')
        if lead["pdf"]:
            aktionen.append(f'<a href="/mitschriften/handbuch.pdf?lead={lid}">'
                            'PDF herunterladen</a>')
        if csrf:
            aktionen.append(
                '<form method="post" action="/mitschriften/handbuch/ausgeben" class="verschieben">'
                f'<input type="hidden" name="csrf" value="{csrf}">'
                f'<input type="hidden" name="lead" value="{lid}">'
                '<button type="submit">Handbuch neu ausgeben</button></form>')
        zeilen = []
        for k in kap:
            kid = str(k["id"])
            if k["aktuelle_fassung"] is None:
                zeilen.append(f'<li>{_e(k["titel"])} '
                              '<span class="meta">– wird neu aufgebaut</span></li>')
                continue
            tage = sorted({beginne[u].astimezone(mb.TZ).date() for u in (k["quellen"] or [])
                           if u in beginne})
            woher = ("aus Sitzungen vom " + ", ".join(t.strftime("%d.%m.%Y") for t in tage)) \
                if tage else ""
            fassungen = int(k["n"])
            meta = " · ".join(x for x in (
                woher, f"{fassungen} Fassung" + ("" if fassungen == 1 else "en")) if x)
            form = ""
            if csrf:
                form = (
                    '<form method="post" action="/mitschriften/handbuch/kapitel" '
                    'class="verschieben">'
                    f'<input type="hidden" name="csrf" value="{csrf}">'
                    f'<input type="hidden" name="lead" value="{lid}">'
                    f'<input type="hidden" name="kapitel_id" value="{kid}">'
                    f'<input type="text" name="titel" value="{_e(k["titel"])}" '
                    f'maxlength="{TITEL_MAX}" aria-label="Kapiteltitel"> '
                    '<button type="submit" name="aktion" value="umbenennen">Umbenennen</button> '
                    '<button type="submit" name="aktion" value="hoch">Nach oben</button> '
                    '<button type="submit" name="aktion" value="runter">Nach unten</button>'
                    '</form>')
            zeilen.append(f'<li>{_e(k["titel"])} <span class="meta">– {_e(meta)}</span>{form}</li>')
        teile.append(
            f'<article class="karte"><h3>{_e(lead["name"] or "Ohne Namen")}</h3>'
            f'<p class="meta">Stand: {_e(stand)} · {n} Sitzung{"" if n == 1 else "en"}</p>'
            f'<p>{" ".join(aktionen)}</p><ol>{"".join(zeilen)}</ol></article>')
    return "".join(teile)


def _datei_lesen(rel: str | None, kennung: str):
    ziel = mb.sicherer_pfad(rel) if rel else None
    if ziel is None:
        return None
    try:
        return ziel.read_bytes() if ziel.is_file() else None
    except OSError as err:
        log.warning("Datei nicht lesbar %s (%s)", kennung, type(err).__name__)
        return None


def routen(ui, leiste) -> list:
    """`leiste(aktiv)` liefert die Reiterleiste der Mitschriften-Seite."""

    def _schreiben() -> bool:
        return ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")

    def _pruefen(form):
        """None, wenn Schreiben erlaubt ist; sonst die Fehlerseite."""
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts geändert. Die Seite neu laden und erneut versuchen.")
        if not _schreiben():
            return ui._fehlerseite(403, "Nur Lesen", "Diese Anmeldung darf nichts ändern.")
        return None

    def _nicht_gefunden(text="Das gibt es nicht (mehr)."):
        return ui._fehlerseite(404, "Nicht gefunden", text)

    def _datei(inhalt, medientyp, name, download):
        koepfe = {"Cache-Control": "private, no-store", "Content-Security-Policy": DATEI_CSP,
                  "X-Content-Type-Options": "nosniff"}
        if download:
            koepfe["Content-Disposition"] = f'attachment; filename="{name}"'
        return Response(inhalt, media_type=medientyp, headers=koepfe)

    def _seite_kurs(titel, rumpf):
        antwort = ui._seite(titel, rumpf)
        antwort.headers["Cache-Control"] = "private, no-store"
        return antwort

    @ui._gesichert_seite
    async def kurs(request):
        uid = str(request.query_params.get("uid") or "")
        fassung = str(request.query_params.get("fassung") or "")
        if fassung not in kurs_mitschrift.FASSUNGEN:
            return _nicht_gefunden("Diese Fassung gibt es nicht.")
        spalte = "kurs_pfad" if fassung == "felix" else "kurs_pfad_lernend"
        z = server._q(f"select {spalte} as rel from termin_mitschriften where uid = %s",
                      (uid,)) if uid else []
        inhalt = _datei_lesen(z[0]["rel"] if z else None, f"uid={mb.uid8(uid)}")
        if inhalt is None:
            return _nicht_gefunden("Zu dieser Mitschrift gibt es keine Kursmitschrift (mehr).")
        name = mb.sicherer_pfad(z[0]["rel"]).name
        return _datei(inhalt, "text/html; charset=utf-8", name,
                      bool(request.query_params.get("download")))

    @ui._gesichert_seite
    async def kurs_pdf_route(request):
        uid = str(request.query_params.get("uid") or "")
        z = server._q("select m.kurs_pdf as rel, a.beginn from termin_mitschriften m "
                      "join termin_akten a on a.uid = m.uid where m.uid = %s",
                      (uid,)) if uid else []
        inhalt = _datei_lesen(z[0]["rel"] if z else None, f"uid={mb.uid8(uid)}")
        if inhalt is None:
            return _nicht_gefunden("Zu dieser Mitschrift gibt es kein PDF (mehr).")
        return _datei(inhalt, "application/pdf",
                      f"Kursmitschrift_{_iso_tag(z[0]['beginn'])}.pdf", True)

    @ui._gesichert_seite
    async def lernender(request):
        form = await request.form()
        fehler = _pruefen(form)
        if fehler:
            return fehler
        uid = str(form.get("uid") or "")
        z = server._q("select rubrik from termin_mitschriften where uid = %s",
                      (uid,)) if uid else []
        if not z or not kurs_mitschrift.ist_kurs(z[0]["rubrik"]):
            return _nicht_gefunden("Diese Kurs-Mitschrift gibt es nicht (mehr).")
        roh = str(form.get("lead_id") or "").strip()
        # Sperren und Rueckbau des alten Handbuchs: nicht auf der Ereignisschleife
        if not await asyncio.to_thread(kurs_mitschrift.lernender_setzen, uid, roh or None):
            lid = kurs_handbuch.gueltige_id(roh) if roh else None
            if roh and (lid is None or not server._q("select 1 from leads where id = %s",
                                                      (lid,))):
                return ui._fehlerseite(400, "Lernende/r ungültig",
                                       "Diesen Kontakt gibt es nicht. Nichts geändert.")
            if lid and kurs_mitschrift.lernender_gesperrt(lid):
                return ui._fehlerseite(400, "Kontakt gesperrt",
                                       "Für diesen Kontakt liegt ein Löschantrag oder eine "
                                       "Sperre (Verbotsliste) vor; er wird nicht mehr "
                                       "verarbeitet und kann nicht Lernende/r sein. "
                                       "Nichts geändert.")
            return ui._fehlerseite(409, "Nicht mehr in „Kurse“",
                                   "Diese Mitschrift gehört nicht mehr zur Rubrik Kurse. "
                                   "Nichts geändert.")
        log.info("Lernende/r %s uid=%s", "gesetzt" if roh else "entfernt", mb.uid8(uid))
        return RedirectResponse(f"/mitschriften?rubrik={quote(z[0]['rubrik'], safe='')}",
                                status_code=303)

    @ui._gesichert_seite
    async def suche(request):
        form = await request.form()
        fehler = _pruefen(form)
        if fehler:
            return fehler
        uid = str(form.get("uid") or "")
        z = server._q("select rubrik from termin_mitschriften where uid = %s",
                      (uid,)) if uid else []
        if not z or not kurs_mitschrift.ist_kurs(z[0]["rubrik"]):
            return _nicht_gefunden("Diese Kurs-Mitschrift gibt es nicht (mehr).")
        text = " ".join(str(form.get("q") or "").split())[:SUCHE_MAX]
        zurueck = (f'<p><a href="/mitschriften?rubrik={quote(z[0]["rubrik"], safe="")}">'
                   'Zurück zur Liste</a></p>')
        if not text:
            return _seite_kurs("Mitschriften",
                               '<p class="meta">Bitte einen Namen eingeben.</p>' + zurueck)
        muster = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        # ohne Kontakte mit Loeschantrag (gleich in SQL, damit sie keine Treffer belegen) und
        # ohne gesperrte (Verbotsliste); beides wie kurs_mitschrift.lernender_gesperrt
        treffer = server._q(
            "select id, name from leads where name ilike %s "
            "and jsonb_typeof(coalesce(enrichment, '{}'::jsonb) -> %s::text) is distinct from "
            "'object' order by name, id limit %s",
            (muster, server.LOESCH_SCHLUESSEL, MAX_TREFFER))
        treffer = [t for t in treffer
                   if not kurs_mitschrift.lernender_gesperrt(str(t["id"]))]
        log.info("Lernenden-Suche uid=%s treffer=%d", mb.uid8(uid), len(treffer))
        zeilen = "".join(
            '<li><form method="post" action="/mitschriften/kurs/lernender" class="verschieben">'
            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
            f'<input type="hidden" name="uid" value="{_e(uid)}">'
            f'<input type="hidden" name="lead_id" value="{t["id"]}">'
            f'{_e(t["name"] or "ohne Namen")} <button type="submit">Wählen</button></form></li>'
            for t in treffer)
        rumpf = ("<h2>Lernende/n wählen</h2>"
                 + (f"<ul>{zeilen}</ul>" if zeilen
                    else '<p class="meta">Kein Kontakt gefunden.</p>')
                 + zurueck)
        return _seite_kurs("Mitschriften", rumpf)

    @ui._gesichert_seite
    async def handbuecher(request):
        return _seite_kurs("Mitschriften", leiste("::handbuecher") + _handbuecher_rumpf(
            ui.CSRF_TOKEN if _schreiben() else None))

    def _handbuch_zeile(request):
        lead = kurs_handbuch.gueltige_id(request.query_params.get("lead"))
        z = server._q("select pfad, pdf, stand_am from kurs_handbuch where lead_id = %s",
                      (lead,)) if lead else []
        return lead, (z[0] if z else None)

    @ui._gesichert_seite
    async def handbuch(request):
        lead, z = _handbuch_zeile(request)
        inhalt = _datei_lesen(z["pfad"] if z else None, f"lead={(lead or '')[:8]}")
        if inhalt is None:
            return _nicht_gefunden("Zu diesem Lernenden gibt es kein Handbuch (mehr).")
        return _datei(inhalt, "text/html; charset=utf-8",
                      f"Kurs-Handbuch_{_iso_tag(z['stand_am'])}.html",
                      bool(request.query_params.get("download")))

    @ui._gesichert_seite
    async def handbuch_pdf(request):
        lead, z = _handbuch_zeile(request)
        inhalt = _datei_lesen(z["pdf"] if z else None, f"lead={(lead or '')[:8]}")
        if inhalt is None:
            return _nicht_gefunden("Zu diesem Lernenden gibt es kein Handbuch-PDF (mehr).")
        return _datei(inhalt, "application/pdf",
                      f"Kurs-Handbuch_{_iso_tag(z['stand_am'])}.pdf", True)

    @ui._gesichert_seite
    async def kapitel(request):
        form = await request.form()
        fehler = _pruefen(form)
        if fehler:
            return fehler
        lead = kurs_handbuch.gueltige_id(form.get("lead"))
        kid = kurs_handbuch.gueltige_id(form.get("kapitel_id"))
        aktion = str(form.get("aktion") or "")
        if aktion not in ("umbenennen", "hoch", "runter"):
            return ui._fehlerseite(400, "Aktion ungültig", "Nichts geändert.")
        titel = None
        if aktion == "umbenennen":
            titel = str(form.get("titel") or "").strip()
            if not 1 <= len(titel) <= TITEL_MAX:
                return ui._fehlerseite(400, "Titel ungültig",
                                       f"Der Titel braucht 1 bis {TITEL_MAX} Zeichen. "
                                       "Nichts geändert.")
        if lead is None or kid is None:
            return _nicht_gefunden("Dieses Kapitel gibt es nicht (mehr).")
        ergebnis = await asyncio.to_thread(kurs_handbuch.kapitel_aendern, lead, kid, aktion,
                                           titel)
        if ergebnis == "fehlt":
            return _nicht_gefunden("Dieses Kapitel gibt es nicht (mehr).")
        if ergebnis == "neu":
            return ui._fehlerseite(409, "Kapitel wird neu aufgebaut",
                                   "Dieses Kapitel wird gerade neu aufgebaut. "
                                   "Später erneut versuchen.")
        return RedirectResponse("/mitschriften/handbuecher", status_code=303)

    @ui._gesichert_seite
    async def ausgeben(request):
        form = await request.form()
        fehler = _pruefen(form)
        if fehler:
            return fehler
        lead = kurs_handbuch.gueltige_id(form.get("lead"))
        if lead is None:
            return _nicht_gefunden("Diesen Lernenden gibt es nicht.")
        if not server._q("select 1 from leads where id = %s", (lead,)):
            return _nicht_gefunden("Diesen Lernenden gibt es nicht.")
        try:
            await asyncio.to_thread(kurs_handbuch.ausgeben, lead)
        except kurs_pdf.PdfFehler as err:
            log.warning("Handbuch-Ausgabe fehlgeschlagen lead=%s (PdfFehler)", lead[:8])
            return ui._fehlerseite(502, "Ausgabe fehlgeschlagen", f"{err} Nichts geändert.")
        except Exception as err:
            log.warning("Handbuch-Ausgabe fehlgeschlagen lead=%s (%s)", lead[:8],
                        type(err).__name__)
            return ui._fehlerseite(500, "Ausgabe fehlgeschlagen",
                                   "Das Handbuch konnte nicht ausgegeben werden. "
                                   "Später erneut versuchen.")
        return RedirectResponse("/mitschriften/handbuecher", status_code=303)

    return [Route("/mitschriften/kurs", kurs, methods=["GET"]),
            Route("/mitschriften/kurs.pdf", kurs_pdf_route, methods=["GET"]),
            Route("/mitschriften/kurs/lernender", lernender, methods=["POST"]),
            Route("/mitschriften/kurs/suche", suche, methods=["POST"]),
            Route("/mitschriften/handbuecher", handbuecher, methods=["GET"]),
            Route("/mitschriften/handbuch", handbuch, methods=["GET"]),
            Route("/mitschriften/handbuch.pdf", handbuch_pdf, methods=["GET"]),
            Route("/mitschriften/handbuch/kapitel", kapitel, methods=["POST"]),
            Route("/mitschriften/handbuch/ausgeben", ausgeben, methods=["POST"])]
