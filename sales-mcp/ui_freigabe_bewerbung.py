"""Bewerbungen in den Sales-Freigaben (Plan 2026-10-20 Hermes H1, Task 5).

Auf /freigaben steht im Laden `sales` nach "Marketing" ein Abschnitt
"Bewerbungen": was der Bewerbungs-Bot zur Unterlagenfreigabe vorlegt, je mit
Firma, Rolle, Fassung, Score, groesster Luecke, Kanal, Pruefhinweisen und den
Knoepfen Freigeben / Nicht bewerben / Feedback. Daten und Entscheidung gehoeren
der Zentrale des Bots (Pult-API, bewerbung_pult); diese Datei zeigt nur an und
reicht weiter. Jede Entscheidung ist an Fassung und Bindung der Karte gebunden.

Wie der Rest von sales-ui: kein JavaScript, CSRF-Marke in jedem Formular, das
Anschreiben-PDF nur verlinkt (eigene Datei-Richtlinie, nie gerahmt). Die Texte
der Zentrale sind bereinigt, aber nicht HTML-maskiert: jede Ausgabe laeuft
durch ui._e. Faellt die Zentrale aus, zeigt der Abschnitt einen Hinweis - die
Seite bleibt."""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from datetime import datetime
from functools import partial

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import bewerbung_pult
import pult_cache
from ui_freigabe_newsletter import _vor

ADMIN_PFAD = "/freigaben/bewerbung"
KANAELE = {"email": "E-Mail", "portal": "Portal"}
ENTSCHEIDUNGEN = {"approve": "Freigegeben", "reject": "Nicht bewerben"}
GRUND_MAX = 500
KOMMENTAR_MAX = 2000
TEXT_MAX = 15000
VERLAUF_MAX = 10
# Abschnitt und Menue-Zaehler lesen mit demselben Zeitlimit: ein Zaehler-Abruf, der
# scheitert, sperrt den Abschnitt 60 s (pult_cache) - mit einem kuerzeren Zeitlimit
# als der Abschnitt selbst taete er das zu frueh.
LESE_ZEITLIMIT_S = 3
PDF_ZEITLIMIT_S = 8
# Freigeben/Nicht bewerben verbucht die Zentrale samt Kommando unter einer Schreibsperre.
ENTSCHEIDUNG_ZEITLIMIT_S = 30
FEEDBACK_ZEITLIMIT_S = 8
UNKLAR_TITEL = "Ergebnis unklar – Seite neu laden"

_OFFEN = "/bewerbungen?status=offen"
_ENTSCHIEDEN = "/bewerbungen?status=entschieden"
_FASSUNG = re.compile(r"[1-9][0-9]{0,8}")
_BINDUNG = re.compile(r"sha256:[0-9a-fA-F]{64}")
_NICHT_VON = re.compile(r"[^A-Za-z0-9_.@-]")
# Ein Ablehnungscode der Zentrale (`nicht_offen`, `unbekannt`, ...). Nur so etwas kommt
# aus der Adresse in die Seite - kein freier Text, den jemand in einen Link schreibt.
_CODE = re.compile(r"[a-z0-9_]{1,40}")
_ERFOLG = {"freigeben": "freigegeben", "nicht-bewerben": "abgelehnt", "feedback": "erfasst"}
# bw_hinweis -> (Klasse, fester Text). Die drei 409-Codes der Zentrale heissen hier gleich.
_HINWEISE = {
    "freigegeben": ("hinweis", "Freigegeben – die Zentrale hat die Entscheidung verbucht."),
    "nicht_beworben": ("hinweis", "Nicht bewerben – die Zentrale hat die Entscheidung verbucht."),
    "feedback": ("hinweis", "Feedback erfasst. Die Durchsicht setzt es um."),
    "kein_feedback": ("warnung", "Kein Feedback eingegeben – weder ein Kommentar noch ein "
                                 "geändertes Anschreiben. Nichts wurde gesendet."),
    "fassung_veraltet": ("warnung", "Diese Fassung ist veraltet – Seite neu laden"),
    "schon_entschieden": ("warnung", "Schon entschieden – Seite neu laden."),
    "wartet_auf_durchsicht": ("warnung", "Wartet auf Durchsicht – entscheiden geht erst "
                                         "nach dem GO der Durchsicht."),
}
_ABLEHNUNGEN = ("fassung_veraltet", "schon_entschieden", "wartet_auf_durchsicht")
_WEG = "Die Bewerbungs-Zentrale ist gerade nicht erreichbar."
_NICHT_VERBUNDEN = "Die Bewerbungs-Zentrale ist nicht verbunden."

