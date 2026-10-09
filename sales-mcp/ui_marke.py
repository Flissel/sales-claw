"""Seite "Marke" im Marketing-Bereich (Spec 2026-10-07-marke-per-chat-design.md §4.1).
/marketing/layouts zeigt das Markenprofil der gewaehlten Firma (Spiegel), den Chat mit dem
Marken-Agenten, den offenen Vorschlag samt Vorschau und "Uebernehmen"/"Verwerfen".

Wie der Rest von sales-ui ohne JavaScript: Formulare, Verweise (Mail/Handy) und ein
Meta-Refresh alle 5 s, solange ein Chat-, Bearbeitungs- oder Uebernahme-Auftrag laeuft (ein Wissens-Lauf
nie: Link "Aktualisieren"). Daten kommen nur ueber marketing_pult;
jeder Aufruf laeuft im Threadpool. Der alte Regler-Editor entfaellt, seine Pfade leiten hierher.

Uploads (Plan-Ruling R2): Bilder und Dokumente gehen durch dieselbe Ablage und Pruefung wie
der Editor-Anhang (ui_editor.anhang_speichern), gehoeren aber der gewaehlten Firma
(POST /medien/zuordnung); scheitert die Zuordnung, wird die Datei wieder geloescht."""
from __future__ import annotations

import re
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

SEITE = "/marketing/layouts"
NACHRICHT_MAX = 2000
PC_WARTET_NACH_S = 60                # danach: "sobald der PC läuft"
KURZ_ZEILEN, KURZ_ZEICHEN = 2, 160
ANHAENGE_MAX = 5                     # wie ANHAENGE_MAX der Marketing-API (kontext.anhaenge)
REFRESH_S = 5
FORMATE = {"mail": "Mail", "handy": "Handy"}
PC_LAEUFT = "Wird übernommen, sobald der PC läuft"
WISSEN_WARTET = "Wissen wird aktualisiert, sobald der PC läuft"
WISSEN_LAEUFT = "Wissen wird aktualisiert …"
WISSEN_AKTUALISIEREN = "Aktualisieren"
KEIN_PROFIL = "Noch kein Branding – erzähl mir von der Firma"
NEUERES_PROFIL = "Inzwischen gibt es ein neueres Profil – bitte neu laden"
_FARBE = re.compile(r"#[0-9A-Fa-f]{6}")
LOGO_BASE64_MAX = 210_000           # Logo <= 140 KB als data-URL = rund 187 000 Zeichen, plus Luft
_BILD_DATEN = re.compile(rf"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]{{1,{LOGO_BASE64_MAX}}}")
_FARBEN = (("akzent", "Akzent"), ("flaeche", "Fläche"))
_VORSCHLAG_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Zweitfarbe"), ("grund", "Grund"), ("text", "Text"))
ABSCHNITTE = ("Wer wir sind", "Zielgruppe", "Ton", "Angebote", "Do & Don'ts", "Fakten und Zahlen", "Bildstil")
FORM_FARBEN = (("akzent", "Akzent"), ("zweitfarbe", "Zweitfarbe"), ("grund", "Grund"), ("text", "Text"))
FARBE_MAX, SCHRIFT_MAX, WEBSEITE_MAX, ABSCHNITT_MAX = 20, 40, 300, 8000   # wie api/marke.FORMULAR_GRENZEN
_MEDIENNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(?:png|jpe?g)")
_STATUS = {"offen": "wartet (PC muss laufen)", "in_arbeit": "wird bearbeitet", "fehler": "fehlgeschlagen"}


def _uuid_oder_none(wert) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except ValueError:
        return None


def _medienname(wert) -> str | None:
    w = str(wert or "")
    w = w[len("anhang:"):] if w.startswith("anhang:") else w
    return w if _MEDIENNAME.fullmatch(w) else None


def _kurz(text) -> str:
    """Die ersten Zeilen eines Abschnitts, auf KURZ_ZEICHEN gekuerzt."""
    zeilen = [z.strip() for z in str(text or "").splitlines() if z.strip()][:KURZ_ZEILEN]
    t = "\n".join(zeilen)
    return t if len(t) <= KURZ_ZEICHEN else t[:KURZ_ZEICHEN - 1].rstrip() + "…"


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


