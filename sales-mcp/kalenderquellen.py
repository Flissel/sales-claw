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
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

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


# RFC 5545 §3.3.6 DURATION — bescheidene Auswertung fuer Tage/Stunden/
# Minuten/Sekunden (K4-Ruling, Schlusspruefung 13.09.2026). Bewusst NICHT
# unterstuetzt: Wochen ("P2W") und negative Dauern — beide sind in echten
# Kalenderexporten selten, und eine falsche Auswertung waere schlimmer als
# eine ehrlich gemeldete Luecke. Was hier nicht passt, gilt als unlesbar.
_DAUER_MUSTER = re.compile(
    r"^P(?:(?P<tage>\d+)D)?"
    r"(?:T(?:(?P<stunden>\d+)H)?(?:(?P<minuten>\d+)M)?(?:(?P<sekunden>\d+)S)?)?$")


def _dauer_lesen(wert: str):
    """DURATION-Wert ('PT1H30M', 'P1D', ...) -> timedelta oder None (nicht
    verstanden — behandle wie ein fehlendes Ende, siehe Aufrufer)."""
    treffer = _DAUER_MUSTER.match((wert or "").strip())
    if not treffer:
        return None
    teile = {k: int(v) for k, v in treffer.groupdict(default="0").items()}
    dauer = timedelta(days=teile["tage"], hours=teile["stunden"],
                      minutes=teile["minuten"], seconds=teile["sekunden"])
    return dauer if dauer > timedelta(0) else None


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

    Serientermine und DURATION (K4, Schlusspruefung 13.09.2026): ein VEVENT
    mit RRULE wird NICHT entfaltet (ein eigenes Vorhaben, halb richtig waere
    schlimmer als gar nicht) — es zaehlt weder mit seinem einzelnen DTSTART
    als Termin (das waere K4s Ursprungsfehler: ein woechentliches Meeting
    kollidiert dann nie wieder) noch fehlt es stillschweigend. Stattdessen
    zaehlt `hole()` solche Eintraege (und VEVENTs mit unlesbarer DURATION
    statt DTEND) und meldet sie als `fehler` — nicht als leerer `termine`,
    denn andere, einmalige VEVENTs derselben Antwort bleiben gueltige
    Kollisionsdaten. `belegungen()` haengt diesen Text als eigene Luecke an,
    OHNE die zurueckgegebenen `termine` zu verwerfen (Fix K4/K3): eine
    Quelle mit Serientermin meldet `termin_konflikte` dadurch nie
    `frei: true`, verliert aber nicht die Kollisionen, die sie sehr wohl
    versteht.
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

    termine = []
    serien = 0
    unlesbare_dauer = 0
    for teil in text.split("BEGIN:VEVENT")[1:]:
        block = teil.split("END:VEVENT", 1)[0]
        beginn = kalender._ics_zeit(kalender._ics_feld(block, "DTSTART"),
                                    kalender._ics_tzid(block, "DTSTART"))
        if beginn is None:
            continue
        ist_serie = bool(kalender._ics_feld(block, "RRULE"))
        ende = kalender._ics_zeit(kalender._ics_feld(block, "DTEND"),
                                  kalender._ics_tzid(block, "DTEND"))
        dauer_unlesbar = False
        if not (ende and ende > beginn):
            # Ohne (lesbares) DTEND: DURATION probieren (K4 — RFC 5545
            # erlaubt beides, Apple und manche Outlook-Exporte nutzen es).
            dauer_wert = kalender._ics_feld(block, "DURATION")
            dauer = _dauer_lesen(dauer_wert) if dauer_wert else None
            if dauer is not None:
                ende = beginn + dauer
            else:
                # Weder DTEND noch (lesbare) DURATION: punktuell. NICHT
                # geraten: eine erfundene Dauer erzeugte Kollisionen, die es
                # nicht gibt.
                dauer_unlesbar = bool(dauer_wert)
                ende = beginn
        # Zeitfenster (K2/W1) — jetzt VOR dem Serien-/Dauer-Zaehler (Fix
        # Koordinator, 13.09.2026): eine Serie oder ein unlesbares DURATION
        # zaehlt nur, wenn IHR eigener Anhaltspunkt (Master-DTSTART/-DTEND)
        # im Fenster liegt. Vorher zaehlte auch eine vor Jahren beendete
        # Serie fuer immer als Luecke — termin_konflikte haette fuer eine
        # solche Quelle NIE WIEDER frei: true gemeldet, und /team/kalender
        # haette sie fuer immer als Fehler statt mit Terminzahl gezeigt
        # (kalenderquelle_stand_setzen laesst den Zaehler bei jedem
        # `fehler` unveraendert). Ein punktueller Termin (ende == beginn)
        # zaehlt, wenn sein Zeitpunkt im Fenster liegt; sonst gilt die
        # Ueberlappung [beginn, ende) mit [von, bis) — dieselbe Regel wie
        # die CalDAV time-range REPORT in kalender.termine_lesen.
        if ende <= von or beginn >= bis:
            continue
        if ist_serie:
            # K4: nicht entfalten, nicht als einzelnen Termin am ersten
            # DTSTART durchrutschen lassen — nur zaehlen (und das erst,
            # seit gerade eben, nur innerhalb des Fensters).
            serien += 1
            continue
        if dauer_unlesbar:
            unlesbare_dauer += 1
        termine.append({
            "beginn": beginn,
            "ende": ende,
            "titel": kalender._ics_feld(block, "SUMMARY")[:200],
            "ort": kalender._ics_feld(block, "LOCATION")[:120],
            "uid": kalender._ics_feld(block, "UID")[:120]})
    termine.sort(key=lambda t: t["beginn"])

    hinweise = []
    if serien:
        hinweise.append(
            f"{serien} Serientermin{'e' if serien != 1 else ''} (RRULE) "
            f"werden nicht aufgeloest — dort kann etwas liegen, das hier "
            f"fehlt.")
    if unlesbare_dauer:
        hinweise.append(
            f"{unlesbare_dauer} Termin{'e' if unlesbare_dauer != 1 else ''} "
            f"mit unlesbarer Dauer (DURATION) — als punktuell behandelt, "
            f"dort kann etwas liegen, das hier fehlt.")
    # Bewusst KEIN leeres `termine` bei einer Luecke (anders als jeder
    # andere Fehlerpfad oben): andere, einmalige VEVENTs derselben Antwort
    # bleiben gueltige Kollisionsdaten (siehe Docstring). `belegungen()`
    # haengt den Hinweis als eigene Luecke an, OHNE `termine` zu verwerfen.
    return termine, (" ".join(hinweise) if hinweise else None)