# Derselbe Logger wie ui.LOG. Ins Protokoll kommen nur Art und Grund eines Fehlers,
# Kennung, Fassung und Aktion - nie der Schluessel, ein Antwortrumpf, das Anschreiben
# oder ein Kommentar.
LOG = logging.getLogger("sales-ui")

# Zahl fuer den Menue-Zaehler und Ausgang der letzten Lesung, 60 s gueltig (pult_cache).
_speicher = pult_cache.PultCache("bewerbung-zaehler")
_cache_leeren = _speicher.leeren
_laeuft = _speicher.laeuft


def _darf(ui) -> bool:
    """Dieselbe Huerde wie die Routen (ui._ADMIN_BASIS_PFADE): Rolle freigeben im
    Basis-Laden. Rolle aus derselben Quelle wie die Seitenleiste (ui._AKTIVE_ROLLE)."""
    return ui._pfad_erlaubt(ui._AKTIVE_ROLLE.get(), ADMIN_PFAD)


def sichtbar(ui) -> bool:
    """Abschnitt und Zaehler gibt es nur, wenn die Zentrale eingerichtet ist UND die
    angemeldete Rolle hier entscheiden darf."""
    return bewerbung_pult.eingerichtet() and _darf(ui)


def _liste(antwort) -> list[dict]:
    liste = antwort.get("bewerbungen") if isinstance(antwort, dict) else None
    if not isinstance(liste, list):
        # Eine kaputte Antwort ist nicht "nichts offen".
        raise bewerbung_pult.PultFehler("unbekannt", "Antwort ohne Liste")
    return [x for x in liste if isinstance(x, dict)]


def _laden() -> int:
    """Blockierend (nur im Thread aufrufen): holt die Zahl und merkt sie - auch den
    Fehlerfall, damit eine tote Zentrale nicht jede Seite warten laesst."""
    try:
        wert = len(_liste(bewerbung_pult.anfrage("GET", _OFFEN, zeitlimit=LESE_ZEITLIMIT_S)))
    except bewerbung_pult.PultFehler as f:
        LOG.warning("Bewerbungs-Zaehler nicht lesbar: %s (%r)", f.art, f.grund)
        _speicher.merken(0, f.art)
        return 0
    except Exception:  # noqa: BLE001 - ein Zaehler darf nie die Seite reissen
        LOG.warning("Bewerbungs-Zaehler nicht lesbar", exc_info=True)
        _speicher.merken(0, "fehler")
        return 0
    _speicher.merken(wert)
    return wert


def anzahl_offen(ui) -> int:
    """Zahl der wartenden Bewerbungen fuer den Menue-Zaehler. NUR Zwischenspeicher
    (der Render-Weg laeuft im Event-Loop); ist er aelter als 60 s, frischt ein
    Hintergrund-Thread ihn auf. Nicht sichtbar: 0, und es startet kein Thread."""
    return _speicher.anzahl(_laden) if sichtbar(ui) else 0


async def _lesen(pfad: str) -> list[dict]:
    return _liste(await run_in_threadpool(partial(bewerbung_pult.anfrage, "GET", pfad,
                                                  zeitlimit=LESE_ZEITLIMIT_S)))


