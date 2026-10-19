"""Aussehen der Laden-Oberflaeche je Firma (Paket C4, 19.10.2026).

Bis S2 trug jede Oberflaeche fest das VibeMind-Aussehen. Jetzt kommt es aus der Marke der Firma dieses Ladens
(LADEN_MARKE, sonst MARKETING_MANDANT): Farben, Schriften, Logo und Name ueber die Marketing-API
(GET /marke/aussehen). Ein Laden ohne Pult-Zugang (Ivan) liest mit dem schmalen MARKETING_AUSSEHEN_KEY, der
NUR das Aussehen oeffnet - der Pult-Schluessel gaebe die Marketingdaten aller Firmen frei. Die
VibeMind-Grundgestaltung bleibt das Stylesheet; dieses Modul liefert nur die Abweichungen als zweites <style>.

KONTRAST (User-Entscheid "automatisch lesbar"): Markenfarben, auf denen weisse Schrift zu schwach waere (z. B.
fin2gether-Orange), werden fuer Knoepfe und Text so weit abgedunkelt bzw. im Dunkelmodus aufgehellt, bis 4,5:1
erreicht ist. Die echte Farbe steckt in den Toenungen (Grund, aktive Zeile, Linien) und im Logo.

NIE BLOCKIEREN: die Marke wird hoechstens alle GUELTIG_S Sekunden in einem Hintergrund-Thread geholt; eine Seite
nimmt immer den letzten bekannten Stand (beim Start: VibeMind). Faellt die API aus, bleibt der alte Stand.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
import json
import urllib.parse
import urllib.request

import marketing_pult
import schriften

GUELTIG_S = 300
FEHLER_PAUSE_S = 60
ZIEL = 4.5
# S2-Grundgestaltung (von Hand abgestimmt): entspricht die Marke ihr, wird nichts ueberschrieben
VIBEMIND = {"akzent": "#5b3fd6", "zweitfarbe": "#f3e6e3", "schrift_anzeige": "oxanium", "schrift_text": "dm-sans"}
_FARBE = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOGO = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)$")

_zustand: dict = {"wert": None, "bis": 0.0, "laeuft": False}
_sperre = threading.Lock()


# --- Farbrechnung -------------------------------------------------------------------------------------

def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def leuchtdichte(h: str) -> float:
    def kanal(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (kanal(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kontrast(a: str, b: str) -> float:
    la, lb = sorted((leuchtdichte(a), leuchtdichte(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mischen(a: str, b: str, anteil_a: float) -> str:
    """anteil_a von a, Rest von b."""
    return _hex(tuple(x * anteil_a + y * (1 - anteil_a) for x, y in zip(_rgb(a), _rgb(b))))


def _bis(farbe: str, gegen: str, richtung: str, ziel: float = ZIEL) -> str:
    """Die Farbe schrittweise Richtung Schwarz/Weiss mischen, bis sie gegen `gegen` das Ziel erreicht."""
    for i in range(21):
        kandidat = mischen(farbe, richtung, 1 - i * 0.05)
        if kontrast(kandidat, gegen) >= ziel:
            return kandidat
    return richtung


def dunkler_bis(farbe: str, gegen: str, ziel: float = ZIEL) -> str:
    return _bis(farbe, gegen, "#000000", ziel)


def heller_bis(farbe: str, gegen: str, ziel: float = ZIEL) -> str:
    return _bis(farbe, gegen, "#ffffff", ziel)


# --- CSS ----------------------------------------------------------------------------------------------

def _schrift_css(sid: str, rolle: str, rueckfall: str) -> tuple[str, str]:
    """(@font-face-Regeln, Variablenwert) fuer eine Schrift aus dem Register; unbekannt -> ("", "")."""
    s = schriften.REGISTER.get(sid) if isinstance(sid, str) else None
    if not s:
        return "", ""
    regeln = "".join(
        f'@font-face {{ font-family: "{s["familie"]}"; font-style: {stil}; font-weight: {gewicht}; '
        f"font-display: swap; src: url(/marketing/schrift/{sid}-{gewicht}-{stil}.woff2) format(\"woff2\"); }}"
        for gewicht, stil in s["dateien"])
    return regeln, f'--schrift_{rolle}: "{s["familie"]}", {rueckfall};'


def stil(m: dict | None) -> str:
    """Abweichende CSS-Variablen fuer die Marke `m` (Antwort von /marke/aussehen); "" = Grundgestaltung."""
    if not isinstance(m, dict):
        return ""
    akzent = m.get("akzent") if isinstance(m.get("akzent"), str) and _FARBE.match(m["akzent"]) else None
    if not akzent:
        return ""
    if all(str(m.get(k) or "").lower() == v for k, v in VIBEMIND.items()):
        return ""
    akzent = akzent.lower()
    zweit = m.get("zweitfarbe") if isinstance(m.get("zweitfarbe"), str) and _FARBE.match(m["zweitfarbe"]) \
        else mischen(akzent, "#ffffff", 0.2)
    zweit = zweit.lower()

    # hell
    aktiv = mischen(akzent, "#ffffff", 0.12)
    akzent_text = dunkler_bis(akzent, aktiv)
    blush = zweit if leuchtdichte(zweit) >= 0.6 else mischen(zweit, "#ffffff", 0.2)
    hell = {
        "grund": mischen(akzent, "#ffffff", 0.035), "kopfzeile": mischen(akzent, "#ffffff", 0.07),
        "aktiv": aktiv, "linie": mischen(akzent, "#ffffff", 0.16),
        # Rahmen (3:1) und gedaempfter Text (4,5:1) ohne den Lila-Stich der Grundgestaltung
        "linie_stark": dunkler_bis(mischen(akzent, "#9a9a9a", 0.15), "#ffffff", 3.0),
        "gedaempft": dunkler_bis(mischen(akzent, "#6a6a6a", 0.1), "#ffffff"),
        "akzent": dunkler_bis(akzent, "#ffffff"), "akzent_auf": "#ffffff", "akzent_text": akzent_text,
        "verweis": akzent_text, "blush": blush, "blush_text": dunkler_bis(zweit, blush),
    }
    # dunkel
    aktiv_d = mischen(akzent, "#121214", 0.22)
    auf_d = mischen(akzent, "#000000", 0.12)
    akzent_text_d = heller_bis(akzent, aktiv_d)
    blush_d = mischen(zweit, "#121214", 0.22)
    dunkel = {
        "grund": mischen(akzent, "#101012", 0.05), "flaeche": mischen(akzent, "#18181c", 0.06),
        "kopfzeile": mischen(akzent, "#1c1c20", 0.09), "aktiv": aktiv_d, "linie": mischen(akzent, "#2e2e34", 0.15),
        "linie_stark": heller_bis(mischen(akzent, "#6e6e6e", 0.15), "#18181c", 3.0),
        "gedaempft": heller_bis(mischen(akzent, "#a8a8a8", 0.1), "#18181c"),
        "akzent": heller_bis(akzent, auf_d), "akzent_auf": auf_d, "akzent_text": akzent_text_d,
        "verweis": akzent_text_d, "blush": blush_d, "blush_text": heller_bis(zweit, blush_d),
    }
    anzeige_css, anzeige_var = _schrift_css(m.get("schrift_anzeige"), "anzeige", '"DM Sans", system-ui, sans-serif')
    text_css, text_var = _schrift_css(m.get("schrift_text"), "text", 'system-ui, -apple-system, "Segoe UI", sans-serif')

    def block(werte: dict) -> str:
        return " ".join(f"--{k}: {v};" for k, v in werte.items())
    return (f"{anzeige_css}{text_css}"
            f":root {{ {block(hell)} {anzeige_var} {text_var} }}"
            f"@media (prefers-color-scheme: dark) {{ :root {{ {block(dunkel)} }} }}")


# --- Marke holen (nie blockierend) --------------------------------------------------------------------

def mandant() -> str:
    return (os.environ.get("LADEN_MARKE", "").strip() or os.environ.get("MARKETING_MANDANT", "").strip())


def _abrufen(m: str):
    pfad = f"/marke/aussehen?mandant={urllib.parse.quote(m)}"
    schluessel = os.environ.get("MARKETING_AUSSEHEN_KEY", "").strip()
    if not schluessel:
        return marketing_pult.anfrage("GET", pfad, zeitlimit=5)
    basis = (os.environ.get("MARKETING_AUSSEHEN_URL", "").strip() or marketing_pult.URL).rstrip("/")
    req = urllib.request.Request(f"{basis}/api/pult{pfad}", method="GET")
    req.add_unredirected_header("X-Aussehen-Key", schluessel)     # folgt keiner Umleitung (wie marketing_pult)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def _holen(m: str) -> None:
    try:
        d = _abrufen(m)
        ok = isinstance(d, dict)
    except Exception:  # noqa: BLE001 - die Oberflaeche bleibt beim letzten Stand
        d, ok = None, False
    with _sperre:
        if ok:
            _zustand["wert"] = d
        _zustand["bis"] = time.monotonic() + (GUELTIG_S if ok else FEHLER_PAUSE_S)
        _zustand["laeuft"] = False


def aussehen() -> dict | None:
    """Letzter bekannter Stand; ist er abgelaufen, wird im Hintergrund neu geholt."""
    m = mandant()
    if not m:
        return None
    with _sperre:
        wert = _zustand["wert"]
        if time.monotonic() >= _zustand["bis"] and not _zustand["laeuft"]:
            _zustand["laeuft"] = True
            threading.Thread(target=_holen, args=(m,), daemon=True).start()
    return wert


def stil_aktuell() -> str:
    return stil(aussehen())


def name() -> str:
    a = aussehen()
    n = a.get("name") if isinstance(a, dict) else None
    return n.strip() if isinstance(n, str) and n.strip() else "VibeMind"


def logo() -> tuple[bytes, str] | None:
    """(Bytes, Medientyp) des Logos fuer die dunkle Navigation: dunkle Fassung, sonst das Logo; None = VibeMind."""
    a = aussehen()
    if not isinstance(a, dict):
        return None
    for k in ("logo_dunkel", "logo"):
        t = re.match(_LOGO, a.get(k) or "") if isinstance(a.get(k), str) else None
        if t:
            try:
                return base64.b64decode(t.group(2), validate=True), f"image/{t.group(1)}"
            except ValueError:
                return None
    return None
