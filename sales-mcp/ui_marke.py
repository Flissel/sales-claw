"""Seite "Marke" im Marketing-Bereich (Spec 2026-10-07-marke-per-chat-design.md §4.1).
/marketing/layouts zeigt das Markenprofil der gewaehlten Firma (Spiegel), den Chat mit dem
Marken-Agenten, den offenen Vorschlag samt Vorschau und "Uebernehmen"/"Verwerfen".

Wie der Rest von sales-ui ohne JavaScript: Formulare, Verweise (Mail/Handy) und ein
Meta-Refresh alle 5 s, solange ein Auftrag laeuft. Daten kommen nur ueber marketing_pult;
jeder Aufruf laeuft im Threadpool. Der alte Regler-Editor entfaellt, seine Pfade leiten hierher.

Uploads (Plan-Ruling R2): Bilder und Dokumente gehen durch dieselbe Ablage und Pruefung wie
der Editor-Anhang (ui_editor.anhang_speichern), gehoeren aber der gewaehlten Firma
(POST /medien/zuordnung); scheitert die Zuordnung, wird die Datei wieder geloescht."""
from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import schriften
import ui_editor

SEITE = "/marketing/layouts"
NACHRICHT_MAX = 2000
PC_WARTET_NACH_S = 60                # danach: "sobald der PC läuft"
KURZ_ZEILEN, KURZ_ZEICHEN = 2, 160
ANHAENGE_MAX = 5                     # wie ANHAENGE_MAX der Marketing-API (kontext.anhaenge)
REFRESH_S = 5
FORMATE = {"mail": "Mail", "handy": "Handy"}
PC_LAEUFT = "Wird übernommen, sobald der PC läuft"
KEIN_PROFIL = "Noch kein Branding – erzähl mir von der Firma"
NEUERES_PROFIL = "Inzwischen gibt es ein neueres Profil – bitte neu laden"
_FARBE = re.compile(r"#[0-9A-Fa-f]{6}")
LOGO_BASE64_MAX = 210_000           # Logo <= 140 KB als data-URL = rund 187 000 Zeichen, plus Luft
_BILD_DATEN = re.compile(rf"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]{{1,{LOGO_BASE64_MAX}}}")
_FARBEN = (("akzent", "Akzent"), ("flaeche", "Fläche"))
_VORSCHLAG_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Zweitfarbe"), ("grund", "Grund"), ("text", "Text"))
_STATUS = {"offen": "wartet (PC muss laufen)", "in_arbeit": "wird bearbeitet", "fehler": "fehlgeschlagen"}


def _uuid_oder_none(wert) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except ValueError:
        return None


def _kurz(text) -> str:
    """Die ersten Zeilen eines Abschnitts, auf KURZ_ZEICHEN gekuerzt."""
    zeilen = [z.strip() for z in str(text or "").splitlines() if z.strip()][:KURZ_ZEILEN]
    t = "\n".join(zeilen)
    return t if len(t) <= KURZ_ZEICHEN else t[:KURZ_ZEICHEN - 1].rstrip() + "…"


def _alter_s(roh) -> float | None:
    """Alter eines ISO-/Postgres-Zeitpunkts in Sekunden; ohne Zeitzone gilt UTC. None, wenn unlesbar."""
    try:
        dt = datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _familie(sid) -> str | None:
    s = schriften.REGISTER.get(sid) if isinstance(sid, str) else None
    return s["familie"] if s else None


