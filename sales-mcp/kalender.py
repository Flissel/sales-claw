"""Termine: ICS-Datei nach RFC 5545 und der optionale Eintrag im Kalender.

Ein eigenes Modul aus demselben Grund wie `recherche.py`: hier steht
Textbau und HTTP — keine Datenbank, kein Werkzeug, kein Rueckimport auf
`server.py`. Damit ist der ICS-Text ohne Datenbank testbar, und der einzige
neue ausgehende Pfad dieser Stufe (CalDAV-PUT) liegt an EINER Stelle, an
der man ihn ansehen kann.

ZWEI DINGE, DIE HIER PASSIEREN — und was sie NICHT sind
-------------------------------------------------------
1. `ics(...)` baut den Text einer Kalenderdatei. Sie entsteht in `/reports`
   (der einzige beschreibbare Bind), nicht in `/media`: was versendet
   werden kann, legt ausschliesslich ein Mensch ab (Begruendung in
   medien.py). Wer die Datei an eine Nachricht haengen will, kopiert sie
   von Hand nach `media\\` — ein dokumentierter Handgriff, kein neuer Mount.
2. `eintragen(...)` schreibt denselben Text per HTTP PUT in den CalDAV-
   Kalender des BETREIBERS. Das ist Selbstorganisation, keine
   Kundenkommunikation: es beruehrt weder `drafts` noch das Freigabe-Gate,
   und das Ziel ist ausschliesslich die konfigurierte `CALDAV_URL` aus der
   `.env` — NIE eine Adresse aus Lead- oder Kundendaten.

Ohne `CALDAV_URL`/`CALDAV_USER`/`CALDAV_PASSWORT` ist Punkt 2 inert: es
entsteht nur die Datei, und der Aufrufer sagt es im Hinweis. Kein Fehler,
keine Ueberraschung — genau die Bauart des Mail-Dienstes.

DIE WAF-KANTE (gemessen 2026-08-19, Namecheap PrivateEmail)
-----------------------------------------------------------
`dav.privateemail.com` steht hinter einer Web Application Firewall, die
Anfragen mit der VORGABE-Kennung von urllib (`Python-urllib/3.12`)
rundheraus mit HTTP 403 beantwortet — unabhaengig von den Zugangsdaten. Ein
frueherer Messdurchgang las dieses 403 als „das App-Passwort deckt DAV
nicht ab". Das war falsch: dasselbe Passwort, dasselbe Ziel, nur ein
gesetzter User-Agent, und der Server antwortet mit HTTP 207.

Gesperrt ist genau diese eine Kennung, nicht „Nicht-Browser" — die
vollstaendige Messreihe steht bei `CALDAV_USER_AGENT` unten. Der Header ist
damit Betriebsvoraussetzung, nicht Kosmetik.

RFC 5545, das Wesentliche und warum es hier so steht
----------------------------------------------------
* Zeilenende ist CRLF (§3.1) — nicht LF. Der gehaertete Schreiber oeffnet
  mit `newline="\\n"`, uebersetzt also nichts; die CRLF stehen deshalb
  woertlich im Text.
* Lange Zeilen werden auf 75 Oktette gefaltet, Folgezeilen beginnen mit
  einem Leerzeichen (§3.1). Ein langer SUMMARY („Thema — Kundenname")
  reisst sonst strenge Parser ab.
* In TEXT-Werten sind `\\`, `;`, `,` und Zeilenumbruch zu maskieren
  (§3.3.11). Der Doppelpunkt ausdruecklich NICHT.
* `DTSTART;TZID=Europe/Berlin` braucht einen VTIMEZONE-Block im selben
  VCALENDAR. Outlook-Varianten lehnen eine TZID-Referenz ohne ihn ab —
  deshalb steht die Definition unten fest im Modul und wird nicht aus der
  Systemzeitzone abgeleitet.
* KEIN `METHOD:`. RFC 5545 wuerde `METHOD:PUBLISH` in einer
  veroeffentlichten Datei erlauben, RFC 4791 §4.1 verbietet es in einem
  Kalenderobjekt auf einem CalDAV-Server — SabreDAV weist den PUT sonst
  mit HTTP 415 zurueck (live gemessen). Ohne die Zeile ist EIN Text
  beides: anhaengbare Datei und Kalendereintrag. Begruendung am Code.
"""
import base64
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# Ortszeit fuer DTSTART-Werte ohne (oder mit unbekannter) Zone — dieselbe
# Quelle und derselbe Fallback wie ui.ZEITZONE (10.09.2026, Aufgabe 3):
# unabhaengiges Modul (siehe Moduldocstring), daher eigene, aber identisch
# hergeleitete Zone statt eines Rueckimports aus ui.py.
#
# Import und Instanziierung bewusst GETRENNT abgesichert: eine ungueltige
# `TZID` aus einem fremden VEVENT (unten, `_ics_zeit`) darf `ZoneInfo`
# selbst nicht global lahmlegen — sonst risse eine kaputte Fremdzone auch
# die Standardzone Europe/Berlin mit.
try:
    from zoneinfo import ZoneInfo
except Exception:                    # noqa: BLE001 — kein zoneinfo verfuegbar
    ZoneInfo = None
try:
    _ORTSZONE = (ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
                 if ZoneInfo is not None else None)