def _von(akteur) -> str:
    """`von` fuer die Zentrale: nur [A-Za-z0-9_.@-], hoechstens 60 Zeichen."""
    return _NICHT_VON.sub("_", str(akteur or ""))[:60] or "sales-ui"


def _fassung(roh) -> int | None:
    s = roh.strip() if isinstance(roh, str) else ""
    return int(s) if _FASSUNG.fullmatch(s) else None


def _nr(wert) -> int | None:
    """Fassung aus der Antwort der Zentrale: nur eine echte positive Zahl."""
    ok = isinstance(wert, int) and not isinstance(wert, bool) and 1 <= wert < 10 ** 9
    return wert if ok else None


def _bindung(roh) -> str | None:
    return roh if isinstance(roh, str) and _BINDUNG.fullmatch(roh) else None


def _text(roh) -> str:
    """Wie die textarea zaehlt: Browser schicken Zeilenumbrueche als CRLF, gemeint ist LF."""
    if not isinstance(roh, str):
        return ""
    return roh.replace("\r\n", "\n").replace("\r", "\n").strip()


def _fingerabdruck(text) -> str:
    """Kennt das Formular das Anschreiben, wie es vorbefuellt war? Der Hash statt des
    Textes selbst: ein verstecktes Feld mit 15000 Zeichen je Karte waere doppelte Last."""
    return hashlib.sha256(_text(text).encode("utf-8", "surrogatepass")).hexdigest()


def _anzeige(url) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        teile = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    return url if teile.scheme in ("http", "https") and teile.netloc else None


def _label(tabelle: dict, code):
    return tabelle.get(code, code) if isinstance(code, str) else code


def _texte(liste) -> list[str]:
    return [x for x in liste if isinstance(x, str)] if isinstance(liste, list) else []


def _score(wert) -> str:
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return f"{wert:.1f}".replace(".", ",") + " / 5"
    return "–"


def _erfasst_am(ui, wert) -> str:
    """Zeitpunkt der Zentrale (ISO, UTC) in Ortszeit, maskiert. Laesst er sich nicht
    lesen, steht er maskiert so da, wie er kam; kein Text: "" (dann steht nichts da)."""
    if not isinstance(wert, str) or not wert.strip():
        return ""
    try:
        zeitpunkt = datetime.fromisoformat(wert.strip().replace("Z", "+00:00"))
    except ValueError:
        return ui._e(wert)
    return ui._e(ui._zeit(zeitpunkt))


def _link(href: str, text: str) -> str:
    """`href` ist schon maskiert bzw. nur aus gequoteten Teilen gebaut."""
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{text}</a>'


def _basis(eintrag: dict) -> str:
    return f'{ADMIN_PFAD}/{urllib.parse.quote(str(eintrag.get("application_id") or ""), safe="")}'


