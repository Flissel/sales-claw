"""Seite "Marke" im Marketing-Bereich (Spec 2026-10-07-marke-per-chat-design.md §4.1, Plan
2026-10-20-marken-chat-neu.md E10/E11). /marketing/layouts hat zwei Reiter:

- "Chat" (Vorgabe): Faehigkeiten des Agenten (eingeklappt), der Verlauf mit dem Aeltesten oben,
  je Runde Du-Blase und Agent-Blase mit Schritten und Quellen, direkte Aenderungen mit
  "Rueckgaengig", ein offener Vorschlag in seiner Runde, unten die feste Eingabe, die
  Zeile "Firmenwissen" und das Sprungziel #ende.
- "Profil": alle Abschnitte als Karten (Namen aus der API, `abschnitt_namen`), Farben, Schriften
  und beide Logos; darunter "Profil bearbeiten" (Formularfelder `abschnitt::<Name>`).

Wie der Rest von sales-ui ohne JavaScript: Formulare, Verweise und ein Meta-Refresh alle 5 s mit
Sprunganker, solange ein Chat-, Bearbeitungs- oder Uebernahme-Auftrag laeuft (ein Wissens-Lauf nie:
Link "Aktualisieren"). Jede Weiterleitung nach einem POST geht auf ZIEL (E11). Daten kommen nur
ueber marketing_pult; jeder Aufruf laeuft im Threadpool. Der alte Regler-Editor entfaellt, seine
Pfade leiten hierher.

Uploads (Plan-Ruling R2): Bilder und Dokumente gehen durch dieselbe Ablage und Pruefung wie
der Editor-Anhang (ui_editor.anhang_speichern), gehoeren aber der gewaehlten Firma
(POST /medien/zuordnung); scheitert die Zuordnung, wird die Datei wieder geloescht."""
from __future__ import annotations

import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_mandant
import marketing_pult
import schriften
import ui_editor
import ui_muster

SEITE = "/marketing/layouts"
ZIEL = f"{SEITE}?reiter=chat#ende"            # E11: jede Weiterleitung nach einem POST
NACHRICHT_MAX = 2000
PC_WARTET_NACH_S = 60                # danach: "sobald der PC läuft"
ANHAENGE_MAX = 5                     # wie ANHAENGE_MAX der Marketing-API (kontext.anhaenge)
REFRESH_S = 5
FORMATE = {"mail": "Mail", "handy": "Handy"}
REITER = (("chat", "Chat", None), ("profil", "Profil", None))
PC_LAEUFT = "Wird übernommen, sobald der PC läuft"
WISSEN_WARTET = "Wissen wird aktualisiert, sobald der PC läuft"
WISSEN_LAEUFT = "Wissen wird aktualisiert …"
WISSEN_AKTUALISIEREN = "Aktualisieren"
KEIN_PROFIL = "Noch kein Branding – erzähl mir von der Firma"
NOCH_LEER = "Noch leer – frag den Agenten"
NEUERES_PROFIL = "Inzwischen gibt es ein neueres Profil – bitte neu laden"
_FARBE = re.compile(r"#[0-9A-Fa-f]{6}")
LOGO_BASE64_MAX = 210_000           # Logo <= 140 KB als data-URL = rund 187 000 Zeichen, plus Luft
_BILD_DATEN = re.compile(rf"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]{{1,{LOGO_BASE64_MAX}}}")
_PROFIL_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Fläche"), ("grund", "Grund"), ("text", "Text"))
_VORSCHLAG_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Zweitfarbe"), ("grund", "Grund"), ("text", "Text"))
FORM_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Zweitfarbe"), ("grund", "Grund"), ("text", "Text"))
FARBE_MAX, SCHRIFT_MAX, WEBSEITE_MAX, ABSCHNITT_MAX = 20, 40, 300, 8000   # wie api/marke.FORMULAR_GRENZEN
FELD_ABSCHNITT = "abschnitt::"       # Formularfeld je Abschnitt: abschnitt::<Name> (E2)
ABSCHNITTE_MAX, ABSCHNITT_NAME_MAX = 40, 100   # Obergrenzen fuer Fremdeingaben; die API prueft die Namen
_ALTES_FELD = re.compile(r"ab\d+")   # Formular von vor E2 (ab0..ab6): wuerde alle Abschnitte leeren
_MEDIENNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(?:png|jpe?g)")
_STATUS = {"offen": "wartet (PC muss laufen)", "in_arbeit": "wird bearbeitet", "fehler": "fehlgeschlagen"}
_VORSCHLAG_STATUS = {"angenommen": "Vorschlag übernommen", "verworfen": "Vorschlag verworfen",
                     "ersetzt": "Vorschlag durch einen neueren ersetzt"}
_QUELLEN_ART = {"gelesen": "gelesen", "websuche": "Websuche"}
WEBSUCHE_SCHRITT = "Websuche genutzt"
ENDE = '<div id="ende" class="ende"></div>'   # Sprungziel ganz unten (E11)


def _uuid_oder_none(wert) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except ValueError:
        return None


def _medienname(wert) -> str | None:
    w = str(wert or "")
    w = w[len("anhang:"):] if w.startswith("anhang:") else w
    return w if _MEDIENNAME.fullmatch(w) else None


def _alter_s(roh) -> float | None:
    """Alter eines ISO-/Postgres-Zeitpunkts in Sekunden; ohne Zeitzone gilt UTC. None, wenn unlesbar."""
    try:
        dt = datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _familie(sid) -> str | None:
    s = schriften.REGISTER.get(sid) if isinstance(sid, str) else None
    return s["familie"] if s else None


def _dict(wert) -> dict:
    return wert if isinstance(wert, dict) else {}


def _texte(wert) -> list[str]:
    return [str(x) for x in wert if str(x).strip()] if isinstance(wert, list) else []


