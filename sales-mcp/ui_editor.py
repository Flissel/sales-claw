"""Editor-Seite des Newsletter-Editors (Spec 2026-09-29-newsletter-editor-
design.md §3.1/§3.2). Die EINZIGE Route von sales-ui mit Skript: nur das
eingebaute Paket /static/editor/editor.js. Dazu signierte Bild-Adressen fuer
die abgeschottete Vorschau (ohne Anmeldung, 15 Minuten gueltig) und die
Vorlagen-Seite („Neuer Newsletter aus Vorlage").

Alles andere in sales-ui bleibt skriptfrei: die Seiten-CSP (ui._CSP) kennt
kein script-src. Die Editor-Seite setzt ihre eigene Richtlinie CSP_EDITOR;
ui._mit_koepfen laesst eine Antwort, die schon eine CSP traegt, in Ruhe."""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import time
import urllib.parse
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import marketing_pult

GUELTIG_S = 900
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp")
STATIK = Path(__file__).resolve().parent / "static" / "editor"
STATIK_DATEIEN = {"editor.js": "text/javascript", "editor.css": "text/css"}
CSP_EDITOR = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
              "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
# Die ausgelieferte Bilddatei: gar keine Quellen, nichts ausfuehrbar (wie
# ui._CSP_DATEI fuer /medien/datei/).
CSP_BILD = "default-src 'none'; sandbox"
# Wie der Name einer Vorlage in der API geprueft wird (pult.py _VORLAGE).
VORLAGE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
TITEL_MAX = 200
KONFLIKT = "Inzwischen gibt es Fassung"
# Obergrenze fuer den Speichern-Koerper: die DB nimmt hoechstens 256 KB
# Dokument an, dazu Betreff/Vorschautext und JSON-Rahmen.
KOERPER_MAX = 300 * 1024
# Bildplatz-Kennung und Hinweis fuer Bild-Auftraege (Marketing-API prueft
# nochmals; hier nur die Form).
PLATZ_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HINWEIS_MAX = 500


def _ui():
    import ui
    return ui


def bild_token(jetzt: int | None = None) -> str:
    """`<ablauf>.<hex-hmac>` - HMAC-SHA256 ueber str(ablauf) mit
    UI_SESSION_SECRET; gueltig 15 Minuten ab `jetzt`."""
    geheim = _ui().UI_SESSION_SECRET
    ablauf = int(jetzt if jetzt is not None else time.time()) + GUELTIG_S
    sig = hmac.new(geheim.encode(), str(ablauf).encode(), hashlib.sha256).hexdigest()
    return f"{ablauf}.{sig}"


def bild_token_ok(token: str, jetzt: int | None = None) -> bool:
    geheim = _ui().UI_SESSION_SECRET
    if not geheim or "." not in (token or ""):
        return False
    ablauf, sig = token.split(".", 1)
    if not ablauf.isdigit() or len(ablauf) > 12:
        return False
    erwartet = hmac.new(geheim.encode(), ablauf.encode(), hashlib.sha256).hexdigest()
    jetzt = int(jetzt if jetzt is not None else time.time())
    return hmac.compare_digest(sig, erwartet) and jetzt <= int(ablauf) <= jetzt + GUELTIG_S


def bild_basis() -> str:
    """Adresse, unter der die abgeschottete Vorschau Bilder holt - leer, wenn
    kein Geheimnis gesetzt ist (dann gibt es keine Signatur) oder die
    Basis-Adresse kein https ist: die Marketing-API nimmt nur
    `^https://…/$` an und lehnte sonst die ganze Vorschau ab (422). Ohne
    Basis zeigt sie Platzhalter statt der Bilder."""
    ui = _ui()
    basis = str(ui.UI_BASIS_URL or "").rstrip("/")
    if not ui.UI_SESSION_SECRET or not basis.startswith("https://"):
        return ""
    return f"{basis}/marketing/bild/{bild_token()}/"