except Exception:                    # noqa: BLE001 — ohne tzdata: UTC
    _ORTSZONE = None


def ortszone():
    """Oeffentlicher Zugriff auf dieselbe Zone wie `_ics_zeit` oben —
    fuer Aufrufer AUSSERHALB dieses Moduls, die eine naive Ortszeit
    lokalisieren muessen, bevor sie sie mit einem `belegungen()`-Ergebnis
    vergleichen (server._kollisionen, Fix-Runde 1 zu Aufgabe 4,
    13.09.2026). `None`, wenn keine Zeitzonendaten verfuegbar sind — der
    Aufrufer faellt dann bewusst auf UTC zurueck, statt hier fehlzuschlagen
    (dieselbe Randbedingung wie `_ics_zeit`s eigener Rueckfall).

    Ein Getter statt eines oeffentlichen Alias-Namens fuer `_ORTSZONE`: die
    uebrigen Aufrufer dieses Moduls benutzen ausschliesslich benannte
    Funktionen (`ics`, `eintragen`, `termine_lesen`, ...), nie ein internes
    Attribut direkt — ein Unterstrich-Name bedeutet hier „modul-intern",
    und das soll ueber die Modulgrenze hinweg so bleiben.
    """
    return _ORTSZONE

# 20 s wie im Plan. Ein Kalendereintrag ist Beiwerk des Werkzeugs: er darf
# einen Werkzeugaufruf nicht laenger aufhalten, als ein Mensch im Chat
# wartet — die ICS-Datei entsteht ohnehin unabhaengig davon.
TIMEOUT_S = float(os.environ.get("CALDAV_TIMEOUT_S", "20"))

# Rueckgabe-Zustaende von `eintragen` (statt roher Zeichenketten an drei
# Stellen — die Tests und server.py vergleichen gegen diese Namen).
NICHT_KONFIGURIERT = "nicht_konfiguriert"
EINGETRAGEN = "eingetragen"
FEHLGESCHLAGEN = "fehlgeschlagen"

FEHLER_MAXLAENGE = 300

# Nur diese beiden Schemata. Die URL kommt zwar aus der `.env` des
# Betreibers und nicht aus Fremddaten — aber `urllib` spricht auch `file:`
# und `ftp:`, und ein Tippfehler soll nicht dazu fuehren, dass ein PUT
# irgendwo im Dateisystem landet. Kosten: eine Zeile.
_SCHEMATA = ("http", "https")

# BETRIEBSVORAUSSETZUNG, keine Kosmetik — siehe „Die WAF-Kante" im Kopf.
# Gemessen am 19.08.2026 aus dem Container gegen dav.privateemail.com,
# siebenmal dieselbe PROPFIND-Anfrage auf /dav.php/, dieselben
# Zugangsdaten, NUR der User-Agent verschieden:
#
#   (kein Header -> urllib setzt Python-urllib/3.12)     -> 403
#   "Python-urllib/3.12"                                 -> 403
#   "python-requests/2.32"                               -> 207
#   "curl/8.5.0"                                         -> 207
#   "sales-claw/1.0 (CalDAV)"                            -> 207
#   "Mozilla/5.0 (compatible; sales-claw/1.0; CalDAV)"   -> 207
#   "X"                                                  -> 207
#
# Die Regel ist damit genau bestimmt: die WAF sperrt die VORGABE-Kennung
# von urllib, nicht „Nicht-Browser". Jede eigene Kennung genuegt — sogar
# ein einzelnes Zeichen. Deshalb steht hier die sprechende Kennung des
# Hauses und NICHT die eines fremden Kalenderprogramms: wer in seinem
# Serverlog nachsieht, wer da schreibt, soll es beantwortet bekommen, und
# eine fremde Produktkennung vorzutaeuschen waere ohne jeden Gegenwert.
# Wortgleiche Form wie `FIRMA_USER_AGENT` in recherche.py.
#
# Faellt der Header weg, ist der Kalenderweg tot — und der Fehlertext
# deutete dann auf ein Zugangsproblem, das es nicht gibt (genau diese
# Fehldeutung stand im ersten Messdurchgang). Ueber die Umgebung
# umstellbar, falls ein anderer Anbieter etwas anderes verlangt.
CALDAV_USER_AGENT = os.environ.get(
    "CALDAV_USER_AGENT",
    "Mozilla/5.0 (compatible; sales-claw/1.0; CalDAV)")

# Europe/Berlin als VTIMEZONE. Die Regeln sind seit 1996 unveraendert
# (EU-Richtlinie 2000/84/EG: letzter Sonntag im Maerz 02:00 -> 03:00,
# letzter Sonntag im Oktober 03:00 -> 02:00). Fest im Modul statt aus
# `zoneinfo` abgeleitet: die Datei soll bei einem Empfaenger dasselbe
# bedeuten wie bei uns, unabhaengig davon, welche tzdata-Fassung in
# welchem Container liegt.
VTIMEZONE = (
    "BEGIN:VTIMEZONE",
    "TZID:Europe/Berlin",
    "X-LIC-LOCATION:Europe/Berlin",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
)

TZID = "Europe/Berlin"
PRODID = "-//sales-claw//Terminbestaetigung//DE"