def _karte(ui, k: dict) -> str:
    e = ui._e
    basis = _basis(k)
    nr = _nr(k.get("fassung"))
    bindung = _bindung(k.get("bindung"))
    angaben = [f"Fassung {nr if nr else '?'}", f"Score {_score(k.get('score'))}"]
    if k.get("ort"):
        angaben.append(e(k.get("ort")))
    angaben.append(f"wartet seit {e(_vor(k.get('seit')))}")
    luecke = f'<div>Größte Lücke: {e(k.get("luecke"))}</div>' if k.get("luecke") else ""
    links = []
    if (url := _anzeige(k.get("anzeige_url"))):
        links.append(_link(e(url), "Anzeige ↗"))
    if nr:
        links.append(_link(f"{basis}/anschreiben.pdf?fassung={nr}", "Anschreiben (PDF)"))
    verweise = f'<p class="meta">{" · ".join(links)}</p>' if links else ""
    hinweise = _texte(k.get("pruefhinweise"))
    pruef = (f'<div><b>Prüfhinweise</b><ul>{"".join(f"<li>{e(h)}</li>" for h in hinweise)}</ul></div>'
             if hinweise else '<p class="meta">Keine Prüfhinweise.</p>')
    neu = _texte(k.get("was_neu"))
    was_neu = (f'<div><b>Was ist neu</b><ul>{"".join(f"<li>{e(x)}</li>" for x in neu)}</ul></div>'
               if neu else "")
    felder = (f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
              f'<input type="hidden" name="fassung" value="{nr}">')
    if k.get("wartet_auf_durchsicht"):
        # Die Zentrale lehnt beides mit 409 ab, solange das GO der Durchsicht fehlt.
        entscheiden = ('<div class="hinweis">Wartet auf Durchsicht – Freigeben und Nicht bewerben '
                       'gehen erst nach dem GO der Durchsicht. Feedback geht schon jetzt.</div>')
    elif nr is None or bindung is None:
        entscheiden = '<p class="meta">Fassung oder Bindung fehlt – Seite neu laden.</p>'
    else:
        gebunden = f'{felder}<input type="hidden" name="bindung" value="{e(bindung)}">'
        entscheiden = (
            f'<div class="aktionen">'
            f'<form class="aktion primaer" method="post" action="{basis}/freigeben">{gebunden}'
            f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
            f'Fassung {nr} freigeben bestätigen</label>'
            f'<button class="primaer">Freigeben</button></form>'
            f'<form class="aktion gefahr" method="post" action="{basis}/nicht-bewerben">{gebunden}'
            f'<input type="text" name="grund" maxlength="{GRUND_MAX}" placeholder="Grund (optional)">'
            f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
            f'Nicht bewerben bestätigen</label>'
            f'<button class="gefahr">Nicht bewerben</button></form></div>')
    feedback = ""
    if (am := _erfasst_am(ui, k.get("feedback_offen_seit"))):
        # Angekommen, aber noch nicht umgesetzt (offenes Feedback der Zentrale).
        feedback = f'<p class="meta">Feedback zu Fassung {nr if nr else "?"} erfasst am {am}</p>'
    if nr:
        brief = k.get("anschreiben")
        if isinstance(brief, str) and brief.strip():
            aendern = (f'<input type="hidden" name="original" value="{_fingerabdruck(brief)}">'
                       f'<details class="bearbeiten"><summary>Anschreiben selbst ändern</summary>'
                       f'<textarea name="text" rows="14" maxlength="{TEXT_MAX}">{e(brief)}</textarea>'
                       f'</details>')
        else:
            aendern = '<p class="meta">Anschreiben nicht lesbar</p>'
        feedback += (f'<form method="post" action="{basis}/feedback">{felder}'
                    f'<label class="feld">Feedback zu Fassung {nr}'
                    f'<textarea name="kommentar" maxlength="{KOMMENTAR_MAX}" rows="3" '
                    f'placeholder="Was soll anders werden?"></textarea></label>'
                    f'{aendern}<button>Feedback senden</button></form>')
    kanal = k.get("kanal")
    etikett = f'<span class="badge">{e(_label(KANAELE, kanal))}</span>' if kanal else ""
    return (f'<details class="karte" open><summary>{etikett}'
            f'<b>{e(k.get("firma"))} – {e(k.get("rolle"))}</b></summary>'
            f'<div class="meta">{" · ".join(angaben)}</div>{luecke}'
            f'{verweise}{pruef}{was_neu}{entscheiden}{feedback}</details>')