def routen(ui) -> list:
    from ui_marketing import _gerahmt, _wann
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", f'{e(f.grund)}<p><a href="{SEITE}">Zur Marke</a></p>')
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def abgewiesen(status: int, text: str):
        return ui._fehlerseite(status, "Nicht möglich", f'{e(text)}<p><a href="{SEITE}">Zur Marke</a></p>')

    def csrf_feld() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def farbfeld(name: str, wert) -> str:
        w = str(wert or "")
        if not _FARBE.fullmatch(w):
            return ""
        return (f'<span class="farbe"><span class="farbfeld" style="background:{w}"></span>'
                f'{e(name)} {e(w)}</span>')

    # --- Seite -----------------------------------------------------------------------------

    def muster(sid, firma: str) -> str:
        """Schriftmuster "Aa – Firma" in der Schrift (nur Register-ids, sonst nur der Name)."""
        familie = _familie(sid)
        if not familie:
            return f'<span class="schriftmuster">{e(str(sid or ""))}</span>'
        return (f'<span class="schriftmuster" style="font-family:\'{familie}\', sans-serif">'
                f'Aa – {e(firma)}</span> <span class="meta">({e(familie)})</span>')

    def schrift_zeile(anzeige, text, firma: str) -> str:
        if not (anzeige or text):
            return ""
        return (f'<p class="schriften">Überschrift: {muster(anzeige, firma)}<br>'
                f'Text: {muster(text, firma)}</p>')

    def profil_html(d: dict) -> str:
        sp = d.get("spiegel") if isinstance(d.get("spiegel"), dict) else {}
        g = sp.get("gestalt") if isinstance(sp.get("gestalt"), dict) else {}
        stand = str(sp.get("stand") or "")
        if not g and not stand:
            return f'<div class="marke-profil"><p><b>{KEIN_PROFIL}</b></p></div>'
        teile = []
        firma = str(d.get("name") or d.get("mandant") or "")
        aktuell = d.get("aktuell") if isinstance(d.get("aktuell"), dict) else {}
        werte = aktuell.get("werte") if isinstance(aktuell.get("werte"), dict) else {}
        farben = ("".join(farbfeld(n, g.get(k)) for k, n in _FARBEN)
                  + "".join(farbfeld(n, werte.get(k)) for k, n in (("grund", "Grund"), ("text", "Text"))))
        if farben:
            teile.append(f'<div class="farben-zeile">{farben}</div>')
        schrift = g.get("schriften") if isinstance(g.get("schriften"), dict) else {}
        teile.append(schrift_zeile(schrift.get("anzeige"), schrift.get("text"), firma))
        logo = str(g.get("logo") or "")
        if _BILD_DATEN.fullmatch(logo):
            teile.append(f'<p><img class="marke-logo" src="{logo}" alt="Logo"></p>')
        ab = aktuell.get("abschnitte") if isinstance(aktuell.get("abschnitte"), dict) else {}
        for titel in ("Ton", "Zielgruppe"):
            kurz = _kurz(ab.get(titel))
            if kurz:
                teile.append(f'<p class="kurz"><b>{titel}:</b> {e(kurz).replace(chr(10), "<br>")}</p>')
        if stand:
            teile.append(f'<p class="meta">Stand: {e(stand)}</p>')
        if sp.get("fehler"):
            teile.append(f'<p class="warnung">Spiegel veraltet seit {e(_wann(ui, sp.get("gespiegelt_am")))}: '
                         f'{e(str(sp["fehler"]))}</p>')
        return f'<div class="marke-profil">{"".join(teile)}</div>'

    def chat_html(d: dict) -> str:
        runden = []
        for a in d.get("auftraege") or []:
            if not isinstance(a, dict):
                continue
            antwort = str(a.get("antwort") or "")
            if not antwort:
                antwort = _STATUS.get(str(a.get("status") or ""), "")
                antwort = f'<i>{e(antwort)}</i>' if antwort else ""
            else:
                antwort = e(antwort)
            hinweise = "".join(f"<li>{e(str(h))}</li>" for h in a.get("hinweise") or [])
            runden.append(f'<div class="chat-runde"><p class="chat-du">{e(str(a.get("nachricht") or ""))}</p>'
                          + (f'<p class="chat-agent">{antwort}</p>' if antwort else "")
                          + (f'<ul class="meta">{hinweise}</ul>' if hinweise else "") + "</div>")
        leer = '<p class="meta">Noch keine Nachrichten.</p>'
        return f'<div class="marke-chat">{"".join(runden) or leer}</div>'

    def formular_html(d: dict) -> str:
        if d.get("laeuft"):
            return ('<p class="meta">Der Marken-Agent arbeitet gerade – die Seite lädt sich selbst neu. '
                    'Eine neue Nachricht geht erst danach.</p>')
        return (f'<form method="post" action="/marketing/marke/senden" enctype="multipart/form-data" '
                f'class="pult-felder">{csrf_feld()}'
                f'<label>Nachricht <textarea name="nachricht" rows="4" maxlength="{NACHRICHT_MAX}" required '
                f'placeholder="z. B. Wir sind eine Rösterei, warm und klar. Unsere Webseite: https://…"></textarea></label>'
                f'<label>Dateien (Logo, Bilder, Dokumente; höchstens {ANHAENGE_MAX}) '
                f'<input type="file" name="datei" multiple></label>'
                f'<div class="aktionen"><button class="primaer" type="submit">Senden</button></div></form>')

    def vorschlag_html(d: dict, fmt: str) -> str:
        v = d.get("vorschlag")
        if not isinstance(v, dict) or not _uuid_oder_none(v.get("id")):
            return ""
        vid = str(v["id"])
        w = v.get("vorschlag") if isinstance(v.get("vorschlag"), dict) else {}
        farben = "".join(farbfeld(n, w.get(k)) for k, n in _VORSCHLAG_FARBEN)
        schrift = schrift_zeile(w.get("schrift_anzeige"), w.get("schrift_text"),
                                str(d.get("name") or d.get("mandant") or ""))
        logo = f'<p>Logo: {e(str(w["logo"]))}</p>' if w.get("logo") else ""
        abschnitte = "".join(
            f'<h3>{e(str(n))}</h3><p>{e(str(t))}</p>'
            for n, t in (w.get("abschnitte") or {}).items() if isinstance(t, str) and t.strip()) \
            if isinstance(w.get("abschnitte"), dict) else ""
        umschalter = " &middot; ".join(
            (f'<b>{t}</b>' if k == fmt else f'<a href="{SEITE}?format={k}">{t}</a>') for k, t in FORMATE.items())
        return (f'<h2>Vorschlag</h2><p class="meta">Vorschau als {umschalter}</p>'
                f'<div class="pult"><div class="pult-links"><div class="marke-profil">'
                f'<div class="farben-zeile">{farben}</div>{schrift}{logo}{abschnitte}</div>'
                f'<form method="post" action="/marketing/marke/uebernehmen" class="aktion">{csrf_feld()}'
                f'<input type="hidden" name="vorschlag" value="{e(vid)}">'
                f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
                f'Die Marke hat sich geändert – übernehmen?</label>'
                f'<button class="primaer" type="submit">Übernehmen</button></form>'
                f'<form method="post" action="/marketing/marke/verwerfen" class="aktion">{csrf_feld()}'
                f'<input type="hidden" name="vorschlag" value="{e(vid)}">'
                f'<button type="submit">Verwerfen</button></form></div>'
                f'<div class="pult-rechts"><iframe class="vorschau" sandbox title="Vorschau" '
                f'src="{e(f"/marketing/marke/vorschau?format={fmt}&vorschlag={vid}")}"></iframe></div></div>')

    @ui._gesichert_seite
    async def marke(request):
        fmt = request.query_params.get("format", "mail")
        fmt = fmt if fmt in FORMATE else "mail"
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/marke?mandant={urllib.parse.quote(m)}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not isinstance(d, dict):
            return fehler(marketing_pult.PultFehler("unbekannt", "Antwort ohne Marke"))
        status = ""
        if d.get("uebernahme"):
            alter = _alter_s(d.get("uebernahme_seit"))
            wartet = alter is not None and alter > PC_WARTET_NACH_S
            status = f'<p class="status-zeile">{PC_LAEUFT if wartet else "Wird übernommen …"}</p>'
        arbeitet = bool(d.get("laeuft") or d.get("uebernahme"))
        rumpf = ('<link rel="stylesheet" href="/marketing/schrift/schriften.css">'
                 + marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, SEITE)
                 + '<p class="meta">Das Markenprofil bestimmt Farben, Schriften und Logo neuer Newsletter. '
                   'Erzähl dem Marken-Agenten von der Firma; was er vorschlägt, übernimmst du hier.</p>'
                 + profil_html(d) + status + "<h2>Chat</h2>" + chat_html(d) + formular_html(d)
                 + vorschlag_html(d, fmt))
        antwort = ui._seite("Marke", rumpf, refresh=REFRESH_S if arbeitet else None)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'", bilddaten=True, schriften=True)
        return antwort

    # --- Vorschau-Proxy ---------------------------------------------------------------------

    @ui._gesichert_seite
    async def vorschau(request):
        fmt = request.query_params.get("format", "mail")
        fmt = fmt if fmt in FORMATE else "mail"
        try:
            if "vorschlag" in request.query_params:
                # Der Rahmen zeigt genau den Vorschlag, den die Karte daneben zeigt - auch wenn
                # inzwischen ein neuerer offen ist.
                vid = _uuid_oder_none(request.query_params["vorschlag"])
            else:
                m, _liste = await marketing_mandant.firma(request)
                d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/marke?mandant={urllib.parse.quote(m)}")
                v = d.get("vorschlag") if isinstance(d, dict) else None
                vid = _uuid_oder_none(v.get("id")) if isinstance(v, dict) else None
            if not vid:
                return _gerahmt("<p>Kein Vorschlag offen.</p>", status=404)
            q = {"format": fmt}
            if (basis := ui_editor.bild_basis()):
                q["bild_basis"] = basis
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "GET", f"/marke/vorschlaege/{vid}/vorschau?{urllib.parse.urlencode(q)}",
                roh=True)
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return _gerahmt(f"<p>Vorschau nicht möglich: {e(f.grund)}</p>", status=422)
            if f.art == "nicht_verbunden":
                return _gerahmt("<p>Marketing nicht verbunden.</p>", status=503)
            return _gerahmt("<p>Marketing gerade nicht erreichbar.</p>", status=503)
        return _gerahmt(inhalt, typ)

    # --- Senden (Nachricht + Dateien) ---------------------------------------------------------

    @ui._gesichert_seite
    async def senden(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        nachricht = str(form.get("nachricht") or "")
        if not nachricht.strip():
            return abgewiesen(422, "Ohne Nachricht kein Auftrag.")
        if len(nachricht) > NACHRICHT_MAX:
            return abgewiesen(422, f"Die Nachricht darf höchstens {NACHRICHT_MAX} Zeichen haben.")
        dateien = [d for d in form.getlist("datei") if getattr(d, "filename", "")]
        if len(dateien) > ANHAENGE_MAX:
            return abgewiesen(422, f"Höchstens {ANHAENGE_MAX} Dateien je Nachricht.")
        try:
            m, _liste = await marketing_mandant.firma(request)
        except marketing_pult.PultFehler as f:
            return fehler(f)

        abgelegt: list[str] = []

        async def aufraeumen():
            for name in abgelegt:
                await run_in_threadpool(ui.medien_datei_loeschen, name)

        for datei in dateien:
            basis, groesse, abgelehnt = await ui_editor.anhang_speichern(ui, datei)
            if abgelehnt:
                await aufraeumen()
                return abgewiesen(*abgelehnt)
            abgelegt.append(basis)
            # Ohne Zeile gilt eine Datei als Gemeinsam und waere fuer jede Firma sichtbar:
            # sie gehoert der gewaehlten Firma. Gelingt das nicht, bleibt keine Datei liegen.
            try:
                await run_in_threadpool(marketing_pult.anfrage, "POST", "/medien/zuordnung",
                                        {"dateiname": basis, "mandant": m})
            except marketing_pult.PultFehler as f:
                await aufraeumen()
                if f.art == "nicht_verbunden":
                    return fehler(f)
                return ui._fehlerseite(503, "Anhang nicht abgelegt",
                                       "Der Anhang konnte nicht der Firma zugeordnet werden - bitte erneut versuchen.")
            ui.LOG.info("Medien (Marke-Anhang): %s abgelegt (%d Byte)", basis, groesse)
        anhaenge = [{"name": n, "art": ui.server.medien.anhang_art(n)} for n in abgelegt]
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/marke/chat",
                                    {"mandant": m, "nachricht": nachricht, "kontext": {"anhaenge": anhaenge}})
        except marketing_pult.PultFehler as f:
            await aufraeumen()           # abgelehnt (z. B. es laeuft schon einer): keine Kopien anhaeufen
            return fehler(f)
        return RedirectResponse(SEITE, status_code=303)

    # --- Uebernehmen / Verwerfen ------------------------------------------------------------------

    def vorschlag_aktion(aktion: str):
        @ui._gesichert_seite
        async def handler(request):
            form = await request.form()
            if not ui._csrf_ok(form):
                return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
            vid = _uuid_oder_none(form.get("vorschlag"))
            if not vid:
                return abgewiesen(422, "Welcher Vorschlag gemeint ist, fehlt. Seite neu laden.")
            if aktion == "uebernehmen" and str(form.get("bestaetigt") or "") != "ja":
                return abgewiesen(422, "Bitte bestätige das Übernehmen mit dem Haken. Nichts wurde geändert.")
            try:
                await run_in_threadpool(marketing_pult.anfrage, "POST", f"/marke/vorschlaege/{vid}/{aktion}",
                                        {"von": ui._ui_akteur(request)})
            except marketing_pult.PultFehler as f:
                return fehler(f)
            return RedirectResponse(SEITE, status_code=303)
        return handler

    # --- Alte Layout-Pfade -------------------------------------------------------------------------

    async def zur_marke(request):
        return RedirectResponse(SEITE, status_code=303)

    alt = ui._gesichert_seite(zur_marke)
    alle = ["GET", "POST"]
    return [
        Route(SEITE, marke),
        Route("/marketing/marke/vorschau", vorschau),
        Route("/marketing/marke/senden", senden, methods=["POST"]),
        Route("/marketing/marke/uebernehmen", vorschlag_aktion("uebernehmen"), methods=["POST"]),
        Route("/marketing/marke/verwerfen", vorschlag_aktion("verwerfen"), methods=["POST"]),
        Route("/marketing/layout/{name}", alt, methods=alle),
        Route("/marketing/layout/{name}/speichern", alt, methods=alle),
        Route("/marketing/layout/{name}/standard", alt, methods=alle),
        Route("/marketing/layout-vorschau", alt, methods=alle),
        Route("/marketing/layout-bild/{name}", alt, methods=alle),
    ]
