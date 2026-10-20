"""Client zur Pult-API der Zentrale des Bewerbungs-Bots (`/api/pult`, Spec
2026-10-20-hermes-pruefer-design.md §5.3). Einzige Stelle, an der sales-ui mit der Zentrale
spricht; Vertrag und Fehlerabbildung wie beim Marketing-Pult (pult_http).
Schluessel nur aus der Umgebung, nie im Log."""
from __future__ import annotations

import os

import pult_http
from pult_http import PultFehler

URL = os.environ.get("BEWERBUNG_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("BEWERBUNG_PULT_KEY", "").strip()
ZEITLIMIT_S = 8


def eingerichtet() -> bool:
    return bool(URL and KEY)


def anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False,
            zeitlimit: float | None = None):
    if not eingerichtet():
        raise PultFehler("nicht_verbunden", "BEWERBUNG_PULT_URL/KEY fehlt")
    return pult_http.anfrage(URL, KEY, methode, pfad, daten, roh,
                             ZEITLIMIT_S if zeitlimit is None else zeitlimit)