def _verlauf_zeile(ui, v: dict) -> str:
    e = ui._e
    nr = _nr(v.get("fassung"))
    zusatz = ""
    if v.get("entscheidung") == "approve" and v.get("status") == "blockiert":
        # Versand bis H4 gesperrt: Felix reicht selbst ein und braucht dafuer beides.
        was = "Freigegeben – bitte von Hand einreichen"
        if nr:
            zusatz += " · " + _link(f"{_basis(v)}/anschreiben.pdf?fassung={nr}", "Anschreiben (PDF)")
        if (url := _anzeige(v.get("anzeige_url"))):
            zusatz += " · " + _link(e(url), "Anzeige ↗")
    else:
        was = e(_label(ENTSCHEIDUNGEN, v.get("entscheidung")))
    teile = [f"Fassung {nr if nr else '?'}", was]
    if v.get("von"):
        teile.append(f"von {e(v.get('von'))}")
    teile.append(f"vor {e(_vor(v.get('am')))}")
    return (f'<div class="karte"><b>{e(v.get("firma"))} – {e(v.get("rolle"))}</b> '
            f'<span class="meta">{" · ".join(teile)}</span>{zusatz}</div>')


def _hinweis(ui, request) -> str:
    if request is None:
        return ""
    art = request.query_params.get("bw_hinweis")
    if art in _HINWEISE:
        klasse, text = _HINWEISE[art]
        return f'<div class="{klasse}">{text}</div>'
    if art == "abgelehnt":
        grund = request.query_params.get("bw_grund", "")
        zusatz = f" (Grund: {ui._e(grund)})" if _CODE.fullmatch(grund) else ""
        return (f'<div class="warnung">Die Zentrale hat das nicht angenommen{zusatz}. '
                f'Nichts wurde geändert – Seite neu laden.</div>')
    return ""


async def abschnitt(ui, request=None) -> str:
    """HTML des Abschnitts "Bewerbungen" (Karten + zuletzt entschieden); "" wenn nicht sichtbar."""
    if not sichtbar(ui):
        return ""
    kopf = '<section class="block" id="bewerbungen"><h2>Bewerbungen'
    hinweis = _hinweis(ui, request)

    def kurz(text: str) -> str:
        return f'{kopf}</h2>{hinweis}<p class="meta">{text} Sales läuft normal weiter.</p></section>'

    def weg(art: str) -> str:
        return kurz(_NICHT_VERBUNDEN if art == "nicht_verbunden" else _WEG)

    if (art := _speicher.frisch_fehler()):
        return weg(art)                         # kuerzlich gescheitert: sofort
    try:
        offen = await _lesen(_OFFEN)
        _speicher.merken(len(offen))
        verlauf = await _lesen(_ENTSCHIEDEN)
        # Auch die Darstellung steht im Schutz: ein kaputter Wert der Zentrale kostet
        # den Abschnitt, nie die ganze Seite.
        karten = "".join(_karte(ui, k) for k in offen)
        zeilen = "".join(_verlauf_zeile(ui, v) for v in verlauf[:VERLAUF_MAX])
    except bewerbung_pult.PultFehler as f:
        LOG.warning("Bewerbungen auf /freigaben nicht lesbar: %s (%r)", f.art, f.grund)
        _speicher.merken(0, f.art)
        return weg(f.art)
    except Exception:  # noqa: BLE001 - die Seite darf daran nie scheitern
        LOG.warning("Bewerbungen auf /freigaben nicht lesbar oder nicht darstellbar", exc_info=True)
        _speicher.merken(0, "fehler")
        return weg("fehler")
    n = len(offen)
    teile = [f'{kopf} <span class="zaehler{" offen" if n else ""}">{n}</span></h2>', hinweis]
    if not offen:
        teile.append('<p class="meta">Keine Bewerbung wartet auf deine Entscheidung.</p>')
    teile.append(karten)
    teile.append('<h3 class="verlauftitel">Zuletzt entschieden</h3>')
    teile.append(zeilen or '<p class="meta">Noch nichts entschieden.</p>')
    teile.append("</section>")
    return "".join(teile)


