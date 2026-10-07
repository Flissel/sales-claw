"""Editor-Seite des Newsletter-Editors (Spec 2026-09-29-newsletter-editor-
design.md §3.1/§3.2). Die EINZIGE Route von sales-ui mit Skript: nur das
eingebaute Paket /static/editor/editor.js. Dazu signierte Bild-Adressen fuer
die abgeschottete Vorschau (ohne Anmeldung, 15 Minuten gueltig) und die
Vorlagen-Seite („Neuer Newsletter aus Vorlage").

Alles andere in sales-ui bleibt skriptfrei: die Seiten-CSP (ui._CSP) kennt
kein script-src. Die Editor-Seite setzt ihre eigene Richtlinie CSP_EDITOR;
ui._mit_koepfen laesst eine Antwort, die schon eine CSP traegt, in Ruhe."""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import mimetypes
import os
import re
import time
import urllib.parse
import uuid
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import schriften

GUELTIG_S = 900
_STAMM_FUER_PRAEFIX = 90   # Platz fuer "anhang-" und "-NNN" unter den 100 Zeichen
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
GESTALTUNG_ZEITLIMIT_S = 30
HINWEIS_MAX = 500
NACHRICHT_MAX = 2000
KONTEXT_MAX = 4 * 1024
ASSISTENT_WEG = "Assistent gerade nicht erreichbar"


def _ui():
    import ui
    return ui


