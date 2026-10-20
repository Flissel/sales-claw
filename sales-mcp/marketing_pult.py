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
# Einreichen und Mail-Vorschau einer Collage rendern die Bildstuecke in Chromium (die API wartet selbst bis zu
# 60 s auf Chromium und bis zu 90 s auf eine laufende Erzeugung): nicht nach 8 s abbrechen.
LANG_ZEITLIMIT_S = 120


class PultFehler(Exception):
    def __init__(self, art: str, grund: str = "", koerper: dict | None = None):
        super().__init__(f"{art}: {grund}")
        self.art, self.grund = art, grund
        # Der Fehlerkoerper der API (nur bei HTTP-Fehlern): /medien/platzhalter nennt dort
        # bei 503 die schon umgestellten Entwuerfe.
        self.koerper = koerper if isinstance(koerper, dict) else None


def eingerichtet() -> bool:
    return bool(URL and KEY)


def anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False,
            zeitlimit: float | None = None):
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
        with urllib.request.urlopen(req, timeout=ZEITLIMIT_S if zeitlimit is None else zeitlimit) as r:
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
            raise PultFehler("nicht_erreichbar", str(e.code), koerper_fehler)
        if e.code in (404, 409, 422):
            raise PultFehler("abgelehnt", grund or str(e.code), koerper_fehler)
        raise PultFehler("unbekannt", str(e.code), koerper_fehler)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PultFehler("nicht_erreichbar", type(e).__name__)


def medien_verweise(name: str, mandant: str | None = None) -> list:
    """Welche Marketing-Inhalte tragen diese Mediendatei noch (neueste Fassung
    eines nicht abgelehnten Inhalts oder die freigegebene)? Mit `mandant` kommen
    Treffer anderer Firmen ohne Titel und mit "eigen": false. Wirft PultFehler -
    der Aufrufer loescht dann NICHT (unbekannt ist nicht unbenutzt)."""
    from urllib.parse import quote
    pfad = f"/medien/verweise?name={quote(name, safe='')}"
    if mandant:
        pfad += f"&mandant={quote(mandant, safe='')}"
    r = anfrage("GET", pfad)
    verweise = r.get("verweise") if isinstance(r, dict) else None
    if not isinstance(verweise, list):
        raise PultFehler("unbekannt", "Antwort ohne Verweisliste")
    return [v for v in verweise if isinstance(v, dict)]


def medien_platzhalter(name: str, mandant: str, von: str) -> dict:
    """Stellt jeden Entwurf der Firma, der das Bild traegt, auf Platzhalter um (neue
    Fassung). -> {"umgestellt": [{id, titel, fassung}], "gesperrt": [{id, titel, grund}]}.
    Die Datei darf nur geloescht werden, wenn "gesperrt" leer ist."""
    r = anfrage("POST", "/medien/platzhalter", {"name": name, "mandant": mandant, "von": von})
    if (not isinstance(r, dict) or not isinstance(r.get("umgestellt"), list)
            or not isinstance(r.get("gesperrt"), list)):
        raise PultFehler("unbekannt", "Antwort ohne Platzhalter-Ergebnis")
    return {"umgestellt": [z for z in r["umgestellt"] if isinstance(z, dict)],
            "gesperrt": [z for z in r["gesperrt"] if isinstance(z, dict)]}


def medien_vergessen(name: str) -> None:
    """Entfernt die Firmen-Zuordnung der Datei. Die API erlaubt das NUR, nachdem die
    Datei geloescht ist (sonst 409 -> PultFehler("abgelehnt"))."""
    anfrage("POST", "/medien/vergessen", {"name": name})

def inhalt_loeschen(iid: str, mandant: str, von: str) -> dict:
    """Loescht einen Entwurf endgueltig (POST /inhalte/{iid}/loeschen). Die
    Regeln (Status, Firma, laufender Assistent) liegen in der DB; ihre
    Klartext-Ablehnung kommt als PultFehler("abgelehnt", Grund). Antwort:
    {"geloescht": iid, "titel": ...}."""
    from urllib.parse import quote
    r = anfrage("POST", f"/inhalte/{quote(iid, safe='')}/loeschen",
                {"mandant": mandant, "von": von})
    if not isinstance(r, dict) or "geloescht" not in r:
        raise PultFehler("unbekannt", "Antwort ohne Loeschbestaetigung")
    return r
