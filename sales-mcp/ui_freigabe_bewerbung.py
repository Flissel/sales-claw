"""Bewerbungen in den Sales-Freigaben (Plan 2026-10-20 Hermes H1, Task 5).

Auf /freigaben steht im Laden `sales` nach "Marketing" ein Abschnitt
"Bewerbungen": was der Bewerbungs-Bot zur Unterlagenfreigabe vorlegt, je mit
Firma, Rolle, Fassung, Score, groesster Luecke, Kanal, Pruefhinweisen und den
Knoepfen Freigeben / Nicht bewerben / Feedback. Daten und Entscheidung gehoeren
der Zentrale des Bots (Pult-API, bewerbung_pult); diese Datei zeigt nur an und
reicht weiter. Jede Entscheidung ist an Fassung und Bindung der Karte gebunden.

Hermes H4 (Versand per E-Mail): Die Karte zeigt den Versandweg (`versand`), Felix setzt die
Bewerbungsadresse in einem eigenen Formular, und "Freigeben" traegt die angezeigte Adresse als
`versand_an` mit - die Zentrale sendet nur an genau diese Adresse. "Zuletzt entschieden" sagt,
was daraus wurde (`ausgang`: versendet, unklar, Handarbeit, wird versendet, wartet auf die
Freigabe per Mail, haengt).

Hermes H2 (Schreiber und Pruefer, Plan 2026-10-27 Task 10): Der Kopf des Abschnitts zeigt, was Hermes
tut (`GET /laeufe/aktuell`: Zustand, der Lauf mit Zaehlern und Staenden) und hat die Knoepfe "Neuer
Lauf" und "Lauf abbrechen". Bei einem beendeten Lauf steht dort "Ende: ..." (der `ende_grund` in
Worten, nie der Rohwert), und am Knopf "Lauf abbrechen" steht, dass Bewerbungen ohne eingereichten Entwurf
archiviert werden. Auf der Karte steht die Pruefnotiz von Hermes samt den offenen Fragen; die
Antworten (einzeilig, hoechstens 500 Zeichen) gelten nur fuer diese Bewerbung. Faellt der Lauf-Status
aus, steht im Kopf der Hinweis - die Karten bleiben.

Hermes A2 (autonomer Versand, Plan 2026-10-30 Task 10): Mit `BEWERBUNG_AUTONOM` geht eine Bewerbung vier
Stunden nach "bereit" von allein raus. Der Kopf zeigt den Not-Aus der Zentrale (`GET /not-aus`: "Not-Aus: aus"
mit "Not-Aus setzen" samt Grund, "Not-Aus: an seit ..." mit "Lösen"); steht er in bot.env, ist er im Pult
nicht lösbar und hat keinen Knopf. Auf der Karte sagt eine Zeile, wann und warum eine Bewerbung rausgeht
(`autonom`: bereit, offene Fragen, Empfänger prüfen, Überarbeitung); nur eine Karte mit `autonom` ist
autonom - dort heißt "Nicht bewerben" "Stoppen" und der Grund ist Pflicht. Karten ohne `autonom` und eine
Zentrale ohne Not-Aus-Route (404) sehen aus wie vorher.

Der Not-Aus wird vor den Karten gelesen: ist er an, sagt eine "bereit"-Karte dazu, dass sie dann nicht rausgeht.
Er steht auch da, wenn die Kartenliste ausfällt - die Bremse gerade dann. "Lösen" lässt gehaltene Bewerbungen
raus und verlangt wie Freigeben den Bestätigungshaken. Fällt der Tag einer "bereit"-Zeit nicht auf heute, steht
das Datum dabei.

Wie der Rest von sales-ui: kein JavaScript, CSRF-Marke in jedem Formular, das
Anschreiben-PDF nur verlinkt (eigene Datei-Richtlinie, nie gerahmt). Die Texte
der Zentrale sind bereinigt, aber nicht HTML-maskiert: jede Ausgabe laeuft
durch ui._e. Faellt die Zentrale aus, zeigt der Abschnitt einen Hinweis - die
Seite bleibt."""
from __future__ import annotations

import hashlib
import logging
import math
import re
import urllib.parse
from datetime import datetime, timezone
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
VERSANDZIEL_ZEITLIMIT_S = 8
ANTWORTEN_ZEITLIMIT_S = 8
# Neuer Lauf legt nur eine Zeile an; Abbrechen archiviert die angelegten Bewerbungen unter einer Schreibsperre.
LAUF_ZEITLIMIT_S = 8
LAUF_ABBRECHEN_ZEITLIMIT_S = 30
# Antworten auf die offenen Fragen der Pruefnotiz: einzeilig, 1 bis 500 Zeichen, hoechstens 5 je Aufruf
# (wie die Zentrale sie annimmt).
ANTWORT_MAX = 500
MAX_ANTWORTEN = 5
UNKLAR_TITEL = "Ergebnis unklar – Seite neu laden"
# Ausgang `unklar`: Die Mail ist womoeglich raus (der Dienst antwortete nicht mehr). Die Zentrale
# wiederholt nichts, Felix schaut selbst in Gmail nach.
UNKLAR_VERSAND = "Versand unklar – in Gmail ‚Gesendet' prüfen"
# Ausgang `freigabe_per_mail`: Die Zentrale hat Felix die Versand-Freigabe gemailt (etwa weil
# sich die Adresse nach der Freigabe noch geaendert hat); gesendet wird erst nach seinem Klick.
WARTET_AUF_FREIGABE = "Versand wartet auf deine Freigabe – Link in der Mail"
# Ausgang `haengt`: Keine Freigabe wirkt mehr, von selbst geht nichts raus.
HAENGT = "Versand hängt – bitte von Hand einreichen oder archivieren"
# Genau eine Adresse, ASCII, wie in der Zentrale (Plan Hermes H4, Global Constraints).
ADRESSE_MAX = 254

_OFFEN = "/bewerbungen?status=offen"
_ENTSCHIEDEN = "/bewerbungen?status=entschieden"
_LAUF = "/laeufe/aktuell"
_NOT_AUS = "/not-aus"
# Der Not-Aus aendert nur einen Schalter in der Zentrale (kein Archivieren): wie "Neuer Lauf".
NOT_AUS_ZEITLIMIT_S = 8
# Faellt die Kartenliste aus, wird der Not-Aus trotzdem gelesen - aber mit kurzem Zeitlimit: die Liste sperrt den
# Abschnitt 60 s (pult_cache), damit eine tote Zentrale nicht jede Seite warten laesst; der Not-Aus kostet dann
# je Seite hoechstens diese eine Sekunde.
NOT_AUS_FEHLERWEG_ZEITLIMIT_S = 1
# Steht hinter "Geht automatisch raus ...", solange der Not-Aus an ist: die Karte geht dann nicht raus.
NOT_AUS_ZUSATZ = " – nicht, solange der Not-Aus an ist"
# Steht im Formular "Loesen" direkt am Knopf: was das Loesen tut.
LOESEN_HINWEIS = "Danach gehen fällige Bewerbungen raus."
# Die Zentrale liefert `von` mit dem Praefix der Quelle (`sales-ui:felix`); gezeigt wird der Name.
NOT_AUS_VON_PRAEFIX = "sales-ui:"
# Steht der Not-Aus in bot.env, haelt ihn das Pult nicht auf: kein Knopf "Loesen", und ein "Loesen" auf einer
# veralteten Seite beantwortet die Zentrale weiter mit `an: true, quelle: bot.env`.
NOT_AUS_QUELLE_ENV = "bot.env"
# Karte `autonom.grund` (Empfaenger-Regel der Zentrale) -> Wort; dieselben Texte wie die Tagesuebersicht. Ein
# Code, den diese Seite nicht kennt, wird nicht wiedergegeben: es steht nur "Empfänger prüfen" da.
EMPFAENGER_GRUENDE = {"kein_email_weg": "kein E-Mail-Weg", "keine_adresse": "keine Adresse",
                      "nicht_in_anzeige": "Adresse steht nicht in der Anzeige",
                      "freemail": "Freemail-Adresse",
                      "domain_unbelegt": "Domain nicht durch ein Impressum belegt"}
