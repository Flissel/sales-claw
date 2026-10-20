"""Gemeinsamer HTTP-Kern der Pult-Clients (marketing_pult, bewerbung_pult).

Beide Gegenstellen sprechen denselben Vertrag: Wurzel `/api/pult`, Kopf `X-Pult-Key`,
Fehlerantworten als JSON `{"detail": "<text>"}`. Hier liegt nur der Transport samt
Fehlerabbildung auf `PultFehler`. Adresse und Schluessel gibt der Aufrufer mit; der
Schluessel steht in keiner Meldung und in keinem Log."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

PRAEFIX = "/api/pult"


class PultFehler(Exception):
    def __init__(self, art: str, grund: str = "", koerper: dict | None = None):
        super().__init__(f"{art}: {grund}")
        self.art, self.grund = art, grund
        # Der Fehlerkoerper der API (nur bei HTTP-Fehlern): /medien/platzhalter nennt dort
        # bei 503 die schon umgestellten Entwuerfe.
        self.koerper = koerper if isinstance(koerper, dict) else None


def anfrage(basis_url: str, schluessel: str, methode: str, pfad: str, daten: dict | None = None,
            roh: bool = False, zeitlimit: float = 8):
    """Eine Anfrage an `{basis_url}/api/pult{pfad}`. -> geparstes JSON, mit `roh` (Dateien wie
    PDF) `(bytes, Inhaltstyp)`. Wirft nur PultFehler:
      nicht_verbunden  - 401 oder 503 "misconfigured..." (Schluessel fehlt oder passt nicht)
      nicht_erreichbar - Netz, Zeitlimit oder 503 sonst (der Ausgang einer Aenderung ist unklar)
      abgelehnt        - 404/409/422, `grund` ist der `detail`-Text der API
      unbekannt        - alles andere, auch 200 ohne JSON"""
    koerper = json.dumps(daten).encode("utf-8") if daten is not None else None
    req = urllib.request.Request(
        f"{basis_url}{PRAEFIX}{pfad}", data=koerper, method=methode,
        headers={"Content-Type": "application/json"})
    # Der Schluessel folgt keiner Umleitung: urllib gibt normale Koepfe bei
    # einem 30x an das neue Ziel weiter, "unredirected" Koepfe nicht.
    req.add_unredirected_header("X-Pult-Key", schluessel)
    try:
        with urllib.request.urlopen(req, timeout=zeitlimit) as r:
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
        # ("misconfigured") = nicht verbunden; sonst ist die Datenbank der Gegenstelle weg.
        if e.code == 401 or (e.code == 503 and grund.startswith("misconfigured")):
            raise PultFehler("nicht_verbunden", str(e.code))
        if e.code == 503:
            raise PultFehler("nicht_erreichbar", str(e.code), koerper_fehler)
        if e.code in (404, 409, 422):
            raise PultFehler("abgelehnt", grund or str(e.code), koerper_fehler)
        raise PultFehler("unbekannt", str(e.code), koerper_fehler)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PultFehler("nicht_erreichbar", type(e).__name__)
