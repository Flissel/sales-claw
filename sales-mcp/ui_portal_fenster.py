"""Portal-Fenster: entfernt.

Das noVNC-Fenster des Bewerbungs-Bots gibt es seit Schritt A der Direktlink-Umstellung nicht mehr; die
Portal-Karte zeigt stattdessen die Adresse des Bewerbungsformulars. Dieses Relay bleibt nur als Stumpf, damit
alte Seiten und Lesezeichen eine klare Antwort bekommen: dieselben Pfade unter /freigaben/bewerbung/fenster,
HTTP antwortet 410, der WebSocket `/ws` wird vor dem Annehmen mit Code 1008 geschlossen. Nichts fragt die
Zentrale oder den Container. Das Relay ist mit Schritt A entfernt (nur noch dieser Stumpf); Schritt B loescht diese Datei samt
`trennen` (ui.py) und den Einstellungen."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

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
PFAD = "/freigaben/bewerbung/fenster"

# Die eine Verbindung dieses Prozesses (aus der Zeit vor Schritt A; es oeffnet keine mehr).
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


async def _entfernt(request) -> Response:
    return Response("Fenster entfernt", status_code=410, media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


async def _ws_entfernt(websocket) -> None:
    # Vor dem Annehmen schliessen: der Handshake scheitert, es gibt nie eine offene Verbindung.
    await websocket.close(1008)


def routen(ui) -> list:
    return [
        Route(f"{PFAD}/seite", _entfernt),
        Route(f"{PFAD}/fenster.js", _entfernt),
        Route(f"{PFAD}/novnc/{{pfad:path}}", _entfernt),
        WebSocketRoute(f"{PFAD}/ws", _ws_entfernt),
    ]
