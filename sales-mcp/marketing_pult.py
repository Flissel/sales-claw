"""Client zur Marketing-API (Pult-Router, Spec 2026-09-29-marketing-pult-
design.md §3.4). Einzige Stelle, an der sales-ui mit Marketing spricht.
Schluessel nur aus der Umgebung, nie im Log."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

URL = os.environ.get("MARKETING_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("MARKETING_PULT_KEY", "").strip()
ZEITLIMIT_S = 8


class PultFehler(Exception):
    def __init__(self, art: str, grund: str = ""):
        super().__init__(f"{art}: {grund}")
        self.art, self.grund = art, grund


def eingerichtet() -> bool:
    return bool(URL and KEY)


def anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False):
    if not eingerichtet():
        raise PultFehler("nicht_verbunden", "MARKETING_PULT_URL/KEY fehlt")
    koerper = json.dumps(daten).encode("utf-8") if daten is not None else None
    req = urllib.request.Request(
        f"{URL}/api/pult{pfad}", data=koerper, method=methode,
        headers={"Content-Type": "application/json"})
    # Der Schluessel folgt keiner Umleitung: urllib gibt normale Koepfe bei
    # einem 30x an das neue Ziel weiter, "unredirected" Koepfe nicht.
    req.add_unredirected_header("X-Pult-Key", KEY)
    try:
        with urllib.request.urlopen(req, timeout=ZEITLIMIT_S) as r:
            inhalt = r.read()
            if roh:
                return inhalt, r.headers.get("Content-Type", "application/octet-stream")
            try:
                return json.loads(inhalt or b"{}")
            except ValueError:
                # 200, aber kein JSON (z.B. eine Proxy- oder Anmeldeseite).
                raise PultFehler("unbekannt", "Antwort ist kein JSON")
    except urllib.error.HTTPError as e:
        try:
            koerper_fehler = json.loads(e.read() or b"{}")
        except (ValueError, OSError):
            koerper_fehler = {}
        grund = koerper_fehler.get("detail", "") if isinstance(koerper_fehler, dict) else ""
        if not isinstance(grund, str):
            # FastAPI-Validierungsfehler tragen eine Liste - kein Text fuer Menschen.
            grund = "Eingabe ungueltig"
        # 503 heisst zweierlei: Schluessel auf der API-Seite nicht gesetzt
        # ("misconfigured") = nicht verbunden; sonst ist die Marketing-DB weg.
        if e.code == 401 or (e.code == 503 and grund.startswith("misconfigured")):
            raise PultFehler("nicht_verbunden", str(e.code))
        if e.code == 503:
            raise PultFehler("nicht_erreichbar", str(e.code))
        if e.code in (404, 422):
            raise PultFehler("abgelehnt", grund or str(e.code))
        raise PultFehler("unbekannt", str(e.code))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PultFehler("nicht_erreichbar", type(e).__name__)


def medien_verweise(name: str) -> list:
    """Welche Marketing-Inhalte tragen diese Mediendatei noch (neueste Fassung
    eines nicht abgelehnten Inhalts oder die freigegebene)? Wirft PultFehler -
    der Aufrufer loescht dann NICHT (unbekannt ist nicht unbenutzt)."""
    from urllib.parse import quote
    r = anfrage("GET", f"/medien/verweise?name={quote(name, safe='')}")
    verweise = r.get("verweise") if isinstance(r, dict) else None
    if not isinstance(verweise, list):
        raise PultFehler("unbekannt", "Antwort ohne Verweisliste")
    return [v for v in verweise if isinstance(v, dict)]