EMPFAENGER_FREIGEBEN = "Empfänger bestätigen und freigeben"
# Die Zentrale meldet die Karte als autonom (`autonom` nicht null), der Stand ist aber keiner, den diese Seite kennt.
AUTONOM_UNBEKANNT = "Automatischer Versand: Stand unbekannt"
# Lauf `status` der Zentrale -> Text im Lauf-Kasten (Unbekanntes steht maskiert so da).
LAUF_STATUS = {"angefordert": "angefordert", "laeuft": "läuft", "fertig": "fertig",
               "abgebrochen": "abgebrochen"}
# Bewerbung `stand` der Zentrale (laeufe._stand) -> Text. Ein Stand, den diese Seite nicht kennt, wird
# nicht wiedergegeben: es steht STAND_UNBEKANNT da.
STAENDE = {"offen": "offen", "in_arbeit": "in Arbeit", "wird_verarbeitet": "wird verarbeitet",
           "vorgelegt": "vorgelegt", "blockiert": "blockiert – bitte prüfen", "aufgegeben": "aufgegeben",
           "archiviert": "archiviert"}
STAND_UNBEKANNT = "Stand unbekannt"
# Lauf `ende_grund` der Zentrale -> Zeile "Ende: ..." bei einem beendeten Lauf. `abgebrochen_von:<wer>`
# (Felix im Pult) hat ein Praefix. Jeder andere Wert zeigt nichts - nie den Rohwert.
ENDE_GRUENDE = {"fertig": "alle Bewerbungen bearbeitet", "keine_geeigneten": "keine geeignete Stelle gefunden",
                "auswahl_gescheitert": "Auswahl zweimal gescheitert",
                "kontingent_erschoepft": "Kontingent erschöpft"}
ENDE_ABGEBROCHEN_PRAEFIX = "abgebrochen_von:"
ENDE_ABGEBROCHEN = "von dir abgebrochen"
_LAUF_OFFEN = ("angefordert", "laeuft")
# Steht direkt am Knopf "Lauf abbrechen": was der Abbruch mit den Bewerbungen im Lauf tut.
ABBRECHEN_HINWEIS = ("Bewerbungen, für die Hermes noch keinen Entwurf eingereicht hat, werden archiviert "
                     "und kommen nicht wieder.")
FRAGEN_HINWEIS = "Gilt nur für diese Bewerbung. Soll es allgemein gelten, am PC in profil/ übernehmen."
_ANTWORT_PRAEFIX = "antwort_"
# Kennung einer Frage (die Zentrale vergibt f1 .. f5): nur so etwas wird Feldname und Pfadteil.
_FRAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
_FASSUNG = re.compile(r"[1-9][0-9]{0,8}")
_BINDUNG = re.compile(r"sha256:[0-9a-fA-F]{64}")
_NICHT_VON = re.compile(r"[^A-Za-z0-9_.@-]")
_ADRESSE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Ein Ablehnungscode der Zentrale (`nicht_offen`, `unbekannt`, ...). Nur so etwas kommt
# aus der Adresse in die Seite - kein freier Text, den jemand in einen Link schreibt.
_CODE = re.compile(r"[a-z0-9_]{1,40}")
_ERFOLG = {"freigeben": "freigegeben", "nicht-bewerben": "abgelehnt", "feedback": "erfasst",
           "versandziel": "gesetzt", "antworten": "erfasst"}
# bw_hinweis -> (Klasse, fester Text). Die 409-Codes der Zentrale (_ABLEHNUNGEN) heissen hier gleich.
_HINWEISE = {
    "freigegeben": ("hinweis", "Freigegeben – die Zentrale hat die Entscheidung verbucht."),
    "adresse_gespeichert": ("hinweis", "Bewerbungsadresse gespeichert."),
    "weg_portal": ("hinweis", "Versandweg auf Portal gestellt – nach der Freigabe ist "
                              "Handarbeit nötig."),
    "nicht_beworben": ("hinweis", "Nicht bewerben – die Zentrale hat die Entscheidung verbucht."),
    "feedback": ("hinweis", "Feedback erfasst. Die Durchsicht setzt es um."),
    "kein_feedback": ("warnung", "Kein Feedback eingegeben – weder ein Kommentar noch ein "
                                 "geändertes Anschreiben. Nichts wurde gesendet."),
    "fassung_veraltet": ("warnung", "Diese Fassung ist veraltet – Seite neu laden"),
    "schon_entschieden": ("warnung", "Schon entschieden – Seite neu laden."),
    "wartet_auf_durchsicht": ("warnung", "Wartet auf Durchsicht – entscheiden geht erst "
                                         "nach dem GO der Durchsicht."),
    # Freigeben mit einer Adresse, die inzwischen nicht mehr die der Karte ist: nichts verbucht.
    "versandziel_geaendert": ("warnung", "Bewerbungsadresse hat sich geändert – Seite neu laden"),
    # Hermes H2: Laeufe und Antworten auf die offenen Fragen.
    "lauf_gestartet": ("hinweis", "Neuer Lauf angefordert – Hermes beginnt, sobald er den Auftrag sieht."),
    "lauf_abgebrochen": ("hinweis", "Lauf abgebrochen. Ein Schritt, der gerade läuft, endet von selbst."),
    "antworten_erfasst": ("hinweis", "Antworten erfasst – sie gelten nur für diese Bewerbung."),
    "keine_antwort": ("warnung", "Keine Antwort eingegeben. Nichts wurde gesendet."),
    "lauf_laeuft": ("warnung", "Es läuft schon ein Lauf."),
    "lauf_unbekannt": ("warnung", "Diesen Lauf gibt es nicht – Seite neu laden."),
    "lauf_nicht_offen": ("warnung", "Dieser Lauf ist schon beendet – Seite neu laden."),
    "antwort_ungueltig": ("warnung", "Antwort ungültig – höchstens 500 Zeichen."),
    "frage_unbekannt": ("warnung", "Diese Frage gibt es nicht mehr – Seite neu laden."),
    # Hermes A2: Not-Aus und Stoppen einer autonomen Bewerbung.
    "not_aus_gesetzt": ("hinweis", "Not-Aus gesetzt – es geht nichts mehr automatisch raus."),
    "not_aus_geloest": ("hinweis", "Not-Aus gelöst."),
    "not_aus_bot_env": ("warnung", "Der Not-Aus steht in bot.env und lässt sich im Pult nicht lösen."),
    "gestoppt": ("hinweis", "Gestoppt – die Zentrale hat die Entscheidung verbucht. Die Bewerbung geht nicht raus."),
    "grund_fehlt": ("warnung", "Kein Grund eingegeben – zum Stoppen ist ein Grund nötig. Nichts wurde gesendet."),
}
_ABLEHNUNGEN = ("fassung_veraltet", "schon_entschieden", "wartet_auf_durchsicht",
                "versandziel_geaendert", "lauf_laeuft", "lauf_unbekannt", "lauf_nicht_offen",
                "antwort_ungueltig", "frage_unbekannt")
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