def adresse(reiter: str = "chat", alle: bool = False, fmt: str | None = None, anker: str = "",
            stand: int | None = None) -> str:
    """Seitenadresse aus geprueften Werten (Reiter, alle, Vorschau-Format, stand)."""
    q = {"reiter": reiter}
    if alle:
        q["alle"] = "1"
    if fmt:
        q["format"] = fmt
    if stand is not None:
        q["stand"] = str(int(stand))
    return f"{SEITE}?{urllib.parse.urlencode(q)}{anker}"


def abschnitt_namen(d: dict, abschnitte: dict) -> list[str]:
    """Reihenfolge der Profilkarten: die Namen der API (`abschnitt_namen`, E2); fehlt die Liste, die Abschnitte
    des Profils in ihrer Reihenfolge. Abschnitte des Profils, die die Liste nicht kennt, kommen danach."""
    namen = [n for n in d.get("abschnitt_namen") or [] if isinstance(n, str) and n.strip()] \
        if isinstance(d.get("abschnitt_namen"), list) else []
    return namen + [n for n in abschnitte if isinstance(n, str) and n not in namen]


def routen(ui) -> list:
    from ui_marketing import _gerahmt, _wann
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", f'{e(f.grund)}<p><a href="{ZIEL}">Zur Marke</a></p>')
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def abgewiesen(status: int, text: str):
        return ui._fehlerseite(status, "Nicht möglich", f'{e(text)}<p><a href="{ZIEL}">Zur Marke</a></p>')

    def csrf_feld() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def farbfeld(name: str, wert) -> str:
        w = str(wert or "")
        if not _FARBE.fullmatch(w):
            return ""
        return (f'<span class="farbe"><span class="farbfeld" style="background:{w}"></span>'
                f'{e(name)} {e(w)}</span>')

    def absaetze(text) -> str:
        return e(str(text)).replace("\n", "<br>")

    # --- Profil ----------------------------------------------------------------------------

    def muster(sid, firma: str) -> str:
        """Schriftmuster "Aa – Firma" in der Schrift (nur Register-ids, sonst nur der Name)."""
        familie = _familie(sid)
        if not familie:
            return f'<span class="schriftmuster">{e(str(sid or ""))}</span>'
        return (f'<span class="schriftmuster" style="font-family:\'{familie}\', sans-serif">'
                f'Aa – {e(firma)}</span> <span class="meta">({e(familie)})</span>')

    def schrift_zeile(anzeige, text, firma: str) -> str:
        if not (anzeige or text):
            return ""
        return (f'<p class="schriften">Überschrift: {muster(anzeige, firma)}<br>'
                f'Text: {muster(text, firma)}</p>')

    def liste(eintraege, klasse: str) -> str:
        punkte = "".join(f"<li>{e(str(h))}</li>" for h in eintraege or [] if str(h).strip())
        return f'<ul class="{klasse}">{punkte}</ul>' if punkte else ""

    def spiegel_warnung(sp: dict) -> str:
        if not sp.get("fehler"):
            return ""
        grund = e(str(sp["fehler"]))
        if not sp.get("gespiegelt_am"):          # noch nie gelungen: es gibt kein "seit"
            return f'<p class="warnung">Spiegel noch nie gesetzt: {grund}</p>'
        return f'<p class="warnung">Spiegel veraltet seit {e(_wann(ui, sp.get("gespiegelt_am")))}: {grund}</p>'

    def logo_fassungen_html(w: dict) -> str:
        """Original, logo auf Weiss und logo_dunkel auf #1a1a1a (Spec 2026-10-09 §1); ohne dunkle Fassung nur das Logo."""
        hell, dunkel, original = (_medienname(w.get(k)) for k in ("logo", "logo_dunkel", "logo_original"))
        if not hell:
            return ""

        def bild(name: str, titel: str, klasse: str) -> str:
            return (f'<figure class="logo-fassung {klasse}"><img src="/medien/datei/{e(name)}" alt="{e(titel)}">'
                    f'<figcaption>{e(titel)}</figcaption></figure>')
        teile = [bild(original, "Original", "original")] if original and dunkel else []
        teile.append(bild(hell, "Logo auf Weiß" if dunkel else "Logo", "hell"))
        if dunkel:
            teile.append(bild(dunkel, "Logo auf dunkler Fläche", "dunkel"))
        return f'<div class="logo-fassungen">{"".join(teile)}</div>'

    def profil_quelle(d: dict) -> tuple[dict, dict]:
        """(werte, abschnitte) des aktuellen Profils: das echte Profil der Marke.md (`profil`, vom PC gemeldet,
        Ruling R8), sonst der zuletzt uebernommene Vorschlag (`aktuell`)."""
        p = d.get("profil") if isinstance(d.get("profil"), dict) else None
        p = p if p is not None else _dict(d.get("aktuell"))
        return _dict(p.get("werte")), _dict(p.get("abschnitte"))

    def bearbeiten_html(d: dict, mandant: str) -> str:
        if d.get("laeuft") or d.get("uebernahme"):
            return '<p class="meta">Der Marken-Agent arbeitet gerade – bearbeiten geht danach.</p>'
        offen = d.get("vorschlag") if isinstance(d.get("vorschlag"), dict) else None
        warnung = (f'<p class="warnung">Es gibt einen offenen Vorschlag vom {e(_wann(ui, offen.get("erstellt_am")))}'
                   ' – wenn du das Formular abschickst, ersetzt es ihn. Übernimm oder verwirf ihn vorher, '
                   'wenn du ihn behalten willst.</p>') if offen else ""
        werte, ab = profil_quelle(d)
        g = _dict(_dict(d.get("spiegel")).get("gestalt"))
        sw = _dict(g.get("schriften"))
        vor = {"akzent": werte.get("akzent") or g.get("akzent"), "zweitfarbe": werte.get("zweitfarbe") or g.get("flaeche"),
               "grund": werte.get("grund"), "text": werte.get("text"),
               "schrift_anzeige": werte.get("schrift_anzeige") or sw.get("anzeige"),
               "schrift_text": werte.get("schrift_text") or sw.get("text"), "webseite": werte.get("webseite")}

        def wert(k: str) -> str:
            return str(vor[k]) if isinstance(vor.get(k), str) else ""

        def auswahl(name: str, titel: str) -> str:
            optionen = ['<option value="">– bitte wählen –</option>'] + [
                f'<option value="{e(sid)}"{" selected" if sid == vor.get(name) else ""}>{e(s["familie"])}</option>'
                for sid, s in schriften.REGISTER.items()]
            return f'<label>{e(titel)} <select name="{name}">{"".join(optionen)}</select></label>'
        farben = "".join(f'<label>{e(t)} <input name="{k}" value="{e(wert(k))}" maxlength="{FARBE_MAX}" '
                         f'placeholder="#RRGGBB"></label>' for k, t in FORM_FARBEN)
        texte = "".join(f'<label>{e(n)} <textarea name="{e(FELD_ABSCHNITT + n)}" rows="4" maxlength="{ABSCHNITT_MAX}">'
                        f'{e(str(ab.get(n) or ""))}</textarea></label>' for n in abschnitt_namen(d, ab))
        return (warnung + '<h2>Profil bearbeiten</h2><p class="meta">Der Marken-Agent übernimmt deine Angaben wörtlich und '
                'korrigiert nur Ungültiges (mit Hinweis). Reine Texte gelten sofort, Farben, Schriften und die '
                'Webseite kommen als Vorschlag zum Übernehmen.</p>'
                f'<form method="post" action="/marketing/marke/bearbeiten" class="pult-felder marke-bearbeiten">'
                f'{csrf_feld()}<input type="hidden" name="mandant" value="{e(mandant)}">'
                f'<fieldset><legend>Farben</legend>{farben}</fieldset>'
                f'<fieldset><legend>Schriften</legend>{auswahl("schrift_anzeige", "Überschrift")}'
                f'{auswahl("schrift_text", "Text")}</fieldset>'
                f'<label>Webseite <input name="webseite" type="url" value="{e(wert("webseite"))}" '
                f'maxlength="{WEBSEITE_MAX}" placeholder="https://…"></label>{texte}'
                f'<div class="aktionen"><button class="primaer" type="submit">An den Agenten geben</button> '
                f'<a href="{e(adresse("profil"))}">Abbrechen</a></div></form>')

    def profil_html(d: dict) -> str:
        """Reiter "Profil" (E10): Farben, Schriften, helles Logo auf --flaeche-Ton, dunkles auf dunklem Grund, dann
        jeder Abschnitt als Karte in der Reihenfolge der API; leere Karten laden zum Fragen ein."""
        sp = _dict(d.get("spiegel"))
        g = _dict(sp.get("gestalt"))
        stand = str(sp.get("stand") or "")
        # Lese-Hinweise der Marke.md ("Marke.md: akzent ungültig"), vom Abgleich am PC gemeldet
        hinweise = liste(_texte(d.get("profil_hinweise")), "warnung")
        firma = str(d.get("name") or d.get("mandant") or "")
        werte, ab = profil_quelle(d)
        teile = []
        if not g and not stand:
            teile.append(f'<p><b>{KEIN_PROFIL}</b></p>')
        else:
            quelle = {"akzent": g.get("akzent"), "zweitfarbe": g.get("flaeche"),
                      "grund": werte.get("grund"), "text": werte.get("text")}
            farben = "".join(farbfeld(n, quelle.get(k)) for k, n in _PROFIL_FARBEN)
            if farben:
                teile.append(f'<div class="farben-zeile">{farben}</div>')
            schrift = _dict(g.get("schriften"))
            teile.append(schrift_zeile(schrift.get("anzeige"), schrift.get("text"), firma))
            logos = []
            logo = str(g.get("logo") or "")
            if _BILD_DATEN.fullmatch(logo):
                logos.append(f'<div class="logo-hell-flaeche"><img class="marke-logo" src="{logo}" alt="Logo"></div>')
            dunkel = str(g.get("logo_dunkel") or "")
            if _BILD_DATEN.fullmatch(dunkel):
                logos.append(f'<div class="logo-dunkel-flaeche"><img class="marke-logo dunkel" src="{dunkel}" '
                             'alt="Logo für dunkle Flächen"></div>')
            if logos:
                teile.append(f'<div class="profil-logos">{"".join(logos)}</div>')
            if stand:
                teile.append(f'<p class="meta">Stand: {e(stand)}</p>')
        teile.append(spiegel_warnung(sp))
        teile.append(hinweise)
        karten = "".join(
            f'<section class="profil-karte"><h3>{e(n)}</h3>'
            + (f'<p>{absaetze(ab[n])}</p>' if isinstance(ab.get(n), str) and ab[n].strip()
               else f'<p class="leer">{NOCH_LEER}</p>') + "</section>"
            for n in abschnitt_namen(d, ab))
        return (f'<div class="marke-profil">{"".join(teile)}</div>'
                f'<div class="profil-karten">{karten}</div>'
                f'<p><a class="knopf sek" href="{SEITE}?bearbeiten=1">Profil bearbeiten</a></p>')

    # --- Chat ------------------------------------------------------------------------------

    LIVE_ZEICHEN = 600
    LIVE_SCHRITTE = 8
    KENNUNG = "Claudes Gedanken (zusammengefasst, englisch)"

    def _schritte(schritte) -> list[dict]:
        return [s for s in (schritte or []) if isinstance(s, dict)
                and isinstance(s.get("zeit"), str) and isinstance(s.get("text"), str)]

    def _quellen(quellen) -> list[dict]:
        return [q for q in (quellen if isinstance(quellen, list) else []) if isinstance(q, dict)
                and isinstance(q.get("titel"), str) and isinstance(q.get("url"), str)]

    def _schritt_liste(schritte: list[dict]) -> str:
        return ('<ol class="spur-schritte">'
                + "".join(f'<li><span class="zeit">{e(s["zeit"])}</span> {e(s["text"])}</li>' for s in schritte)
                + "</ol>") if schritte else ""

    def quelle_html(q: dict) -> str:
        """Nur http(s) wird ein Link (Review Focus 4); alles andere steht als Text da."""
        url, titel = q["url"], q["titel"].strip() or q["url"]
        art = _QUELLEN_ART.get(str(q.get("art") or ""), "")
        art = f' <span class="meta">{e(art)}</span>' if art else ""
        if url.startswith(("https://", "http://")):
            return (f'<li><a href="{e(url)}" rel="noopener noreferrer" target="_blank">{e(titel)}</a>{art}</li>')
        return f'<li>{e(titel)}{art} <span class="meta">{e(url)}</span></li>'

    def schritte_html(a: dict) -> str:
        """Eine Zeile "4 Schritte · Websuche · 2 Quellen", darin Schritte, Quellen und Gedanken (E10.4)."""
        schritte = _schritte(a.get("schritte"))
        quellen = _quellen(a.get("quellen"))
        denken = a.get("denken") if isinstance(a.get("denken"), str) else ""
        if not schritte and not quellen and not denken.strip():
            return ""
        zeile = []
        if schritte:
            zeile.append("1 Schritt" if len(schritte) == 1 else f"{len(schritte)} Schritte")
        if any(s["text"] == WEBSUCHE_SCHRITT for s in schritte):
            zeile.append("Websuche")
        if quellen:
            zeile.append("1 Quelle" if len(quellen) == 1 else f"{len(quellen)} Quellen")
        teile = [_schritt_liste(schritte)]
        if quellen:
            teile.append('<p class="meta">Quellen</p><ul class="quellen">'
                         + "".join(quelle_html(q) for q in quellen) + "</ul>")
        if denken.strip():
            teile.append(f'<p class="meta">{e(KENNUNG)}</p><pre class="spur-denken">{e(denken)}</pre>')
        return (f'<details class="schritte"><summary>{" · ".join(zeile) or "Gedanken"}</summary>'
                + "".join(teile) + "</details>")

    def live_html(l: dict) -> str:
        schritte = _schritte(l.get("schritte"))[-LIVE_SCHRITTE:]
        denken = l.get("denken") if isinstance(l.get("denken"), str) else ""
        ausschnitt = ("…" + denken[-LIVE_ZEICHEN:]) if len(denken) > LIVE_ZEICHEN else denken
        if not schritte and not ausschnitt.strip():
            return '<div class="spur-live"><p class="meta">Denkt nach …</p></div>'
        return ('<div class="spur-live"><p class="meta">Denkt nach …</p>' + _schritt_liste(schritte)
                + (f'<p class="meta">{e(KENNUNG)}</p><pre class="spur-denken">{e(ausschnitt)}</pre>'
                   if ausschnitt.strip() else "") + "</div>")

    def spur_html(a: dict) -> str:
        """Spur der Uebernahme und des Wissens-Laufs (gleiche Zeile wie die Chat-Runden)."""
        return schritte_html({"schritte": a.get("schritte"), "denken": a.get("denken")})

    def letzte_html(d: dict) -> str:
        """Ergebnis der letzten Uebernahme: ein Fehlschlag mit Grund, ein Erfolg nur mit Hinweisen.
        Waehrend eine Uebernahme laeuft, zaehlt nur deren Status."""
        z = d.get("letzte_uebernahme")
        if d.get("uebernahme") or not isinstance(z, dict):
            return ""
        hinweise = z.get("hinweise") if isinstance(z.get("hinweise"), list) else []
        antwort = str(z.get("antwort") or "")
        if z.get("status") == "fehler":
            return (f'<div class="systemblock"><p class="warnung">Übernehmen fehlgeschlagen: {e(antwort or "ohne Grund")}</p>'
                    + liste(hinweise, "meta") + spur_html(z) + "</div>")
        if hinweise or (z.get("status") == "fertig" and _schritte(z.get("schritte"))):
            return (f'<div class="systemblock"><p class="meta">Letzte Übernahme: {e(antwort)}</p>'
                    + liste(hinweise, "meta") + spur_html(z) + "</div>")
        return ""

    def wissen_zeile_html(d: dict) -> str:
        """Statuszeile "Firmenwissen" unter der Eingabe (E10.9), Einzelheiten eingeklappt. Ein wartender oder
        laufender Lauf laedt die Seite NICHT neu (Ruling R7, er dauert Minuten und verwarf sonst alle 5 s die
        Chat-Eingabe) - sein Stand kommt mit dem naechsten Laden ("Aktualisieren")."""
        w = d.get("wissen")
        if not isinstance(w, dict):
            return ""
        status = str(w.get("status") or "")
        neu_laden = f' <a href="{ZIEL}">{WISSEN_AKTUALISIEREN}</a>'
        hinweise = w.get("hinweise") if isinstance(w.get("hinweise"), list) else []
        zeilen = [z for z in str(w.get("antwort") or "").splitlines() if z.strip()]
        kopf = zeilen[0] if zeilen else ""
        if status == "offen":
            titel, inhalt = "wird aufgefrischt", f'<p class="meta marke-wissen-stand">{WISSEN_WARTET}.</p>'
        elif status == "in_arbeit":
            titel, inhalt = "wird aufgefrischt", (f'<p class="meta marke-wissen-stand">{WISSEN_LAEUFT}</p>'
                                                 + spur_html(w))
        elif status == "fehler":
            titel, inhalt = "Fehler", (f'<p class="warnung">Wissen nicht aktualisiert: {e(kopf or "ohne Grund")}</p>'
                                       + liste(hinweise, "meta") + spur_html(w))
        else:
            dateien = [z[2:] for z in zeilen[1:] if z.startswith("- ")]
            titel, inhalt = "aktuell", (f'<p class="meta">{e(kopf)}</p>' + liste(dateien, "wissen-dateien")
                                        + liste(hinweise, "meta") + spur_html(w))
        laeuft = neu_laden if status in ("offen", "in_arbeit") else ""
        return (f'<div class="marke-wissen wissen-zeile"><details><summary>Firmenwissen: {titel}</summary>'
                f'{inhalt}</details>{laeuft}</div>')

    def faehigkeiten_html(d: dict) -> str:
        f = _dict(d.get("faehigkeiten"))
        kann, nicht = _texte(f.get("kann")), _texte(f.get("nicht"))
        if not kann and not nicht:
            return ""
        return ('<details class="faehigkeiten"><summary>Was der Marken-Agent kann</summary>'
                + liste(kann, "kann")
                + (f'<p class="meta">Was er nicht kann:</p>{liste(nicht, "nicht")}' if nicht else "")
                + "</details>")

    def aenderung_html(a: dict, d: dict) -> str:
        """Karte "Geändert: Ton, Wörter" einer direkt uebernommenen Textaenderung (E10.5). Nur fuer direkt UND
        angenommen; ist das direkte Annehmen gescheitert (offen), zeigt die Runde die Vorschlagskarte."""
        z = a.get("aenderung")
        if not isinstance(z, dict) or z.get("direkt") is not True or z.get("status") != "angenommen":
            return ""
        felder = [x for x in z.get("aenderungen") or [] if isinstance(x, dict) and isinstance(x.get("feld"), str)] \
            if isinstance(z.get("aenderungen"), list) else []

        def text(wert) -> str:
            t = str(wert or "")
            return absaetze(t) if t.strip() else '<i>leer</i>'
        einzeln = "".join(
            f'<details><summary>{e(x["feld"])}</summary>'
            f'<p class="meta">vorher</p><div class="vorher">{text(x.get("vorher"))}</div>'
            f'<p class="meta">nachher</p><div class="nachher">{text(x.get("nachher"))}</div></details>'
            for x in felder)
        namen = ", ".join(x["feld"] for x in felder)
        vid = _uuid_oder_none(z.get("vid"))
        knopf = (f'<form method="post" action="/marketing/marke/rueckgaengig" class="aktion">{csrf_feld()}'
                 f'<input type="hidden" name="vorschlag" value="{e(vid)}">'
                 '<button type="submit">Rückgängig</button></form>') if z.get("rueckgaengig_moeglich") and vid else ""
        if knopf and (d.get("uebernahme") or d.get("laeuft")):    # der Agent arbeitet: erst danach (Review)
            knopf = '<p class="meta">Rückgängig geht, sobald der Agent fertig ist.</p>'
        if z.get("rueckgaengig_gemacht") is True:      # die API kennt einen Gegenvorschlag zu dieser Aenderung
            knopf = '<p class="meta">Rückgängig gemacht</p>'
        return (f'<div class="diff-karte"><p><b>Geändert{": " + e(namen) if namen else ""}</b></p>'
                f'{einzeln}{knopf}</div>')

    def vorschlag_html(d: dict, fmt: str, alle: bool) -> str:
        v = d.get("vorschlag")
        if not isinstance(v, dict) or not _uuid_oder_none(v.get("id")):
            return ""
        vid = str(v["id"])
        w = _dict(v.get("vorschlag"))
        farben = "".join(farbfeld(n, w.get(k)) for k, n in _VORSCHLAG_FARBEN)
        schrift = schrift_zeile(w.get("schrift_anzeige"), w.get("schrift_text"),
                                str(d.get("name") or d.get("mandant") or ""))
        logo = logo_fassungen_html(w) or (f'<p>Logo: {e(str(w["logo"]))}</p>' if w.get("logo") else "")
        abschnitte = "".join(
            f'<h4>{e(str(n))}</h4><p>{absaetze(t)}</p>'
            for n, t in _dict(w.get("abschnitte")).items() if isinstance(t, str) and t.strip())
        umschalter = " &middot; ".join(
            (f'<b>{t}</b>' if k == fmt else f'<a href="{e(adresse("chat", alle, k, "#vorschlag"))}">{t}</a>')
            for k, t in FORMATE.items())
        # Ein offener Gegenvorschlag (API: ist_rueckgaengig) ist das Rueckgaengig einer Aenderung, die noch
        # uebernommen wird (z. B. nach gescheiterter Direktannahme) - sonst gleiche Karte.
        titel = "Rückgängig wird übernommen" if v.get("ist_rueckgaengig") is True else "Vorschlag"
        return (f'<div class="vorschlag-karte" id="vorschlag"><h3>{titel}</h3>'
                f'<p class="meta">Vorschau als {umschalter}</p>'
                f'<div class="pult"><div class="pult-links"><div class="marke-profil">'
                f'<div class="farben-zeile">{farben}</div>{schrift}{logo}{abschnitte}</div>'
                f'<form method="post" action="/marketing/marke/uebernehmen" class="aktion">{csrf_feld()}'
                f'<input type="hidden" name="vorschlag" value="{e(vid)}">'
                f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
                f'Ja, dieses Profil übernehmen</label>'
                f'<button class="primaer" type="submit">Übernehmen</button></form>'
                f'<form method="post" action="/marketing/marke/verwerfen" class="aktion">{csrf_feld()}'
                f'<input type="hidden" name="vorschlag" value="{e(vid)}">'
                f'<button type="submit">Verwerfen</button></form></div>'
                f'<div class="pult-rechts"><iframe class="vorschau" sandbox title="Vorschau" '
                f'src="{e(f"/marketing/marke/vorschau?format={fmt}&vorschlag={vid}")}"></iframe></div></div></div>')

    def offene_vid(d: dict) -> str | None:
        v = d.get("vorschlag")
        return _uuid_oder_none(v.get("id")) if isinstance(v, dict) else None

    def runde_html(a: dict, d: dict, *, live: dict | None = None, karte: str = "") -> str:
        """Eine Runde (E10.3–6): Du-Blase rechts (bei einer Bearbeitung die Systemzeile), Agent-Blase links mit
        Schritten, dann die Aenderungskarte oder die Vorschlagskarte dieser Runde. `live`: die laufende Spur."""
        wann = e(_wann(ui, a.get("erstellt_am"))) if a.get("erstellt_am") else ""
        if str(a.get("art") or "") == "bearbeitung":
            kopf = f'<p class="systemzeile">Profil von Hand bearbeitet{" · " + wann if wann else ""}</p>'
        else:
            kopf = (f'<div class="blase-du"><span class="blase-kopf">Du{" · " + wann if wann else ""}</span>'
                    f'<p>{e(str(a.get("nachricht") or ""))}</p></div>')
        status = str(a.get("status") or "")
        laeuft = status in ("offen", "in_arbeit")
        antwort = str(a.get("antwort") or "")
        if live is not None:
            inhalt = live_html(live)
        elif antwort:
            inhalt = f"<p>{e(antwort)}</p>"
        else:
            inhalt = f'<p><i>{e(_STATUS.get(status, ""))}</i></p>' if _STATUS.get(status) else ""
        hinweise = liste(a.get("hinweise") if isinstance(a.get("hinweise"), list) else [], "meta")
        schritte = "" if laeuft else schritte_html(a)
        letzte = _schritte(a.get("schritte"))
        uhr = f" · {e(letzte[-1]['zeit'][:5])}" if letzte and not laeuft else ""
        agent = (f'<div class="blase-agent"><span class="blase-kopf">Agent{uhr}</span>{inhalt}{hinweise}{schritte}</div>'
                 if (inhalt or hinweise or schritte) else "")
        z = a.get("aenderung")
        rest = aenderung_html(a, d)
        if not rest and not karte and isinstance(z, dict):      # verworfen/ersetzt auch bei direkt (Review)
            wort = _VORSCHLAG_STATUS.get(str(z.get("status") or ""))
            rest = f'<p class="systemzeile">{wort}</p>' if wort else ""
        return f'<div class="chat-runde">{kopf}{agent}{rest}{karte}</div>'

    def chat_html(d: dict, alle: bool, fmt: str = "mail") -> str:
        """Reiter "Chat" bis vor die Eingabe (E10.1–7): Faehigkeiten, Verlauf mit dem Aeltesten oben (bei mehr
        Runden als gezeigt oben "Ältere anzeigen"), die laufende Runde mit "Denkt nach …", Uebernahme-Status."""
        runden = [a for a in d.get("auftraege") or [] if isinstance(a, dict)] \
            if isinstance(d.get("auftraege"), list) else []
        im_chat = bool(d.get("laeuft") or d.get("uebernahme"))
        laufend = d.get("laufend") if isinstance(d.get("laufend"), dict) and im_chat else None
        if laufend is not None and laufend.get("art") == "wissen":
            laufend = None
        laufende = next((i for i in range(len(runden) - 1, -1, -1)
                         if str(runden[i].get("status") or "") in ("offen", "in_arbeit")), None)
        live_in_runde = (laufend is not None and laufende is not None
                         and laufend.get("art") in ("chat", "bearbeitung"))
        vid = offene_vid(d)
        karte = vorschlag_html(d, fmt, alle)
        teile = []
        gesamt = d.get("runden_gesamt")
        if not alle and isinstance(gesamt, int) and gesamt > len(runden):
            teile.append(f'<p class="aeltere"><a href="{e(adresse("chat", True, None, "#ende"))}">Ältere anzeigen'
                         f'</a> <span class="meta">({gesamt - len(runden)} weitere)</span></p>')
        karte_gesetzt = False
        for i, a in enumerate(runden):
            hier = ""
            z = a.get("aenderung")
            direkt_fertig = isinstance(z, dict) and z.get("direkt") is True and z.get("status") == "angenommen"
            if karte and not karte_gesetzt and vid and not direkt_fertig and _uuid_oder_none(a.get("vorschlag")) == vid:
                hier, karte_gesetzt = karte, True
            teile.append(runde_html(a, d, live=laufend if live_in_runde and i == laufende else None, karte=hier))
        if not runden:
            teile.append('<p class="meta">Noch keine Nachrichten.</p>')
        if karte and not karte_gesetzt:             # Runde nicht (mehr) im Verlauf: die Karte geht nie verloren
            teile.append(f'<div class="chat-runde">{karte}</div>')
        if laufend is not None and not live_in_runde:
            teile.append(live_html(laufend))
        if d.get("uebernahme"):
            alter = _alter_s(d.get("uebernahme_seit"))
            wartet = alter is not None and alter > PC_WARTET_NACH_S
            teile.append(f'<p class="status-zeile">{PC_LAEUFT if wartet else "Wird übernommen …"}</p>')
        teile.append(letzte_html(d))
        return faehigkeiten_html(d) + f'<div class="chat-verlauf">{"".join(teile)}</div>'

    def eingabe_html(d: dict) -> str:
        """Die feste Eingabe unten (E10.8, CSS sticky). Das Sprungziel #ende steht NICHT hier, sondern als leeres
        Element ganz unten (ENDE): ein Sprung auf ein klebendes Element landet dort, wo es gerade klebt, nicht am
        Ende des Verlaufs (gemessen mit Playwright, 20.10.2026)."""
        if d.get("laeuft"):
            return ('<div class="chat-eingabe"><p class="meta">Der Marken-Agent arbeitet gerade – die Seite '
                    'lädt sich selbst neu. Eine neue Nachricht geht erst danach.</p></div>')
        return (f'<form method="post" action="/marketing/marke/senden" enctype="multipart/form-data" '
                f'class="chat-eingabe">{csrf_feld()}'
                f'<textarea aria-label="Nachricht an den Marken-Agenten" name="nachricht" rows="3" maxlength="{NACHRICHT_MAX}" required '
                f'placeholder="Frag den Marken-Agenten – z. B. Mach den Ton wärmer. Unsere Webseite: https://…">'
                f'</textarea><div class="chat-eingabe-zeile">'
                f'<label class="meta">Dateien (Logo, Bilder, Dokumente; höchstens {ANHAENGE_MAX}) '
                f'<input type="file" name="datei" multiple></label>'
                f'<button class="primaer" type="submit">Senden</button></div></form>')

    @ui._gesichert_seite
    async def marke(request):
        fmt = request.query_params.get("format", "mail")
        fmt = fmt if fmt in FORMATE else "mail"
        reiter = "profil" if request.query_params.get("reiter") == "profil" else "chat"
        alle = request.query_params.get("alle") == "1"
        try:
            m, liste_ = await marketing_mandant.firma(request)
            pfad = f"/marke?mandant={urllib.parse.quote(m)}" + ("&alle=1" if alle else "")
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", pfad)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not isinstance(d, dict):
            return fehler(marketing_pult.PultFehler("unbekannt", "Antwort ohne Marke"))
        kopf = ('<link rel="stylesheet" href="/marketing/schrift/schriften.css">'
                + marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste_, SEITE))
        if request.query_params.get("bearbeiten") == "1":
            rumpf = kopf + bearbeiten_html(d, m) + f'<p><a href="{e(adresse("profil"))}">Zurück zur Marke</a></p>'
            antwort = ui._seite("Marke", rumpf)
            antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'", bilddaten=True, schriften=True)
            return antwort
        nav = ui_muster.reiter(list(REITER), reiter,
                               lambda k: adresse(k, anker="#ende") if k == "chat" else adresse(k))
        # Der Refresh zielt immer auf eine NEUE Adresse (stand=<Sekunden>): unterscheidet sich das Ziel nur im Anker,
        # ist es nach HTML-Spec nur ein Sprung ohne Neuladen (Firefox/Safari, Review Task 5).
        stand = int(time.time())
        if reiter == "profil":
            rumpf = (kopf + nav + '<p class="meta">Das Markenprofil bestimmt Farben, Schriften, Logo und Texte neuer '
                     'Newsletter. Ändern geht im Chat oder mit „Profil bearbeiten“.</p>' + profil_html(d))
            ziel = adresse("profil", stand=stand)
        else:
            rumpf = kopf + nav + chat_html(d, alle, fmt) + eingabe_html(d) + wissen_zeile_html(d) + ENDE
            ziel = adresse("chat", alle, fmt if fmt != "mail" else None, "#ende", stand)
        # Neu laden nur fuer Chat, Bearbeitung und Uebernahme; ein Wissens-Lauf nie (Ruling R7)
        arbeitet = bool(d.get("laeuft") or d.get("uebernahme"))
        antwort = ui._seite("Marke", rumpf, refresh=(REFRESH_S, ziel) if arbeitet else None)
        antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'", bilddaten=True, schriften=True)
        return antwort

    # --- Vorschau-Proxy ---------------------------------------------------------------------

    @ui._gesichert_seite
    async def vorschau(request):
        fmt = request.query_params.get("format", "mail")
        fmt = fmt if fmt in FORMATE else "mail"
        try:
            if "vorschlag" in request.query_params:
                # Der Rahmen zeigt genau den Vorschlag, den die Karte daneben zeigt - auch wenn
                # inzwischen ein neuerer offen ist.
                vid = _uuid_oder_none(request.query_params["vorschlag"])
                if not vid:
                    return _gerahmt("<p>Kein Vorschlag offen.</p>", status=404)
                m, _liste = await marketing_mandant.firma(request)
            else:
                m, _liste = await marketing_mandant.firma(request)
                d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/marke?mandant={urllib.parse.quote(m)}")
                v = d.get("vorschlag") if isinstance(d, dict) else None
                vid = _uuid_oder_none(v.get("id")) if isinstance(v, dict) else None
            if not vid:
                return _gerahmt("<p>Kein Vorschlag offen.</p>", status=404)
            # Nur ein Vorschlag der gewaehlten Firma (Minor 4): die API vergleicht und sagt sonst 404
            q = {"mandant": m, "format": fmt}
            if (basis := ui_editor.bild_basis()):
                q["bild_basis"] = basis
            inhalt, typ = await run_in_threadpool(
                marketing_pult.anfrage, "GET", f"/marke/vorschlaege/{vid}/vorschau?{urllib.parse.urlencode(q)}",
                roh=True)
        except marketing_pult.PultFehler as f:
            if f.art == "abgelehnt":
                return _gerahmt(f"<p>Vorschau nicht möglich: {e(f.grund)}</p>", status=422)
            if f.art == "nicht_verbunden":
                return _gerahmt("<p>Marketing nicht verbunden.</p>", status=503)
            return _gerahmt("<p>Marketing gerade nicht erreichbar.</p>", status=503)
        return _gerahmt(inhalt, typ)

    # --- Senden (Nachricht + Dateien) ---------------------------------------------------------

    @ui._gesichert_seite
    async def senden(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        nachricht = str(form.get("nachricht") or "")
        if not nachricht.strip():
            return abgewiesen(422, "Ohne Nachricht kein Auftrag.")
        if len(nachricht) > NACHRICHT_MAX:
            return abgewiesen(422, f"Die Nachricht darf höchstens {NACHRICHT_MAX} Zeichen haben.")
        dateien = [d for d in form.getlist("datei") if getattr(d, "filename", "")]
        if len(dateien) > ANHAENGE_MAX:
            return abgewiesen(422, f"Höchstens {ANHAENGE_MAX} Dateien je Nachricht.")
        try:
            m, _liste = await marketing_mandant.firma(request)
        except marketing_pult.PultFehler as f:
            return fehler(f)

        abgelegt: list[str] = []

        async def aufraeumen():
            for name in abgelegt:
                await run_in_threadpool(ui.medien_datei_loeschen, name)

        for datei in dateien:
            basis, groesse, abgelehnt = await ui_editor.anhang_speichern(ui, datei)
            if abgelehnt:
                await aufraeumen()
                return abgewiesen(*abgelehnt)
            abgelegt.append(basis)
            # Ohne Zeile gilt eine Datei als Gemeinsam und waere fuer jede Firma sichtbar:
            # sie gehoert der gewaehlten Firma. Gelingt das nicht, bleibt keine Datei liegen.
            try:
                await run_in_threadpool(marketing_pult.anfrage, "POST", "/medien/zuordnung",
                                        {"dateiname": basis, "mandant": m})
            except marketing_pult.PultFehler as f:
                await aufraeumen()
                if f.art == "nicht_verbunden":
                    return fehler(f)
                return ui._fehlerseite(503, "Anhang nicht abgelegt",
                                       "Der Anhang konnte nicht der Firma zugeordnet werden - bitte erneut versuchen.")
            ui.LOG.info("Medien (Marke-Anhang): %s abgelegt (%d Byte)", basis, groesse)
        anhaenge = [{"name": n, "art": ui.server.medien.anhang_art(n)} for n in abgelegt]
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/marke/chat",
                                    {"mandant": m, "nachricht": nachricht, "kontext": {"anhaenge": anhaenge}})
        except marketing_pult.PultFehler as f:
            await aufraeumen()           # abgelehnt (z. B. es laeuft schon einer): keine Kopien anhaeufen
            return fehler(f)
        return RedirectResponse(ZIEL, status_code=303)

    # --- Uebernehmen / Verwerfen / Rueckgaengig ---------------------------------------------------

    def vorschlag_aktion(aktion: str):
        @ui._gesichert_seite
        async def handler(request):
            form = await request.form()
            if not ui._csrf_ok(form):
                return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
            vid = _uuid_oder_none(form.get("vorschlag"))
            if not vid:
                return abgewiesen(422, "Welcher Vorschlag gemeint ist, fehlt. Seite neu laden.")
            if aktion == "uebernehmen" and str(form.get("bestaetigt") or "") != "ja":
                return abgewiesen(422, "Bitte bestätige das Übernehmen mit dem Haken. Nichts wurde geändert.")
            try:
                # Die gerade gewaehlte Firma: ein Tab von vor dem Firmenwechsel handelt so nie am
                # Vorschlag einer anderen Firma (Minor 4, die DB vergleicht). Rueckgaengig (E7): jede
                # Ablehnung der DB (neuere Aenderung, Assistent arbeitet, zu gross) kommt als Meldung an.
                m, _liste = await marketing_mandant.firma(request)
                await run_in_threadpool(marketing_pult.anfrage, "POST", f"/marke/vorschlaege/{vid}/{aktion}",
                                        {"von": ui._ui_akteur(request), "mandant": m})
            except marketing_pult.PultFehler as f:
                return fehler(f)
            return RedirectResponse(ZIEL, status_code=303)
        return handler

    # Rueckgaengig (E7): wie Uebernehmen/Verwerfen, ohne Haken - die API legt den Gegenvorschlag an
    rueckgaengig = vorschlag_aktion("rueckgaengig")

    @ui._gesichert_seite
    async def bearbeiten(request):
        """Formular -> Marken-Agent (Art 'bearbeitung'). Es gibt keinen Schreibweg an ihm vorbei (Spec §2)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if any(_ALTES_FELD.fullmatch(k) for k in form.keys()):
            return abgewiesen(422, "Das Formular ist veraltet. Nichts wurde geändert – bitte Seite neu laden.")
        formular = {k: str(form.get(k) or "").strip() for k, _ in FORM_FARBEN}
        formular.update({k: str(form.get(k) or "").strip() for k in ("schrift_anzeige", "schrift_text", "webseite")})
        formular["abschnitte"] = {k[len(FELD_ABSCHNITT):]: str(form.get(k) or "").replace("\r\n", "\n").strip()
                                  for k in form.keys() if k.startswith(FELD_ABSCHNITT)}
        zu_lang = (any(len(formular[k]) > FARBE_MAX for k, _ in FORM_FARBEN)
                   or any(len(formular[k]) > SCHRIFT_MAX for k in ("schrift_anzeige", "schrift_text"))
                   or len(formular["webseite"]) > WEBSEITE_MAX
                   or len(formular["abschnitte"]) > ABSCHNITTE_MAX
                   or any(len(n) > ABSCHNITT_NAME_MAX or len(t) > ABSCHNITT_MAX
                          for n, t in formular["abschnitte"].items()))
        if zu_lang:
            return abgewiesen(422, "Ein Feld ist zu lang. Nichts wurde geändert.")
        try:
            m, _liste = await marketing_mandant.firma(request)
            if str(form.get("mandant") or "") != m:      # Tab von vor dem Firmenwechsel (wie vorschlag_aktion)
                return abgewiesen(422, "Die Firma wurde gewechselt. Nichts wurde geändert – bitte Seite neu laden.")
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/marke/bearbeiten",
                                    {"mandant": m, "formular": formular})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(ZIEL, status_code=303)

    # --- Alte Layout-Pfade -------------------------------------------------------------------------

    async def zur_marke(request):
        return RedirectResponse(SEITE, status_code=303)

    alt = ui._gesichert_seite(zur_marke)
    alle_methoden = ["GET", "POST"]
    return [
        Route(SEITE, marke),
        Route("/marketing/marke/vorschau", vorschau),
        Route("/marketing/marke/senden", senden, methods=["POST"]),
        Route("/marketing/marke/uebernehmen", vorschlag_aktion("uebernehmen"), methods=["POST"]),
        Route("/marketing/marke/verwerfen", vorschlag_aktion("verwerfen"), methods=["POST"]),
        Route("/marketing/marke/rueckgaengig", rueckgaengig, methods=["POST"]),
        Route("/marketing/marke/bearbeiten", bearbeiten, methods=["POST"]),
        Route("/marketing/layout/{name}", alt, methods=alle_methoden),
        Route("/marketing/layout/{name}/speichern", alt, methods=alle_methoden),
        Route("/marketing/layout/{name}/standard", alt, methods=alle_methoden),
        Route("/marketing/layout-vorschau", alt, methods=alle_methoden),
        Route("/marketing/layout-bild/{name}", alt, methods=alle_methoden),
    ]