def _json_im_html(daten: dict) -> str:
    # "</" und "<!--" duerfen im Daten-Element nie vorkommen, sonst schliesst
    # es das Tag bzw. schaltet den Parser um. JSON.parse liest "<\/" als "</".
    return (json.dumps(daten, ensure_ascii=False)
            .replace("</", "<\\/").replace("<!--", "<\\u0021--"))


def _fehler(ui, f: marketing_pult.PultFehler) -> Response:
    """Wie fehler() in ui_marketing."""
    if f.art == "nicht_verbunden":
        return ui._fehlerseite(503, "Marketing nicht verbunden",
                               "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
    if f.art == "abgelehnt":
        return ui._fehlerseite(422, "Nicht möglich", ui._e(f.grund))
    return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                           "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")


def _gerahmt(inhalt, typ: str = "text/html; charset=utf-8", status: int = 200) -> Response:
    """Vorschau im eigenen, gesandboxten Rahmen - dieselben Koepfe wie der
    Entwurfs-Proxy (ui_marketing._CSP_VORSCHAU + SAMEORIGIN)."""
    import ui_marketing
    return Response(inhalt, status_code=status, media_type=typ,
                    headers={"Content-Security-Policy": ui_marketing._CSP_VORSCHAU,
                             "X-Frame-Options": "SAMEORIGIN",
                             "Cache-Control": "private, no-store"})


