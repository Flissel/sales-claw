"""LID-Aufloesung — aus WhatsApps Privacy-Kennung eine Rufnummer machen.

Seit dem 18.08.2026 adressiert WhatsApp die Chats dieser Session fast
durchgehend als `@lid` (Privacy-ID) statt `@c.us` (Rufnummer). Eine `@lid` ist
KEINE Rufnummer — sie sieht nur aus wie eine. Ohne Aufloesung findet
`lead_zu_nummer` keinen Kontakt, und jede eingehende Nachricht landet am
Sammelkontakt „Unbekannte Eingaenge", auch die von langjaehrigen Kunden.

Dieses Modul ist der einzige Ort, an dem gefragt wird, wem eine Kennung
gehoert. Es kennt WEDER die Datenbank NOCH die Werkzeuge — nur HTTP und
`nummern.py` (dasselbe Muster wie `recherche.py`/`kalender.py`, und aus
demselben Grund: `server.py` importiert es, ein Rueckimport waere ein
Zirkelimport). Gespeichert wird nichts hier; das tut `server.py`.

Es geht ueber dieses Modul NIE eine Nachricht raus. Der einzige Aufruf ist ein
GET gegen den eigenen OpenWA-Container — eine Frage, keine Zustellung.

GEMESSENE ENDPUNKT-FAKTEN (20.08.2026, live gegen den laufenden Container;
Herleitung im Plan docs/superpowers/plans/2026-08-20-…-stufe11-einordnung.md,
Quelle openwa/upstream/src/modules/contact/contact.controller.ts:157)
-----------------------------------------------------------------------------

    GET /api/sessions/{OPENWA_SESSION_ID}/contacts/{kennung}/phone
    Header: X-API-Key: {OPENWA_API_KEY}
    200: {"contactId": "183096603361451@lid", "phone": "491729186846"}
         `phone` ist null, wenn die Engine nicht aufloesen kann.

1. **Das `@lid`-Suffix ist Pflicht und muss URL-kodiert werden** (`%40lid`).
   Gemessen: `183096603361451@lid` -> `491729186846`, dieselbe Kennung OHNE
   Suffix -> `phone: null`. Wer nur die Ziffern schickt, bekommt stillschweigend
   Nullen und haelt das faelschlich fuer „nicht aufloesbar". Deshalb baut
   `_ziel` das Suffix selbst an und kodiert mit `quote(..., safe="")`.
2. **`phone` kommt als blanke MSISDN-Ziffern ohne `+`** (`491729186846`) — vor
   jedem Vergleich mit `leads.phone` durch `nummern.py`, wie ueberall sonst.
   Ausdruecklich als `+<ziffern>`, damit die 49-Sonderregel fuer blanke Folgen
   (BLANK_PRAEFIX) gar nicht erst greift und eine oesterreichische Nummer nicht
   als unzustellbar gilt (gleiche Begruendung wie in inbox.py).
3. **Rate-Limit: HTTP 429 nach etwa 10 Abfragen in Folge.** In der
   Deckungsmessung liefen 10 Abfragen durch, die restlichen 6 liefen in 429.
   429 ist deshalb TRANSIENT und wird NIE als Negativergebnis gemeldet
   (`typ=None`, `transient=True`) — sonst braennte sich ein Rate-Limit als
   „nicht aufloesbar" in die Zuordnung ein und die Kennung wuerde nie wieder
   gefragt. Aus demselben Grund gibt es `PAUSE_S` und `mehrere()`.
4. **Die Session muss `ready` sein**, sonst antwortet der ganze contacts-Zweig
   mit HTTP 400 (gemessen bei `disconnected`; der Controller dokumentiert
   zusaetzlich 409 „engine not ready"). Beides ist transient. `bereit()` fragt
   den Sessionstatus VOR der ersten Kennung, damit ein abgemeldetes Handy nicht
   als „16 unaufloesbare Absender" in der Datenbank landet.
5. **Der Endpunkt loest auch Kennungen auf, die noch nicht in OpenWAs
   `lid_mappings` stehen** (gemessen an `187853296390180@lid` ->
   `4917670794980`). Er fragt die Engine aktiv — die SQLite-Tabelle im
   openwa-Container ist also nicht die Obergrenze der Deckung.

GRUPPEN WERDEN NICHT GEFRAGT
---------------------------
`120363421499541820` ist eine Gruppen-Kennung (18-stellig) und liefert
voraussichtlich nie eine Rufnummer. Solche Kennungen kosten sonst je einen
Platz im Rate-Limit-Budget und kaemen jedes Mal als Fehlschlag zurueck.
Erkannt wird das an der Domain (`@g.us`, `@broadcast`, `@newsletter`) und
hilfsweise an der Ziffernzahl: E.164 endet bei 15 Stellen, gemessene LIDs
liegen bei 14–15, die gemessene Gruppen-Kennung bei 18. Ab
GRUPPEN_ZIFFERN_AB = 17 kann es keine Rufnummer mehr sein.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import quote

from nummern import normalisiere_empfaenger

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
# Dieselben Variablen wie im Dispatcher — es gibt genau ein OpenWA und genau
# einen Schluessel; zwei Namen dafuer waeren zwei Wahrheiten.
OPENWA_URL = os.environ.get("OPENWA_URL", "http://openwa:2785")
OPENWA_SESSION_ID = os.environ.get("OPENWA_SESSION_ID", "")
OPENWA_API_KEY = os.environ.get("OPENWA_API_KEY", "")
HTTP_TIMEOUT_S = float(os.environ.get("OPENWA_TIMEOUT_S", "30"))

# Drossel zwischen zwei Abfragen (Punkt 3 oben). 1,5 s heisst: rund 40 Abfragen
# je Minute statt 10 in zwei Sekunden. Die Alternative — volle Fahrt und dann
# Backoff — verbrennt das Budget zuerst und wartet danach; das hier verbrennt
# es gar nicht erst.
PAUSE_S = float(os.environ.get("LID_PAUSE_S", "1.5"))

LID_SUFFIX = "@lid"
NUMMER_SUFFIX = "@c.us"
GRUPPEN_SUFFIXE = ("@g.us", "@broadcast", "@newsletter")
GRUPPEN_ZIFFERN_AB = 17
SESSION_BEREIT = "ready"

# HTTP-Ausgaenge, die ueber die KENNUNG nichts aussagen, sondern ueber den
# Moment: Rate-Limit, nicht bereite Engine, kaputtes Gateway. Sie duerfen nie
# zu einem gespeicherten Negativergebnis werden.
TRANSIENTE_CODES = frozenset((400, 408, 409, 425, 429, 500, 502, 503, 504))

TYP_RUFNUMMER = "rufnummer"
TYP_GRUPPE = "gruppe"
TYP_UNAUFLOESBAR = "unaufloesbar"

FEHLER_KONFIG = ("OPENWA_SESSION_ID/OPENWA_API_KEY fehlen — es wurde nichts "
                 "abgefragt.")
FEHLER_MAXLAENGE = 300


class Ergebnis(NamedTuple):
    """Antwort auf „wem gehoert diese Kennung?".

    `transient=True` heisst ausdruecklich: **nichts gelernt**. Weder positiv
    noch negativ — der Aufrufer darf daraus keine Zuordnung speichern und soll
    spaeter erneut fragen. `typ` ist dann None.
    """
    telefon: str            # normalisiert, "49…@c.us" — oder ""
    roh: str                # blanke MSISDN von OpenWA — oder ""
    typ: str                # rufnummer | gruppe | unaufloesbar — oder ""
    grund: str              # menschenlesbarer Grund — oder ""
    transient: bool


# ---------------------------------------------------------------------------
# Kennungen
# ---------------------------------------------------------------------------

def ziffern(kennung) -> str:
    """Blanke Ziffern einer Kennung — Domain und `:geraet`-Suffix fallen weg."""
    return "".join(z for z in str(kennung or "").split("@", 1)[0].split(":", 1)[0]
                   if z.isdigit())


def ist_gruppe(kennung) -> bool:
    """Gruppe/Broadcast/Newsletter — hat nie eine Rufnummer (siehe Kopf)."""
    roh = str(kennung or "").lower()
    if any(roh.endswith(s) for s in GRUPPEN_SUFFIXE):
        return True
    return len(ziffern(kennung)) >= GRUPPEN_ZIFFERN_AB


def ist_lid(kennung) -> bool:
    return str(kennung or "").lower().endswith(LID_SUFFIX)


def als_lid(kennung) -> str:
    """Kennung -> `<ziffern>@lid`, oder "" wenn keine Ziffern drinstehen.

    Die kanonische Schreibweise einer unaufgeloesten Kennung im ganzen Haus.
    Wichtig, dass sie NICHT `@c.us` lautet: `@c.us` heisst „Rufnummer", und
    eine als Rufnummer ausgegebene LID hat schon einmal dazu verleitet, sie als
    Kontakt anzulegen (Review-Befund H1, docs/03_RUNBOOK.md).
    """
    z = ziffern(kennung)
    return f"{z}{LID_SUFFIX}" if z else ""


def _ohne_schluessel(text: str) -> str:
    """Der API-Schluessel darf in keinem Fehlertext landen — der geht in die
    Antwort des Werkzeugs, von dort in den Chat und ins Log. Fremde
    Fehlerrumpfe spiegeln Anfragen manchmal zurueck (Proxys, Gateways); die
    Zeile kostet nichts und schliesst die Klasse Vorfall aus. Dieselbe
    Vorsorge wie `_ohne_token` in recherche.py."""
    sauber = " ".join((text or "").split())[:FEHLER_MAXLAENGE]
    return sauber.replace(OPENWA_API_KEY, "***") if OPENWA_API_KEY else sauber


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _hole(pfad: str):
    """GET gegen OpenWA -> (objekt, grund, transient).

    Fehlerabbildung wie `dispatch._senden` (dort begruendet): HTTPError VOR
    URLError, Timeout getrennt, und am Ende ein breiter Fang — dieses Modul
    darf einen Werkzeugaufruf nie als Traceback beenden.
    """
    if not OPENWA_SESSION_ID or not OPENWA_API_KEY:
        return None, FEHLER_KONFIG, True
    try:
        anfrage = urllib.request.Request(
            f"{OPENWA_URL.rstrip('/')}{pfad}", method="GET",
            headers={"Accept": "application/json",
                     "X-API-Key": OPENWA_API_KEY})
        with urllib.request.urlopen(anfrage, timeout=HTTP_TIMEOUT_S) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as e:      # muss vor URLError stehen
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:                    # noqa: BLE001 — Detail ist Beiwerk
            detail = ""
        return None, (f"OpenWA HTTP {e.code}: {_ohne_schluessel(detail)}"
                      .strip()), e.code in TRANSIENTE_CODES
    except socket.timeout:                   # ab 3.10 identisch mit TimeoutError
        return None, f"OpenWA Zeitueberschreitung nach {HTTP_TIMEOUT_S:g} s", True
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return None, (f"OpenWA Zeitueberschreitung nach "
                          f"{HTTP_TIMEOUT_S:g} s"), True
        return None, (f"OpenWA nicht erreichbar: "
                      f"{_ohne_schluessel(str(e.reason))}"), True
    except Exception as e:                   # noqa: BLE001 — nie als Traceback
        return None, (f"Abruffehler {type(e).__name__}: "
                      f"{_ohne_schluessel(str(e))}"), True
    try:
        objekt = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "OpenWA antwortete kein JSON", True
    if not isinstance(objekt, dict):
        return None, "OpenWA antwortete in unerwarteter Form", True
    return objekt, "", False


def sessionstatus():
    """(status, grund) — der Sessionstatus von OpenWA, ohne Deutung."""
    objekt, grund, _transient = _hole(f"/api/sessions/{OPENWA_SESSION_ID}")
    if grund:
        return "", grund
    return str(objekt.get("status") or ""), ""


def bereit() -> str:
    """"" wenn die Session `ready` ist, sonst der Grund, warum nicht.

    Vorpruefung vor jeder Aufloesungsrunde (Punkt 4 im Kopf): ein abgemeldetes
    Handy laesst den ganzen contacts-Zweig mit 400 antworten. Ohne diese
    Pruefung liesse sich das nicht von „Kennung unbekannt" unterscheiden, und
    eine Runde schriebe 16 Negativergebnisse in die Datenbank, die keine sind.
    """
    status, grund = sessionstatus()
    if grund:
        return f"Sessionstatus nicht lesbar: {grund}"
    if status != SESSION_BEREIT:
        return (f"OpenWA-Session ist '{status}', nicht '{SESSION_BEREIT}' — "
                f"Kennungen lassen sich gerade nicht aufloesen. Es wurde "
                f"nichts abgefragt und nichts gespeichert.")
    return ""


# ---------------------------------------------------------------------------
# Aufloesung
# ---------------------------------------------------------------------------

def aufloesen(kennung) -> Ergebnis:
    """Eine Kennung -> Ergebnis. Fragt OpenWA genau einmal.

    Gruppen werden gar nicht erst gefragt (siehe Kopf), und ein 429 kommt als
    `transient` zurueck — nicht als Negativergebnis.
    """
    z = ziffern(kennung)
    if not z:
        return Ergebnis("", "", TYP_UNAUFLOESBAR,
                        "Kennung ohne Ziffern", False)
    if ist_gruppe(kennung):
        return Ergebnis("", "", TYP_GRUPPE,
                        "Gruppen-/Broadcast-Kennung — hat keine Rufnummer",
                        False)

    ziel = (f"/api/sessions/{OPENWA_SESSION_ID}/contacts/"
            f"{quote(z + LID_SUFFIX, safe='')}/phone")
    objekt, grund, transient = _hole(ziel)
    if grund:
        return Ergebnis("", "", "" if transient else TYP_UNAUFLOESBAR,
                        grund, transient)

    roh = objekt.get("phone")
    if not roh:
        return Ergebnis("", "", TYP_UNAUFLOESBAR,
                        "OpenWA konnte die Kennung nicht aufloesen "
                        "(phone: null)", False)
    # Blanke MSISDN (Punkt 2 im Kopf) — ausdruecklich als `+<ziffern>`.
    telefon, fehler = normalisiere_empfaenger("+" + ziffern(roh))
    if fehler:
        return Ergebnis("", str(roh), TYP_UNAUFLOESBAR,
                        f"OpenWA lieferte '{ziffern(roh)}': {fehler}", False)
    return Ergebnis(telefon, ziffern(roh), TYP_RUFNUMMER, "", False)


def mehrere(kennungen, pause=None):
    """Kennungen der Reihe nach aufloesen — mit Drossel, Abbruch bei transient.

    Generator ueber `(kennung, Ergebnis)`. Zwischen zwei ABFRAGEN wird
    `PAUSE_S` gewartet; nach einer Gruppe nicht, denn die hat das Netz nie
    beruehrt (gleiche Regel wie die Sendepause im Dispatcher). Beim ersten
    transienten Ausgang bricht der Lauf ab: nach einem 429 laufen die
    folgenden Abfragen ohnehin in denselben Fehler, und jede weitere macht die
    Sperre nur laenger.
    """
    warte = PAUSE_S if pause is None else pause
    gefragt = False
    for kennung in kennungen:
        # Nur was OpenWA wirklich fragt, kostet Budget — eine Gruppe und eine
        # Kennung ohne Ziffern beantwortet dieses Modul selbst.
        netz = bool(ziffern(kennung)) and not ist_gruppe(kennung)
        if gefragt and netz and warte > 0:
            time.sleep(warte)
        ergebnis = aufloesen(kennung)
        gefragt = gefragt or netz
        yield kennung, ergebnis
        if ergebnis.transient:
            return