# Die DESCRIPTION ist bewusst nichtssagend. Die Datei kann beim Kunden
# landen (er bekommt sie im Zweifel als Anhang) — Bedarfsangaben, Notizen
# oder gar eine Einschaetzung haetten dort nichts verloren.
#
# Echter Umlaut (12.09.2026, im ersten echten Durchgang gefunden): hier
# stand "ueber". Der Waechter-Test aus Stufe 1 bewacht nur `ui.py` — dieser
# Text hier steht in JEDER Einladung, die je einen Kunden erreicht, und ist
# damit sichtbarer als jede Bildschirmzeile. ICS ist UTF-8 (CHARSET im
# Mailteil, `_falte` zaehlt Oktetts), der Umlaut reist also unbeschadet.
BESCHREIBUNG = ("Termin mit unserem Haus. Vereinbart über die "
                "Terminassistenz.")


def _maskiere(text: str) -> str:
    """RFC 5545 §3.3.11: Backslash zuerst, dann Semikolon, Komma, Umbruch.

    Die Reihenfolge ist keine Kosmetik — wer den Backslash zuletzt ersetzt,
    verdoppelt die eben erst erzeugten Escapes wieder.
    """
    return (str(text or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n"))


def _falte(zeile: str) -> list:
    """Eine Content-Line auf 75 Oktette falten (§3.1).

    Gezaehlt wird in OKTETTEN, nicht in Zeichen: ein „ü" ist in UTF-8 zwei
    Bytes, und ein Umlaut in einem Kundennamen ist der Normalfall, nicht die
    Ausnahme. Getrennt wird deshalb entlang der UTF-8-Kodierung, aber nie
    mitten in einem Zeichen — sonst entstuende genau an der Faltstelle
    Zeichensalat.
    """
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return [zeile]
    teile, rest = [], roh
    grenze = 75
    while len(rest) > grenze:
        schnitt = grenze
        # Nicht mitten in eine Mehrbyte-Sequenz schneiden: Folgebytes einer
        # UTF-8-Sequenz haben das Bitmuster 10xxxxxx.
        while schnitt > 1 and (rest[schnitt] & 0xC0) == 0x80:
            schnitt -= 1
        teile.append(rest[:schnitt].decode("utf-8"))
        rest = rest[schnitt:]
        grenze = 74          # Folgezeilen tragen ein fuehrendes Leerzeichen
    teile.append(rest.decode("utf-8"))
    return [teile[0]] + [" " + t for t in teile[1:]]


def ics(uid: str, beginn, dauer_minuten: int, summary: str, ort: str = "",
        beschreibung: str = BESCHREIBUNG, jetzt=None) -> str:
    """Eine VEVENT-Kalenderdatei als Text (CRLF, gefaltet, maskiert).

    `beginn` ist eine NAIVE lokale Zeit (Europe/Berlin) — genau das, was der
    Kunde am Telefon sagt („Mittwoch um halb drei"). `dauer_minuten` wird als
    Wandzeit addiert: 60 Minuten ab 14:30 enden um 15:30, auch am Tag der
    Zeitumstellung. Ein Termin, der die Umstellungsnacht zwischen 02:00 und
    03:00 kreuzt, waere damit um eine Stunde daneben — er kommt in einer
    Terminassistenz fuer Beratungsgespraeche nicht vor, und der Preis waere
    eine Abhaengigkeit von der tzdata-Fassung des jeweiligen Containers.
    """
    ende = beginn + timedelta(minutes=int(dauer_minuten))
    stempel = (jetzt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # KEIN `METHOD:` — und das ist gemessen, nicht vergessen. RFC 5545 wuerde
    # `METHOD:PUBLISH` in einer veroeffentlichten Datei erlauben, RFC 4791
    # §4.1 verbietet es in einem Kalenderobjekt auf einem CalDAV-Server.
    # SabreDAV (PrivateEmail) weist den PUT sonst mit HTTP 415 zurueck:
    # „Validation error in iCalendar: A calendar object on a CalDAV server
    # MUST NOT have a METHOD property." Ohne die Zeile ist EINE Fassung
    # beides — anhaengbare Datei und Kalendereintrag —, und was im Kalender
    # steht, ist zeichengleich mit dem, was in reports\ liegt. Zwei
    # Fassungen waeren der teurere Weg gewesen.
    zeilen = ["BEGIN:VCALENDAR",
              "VERSION:2.0",
              f"PRODID:{PRODID}",
              "CALSCALE:GREGORIAN",
              *VTIMEZONE,
              "BEGIN:VEVENT",
              f"UID:{uid}",
              f"DTSTAMP:{stempel:%Y%m%dT%H%M%SZ}",
              f"DTSTART;TZID={TZID}:{beginn:%Y%m%dT%H%M%S}",
              f"DTEND;TZID={TZID}:{ende:%Y%m%dT%H%M%S}",
              f"SUMMARY:{_maskiere(summary)}"]
    if (ort or "").strip():
        zeilen.append(f"LOCATION:{_maskiere(ort)}")
    zeilen += [f"DESCRIPTION:{_maskiere(beschreibung)}",
               "STATUS:CONFIRMED",
               "TRANSP:OPAQUE",
               "END:VEVENT",
               "END:VCALENDAR"]
    gefaltet = [teil for z in zeilen for teil in _falte(z)]
    # Abschliessendes CRLF: eine Content-Line endet laut §3.1 IMMER mit
    # CRLF, auch die letzte.
    return "\r\n".join(gefaltet) + "\r\n"


def _adresse(wert: str) -> str:
    """Eine E-Mail-Adresse fuer ORGANIZER/ATTENDEE — ohne `mailto:`-Praefix.

    Geprueft wird nur das Noetigste: ein @ mit etwas davor und dahinter, und
    keine Zeichen, die eine ICS-Zeile zerlegen koennten. Eine kaputte Adresse
    hier wuerde eine Einladung erzeugen, die kein Mailprogramm zuordnen kann —
    lieber ein Fehler beim Bauen als eine stille Einladung ins Leere.
    """
    kern = (wert or "").strip()
    if kern.lower().startswith("mailto:"):
        kern = kern[7:]
    if "@" not in kern or kern.startswith("@") or kern.endswith("@"):
        raise ValueError(f"keine Adresse: {kern!r}")
    if any(z in kern for z in "\r\n,;:"):
        raise ValueError(f"unerlaubte Zeichen in Adresse: {kern!r}")
    return kern


def ics_einladung(uid: str, beginn, dauer_minuten: int, summary: str,
                  veranstalter: str = "", eingeladene=(), ort: str = "",
                  beschreibung: str = BESCHREIBUNG, jetzt=None,
                  folge: int = 0) -> str:
    """Dieselbe Buchung wie `ics()`, aber als EINLADUNG (RFC 5546).

    Unterschied zur CalDAV-Fassung, und warum es zwei gibt: RFC 4791 §4.1
    VERBIETET `METHOD:` in einem Kalenderobjekt auf einem CalDAV-Server
    (SabreDAV antwortet mit HTTP 415), RFC 5546 VERLANGT es fuer eine
    Einladung. Eine Datei kann nicht beides sein. `ics()` bleibt deshalb
    unveraendert die Fassung fuer den Kalender; diese hier geht per Mail.

    `folge` ist die SEQUENCE: 0 fuer die erste Einladung, bei jeder Aenderung
    derselben Buchung um eins hoeher. Mailprogramme erkennen daran, welche
    Fassung die neuere ist — ohne sie wuerde eine Verschiebung als Dublette
    erscheinen.
    """
    org = _adresse(veranstalter)
    gaeste = [_adresse(e) for e in eingeladene]
    if not gaeste:
        raise ValueError("eine Einladung braucht mindestens einen Eingeladenen")
    folge = int(folge)
    if folge < 0:
        raise ValueError(f"SEQUENCE darf nicht negativ sein: {folge!r}")
    roh = ics(uid, beginn, dauer_minuten, summary, ort=ort,
              beschreibung=beschreibung, jetzt=jetzt)
    # Auf der ENTFALTETEN Fassung arbeiten: `ics()` faltet auf 75 Oktette,
    # und eine eingefuegte Zeile muss danach mitgefaltet werden.
    zeilen = roh.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
    ergebnis = []
    for zeile in zeilen:
        if zeile == "BEGIN:VEVENT":
            ergebnis.append(zeile)
            ergebnis.append(f"ORGANIZER:mailto:{org}")
            for gast in gaeste:
                ergebnis.append(
                    "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
                    f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{gast}")
            ergebnis.append(f"SEQUENCE:{folge}")
            continue
        if zeile == "CALSCALE:GREGORIAN":
            ergebnis.append(zeile)
            ergebnis.append("METHOD:REQUEST")
            continue
        ergebnis.append(zeile)
    gefaltet = [teil for z in ergebnis if z for teil in _falte(z)]
    return "\r\n".join(gefaltet) + "\r\n"


def ics_antwort_lesen(text: str):
    """Eine Antwort auf eine Einladung lesen — oder None.

    Liefert nur bei METHOD:REPLY und METHOD:COUNTER ein Ergebnis; eine
    REQUEST-Datei ist KEINE Antwort und darf nicht als eine durchgehen
    (sonst haette eine weitergeleitete Einladung als Zusage gegolten).

    Gelesen wird auf der ENTFALTETEN Fassung: ein Grund laenger als 75
    Oktette steht sonst ueber mehrere Zeilen und wuerde abgeschnitten.
    Werte laufen durch `_entmaskiere`, sonst steht im Grund ein `\\,` statt
    eines Kommas — derselbe Fehler, der im Lesepfad schon einmal steckte.

    Der TZID-Parameter von DTSTART (nur fuer COUNTER gebraucht) wird ueber
    das vorhandene `_ics_tzid(block, name)` gelesen statt ueber einen
    eigenen zweiten Helfer — der sucht selbst die passende Zeile in einem
    Textblock und entfaltet dabei selbststaendig. `block` ist hier (seit
    K2, Schlusspruefung 11.09.2026) NICHT mehr der ganze Rohtext, sondern
    ausschliesslich der herausgeschnittene VEVENT-Block: eine
    zeitzonenbewusste Kalenderdatei traegt VOR dem Termin einen
    VTIMEZONE-Block mit EIGENEN DTSTART-Zeilen (Sommerzeit-Umstellung,
    `BEGIN:DAYLIGHT`/`BEGIN:STANDARD`) — wer den ganzen Text durchsucht,
    liest deren erste DTSTART-Zeile statt der des Termins. Derselbe Zuschnitt
    wie in `termine_lesen` (die CalDAV-Lesestrecke, dort `_ics_feld`/
    `_ics_tzid(block, ...)` auf dem VEVENT-Block).

    `teilnehmende` (Fix-Runde 2, Koordinator, 11.09.2026, Mangel 1) traegt
    ALLE ATTENDEE-Zeilen, nicht nur die erste: RFC 5546 empfiehlt zwar,
    dass eine Antwort nur den Antwortenden nennt, aber reale
    Mailprogramme spiegeln bei einer Einladung an mehrere oft die
    komplette urspruengliche Liste zurueck und aendern nur EINEN Status.
    Welche Zeile die tatsaechliche Antwort ist, kann diese Funktion allein
    nicht entscheiden — sie kennt nur die Kalenderdatei, nicht den
    Mail-Absender. Die obersten Felder `teilnehmer`/`status` bleiben zur
    Bequemlichkeit die ERSTE ZEILE MIT NICHTLEEREM STATUS (bisheriges
    Verhalten, von den bestehenden Ein-Teilnehmer-Tests abgedeckt); wer
    mehrere Teilnehmer zulassen muss (postfach.py, ueber den Absender der
    Mail), liest `teilnehmende`.
    """
    roh = (text or "")
    if "BEGIN:VCALENDAR" not in roh:
        return None
    entfaltet = roh.replace("\r\n ", "").replace("\r\n\t", "").replace(
        "\n ", "").replace("\n\t", "").replace("\r\n", "\n")
    ergebnis = {"uid": "", "methode": "", "teilnehmer": "", "status": "",
                "grund": "", "folge": 0, "neuer_beginn": None,
                "teilnehmende": []}

    # METHOD ist eine Eigenschaft von VCALENDAR selbst (RFC 5546), nicht von
    # VEVENT — sie liegt bewusst ausserhalb des unten herausgeschnittenen
    # Blocks und wird deshalb weiterhin ueber das GANZE Dokument gesucht.
    for zeile in entfaltet.split("\n"):
        name, _, wert = zeile.partition(":")
        if name.split(";")[0].upper() == "METHOD":
            ergebnis["methode"] = wert.strip().upper()
            break

    # Erst den VEVENT-Block herausschneiden, DANN darin lesen — wie die
    # CalDAV-Lesestrecke es seit Langem macht (`termine_lesen`,
    # `text.split("BEGIN:VEVENT")[1:]` / `teil.split("END:VEVENT", 1)[0]`).
    # Ohne das nimmt die ERSTE DTSTART-Zeile im ganzen Dokument den Vorrang
    # — und eine zeitzonenbewusste Kalenderdatei traegt VOR dem eigentlichen
    # Termin einen VTIMEZONE-Block mit EIGENEN DTSTART-Zeilen
    # (BEGIN:DAYLIGHT/BEGIN:STANDARD, die Sommerzeit-Umstellungsregeln,
    # siehe die Konstante `VTIMEZONE` oben). Gemessenes Symptom (K2,
    # Schlusspruefung 11.09.2026): ein Gegenvorschlag fuer den 02.10.2026
    # wurde als 1970-03-29 gelesen — genau der DTSTART aus BEGIN:DAYLIGHT.
    block = ""
    if "BEGIN:VEVENT" in entfaltet:
        block = entfaltet.split("BEGIN:VEVENT", 1)[1].split(
            "END:VEVENT", 1)[0]

    dtstart_wert = ""
    for zeile in block.split("\n"):
        name, _, wert = zeile.partition(":")
        feld = name.split(";")[0].upper()
        if feld == "UID" and not ergebnis["uid"]:
            ergebnis["uid"] = _entmaskiere(wert.strip())
        elif feld == "SEQUENCE":
            try:
                ergebnis["folge"] = int(wert.strip())
            except ValueError:
                pass
        elif feld == "COMMENT" and not ergebnis["grund"]:
            ergebnis["grund"] = _entmaskiere(wert.strip())
        elif feld == "DTSTART" and not dtstart_wert:
            dtstart_wert = wert.strip()
        elif feld == "ATTENDEE":
            zeilen_status = ""
            for teil in name.split(";")[1:]:
                schluessel, _, inhalt = teil.partition("=")
                if schluessel.upper() == "PARTSTAT":
                    zeilen_status = inhalt.strip().upper()
            adresse = wert.strip()
            if adresse.lower().startswith("mailto:"):
                adresse = adresse[7:]
            adresse = _entmaskiere(adresse)
            ergebnis["teilnehmende"].append(
                {"teilnehmer": adresse, "status": zeilen_status})
            if not ergebnis["status"]:
                ergebnis["status"] = zeilen_status
                ergebnis["teilnehmer"] = adresse
    if ergebnis["methode"] not in ("REPLY", "COUNTER"):
        return None
    if ergebnis["methode"] == "COUNTER" and dtstart_wert:
        ergebnis["neuer_beginn"] = _ics_zeit(
            dtstart_wert, _ics_tzid(block, "DTSTART"))
    return ergebnis


# ---------------------------------------------------------------------------
# CalDAV — optionaler Eintrag im echten Kalender des Betreibers
# ---------------------------------------------------------------------------

def konfiguration():
    """(url, user, passwort) — zur AUFRUFZEIT gelesen, nicht beim Import.

    Gleicher Grund wie bei `recherche.token()`: sonst koennte die Suite den
    unkonfigurierten Fall nicht pruefen, und ein spaeter nachgetragener Wert
    wirkte erst nach einem Neustart.
    """
    return (os.environ.get("CALDAV_URL", "").strip(),
            os.environ.get("CALDAV_USER", "").strip(),
            os.environ.get("CALDAV_PASSWORT", ""))


def _ohne_geheimnis(text: str) -> str:
    """Das CalDAV-Passwort darf in keinem Fehlertext landen.

    Dieselbe Klasse Vorfall wie `_ohne_token` in recherche.py: der Text geht
    in die Werkzeug-Antwort, von dort in den Chat und ins Log. Fremde
    Fehlerrumpfe spiegeln Anfragen manchmal zurueck (Proxys, Gateways), und
    eine URL in der Form `https://user:passwort@host/` traegt das Geheimnis
    sogar selbst. Beides wird hier gefiltert.
    """
    _url, _user, passwort = konfiguration()
    if not passwort:
        return text
    return text.replace(passwort, "***").replace(
        urllib.parse.quote(passwort, safe=""), "***")


def _kurz(text: str) -> str:
    """Fehlertext auf `FEHLER_MAXLAENGE` falten — harter Zeichenschnitt,
    keine Wortgrenze. Nur fuer Diagnose-/Fehlermeldungen dieses Moduls.

    Verwechslungsschutz: `ui.py` hat eine GLEICHNAMIGE, aber andere Funktion
    `ui._kurz(text, laenge=90)` fuer Anzeigetexte im Browser — kuerzt an
    Wortgrenzen und haengt „…" an (Aufgabe 7, 10.09.2026). Beide sind
    bewusst getrennt, nicht austauschbar.
    """
    return " ".join((text or "").split())[:FEHLER_MAXLAENGE]


def eintragen(uid: str, ics_text: str):
    """Den Termin per PUT in die konfigurierte Kalender-Kollektion legen.

    Rueckgabe: `(zustand, grund)` — `zustand` ist NICHT_KONFIGURIERT,
    EINGETRAGEN oder FEHLGESCHLAGEN; `grund` traegt bei FEHLGESCHLAGEN einen
    Satz, den der Betreiber versteht.

    `If-None-Match: *` heisst „nur anlegen, nie ueberschreiben": faende sich
    unter demselben Namen bereits ein Eintrag, waere das ein fremder Termin
    (die UID ist eine uuid4) — den still zu ersetzen waere Datenverlust im
    Kalender eines Menschen.

    Es wird NICHTS geworfen: der Aufrufer hat zu diesem Zeitpunkt bereits
    eine gueltige ICS-Datei, und die darf an einem Kalenderproblem nicht
    verloren gehen.
    """
    url, user, passwort = konfiguration()
    if not (url and user and passwort):
        return NICHT_KONFIGURIERT, None
    if urllib.parse.urlsplit(url).scheme not in _SCHEMATA:
        return FEHLGESCHLAGEN, ("CALDAV_URL hat kein http(s)-Schema — es "
                                "wurde nichts abgeschickt.")
    try:
        # Request-Bau IM try (Lehre aus dispatch.py, T5a): eine vertippte
        # URL wirft schon beim Konstruieren, und die Meldung traegt dann die
        # volle URL — die im Zweifel Zugangsdaten enthaelt.
        ziel = f"{url.rstrip('/')}/{uid}.ics"
        anmeldung = base64.b64encode(
            f"{user}:{passwort}".encode("utf-8")).decode("ascii")
        anfrage = urllib.request.Request(
            ziel, method="PUT", data=ics_text.encode("utf-8"),
            headers={"Content-Type": "text/calendar; charset=utf-8",
                     "If-None-Match": "*",
                     # Ohne echte Client-Kennung wirft die WAF von
                     # dav.privateemail.com pauschal 403 (Moduldocstring,
                     # gemessen) — der User-Agent ist hier Funktion, nicht
                     # Kosmetik.
                     "User-Agent": CALDAV_USER_AGENT,
                     # Das Geheimnis reist im Header, nie in argv und nie in
                     # der URL. Geloggt wird von hier aus gar nichts.
                     "Authorization": f"Basic {anmeldung}"})
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            antwort.read()
            code = antwort.status
    except urllib.error.HTTPError as e:      # muss vor URLError stehen
        try:
            rumpf = e.read().decode("utf-8", "replace")
        except Exception:                    # noqa: BLE001 — Rumpf ist Beiwerk
            rumpf = ""
        if e.code in (401, 403):
            return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
                f"Der Kalender weist die Anmeldung zurueck (HTTP {e.code}). "
                f"CALDAV_USER/CALDAV_PASSWORT pruefen — bei Anbietern mit "
                f"App-Passwoertern gilt ein Mail-App-Passwort oft NICHT fuer "
                f"DAV. Antwort: {rumpf}"))
        if e.code == 412:
            return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
                f"Unter dieser UID liegt im Kalender bereits ein Eintrag "
                f"(HTTP 412) — es wurde nichts ueberschrieben. Antwort: "
                f"{rumpf}"))
        return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
            f"Der Kalender lehnt den Eintrag ab (HTTP {e.code}). CALDAV_URL "
            f"muss auf eine Kalender-KOLLEKTION zeigen (…/calendars/<user>/"
            f"<kalender>/). Antwort: {rumpf}"))
    except socket.timeout:
        return FEHLGESCHLAGEN, (f"Kalender antwortet nicht innerhalb von "
                                f"{TIMEOUT_S:g} s.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return FEHLGESCHLAGEN, (f"Kalender antwortet nicht innerhalb von "
                                    f"{TIMEOUT_S:g} s.")
        return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
            f"Kalender nicht erreichbar: {e.reason}"))
    except Exception as e:                   # noqa: BLE001 — nie als Traceback
        return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
            f"Kalenderfehler {type(e).__name__}: {e}"))
    if code in (200, 201, 204):
        # 201 ist der Normalfall (neu angelegt), 204 kommt bei Servern, die
        # kein Ergebnisdokument senden. 200 ist bei PUT unueblich, aber
        # zulaessig — jedes 2xx auf ein PUT heisst „liegt jetzt dort".
        return EINGETRAGEN, None
    return FEHLGESCHLAGEN, (f"Kalender antwortet mit HTTP {code} — der "
                            f"Eintrag ist nicht sicher angelegt.")