def routen(ui) -> list:
    e = ui._e
    nicht_im_editor = ("Dieser Entwurf lässt sich nicht im Editor öffnen. Der Editor öffnet nur "
                       "Newsletter-Entwürfe, deren neueste Fassung im Editor entstanden ist.")

    def json_grund(status: int, grund: str, **mehr) -> JSONResponse:
        return JSONResponse({**mehr, "grund": grund}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_seite(request):
        roh = request.path_params["iid"]
        iid = urllib.parse.quote(roh, safe="")
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}")
        except marketing_pult.PultFehler as f:
            return _fehler(ui, f)
        i, fassungen = d.get("inhalt") or {}, d.get("fassungen") or []
        neueste = fassungen[0] if fassungen else {}
        if (neueste.get("format") != "bloecke" or not isinstance(neueste.get("bloecke"), dict)
                or i.get("art") != "newsletter" or i.get("status") != "entwurf"):
            return ui._fehlerseite(422, "Nicht im Editor", e(nicht_im_editor) +
                                   f' <a href="/marketing/entwurf/{e(iid)}">Zurück zum Entwurf</a>')
        felder = neueste.get("felder") or {}
        start = {
            "dokument": neueste["bloecke"],
            "betreff": str(felder.get("betreff") or ""),
            "vorschautext": str(felder.get("vorschautext") or ""),
            "basis_fassung": int(neueste["fassung"]),
            "speichern_url": f"/marketing/editor/{iid}/speichern",
            "vorschau_url": f"/marketing/entwurf/{iid}/vorschau",
            "medien_url": "/marketing/editor/medien.json",
            "zurueck_url": f"/marketing/entwurf/{iid}",
            "bild_url": f"/marketing/editor/{iid}/bild",
            "stand_url": f"/marketing/editor/{iid}/stand.json",
            "csrf": ui.CSRF_TOKEN,
            # Herkunft aus dem alten Freigabeweg - der Editor zeigt denselben
            # Hinweis wie die Entwurfsseite (ui_marketing.alter_hinweis).
            "alter_weg": d.get("alter_weg") if isinstance(d.get("alter_weg"), dict) else None,
        }
        seite = (
            '<!doctype html><html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Editor – {e(i.get("titel") or "")}</title>'
            '<link rel="stylesheet" href="/static/editor/editor.css">'
            # Grundregel VOR der Media-Query - sonst gewinnt das spaetere
            # display:none bei gleicher Spezifitaet (Smoke 29.09.: Hinweis
            # blieb bei 390 px unsichtbar).
            '<style>.schmal{display:none;padding:2rem;font-family:system-ui} '
            '@media (max-width:767px){#root{display:none}.schmal{display:block}}</style></head><body>'
            '<p class="schmal">Der Editor braucht einen größeren Bildschirm. '
            f'<a href="/marketing/entwurf/{e(iid)}">Zurück zum Entwurf</a></p>'
            '<div id="root"></div>'
            f'<script type="application/json" id="editor-start">{_json_im_html(start)}</script>'
            '<script src="/static/editor/editor.js" defer></script></body></html>')
        return HTMLResponse(seite, headers={"Content-Security-Policy": CSP_EDITOR,
                                            "Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_speichern(request):
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        # Groesse vor dem Lesen (Content-Length) und beim Lesen (Stuecke) begrenzen.
        try:
            laenge = int(request.headers.get("content-length") or 0)
        except ValueError:
            laenge = 0
        if laenge > KOERPER_MAX:
            return json_grund(413, "Das Dokument ist zu groß (höchstens 300 KB)")
        roh = bytearray()
        async for stueck in request.stream():
            roh += stueck
            if len(roh) > KOERPER_MAX:
                return json_grund(413, "Das Dokument ist zu groß (höchstens 300 KB)")
        try:
            body = json.loads(bytes(roh))
        except (ValueError, UnicodeDecodeError):
            return json_grund(422, "Die Anfrage ist kein gültiges JSON")
        if not isinstance(body, dict):
            return json_grund(422, "Die Anfrage ist kein JSON-Objekt")
        basis = body.get("basis_fassung")
        dokument = body.get("dokument")
        betreff = body.get("betreff", "")
        vorschautext = body.get("vorschautext", "")
        als_kopie = body.get("als_kopie", False)
        if isinstance(basis, bool) or not isinstance(basis, int) or basis < 0:
            return json_grund(422, "basis_fassung muss eine ganze Zahl ab 0 sein")
        if not isinstance(dokument, dict):
            return json_grund(422, "Das Dokument fehlt")
        if not isinstance(betreff, str) or not isinstance(vorschautext, str):
            return json_grund(422, "Betreff und Vorschautext müssen Text sein")
        if not isinstance(als_kopie, bool):
            return json_grund(422, "als_kopie muss true oder false sein")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/bloecke",
                {"basis_fassung": basis, "betreff": betreff, "vorschautext": vorschautext,
                 "bloecke": dokument, "als_kopie": als_kopie, "urheber": "betreiber"})
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                grund = str(f.grund or "")
                if grund.startswith(KONFLIKT):
                    return json_grund(409, grund, konflikt=True)
                return json_grund(422, grund or "Abgelehnt")
            return json_grund(503, "Speichern gerade nicht möglich")
        fassung = r.get("fassung") if isinstance(r, dict) else None
        if isinstance(fassung, bool) or not isinstance(fassung, int):
            # Die API hat gespeichert (oder nicht) - ohne Fassungsnummer koennen
            # wir das nicht bestaetigen; der Editor behaelt die Aenderungen.
            return json_grund(503, "Speichern gerade nicht möglich")
        return JSONResponse({"fassung": fassung}, headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_bild(request):
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            return json_grund(422, "Die Anfrage ist kein gültiges JSON")
        if not isinstance(body, dict):
            return json_grund(422, "Die Anfrage ist kein JSON-Objekt")
        platz, hinweis = body.get("platz"), body.get("hinweis", "")
        if platz is not None and (not isinstance(platz, str) or not PLATZ_ID.match(platz)):
            return json_grund(422, "Unbekannter Bildplatz")
        if not isinstance(hinweis, str) or len(hinweis) > HINWEIS_MAX:
            return json_grund(422, f"Der Hinweis darf höchstens {HINWEIS_MAX} Zeichen haben")
        staerke, neu = body.get("staerke", 55), body.get("neu", False)
        if isinstance(staerke, bool) or not isinstance(staerke, int) or not 0 <= staerke <= 100:
            return json_grund(422, "Die Stärke muss eine ganze Zahl von 0 bis 100 sein")
        if not isinstance(neu, bool):
            return json_grund(422, "neu muss true oder false sein")
        neu = neu or staerke == 100      # Stufe 100 heisst immer "ganz neu"
        nutzlast = {"platz": platz, "hinweis": hinweis.strip(), "nur_leere": False,
                    "staerke": 100 if neu else staerke, "modus": "neu" if neu else "ueberarbeiten"}
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/bilder", nutzlast)
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return json_grund(422, str(f.grund or "Abgelehnt"))
            return json_grund(503, "Auftrag gerade nicht möglich")
        return JSONResponse({"auftrag": str((r or {}).get("auftrag") or "")}, headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_stand(request):
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}")
            b = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}/bilder")
        except marketing_pult.PultFehler:
            return json_grund(503, "Stand gerade nicht abrufbar")
        fassungen = (d or {}).get("fassungen") or []
        return JSONResponse({"fassung": int(fassungen[0]["fassung"]) if fassungen else 0,
                             "auftraege": (b or {}).get("auftraege") or []},
                            headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def medien_json(request):
        try:
            eintraege = await run_in_threadpool(ui.server.medien.liste, True)
        except OSError:
            eintraege = []
        bilder = [n for n, _groesse in eintraege if os.path.splitext(n)[1].lower() in BILD_ENDUNGEN]
        return JSONResponse({"bilder": bilder}, headers={"Cache-Control": "no-store"})

    async def bild(request):
        # OHNE Anmeldung (AnmeldeWache laesst /marketing/bild/<t>/<n> durch):
        # die abgeschottete Vorschau schickt keine Anmelde-Cookies. Die
        # Berechtigung ist die Signatur - 15 Minuten, nur Bilder aus den
        # Medien, keine internen Unterlagen (Terminkarten tragen Kundendaten).
        nicht_da = Response("Nicht gefunden", status_code=404, media_type="text/plain",
                            headers={"Content-Security-Policy": CSP_BILD})
        if not bild_token_ok(request.path_params["token"]):
            return nicht_da
        # path_params ist schon entschluesselt - ein zweites unquote machte aus
        # "logo%2Epng" wieder "logo.png" und umginge die Namenspruefung.
        name = request.path_params["name"]
        endung = os.path.splitext(name)[1].lower()
        if endung not in BILD_ENDUNGEN:
            return nicht_da
        medien = ui.server.medien
        basis, fehler = await run_in_threadpool(medien.pruefe_anhang, name)
        if fehler or not basis:
            return nicht_da
        typ = mimetypes.guess_type(basis)[0] or medien.ERLAUBT.get(endung, ("", ""))[1]
        if not typ or not typ.startswith("image/"):
            return nicht_da
        return FileResponse(medien.pfad(basis), media_type=typ,
                            headers={"Cache-Control": "private, max-age=300",
                                     "X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": CSP_BILD})

    @ui._gesichert_seite
    async def vorlagen_seite(request):
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        "/vorlagen?mandant=vibemind&status=freigegeben")
        except marketing_pult.PultFehler as f:
            return _fehler(ui, f)
        csrf = f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

        def karte(v: dict) -> str:
            n = str(v.get("name") or "")
            if not VORLAGE_NAME.match(n):
                return ""
            beschreibung = str(v.get("beschreibung") or n)
            return (f'<div class="layout-karte"><div class="layout-rahmen">'
                    f'<iframe class="layout-bild" sandbox tabindex="-1" title="Vorschau {e(beschreibung)}" '
                    f'src="/marketing/vorlage-bild/{e(n)}"></iframe></div>'
                    f'<b>{e(beschreibung)}</b><span class="meta">{e(n)} &middot; Fassung '
                    f'{int(v.get("fassung") or 1)}</span>'
                    f'<form method="post" action="/marketing/aus-vorlage" class="aktion">{csrf}'
                    f'<input type="hidden" name="vorlage" value="{e(n)}">'
                    f'<label>Titel <input name="titel" required maxlength="{TITEL_MAX}" '
                    f'placeholder="z. B. Newsletter Oktober"></label>'
                    f'<button class="primaer" type="submit">Neu aus Vorlage</button></form></div>')

        karten = "".join(karte(v) for v in d.get("vorlagen") or [])
        rumpf = (f'<p class="meta">Eine Vorlage wählen, einen Titel geben - der neue Entwurf öffnet '
                 f'sich im Editor.</p>'
                 + (f'<div class="galerie">{karten}</div>' if karten else "<p>Keine freigegebenen Vorlagen.</p>"))
        antwort = ui._seite("Neuer Newsletter aus Vorlage", rumpf)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'")
        return antwort

    @ui._gesichert_seite
    async def vorlage_bild(request):
        name = request.path_params["name"]
        if not VORLAGE_NAME.match(name):
            return _gerahmt("<p>Unbekannte Vorlage.</p>", status=404)
        q = {"format": "mail"}
        if (b := bild_basis()):
            q["bild_basis"] = b
        try:
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "GET",
                f"/vorlagen/{name}/vorschau?{urllib.parse.urlencode(q)}", roh=True)
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return _gerahmt(f"<p>Vorschau nicht möglich: {e(f.grund)}</p>", status=422)
            return _gerahmt("<p>Marketing gerade nicht erreichbar.</p>", status=503)
        return _gerahmt(inhalt, typ)

    @ui._gesichert_seite
    async def aus_vorlage(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        vorlage = str(form.get("vorlage") or "")
        titel = str(form.get("titel") or "").strip()
        if not VORLAGE_NAME.match(vorlage):
            return ui._fehlerseite(422, "Nicht möglich", "Unbekannte Vorlage.")
        if not titel or len(titel) > TITEL_MAX:
            return ui._fehlerseite(422, "Nicht möglich",
                                   f"Der Titel fehlt oder ist länger als {TITEL_MAX} Zeichen.")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", "/inhalte/aus_vorlage",
                                        {"vorlage": vorlage, "titel": titel, "mandant": "vibemind"})
        except marketing_pult.PultFehler as f:
            return _fehler(ui, f)
        return RedirectResponse(f"/marketing/editor/{urllib.parse.quote(str(r['id']), safe='')}",
                                status_code=303)

    async def statik(request):
        # Nur die zwei Paket-Dateien (MANIFEST.json bleibt Build-Beleg, nicht
        # ausgeliefert). Hinter der Anmeldewache wie alles ausser /login.
        datei = request.path_params["datei"]
        typ = STATIK_DATEIEN.get(datei)
        if not typ:
            return Response("Nicht gefunden", status_code=404, media_type="text/plain")
        return FileResponse(STATIK / datei, media_type=typ, headers={"Cache-Control": "no-cache"})

    return [
        # medien.json VOR {iid}, sonst faenge der Platzhalter sie ab.
        Route("/marketing/editor/medien.json", medien_json),
        Route("/marketing/editor/{iid}", editor_seite),
        Route("/marketing/editor/{iid}/speichern", editor_speichern, methods=["POST"]),
        Route("/marketing/editor/{iid}/bild", editor_bild, methods=["POST"]),
        Route("/marketing/editor/{iid}/stand.json", editor_stand),
        Route("/marketing/bild/{token}/{name}", bild),
        Route("/marketing/vorlagen", vorlagen_seite),
        Route("/marketing/vorlage-bild/{name}", vorlage_bild),
        Route("/marketing/aus-vorlage", aus_vorlage, methods=["POST"]),
        Route("/static/editor/{datei}", statik),
    ]
