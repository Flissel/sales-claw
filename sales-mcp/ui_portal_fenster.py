"""Portal-Fenster: das Chromium des Bewerbungs-Bots im Container, sichtbar in der sales-ui.

Der Container (`bewerbung-portal`, anderes Repo) zeigt seinen Bildschirm als VNC-WebSocket
(x11vnc + websockify, `ws://bewerbung-portal:6080`, Netz `bewerbung-fenster`, HTTP-Basic-Anmeldung
mit einem gemeinsamen Schluessel). Hier liegen drei Teile, alle unter /freigaben/bewerbung und damit
hinter Host-/Origin-/Sitzungs-Pruefung und der Rolle `freigeben` im Basis-Laden (`_ADMIN_BASIS_PFADE`,
HostWache/AnmeldeWache auch fuer WebSockets):

- die noVNC-Dateien (`core/`, `vendor/`; im Image unter /app/static/novnc),
- eine eigene kleine Seite plus `fenster.js` (noVNCs `vnc_lite.html` hat ein Inline-Skript, das die
  CSP `script-src 'self'` sperrt),
- die Weiterleitung `{PFAD}/ws`: erst die Zentrale fragen, ob gerade ein Fenster gewollt ist, dann
  Bytes zwischen Browser und Container durchreichen.

Der Schluessel (BEWERBUNG_FENSTER_SCHLUESSEL) bleibt auf dem Server: er geht nur im Authorization-Kopf
der Verbindung nach innen, nie in HTML, JS, Antworten, Logs oder Fehlertexte."""
from __future__ import annotations

import asyncio
import base64
import html
import logging
import mimetypes
import os
from pathlib import Path

import websockets
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute

import bewerbung_pult

LOG = logging.getLogger("sales-ui")
# Auf DEBUG schreibt websockets die Kopfzeilen des Handshakes ins Log - darunter Authorization
# (der Fenster-Schluessel). Die Stufe wird hier festgenagelt, nie darunter.
# ACHTUNG: gilt nur ab dem Import - ein spaeteres DEBUG-basicConfig oder setLevel(DEBUG) loggte den Authorization-Kopf.
logging.getLogger("websockets").setLevel(logging.INFO)

FENSTER_WS = os.environ.get("BEWERBUNG_FENSTER_WS", "").strip().rstrip("/")
FENSTER_SCHLUESSEL = os.environ.get("BEWERBUNG_FENSTER_SCHLUESSEL", "").strip()
NOVNC_DIR = Path(os.environ.get("NOVNC_DIR", "/app/static/novnc"))
JS_DATEI = Path(__file__).resolve().parent / "static" / "portal_fenster" / "fenster.js"
PFAD = "/freigaben/bewerbung/fenster"
CSP_NOVNC = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
             "font-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
ZUSTAENDE = ("fenster_angefragt", "im_fenster")
NACHPRUEFEN_S = 10   # so oft prueft das offene Fenster Zentrale und Sitzung erneut

_TYPEN = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
          ".html": "text/html; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
          ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon"}