# ---------------------------------------------------------------------------
# Lesen (01.09.2026, Betreiber-Wunsch „Kalender als Tab"): der CalDAV-
# Kalender hat kein Web-UI, das man einbetten koennte — seine Eintraege
# holt der Kalender-Tab deshalb selbst. REIN LESEND: ein REPORT-Aufruf,
# kein PUT, kein DELETE. Faellt der Kalender aus, zeigt der Tab die
# Termine aus der eigenen Datenbank und sagt warum der Rest fehlt.
# ---------------------------------------------------------------------------

_ZEITFENSTER_REPORT = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    '<C:calendar-query xmlns:D="DAV:" '
    'xmlns:C="urn:ietf:params:xml:ns:caldav">'
    '<D:prop><D:getetag/><C:calendar-data/></D:prop>'
    '<C:filter><C:comp-filter name="VCALENDAR">'
    '<C:comp-filter name="VEVENT">'
    '<C:time-range start="{von}" end="{bis}"/>'
    '</C:comp-filter></C:comp-filter></C:filter>'
    '</C:calendar-query>')


_ICS_ESCAPE = re.compile(r"\\(.)")


def _entmaskiere(text: str) -> str:
    """Kehrt `_maskiere()` um (RFC 5545 §3.3.11): `\\;`, `\\,`, `\\n`/`\\N`
    und `\\\\` werden wieder `;`, `,`, Zeilenumbruch und `\\`.

    Ein gelesenes Feld, das diese Escapes stehen laesst, zeigt der
    Oberflaeche das ICS-Escaping als sichtbaren Text an — und `_e()`
    escapet ein darin verbliebenes „&" beim Rendern obendrauf (gemessen:
    `&amp;amp\\;` auf /kalender, 10.09.2026).
    """
    return _ICS_ESCAPE.sub(
        lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def _ics_feld(block: str, name: str) -> str:
    """Ein Feld aus einem VEVENT — entfaltet, ohne Parameter, entmaskiert."""
    for zeile in block.replace("\r\n ", "").replace("\n ", "").split("\n"):
        zeile = zeile.strip()
        if zeile.upper().startswith(name.upper()):
            rest = zeile[len(name):]
            if rest[:1] in (";", ":"):
                return _entmaskiere(rest.split(":", 1)[-1].strip())
    return ""


_TZID_MUSTER = re.compile(r"(?i)TZID=([^:;]+)")


def _ics_tzid(block: str, name: str) -> str:
    """TZID-Parameter eines Feldes (z. B. 'Europe/Berlin') — leer, wenn
    keiner gesetzt ist. Eigenstaendig neben `_ics_feld`, das Parameter
    bewusst verwirft (dessen Docstring: „ohne Parameter")."""
    for zeile in block.replace("\r\n ", "").replace("\n ", "").split("\n"):
        zeile = zeile.strip()
        if zeile.upper().startswith(name.upper()):
            treffer = _TZID_MUSTER.search(zeile.split(":", 1)[0])
            return treffer.group(1).strip() if treffer else ""
    return ""


def _ics_zeit(wert: str, tzid: str = ""):
    """DTSTART-Wert (+ optionaler TZID-Parameter) -> datetime (UTC) oder
    None. Wirft nie.

    Zonenregeln (RFC 5545 3.3.5), gemessen am Produktionssymptom
    (10.09.2026: derselbe Termin 19:00 in der Vergangen-Tabelle, 21:00 in
    der Kalender-Tabelle):

    * Ein 'Z'-Suffix ist bereits UTC.
    * `TZID=<Zone>` benennt die Zone einer angegebenen ORTSZEIT. Wird der
      Parameter verworfen und der rohe Wert wie UTC gelesen, entsteht
      genau der gemessene Zwei-Stunden-Versatz (TZID=Europe/Berlin,
      September/CEST = UTC+2).
    * Ganz ohne Zone ("floating time") gilt der Wert ebenfalls als
      Ortszeit, nicht als UTC.

    Alle drei Faelle werden hier nach UTC vereinheitlicht, damit der Rest
    der Pipeline (ui._zeit -> astimezone) durchgehend mit bewussten
    Zeitpunkten arbeitet.
    """
    roh = (wert or "").strip()
    ist_utc = roh.endswith("Z")
    roh = roh.rstrip("Z")
    naiv = None
    for muster in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            naiv = datetime.strptime(roh, muster)
            break
        except ValueError:
            continue
    if naiv is None:
        return None
    if ist_utc:
        return naiv.replace(tzinfo=timezone.utc)
    zone = None
    if tzid and ZoneInfo is not None:
        try:
            zone = ZoneInfo(tzid)
        except Exception:            # noqa: BLE001 — unbekannte/kaputte Zone
            zone = None
    if zone is None:
        zone = _ORTSZONE
    if zone is None:                 # ohne tzdata bleibt nur UTC (wie ui.ZEITZONE)
        return naiv.replace(tzinfo=timezone.utc)
    return naiv.replace(tzinfo=zone).astimezone(timezone.utc)


def termine_lesen(tage_zurueck: int = 7, tage_voraus: int = 60):
    """Termine aus dem CalDAV-Kalender -> (liste, fehler).

    `liste` = [{"beginn": datetime, "ende": datetime, "titel": str,
    "ort": str, "uid": str}], aufsteigend. Rein lesend; wirft nie — ein
    Kalenderproblem darf den Tab nicht kosten, es kostet nur die
    Fremdtermine.
    """
    url, user, passwort = konfiguration()
    if not (url and user and passwort):
        return [], None          # nicht konfiguriert ist kein Fehler
    jetzt = datetime.now(timezone.utc)
    rumpf = _ZEITFENSTER_REPORT.format(
        von=(jetzt - timedelta(days=tage_zurueck)).strftime("%Y%m%dT%H%M%SZ"),
        bis=(jetzt + timedelta(days=tage_voraus)).strftime("%Y%m%dT%H%M%SZ"))
    try:
        anmeldung = base64.b64encode(
            f"{user}:{passwort}".encode("utf-8")).decode("ascii")
        anfrage = urllib.request.Request(
            url, method="REPORT", data=rumpf.encode("utf-8"),
            headers={"Content-Type": 'application/xml; charset="utf-8"',
                     "Depth": "1",
                     "User-Agent": CALDAV_USER_AGENT,
                     "Authorization": f"Basic {anmeldung}"})
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            text = antwort.read().decode("utf-8", "replace")
    except Exception as e:       # noqa: BLE001 — Netz, HTTP, Zeitgrenze
        return [], _ohne_geheimnis(_kurz(
            f"Kalender nicht erreichbar ({type(e).__name__})."))

    termine = []
    for teil in text.split("BEGIN:VEVENT")[1:]:
        block = teil.split("END:VEVENT", 1)[0]
        beginn = _ics_zeit(_ics_feld(block, "DTSTART"),
                           _ics_tzid(block, "DTSTART"))
        if beginn is None:
            continue
        ende = _ics_zeit(_ics_feld(block, "DTEND"),
                         _ics_tzid(block, "DTEND"))
        termine.append({
            "beginn": beginn,
            # Ergaenzt 12.09.2026: DTEND wurde im Baum bis dahin nur
            # GESCHRIEBEN (ics()), nie gelesen — ohne Endzeit laesst sich
            # keine Ueberlappung berechnen (Spec §2.2). Nur ERGAENZT, die
            # beiden Anzeigestellen in ui.py bleiben unberuehrt.
            # Fehlt DTEND, gilt der Termin als punktuell statt geraten.
            "ende": ende if ende and ende > beginn else beginn,
            "titel": _ics_feld(block, "SUMMARY")[:200],
            "ort": _ics_feld(block, "LOCATION")[:120],
            "uid": _ics_feld(block, "UID")[:120]})
    termine.sort(key=lambda t: t["beginn"])
    return termine, None


def loeschen(uid: str):
    """Einen Eintrag aus der Kalender-Kollektion entfernen -> (zustand,
    grund). Fuer Absagen: ein abgesagter Termin, der im Handy des
    Betreibers stehen bleibt, ist schlimmer als gar keiner. Wirft nie —
    die Absage im Protokoll gilt auch dann, wenn der Kalender klemmt.
    Ein 404 ist KEIN Fehler: der Eintrag ist dann schon weg."""
    url, user, passwort = konfiguration()
    if not (url and user and passwort):
        return NICHT_KONFIGURIERT, None
    try:
        ziel = f"{url.rstrip('/')}/{uid}.ics"
        anmeldung = base64.b64encode(
            f"{user}:{passwort}".encode("utf-8")).decode("ascii")
        anfrage = urllib.request.Request(
            ziel, method="DELETE",
            headers={"User-Agent": CALDAV_USER_AGENT,
                     "Authorization": f"Basic {anmeldung}"})
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            antwort.read()
        return EINGETRAGEN, None
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return EINGETRAGEN, None
        return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
            f"Der Kalender lehnt das Loeschen ab (HTTP {e.code})."))
    except Exception as e:      # noqa: BLE001 — Netz, Zeitgrenze, Protokoll
        return FEHLGESCHLAGEN, _ohne_geheimnis(_kurz(
            f"Kalender nicht erreichbar ({type(e).__name__})."))
