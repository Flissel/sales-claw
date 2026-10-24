"""Reels im Marketing-Pult (17.10.2026, Video-Claw, Marketing-Migration 072; Reels Stufe 1 21.10.2026,
Migration 085, Plan docs/superpowers/plans/2026-10-21-reels-stufe1.md E7-E10).

- /marketing/reels: Galerie mit Reitern (Fertig, In Arbeit, Fehlgeschlagen, Archiv) und Karten im
  Format 9:16; jede Karte verlinkt auf die Detailseite.
- /marketing/reels/{aid}: Detailseite, nur fuer Auftraege der gewaehlten Firma (sonst 404), mit
  Herunterladen, LinkedIn-Entwurf, Nochmal mit Aenderungswunsch, Neu versuchen, Archiv und Abbrechen.
- /marketing/reels/neu: gefuehrte Bestellung in drei Schritten ueber GET-Parameter (Art, Material,
  Text); "Bestellen" geht per POST an die API.

Betreiber-Entscheid E4 (17.10.): bestellen koennen der Betreiber (hier) und der Marketing-Agent. Gebaut
wird am PC vom Video-Claw mit Laura. Hinaus geht es nur als Entwurf ueber die Freigaben, und nur fuer
die Firma dieses Ladens (MARKETING_MANDANT). Die Stimme kommt aus der Marke (E2), die Farben auch.
Wie der Rest von sales-ui ohne JavaScript; geprueft wird in der Marketing-API (eine Wahrheit).
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import kanaele
import marketing_mandant
import marketing_pult
import medien
import ui_muster

# "ki" gibt es nur auf dieser Seite: an die API geht art "bilder" mit briefing.ki (Stufe 3, E2)
ARTEN = {"bilder": "Aus Bildern", "material": "Aus Videomaterial", "kurzfassung": "Kurzfassung eines Videos",
         "ki": "Aus KI-Bildern"}
ARTEN_TEXT = {
    "bilder": "Bilder aus deinen Medien werden zum Reel mit Sprechertext, Untertiteln und deinen Markenfarben.",
    "material": "Ausschnitte aus Videos in Laura werden neu geschnitten und vertont.",
    "kurzfassung": "Ein langes Video aus Laura wird auf 15 bis 60 Sekunden gekürzt.",
    "ki": "Ich entwerfe 3 bis 5 Bilder im Bildstil deiner Marke. Du siehst sie dir an, bevor das Reel entsteht.",
}
STATUS = {"offen": "wartet", "in_arbeit": "wird gebaut", "fertig": "fertig", "fehler": "Fehler",
          "abgebrochen": "abgebrochen", "ideen": "Bildideen werden geschrieben",
          "bilder_laufen": "Bilder entstehen", "bilder_pruefen": "Bilder prüfen"}
# bilder_pruefen wartet auf den Betreiber: eigener, auffaelliger Chip (E7)
STATUS_CHIP = {"offen": "offen", "in_arbeit": "offen", "fertig": "gut", "fehler": "fehler",
               "abgebrochen": "archiv", "ideen": "offen", "bilder_laufen": "offen", "bilder_pruefen": "bereich"}
KI_VORSTUFEN = ("ideen", "bilder_laufen", "bilder_pruefen")
# (Schluessel, Name, Status) je Reiter; das Archiv fragt die API mit archiv=true
REITER = (("fertig", "Fertig", ("fertig",)), ("arbeit", "In Arbeit", ("offen", "in_arbeit") + KI_VORSTUFEN),
          ("fehler", "Fehlgeschlagen", ("fehler", "abgebrochen")), ("archiv", "Archiv", None))
# frischt sich auf; nie bei bilder_pruefen - dort tippt der Betreiber vielleicht gerade eine Idee (E7)
LAUFEND = ("offen", "in_arbeit", "ideen", "bilder_laufen")
ABBRECHBAR = LAUFEND + ("bilder_pruefen",)       # video_abbrechen (090) nimmt alle drei KI-Vorstufen
ERLEDIGT = ("fertig", "fehler", "abgebrochen")
KI_ANZAHLEN = (3, 4, 5)
KI_VORGABE = 4
IDEE_MAX = 600                     # wie reel_bilder.idee (090) und die Pult-Route ki/neu
_KI_DATEI = re.compile(r"^ki-[0-9a-f]{8}-[1-5]-[0-9]{1,3}\.jpg$")    # wie der Check in 090
_DATEI = re.compile(r"^vid-[0-9a-f]{8}-[a-z0-9-]{1,40}\.mp4$")
_POSTER = re.compile(r"^vid-[0-9a-f]{8}-[a-z0-9-]{1,40}\.jpg$")
_AID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_BILD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(?:png|jpe?g|webp)$", re.IGNORECASE)
_LAURA_ID = re.compile(r"^[0-9a-f][0-9a-f-]{7,63}$")       # wie _LAURA_ID der Marketing-API
POST_TEXT_MAX = 3000
LINK_MAX = 300                     # "Auf Kanaelen teilen": optionaler Link, nur https:// (Task 8)
_LINK = re.compile(r"^https://[^\s<>\"']+$")
WUNSCH_MAX = 500
AUSWAHL_MAX = 8
DETAIL_LIMIT = 200                 # Hoechstwert der API: so findet die Detailseite auch aeltere Reels
MATERIAL_ZEITLIMIT_S = 12          # die API wartet bis zu ~6 s auf Laura
REFRESH_S = 30
SEITE = "/marketing/reels"
NEU_SEITE = "/marketing/reels/neu"
MARKE_PROFIL = "/marketing/layouts?reiter=profil"
FORMATE = {"reel": "Hochformat 9:16 – Instagram, TikTok, Shorts", "quadrat": "Quadrat 1:1 – LinkedIn",
           "quer": "Querformat 16:9 – Website, Präsentation"}
_FORMAT_KLASSE = {"quadrat": "f-quadrat", "quer": "f-quer"}      # reel = keine Klasse (Hochformat)


def format_von(briefing) -> str:
    """Das Format eines Auftrags: nur ein bekanntes Wort zaehlt, alles andere ist Hochformat (E7)."""
    f = briefing.get("format") if isinstance(briefing, dict) else None
    return f if isinstance(f, str) and f in FORMATE else "reel"


def klassen(*teile) -> str:
    """CSS-Klassen zusammenfuegen, leere Teile faellt weg."""
    return " ".join(t for t in teile if t)


def format_klasse(briefing) -> str:
    return _FORMAT_KLASSE.get(format_von(briefing), "")


STANDARD_STIMME = "standard"       # steht nie in GET /stimmen und gilt immer (claw/stimmen.py)


def _texte(werte) -> list[str]:
    return [str(w).strip() for w in werte if str(w or "").strip()]


def ki_anzahl(roh) -> int | None:
    """Die Zahl der KI-Bilder aus dem Formular (3, 4 oder 5) oder None."""
    try:
        n = int(str(roh or "").strip())
    except ValueError:
        return None
    return n if n in KI_ANZAHLEN else None


def ist_ki(a: dict) -> bool:
    b = a.get("briefing")
    return isinstance(b, dict) and isinstance(b.get("ki"), dict)


def ki_bilder(a: dict) -> list[dict]:
    """Die aktiven KI-Bilder eines Auftrags (die API laesst verworfene weg), nach nr."""
    roh = a.get("ki_bilder")
    bilder = [b for b in roh if isinstance(b, dict)] if isinstance(roh, list) else []
    return sorted(bilder, key=lambda b: b.get("nr") if isinstance(b.get("nr"), int) else 99)


def fertige_ki_bilder(a: dict) -> list[dict]:
    """Die fertigen KI-Bilder mit gueltiger Datei - eine Regel fuer den Knopf "Reel bauen" und die Route."""
    return [b for b in ki_bilder(a) if b.get("status") == "fertig" and _KI_DATEI.fullmatch(str(b.get("datei") or ""))]


def status_text(a: dict) -> str:
    """Status als Satz; waehrend der Erzeugung mit Fortschritt "Bilder entstehen (2 von 4)" (E7)."""
    status = str(a.get("status") or "")
    text = STATUS.get(status, status)
    if status == "bilder_laufen":
        bilder = ki_bilder(a)
        ki = a["briefing"]["ki"] if ist_ki(a) else {}
        gesamt = len(bilder) or (ki.get("anzahl") if isinstance(ki.get("anzahl"), int) else 0)
        fertig = sum(1 for b in bilder if b.get("status") in ("fertig", "fehler"))
        if gesamt:
            text += f" ({fertig} von {gesamt})"
    return text


def briefing_aus_formular(form) -> tuple[str, str, dict]:
    """(art, titel, briefing) aus dem Formular. Farben und Stimme gibt es nicht mehr: beides kommt aus
    der Marke der Firma (E2, E9). Geprueft wird in der Marketing-API (eine Wahrheit). Bei "ki" traegt
    das Briefing nur die Zahl (briefing.ki), keine Bilderliste und kein Logo."""
    art = str(form.get("art") or "")
    titel = str(form.get("titel") or "").strip()
    try:
        dauer = int(str(form.get("dauer_s") or "30"))
    except ValueError:
        dauer = 30
    b: dict = {"thema": str(form.get("thema") or "").strip(),
               "sprechertext": str(form.get("sprechertext") or "").strip(),
               "hook": str(form.get("hook") or "").strip(), "dauer_s": dauer}
    fmt = str(form.get("format") or "reel")
    if fmt != "reel":
        b["format"] = fmt                    # die Marketing-API prueft (eine Wahrheit), die Vorgabe schickt nichts
    if art == "bilder":
        b["bilder"] = _texte(form.getlist("bild"))
        if str(form.get("logo") or "").strip():
            b["logo"] = str(form.get("logo")).strip()
    elif art == "material":
        b["videos"] = _texte(form.getlist("video"))
    elif art == "kurzfassung":
        b["video"] = (_texte(form.getlist("video")) or [""])[0]
    elif art == "ki":
        b["ki"] = {"anzahl": ki_anzahl(form.get("anzahl"))}
    return art, titel, b


def auswahl_fehler(art: str, bilder: list[str], videos: list[str], anzahl: int | None = None) -> str:
    """Die Auswahl aus Schritt 2 als Satz, wenn sie nicht passt, sonst "". Die API prueft noch einmal
    (fremde Bilder, unbekannte Videos); hier geht es um eine verstaendliche Meldung vor dem Bestellen."""
    if art == "ki":
        return "" if anzahl in KI_ANZAHLEN else "Wähle 3, 4 oder 5 Bilder."
    if art == "bilder":
        if any(not _BILD.fullmatch(n) for n in bilder):
            return "Ungültige Auswahl. Bitte wähle die Bilder neu."
        if not bilder:
            return "Wähle mindestens ein Bild."
        if len(bilder) > AUSWAHL_MAX:
            return f"Bitte höchstens {AUSWAHL_MAX} Bilder wählen."
    else:
        if any(not _LAURA_ID.fullmatch(v) for v in videos):
            return "Ungültige Auswahl. Bitte wähle die Videos neu."
        if art == "material" and len(videos) > AUSWAHL_MAX:
            return f"Bitte höchstens {AUSWAHL_MAX} Videos wählen."
        if art == "kurzfassung" and len(videos) != 1:
            return "Für die Kurzfassung brauchst du genau ein Video aus Laura."
    return ""


def dauer_text(sekunden) -> str:
    if isinstance(sekunden, bool) or not isinstance(sekunden, (int, float)) or sekunden <= 0:
        return ""
    if float(sekunden).is_integer():
        return f"{int(sekunden)} s"
    return f"{sekunden:.1f} s".replace(".", ",")


def laenge_text(sekunden) -> str:
    """Laenge eines Laura-Videos als m:ss."""
    if isinstance(sekunden, bool) or not isinstance(sekunden, (int, float)) or sekunden <= 0:
        return "?"
    s = int(round(sekunden))
    return f"{s // 60}:{s % 60:02d}"


def datum_text(roh) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(roh or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else ""


def kuerzen(text: str, grenze: int) -> str:
    """Zu langer Text wird am letzten Leerzeichen vor `grenze - 1` gekuerzt und bekommt "…" -
    das Ergebnis hat hoechstens `grenze` Zeichen. Ohne Leerzeichen wird hart geschnitten."""
    if len(text) <= grenze:
        return text
    if grenze < 1:
        return ""
    stueck = text[:grenze - 1]
    leer = stueck.rfind(" ")
    if leer > 0:
        stueck = stueck[:leer]
    return stueck.rstrip() + "…"


def eigene_firma() -> str:
    return os.environ.get("MARKETING_MANDANT", "").strip()


def _auftraege(d) -> list[dict]:
    return [a for a in (d.get("auftraege") if isinstance(d, dict) else None) or [] if isinstance(a, dict)]


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def abgewiesen():
        return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")

    def csrf() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def datei_url(name: str, laden: bool = False) -> str:
        return f"/medien/datei/{e(urllib.parse.quote(name, safe=''))}" + ("?laden=1" if laden else "")

    def detail_url(aid: str) -> str:
        return f"{SEITE}/{urllib.parse.quote(aid, safe='')}"

    async def liste(m: str, archiv: bool, limit: int | None = None) -> list[dict]:
        q = {"mandant": m, "archiv": "true" if archiv else "false"}
        if limit:
            q["limit"] = str(limit)
        d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/video?{urllib.parse.urlencode(q)}")
        return _auftraege(d)

    def kopf(m: str, firmen: list, ziel: str = SEITE) -> str:
        return marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, firmen, ziel)

    def bestell_kopf(m: str, firmen: list) -> str:
        """Review Task 5: die Firma steht auf jedem Schritt; ein Wechsel beginnt die Bestellung neu."""
        return (kopf(m, firmen, NEU_SEITE)
                + f'<p class="meta">Bestellung für <b>{e(marketing_mandant.name_von(m, firmen))}</b></p>')

    def chip(a: dict) -> str:
        status = str(a.get("status") or "")
        return f'<span class="chip {STATUS_CHIP.get(status, "offen")}">{e(status_text(a))}</span>'

    # --- Galerie ---------------------------------------------------------------------------

    def karte(a: dict) -> str:
        aid = str(a.get("id") or "")
        titel = str(a.get("titel") or "")
        poster = str(a.get("poster") or "")
        if _POSTER.fullmatch(poster):
            bild = f'<video preload="none" muted poster="{datei_url(poster)}"></video>'
        else:
            bild = f'<div class="reel-flaeche"><span>{e(titel)}</span></div>'
        angaben = " · ".join(t for t in (dauer_text(a.get("dauer_s")), datum_text(a.get("erstellt_am"))) if t)
        klasse = klassen("reel-karte", format_klasse(a.get("briefing")))
        return (f'<a class="{klasse}" href="{e(detail_url(aid))}">{bild}'
                f'<span class="reel-titel">{e(titel)}</span>'
                f'<span class="reel-fuss">{chip(a)}'
                f'<span class="meta">{e(angaben)}</span></span></a>')

    @ui._gesichert_seite
    async def galerie(request):
        try:
            m, firmen = await marketing_mandant.firma(request)
            aktuell = await liste(m, False, DETAIL_LIMIT)
            archiv = await liste(m, True, DETAIL_LIMIT)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        je_reiter = {k: [a for a in aktuell if a.get("status") in st] for k, _, st in REITER if st}
        je_reiter["archiv"] = archiv
        vorgabe = "fertig" if je_reiter["fertig"] else "arbeit"
        reiter = request.query_params.get("reiter", vorgabe)
        reiter = reiter if reiter in je_reiter else vorgabe
        nav = ui_muster.reiter([(k, n, len(je_reiter[k])) for k, n, _ in REITER], reiter,
                               lambda k: f"{SEITE}?reiter={k}")
        karten = "".join(karte(a) for a in je_reiter[reiter])
        inhalt = (f'<div class="reel-raster">{karten}</div>' if karten
                  else '<p class="meta">Noch keine Reels in diesem Bereich.</p>')
        rumpf = (kopf(m, firmen) + f'<div class="reel-kopf"><a class="knopf" href="{NEU_SEITE}">Neues Reel</a>'
                 '<p class="meta">Gebaut wird am PC mit Laura, das dauert einige Minuten. Versendet wird nichts '
                 'ohne deine Freigabe.</p></div>' + nav + inhalt)
        return ui._seite("Reels", rumpf, refresh=REFRESH_S if any(a.get("status") in LAUFEND for a in aktuell)
                         else None)

    # --- Detailseite -----------------------------------------------------------------------

    async def auftrag_der_firma(m: str, aid: str) -> dict | None:
        """Review Focus 1: nur ein Auftrag der gewaehlten Firma; erst die aktuellen, dann das Archiv."""
        for archiv in (False, True):
            for a in await liste(m, archiv, DETAIL_LIMIT):
                if str(a.get("id") or "") == aid:
                    return a
        return None

    def angabe(name: str, wert) -> str:
        text = str(wert or "").strip()
        return f"<dt>{e(name)}</dt><dd>{e(text)}</dd>" if text else ""

    def aktionen_html(a: dict, m: str) -> str:
        aid = str(a.get("id") or "")
        basis = e(detail_url(aid))
        status = str(a.get("status") or "")
        datei = str(a.get("datei") or "")
        briefing = a.get("briefing") if isinstance(a.get("briefing"), dict) else {}
        teile = []
        if status == "fertig" and _DATEI.fullmatch(datei):
            teile.append(f'<div class="aktionen"><a class="knopf" href="{datei_url(datei, laden=True)}">'
                         'Herunterladen</a></div>')
            if m == eigene_firma():
                vorschlag = str(briefing.get("sprechertext") or briefing.get("thema") or "")
                teile.append(
                    f'<form method="post" action="{SEITE}/post" class="reel-form">{csrf()}'
                    f'<input type="hidden" name="datei" value="{e(datei)}">'
                    f'<input type="hidden" name="thema" value="{e(str(a.get("titel") or ""))}">'
                    f'<label>Text zum Post <textarea name="text" rows="3" maxlength="{POST_TEXT_MAX}">'
                    f'{e(vorschlag)}</textarea></label>'
                    '<button type="submit">Als LinkedIn-Post vorbereiten</button>'
                    '<p class="meta">Legt einen Entwurf in die Freigaben – gepostet wird erst nach deiner '
                    'Freigabe.</p></form>')
                titel = str(a.get("titel") or "")
                teile.append(
                    f'<form method="post" action="{SEITE}/kanaele" class="reel-form">{csrf()}'
                    f'<input type="hidden" name="datei" value="{e(datei)}">'
                    f'<input type="hidden" name="thema" value="{e(titel)}">'
                    f'<label>Text für die Kanäle <textarea name="text" rows="3" maxlength="{POST_TEXT_MAX}">'
                    f'{e(titel)}</textarea></label>'
                    f'<label>Link (optional, nur https://) <input type="url" name="link" maxlength="{LINK_MAX}" '
                    'placeholder="https://"></label>'
                    '<button type="submit">Auf Kanälen teilen</button>'
                    '<p class="meta">Legt je verbundenem Kanal, der Videos nimmt, einen Entwurf in die Freigaben. '
                    'Zu lange Texte werden gekürzt. <a href="/einstellungen/kanaele">Kanäle</a></p></form>')
            else:
                teile.append('<p class="meta">Posten kann nur der Laden dieser Firma.</p>')
        if status == "fertig":
            # E2: "Nochmal" nimmt die gewaehlten KI-Bilder mit; neue KI-Bilder gibt es nur mit neuer Bestellung
            ki_satz = (" Die Bilder bleiben dieselben. Für neue KI-Bilder bestelle ein neues Reel."
                       if ist_ki(a) else "")
            teile.append(
                f'<form method="post" action="{basis}/nochmal" class="reel-form">{csrf()}'
                f'<label>Was soll anders werden? <textarea name="wunsch" rows="3" maxlength="{WUNSCH_MAX}" required '
                'placeholder="z. B. kürzer, anderer Einstieg, mehr Bilder vom Team"></textarea></label>'
                '<button class="primaer" type="submit">Nochmal mit Änderung</button>'
                f'<p class="meta">Baut ein neues Reel; dieses bleibt, wie es ist.{ki_satz}</p></form>')
        elif status == "fehler":
            teile.append(f'<form method="post" action="{basis}/nochmal" class="aktion">{csrf()}'
                         '<input type="hidden" name="wunsch" value="">'
                         '<button class="primaer" type="submit">Neu versuchen</button></form>')
        knoepfe = []
        if status in ERLEDIGT:
            an, text = ("0", "Wieder anzeigen") if a.get("archiviert") else ("1", "Archivieren")
            knoepfe.append(f'<form method="post" action="{basis}/archiv" class="aktion">{csrf()}'
                           f'<input type="hidden" name="an" value="{an}"><button type="submit">{text}</button></form>')
        if status in ABBRECHBAR:
            knoepfe.append(f'<form method="post" action="{basis}/abbrechen" class="aktion">{csrf()}'
                           '<button class="gefahr" type="submit">Abbrechen</button></form>')
        if knoepfe:
            teile.append(f'<div class="aktionen">{"".join(knoepfe)}</div>')
        return "".join(teile)

    def detail_html(a: dict, m: str) -> str:
        status = str(a.get("status") or "")
        titel = str(a.get("titel") or "")
        briefing = a.get("briefing") if isinstance(a.get("briefing"), dict) else {}
        protokoll = a.get("protokoll") if isinstance(a.get("protokoll"), list) else []
        datei = str(a.get("datei") or "")
        poster = str(a.get("poster") or "")
        poster_attr = f' poster="{datei_url(poster)}"' if _POSTER.fullmatch(poster) else ""
        fk = format_klasse(briefing)
        if status == "fertig" and _DATEI.fullmatch(datei):
            bild = (f'<video class="{klassen("reel-gross", fk)}" controls preload="metadata"{poster_attr} '
                    f'src="{datei_url(datei)}"></video>')
        else:
            bild = f'<div class="{klassen("reel-flaeche reel-gross", fk)}"><span>{e(titel)}</span></div>'
        satz = str(a.get("befund_text") or "").strip()
        teile = [f'<h2>{e(titel)}</h2><p>{chip(a)}</p>']
        if satz:
            teile.append(f'<p class="{"warnung" if status == "fehler" else "meta"}">{e(satz)}</p>')
        hinweis = str(briefing.get("stimme_hinweis") or "").strip()
        if hinweis:
            teile.append(f'<p class="hinweis">{e(hinweis)}</p>')
        groesse = ""
        if isinstance(a.get("bytes"), (int, float)) and not isinstance(a.get("bytes"), bool) and a["bytes"] > 0:
            groesse = f'{a["bytes"] / 1_000_000:.1f} MB'.replace(".", ",")
        laenge = " · ".join(t for t in (dauer_text(a.get("dauer_s")), groesse) if t)
        bestellt = " · ".join(t for t in (datum_text(a.get("erstellt_am")),
                                          "Agent" if a.get("angelegt_von") == "agent" else "Betreiber") if t)
        art = ARTEN["ki"] if ist_ki(a) else ARTEN.get(str(a.get("art")), str(a.get("art") or ""))
        teile.append('<dl class="reel-angaben">'
                     + angabe("Art", art)
                     + angabe("Thema", briefing.get("thema")) + angabe("Sprechertext", briefing.get("sprechertext"))
                     + angabe("Einstieg", briefing.get("hook")) + angabe("Stimme", briefing.get("stimme"))
                     + angabe("Format", FORMATE[format_von(briefing)]) + angabe("Länge", laenge) + angabe("Bestellt", bestellt) + "</dl>")
        vorgaenger = str(a.get("vorgaenger") or "")
        if _AID.fullmatch(vorgaenger):
            name = str(a.get("vorgaenger_titel") or "") or "voriges Reel"
            teile.append(f'<p>Vorgänger: <a href="{e(detail_url(vorgaenger))}">{e(name)}</a></p>')
        wunsch = str(a.get("aenderungswunsch") or "").strip()
        if wunsch:
            teile.append(f'<p>Änderungswunsch: „{e(wunsch)}“</p>')
        teile.append(aktionen_html(a, m))
        notizen = "".join(f"<li>{e(str(p.get('text') or ''))}</li>" for p in protokoll if isinstance(p, dict))
        befund = str(a.get("befund") or "").strip()
        innen = (f"<ol>{notizen}</ol>" if notizen else '<p class="meta">Noch keine Notizen.</p>')
        if befund:
            innen += f'<p class="meta">Befund: {e(befund)}</p>'
        teile.append(f'<details class="reel-protokoll"><summary>Was der Claw gemacht hat</summary>{innen}</details>')
        # KI-Vorstufen: noch kein Reel - am Handy faellt die leere Flaeche weg, die Bilder rutschen nach oben
        vorstufe = "ki-vorstufe" if ist_ki(a) and status in KI_VORSTUFEN else ""
        return (f'<p><a href="{SEITE}">Alle Reels</a></p>'
                f'<div class="{klassen("reel-detail", fk, vorstufe)}"><div class="reel-bild">{bild}</div>'
                f'<div class="reel-text">{"".join(teile)}</div></div>' + ki_html(a, m))

    # --- KI-Bilder ansehen, neu erzeugen, Reel bauen (Stufe 3, E7) -------------------------

    def ki_zelle(a: dict, b: dict, m: str, pruefen: bool) -> str:
        nr = b.get("nr") if isinstance(b.get("nr"), int) else 0
        status = str(b.get("status") or "")
        datei = str(b.get("datei") or "")
        if status == "fertig" and _KI_DATEI.fullmatch(datei):
            bild = f'<img src="{datei_url(datei)}" alt="Bild {nr}" loading="lazy">'
        elif status == "fehler":
            befund = str(b.get("befund") or "").strip()
            satz = f"Fehlgeschlagen: {befund}" if befund else "Fehlgeschlagen"
            bild = f'<div class="ki-leer fehlt"><span>{e(satz)}</span></div>'
        else:
            bild = f'<div class="ki-leer"><span>{"entsteht gerade" if status == "in_arbeit" else "wartet"}</span></div>'
        idee = str(b.get("idee") or "").strip()
        teile = [f'<span class="meta">Bild {nr}</span>']
        if idee:
            teile.append(f"<details><summary>Idee</summary><p>{e(idee)}</p></details>")
        bid = str(b.get("id") or "")
        if pruefen and status in ("fertig", "fehler") and _AID.fullmatch(bid):
            teile.append(
                f'<form method="post" action="{e(detail_url(str(a.get("id") or "")))}/ki/neu" class="ki-neu">'
                f'{csrf()}<input type="hidden" name="mandant" value="{e(m)}">'
                f'<input type="hidden" name="bild" value="{e(bid)}">'
                f'<label>andere Idee (freiwillig) <input type="text" name="idee" maxlength="{IDEE_MAX}" '
                'placeholder="leer = dieselbe Idee"></label>'
                '<button type="submit">Neu erzeugen</button></form>')
        return f'<figure class="ki-bild">{bild}<figcaption>{"".join(teile)}</figcaption></figure>'

    def ki_html(a: dict, m: str) -> str:
        status = str(a.get("status") or "")
        bilder = ki_bilder(a)
        if not ist_ki(a) or status not in ("bilder_laufen", "bilder_pruefen") or not bilder:
            return ""
        pruefen = status == "bilder_pruefen"
        raster = "".join(ki_zelle(a, b, m, pruefen) for b in bilder)
        teile = ['<section class="ki-bilder"><h3>Deine KI-Bilder</h3>']
        if pruefen:
            teile.append('<p class="meta">Sieh dir die Bilder an. Gefällt dir eins nicht, lass es neu erzeugen – '
                         'mit derselben oder einer anderen Idee.</p>')
        else:
            teile.append('<p class="meta">Die Bilder entstehen nacheinander, etwa 2 Minuten je Bild. Die Seite '
                         'lädt sich von selbst neu.</p>')
        teile.append(f'<div class="{klassen("ki-raster", format_klasse(a.get("briefing")))}">{raster}</div>')
        if pruefen:
            fertig = len(fertige_ki_bilder(a))
            if fertig:
                menge = "dem fertigen Bild" if fertig == 1 else f"den {fertig} fertigen Bildern"
                rest = (" Fehlgeschlagene Bilder bleiben draußen."
                        if any(b.get("status") == "fehler" for b in bilder) else "")
                teile.append(
                    f'<form method="post" action="{e(detail_url(str(a.get("id") or "")))}/ki/bauen" class="reel-form">'
                    f'{csrf()}<input type="hidden" name="mandant" value="{e(m)}">'
                    f'<p class="meta">Gebaut wird mit {menge}, in dieser Reihenfolge.{rest}</p>'
                    '<button class="primaer" type="submit">Reel bauen</button></form>')
            else:
                teile.append('<p class="hinweis">Noch kein Bild ist fertig. Lass mindestens eins neu erzeugen, '
                             'erst dann kann das Reel entstehen.</p>')
        return "".join(teile) + "</section>"

    @ui._gesichert_seite
    async def detail(request):
        aid = request.path_params["aid"]
        if not _AID.fullmatch(aid):
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es nicht.")
        try:
            m, firmen = await marketing_mandant.firma(request)
            a = await auftrag_der_firma(m, aid)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if a is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es bei der gewählten Firma nicht.")
        return ui._seite("Reels", kopf(m, firmen) + detail_html(a, m),
                         refresh=REFRESH_S if a.get("status") in LAUFEND else None)

    def aid_aus(request) -> str | None:
        aid = request.path_params["aid"]
        return aid if _AID.fullmatch(aid) else None

    @ui._gesichert_seite
    async def nochmal(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        aid = aid_aus(request)
        if not aid:
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es nicht.")
        wunsch = str(form.get("wunsch") or "").strip()
        if len(wunsch) > WUNSCH_MAX:
            return ui._fehlerseite(422, "Nicht möglich", f"Der Wunsch darf höchstens {WUNSCH_MAX} Zeichen haben.")
        try:
            m, _ = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/nochmal",
                                        {"wunsch": wunsch, "mandant": m})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        neu = str(d.get("auftrag") or "") if isinstance(d, dict) else ""
        return RedirectResponse(detail_url(neu) if _AID.fullmatch(neu) else SEITE, status_code=303)

    @ui._gesichert_seite
    async def archiv(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        aid = aid_aus(request)
        if not aid:
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es nicht.")
        an = str(form.get("an") or "") == "1"
        try:
            m, _ = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/archivieren",
                                        {"an": an, "mandant": m})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not (isinstance(d, dict) and d.get("ok")):
            return ui._fehlerseite(422, "Nicht möglich", "Nur erledigte Reels lassen sich archivieren.")
        return RedirectResponse(detail_url(aid), status_code=303)

    @ui._gesichert_seite
    async def abbrechen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        aid = aid_aus(request)
        if not aid:
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es nicht.")
        try:
            m, _ = await marketing_mandant.firma(request)
            # mit mandant prueft die API, dass der Auftrag dieser Firma gehoert
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/abbrechen", {"mandant": m})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(detail_url(aid), status_code=303)

    def nicht_gefunden():
        return ui._fehlerseite(404, "Nicht gefunden", "Dieses Reel gibt es bei der gewählten Firma nicht.")

    def firma_gewechselt():
        return ui._fehlerseite(422, "Nicht möglich", "Die Firma wurde inzwischen gewechselt – bitte die Seite neu laden.")

    @ui._gesichert_seite
    async def ki_neu(request):
        """Ein KI-Bild neu erzeugen lassen (E6/E7): nur ein Bild dieses Auftrags der gewaehlten Firma,
        nur waehrend der Pruefung. Die API prueft noch einmal (eine Wahrheit)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        aid = aid_aus(request)
        if not aid:
            return nicht_gefunden()
        idee = str(form.get("idee") or "").strip()
        if len(idee) > IDEE_MAX:
            return ui._fehlerseite(422, "Nicht möglich", f"Die Idee darf höchstens {IDEE_MAX} Zeichen haben.")
        bid = str(form.get("bild") or "")
        try:
            m, _ = await marketing_mandant.firma(request)
            if str(form.get("mandant") or "") != m:      # Tab von vor dem Firmenwechsel (wie bei der Bestellung)
                return firma_gewechselt()
            a = await auftrag_der_firma(m, aid)
            if a is None or not _AID.fullmatch(bid):
                return nicht_gefunden()
            # Doppelklick oder alter Tab: Pruefung vorbei bzw. Bild schon verworfen -> zurueck zur Seite.
            # Erst der Status: nach dem Bau stehen die Bilder nicht mehr zur Wahl.
            if a.get("status") != "bilder_pruefen" or bid not in {str(b.get("id")) for b in ki_bilder(a)}:
                return RedirectResponse(detail_url(aid), status_code=303)
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/ki/neu",
                                    {"bild": bid, "mandant": m, "idee": idee})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(detail_url(aid), status_code=303)

    @ui._gesichert_seite
    async def ki_bauen(request):
        """Reel bauen freigeben (E6/E7): die fertigen Bilder gehen nach nr ins Briefing, der Auftrag auf offen."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        aid = aid_aus(request)
        if not aid:
            return nicht_gefunden()
        nur_fertige = "Reel bauen geht erst, wenn die Bilder bereitstehen und mindestens ein Bild fertig ist."
        try:
            m, _ = await marketing_mandant.firma(request)
            if str(form.get("mandant") or "") != m:
                return firma_gewechselt()
            a = await auftrag_der_firma(m, aid)
            if a is None:
                return nicht_gefunden()
            if a.get("status") != "bilder_pruefen":      # schon gebaut/abgebrochen (Doppelklick, alter Tab)
                return RedirectResponse(detail_url(aid), status_code=303)
            if not fertige_ki_bilder(a):
                return ui._fehlerseite(422, "Nicht möglich", nur_fertige)
            d = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/video/{aid}/ki/freigeben", {"mandant": m})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not (isinstance(d, dict) and d.get("ok")):
            return ui._fehlerseite(422, "Nicht möglich", nur_fertige)
        return RedirectResponse(detail_url(aid), status_code=303)

    # --- Gefuehrte Bestellung --------------------------------------------------------------

    def schritte(aktiv: int) -> str:
        namen = ("Art wählen", "Material", "Text")
        aktuell = ' aria-current="step"'
        teile = "".join(f'<li{aktuell if i == aktiv else ""}>{e(n)}</li>' for i, n in enumerate(namen, 1))
        return f'<ol class="reel-schritte">{teile}</ol>'

    def schritt1() -> str:
        karten = "".join(f'<a class="reel-art" href="{NEU_SEITE}?art={k}"><b>{e(n)}</b>'
                         f'<span>{e(ARTEN_TEXT[k])}</span></a>' for k, n in ARTEN.items())
        return schritte(1) + f'<div class="reel-arten">{karten}</div>'

    async def bilder_der_firma(m: str) -> list[str]:
        d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                    f"/video/bilder?{urllib.parse.urlencode({'mandant': m})}")
        roh = d.get("bilder") if isinstance(d, dict) else None
        # KI-Bilder (ki-*) sind keine Auswahl: verworfene Versuche kennt nur die Marketing-DB (medien.KI_REEL_MUSTER)
        return [str(b.get("name")) for b in roh or [] if isinstance(b, dict) and _BILD.fullmatch(str(b.get("name") or ""))
                and not _KI_DATEI.fullmatch(str(b.get("name")))]

    async def laura_videos() -> tuple[list[dict], str]:
        """(videos, hinweis). Laura oder die API weg: leere Liste mit Hinweis statt Fehlerseite (Review
        Focus 5) - nur eine fehlende Verbindung zur API ist ein Fehler."""
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", "/video/material",
                                        zeitlimit=MATERIAL_ZEITLIMIT_S)
        except marketing_pult.PultFehler as f:
            if f.art == "nicht_verbunden":
                raise
            return [], "Die Liste der Laura-Videos ist gerade nicht erreichbar."
        roh = d.get("videos") if isinstance(d, dict) else None
        videos = [v for v in roh or [] if isinstance(v, dict) and _LAURA_ID.fullmatch(str(v.get("kennung") or ""))]
        hinweis = str(d.get("hinweis") or "") if isinstance(d, dict) else ""
        return videos, hinweis

    def weiter_form(art: str, innen: str, mit_knopf: bool = True) -> str:
        knopf = '<button class="primaer" type="submit">Weiter</button>' if mit_knopf else ""
        return (f'<form method="get" action="{NEU_SEITE}" class="reel-wahl">'
                f'<input type="hidden" name="art" value="{e(art)}"><input type="hidden" name="schritt" value="3">'
                f'{innen}<div class="aktionen">{knopf}<a href="{NEU_SEITE}">Andere Art</a></div></form>')

    def ki_anzahl_wahl(anzahl: int | None) -> str:
        gewaehlt = anzahl if anzahl in KI_ANZAHLEN else KI_VORGABE
        punkte = "".join(
            f'<label><input type="radio" name="anzahl" value="{n}"{" checked" if n == gewaehlt else ""}> {n} Bilder</label>'
            for n in KI_ANZAHLEN)
        return (f'<fieldset class="ki-anzahl"><legend>Wie viele Bilder?</legend>{punkte}</fieldset>'
                '<p class="meta">Das dauert etwa 2 Minuten je Bild. Die Bilder folgen dem Bildstil deiner Marke; '
                'du siehst sie dir an, bevor das Reel gebaut wird.</p>')

    async def schritt2(art: str, m: str, bilder: list[str], logo: str, videos: list[str], warnung: str,
                       anzahl: int | None = None) -> str:
        teile = [schritte(2), f"<h2>{e(ARTEN[art])}</h2>"]
        if warnung:
            teile.append(f'<p class="warnung">{e(warnung)}</p>')
        if art == "ki":
            teile.append(weiter_form(art, ki_anzahl_wahl(anzahl)))
            return "".join(teile)
        if art == "bilder":
            namen = await bilder_der_firma(m)
            if not namen:
                teile.append('<p class="hinweis">Noch keine Bilder in den Medien. Lade erst welche unter '
                             '<a href="/medien">Medien</a> hoch.</p>'
                             f'<p><a href="{NEU_SEITE}">Andere Art</a></p>')
                return "".join(teile)
            felder = "".join(
                f'<label class="bild-wahl"><input type="checkbox" name="bild" value="{e(n)}"'
                f'{" checked" if n in bilder else ""}><img src="{datei_url(n)}" loading="lazy" alt="">'
                f'<span>{e(n)}</span></label>' for n in namen)
            optionen = '<option value="">kein Logo</option>' + "".join(
                f'<option value="{e(n)}"{" selected" if n == logo else ""}>{e(n)}</option>' for n in namen)
            teile.append(weiter_form(art, f'<p class="meta">Wähle mindestens ein und höchstens {AUSWAHL_MAX} Bilder. '
                                          'Die Reihenfolge legt der Claw fest.</p>'
                                          f'<div class="bild-raster">{felder}</div>'
                                          f'<label>Logo (optional) <select name="logo">{optionen}</select></label>'))
            return "".join(teile)
        liste_, hinweis = await laura_videos()
        if hinweis:
            teile.append(f'<p class="hinweis">{e(hinweis)}</p>')
        typ = "radio" if art == "kurzfassung" else "checkbox"
        if art == "material":
            teile.append(f'<p class="meta">Wähle höchstens {AUSWAHL_MAX} Videos. Wählst du keins, sucht der '
                         'Claw selbst passendes Material.</p>')
        else:
            teile.append('<p class="meta">Wähle genau ein langes Video, das gekürzt werden soll.</p>')
        if not liste_ and art == "kurzfassung":
            teile.append('<p class="meta">Ohne Video aus Laura geht keine Kurzfassung. Versuch es später noch '
                         f'einmal.</p><p><a href="{NEU_SEITE}">Andere Art</a></p>')
            return "".join(teile)
        zeilen = "".join(
            f'<tr><td data-label="Video"><label class="haken"><input type="{typ}" name="video" '
            f'value="{e(v["kennung"])}"{" checked" if v["kennung"] in videos else ""}> {e(str(v.get("name") or ""))}'
            f'</label></td><td data-label="Projekt">{e(str(v.get("projekt") or ""))}</td>'
            f'<td data-label="Länge">{e(laenge_text(v.get("dauer_s")))}</td></tr>' for v in liste_)
        tabelle = (f'<div class="tabelle"><table><thead><tr><th>Video</th><th>Projekt</th><th>Länge</th></tr>'
                   f'</thead><tbody>{zeilen}</tbody></table></div>') if zeilen else ""
        teile.append(weiter_form(art, tabelle))
        return "".join(teile)

    async def stimmen_liste() -> list[str] | None:
        """Namen aus GET /stimmen oder None, wenn die Liste nicht lesbar ist (dann nichts behaupten)."""
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", "/stimmen")
        except marketing_pult.PultFehler:
            return None
        roh = d.get("stimmen") if isinstance(d, dict) else None
        return [n for n in roh if isinstance(n, str)] if isinstance(roh, list) else None

    async def stimme_zeile(m: str) -> str:
        """E2: Die Stimme kommt aus der Marke; ohne Markenstimme gilt Standard."""
        try:
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/marke?{urllib.parse.urlencode({'mandant': m})}")
        except marketing_pult.PultFehler:
            return '<p class="meta">Stimme: aus der Marke der Firma.</p>'
        profil = d.get("profil") if isinstance(d, dict) and isinstance(d.get("profil"), dict) else {}
        werte = profil.get("werte") if isinstance(profil.get("werte"), dict) else {}
        stimme = str(werte.get("stimme") or "").strip()
        if stimme and stimme != STANDARD_STIMME and (liste := await stimmen_liste()) is not None                 and stimme not in liste:
            # wie die API (_stimme_einsetzen): eine Markenstimme ohne Stimmprobe wird zu Standard
            return (f'<p class="meta">Stimme: Standard (die Markenstimme „{e(stimme)}“ '
                    f'gibt es nicht mehr)</p>')
        if stimme:
            return f'<p class="meta">Stimme: <b>{e(stimme)}</b> (aus der Marke)</p>'
        return f'<p class="meta">Stimme: Standard – <a href="{MARKE_PROFIL}">in der Marke festlegen</a></p>'

    def formate_wahl() -> str:
        punkte = "".join(
            f'<label><input type="radio" name="format" value="{k}"{" checked" if k == "reel" else ""}> {e(t)}</label>'
            for k, t in FORMATE.items())
        return f'<fieldset class="reel-formate"><legend>Format</legend>{punkte}</fieldset>'

    async def schritt3(art: str, m: str, bilder: list[str], logo: str, videos: list[str],
                       anzahl: int | None = None) -> str:
        versteckt = [("art", art)] + [("bild", n) for n in bilder] + ([("logo", logo)] if logo else []) + [
            ("video", v) for v in videos] + ([("anzahl", str(anzahl))] if art == "ki" else [])
        felder = "".join(f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in versteckt)
        zurueck_zu = f"{NEU_SEITE}?{urllib.parse.urlencode([(k, v) for k, v in versteckt])}"
        if art == "ki":
            punkte = [f"<li>{anzahl} KI-Bilder im Bildstil deiner Marke – du siehst sie vor dem Bau.</li>"]
        elif art == "bilder":
            punkte = [f'<li><img src="{datei_url(n)}" loading="lazy" alt=""> {e(n)}</li>' for n in bilder]
            if logo:
                punkte.append(f"<li>Logo: {e(logo)}</li>")
        elif videos:
            liste_, _ = await laura_videos()        # Laura weg: leere Liste, dann stehen die Kennungen da
            namen = {str(v["kennung"]): str(v.get("name") or "") for v in liste_}
            punkte = [f"<li>{e(namen.get(v) or v)}</li>" for v in videos]
        else:
            punkte = ["<li>Keine Auswahl – der Claw sucht selbst passendes Material.</li>"]
        pflicht = "" if art == "kurzfassung" else " required"
        return (schritte(3) + f"<h2>{e(ARTEN[art])}</h2>"
                f'<form method="post" action="{NEU_SEITE}" class="reel-form">{csrf()}'
                f'<input type="hidden" name="mandant" value="{e(m)}">{felder}'
                f'<div class="reel-auswahl"><h3>Deine Auswahl</h3><ul>{"".join(punkte)}</ul>'
                f'<a href="{e(zurueck_zu)}">Ändern</a></div>'
                '<label>Titel <input type="text" name="titel" required maxlength="120"></label>'
                '<label>Thema <input type="text" name="thema" required maxlength="300"></label>'
                f'<label>Sprechertext <textarea name="sprechertext" rows="4" maxlength="900"{pflicht}></textarea></label>'
                '<label>Einstieg (eine Zeile) <input type="text" name="hook" maxlength="120"></label>'
                '<label>Länge in Sekunden <input type="number" name="dauer_s" min="15" max="60" value="30"></label>'
                + formate_wahl()
                + await stimme_zeile(m)
                + '<p class="meta">Das Reel bekommt Untertitel, die Farben der Marke und den Hinweis „Stimme: KI“.</p>'
                '<div class="aktionen"><button class="primaer" type="submit">Bestellen</button></div></form>')

    @ui._gesichert_seite
    async def bestellung(request):
        q = request.query_params
        art = q.get("art", "")
        bilder = _texte(q.getlist("bild")) if art == "bilder" else []
        logo = str(q.get("logo") or "").strip() if art == "bilder" else ""
        videos = _texte(q.getlist("video")) if art in ("material", "kurzfassung") else []
        anzahl = ki_anzahl(q.get("anzahl")) if art == "ki" else None
        if logo and not _BILD.fullmatch(logo):
            logo = ""
        try:
            m, firmen = await marketing_mandant.firma(request)
            kopf_ = bestell_kopf(m, firmen)
            if art not in ARTEN:
                return ui._seite("Neues Reel", kopf_ + schritt1())
            if q.get("schritt") == "3":
                warnung = auswahl_fehler(art, bilder, videos, anzahl)
                if not warnung:
                    return ui._seite("Neues Reel", kopf_ + await schritt3(art, m, bilder, logo, videos, anzahl))
                # Review Task 5: der gueltige Teil der Auswahl bleibt angehakt
                bleibt = [n for n in bilder if _BILD.fullmatch(n)][:AUSWAHL_MAX]
                bleiben_v = [v for v in videos if _LAURA_ID.fullmatch(v)][:1 if art == "kurzfassung" else AUSWAHL_MAX]
                return ui._seite("Neues Reel", kopf_ + await schritt2(art, m, bleibt, logo, bleiben_v, warnung, anzahl),
                                 status=422)
            return ui._seite("Neues Reel", kopf_ + await schritt2(art, m, bilder, logo, videos, "", anzahl))
        except marketing_pult.PultFehler as f:
            return fehler(f)

    @ui._gesichert_seite
    async def neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        art, titel, briefing = briefing_aus_formular(form)
        if art not in ARTEN or not titel or not briefing["thema"]:
            return ui._fehlerseite(422, "Nicht möglich", "Art, Titel und Thema sind nötig.")
        # die rohe Auswahl: bei der Kurzfassung nahm das Briefing sonst still das erste von mehreren Videos
        warnung = auswahl_fehler(art, _texte(form.getlist("bild")) if art == "bilder" else [],
                                 _texte(form.getlist("video")) if art in ("material", "kurzfassung") else [],
                                 ki_anzahl(form.get("anzahl")) if art == "ki" else None)
        if warnung:
            return ui._fehlerseite(422, "Nicht möglich", e(warnung))
        try:
            m, _ = await marketing_mandant.firma(request)
            if str(form.get("mandant") or "") != m:      # Tab von vor dem Firmenwechsel (wie ui_marke.bearbeiten)
                return ui._fehlerseite(422, "Nicht möglich", "Die Firma wurde inzwischen gewechselt – bitte neu bestellen.")
            # KI-Bilder sind fuer die API Art "bilder" mit briefing.ki (E2)
            d = await run_in_threadpool(marketing_pult.anfrage, "POST", "/video",
                                        {"mandant": m, "art": "bilder" if art == "ki" else art, "titel": titel,
                                         "briefing": briefing})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        aid = str(d.get("auftrag") or "") if isinstance(d, dict) else ""
        return RedirectResponse(detail_url(aid) if _AID.fullmatch(aid) else SEITE, status_code=303)

    # --- LinkedIn-Entwurf ------------------------------------------------------------------

    async def nicht_eigenes_reel(request, datei: str):
        """None, wenn `datei` ein fertiges Reel der Firma dieses Ladens ist (aktuell oder Archiv)
        und genau diese Firma gewaehlt ist; sonst die Fehlerseite (Review Focus 1)."""
        firma = eigene_firma()
        if not firma:
            return ui._fehlerseite(422, "Nicht möglich", "Dieser Laden ist keiner Marketing-Firma zugeordnet.")
        try:
            m, _ = await marketing_mandant.firma(request)
            if m != firma:
                return ui._fehlerseite(422, "Nicht möglich", "Dieses Reel gehört nicht zur Firma dieses Ladens.")
            alle = await liste(firma, False, DETAIL_LIMIT) + await liste(firma, True, DETAIL_LIMIT)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        eigene = {str(a.get("datei")) for a in alle if a.get("status") == "fertig"}
        if datei not in eigene:
            return ui._fehlerseite(422, "Nicht möglich", "Dieses Reel gehört nicht zur Firma dieses Ladens.")
        return None

    @ui._gesichert_seite
    async def post_vorbereiten(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        datei = str(form.get("datei") or "")
        thema = str(form.get("thema") or "").strip()
        text = str(form.get("text") or "").strip()
        if not _DATEI.fullmatch(datei) or not thema or not text or len(text) > POST_TEXT_MAX:
            return ui._fehlerseite(422, "Nicht möglich", "Reel-Datei, Thema und Text (bis 3000 Zeichen) sind nötig.")
        abgelehnt = await nicht_eigenes_reel(request, datei)
        if abgelehnt is not None:
            return abgelehnt
        ergebnis = json.loads(await run_in_threadpool(ui.server.post_entwurf_erstellen, thema, text, datei))
        if ergebnis.get("fehler"):
            return ui._fehlerseite(422, "Nicht möglich", e(str(ergebnis["fehler"])))
        return RedirectResponse("/freigaben", status_code=303)

    # --- Auf Kanaelen teilen (Beitraege auf weitere Kanaele, Task 8) ------------------------

    @ui._gesichert_seite
    async def kanaele_teilen(request):
        """Je verbundenem Kanal, der diese Medienart nimmt, ein Entwurf ueber
        server.kanal_post_entwurf - veroeffentlicht wird erst nach der Freigabe. dev.to nie."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return abgewiesen()
        datei = str(form.get("datei") or "")
        thema = str(form.get("thema") or "").strip()
        text = str(form.get("text") or "").strip()
        link = str(form.get("link") or "").strip()
        if not _DATEI.fullmatch(datei) or not thema or not text or len(text) > POST_TEXT_MAX:
            return ui._fehlerseite(422, "Nicht möglich", "Reel-Datei, Thema und Text (bis 3000 Zeichen) sind nötig.")
        if link and (len(link) > LINK_MAX or not _LINK.fullmatch(link)):
            return ui._fehlerseite(422, "Nicht möglich",
                                   f"Der Link muss mit https:// beginnen und darf höchstens {LINK_MAX} Zeichen haben.")
        abgelehnt = await nicht_eigenes_reel(request, datei)
        if abgelehnt is not None:
            return abgelehnt
        art = "video" if medien.endpunkt_und_typ(datei)[1].startswith("video/") else "bild"
        status = await run_in_threadpool(kanaele.status_lesen, ui.server._q)
        ziele = [info for k, info in kanaele.KANAELE.items()
                 if k != "devto" and (status.get(k) or {}).get("verbunden")
                 and (info.video_max if art == "video" else info.bilder_max) >= 1]
        if not ziele:
            return ui._fehlerseite(
                422, "Nicht möglich",
                f"Kein verbundener Kanal nimmt dieses Reel ({'Video' if art == 'video' else 'Bild'}). "
                'Kanäle: <a href="/einstellungen/kanaele">/einstellungen/kanaele</a>')
        zeilen = []
        for info in ziele:
            platz = info.max_zeichen_mit_medien - (len(link) + 2 if link else 0)
            fassung = kuerzen(text, platz) + ("\n\n" + link if link else "")
            antwort = json.loads(await run_in_threadpool(
                ui.server.kanal_post_entwurf, info.name, thema, fassung, medien_dateien=datei))
            grund = antwort.get("fehler") if isinstance(antwort, dict) else "unerwartete Antwort"
            zeilen.append(f"<li><strong>{e(info.anzeige)}</strong>: "
                          + (e(str(grund)) if grund else "angelegt") + "</li>")
        rumpf = (f'<ul>{"".join(zeilen)}</ul>'
                 '<p class="meta">Veröffentlicht wird erst nach deiner Freigabe.</p>'
                 '<p><a class="knopf" href="/freigaben">Zu den Freigaben</a></p>')
        return ui._seite("Auf Kanälen teilen", rumpf)

    return [
        Route(SEITE, galerie),
        Route(NEU_SEITE, bestellung),
        Route(NEU_SEITE, neu, methods=["POST"]),
        Route(f"{SEITE}/post", post_vorbereiten, methods=["POST"]),
        Route(f"{SEITE}/kanaele", kanaele_teilen, methods=["POST"]),
        Route(SEITE + "/{aid}", detail),
        Route(SEITE + "/{aid}/nochmal", nochmal, methods=["POST"]),
        Route(SEITE + "/{aid}/archiv", archiv, methods=["POST"]),
        Route(SEITE + "/{aid}/abbrechen", abbrechen, methods=["POST"]),
        Route(SEITE + "/{aid}/ki/neu", ki_neu, methods=["POST"]),
        Route(SEITE + "/{aid}/ki/bauen", ki_bauen, methods=["POST"]),
    ]
