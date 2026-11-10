"""Ziele und Fassungen fuer ein Reel auf den Beitragskanaelen.

Herausgeloest aus ui_reels.kanaele_teilen, damit die Oberflaeche und der Auftragsbuch-Weg
(Salesman-Werkzeug, Reel-Kette) dieselben Regeln benutzen. dev.to ist nie Ziel.
"""
from __future__ import annotations

import os
import urllib.parse

import kanaele
import marketing_pult
from kanaele import KanalInfo

LISTE_MAX = 200    # Hoechstwert der Marketing-API: so findet sich auch ein aelteres Reel

# LinkedIn ist kein Kanal von sales-kanaele (eigener Dienst, post_entwurf_erstellen), hat aber
# dieselben Grenzen fuer die Fassung: Beitrag bis 3000 Zeichen, ein Video, kein Titel.
LINKEDIN = KanalInfo(
    name="linkedin", anzeige="LinkedIn", env_namen=(), geheim_namen=(),
    max_zeichen=3000, max_zeichen_mit_medien=3000,
    bilder_max=1, video_max=1, medien_max=1,
    bild_max_bytes=0, video_max_bytes=0,
    kadenz_pro_tag=1, titel_pflicht=False, titel_max=0, hashtags=True)


def kuerzen(text: str, grenze: int) -> str:
    """Am letzten Leerzeichen vor `grenze - 1` kuerzen, "…" anhaengen (hoechstens `grenze` Zeichen)."""
    if len(text) <= grenze:
        return text
    if grenze < 1:
        return ""
    stueck = text[:grenze - 1]
    leer = stueck.rfind(" ")
    if leer > 0:
        stueck = stueck[:leer]
    return stueck.rstrip() + "…"


def fertige_reels(firma: str) -> set[str]:
    """Dateinamen der fertigen Reels einer Firma (aktuelle und archivierte Auftraege) laut Marketing-API.
    Die Eigentumspruefung vor jedem Teilen (Reels-Seite und auftrag-bote): eine Datei, die hier fehlt, ist kein
    fertiges Reel dieser Firma. Wirft marketing_pult.PultFehler (dann wird nichts geteilt)."""
    alle: list[dict] = []
    for archiv in (False, True):
        abfrage = urllib.parse.urlencode({"mandant": firma, "archiv": "true" if archiv else "false",
                                          "limit": str(LISTE_MAX)})
        d = marketing_pult.anfrage("GET", f"/video?{abfrage}")
        alle += [a for a in (d.get("auftraege") if isinstance(d, dict) else None) or [] if isinstance(a, dict)]
    return {str(a.get("datei")) for a in alle if a.get("status") == "fertig"}


def ziele(q, nur: list[str] | None = None, art: str = "video",
          mit_linkedin: bool = True) -> list[KanalInfo]:
    """Verbundene Kanaele, die diese Medienart nehmen (ohne dev.to); dazu LinkedIn, wenn
    LINKEDIN_POST_LEAD_ID gesetzt ist. `nur` filtert nach Namen."""
    status = kanaele.status_lesen(q)
    gefunden = [info for k, info in kanaele.KANAELE.items()
                if k != "devto" and (status.get(k) or {}).get("verbunden")
                and (info.video_max if art == "video" else info.bilder_max) >= 1]
    if mit_linkedin and os.environ.get("LINKEDIN_POST_LEAD_ID", "").strip():
        gefunden.append(LINKEDIN)
    if nur is not None:
        gefunden = [i for i in gefunden if i.name in nur]
    return gefunden


def fassung(info: KanalInfo, thema: str, texte: dict, link: str = "") -> tuple[str, str]:
    """(titel, text) fuer einen Kanal. `texte` kennt `text_lang` und `text_kurz`: lang, wenn er
    in die Grenze des Kanals passt, sonst kurz, sonst der vorhandene Text gekuerzt."""
    platz = info.max_zeichen_mit_medien - (len(link) + 2 if link else 0)
    lang = str(texte.get("text_lang") or "").strip()
    kurz = str(texte.get("text_kurz") or "").strip()
    if lang and len(lang) <= platz:
        text = lang
    elif kurz and len(kurz) <= platz:
        text = kurz
    else:
        text = kuerzen(kurz or lang, platz)
    if link:
        text += "\n\n" + link
    titel = kuerzen(thema, info.titel_max) if info.titel_pflicht else ""
    return titel, text