def _adresse_ok(wert) -> bool:
    """Genau eine E-Mail-Adresse, wie die Zentrale sie annimmt. Die Laenge zuerst: das Muster
    laeuft nie auf Beliebig-Langem."""
    return isinstance(wert, str) and len(wert) <= ADRESSE_MAX and _ADRESSE.fullmatch(wert) is not None


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


def _jetzt() -> datetime:
    """Jetzt (UTC). Eigene Funktion, damit die Tests "heute" festlegen koennen."""
    return datetime.now(timezone.utc)


def _ortszeit(ui, zeitpunkt: datetime) -> datetime:
    """Zeitpunkt in der Ortszeit der Seite (ui.ZEITZONE, Europe/Berlin); ohne Zone gilt er als UTC, und ohne
    Zeitzonen-Datenbank (ui.ZEITZONE None) bleibt es bei UTC."""
    if zeitpunkt.tzinfo is None:
        zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
    return zeitpunkt.astimezone(ui.ZEITZONE if ui.ZEITZONE is not None else timezone.utc)


def _uhrzeit(ui, zeitpunkt: datetime) -> str:
    """"HH:MM" in Ortszeit; liegt der Berliner Tag nicht auf heute (morgen, gestern), steht " (TT.MM.)" dahinter.
    Verglichen wird der Tag in Ortszeit, nicht der in UTC (um Mitternacht liegen sie auseinander)."""
    ort = _ortszeit(ui, zeitpunkt)
    text = ort.strftime("%H:%M")
    if ort.date() != _ortszeit(ui, _jetzt()).date():
        text += ort.strftime(" (%d.%m.)")
    return text


def _in_ortszeit(wert, darstellen) -> str | None:
    """Zeitpunkt der Zentrale (ISO-Text, UTC; ohne Zone gilt UTC) mit `darstellen` (ui._zeit, ui._tag_kurz)
    in Ortszeit gezeigt. Kein Text, nicht lesbar oder nicht umzurechnen (Jahr 9999): None."""
    if not isinstance(wert, str) or not wert.strip():
        return None
    try:
        return darstellen(datetime.fromisoformat(wert.strip().replace("Z", "+00:00")))
    except (ValueError, OverflowError):
        return None


def _erfasst_am(ui, wert) -> str:
    """Zeitpunkt der Zentrale (ISO, UTC) in Ortszeit, maskiert. Laesst er sich nicht
    lesen, steht er maskiert so da, wie er kam; kein Text: "" (dann steht nichts da)."""
    if not isinstance(wert, str) or not wert.strip():
        return ""
    zeit = _in_ortszeit(wert, ui._zeit)
    return ui._e(zeit if zeit is not None else wert)


def _link(href: str, text: str) -> str:
    """`href` ist schon maskiert bzw. nur aus gequoteten Teilen gebaut."""
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{text}</a>'


def _basis(eintrag: dict) -> str:
    return f'{ADMIN_PFAD}/{urllib.parse.quote(str(eintrag.get("application_id") or ""), safe="")}'


def _nur_text(wert) -> str:
    return wert.strip() if isinstance(wert, str) else ""


def _dicts(liste) -> list[dict]:
    return [x for x in liste if isinstance(x, dict)] if isinstance(liste, list) else []


def _zeilen(liste) -> list[str]:
    """Die nicht leeren Texte einer Liste der Zentrale (anderes faellt weg)."""
    return [t for t in (_nur_text(x) for x in liste) if t] if isinstance(liste, list) else []


def _pruefnotiz(ui, k: dict, felder: str, basis: str, nr) -> str:
    """Hermes' Pruefnotiz zur Fassung und seine offenen Fragen. Alles maskiert; was nicht die erwartete
    Form hat, faellt weg, die Karte bleibt. Eine Frage mit Antwort steht als Text da, eine ohne bekommt ein
    Eingabefeld `antwort_<id>` (einzeilig, 500 Zeichen) - nur mit gueltiger Fassung und gueltiger Kennung.
    Die Antworten gehen in einem eigenen Formular an die Zentrale und gelten nur fuer diese Bewerbung."""
    e = ui._e
    n = k.get("pruefnotiz")
    if not isinstance(n, dict):
        return ""
    block = ""
    zusammenfassung = _nur_text(n.get("zusammenfassung"))
    listen = "".join(
        f'<div><b>{titel}</b><ul>{"".join(f"<li>{e(x)}</li>" for x in eintraege)}</ul></div>'
        for titel, eintraege in (("Geprüft", _zeilen(n.get("geprueft"))),
                                 ("Geändert", _zeilen(n.get("geaendert"))),
                                 ("Quellen", _zeilen(n.get("quellen"))))
        if eintraege)               # Quellen sind Text, nie Links: Hermes' Text ist kein Ziel fuer den Browser
    if zusammenfassung or listen:
        kurz = f"<p>{e(zusammenfassung)}</p>" if zusammenfassung else ""
        block = f'<div class="pruefnotiz"><b>Prüfnotiz</b>{kurz}{listen}</div>'
    fragen, felder_da = [], False
    for frage in _dicts(n.get("fragen")):
        kennung, text, antwort = frage.get("id"), _nur_text(frage.get("frage")), _nur_text(frage.get("antwort"))
        if not isinstance(kennung, str) or not text:
            continue
        if antwort:
            fragen.append(f'<div class="frage">{e(text)}<br>Deine Antwort: {e(antwort)}</div>')
        elif nr and _FRAGE_ID.fullmatch(kennung):
            felder_da = True
            fragen.append(f'<label class="feld">{e(text)}'
                          f'<input type="text" name="{_ANTWORT_PRAEFIX}{e(kennung)}" maxlength="{ANTWORT_MAX}" '
                          f'placeholder="Deine Antwort"></label>')
        else:
            fragen.append(f'<div class="frage">{e(text)}</div>')
    if fragen:
        inhalt = "".join(fragen)
        if felder_da:
            inhalt = (f'<form method="post" action="{basis}/antworten">{felder}{inhalt}'
                      f'<button>Antworten senden</button></form>')
        block += (f'<div class="fragen"><b>Offene Fragen</b>{inhalt}'
                  f'<p class="meta">{FRAGEN_HINWEIS}</p></div>')
    return block


def _adressformulare(ui, kanal: str, an: str, basis: str, felder: str) -> str:
    """Die Adresse setzen (E-Mail-Weg) und, vom E-Mail-Weg aus, auf Portal zurueckstellen.
    Eigene Formulare, nie zusammen mit Freigeben: die Adresse wird erst gespeichert, dann sieht
    Felix die Karte mit ihr, dann gibt er frei."""
    e = ui._e
    fehlt = kanal == "email" and not an
    eingabe = (f'<label class="feld">Bewerbungsadresse (E-Mail)'
               f'<input type="email" name="an" value="{e(an)}" maxlength="{ADRESSE_MAX}" required '
               f'placeholder="bewerbung@firma.example"></label>')
    klasse = "aktion primaer adresse" if fehlt else "aktion"
    knopf = '<button class="primaer">' if fehlt else "<button>"
    speichern = (f'<form class="{klasse}" method="post" action="{basis}/versandziel">{felder}{eingabe}'
                 f'{knopf}Adresse speichern</button></form>')
    portal = (f'<form class="aktion" method="post" action="{basis}/versandziel">{felder}'
              f'<input type="hidden" name="kanal" value="portal">'
              f'<button>Kein E-Mail-Weg (Portal)</button></form>') if kanal == "email" else ""
    if fehlt:
        return speichern + portal               # die Karte braucht erst eine Adresse: nicht eingeklappt
    titel = "Bewerbungsadresse ändern" if kanal == "email" else "Bewerbungsadresse eintragen"
    return f'<details class="bearbeiten"><summary>{titel}</summary>{speichern}{portal}</details>'