def routen(ui) -> list:
    from ui_marketing import _gerahmt, _wann
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", f'{e(f.grund)}<p><a href="{SEITE}">Zur Marke</a></p>')
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def abgewiesen(status: int, text: str):
        return ui._fehlerseite(status, "Nicht möglich", f'{e(text)}<p><a href="{SEITE}">Zur Marke</a></p>')

    def csrf_feld() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def farbfeld(name: str, wert) -> str:
        w = str(wert or "")
        if not _FARBE.fullmatch(w):
            return ""
        return (f'<span class="farbe"><span class="farbfeld" style="background:{w}"></span>'
                f'{e(name)} {e(w)}</span>')

    # --- Seite -----------------------------------------------------------------------------

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
        p = p if p is not None else (d.get("aktuell") if isinstance(d.get("aktuell"), dict) else {})
        werte = p.get("werte") if isinstance(p.get("werte"), dict) else {}
        ab = p.get("abschnitte") if isinstance(p.get("abschnitte"), dict) else {}
        return werte, ab

    def bearbeiten_html(d: dict, mandant: str) -> str:
        if d.get("laeuft") or d.get("uebernahme"):
            return '<p class="meta">Der Marken-Agent arbeitet gerade – bearbeiten geht danach.</p>'
        offen = d.get("vorschlag") if isinstance(d.get("vorschlag"), dict) else None
        warnung = (f'<p class="warnung">Es gibt einen offenen Vorschlag vom {e(_wann(ui, offen.get("erstellt_am")))}'
                   ' – wenn du das Formular abschickst, ersetzt es ihn. Übernimm oder verwirf ihn vorher, '
                   'wenn du ihn behalten willst.</p>') if offen else ""
        werte, ab = profil_quelle(d)
        sp = d.get("spiegel") if isinstance(d.get("spiegel"), dict) else {}
        g = sp.get("gestalt") if isinstance(sp.get("gestalt"), dict) else {}
        sw = g.get("schriften") if isinstance(g.get("schriften"), dict) else {}
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
        texte = "".join(f'<label>{e(n)} <textarea name="ab{i}" rows="4" maxlength="{ABSCHNITT_MAX}">'
                        f'{e(str(ab.get(n) or ""))}</textarea></label>' for i, n in enumerate(ABSCHNITTE))
        return (warnung + '<h2>Profil bearbeiten</h2><p class="meta">Der Marken-Agent übernimmt deine Angaben wörtlich und '
                'korrigiert nur Ungültiges (mit Hinweis). Danach Vorschau und Übernehmen wie gewohnt.</p>'
                f'<form method="post" action="/marketing/marke/bearbeiten" class="pult-felder marke-bearbeiten">'
                f'{csrf_feld()}<input type="hidden" name="mandant" value="{e(mandant)}">'
                f'<fieldset><legend>Farben</legend>{farben}</fieldset>'
                f'<fieldset><legend>Schriften</legend>{auswahl("schrift_anzeige", "Überschrift")}'
                f'{auswahl("schrift_text", "Text")}</fieldset>'
                f'<label>Webseite <input name="webseite" type="url" value="{e(wert("webseite"))}" '
                f'maxlength="{WEBSEITE_MAX}" placeholder="https://…"></label>{texte}'
                f'<div class="aktionen"><button class="primaer" type="submit">An den Agenten geben</button> '
                f'<a href="{SEITE}">Abbrechen</a></div></form>')

    def profil_html(d: dict) -> str:
        sp = d.get("spiegel") if isinstance(d.get("spiegel"), dict) else {}
        g = sp.get("gestalt") if isinstance(sp.get("gestalt"), dict) else {}
        stand = str(sp.get("stand") or "")
        # Lese-Hinweise der Marke.md ("Marke.md: akzent ungültig"), vom Abgleich am PC gemeldet
        hinweise = liste(d.get("profil_hinweise") if isinstance(d.get("profil_hinweise"), list) else [],
                         "warnung")
        if not g and not stand:
            return (f'<div class="marke-profil"><p><b>{KEIN_PROFIL}</b></p>'
                    f'{spiegel_warnung(sp)}{hinweise}</div>')
        teile = []
        firma = str(d.get("name") or d.get("mandant") or "")
        werte, ab = profil_quelle(d)
        farben = ("".join(farbfeld(n, g.get(k)) for k, n in _FARBEN)
                  + "".join(farbfeld(n, werte.get(k)) for k, n in (("grund", "Grund"), ("text", "Text"))))
        if farben:
            teile.append(f'<div class="farben-zeile">{farben}</div>')
        schrift = g.get("schriften") if isinstance(g.get("schriften"), dict) else {}
        teile.append(schrift_zeile(schrift.get("anzeige"), schrift.get("text"), firma))
        logo = str(g.get("logo") or "")
        if _BILD_DATEN.fullmatch(logo):
            teile.append(f'<p><img class="marke-logo" src="{logo}" alt="Logo"></p>')
        dunkel = str(g.get("logo_dunkel") or "")
        if _BILD_DATEN.fullmatch(dunkel):
            teile.append(f'<p><img class="marke-logo dunkel" src="{dunkel}" alt="Logo für dunkle Flächen"></p>')
        for titel in ("Ton", "Zielgruppe"):
            kurz = _kurz(ab.get(titel))
            if kurz:
                teile.append(f'<p class="kurz"><b>{titel}:</b> {e(kurz).replace(chr(10), "<br>")}</p>')
        if stand:
            teile.append(f'<p class="meta">Stand: {e(stand)}</p>')
        teile.append(spiegel_warnung(sp))
        teile.append(hinweise)
        return f'<div class="marke-profil">{"".join(teile)}</div>'

    LIVE_ZEICHEN = 600
    LIVE_SCHRITTE = 8
    KENNUNG = "Claudes Gedanken (zusammengefasst, englisch)"

    def _schritte(schritte) -> list[dict]:
        return [s for s in (schritte or []) if isinstance(s, dict)
                and isinstance(s.get("zeit"), str) and isinstance(s.get("text"), str)]

    def _schritt_liste(schritte: list[dict]) -> str:
        return ('<ol class="spur-schritte">'
                + "".join(f'<li><span class="zeit">{e(s["zeit"])}</span> {e(s["text"])}</li>' for s in schritte)
                + "</ol>") if schritte else ""

    def spur_html(a: dict, offen: bool = False) -> str:
        schritte = _schritte(a.get("schritte"))
        denken = a.get("denken") if isinstance(a.get("denken"), str) else ""
        if not schritte and not denken.strip():
            return ""
        teile = [_schritt_liste(schritte)]
        if denken.strip():
            teile.append(f'<p class="meta">{e(KENNUNG)}</p><pre class="spur-denken">{e(denken)}</pre>')
        return (f'<details class="spur"{" open" if offen else ""}><summary>Gedanken &amp; Schritte</summary>'
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

    def laufend_html(d: dict) -> str:
        """Live-Spur im Chat-Bereich. Der Wissens-Lauf hat seine eigene Anzeige (wissen_html)."""
        l = d.get("laufend")
        if not isinstance(l, dict) or l.get("art") == "wissen":
            return ""
        return live_html(l)

    def letzte_html(d: dict) -> str:
        """Ergebnis der letzten Uebernahme: ein Fehlschlag mit Grund, ein Erfolg nur mit Hinweisen.
        Waehrend eine Uebernahme laeuft, zaehlt nur deren Status."""
        z = d.get("letzte_uebernahme")
        if d.get("uebernahme") or not isinstance(z, dict):
            return ""
        hinweise = z.get("hinweise") if isinstance(z.get("hinweise"), list) else []
        antwort = str(z.get("antwort") or "")
        if z.get("status") == "fehler":
            return (f'<p class="warnung">Übernehmen fehlgeschlagen: {e(antwort or "ohne Grund")}</p>'
                    + liste(hinweise, "meta") + spur_html(z))
        if hinweise or (z.get("status") == "fertig" and _schritte(z.get("schritte"))):
            return (f'<p class="meta">Letzte Übernahme: {e(antwort)}</p>' + liste(hinweise, "meta")
                    + spur_html(z))
        return ""

    def wissen_html(d: dict) -> str:
        """Rowboat-Lauf nach der Uebernahme: Ergebnis mit Dateiliste, Hinweisen, Denken und Schritten. Ein
        wartender oder laufender Lauf laedt die Seite NICHT neu (Ruling R7, er dauert Minuten und verwarf sonst
        alle 5 s die Chat-Eingabe) - sein Stand kommt mit dem naechsten Laden ("Aktualisieren")."""
        w = d.get("wissen")
        if not isinstance(w, dict):
            return ""
        status = str(w.get("status") or "")
        neu_laden = f' <a href="{SEITE}">{WISSEN_AKTUALISIEREN}</a>'
        if status == "offen":
            return f'<p class="meta marke-wissen-stand">{WISSEN_WARTET}.{neu_laden}</p>'
        if status == "in_arbeit":
            return (f'<p class="meta marke-wissen-stand">{WISSEN_LAEUFT}{neu_laden}</p>'
                    + spur_html(w))
        zeilen = [z for z in str(w.get("antwort") or "").splitlines() if z.strip()]
        kopf = zeilen[0] if zeilen else ""
        hinweise = w.get("hinweise") if isinstance(w.get("hinweise"), list) else []
        if status == "fehler":
            return (f'<p class="warnung">Wissen nicht aktualisiert: {e(kopf or "ohne Grund")}</p>'
                    + liste(hinweise, "meta") + spur_html(w))
        dateien = [z[2:] for z in zeilen[1:] if z.startswith("- ")]
        return (f'<div class="marke-wissen"><p class="meta">{e(kopf)}</p>' + liste(dateien, "wissen-dateien")
                + liste(hinweise, "meta") + spur_html(w) + "</div>")

    def chat_html(d: dict) -> str:
        runden = []
        for a in d.get("auftraege") or []:
            if not isinstance(a, dict):
                continue
            antwort = str(a.get("antwort") or "")
            if not antwort:
                antwort = _STATUS.get(str(a.get("status") or ""), "")
                antwort = f'<i>{e(antwort)}</i>' if antwort else ""
            else:
                antwort = e(antwort)
            hinweise = "".join(f"<li>{e(str(h))}</li>" for h in a.get("hinweise") or [])
            runden.append(f'<div class="chat-runde"><p class="chat-du">{e(str(a.get("nachricht") or ""))}</p>'
                          + (f'<p class="chat-agent">{antwort}</p>' if antwort else "")
                          + (f'<ul class="meta">{hinweise}</ul>' if hinweise else "")
                          + ("" if str(a.get("status") or "") in ("offen", "in_arbeit") else spur_html(a))
                          + "</div>")
        leer = '<p class="meta">Noch keine Nachrichten.</p>'
        return f'<div class="marke-chat">{"".join(runden) or leer}</div>'

    def formular_html(d: dict) -> str:
        if d.get("laeuft"):
            return ('<p class="meta">Der Marken-Agent arbeitet gerade – die Seite lädt sich selbst neu. '
                    'Eine neue Nachricht geht erst danach.</p>')
        return (f'<form method="post" action="/marketing/marke/senden" enctype="multipart/form-data" '
                f'class="pult-felder">{csrf_feld()}'
                f'<label>Nachricht <textarea name="nachricht" rows="4" maxlength="{NACHRICHT_MAX}" required '
                f'placeholder="z. B. Wir sind eine Rösterei, warm und klar. Unsere Webseite: https://…"></textarea></label>'
                f'<label>Dateien (Logo, Bilder, Dokumente; höchstens {ANHAENGE_MAX}) '
                f'<input type="file" name="datei" multiple></label>'
                f'<div class="aktionen"><button class="primaer" type="submit">Senden</button></div></form>')

    def vorschlag_html(d: dict, fmt: str) -> str:
        v = d.get("vorschlag")
        if not isinstance(v, dict) or not _uuid_oder_none(v.get("id")):
            return ""
        vid = str(v["id"])
        w = v.get("vorschlag") if isinstance(v.get("vorschlag"), dict) else {}
        farben = "".join(farbfeld(n, w.get(k)) for k, n in _VORSCHLAG_FARBEN)
        schrift = schrift_zeile(w.get("schrift_anzeige"), w.get("schrift_text"),
                                str(d.get("name") or d.get("mandant") or ""))
        logo = logo_fassungen_html(w) or (f'<p>Logo: {e(str(w["logo"]))}</p>' if w.get("logo") else "")
        abschnitte = "".join(
            f'<h3>{e(str(n))}</h3><p>{e(str(t))}</p>'
            for n, t in (w.get("abschnitte") or {}).items() if isinstance(t, str) and t.strip()) \
            if isinstance(w.get("abschnitte"), dict) else ""
        umschalter = " &middot; ".join(
            (f'<b>{t}</b>' if k == fmt else f'<a href="{SEITE}?format={k}">{t}</a>') for k, t in FORMATE.items())
        return (f'<h2>Vorschlag</h2><p class="meta">Vorschau als {umschalter}</p>'
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
                f'src="{e(f"/marketing/marke/vorschau?format={fmt}&vorschlag={vid}")}"></iframe></div></div>')

    @ui._gesichert_seite
    async def marke(request):
        fmt = request.query_params.get("format", "mail")
        fmt = fmt if fmt in FORMATE else "mail"
        try:
            m, liste = await marketing_mandant.firma(request)
            d = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                        f"/marke?mandant={urllib.parse.quote(m)}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not isinstance(d, dict):
            return fehler(marketing_pult.PultFehler("unbekannt", "Antwort ohne Marke"))
        if request.query_params.get("bearbeiten") == "1":
            rumpf = ('<link rel="stylesheet" href="/marketing/schrift/schriften.css">'
                     + marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, SEITE)
                     + bearbeiten_html(d, m) + f'<p><a href="{SEITE}">Zurück zur Marke</a></p>')
            antwort = ui._seite("Marke", rumpf)
            antwort.headers["Content-Security-Policy"] = ui._csp_mit_rahmen("'self'", bilddaten=True, schriften=True)
            return antwort
        status = ""
        if d.get("uebernahme"):
            alter = _alter_s(d.get("uebernahme_seit"))
            wartet = alter is not None and alter > PC_WARTET_NACH_S
            status = f'<p class="status-zeile">{PC_LAEUFT if wartet else "Wird übernommen …"}</p>'
        # Neu laden nur fuer Chat, Bearbeitung und Uebernahme; ein Wissens-Lauf nie (Ruling R7)
        im_chat = bool(d.get("laeuft") or d.get("uebernahme"))
        arbeitet = im_chat
        rumpf = ('<link rel="stylesheet" href="/marketing/schrift/schriften.css">'
                 + marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, SEITE)
                 + '<p class="meta">Das Markenprofil bestimmt Farben, Schriften und Logo neuer Newsletter. '
                   'Erzähl dem Marken-Agenten von der Firma; was er vorschlägt, übernimmst du hier.</p>'
                 + profil_html(d) + f'<p><a href="{SEITE}?bearbeiten=1">Profil bearbeiten</a></p>' + status + (laufend_html(d) if im_chat else "") + letzte_html(d) + wissen_html(d) + "<h2>Chat</h2>" + chat_html(d) + formular_html(d)
                 + vorschlag_html(d, fmt))
        antwort = ui._seite("Marke", rumpf, refresh=REFRESH_S if arbeitet else None)
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
        return RedirectResponse(SEITE, status_code=303)

    # --- Uebernehmen / Verwerfen ------------------------------------------------------------------

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
                # Vorschlag einer anderen Firma (Minor 4, die DB vergleicht)
                m, _liste = await marketing_mandant.firma(request)
                await run_in_threadpool(marketing_pult.anfrage, "POST", f"/marke/vorschlaege/{vid}/{aktion}",
                                        {"von": ui._ui_akteur(request), "mandant": m})
            except marketing_pult.PultFehler as f:
                return fehler(f)
            return RedirectResponse(SEITE, status_code=303)
        return handler

    @ui._gesichert_seite
    async def bearbeiten(request):
        """Formular -> Marken-Agent (Art 'bearbeitung'). Es gibt keinen direkten Schreibweg (Spec §2)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        formular = {k: str(form.get(k) or "").strip() for k, _ in FORM_FARBEN}
        formular.update({k: str(form.get(k) or "").strip() for k in ("schrift_anzeige", "schrift_text", "webseite")})
        formular["abschnitte"] = {n: str(form.get(f"ab{i}") or "").replace("\r\n", "\n").strip()
                                  for i, n in enumerate(ABSCHNITTE)}
        zu_lang = (any(len(formular[k]) > FARBE_MAX for k, _ in FORM_FARBEN)
                   or any(len(formular[k]) > SCHRIFT_MAX for k in ("schrift_anzeige", "schrift_text"))
                   or len(formular["webseite"]) > WEBSEITE_MAX
                   or any(len(t) > ABSCHNITT_MAX for t in formular["abschnitte"].values()))
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
        return RedirectResponse(SEITE, status_code=303)

    # --- Alte Layout-Pfade -------------------------------------------------------------------------

    async def zur_marke(request):
        return RedirectResponse(SEITE, status_code=303)

    alt = ui._gesichert_seite(zur_marke)
    alle = ["GET", "POST"]
    return [
        Route(SEITE, marke),
        Route("/marketing/marke/vorschau", vorschau),
        Route("/marketing/marke/senden", senden, methods=["POST"]),
        Route("/marketing/marke/uebernehmen", vorschlag_aktion("uebernehmen"), methods=["POST"]),
        Route("/marketing/marke/verwerfen", vorschlag_aktion("verwerfen"), methods=["POST"]),
        Route("/marketing/marke/bearbeiten", bearbeiten, methods=["POST"]),
        Route("/marketing/layout/{name}", alt, methods=alle),
        Route("/marketing/layout/{name}/speichern", alt, methods=alle),
        Route("/marketing/layout/{name}/standard", alt, methods=alle),
        Route("/marketing/layout-vorschau", alt, methods=alle),
        Route("/marketing/layout-bild/{name}", alt, methods=alle),
    ]
