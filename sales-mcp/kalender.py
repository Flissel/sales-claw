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
BESCHREIBUNG = ("Termin mit unserem Haus. Vereinbart ueber die "
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


def _ics_zeit(wert: str):
    """DTSTART-Wert -> datetime (UTC) oder None. Wirft nie."""
    roh = (wert or "").strip().rstrip("Z")
    for muster in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(roh, muster).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def termine_lesen(tage_zurueck: int = 7, tage_voraus: int = 60):
    """Termine aus dem CalDAV-Kalender -> (liste, fehler).

    `liste` = [{"beginn": datetime, "titel": str, "ort": str, "uid": str}],
    aufsteigend. Rein lesend; wirft nie — ein Kalenderproblem darf den
    Tab nicht kosten, es kostet nur die Fremdtermine.
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
        beginn = _ics_zeit(_ics_feld(block, "DTSTART"))
        if beginn is None:
            continue
        termine.append({
            "beginn": beginn,
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