def _weg(ui, k: dict, basis: str, nr, felder: str) -> tuple[str, str, str]:
    """Versandweg der Karte: (Zeile samt Adressformular, verstecktes `versand_an`, Knopfbeschriftung).
    Massgeblich ist allein `versand` - `kanal` oben auf der Karte ist der Kanal der Aufnahme und
    kann ein anderer sein. `versand_an` traegt die angezeigte Adresse mit zur Freigabe (Portal: leer);
    ohne Adresse oder ohne `versand` (Zentrale vor H4) fehlt das Feld, dann fragt die Zentrale wie
    bisher selbst per Mail."""
    e = ui._e
    v = k.get("versand") if isinstance(k.get("versand"), dict) else {}
    kanal, an, warnung = _nur_text(v.get("kanal")), _nur_text(v.get("an")), _nur_text(v.get("warnung"))
    feld, knopf = "", "Freigeben"
    if kanal == "email" and an:
        zeile, knopf = f"<div>Versand: E-Mail an {e(an)}</div>", "Freigeben und senden"
        feld = f'<input type="hidden" name="versand_an" value="{e(an)}">'
    elif kanal == "email":
        zeile = '<div class="hinweis">Versand: E-Mail – Adresse fehlt</div>'
    elif kanal == "portal":
        zeile = '<div class="hinweis">Versand: Portal – nach Freigabe Handarbeit nötig</div>'
        feld = '<input type="hidden" name="versand_an" value="">'
    elif kanal:
        zeile = f"<div>Versand: {e(kanal)}</div>"            # unbekannter Weg: gezeigt, nicht geraten
    else:
        return "", "", knopf
    if warnung:
        zeile += f'<div class="warnung">{e(warnung)}</div>'
    if nr and kanal in ("email", "portal"):
        zeile += _adressformulare(ui, kanal, an if kanal == "email" else "", basis, felder)
    return zeile, feld, knopf


def _autonom(ui, k: dict, not_aus: bool = False) -> tuple[str, str | None]:
    """Autonomie-Zeile der Karte und ihr Stand: (Zeile, Stand). Autonom ist eine Karte genau dann, wenn die
    Zentrale `autonom` als Objekt liefert; sonst ("", None) und die Karte bleibt, wie sie war. Der Stand ist
    einer der vier der Zentrale, bei einem unbekannten "" (die Karte geht trotzdem von allein raus: neutrale
    Zeile, kein Rohwert). Zeiten in Ortszeit; ohne lesbaren Zeitpunkt steht keiner da. Ein Grund steht nur
    in Worten da (EMPFAENGER_GRUENDE); alles andere ist Text der Seite. `not_aus`: die Zentrale hat den Not-Aus als
    an gemeldet - eine "bereit"-Karte sagt dann dazu, dass sie so nicht rausgeht (nur sie verspricht einen Versand)."""
    a = k.get("autonom")
    if not isinstance(a, dict):
        return "", None
    stand = a.get("stand")
    if stand == "bereit":
        uhr = _in_ortszeit(a.get("faellig_am"), lambda z: _uhrzeit(ui, z))
        text = (f"Geht automatisch raus um {ui._e(uhr)}" if uhr
                else "Geht automatisch raus (Zeitpunkt steht noch nicht fest)")
        return f'<div class="hinweis">{text}{NOT_AUS_ZUSATZ if not_aus else ""}</div>', "bereit"
    if stand == "offene_fragen":
        tag = _in_ortszeit(a.get("verfaellt_am"), ui._tag_kurz)
        text = f"Wartet auf deine Antworten, verfällt am {ui._e(tag)}" if tag else "Wartet auf deine Antworten"
        return f'<div class="hinweis">{text}</div>', "offene_fragen"
    if stand == "empfaenger_pruefen":
        grund = a.get("grund")
        wort = EMPFAENGER_GRUENDE.get(grund) if isinstance(grund, str) else None
        text = f"Empfänger prüfen: {ui._e(wort)}" if wort else "Empfänger prüfen"
        return f'<div class="warnung">{text}</div>', "empfaenger_pruefen"
    if stand == "feedback_offen":
        return '<div class="hinweis">Überarbeitung läuft</div>', "feedback_offen"
    return f'<div class="hinweis">{AUTONOM_UNBEKANNT}</div>', ""


def _karte(ui, k: dict, not_aus: bool = False) -> str:
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
    versand, versand_an, freigeben = _weg(ui, k, basis, nr, felder)
    autonom_zeile, autonom_stand = _autonom(ui, k, not_aus)
    if autonom_stand == "empfaenger_pruefen":
        freigeben = EMPFAENGER_FREIGEBEN        # die Karte geht nicht von allein raus: Felix bestätigt den Empfänger
    pruefnotiz = _pruefnotiz(ui, k, felder, basis, nr)
    if k.get("wartet_auf_durchsicht"):
        # Die Zentrale lehnt beides mit 409 ab, solange das GO der Durchsicht fehlt.
        entscheiden = ('<div class="hinweis">Wartet auf Durchsicht – Freigeben und Nicht bewerben '
                       'gehen erst nach dem GO der Durchsicht. Feedback geht schon jetzt.</div>')
    elif nr is None or bindung is None:
        entscheiden = '<p class="meta">Fassung oder Bindung fehlt – Seite neu laden.</p>'
    else:
        gebunden = f'{felder}<input type="hidden" name="bindung" value="{e(bindung)}">'
        if autonom_stand is None:
            ablehnen = (
                f'<form class="aktion gefahr" method="post" action="{basis}/nicht-bewerben">{gebunden}'
                f'<input type="text" name="grund" maxlength="{GRUND_MAX}" placeholder="Grund (optional)">'
                f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
                f'Nicht bewerben bestätigen</label>'
                f'<button class="gefahr">Nicht bewerben</button></form>')
        else:
            # Eine autonome Karte geht von allein raus: das Ablehnen heißt Stoppen, und warum, steht im Grund.
            ablehnen = (
                f'<form class="aktion gefahr" method="post" action="{basis}/stoppen">{gebunden}'
                f'<input type="text" name="grund" maxlength="{GRUND_MAX}" required placeholder="Grund (Pflicht)">'
                f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
                f'Stoppen bestätigen</label>'
                f'<button class="gefahr">Stoppen</button></form>')
        entscheiden = (
            f'<div class="aktionen">'
            f'<form class="aktion primaer" method="post" action="{basis}/freigeben">{gebunden}{versand_an}'
            f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
            f'Fassung {nr} freigeben bestätigen</label>'
            f'<button class="primaer">{freigeben}</button></form>'
            f'{ablehnen}</div>')
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
    # Das Etikett folgt dem Versandweg wie die Versandzeile; ohne `versand` (Zentrale vor H4)
    # der Kanal der Aufnahme.
    weg = k.get("versand") if isinstance(k.get("versand"), dict) else {}
    kanal = _nur_text(weg.get("kanal")) or k.get("kanal")
    etikett = f'<span class="badge">{e(_label(KANAELE, kanal))}</span>' if kanal else ""
    return (f'<details class="karte" open><summary>{etikett}'
            f'<b>{e(k.get("firma"))} – {e(k.get("rolle"))}</b></summary>'
            f'<div class="meta">{" · ".join(angaben)}</div>{autonom_zeile}{luecke}'
            f'{verweise}{pruef}{was_neu}{pruefnotiz}{versand}{entscheiden}{feedback}</details>')


