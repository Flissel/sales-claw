"""Abonnierte FREMDE Kalender — rein lesend, ohne Zugangsdaten.

Abgrenzung zu `kalender.py`: dort steht der EIGENE Kalender, schreibend,
mit Zugangsdaten aus der `.env`. Hier stehen die Kalender der Kollegen,
die ueber eine geheime iCal-Adresse abonniert werden (Spec
`2026-09-11-team-terminabstimmung-design.md` §2.1 Weg 3). Zwei Wege, zwei
Module — die Zerleger werden aus `kalender` IMPORTIERT, nicht abgeschrieben,
damit es nicht zwei Auffassungen davon gibt, was ein DTSTART bedeutet.

DIE ADRESSE IST EIN GEHEIMNIS. Sie traegt ihre Berechtigung in sich: wer
sie kennt, liest den Kalender vollstaendig, ohne Anmeldung. Jeder
Fehlertext laeuft deshalb durch `ohne_adresse` — dieselbe Klasse wie
`kalender._ohne_geheimnis` fuer das CalDAV-Passwort.

KEINE DATENBANK. Wie `medien.py` und `recherche.py`: das Modul ist ohne
Datenbank testbar, die Zugriffe liegen in `server.py`.

SSRF-SCHLUSS (Fix-Runde 1, 2026-09-13): die Adresse kommt kuenftig nicht vom
Betreiber, sondern von einem Kollegen mit einer absichtlich schmalen Rolle,
der ueber eine Selbstbedienungsseite seinen Kalender verbindet. Ein
ungepruefter Abruf in genau dieser einen Schreibaktion waere ein Fenster ins
interne Netz der VM — dieselbe Klasse Schreibaktion wie
`recherche._ziel_erlaubt` (dort aus einem Google-Maps-Datensatz gespeist,
hier aus der Kollegen-Selbstbedienung). Der dortige Loesungsweg wird
uebernommen: Hostname aufloesen, JEDE zurueckgegebene Adresse pruefen, jeden
Weiterleitungssprung erneut. Eine Abweichung bewusst: dort schliesst
`FIRMA_PRIVATE_ZIELE_ERLAUBT` sich an eine Positivliste einzelner Flags an
(is_loopback/is_private/...); die wurde dort per Review-Befund S2
NACHTRAEGLICH auf `is_global` umgestellt, weil die Flag-Liste
100.64.0.0/10 (CGNAT) durchliess. Hier wird gleich mit `is_global`
begonnen, um denselben Fehler nicht zu wiederholen. Keine Portbeschraenkung
(anders als bei recherche.py): eine Firmenwebsite antwortet auf 80/443, ein
Kollege koennte seinen Kalender ueber einen Anbieter auf einem anderen Port
freigeben, und eine 80/443-Regel wuerde echte Quellen abweisen.
"""
import ipaddress
import math
import multiprocessing
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import icalendar
import recurring_ical_events

import kalender

# 5 MB. Ein Jahreskalender mit einigen hundert Terminen liegt bei wenigen
# hundert Kilobyte; alles darueber ist entweder ein Irrtum oder ein Ziel,
# das uns vollaeuft. Gelesen wird hoechstens so viel — nicht erst geprueft,
# nachdem alles im Speicher liegt.
MAX_BYTES = 5 * 1024 * 1024

_SCHEMATA = ("http", "https")

# Wie beim CalDAV-Weg: Zeitgrenze und eigene Kennung. Ein fremder Anbieter
# darf die Vorgabe-Kennung von urllib genauso abweisen wie die WAF vor
# dav.privateemail.com es tut (Messreihe im Kopf von kalender.py).
TIMEOUT_S = kalender.TIMEOUT_S
USER_AGENT = kalender.CALDAV_USER_AGENT

FEHLER_MAXLAENGE = 300

# Obergrenze fuer Vorkommen je Abruf (Schutz vor feindlichen Serienregeln).
MAX_VORKOMMEN = 5000