def _graustufen(pfad: str):
    """(Bytes, Medientyp) der Graustufen-Fassung oder None bei jedem Fehler."""
    try:
        import io
        from PIL import Image, ImageOps
        with Image.open(pfad) as bild:
            png = bild.format == "PNG"
            alpha = None
            if png and (bild.mode in ("RGBA", "LA", "PA")
                        or (bild.mode == "P" and "transparency" in bild.info)):
                alpha = bild.convert("RGBA").getchannel("A")
            if alpha is not None:
                # Freigestellte Bilder: Grauwerte aus RGB, Alpha bleibt erhalten.
                grau = Image.merge("LA", (ImageOps.grayscale(bild.convert("RGB")), alpha))
            else:
                grau = ImageOps.grayscale(bild)
            puffer = io.BytesIO()
            if png:
                grau.save(puffer, "PNG")
            else:
                grau.convert("L").save(puffer, "JPEG", quality=88)
        return puffer.getvalue(), ("image/png" if png else "image/jpeg")
    except Exception:  # noqa: BLE001 - Originaldatei ist die sichere Rueckfalloption
        return None


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
                or i.get("art") != "newsletter" or i.get("status") not in ("entwurf", "eingereicht")):
            return ui._fehlerseite(422, "Nicht im Editor", e(nicht_im_editor) +
                                   f' <a href="/marketing/entwurf/{e(iid)}">Zurück zum Entwurf</a>')
        felder = neueste.get("felder") or {}
        # Der Editor folgt der Firma des Newsletters, nicht dem Cookie. Ist die
        # Liste nicht erreichbar, bleibt als Name die id (der Editor geht auf).
        # Ohne Firma am Inhalt (alter Entwurf) steht null im Start-JSON: nie die
        # Vorgabe-Firma unterschieben; der Editor zeigt dann kein Etikett.
        mid = str(i.get("mandant") or "")
        mandant = None
        if mid:
            try:
                mname = marketing_mandant.name_von(mid, await run_in_threadpool(marketing_mandant.mandanten))
            except marketing_pult.PultFehler:
                mname = mid
            mandant = {"id": mid, "name": mname}
        # Nur offene Rueckmeldungen (neueste zuerst, wie die API liefert) gehen an den Editor.
        rueck = [{"text": str(r.get("text") or ""), "von": str(r.get("von") or ""),
                  "am": str(r.get("am") or ""), "fassung": r.get("fassung")}
                 for r in (d.get("rueckmeldungen") or [])
                 if isinstance(r, dict) and not r.get("erledigt")]
        start = {
            "status": i.get("status"),
            "eingereicht_am": i.get("eingereicht_am") if i.get("status") == "eingereicht" else None,
            "rueckmeldungen": rueck,
            "einreichen_url": f"/marketing/editor/{iid}/einreichen",
            "zurueckziehen_url": f"/marketing/editor/{iid}/zurueckziehen",
            "mandant": mandant,
            "dokument": neueste["bloecke"],
            "betreff": str(felder.get("betreff") or ""),
            "vorschautext": str(felder.get("vorschautext") or ""),
            "basis_fassung": int(neueste["fassung"]),
            "speichern_url": f"/marketing/editor/{iid}/speichern",
            "vorschau_url": f"/marketing/entwurf/{iid}/vorschau",
            "medien_url": f"/marketing/editor/medien.json?iid={iid}",
            "medien_zuordnung_url": f"/marketing/editor/{iid}/medien/zuordnung",
            "medien_loeschen_url": "/marketing/editor/medien/loeschen",
            "zurueck_url": f"/marketing/entwurf/{iid}",
            "bild_url": f"/marketing/editor/{iid}/bild",
            "gestaltung_url": f"/marketing/editor/{iid}/gestaltung",
            "stand_url": f"/marketing/editor/{iid}/stand.json",
            "chat_url": f"/marketing/editor/{iid}/chat",
            "anhang_url": f"/marketing/editor/{iid}/anhang",
            "chat_stand_url": f"/marketing/editor/{iid}/chat.json",
            "chat_rueckgaengig_url": f"/marketing/editor/{iid}/chat/rueckgaengig",
            "chat_vormerkung_url": f"/marketing/editor/{iid}/chat/vormerkung",
            "chat_vormerkung_starten_url": f"/marketing/editor/{iid}/chat/vormerkung/starten",
            "chat_stopp_url": f"/marketing/editor/{iid}/chat/stopp",
            "export_vorschau_url": f"/marketing/editor/{iid}/export/vorschau",
            "export_url": f"/marketing/editor/{iid}/export",
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
        freistellen = body.get("freistellen", False)
        if not isinstance(freistellen, bool):
            return json_grund(422, "freistellen muss true oder false sein")
        neu = neu or staerke == 100      # Stufe 100 heisst immer "ganz neu"
        if freistellen:
            if not platz:
                return json_grund(422, "Freistellen braucht einen Bildplatz")
            nutzlast = {"platz": platz, "hinweis": "", "nur_leere": False,
                        "staerke": 0, "modus": "freistellen"}
        else:
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
    async def editor_gestaltung(request):
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            return json_grund(422, "Die Anfrage ist kein gültiges JSON")
        gestaltung = body.get("gestaltung") if isinstance(body, dict) else None
        if not isinstance(gestaltung, dict):
            return json_grund(422, "Gestaltung fehlt")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            # Das Pult prueft und rechnet; viele Ebenen brauchen laenger als
            # die 8 s der uebrigen Aufrufe.
            r = await run_in_threadpool(
                functools.partial(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/gestaltung",
                                  {"gestaltung": gestaltung}, zeitlimit=GESTALTUNG_ZEITLIMIT_S))
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return json_grund(422, str(f.grund or "Abgelehnt"))
            return json_grund(503, "Gestaltung gerade nicht möglich")
        if not isinstance(r, dict):
            return json_grund(503, "Gestaltung gerade nicht möglich")
        return JSONResponse(r, headers={"Cache-Control": "no-store"})

    async def _agent_post(request, pfad: str, pruefen, zeitlimit=None, methode: str = "POST"):
        """Gemeinsamer Weg der schreibenden Agent-Routen: CSRF, JSON-Objekt,
        Formpruefung (`pruefen(body)` -> (nutzlast, None) oder (None, grund)),
        Pult-Aufruf im Threadpool, Fehlerabbildung wie editor_bild. `pruefen=None`:
        Route ohne Koerper (nur CSRF), `methode` ist die Pult-Methode."""
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        nutzlast = None
        if pruefen is not None:
            try:
                body = json.loads(await request.body() or b"{}")
            except (ValueError, UnicodeDecodeError):
                return json_grund(422, "Die Anfrage ist kein gültiges JSON")
            if not isinstance(body, dict):
                return json_grund(422, "Die Anfrage ist kein JSON-Objekt")
            nutzlast, grund = pruefen(body)
            if grund:
                return json_grund(422, grund)
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        aufruf = functools.partial(marketing_pult.anfrage, methode, f"/inhalte/{iid}/{pfad}", nutzlast)
        if zeitlimit:
            aufruf = functools.partial(aufruf, zeitlimit=zeitlimit)
        try:
            r = await run_in_threadpool(aufruf)
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return json_grund(422, str(f.grund or "Abgelehnt"))
            return json_grund(503, ASSISTENT_WEG)
        if not isinstance(r, dict):
            return json_grund(503, ASSISTENT_WEG)
        return JSONResponse(r, headers={"Cache-Control": "no-store"})

    def _flaechen_ids(body: dict):
        flaechen = body.get("flaechen")
        if not isinstance(flaechen, list) or not all(isinstance(b, str) for b in flaechen):
            return None
        return flaechen

    def _chat_pruefen(body: dict):
        nachricht, kontext = body.get("nachricht"), body.get("kontext", {})
        if not isinstance(nachricht, str) or not nachricht.strip():
            return None, "Die Nachricht fehlt"
        if len(nachricht) > NACHRICHT_MAX:
            return None, f"Die Nachricht darf höchstens {NACHRICHT_MAX} Zeichen haben"
        if not isinstance(kontext, dict):
            return None, "kontext muss ein Objekt sein"
        if len(json.dumps(kontext, ensure_ascii=False).encode()) > KONTEXT_MAX:
            return None, "kontext ist zu groß (höchstens 4 KB)"
        return {"nachricht": nachricht, "kontext": kontext}, None

    def _rueckgaengig_pruefen(body: dict):
        auftrag = body.get("auftrag")
        if not isinstance(auftrag, str) or not auftrag:
            return None, "auftrag fehlt"
        return {"auftrag": auftrag}, None

    def _stopp_pruefen(body: dict):
        art, auftrag = body.get("art"), body.get("auftrag")
        if art not in ("behalten", "verwerfen"):
            return None, "art muss behalten oder verwerfen sein"
        nutzlast = {"art": art}
        if auftrag is not None:
            try:
                if not isinstance(auftrag, str):
                    raise ValueError
                nutzlast["auftrag"] = str(uuid.UUID(auftrag))
            except ValueError:
                return None, "auftrag muss eine Auftrags-ID sein"
        return nutzlast, None

    def _vorschau_pruefen(body: dict):
        flaechen = _flaechen_ids(body)
        if flaechen is None:
            return None, "flaechen muss eine Liste von Block-IDs sein"
        return {"flaechen": flaechen}, None

    def _export_pruefen(body: dict):
        if body.get("bestaetigt") is not True:
            return None, "Export nur mit Bestätigung"
        newsletter, flaechen = body.get("newsletter", False), body.get("flaechen", [])
        if not isinstance(newsletter, bool):
            return None, "newsletter muss true oder false sein"
        if not isinstance(flaechen, list) or not all(isinstance(b, str) for b in flaechen):
            return None, "flaechen muss eine Liste von Block-IDs sein"
        return {"newsletter": newsletter, "flaechen": flaechen, "bestaetigt": True}, None

    @ui._gesichert_seite
    async def editor_chat(request):
        return await _agent_post(request, "chat", _chat_pruefen)

    @ui._gesichert_seite
    async def editor_chat_rueckgaengig(request):
        return await _agent_post(request, "chat/rueckgaengig", _rueckgaengig_pruefen)

    @ui._gesichert_seite
    async def editor_chat_vormerken(request):
        return await _agent_post(request, "chat/vormerkung", _chat_pruefen, methode="PUT")

    @ui._gesichert_seite
    async def editor_chat_vormerkung_loeschen(request):
        return await _agent_post(request, "chat/vormerkung", None, methode="DELETE")

    @ui._gesichert_seite
    async def editor_chat_vormerkung_starten(request):
        return await _agent_post(request, "chat/vormerkung/starten", None)

    @ui._gesichert_seite
    async def editor_chat_stopp(request):
        return await _agent_post(request, "chat/stopp", _stopp_pruefen)

    @ui._gesichert_seite
    async def editor_export_vorschau(request):
        # Rechnet auf der VM mehrere Flaechen x drei Geraete - wie die Gestaltung.
        return await _agent_post(request, "export/vorschau", _vorschau_pruefen, GESTALTUNG_ZEITLIMIT_S)

    @ui._gesichert_seite
    async def editor_export(request):
        return await _agent_post(request, "export", _export_pruefen, GESTALTUNG_ZEITLIMIT_S)

    @ui._gesichert_seite
    async def editor_chat_stand(request):
        # Nur lesen: ohne CSRF, aber hinter der Anmeldung.
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}/chat")
        except marketing_pult.PultFehler:
            return json_grund(503, ASSISTENT_WEG)
        if not isinstance(r, dict):
            return json_grund(503, ASSISTENT_WEG)
        return JSONResponse(r, headers={"Cache-Control": "no-store"})

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
    async def medien_loeschen(request):
        """Bild aus der Bibliothek loeschen (Betreiber 01.10.2026). Zwei Schritte
        wie /medien: ohne "bestaetigt" nur pruefen und berichten, mit
        "bestaetigt" erneut pruefen und loeschen. Gesperrt wie dort, dazu
        Bilder in Newslettern (ui.medien_loeschsperre)."""
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            return json_grund(422, "Die Anfrage ist kein gültiges JSON")
        if not isinstance(body, dict):
            return json_grund(422, "Die Anfrage ist kein JSON-Objekt")
        name, bestaetigt = body.get("name"), body.get("bestaetigt", False)
        if not isinstance(name, str) or not isinstance(bestaetigt, bool):
            return json_grund(422, "name (Text) und bestaetigt (true/false) erwartet")
        basis, fehler = await run_in_threadpool(ui.server.medien.pruefe, name)
        if fehler:
            return json_grund(404, str(fehler))
        if basis.startswith("platzhalter-"):
            return json_grund(422, "Platzhalter gehören zu den Vorlagen und bleiben")
        try:
            entwuerfe, newsletter, sperre = await run_in_threadpool(ui.medien_loeschsperre, basis)
        except Exception:   # noqa: BLE001 - Sales-DB weg: unbekannt ist nicht unbenutzt
            return json_grund(503, "Prüfung gerade nicht möglich")
        if not bestaetigt:
            return JSONResponse({"name": basis, "entwuerfe": len(entwuerfe), "sperre": sperre,
                                 "newsletter": [{"titel": v.get("titel"), "status": v.get("status")}
                                                for v in newsletter]},
                                headers={"Cache-Control": "no-store"})
        if sperre:
            return json_grund(409, sperre)
        fehler = await run_in_threadpool(ui.medien_datei_loeschen, basis)
        if fehler:
            return json_grund(500, fehler)
        ui.LOG.warning("Medien (Editor): %s gelöscht (%d Entwürfe verwiesen darauf)", basis, len(entwuerfe))
        return JSONResponse({"geloescht": basis}, headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_anhang(request):
        """Bild oder Dokument fuer den Gestaltungs-Chat ablegen. Gleicher Ordner
        und gleiche Pruefung wie /medien/hochladen (ui.medien_ablegen); der Name
        wird auf Marketings Anhangsmuster normalisiert, eine Kollision bekommt
        ein Suffix - nie ein stilles Ersetzen."""
        form = await request.form()
        marke = request.headers.get("x-csrf", "")
        if not (ui._csrf_ok(form) or (marke and hmac.compare_digest(marke, ui.CSRF_TOKEN))):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        datei = form.get("datei")
        if datei is None or not getattr(datei, "filename", ""):
            return json_grund(422, "Es wurde keine Datei mitgeschickt")
        stamm, endung = ui.server.medien.anhang_name(datei.filename)
        if stamm is None:
            return json_grund(422, endung)
        med = ui.server.medien
        for n in range(1, 1000):
            basis = f"{stamm}{endung}" if n == 1 else f"{stamm}-{n}{endung}"
            if med.intern(basis) or med.entwurfsbild(basis):
                # Das Suffix machte daraus einen internen Namen (terminkarte-2.pdf):
                # fuer alle weiteren Kandidaten mit Praefix, sonst unsichtbar.
                stamm = "anhang-" + stamm[:_STAMM_FUER_PRAEFIX]
                basis = f"{stamm}-{n}{endung}"
            fehler = ui.server.medien.pruefe_neuen_namen(basis)[1]
            if fehler:   # kann nach der Normalisierung nicht vorkommen - Sicherheitsnetz
                return json_grund(422, fehler)
            if med.liegt_schon(basis):
                continue
            groesse, abgelehnt = await ui.medien_ablegen(datei, basis, ersetzen=False)
            if abgelehnt and abgelehnt[0] == 409:    # zwischen Pruefung und Ablegen belegt
                await datei.seek(0)
                continue
            break
        else:
            return json_grund(422, "Zu viele gleichnamige Dateien")
        if abgelehnt:
            status, text = abgelehnt
            return json_grund(500 if status == 500 else 422, text)
        # Chat-Kontext ist nicht fuer Kunden gedacht: ohne Zeile in medien_meta
        # gilt "Bot darf senden". Gesperrt anlegen; der Betreiber gibt auf /medien
        # ausdruecklich frei. Gelingt das nicht, bleibt keine sendbare Datei liegen.
        try:
            await run_in_threadpool(ui.server.medien_meta_setzen, basis, False)
        except Exception:   # noqa: BLE001 - fail-closed
            await run_in_threadpool(ui.medien_datei_loeschen, basis)
            return json_grund(503, "Anhang konnte nicht gesichert werden - bitte erneut versuchen")
        # Ohne Zeile gilt eine Datei als Gemeinsam und waere fuer jede Firma
        # sichtbar: der Anhang gehoert der Firma des Newsletters. Gelingt das
        # nicht, bleibt keine Datei liegen.
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/medien/zuordnen",
                                    {"namen": [basis]})
        except marketing_pult.PultFehler:
            await run_in_threadpool(ui.medien_datei_loeschen, basis)
            return json_grund(503, "Anhang konnte nicht der Firma zugeordnet werden - bitte erneut versuchen")
        ui.LOG.info("Medien (Editor-Anhang): %s abgelegt (%d Byte)", basis, groesse)
        return JSONResponse({"name": basis, "art": ui.server.medien.anhang_art(basis), "groesse": groesse},
                            headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def medien_json(request):
        """Bildwahl des Editors: nur Bilder der Firma des Newsletters plus
        gemeinsame. Die Regel gehoert der Marketing-API (POST /medien/sichtbar);
        hier wird nur weitergereicht. Ist die Zuordnung nicht lesbar, bleibt die
        Liste leer (fail-closed) und die Bildwahl zeigt den Hinweis."""
        try:
            iid = str(uuid.UUID(request.query_params.get("iid", "")))
        except ValueError:
            return json_grund(422, "iid fehlt")
        try:
            eintraege = await run_in_threadpool(ui.server.medien.liste, True)
        except OSError:
            eintraege = []
        alle = [n for n, _groesse in eintraege if os.path.splitext(n)[1].lower() in BILD_ENDUNGEN]
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/inhalte/{iid}")
            mandant = str(((d or {}).get("inhalt") or {}).get("mandant") or "")
            if not mandant:   # keine Firma am Inhalt = Zuordnung nicht lesbar (fail-closed)
                raise ValueError("Inhalt ohne Firma")
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", "/medien/sichtbar",
                                        {"mandant": mandant, "namen": alle})
            sichtbar = set(r["sichtbar"])
            ergebnis = {"bilder": [n for n in alle if n in sichtbar],
                        "zuordnung": dict(r.get("zuordnung") or {}),
                        "mandanten": list(r.get("mandanten") or []),
                        "mandant": mandant, "hinweis": None}
        except (marketing_pult.PultFehler, TypeError, KeyError, ValueError, AttributeError):
            ergebnis = {"bilder": [], "zuordnung": {}, "mandanten": [], "mandant": "",
                        "hinweis": "Bildzuordnung nicht erreichbar"}
        return JSONResponse(ergebnis, headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_medien_zuordnung(request):
        """Bild einer Firma oder (mandant null) allen zuordnen. Fuer "Gemeinsam"
        geht immer null an die API - nie "", das dort auf vibemind zurueckfiele."""
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            return json_grund(422, "Die Anfrage ist kein gültiges JSON")
        if not isinstance(body, dict):
            return json_grund(422, "Die Anfrage ist kein JSON-Objekt")
        name, mandant = body.get("name"), body.get("mandant", "")
        if not isinstance(name, str) or not (mandant is None or (isinstance(mandant, str) and mandant)):
            return json_grund(422, "name (Text) und mandant (Firma oder null) erwartet")
        basis, fehler = await run_in_threadpool(ui.server.medien.pruefe_anzeige, name)
        if fehler or not basis:
            return json_grund(422, str(fehler or "Unbekannte Datei"))
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/medien/zuordnung",
                                    {"dateiname": basis, "mandant": mandant})
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return json_grund(422, str(f.grund or "Abgelehnt"))
            return json_grund(503, "Zuordnung gerade nicht möglich")
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    async def _freigabe_schritt(request, schritt: str):
        """Einreichen bzw. Zurueckziehen: nur durchreichen, die Regeln liegen in der API/DB."""
        marke = request.headers.get("x-csrf", "")
        if not marke or not hmac.compare_digest(marke, ui.CSRF_TOKEN):
            return json_grund(403, "Fehlende oder falsche CSRF-Marke")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/{schritt}",
                                        {"von": ui._ui_akteur(request)})
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return json_grund(422, str(f.grund or "Abgelehnt"))
            return json_grund(503, "Marketing gerade nicht erreichbar")
        return JSONResponse(r if isinstance(r, dict) else {}, headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def editor_einreichen(request):
        return await _freigabe_schritt(request, "einreichen")

    @ui._gesichert_seite
    async def editor_zurueckziehen(request):
        return await _freigabe_schritt(request, "zurueckziehen")

    async def bild(request):
        # OHNE Anmeldung (AnmeldeWache laesst /marketing/bild/<t>/<n> durch):
        # die abgeschottete Vorschau schickt keine Anmelde-Cookies. Die
        # Berechtigung ist die Signatur - 15 Minuten, nur Bilder aus den
        # Medien (auch Entwurfsbilder gs-*), keine internen Unterlagen
        # (Terminkarten tragen Kundendaten).
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
        basis, fehler = await run_in_threadpool(medien.pruefe_anzeige, name)
        if fehler or not basis:
            return nicht_da
        typ = mimetypes.guess_type(basis)[0] or medien.ERLAUBT.get(endung, ("", ""))[1]
        if not typ or not typ.startswith("image/"):
            return nicht_da
        kopf = {"Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": CSP_BILD}
        if request.query_params.get("sw") == "1":
            # Schwarz-Weiss-Fassung (Vorlagen mit Graustufen-Bildern). Pillow-
            # Fehler -> Originaldatei, nie ein 500 in der Vorschau.
            grau = await run_in_threadpool(_graustufen, medien.pfad(basis))
            if grau is not None:
                return Response(grau[0], media_type=grau[1], headers=kopf)
        return FileResponse(medien.pfad(basis), media_type=typ, headers=kopf)

    async def schrift(request):
        # OHNE Anmeldung (AnmeldeWache laesst /marketing/schrift/<datei> durch):
        # die abgeschottete Vorschau und Mailprogramme laden die Schriften
        # ohne Cookies, aus undurchsichtiger Herkunft -> CORS offen. Nur die
        # Registerdateien und schriften.css, sonst 404.
        datei = request.path_params["datei"]
        kopf = {"Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff"}
        if datei == "schriften.css":
            return Response(schriften.css(), media_type="text/css", headers=kopf)
        if not schriften.datei_ok(datei):
            return Response("Nicht gefunden", status_code=404, media_type="text/plain")
        return Response((schriften.ORDNER / datei).read_bytes(), media_type="font/woff2", headers=kopf)

    @ui._gesichert_seite
    async def vorlagen_seite(request):
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/vorlagen?mandant={urllib.parse.quote(m)}&status=freigegeben")
        except marketing_pult.PultFehler as f:
            return _fehler(ui, f)
        csrf = f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

        def karte(v: dict) -> str:
            n = str(v.get("name") or "")
            if not VORLAGE_NAME.match(n):
                return ""
            beschreibung = str(v.get("beschreibung") or n)
            return (f'<div class="layout-karte"><div class="layout-rahmen">'
                    f'<span class="layout-platzhalter">{e(beschreibung)}</span>'
                    f'<iframe class="layout-bild" sandbox tabindex="-1" loading="lazy" title="Vorschau {e(beschreibung)}" '
                    f'src="/marketing/vorlage-bild/{e(n)}"></iframe></div>'
                    f'<b>{e(beschreibung)}</b><span class="meta">{e(n)} &middot; Fassung '
                    f'{int(v.get("fassung") or 1)}</span>'
                    f'<form method="post" action="/marketing/aus-vorlage" class="aktion">{csrf}'
                    f'<input type="hidden" name="vorlage" value="{e(n)}">'
                    f'<label>Titel <input name="titel" required maxlength="{TITEL_MAX}" '
                    f'placeholder="z. B. Newsletter Oktober"></label>'
                    f'<button class="primaer" type="submit">Neu aus Vorlage</button></form></div>')

        karten = "".join(karte(v) for v in d.get("vorlagen") or [])
        rumpf = (marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, "/marketing/vorlagen")
                 + f'<p class="meta">Eine Vorlage wählen, einen Titel geben - der neue Entwurf öffnet '
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
            q["mandant"] = (await marketing_mandant.firma(request))[0]
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
            m, _liste = await marketing_mandant.firma(request)
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", "/inhalte/aus_vorlage",
                                        {"vorlage": vorlage, "titel": titel, "mandant": m})
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
        Route("/marketing/editor/medien/loeschen", medien_loeschen, methods=["POST"]),
        Route("/marketing/editor/{iid}", editor_seite),
        Route("/marketing/editor/{iid}/speichern", editor_speichern, methods=["POST"]),
        Route("/marketing/editor/{iid}/bild", editor_bild, methods=["POST"]),
        Route("/marketing/editor/{iid}/einreichen", editor_einreichen, methods=["POST"]),
        Route("/marketing/editor/{iid}/zurueckziehen", editor_zurueckziehen, methods=["POST"]),
        Route("/marketing/editor/{iid}/anhang", editor_anhang, methods=["POST"]),
        Route("/marketing/editor/{iid}/medien/zuordnung", editor_medien_zuordnung, methods=["POST"]),
        Route("/marketing/editor/{iid}/gestaltung", editor_gestaltung, methods=["POST"]),
        Route("/marketing/editor/{iid}/chat", editor_chat, methods=["POST"]),
        Route("/marketing/editor/{iid}/chat.json", editor_chat_stand),
        Route("/marketing/editor/{iid}/chat/rueckgaengig", editor_chat_rueckgaengig, methods=["POST"]),
        Route("/marketing/editor/{iid}/chat/vormerkung", editor_chat_vormerken, methods=["PUT"]),
        Route("/marketing/editor/{iid}/chat/vormerkung", editor_chat_vormerkung_loeschen, methods=["DELETE"]),
        Route("/marketing/editor/{iid}/chat/vormerkung/starten", editor_chat_vormerkung_starten, methods=["POST"]),
        Route("/marketing/editor/{iid}/chat/stopp", editor_chat_stopp, methods=["POST"]),
        Route("/marketing/editor/{iid}/export/vorschau", editor_export_vorschau, methods=["POST"]),
        Route("/marketing/editor/{iid}/export", editor_export, methods=["POST"]),
        Route("/marketing/editor/{iid}/stand.json", editor_stand),
        Route("/marketing/bild/{token}/{name}", bild),
        Route("/marketing/schrift/{datei}", schrift),
        Route("/marketing/vorlagen", vorlagen_seite),
        Route("/marketing/vorlage-bild/{name}", vorlage_bild),
        Route("/marketing/aus-vorlage", aus_vorlage, methods=["POST"]),
        Route("/static/editor/{datei}", statik),
    ]