def _von_hand_links(ui, v: dict, nr) -> str:
    """Anschreiben-PDF und Anzeige: was Felix zum Einreichen von Hand braucht."""
    zusatz = ""
    if nr:
        zusatz += " · " + _link(f"{_basis(v)}/anschreiben.pdf?fassung={nr}", "Anschreiben (PDF)")
    if (url := _anzeige(v.get("anzeige_url"))):
        zusatz += " · " + _link(ui._e(url), "Anzeige ↗")
    return zusatz


def _verlauf_zeile(ui, v: dict) -> str:
    e = ui._e
    nr = _nr(v.get("fassung"))
    zusatz = ""
    # `ausgang` sagt die Zentrale (H4). Fehlt es ganz (aeltere Zentrale), gilt wie vor H4 der Status.
    ausgang = v.get("ausgang")
    von_hand = ausgang == "handarbeit" or (
        ausgang in (None, "") and v.get("entscheidung") == "approve" and v.get("status") == "blockiert")
    if ausgang == "versendet":
        an = _nur_text(v.get("versand_an"))
        was = f"Versendet an {e(an)}" if an else "Versendet"
    elif ausgang == "unklar":
        was = UNKLAR_VERSAND
    elif ausgang == "wird_versendet":
        was = "Wird versendet …"
    elif ausgang == "freigabe_per_mail":
        was = WARTET_AUF_FREIGABE
    elif ausgang == "haengt":
        # Keine Freigabe wirkt mehr (etwa eine geaenderte Vorlage): von Hand oder archivieren.
        was = HAENGT
        zusatz = _von_hand_links(ui, v, nr)
    elif von_hand:
        # Nicht automatisch rausgegangen: Felix reicht selbst ein und braucht dafuer beides,
        # beim E-Mail-Weg auch die Adresse.
        was = "Freigegeben – bitte von Hand einreichen"
        if (an := _nur_text(v.get("versand_an"))):
            was += f" (per E-Mail an {e(an)})"
        zusatz = _von_hand_links(ui, v, nr)
    elif ausgang in (None, "", "abgelehnt", "offen"):
        was = e(_label(ENTSCHEIDUNGEN, v.get("entscheidung")))
    else:
        was = e(ausgang)                       # ein Ausgang, den diese Seite nicht kennt: wie geliefert
    teile = [f"Fassung {nr if nr else '?'}", was]
    if v.get("von"):
        teile.append(f"von {e(v.get('von'))}")
    teile.append(f"vor {e(_vor(v.get('am')))}")
    return (f'<div class="karte"><b>{e(v.get("firma"))} – {e(v.get("rolle"))}</b> '
            f'<span class="meta">{" · ".join(teile)}</span>{zusatz}</div>')


def _ganz(wert) -> bool:
    """Ein Zaehler der Zentrale: eine echte ganze Zahl, nicht negativ."""
    return isinstance(wert, int) and not isinstance(wert, bool) and wert >= 0


def _zahl(wert) -> str:
    return str(wert) if _ganz(wert) else "?"


def _minuten(sekunden) -> str:
    """Dauer in ganzen Minuten (gerundet); keine brauchbare Zahl: "?"."""
    ok = (isinstance(sekunden, (int, float)) and not isinstance(sekunden, bool)
          and math.isfinite(sekunden) and sekunden >= 0)
    return str(int(sekunden / 60 + 0.5)) if ok else "?"


def _score_kurz(wert) -> str:
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return f"{wert:.1f}".replace(".", ",")
    return "–"


def _hermes_zeile(ui, hermes) -> str:
    """Was Hermes gerade tut. Ein Zustand, den diese Seite nicht kennt (oder gar keiner), ist
    "Status unbekannt" - er wird nicht wiedergegeben. Der Grund steht nur bei `pausiert`."""
    h = hermes if isinstance(hermes, dict) else {}
    zustand, grund = h.get("zustand"), _nur_text(h.get("grund"))
    if zustand == "bereit":
        return '<p class="meta">Hermes: bereit</p>'
    if zustand == "arbeitet":
        return '<p class="meta">Hermes arbeitet …</p>'
    if zustand == "pausiert":
        zusatz = ": Kontingent" if grund == "kontingent" else (f": {ui._e(grund)}" if grund else "")
        return f'<div class="hinweis">Hermes pausiert{zusatz}</div>'
    if zustand == "nicht_erreichbar":
        return '<div class="warnung">Hermes nicht erreichbar</div>'
    return '<p class="meta">Hermes: Status unbekannt</p>'


def _stand_text(stand) -> str:
    """Der Text zu einem Stand der Zentrale; ein unbekannter (auch ein Nicht-Text) wird nicht roh gezeigt."""
    return STAENDE.get(stand, STAND_UNBEKANNT) if isinstance(stand, str) else STAND_UNBEKANNT


def _ende_text(lauf: dict) -> str | None:
    """Warum ein beendeter Lauf endete, in Worten; sonst None (offener Lauf, kein oder unbekannter Grund)."""
    grund = lauf.get("ende_grund")
    if lauf.get("status") not in ("fertig", "abgebrochen") or not isinstance(grund, str):
        return None
    if grund in ENDE_GRUENDE:
        return ENDE_GRUENDE[grund]
    return ENDE_ABGEBROCHEN if grund.startswith(ENDE_ABGEBROCHEN_PRAEFIX) else None


def _lauf_kasten(ui, lauf: dict) -> str:
    """Der Lauf in Worten: Anforderung und Status, je Bewerbung Stand, bei einem beendeten Lauf das Ende,
    die Zaehler der Bewertung, die Begruendung von Hermes und was der Lauf gekostet hat (`modellaufrufe`
    kennt die Zentrale nicht immer)."""
    e = ui._e
    am = _erfasst_am(ui, lauf.get("angefordert_am")) or "?"
    kopf = f"Lauf vom {am}: {e(_label(LAUF_STATUS, lauf.get('status')))}"
    bewerbungen = "".join(
        f"<li>{e(b.get('firma'))} – {e(b.get('rolle'))} (Score {_score_kurz(b.get('score'))}): "
        f"{e(_stand_text(b.get('stand')))}</li>"
        for b in _dicts(lauf.get("bewerbungen")))
    liste = f"<ul>{bewerbungen}</ul>" if bewerbungen else ""
    ende = _ende_text(lauf)
    ende = f"<p>Ende: {e(ende)}</p>" if ende else ""
    zaehler = (f"bewertet {_zahl(lauf.get('bewertet'))} · unter 3,5: {_zahl(lauf.get('unter_schwelle'))}"
               f" · Sperrfrist: {_zahl(lauf.get('sperrfrist'))} · Lauf voll: {_zahl(lauf.get('lauf_voll'))}")
    begruendung = _nur_text(lauf.get("begruendung"))
    warum = f"<p>Begründung: {e(begruendung)}</p>" if begruendung else ""
    dauer = f"Dauer {_minuten(lauf.get('dauer_s'))} min"
    if _ganz(lauf.get("modellaufrufe")):
        dauer += f" · {lauf['modellaufrufe']} Modellaufrufe"
    return (f'<div class="karte lauf"><b>{kopf}</b>{liste}{ende}<p class="meta">{zaehler}</p>{warum}'
            f'<p class="meta">{dauer}</p></div>')