def routen(ui) -> list:
    e = ui._e

    def ziel(hinweis: str, grund: str = "") -> RedirectResponse:
        abfrage = {"bw_hinweis": hinweis, **({"bw_grund": grund} if grund else {})}
        return RedirectResponse(f"/freigaben?{urllib.parse.urlencode(abfrage)}#bewerbungen",
                                status_code=303)

    def verboten():
        return ui._fehlerseite(403, "Nicht für diese Anmeldung",
                               "Bewerbungen entscheidet nur die Rolle „freigeben“ im eigenen Laden. "
                               "Nichts wurde getan.")

    def ungueltig(text: str):
        return ui._fehlerseite(422, "Abgewiesen", f"{text} Nichts wurde gesendet.")

    def nicht_verbunden():
        return ui._fehlerseite(503, "Bewerbungs-Zentrale nicht verbunden",
                               "Die Verbindung zur Bewerbungs-Zentrale ist nicht eingerichtet oder "
                               "der Schlüssel stimmt nicht. Nichts wurde getan.")

    def unklar(was: str):
        # Zeitlimit, Verbindung weg oder unklare Antwort: die Zentrale kann es trotzdem
        # verbucht haben - nie "Nichts wurde getan", nie eine Erfolgsmeldung.
        return ui._fehlerseite(504, UNKLAR_TITEL,
                               f"Die Bewerbungs-Zentrale hat nicht rechtzeitig oder nicht eindeutig "
                               f"geantwortet. Ob {was}, ist offen – bitte die Freigaben-Seite neu "
                               f"laden und nachsehen.")

    async def senden(request, aktion: str, daten: dict, zeitlimit: float, was: str, erfolg: str):
        kennung = request.path_params["bid"]
        bid = urllib.parse.quote(kennung, safe="")

        def unklar_protokolliert(warum: str, *args):
            # Zum spaeteren Abgleich mit der Zentrale: welche Bewerbung, welche Fassung,
            # welche Aktion. Die Kennung als repr - sie kommt aus der Adresse.
            LOG.warning("Bewerbung %r Fassung %s: Ausgang von %s unklar (" + warum + ")",
                        kennung, daten["fassung"], aktion, *args)
            return unklar(was)

        try:
            r = await run_in_threadpool(partial(
                bewerbung_pult.anfrage, "POST", f"/bewerbungen/{bid}/{aktion}", daten,
                zeitlimit=zeitlimit))
        except bewerbung_pult.PultFehler as f:
            _cache_leeren()
            if f.art == "nicht_verbunden":
                return nicht_verbunden()
            if f.art == "abgelehnt":
                if f.grund in _ABLEHNUNGEN:
                    return ziel(f.grund)
                return ziel("abgelehnt", f.grund if _CODE.fullmatch(f.grund) else "")
            return unklar_protokolliert("%s: %r", f.art, f.grund)
        _cache_leeren()
        if not (isinstance(r, dict) and r.get("status") == _ERFOLG[aktion]):
            return unklar_protokolliert("Antwort ohne erwarteten Status")
        return ziel(erfolg)

    async def entscheiden(request, aktion: str):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not _darf(ui):
            return verboten()
        fassung, bindung = _fassung(form.get("fassung")), _bindung(form.get("bindung"))
        if fassung is None or bindung is None:
            return ungueltig("Fassung oder Bindung fehlt oder ist ungültig – Seite neu laden.")
        if form.get("bestaetigt") != "ja":
            return ui._fehlerseite(400, "Nicht bestätigt", "Der Bestätigungshaken fehlt. "
                                   "Nichts wurde gesendet.")
        daten = {"fassung": fassung, "bindung": bindung, "von": _von(ui._ui_akteur(request))}
        if aktion == "freigeben":
            return await senden(request, aktion, daten, ENTSCHEIDUNG_ZEITLIMIT_S,
                                "freigegeben wurde", "freigegeben")
        grund = _text(form.get("grund"))
        if len(grund) > GRUND_MAX:
            return ungueltig(f"Der Grund hat mehr als {GRUND_MAX} Zeichen.")
        if grund:
            daten["grund"] = grund
        return await senden(request, aktion, daten, ENTSCHEIDUNG_ZEITLIMIT_S,
                            "„Nicht bewerben“ vermerkt wurde", "nicht_beworben")

    @ui._gesichert_seite
    async def freigeben(request):
        return await entscheiden(request, "freigeben")

    @ui._gesichert_seite
    async def nicht_bewerben(request):
        return await entscheiden(request, "nicht-bewerben")

    @ui._gesichert_seite
    async def feedback(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not _darf(ui):
            return verboten()
        fassung = _fassung(form.get("fassung"))
        if fassung is None:
            return ungueltig("Welche Fassung gemeint ist, fehlt – Seite neu laden.")
        kommentar = _text(form.get("kommentar"))
        if len(kommentar) > KOMMENTAR_MAX:
            return ungueltig(f"Der Kommentar hat mehr als {KOMMENTAR_MAX} Zeichen.")
        text = _text(form.get("text"))
        if text and _fingerabdruck(text) == form.get("original"):
            text = ""                           # das Anschreiben kam unveraendert zurueck
        if len(text) > TEXT_MAX:
            return ungueltig(f"Das Anschreiben hat mehr als {TEXT_MAX} Zeichen.")
        if not kommentar and not text:
            return ziel("kein_feedback")
        daten = {"fassung": fassung, "von": _von(ui._ui_akteur(request))}
        if kommentar:
            daten["kommentar"] = kommentar
        if text:
            daten["text"] = text
        return await senden(request, "feedback", daten, FEEDBACK_ZEITLIMIT_S,
                            "das Feedback erfasst wurde", "feedback")

    @ui._gesichert_seite
    async def anschreiben_pdf(request):
        if not _darf(ui):
            return verboten()
        fassung = _fassung(request.query_params.get("fassung"))
        if fassung is None:
            return ui._fehlerseite(422, "Ungültige Fassung",
                                   "Welche Fassung gemeint ist, fehlt – Seite neu laden.")
        bid = urllib.parse.quote(request.path_params["bid"], safe="")
        try:
            inhalt, typ = await run_in_threadpool(partial(
                bewerbung_pult.anfrage, "GET", f"/bewerbungen/{bid}/anschreiben.pdf?fassung={fassung}",
                roh=True, zeitlimit=PDF_ZEITLIMIT_S))
        except bewerbung_pult.PultFehler as f:
            if f.art == "nicht_verbunden":
                return nicht_verbunden()
            if f.art == "abgelehnt" and f.grund == "fassung_veraltet":
                return ui._fehlerseite(409, "Fassung veraltet", _HINWEISE["fassung_veraltet"][1])
            if f.art == "abgelehnt" and f.grund == "unbekannt":
                return ui._fehlerseite(404, "Nicht gefunden",
                                       "Dieses Anschreiben hat die Zentrale nicht (mehr).")
            if f.art == "abgelehnt":
                return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
            return ui._fehlerseite(503, "Bewerbungs-Zentrale gerade nicht erreichbar",
                                   "Das Anschreiben ließ sich gerade nicht abrufen. "
                                   "Später erneut versuchen.")
        if not str(typ).startswith("application/pdf"):
            return ui._fehlerseite(502, "Unklare Antwort", "Die Zentrale lieferte kein PDF.")
        # Wie die Medienseite: eigene Datei-Richtlinie (sandbox), verlinkt statt gerahmt.
        return Response(inhalt, media_type="application/pdf",
                        headers={"Content-Security-Policy": ui._CSP_DATEI,
                                 "Content-Disposition": 'inline; filename="Anschreiben.pdf"',
                                 "Cache-Control": "private, no-store"})

    return [
        Route(ADMIN_PFAD + "/{bid}/freigeben", freigeben, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/nicht-bewerben", nicht_bewerben, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/feedback", feedback, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/anschreiben.pdf", anschreiben_pdf),
    ]