# Obergrenze fuer die Schritte, die die Bibliothek von DTSTART bis zum
# Fensterende gehen muesste. `paginate` kappt nur die AUSGABE, nicht die
# Arbeit davor: FREQ=SECONDLY ab dem Jahr 2000 laeuft sonst Minuten bis
# Stunden und blockiert den Abgleich und die Seite.
MAX_ITERATIONEN = 200_000

_PERIODE_S = {
    "HOURLY": 3600.0, "DAILY": 86400.0, "WEEKLY": 604800.0,
    "MONTHLY": 2.6e6, "YEARLY": 3.15e7,
}
_VERVIELFACHER = ("BYSECOND", "BYMINUTE", "BYHOUR", "BYMONTHDAY",
                  "BYYEARDAY", "BYMONTH")

# Gesamtbudget ueber ALLE Serien eines Kalenders und Obergrenze fuer die
# Zahl der Serien (viele Termine knapp unter der Einzelgrenze addieren sich).
MAX_SERIEN = 2000

# Harte Zeitgrenze fuer das Aufklappen in einem Kindprozess — die eigentliche
# Garantie; der Vorab-Filter ist nur die billige erste Stufe.
KALENDER_AUFKLAPP_TIMEOUT_S = 15
ZEITLIMIT_FEHLER = ("Kalender zu aufwendig zum Lesen (Zeitlimit) — "
                    "nicht abgeglichen.")

# NUR fuer Tests — MUSS in Produktion IMMER False bleiben. Ein "1" hier
# schaltet die komplette Ziel-Pruefung unten ab (siehe `_ziel_erlaubt`) und
# liesse `hole()` gegen 127.0.0.1 und jedes interne Netz abrufen. Die
# server_stub-Fixture in test_kalenderquellen.py setzt sie per
# `monkeypatch.setattr` und damit automatisch zurueckgesetzt — nur so kommt
# der lokale Test-HTTP-Server auf 127.0.0.1 ueberhaupt an die Pruefung
# vorbei. Gleiches Muster wie `recherche.FIRMA_PRIVATE_ZIELE_ERLAUBT`.
PRIVATE_ZIELE_ERLAUBT = os.environ.get("KALENDERQUELLEN_PRIVATE_ZIELE", "") == "1"


class _ZielAbgewiesen(Exception):
    """Eine Weiterleitung zeigte aus dem oeffentlichen Netz heraus.

    Eigene Klasse statt HTTPError: der Fall ist kein Fehler des fremden
    Anbieters, sondern unsere eigene Kante — er darf nicht in der
    HTTP-Fehlerabbildung landen, die von Anbieterstoerungen spricht.
    """


def _ziel_erlaubt(url: str):
    """Darf diese Adresse abgerufen werden? -> (True, None) | (False, grund).

    Wirft nie (Fix-Runde 1, KRITISCH 1): `urllib.parse.urlsplit` wirft bei
    kaputten IPv6-Literalen wie 'http://exa[mple.com/...' ein
    'ValueError: Invalid IPv6 URL' — live nachgestellt, ausserhalb eines
    try haette das die aufrufende Seite abgerissen statt eine Meldung zu
    liefern. Auch der Zugriff auf `.hostname`/`.port` kann bei kaputter
    Portsyntax ("...:abc") noch einmal ValueError werfen — derselbe Fang.
    """
    try:
        teile = urllib.parse.urlsplit(url)
    except ValueError as e:
        return False, f"Adresse nicht lesbar ({type(e).__name__})."
    if teile.scheme not in _SCHEMATA:
        return False, ("Die Adresse muss mit http:// oder https:// beginnen — "
                       f"gefunden wurde '{teile.scheme or 'nichts'}'.")
    try:
        gastgeber = teile.hostname
        port = teile.port or (443 if teile.scheme == "https" else 80)
    except ValueError as e:
        return False, f"Adresse nicht lesbar ({type(e).__name__})."
    if not gastgeber:
        return False, "die Adresse nennt keinen Hostnamen."
    if PRIVATE_ZIELE_ERLAUBT:
        return True, None
    try:
        infos = socket.getaddrinfo(gastgeber, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError, OSError) as e:
        return False, (f"der Hostname '{gastgeber}' ist nicht aufloesbar "
                       f"({type(e).__name__}).")
    for info in infos:
        try:
            adresse = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except ValueError:
            return False, f"unlesbare IP-Adresse zu '{gastgeber}'."
        if not adresse.is_global:
            return False, (f"'{gastgeber}' zeigt auf {adresse} — ein Ziel im "
                           f"eigenen Netz. Dort liegt kein Kalender eines "
                           f"Kollegen.")
    return True, None


