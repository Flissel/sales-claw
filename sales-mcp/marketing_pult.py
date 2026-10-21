"""Client zur Marketing-API (Pult-Router, Spec 2026-09-29-marketing-pult-
design.md §3.4). Einzige Stelle, an der sales-ui mit Marketing spricht.
Schluessel nur aus der Umgebung, nie im Log."""
from __future__ import annotations

import os

import pult_http
from pult_http import PultFehler

URL = os.environ.get("MARKETING_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("MARKETING_PULT_KEY", "").strip()
ZEITLIMIT_S = 8
# Einreichen und Mail-Vorschau einer Collage rendern die Bildstuecke in Chromium (die API wartet selbst bis zu
# 60 s auf Chromium und bis zu 90 s auf eine laufende Erzeugung): nicht nach 8 s abbrechen.
LANG_ZEITLIMIT_S = 120


def eingerichtet() -> bool:
    return bool(URL and KEY)


def anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False,
            zeitlimit: float | None = None):
    if not eingerichtet():
        raise PultFehler("nicht_verbunden", "MARKETING_PULT_URL/KEY fehlt")
    return pult_http.anfrage(URL, KEY, methode, pfad, daten, roh,
                             ZEITLIMIT_S if zeitlimit is None else zeitlimit)


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