def _lauf_knoepfe(ui, neuer_lauf_moeglich: bool, lauf: dict | None) -> str:
    """"Neuer Lauf" nur, wenn die Zentrale es meldet (sonst steht da "Lauf läuft"); "Lauf abbrechen" nur
    bei einem offenen Lauf (angefordert oder laeuft). Beide Formulare tragen die CSRF-Marke."""
    csrf = f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
    if neuer_lauf_moeglich:
        neu = (f'<form class="aktion primaer" method="post" action="{ADMIN_PFAD}/lauf">{csrf}'
               f'<button class="primaer">Neuer Lauf</button></form>')
    else:
        neu = '<span class="meta">Lauf läuft</span>'
    abbrechen = ""
    lauf_id = lauf.get("lauf_id") if lauf else None
    if lauf and lauf.get("status") in _LAUF_OFFEN and isinstance(lauf_id, str) and lauf_id:
        abbrechen = (f'<form class="aktion gefahr" method="post" '
                     f'action="{ADMIN_PFAD}/lauf/{urllib.parse.quote(lauf_id, safe="")}/abbrechen">{csrf}'
                     f'<p class="meta">{ui._e(ABBRECHEN_HINWEIS)}</p>'
                     f'<button class="gefahr">Lauf abbrechen</button></form>')
    return f'<div class="aktionen">{neu}{abbrechen}</div>'


def _lauf_html(ui, antwort) -> str:
    """Hermes-Zeile, Lauf-Kasten und Knoepfe aus der Antwort von `/laeufe/aktuell`. Eine Antwort, deren
    Form nicht stimmt, ist ein Fehler (PultFehler) - kein "kein Lauf", und kein Knopf auf Verdacht."""
    if not isinstance(antwort, dict) or not isinstance(antwort.get("neuer_lauf_moeglich"), bool):
        raise bewerbung_pult.PultFehler("unbekannt", "Antwort ohne neuer_lauf_moeglich")
    lauf = antwort.get("lauf")
    if lauf is not None and not isinstance(lauf, dict):
        raise bewerbung_pult.PultFehler("unbekannt", "Lauf ist kein Objekt")
    kasten = _lauf_kasten(ui, lauf) if lauf else '<p class="meta">Noch kein Lauf.</p>'
    return (f'<div class="hermes">{_hermes_zeile(ui, antwort.get("hermes"))}{kasten}'
            f'{_lauf_knoepfe(ui, antwort["neuer_lauf_moeglich"], lauf)}</div>')


async def _lauf_kopf(ui) -> str:
    """Der Kopf des Abschnitts. Der Lauf-Status hat seinen eigenen Schutz: scheitert das Lesen oder
    Darstellen, steht hier der Hinweis (ohne Knoepfe) und der Rest des Abschnitts bleibt. Anders als die
    Liste wird er nicht im Zwischenspeicher gesperrt - jede Seite fragt neu, mit dem Zeitlimit der Liste."""
    try:
        antwort = await run_in_threadpool(partial(bewerbung_pult.anfrage, "GET", _LAUF,
                                                  zeitlimit=LESE_ZEITLIMIT_S))
        return _lauf_html(ui, antwort)
    except bewerbung_pult.PultFehler as f:
        LOG.warning("Hermes-Lauf auf /freigaben nicht lesbar: %s (%r)", f.art, f.grund)
        text = _NICHT_VERBUNDEN if f.art == "nicht_verbunden" else _WEG
    except Exception:  # noqa: BLE001 - der Lauf-Status darf nie die Karten reissen
        LOG.warning("Hermes-Lauf auf /freigaben nicht lesbar oder nicht darstellbar", exc_info=True)
        text = _WEG
    return f'<p class="meta">Lauf-Status: {text}</p>'


def _not_aus_html(ui, antwort) -> str:
    """Der Not-Aus aus der Antwort von `GET /not-aus`. Aus: "Not-Aus: aus" und der Knopf "Not-Aus setzen"
    samt (freiwilligem) Grund. An: seit wann, von wem und warum, und der Knopf "Lösen" - außer der Not-Aus
    steht in bot.env, dann hält ihn das Pult nicht auf: "gesetzt in bot.env" und kein Knopf. Nur ein echtes
    bool in `an` sagt etwas; eine andere Form ist ein Fehler (PultFehler), kein "aus" und kein Knopf auf
    Verdacht. Alles aus der Zentrale ist maskiert."""
    if not isinstance(antwort, dict) or not isinstance(antwort.get("an"), bool):
        raise bewerbung_pult.PultFehler("unbekannt", "Antwort ohne an")
    csrf = f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
    if not antwort["an"]:
        return (f'<div class="notaus"><p class="meta">Not-Aus: aus</p><div class="aktionen">'
                f'<form class="aktion gefahr" method="post" action="{ADMIN_PFAD}/not-aus/setzen">{csrf}'
                f'<input type="text" name="grund" maxlength="{GRUND_MAX}" placeholder="Grund (optional)">'
                f'<button class="gefahr">Not-Aus setzen</button></form></div></div>')
    if antwort.get("quelle") == NOT_AUS_QUELLE_ENV:
        return ('<div class="notaus"><div class="warnung">Not-Aus: an – gesetzt in bot.env, '
                'im Pult nicht lösbar</div></div>')
    seit, grund = _erfasst_am(ui, antwort.get("seit")), _nur_text(antwort.get("grund"))
    von = _nur_text(antwort.get("von")).removeprefix(NOT_AUS_VON_PRAEFIX)
    teile = [f"Not-Aus: an seit {seit}" if seit else "Not-Aus: an"]
    if von:
        teile.append(f"von {ui._e(von)}")
    if grund:
        teile.append(f"Grund: {ui._e(grund)}")
    return (f'<div class="notaus"><div class="warnung">{" · ".join(teile)}</div><div class="aktionen">'
            f'<form class="aktion" method="post" action="{ADMIN_PFAD}/not-aus/loesen">{csrf}'
            f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> Lösen bestätigen</label>'
            f'<p class="meta">{LOESEN_HINWEIS}</p>'
            f'<button>Lösen</button></form></div></div>')


async def _not_aus_lesen(ui, zeitlimit: float = LESE_ZEITLIMIT_S) -> tuple[str, bool]:
    """Der Not-Aus im Kopf des Abschnitts: (HTML, `an`). Wie der Lauf-Status mit eigenem Schutz und ohne Sperre im
    Zwischenspeicher: scheitert das Lesen oder Darstellen, steht hier der Hinweis (ohne Knöpfe), und der Rest des
    Abschnitts bleibt. Eine Zentrale ohne die Route (404, vor A2) hat keinen Not-Aus: dann steht nichts da.
    `an` ist nur wahr, wenn die Zentrale den Not-Aus als gesetzt gemeldet hat; in jedem anderen Fall (aus, nicht
    lesbar, keine Route) ist es falsch - die Karten behaupten dann nichts über ihn."""
    try:
        antwort = await run_in_threadpool(partial(bewerbung_pult.anfrage, "GET", _NOT_AUS,
                                                  zeitlimit=zeitlimit))
        return _not_aus_html(ui, antwort), antwort["an"] is True
    except bewerbung_pult.PultFehler as f:
        if f.art == "abgelehnt":
            LOG.debug("Not-Aus: die Zentrale kennt die Route nicht (%r)", f.grund)
            return "", False
        LOG.warning("Not-Aus auf /freigaben nicht lesbar: %s (%r)", f.art, f.grund)
        text = _NICHT_VERBUNDEN if f.art == "nicht_verbunden" else _WEG
    except Exception:  # noqa: BLE001 - der Not-Aus darf nie die Karten reissen
        LOG.warning("Not-Aus auf /freigaben nicht lesbar oder nicht darstellbar", exc_info=True)
        text = _WEG
    return f'<div class="warnung">Not-Aus-Status nicht lesbar: {text}</div>', False


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