class _GepruefteWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Prueft JEDEN Weiterleitungssprung, nicht nur die Startadresse.

    Ohne das waere `_ziel_erlaubt` wirkungslos: eine oeffentlich erreichbare
    Adresse darf mit HTTP 302 auf 127.0.0.1 zeigen, und urllib folgt von
    sich aus.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        erlaubt, grund = _ziel_erlaubt(newurl)
        if not erlaubt:
            raise _ZielAbgewiesen(grund)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _antwort_lesen(url: str):
    """Die Verbindung oeffnen — ausgelagert, damit Tests sie ohne Netz und
    ohne Namensdienstabfrage ersetzen koennen (Fix-Runde 1, KRITISCH 2)."""
    anfrage = urllib.request.Request(
        url, method="GET", headers={"User-Agent": USER_AGENT})
    oeffner = urllib.request.build_opener(_GepruefteWeiterleitung)
    return oeffner.open(anfrage, timeout=TIMEOUT_S)


def ohne_adresse(text: str, url: str) -> str:
    """Die Adresse aus einem Fehlertext entfernen — ganz und in Teilen.

    Ganz: manche Bibliotheken haengen die URL an ihre Meldung. In Teilen:
    der Pfad allein genuegt einem Angreifer bereits, wenn er den Host kennt.

    Wirft nie: `url` kann hier bereits eine Adresse sein, die `_ziel_erlaubt`
    als unlesbar abgewiesen hat — ein ungeschuetztes zweites `urlsplit`
    wuerde denselben ValueError reproduzieren, den `_ziel_erlaubt` gerade
    erst abgefangen hat.
    """
    text = (text or "").replace(url, "<Adresse>")
    try:
        zerlegt = urllib.parse.urlsplit(url)
    except ValueError:
        return text[:FEHLER_MAXLAENGE]
    if zerlegt.path and len(zerlegt.path) > 1:
        text = text.replace(zerlegt.path, "<Pfad>")
    if zerlegt.query:
        text = text.replace(zerlegt.query, "<Abfrage>")
    return text[:FEHLER_MAXLAENGE]


def _sieht_aus_wie_kalender(text: str) -> bool:
    return "BEGIN:VCALENDAR" in text[:2000].upper()


def _ortszeit_utc(wert, ortszone) -> datetime:
    """Ein iCal-Zeitwert (date | naiv | zonenbewusst) -> UTC-aware.

    Ein reines Datum (VALUE=DATE, ganztaegig) beginnt um Mitternacht
    ORTSZEIT, nicht UTC: ein Termin am 10.11. soll am 10.11. liegen. Ein
    „schwebender" Wert ohne TZID gilt ebenfalls als Ortszeit.
    """
    zone = ortszone or timezone.utc
    if not isinstance(wert, datetime):
        wert = datetime(wert.year, wert.month, wert.day)
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=zone)
    return wert.astimezone(timezone.utc)


def _serien_uids(kal) -> set:
    """UIDs aller VEVENTs, die zu einer Serie gehoeren (RRULE/RDATE am
    Stamm oder RECURRENCE-ID an einer Abweichung)."""
    uids = set()
    for ev in kal.walk("VEVENT"):
        if (ev.get("RRULE") is not None or ev.get("RDATE") is not None
                or ev.get("RECURRENCE-ID") is not None):
            uids.add(str(ev.get("UID", "")))
    return uids