SEITE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Portal-Fenster</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
html, body { height: 100%; margin: 0; background: #1b1b1b; color: #eee; font: 14px system-ui, sans-serif; }
#status { height: 28px; line-height: 28px; padding: 0 10px; box-sizing: border-box; }
#schirm { height: calc(100% - 28px); }
</style>
</head>
<body>
<div id="status">Verbinde ...</div>
<div id="schirm"></div>
<script type="module" src="fenster.js"></script>
</body>
</html>
"""

# Die eine Verbindung dieses Prozesses: eine neue schliesst die alte (Code 1000).
_AKTUELL: "_Verbindung | None" = None


class _Verbindung:
    def __init__(self, benutzer: str = ""):
        self.benutzer = benutzer   # wer das Fenster geoeffnet hat (Name aus der Sitzung des Handshakes)
        self.schleife = asyncio.get_running_loop()
        self.ende = asyncio.Event()

    def beenden(self):
        # Die alte Verbindung kann in einer anderen Ereignisschleife laufen (Tests): threadsicher setzen.
        try:
            self.schleife.call_soon_threadsafe(self.ende.set)
        except RuntimeError:   # Schleife schon zu: die Verbindung ist ohnehin weg
            pass


def trennen(name: "str | None") -> None:
    """Beendet das offene Fenster, wenn `name` es geoeffnet hat (Abmelden): das Cookie des Handshakes gilt
    sonst bis zu 12 h weiter. Ein anderer Benutzer (oder keiner) trennt nichts."""
    aktuell = _AKTUELL
    if aktuell is not None and name and aktuell.benutzer == name:
        aktuell.beenden()


def eingerichtet() -> bool:
    # Wie bewerbung_pult.eingerichtet: ein Schluessel mit Steuerzeichen, Leerraum oder Nicht-ASCII ist als
    # HTTP-Kopf nicht sendbar - dann lieber "nicht eingerichtet" als ein Versuch.
    s = FENSTER_SCHLUESSEL
    return bool(FENSTER_WS and s and s.isascii() and s.isprintable()
                and not any(z.isspace() for z in s)
                and (NOVNC_DIR / "core" / "rfb.js").is_file()
                and bewerbung_pult.eingerichtet())


def fenster_rahmen(ui) -> str:
    """Der Rahmen fuer den Bewerbungen-Reiter; leer, solange nichts eingerichtet ist."""
    if not eingerichtet():
        return ""
    adresse = html.escape(f"{PFAD}/seite", quote=True)
    return (f'<iframe class="fenster" title="Portal-Fenster" src="{adresse}"></iframe>'
            f'<p><a href="{adresse}" target="_blank" rel="noopener noreferrer">Groß öffnen</a></p>')


def _kopfe(cache: str) -> dict:
    return {"Content-Security-Policy": CSP_NOVNC, "X-Frame-Options": "SAMEORIGIN", "Cache-Control": cache}


def _nicht_da() -> Response:
    return Response("Nicht gefunden", status_code=404, media_type="text/plain")


def _typ(datei: Path) -> str:
    return _TYPEN.get(datei.suffix.lower()) or mimetypes.guess_type(datei.name)[0] or "application/octet-stream"


def _darf(request, ui) -> bool:
    """Wie ui_freigabe_bewerbung: nur die Rolle `freigeben` im Basis-Laden. Ohne Anmeldung (kein
    UI_SESSION_SECRET, Uebergangszustand) gibt es keine Rolle - dann auch keine Dateien."""
    return bool(ui._pfad_erlaubt(str(request.scope.get("benutzer_rolle") or ""), PFAD))


async def seite(request, ui) -> Response:
    if not eingerichtet() or not _darf(request, ui):
        return _nicht_da()
    return Response(SEITE, media_type="text/html; charset=utf-8", headers=_kopfe("no-store"))


async def fenster_js(request, ui) -> Response:
    if not eingerichtet() or not _darf(request, ui):
        return _nicht_da()
    try:
        inhalt = await run_in_threadpool(JS_DATEI.read_bytes)
    except OSError:
        return _nicht_da()
    return Response(inhalt, media_type="text/javascript", headers=_kopfe("no-store"))


def _aufloesen(pfad: str) -> Path | None:
    """Datei unter NOVNC_DIR, sonst None. Auch Symlinks, die hinausfuehren, zaehlen nicht."""
    try:
        wurzel = NOVNC_DIR.resolve()
        datei = (wurzel / pfad).resolve()
        datei.relative_to(wurzel)
        return datei if datei.is_file() else None
    except (OSError, ValueError):
        return None


async def novnc_datei(request, ui) -> Response:
    if not eingerichtet() or not _darf(request, ui):
        return _nicht_da()
    datei = _aufloesen(request.path_params.get("pfad", ""))
    if datei is None:
        return _nicht_da()
    try:
        inhalt = await run_in_threadpool(datei.read_bytes)
    except OSError:
        return _nicht_da()
    return Response(inhalt, media_type=_typ(datei), headers=_kopfe("private, no-cache"))


async def _schliessen(ws, code: int) -> None:
    try:
        await ws.close(code)
    except Exception:   # schon zu
        pass


async def _zentrale_erlaubt() -> bool:
    """Will die Zentrale gerade ein Fenster? Jeder Fehler und jeder andere Zustand: nein."""
    try:
        antwort = await run_in_threadpool(bewerbung_pult.anfrage, "GET", "/portal/fenster", zeitlimit=3)
    except Exception as e:   # PultFehler und alles andere: kein Fenster
        LOG.warning("portal-fenster: Zentrale nicht erreichbar (%s)", type(e).__name__)
        return False
    return isinstance(antwort, dict) and antwort.get("zustand") in ZUSTAENDE


async def _sitzung_gilt(websocket, ui) -> bool:
    """Die Sitzung des Handshakes gilt noch: Signatur und Ablauf, Benutzer aktiv, Rolle freigeben,
    Pfad erlaubt. Ohne `ui` oder bei jedem Fehler: nein."""
    if ui is None:
        return False

    def pruefen() -> bool:
        if not ui.UI_SESSION_SECRET:   # leerer Schluessel: jedes Cookie waere "gueltig" (Tiefenverteidigung)
            return False
        name = ui._sitzung_pruefen(ui._cookie_wert(websocket.scope, ui.SITZUNG_COOKIE))
        benutzer = ui._benutzer_lesen(name) if name else None
        return bool(benutzer and benutzer["rolle"] == "freigeben"
                    and ui._pfad_erlaubt(benutzer["rolle"], websocket.scope["path"]))

    try:
        return await run_in_threadpool(pruefen)
    except Exception as e:
        LOG.warning("portal-fenster: Sitzung nicht pruefbar (%s)", type(e).__name__)
        return False


async def _nachpruefen(websocket, ui) -> None:
    """Kehrt zurueck, sobald Zentrale oder Sitzung das Fenster nicht mehr tragen."""
    while True:
        await asyncio.sleep(NACHPRUEFEN_S)
        if not await _zentrale_erlaubt() or not await _sitzung_gilt(websocket, ui):
            return


async def weiterleitung(websocket, ui=None) -> None:
    global _AKTUELL
    if not eingerichtet():
        await websocket.close(1008)
        return
    if not await _zentrale_erlaubt():
        await websocket.close(1008)
        return

    angeboten = websocket.scope.get("subprotocols") or []
    await websocket.accept(subprotocol="binary" if "binary" in angeboten else None)

    ich = _Verbindung(str(websocket.scope.get("benutzer_name") or ""))
    alt, _AKTUELL = _AKTUELL, ich
    if alt is not None:
        alt.beenden()

    anmeldung = base64.b64encode(f"portal:{FENSTER_SCHLUESSEL}".encode()).decode()
    upstream = None
    try:
        upstream = await websockets.connect(
            FENSTER_WS + "/websockify", subprotocols=["binary"], max_size=16 * 2**20, open_timeout=5,
            close_timeout=2, extra_headers=[("Authorization", f"Basic {anmeldung}")])
    except Exception as e:   # nur der Typ ins Log: Text koennte Adresse und Zugangsdaten tragen
        LOG.warning("portal-fenster: Container nicht erreichbar (%s)", type(e).__name__)
        if _AKTUELL is ich:
            _AKTUELL = None
        await _schliessen(websocket, 1011)
        return

    async def hoch():
        while True:
            nachricht = await websocket.receive()
            if nachricht["type"] == "websocket.disconnect":
                return
            daten = nachricht.get("bytes")
            if daten is None:
                daten = nachricht.get("text")
            if daten is not None:
                await upstream.send(daten)

    async def runter():
        async for daten in upstream:
            if isinstance(daten, (bytes, bytearray)):
                await websocket.send_bytes(bytes(daten))
            else:
                await websocket.send_text(daten)

    pruefung = asyncio.ensure_future(_nachpruefen(websocket, ui))
    aufgaben = [asyncio.ensure_future(hoch()), asyncio.ensure_future(runter()),
                asyncio.ensure_future(ich.ende.wait()), pruefung]
    code = 1000
    try:
        fertig, _ = await asyncio.wait(aufgaben, return_when=asyncio.FIRST_COMPLETED)
        if pruefung in fertig:
            code = 1008
    finally:
        for a in aufgaben:
            a.cancel()
        await asyncio.gather(*aufgaben, return_exceptions=True)
        if _AKTUELL is ich:
            _AKTUELL = None
        # Client und Container gleichzeitig schliessen: ein haengender Container (Close-Handshake)
        # haelt den Browser so nicht fest.
        await asyncio.gather(_schliessen(websocket, code), _schliessen(upstream, 1000),
                             return_exceptions=True)


def routen(ui) -> list:
    async def ws_weiterleitung(websocket) -> None:
        # `weiterleitung` wird beim Aufruf nachgeschlagen (Tests umhuellen sie).
        await weiterleitung(websocket, ui)

    async def http_seite(request) -> Response:
        return await seite(request, ui)

    async def http_js(request) -> Response:
        return await fenster_js(request, ui)

    async def http_novnc(request) -> Response:
        return await novnc_datei(request, ui)

    return [
        Route(f"{PFAD}/seite", http_seite),
        Route(f"{PFAD}/fenster.js", http_js),
        Route(f"{PFAD}/novnc/{{pfad:path}}", http_novnc),
        WebSocketRoute(f"{PFAD}/ws", ws_weiterleitung),
    ]