async def abschnitt(ui, request=None, offen: bool = True, verlauf: bool = True) -> str:
    """HTML des Abschnitts "Bewerbungen" (Kopf mit Hermes und Lauf, Karten, zuletzt entschieden);
    "" wenn nicht sichtbar.

    Rundgang 27.10.2026: /freigaben zeigt nur Offenes (verlauf=False), "Zuletzt
    entschieden" steht unter Monitoring -> Verlauf (offen=False). Lauf-Kasten, Karten und
    Formulare stehen vor dem Verlaufstitel und damit nur auf /freigaben: die Verlauf-Sicht
    behaelt von allem davor nur die Ueberschrift."""
    teil = await _abschnitt(ui, request)
    if not teil or "verlauftitel" not in teil:
        return teil if offen else ""
    vorne, _, hinten = teil.partition('<h3 class="verlauftitel">')
    if offen and verlauf:
        return teil
    if offen:
        return vorne + "</section>"
    kopf = vorne.split("</h2>")[0].split('<span class="zaehler')[0]
    return f'{kopf}</h2><h3 class="verlauftitel">{hinten}'


async def _abschnitt(ui, request=None) -> str:
    """Der ganze Abschnitt in einem Stueck: Kopf, Hinweis, Lauf-Kasten, Karten - dann, ab dem
    Verlaufstitel, "Zuletzt entschieden". `abschnitt` schneidet daran auf."""
    if not sichtbar(ui):
        return ""
    kopf = '<section class="block" id="bewerbungen"><h2>Bewerbungen'
    hinweis = _hinweis(ui, request)

    async def weg(art: str) -> str:
        # Die Bremse gerade dann: auch wenn die Karten fehlen, steht der Not-Aus da (frisch gelesen, kurzes Zeitlimit).
        not_aus, _ = await _not_aus_lesen(ui, NOT_AUS_FEHLERWEG_ZEITLIMIT_S)
        text = _NICHT_VERBUNDEN if art == "nicht_verbunden" else _WEG
        return f'{kopf}</h2>{hinweis}{not_aus}<p class="meta">{text} Sales läuft normal weiter.</p></section>'

    if (art := _speicher.frisch_fehler()):
        return await weg(art)                   # kuerzlich gescheitert: die Liste sofort, der Not-Aus frisch
    try:
        offen = await _lesen(_OFFEN)
        _speicher.merken(len(offen))
        verlauf = await _lesen(_ENTSCHIEDEN)
        # Der Not-Aus vor den Karten: eine "bereit"-Karte muss wissen, ob er an ist.
        not_aus, not_aus_an = await _not_aus_lesen(ui)
        # Auch die Darstellung steht im Schutz: ein kaputter Wert der Zentrale kostet
        # den Abschnitt, nie die ganze Seite.
        karten = "".join(_karte(ui, k, not_aus_an) for k in offen)
        zeilen = "".join(_verlauf_zeile(ui, v) for v in verlauf[:VERLAUF_MAX])
    except bewerbung_pult.PultFehler as f:
        LOG.warning("Bewerbungen auf /freigaben nicht lesbar: %s (%r)", f.art, f.grund)
        _speicher.merken(0, f.art)
        return await weg(f.art)
    except Exception:  # noqa: BLE001 - die Seite darf daran nie scheitern
        LOG.warning("Bewerbungen auf /freigaben nicht lesbar oder nicht darstellbar", exc_info=True)
        _speicher.merken(0, "fehler")
        return await weg("fehler")
    n = len(offen)
    teile = [f'{kopf} <span class="zaehler{" offen" if n else ""}">{n}</span></h2>', hinweis,
             not_aus, await _lauf_kopf(ui)]
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

    async def abschicken(pfad: str, daten: dict, zeitlimit: float, was: str, erfolg, gelungen,
                         beschreibung: str):
        """Eine Aenderung an die Zentrale. `gelungen(antwort)` sagt, ob die Antwort der Erfolg ist, den
        diese Aktion meldet; `erfolg` ist der Hinweis dazu (oder eine Funktion der Antwort, die ihn nennt:
        der Not-Aus kann gelungen sein und trotzdem an bleiben); `beschreibung` steht im Protokoll, wenn der
        Ausgang unklar bleibt (zum spaeteren Abgleich mit der Zentrale: welche Bewerbung oder welcher Lauf,
        welche Aktion - die Kennung als repr, sie kommt aus der Adresse; nie Schluessel, Rumpf oder
        Eingabetext)."""

        def unklar_protokolliert(warum: str, *args):
            LOG.warning("%s unklar (" + warum + ")", beschreibung, *args)
            return unklar(was)

        try:
            r = await run_in_threadpool(partial(
                bewerbung_pult.anfrage, "POST", pfad, daten, zeitlimit=zeitlimit))
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
        if not (isinstance(r, dict) and gelungen(r)):
            return unklar_protokolliert("Antwort ohne erwarteten Status")
        return ziel(erfolg(r) if callable(erfolg) else erfolg)

    async def senden(request, aktion: str, daten: dict, zeitlimit: float, was: str, erfolg: str):
        kennung = request.path_params["bid"]
        bid = urllib.parse.quote(kennung, safe="")
        return await abschicken(
            f"/bewerbungen/{bid}/{aktion}", daten, zeitlimit, was, erfolg,
            lambda r: r.get("status") == _ERFOLG[aktion],
            f"Bewerbung {kennung!r} Fassung {daten['fassung']}: Ausgang von {aktion}")

    async def formular(request):
        """Das Formular samt der Vorpruefung aller Routen: CSRF-Marke und Rolle. -> (Formular, None) oder
        (None, Fehlerseite)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return None, ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not _darf(ui):
            return None, verboten()
        return form, None

    async def entscheiden(request, aktion: str):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not _darf(ui):
            return verboten()
        fassung, bindung = _fassung(form.get("fassung")), _bindung(form.get("bindung"))
        if fassung is None or bindung is None:
            return ungueltig("Fassung oder Bindung fehlt oder ist ungültig – Seite neu laden.")
        daten = {"fassung": fassung, "bindung": bindung, "von": _von(ui._ui_akteur(request))}
        if aktion == "freigeben" and "versand_an" in form:
            # Die Adresse, die die Karte gezeigt hat (Portal: leer). Fehlt das Feld ganz, schickt die
            # Karte keine: dann fragt die Zentrale wie vor H4 per Mail. Nichts wird zurechtgebogen.
            versand_an = form.get("versand_an")
            if versand_an != "" and not _adresse_ok(versand_an):
                return ungueltig("Die bestätigte Bewerbungsadresse ist keine gültige Adresse – "
                                 "Seite neu laden.")
            daten["versand_an"] = versand_an
        if form.get("bestaetigt") != "ja":
            return ui._fehlerseite(400, "Nicht bestätigt", "Der Bestätigungshaken fehlt. "
                                   "Nichts wurde gesendet.")
        if aktion == "freigeben":
            return await senden(request, aktion, daten, ENTSCHEIDUNG_ZEITLIMIT_S,
                                "freigegeben wurde", "freigegeben")
        grund = _text(form.get("grund"))
        if len(grund) > GRUND_MAX:
            return ungueltig(f"Der Grund hat mehr als {GRUND_MAX} Zeichen.")
        if aktion == "stoppen":
            # Eine autonome Bewerbung stoppen: dieselbe Entscheidung wie "Nicht bewerben" in der Zentrale,
            # aber hier ist der Grund Pflicht - ohne ihn geht nichts hin.
            if not grund:
                return ziel("grund_fehlt")
            daten["grund"] = grund
            return await senden(request, "nicht-bewerben", daten, ENTSCHEIDUNG_ZEITLIMIT_S,
                                "die Bewerbung gestoppt wurde", "gestoppt")
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
    async def stoppen(request):
        return await entscheiden(request, "stoppen")

    async def not_aus_schalten(request, an: bool):
        """Den Not-Aus der Zentrale setzen (mit freiwilligem Grund, eine Zeile) oder lösen (mit Haken). Gelungen heißt:
        `an` kommt als echtes bool so zurück, wie gewollt - beim Lösen auch `an: true` mit Quelle bot.env
        (die Zentrale hält ihn dann, das Pult sagt es). Der Grund steht in keinem Protokoll."""
        form, fehler = await formular(request)
        if fehler is not None:
            return fehler
        if not an and form.get("bestaetigt") != "ja":
            # Lösen lässt gehaltene Bewerbungen raus: wie Freigeben nur mit dem Haken. Setzen ist die sichere
            # Richtung und braucht keinen.
            return ui._fehlerseite(400, "Nicht bestätigt", "Der Bestätigungshaken fehlt. Nichts wurde gesendet.")
        grund = None
        if an:
            text = _text(form.get("grund"))
            if len(text) > GRUND_MAX:
                return ungueltig(f"Der Grund hat mehr als {GRUND_MAX} Zeichen.")
            if not text.isprintable():             # mehrzeilig oder mit Steuerzeichen: die Zentrale lehnt es ab
                return ungueltig("Der Grund darf nur eine Zeile ohne Steuerzeichen sein.")
            grund = text or None
        daten = {"an": an, "von": _von(ui._ui_akteur(request)), "grund": grund}
        if an:
            return await abschicken(
                _NOT_AUS, daten, NOT_AUS_ZEITLIMIT_S, "der Not-Aus gesetzt wurde", "not_aus_gesetzt",
                lambda r: r.get("an") is True, "Not-Aus setzen: Ausgang")
        return await abschicken(
            _NOT_AUS, daten, NOT_AUS_ZEITLIMIT_S, "der Not-Aus gelöst wurde",
            lambda r: "not_aus_geloest" if r.get("an") is False else "not_aus_bot_env",
            lambda r: r.get("an") is False or (r.get("an") is True and r.get("quelle") == NOT_AUS_QUELLE_ENV),
            "Not-Aus lösen: Ausgang")

    @ui._gesichert_seite
    async def not_aus_setzen(request):
        return await not_aus_schalten(request, True)

    @ui._gesichert_seite
    async def not_aus_loesen(request):
        return await not_aus_schalten(request, False)

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
    async def versandziel(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not _darf(ui):
            return verboten()
        fassung = _fassung(form.get("fassung"))
        if fassung is None:
            return ungueltig("Welche Fassung gemeint ist, fehlt – Seite neu laden.")
        daten = {"fassung": fassung, "von": _von(ui._ui_akteur(request))}
        kanal = form.get("kanal", "email")         # das Adressformular schickt keinen `kanal`
        if kanal == "portal":
            daten["kanal"], erfolg = "portal", "weg_portal"        # nie mit Adresse: Portal hat keine
        elif kanal == "email":
            an = _text(form.get("an"))
            if not _adresse_ok(an):
                return ungueltig("Das ist keine einzelne gültige E-Mail-Adresse.")
            daten["kanal"], daten["an"], erfolg = "email", an, "adresse_gespeichert"
        else:
            return ungueltig("Der Versandweg ist unbekannt – Seite neu laden.")
        return await senden(request, "versandziel", daten, VERSANDZIEL_ZEITLIMIT_S,
                            "die Bewerbungsadresse gespeichert wurde", erfolg)

    @ui._gesichert_seite
    async def antworten(request):
        """Felix' Antworten auf die offenen Fragen der Pruefnotiz: die Felder `antwort_<id>`, nur die nicht
        leeren, als [{frage_id, antwort}]. Einzeilig und hoechstens ANTWORT_MAX Zeichen - was die Zentrale
        ablehnen wuerde, geht gar nicht erst hin (alle oder keine)."""
        form, fehler = await formular(request)
        if fehler is not None:
            return fehler
        fassung = _fassung(form.get("fassung"))
        if fassung is None:
            return ungueltig("Welche Fassung gemeint ist, fehlt – Seite neu laden.")
        eintraege, gesehen = [], set()
        for name, wert in form.multi_items():
            text = _text(wert)
            if not isinstance(name, str) or not name.startswith(_ANTWORT_PRAEFIX) or not text:
                continue                    # fremde und leere Felder
            frage_id = name[len(_ANTWORT_PRAEFIX):]
            if _FRAGE_ID.fullmatch(frage_id) is None or frage_id in gesehen:
                return ungueltig("Eine Frage ist unbekannt oder kommt doppelt vor – Seite neu laden.")
            gesehen.add(frage_id)
            eintraege.append({"frage_id": frage_id, "antwort": text})
        if not eintraege:
            return ziel("keine_antwort")
        if len(eintraege) > MAX_ANTWORTEN:
            return ungueltig(f"Mehr als {MAX_ANTWORTEN} Antworten auf einmal.")
        if any(len(x["antwort"]) > ANTWORT_MAX or "\n" in x["antwort"] for x in eintraege):
            return ziel("antwort_ungueltig")
        kennung = request.path_params["bid"]
        daten = {"fassung": fassung, "antworten": eintraege, "von": _von(ui._ui_akteur(request))}
        return await abschicken(
            f"/bewerbungen/{urllib.parse.quote(kennung, safe='')}/antworten", daten, ANTWORTEN_ZEITLIMIT_S,
            "die Antworten erfasst wurden", "antworten_erfasst",
            lambda r: r.get("status") == _ERFOLG["antworten"],
            f"Bewerbung {kennung!r} Fassung {fassung}: Ausgang von antworten")

    @ui._gesichert_seite
    async def lauf_starten(request):
        _, fehler = await formular(request)
        if fehler is not None:
            return fehler
        return await abschicken(
            "/laeufe", {"von": _von(ui._ui_akteur(request))}, LAUF_ZEITLIMIT_S,
            "der Lauf angefordert wurde", "lauf_gestartet",
            lambda r: isinstance(r.get("lauf"), dict), "Lauf anfordern: Ausgang")

    @ui._gesichert_seite
    async def lauf_beenden(request):
        _, fehler = await formular(request)
        if fehler is not None:
            return fehler
        kennung = request.path_params["lauf_id"]
        return await abschicken(
            f"/laeufe/{urllib.parse.quote(kennung, safe='')}/abbrechen",
            {"von": _von(ui._ui_akteur(request))}, LAUF_ABBRECHEN_ZEITLIMIT_S,
            "der Lauf abgebrochen wurde", "lauf_abgebrochen",
            lambda r: isinstance(r.get("lauf"), dict), f"Lauf {kennung!r} abbrechen: Ausgang")

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
        Route(ADMIN_PFAD + "/{bid}/stoppen", stoppen, methods=["POST"]),
        Route(ADMIN_PFAD + "/not-aus/setzen", not_aus_setzen, methods=["POST"]),
        Route(ADMIN_PFAD + "/not-aus/loesen", not_aus_loesen, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/feedback", feedback, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/versandziel", versandziel, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/antworten", antworten, methods=["POST"]),
        Route(ADMIN_PFAD + "/lauf", lauf_starten, methods=["POST"]),
        Route(ADMIN_PFAD + "/lauf/{lauf_id}/abbrechen", lauf_beenden, methods=["POST"]),
        Route(ADMIN_PFAD + "/{bid}/anschreiben.pdf", anschreiben_pdf),
    ]