def _als_utc(wert) -> datetime:
    """date/datetime (naiv oder zonenbewusst) -> UTC-datetime."""
    if isinstance(wert, datetime):
        return (wert.replace(tzinfo=timezone.utc) if wert.tzinfo is None
                else wert.astimezone(timezone.utc))
    return datetime(wert.year, wert.month, wert.day, tzinfo=timezone.utc)


def _hat_ordnungszahl(eintrag) -> bool:
    return bool(re.match(r"^[+-]?\d", str(eintrag)))


def _serie_schritte(ev, bis: datetime) -> float:
    """Geschaetzte Schritte der Serienregel dieses VEVENTs bis `bis`.
    0.0 = keine Serie; inf = nicht aufklappen (Sekunden-/Minutentakt, ohne
    DTSTART, kaputt). Wirft nie."""
    try:
        regeln = ev.get("RRULE")
        if regeln is None:
            return 0.0
        if not isinstance(regeln, list):
            regeln = [regeln]
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            return math.inf
        start = _als_utc(dtstart.dt)
        gesamt = 0.0
        for regel in regeln:
            freq = str((regel.get("FREQ") or [""])[0]).upper()
            if freq in ("SECONDLY", "MINUTELY"):
                return math.inf
            periode = _PERIODE_S.get(freq)
            if periode is None:
                return math.inf
            intervall = int((regel.get("INTERVAL") or [1])[0])
            if intervall < 1:
                return math.inf
            ende = bis
            until = regel.get("UNTIL")
            if until:
                ende = min(ende, _als_utc(until[0]))
            sekunden = max((ende - start).total_seconds(), 0.0)
            schritte = sekunden / (periode * intervall)
            for schluessel in _VERVIELFACHER:
                werte = regel.get(schluessel)
                if werte:
                    schritte *= max(len(werte), 1)
            tage = regel.get("BYDAY") or []
            wochen = regel.get("BYWEEKNO") or []
            enger = any(regel.get(k) for k in
                        ("BYMONTH", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO"))
            if tage:
                gewicht = 1
                if freq == "YEARLY" and not enger:
                    gewicht = 52
                elif freq == "MONTHLY" and not regel.get("BYMONTHDAY"):
                    gewicht = 5
                schritte *= sum(1 if _hat_ordnungszahl(t) else gewicht
                                for t in tage)
            if wochen:
                schritte *= len(wochen) * (7 if freq == "YEARLY"
                                           and not tage else 1)
            gesamt += schritte
        return gesamt
    except Exception:                     # noqa: BLE001 — kaputte Regel
        return math.inf


def _teure_serien_entfernen(kal, bis: datetime) -> int:
    """Entfernt rekursiv jedes VEVENT, das kein direktes Kind des VCALENDAR
    ist (die Bibliothek laeuft rekursiv), jedes zu teure und alle, die das
    Gesamtbudget / die Serien-Obergrenze sprengen -> Anzahl entfernter."""
    stand = {"entfernt": 0, "budget": 0.0, "serien": 0}

    def durch(komp, wurzel):
        behalten = []
        for teil in komp.subcomponents:
            if teil.name == "VEVENT":
                if not wurzel:
                    stand["entfernt"] += 1
                    continue
                schritte = _serie_schritte(teil, bis)
                if schritte > 0:
                    stand["serien"] += 1
                    stand["budget"] += schritte
                    if (schritte > MAX_ITERATIONEN
                            or stand["budget"] > MAX_ITERATIONEN
                            or stand["serien"] > MAX_SERIEN):
                        stand["entfernt"] += 1
                        continue
            durch(teil, False)
            behalten.append(teil)
        komp.subcomponents[:] = behalten

    durch(kal, True)
    return stand["entfernt"]


MAX_BESCHREIBUNG = 4000
MAX_TEILNEHMER = 50
_KONFERENZ_FELDER = ("URL", "X-GOOGLE-CONFERENCE",
                     "X-MICROSOFT-SKYPETEAMSMEETINGURL",
                     "X-MICROSOFT-ONLINEMEETINGCONFLINK")


def _als_liste(wert) -> list:
    if wert is None:
        return []
    return list(wert) if isinstance(wert, (list, tuple)) else [wert]


def _adresse(wert) -> str:
    text = str(wert).strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    return text.strip().lower()


def _teilnehmer_lesen(ev):
    """-> (liste (hoechstens MAX_TEILNEHMER), echte Anzahl). Organisator
    zuerst; steht er auch als ATTENDEE, gilt er einmal als organisator.
    Eintraege ohne Adresse entfallen. Nur schlichte Daten (Kindprozess)."""
    gefunden = {}

    def aufnehmen(wert, organisator):
        adresse = _adresse(wert)
        if not adresse or "@" not in adresse:
            return
        params = getattr(wert, "params", None) or {}
        chair = str(params.get("ROLE", "")).upper() == "CHAIR"
        alt = gefunden.get(adresse)
        if alt is None:
            gefunden[adresse] = {
                "adresse": adresse,
                "name": str(params.get("CN", ""))[:120],
                "rolle": "organisator" if (organisator or chair) else "gast",
                "art": (str(params.get("CUTYPE", "")).lower()
                        or "individual")[:20]}
        elif organisator or chair:
            alt["rolle"] = "organisator"
            alt["name"] = alt["name"] or str(params.get("CN", ""))[:120]

    for w in _als_liste(ev.get("ORGANIZER")):
        aufnehmen(w, True)
    for w in _als_liste(ev.get("ATTENDEE")):
        aufnehmen(w, False)
    alle = list(gefunden.values())
    alle.sort(key=lambda p: p["rolle"] != "organisator")   # stabil
    return alle[:MAX_TEILNEHMER], len(alle)


def _konferenz_lesen(ev) -> str:
    for feld in _KONFERENZ_FELDER:
        for w in _als_liste(ev.get(feld)):
            text = str(w).strip()
            if text:
                return text[:500]
    return ""


def _aufklappen(text: str, von: datetime, bis: datetime):
    """Parsen, Vorab-Filter und Aufklappen — laeuft im Kindprozess. Gibt nur
    schlichte Daten zurueck: (zu_teuer, serien_uids, [(start, ende, uid,
    titel, ort, transp, beschreibung, teilnehmer, anzahl, konferenz)
    | None])."""
    kal = icalendar.Calendar.from_ical(text)
    zu_teuer = _teure_serien_entfernen(kal, bis)
    serien = _serien_uids(kal)
    seiten = recurring_ical_events.of(kal).paginate(
        MAX_VORKOMMEN + 1, earliest_end=von, latest_start=bis)
    roh = []
    for ev in next(iter(seiten), []):
        try:
            teilnehmer, anzahl = _teilnehmer_lesen(ev)
            beschreibung = " ".join(
                str(ev.get("DESCRIPTION", "")).split())[:MAX_BESCHREIBUNG]
            roh.append((ev.start, ev.end, str(ev.get("UID", "")),
                        str(ev.get("SUMMARY", ""))[:200],
                        str(ev.get("LOCATION", ""))[:120],
                        str(ev.get("TRANSP", "")).upper(),
                        beschreibung, teilnehmer, anzahl,
                        _konferenz_lesen(ev)))
        except Exception:                 # noqa: BLE001 — ein Termin, nicht alle
            roh.append(None)
    return zu_teuer, serien, roh


def _kind(verbindung, text, von, bis):
    try:
        verbindung.send(("ok", _aufklappen(text, von, bis)))
    except BaseException as e:            # noqa: BLE001 — nur der Typ geht raus
        try:
            verbindung.send(("fehler", type(e).__name__))
        except Exception:                 # noqa: BLE001
            pass
    finally:
        verbindung.close()


def _aufklappen_mit_zeitgrenze(text: str, von: datetime, bis: datetime):
    """-> ("ok", daten) | ("fehler", Typname) | ("zeit", None).
    Harte Wanduhr-Grenze: ein Kindprozess, der nach Ablauf beendet wird."""
    methoden = multiprocessing.get_all_start_methods()
    ctx = multiprocessing.get_context("fork" if "fork" in methoden else None)
    lesen, schreiben = ctx.Pipe(duplex=False)
    kind = ctx.Process(target=_kind, args=(schreiben, text, von, bis),
                       daemon=True)
    kind.start()
    schreiben.close()
    try:
        if not lesen.poll(KALENDER_AUFKLAPP_TIMEOUT_S):
            return "zeit", None
        try:
            return lesen.recv()
        except (EOFError, OSError):
            return "fehler", "ChildDied"
    finally:
        lesen.close()
        if kind.is_alive():
            kind.terminate()
        kind.join(1)
        if kind.is_alive():
            kind.kill()
            kind.join(1)


def hole(url: str, tage_zurueck: int = 7, tage_voraus: int = 60):
    """Eine abonnierte Adresse abrufen -> (termine, fehler).

    `termine` = [{"beginn", "ende", "titel", "ort", "uid"}], aufsteigend,
    auf ein Zeitfenster begrenzt. Wirft nie: eine unerreichbare Quelle darf
    keine Seite und keinen Werkzeugaufruf kosten, sie kostet nur ihre
    eigenen Termine.

    Zeitfenster (K2/W1, Schlusspruefung 13.09.2026): OHNE dieses Fenster
    kommt jede Vergangenheit eines Google-/Apple-/Outlook-Feeds ungefiltert
    mit, und der aufsteigend sortierte erste Eintrag ist der AELTESTE
    Termin des ganzen Abonnements statt „der naechste" — gemessen genau an
    dem Satz, den ein Kollege beim Verbinden zuerst liest ("Der naechste
    ist ..."). Signatur bewusst wie `kalender.termine_lesen(tage_zurueck,
    tage_voraus)`: zwei verschiedene Auffassungen davon, was „die Termine"
    sind, waeren der naechste Fehler. Die Ueberlappungsregel spiegelt die
    CalDAV time-range REPORT, mit der `termine_lesen` filtert (RFC 4791
    §9.9): ein Termin zaehlt, wenn sein Intervall [beginn, ende) das
    Fenster [von, bis) ueberschneidet; ein punktueller Termin (ende ==
    beginn, siehe unten) zaehlt, wenn sein Zeitpunkt im Fenster liegt.

    Serientermine, Ganztaegiges, „frei" (Task 3, Kalender verbinden):
    `recurring_ical_events` loest RRULE/RDATE/EXDATE/Abweichungen zu
    einzelnen Vorkommen auf (UID = Serien-UID + "#" + Beginn in UTC);
    DURATION statt DTEND versteht `icalendar`. Ganztaegig (VALUE=DATE):
    Beginn = Mitternacht Ortszeit, Ende = folgende Mitternacht, `ganztaegig`
    gesetzt. `TRANSP:TRANSPARENT` ergibt `frei`. Es entfaellt damit der
    fruehere Serien-/Dauer-Hinweis; `fehler` bleibt fuer Abruf- und
    Lesefehler.
    """
    url = (url or "").strip()
    erlaubt, grund = _ziel_erlaubt(url)
    if not erlaubt:
        return [], ohne_adresse(grund, url)
    try:
        with _antwort_lesen(url) as antwort:
            # Ein Byte mehr als erlaubt lesen: nur so laesst sich "zu gross"
            # von "genau an der Grenze" unterscheiden, ohne dem
            # Content-Length-Kopf zu glauben.
            roh = antwort.read(MAX_BYTES + 1)
    except _ZielAbgewiesen as e:
        return [], ohne_adresse(str(e), url)
    except urllib.error.HTTPError as e:
        return [], ohne_adresse(
            f"Der Anbieter antwortet mit HTTP {e.code}. Stimmt die Adresse "
            f"noch, oder wurde sie zurueckgesetzt?", url)
    except Exception as e:                # noqa: BLE001 — Netz, Zeitgrenze, TLS
        return [], ohne_adresse(
            f"Die Adresse ist nicht erreichbar ({type(e).__name__}).", url)

    if len(roh) > MAX_BYTES:
        return [], (f"Die Antwort ist zu gross (mehr als "
                    f"{MAX_BYTES // 1024 // 1024} MB) — das ist kein "
                    f"Kalender, den wir laden wollen.")

    text = roh.decode("utf-8", "replace")
    if not _sieht_aus_wie_kalender(text):
        return [], ("Dort liegt kein Kalender, sondern eine Webseite. "
                    "Wahrscheinlich ist es die oeffentliche Adresse oder der "
                    "Link zum Kalender im Browser — gebraucht wird die "
                    "geheime Adresse im iCal-Format, sie endet meist auf "
                    "'.ics'.")

    jetzt = datetime.now(timezone.utc)
    von = jetzt - timedelta(days=tage_zurueck)
    bis = jetzt + timedelta(days=tage_voraus)
    ortszone = kalender.ortszone()

    art, daten = _aufklappen_mit_zeitgrenze(text, von, bis)
    if art == "zeit":
        return [], ZEITLIMIT_FEHLER
    if art != "ok":
        return [], ohne_adresse(
            f"Der Kalender ist nicht lesbar ({daten}).", url)
    zu_teuer, serien, vorkommen = daten

    hinweise = []
    if zu_teuer:
        hinweise.append(
            f"{zu_teuer} Serientermin{'e' if zu_teuer != 1 else ''} "
            f"uebersprungen (Wiederholungsregel zu fein oder zu weit "
            f"zurueck) — dort kann etwas liegen, das hier fehlt.")
    if len(vorkommen) > MAX_VORKOMMEN:
        vorkommen = vorkommen[:MAX_VORKOMMEN]
        hinweise.append(
            f"Der Kalender enthaelt mehr als {MAX_VORKOMMEN} Termine im "
            f"Zeitfenster — nur die ersten {MAX_VORKOMMEN} wurden gelesen, "
            f"dort kann etwas liegen, das hier fehlt.")
    termine = []
    unlesbar = 0
    for roh_ev in vorkommen:
        try:
            (start, ende, voll, titel, ort, transp, beschreibung, teilnehmer,
             anzahl, konferenz) = roh_ev
            ganztaegig = (isinstance(start, date)
                          and not isinstance(start, datetime))
            beginn = _ortszeit_utc(start, ortszone)
            ende = _ortszeit_utc(ende, ortszone) if ende is not None else beginn
            if ganztaegig and ende <= beginn:
                ende = _ortszeit_utc(start + timedelta(days=1), ortszone)
            # Serienpruefung gegen die VOLLE UID, Schluessel vor dem Kuerzen.
            if voll in serien:
                uid = f"{voll[:80]}#{beginn.isoformat()}"
            else:
                uid = voll[:120]
            termine.append({
                "beginn": beginn,
                "ende": max(ende, beginn),
                "titel": titel,
                "ort": ort,
                "uid": uid,
                "ganztaegig": ganztaegig,
                "frei": transp == "TRANSPARENT",
                "beschreibung": beschreibung,
                "teilnehmer": teilnehmer,
                "teilnehmer_anzahl": anzahl,
                "konferenz": konferenz})
        except Exception:                 # noqa: BLE001 — ein Termin, nicht alle
            unlesbar += 1
    if unlesbar:
        hinweise.append(
            f"{unlesbar} Termin{'e' if unlesbar != 1 else ''} nicht "
            f"lesbar — dort kann etwas liegen, das hier fehlt.")
    termine.sort(key=lambda t: t["beginn"])
    # Bekannte Luecken werden gemeldet, die lesbaren `termine` bleiben.
    return termine, (" ".join(hinweise) if hinweise else None)
