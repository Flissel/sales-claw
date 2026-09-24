"""Setzprogramm fuer Formular-Vorlagen — Musterblatt UND ausgefuellte Karte.

EIN Programm, zwei Anlaesse (docs/superpowers/specs/2026-09-24-terminkarten-
design.md, §2): das Musterblatt, das ein Mitglied freigibt, und jede Karte,
die danach gedruckt wird, entstehen durch denselben Aufruf. Liefen sie
auseinander, gaelte die Freigabe fuer ein anderes Blatt als das gedruckte.

Die Gestalt kommt von Marketing (marketing.layout_vorlagen, art='formular')
und ist dort geprueft (marketing._formular_gestalt_fehler). Hier wird nur
gesetzt. Masse in Millimetern, Ursprung links oben wie auf dem Foto;
reportlab zaehlt von links unten, deshalb `_y`.
"""
import io
import unicodedata

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

SCHRIFT = "Helvetica"
FETT = "Helvetica-Bold"
BESCHRIFTUNG_PT = 7
WERT_PT_MAX = 11
WERT_PT_MIN = 6

MUSTER = {"text": "Muster Mustermann", "datum": "24.09.2026", "uhrzeit": "14:30",
          "telefon": "+49 170 1234567", "mehrzeilig": "Muster: Vorinfos zum Termin"}

# Transliteration table for characters without NFKD decomposition
TRANSLITERATION = {
    'Ł': 'L', 'ł': 'l',
    'Ø': 'O', 'ø': 'o',
    'Đ': 'D', 'đ': 'd',
    'Ħ': 'H', 'ħ': 'h',
    'ı': 'i',
    'Œ': 'OE', 'œ': 'oe',
    'Ŧ': 'T', 'ŧ': 't',
}


class PasstNicht(ValueError):
    """Raised when a field value is too long to fit in its designated space."""
    pass


def beispielwerte(gestalt: dict) -> dict:
    return {f["name"]: MUSTER.get(f.get("art"), "Muster") for f in gestalt["felder"]}


def _druckbar(text: str) -> str:
    """Helvetica kennt Latin-1. Alles andere: transliterieren, dann zerlegen,
    sonst weglassen — ein Absturz beim Drucken waere schlimmer als ein fehlender Akzent."""
    aus = []
    for z in str(text or ""):
        try:
            z.encode("latin-1")
            aus.append(z)
        except UnicodeEncodeError:
            # Try explicit transliteration first
            if z in TRANSLITERATION:
                aus.append(TRANSLITERATION[z])
            else:
                # Fall back to NFKD normalization
                basis = unicodedata.normalize("NFKD", z).encode("latin-1", "ignore").decode("latin-1")
                aus.append(basis)
    return "".join(aus)


def _zeilen(text: str, breite: float, pt: float) -> list:
    zeilen, aktuell = [], ""
    for wort in text.split():
        probe = (aktuell + " " + wort).strip()
        if stringWidth(probe, SCHRIFT, pt) <= breite or not aktuell:
            aktuell = probe
        else:
            zeilen.append(aktuell)
            aktuell = wort
    if aktuell:
        zeilen.append(aktuell)
    return zeilen


def _passend(text: str, breite: float, hoehe: float, beschriftung: str = "") -> tuple:
    """Groesste Schrift, bei der der umbrochene Text in den Platz passt.
    Wenn er nicht einmal in der kleinsten passt, wird PasstNicht gehoben."""
    for pt in range(WERT_PT_MAX, WERT_PT_MIN - 1, -1):
        zeilen = _zeilen(text, breite, pt)
        if len(zeilen) * pt * 1.2 <= hoehe:
            return pt, zeilen
    # Text passt nicht mal bei WERT_PT_MIN — Exception
    raise PasstNicht(f"Feld '{beschriftung}' ist zu lang fuer die Karte - bitte kuerzen.")


def setzen(gestalt: dict, werte: dict) -> bytes:
    seite_b = gestalt["seite"]["breite_mm"] * mm
    seite_h = gestalt["seite"]["hoehe_mm"] * mm
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=(seite_b, seite_h))

    def _y(y_mm: float) -> float:
        return seite_h - y_mm * mm

    for t in gestalt.get("texte") or []:
        p = t["platz"]
        pt = float(t.get("groesse") or 10)
        c.setFont(FETT if t.get("fett", True) else SCHRIFT, pt)
        c.drawString(p["x"] * mm, _y(p["y"]) - pt, _druckbar(t["text"]))

    for f in gestalt["felder"]:
        p = f["platz"]
        x, oben = p["x"] * mm, _y(p["y"])
        breite, hoehe = p["breite"] * mm, p["hoehe"] * mm
        c.setFont(SCHRIFT, BESCHRIFTUNG_PT)
        c.drawString(x, oben - BESCHRIFTUNG_PT, _druckbar(f["beschriftung"]))
        unten = oben - hoehe
        c.setLineWidth(0.4)
        c.line(x, unten, x + breite, unten)
        wert = _druckbar(werte.get(f["name"], "")).strip()
        if not wert:
            continue
        platz_h = hoehe - BESCHRIFTUNG_PT * 1.4
        pt, zeilen = _passend(wert, breite, platz_h, f["beschriftung"])
        c.setFont(SCHRIFT, pt)
        y = oben - BESCHRIFTUNG_PT * 1.4 - pt
        for zeile in zeilen:
            c.drawString(x, y, zeile)
            y -= pt * 1.2
    c.showPage()
    c.save()
    return puffer.getvalue()
