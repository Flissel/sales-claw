"""Newsletter an Kontakte: Vorname und Platzhalter je Empfaenger (15.10.2026).

Plan: docs/superpowers/plans/2026-10-15-newsletter-versand-an-kontakte.md. Marketing liefert die
Versandfassung mit `{vorname}` und `{abmeldelink}`; eingesetzt wird hier, beim Anlegen des Entwurfs -
der Mensch, der freigibt, sieht also genau, was hinausgeht. Marketing sieht nie einen Namen.

Abmelden laeuft per Antwort (Entscheidung E2): `{abmeldelink}` wird ein mailto-Link an den Absender mit
Betreff "Abmelden"; die Postfach-Erkennung setzt den Kontakt dann auf die Sperrliste.
Reine Funktionen, ohne Datenbank.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import quote

ABMELDE_BETREFF = "Abmelden"
_TITEL = {"dr", "dr.", "prof", "prof.", "herr", "frau", "hr", "hr.", "fr", "fr.", "dipl.-ing.", "ing.", "mag."}
_FIRMA = re.compile(r"\b(gmbh|ag|kg|ug|ohg|gbr|e\.\s?v\.|e\.k\.|ltd|inc|co\.?)\b", re.IGNORECASE)
_WORT = re.compile(r"^[A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'-]*$")


def vorname_vorschlag(name: str, firma: str = "") -> str:
    """Erstes Wort des Namens ohne Titel/Anrede - aber nur, wenn danach noch ein Nachname folgt und es
    nicht nach Firma oder Adresse aussieht. Im Zweifel leer: lieber "Hallo," als "Hallo Weber,"."""
    roh = " ".join((name or "").split())
    if not roh or "@" in roh or _FIRMA.search(roh) or (firma and roh.lower() == firma.strip().lower()):
        return ""
    worte = [w for w in roh.split(" ")]
    while worte and worte[0].lower() in _TITEL:
        worte.pop(0)
    if len(worte) < 2 or not _WORT.match(worte[0]):
        return ""
    return worte[0][:1].upper() + worte[0][1:]


def vorname(lead: dict) -> str:
    """Gepflegtes Feld `leads.vorname` hat Vorrang, sonst der Vorschlag aus dem Namen."""
    eigen = " ".join(str(lead.get("vorname") or "").split())
    if eigen:
        return eigen
    return vorname_vorschlag(str(lead.get("name") or ""), str(lead.get("company") or ""))


def abmelde_adresse(absender: str) -> str:
    return f"mailto:{absender}?subject={quote(ABMELDE_BETREFF)}"


def einsetzen(html: str, text: str, vorname_: str, absender: str) -> tuple[str, str]:
    """Setzt Vorname und Abmelde-Link ein. Ohne Vorname faellt der Platzhalter samt Leerzeichen davor
    weg ("Hallo {vorname}," -> "Hallo,")."""
    if not (absender or "").strip():
        raise ValueError("Ohne Absenderadresse gibt es keinen Abmelde-Link - kein Newsletter-Entwurf.")
    link = abmelde_adresse(absender.strip())

    def name_rein(s: str, wert: str) -> str:
        return s.replace("{vorname}", wert) if wert else re.sub(r" ?\{vorname\}", "", s)

    html = name_rein(html or "", _html.escape(vorname_, quote=True))
    html = html.replace("{abmeldelink}", f'<a href="{_html.escape(link, quote=True)}">{ABMELDE_BETREFF}</a>')
    text = name_rein(text or "", vorname_).replace("{abmeldelink}", link)
    return html, text
