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
"""
import urllib.error
import urllib.parse
import urllib.request

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


def ohne_adresse(text: str, url: str) -> str:
    """Die Adresse aus einem Fehlertext entfernen — ganz und in Teilen.

    Ganz: manche Bibliotheken haengen die URL an ihre Meldung. In Teilen:
    der Pfad allein genuegt einem Angreifer bereits, wenn er den Host kennt.
    """
    text = (text or "").replace(url, "<Adresse>")
    zerlegt = urllib.parse.urlsplit(url)
    if zerlegt.path and len(zerlegt.path) > 1:
        text = text.replace(zerlegt.path, "<Pfad>")
    if zerlegt.query:
        text = text.replace(zerlegt.query, "<Abfrage>")
    return text[:FEHLER_MAXLAENGE]


def _sieht_aus_wie_kalender(text: str) -> bool:
    return "BEGIN:VCALENDAR" in text[:2000].upper()


def hole(url: str):
    """Eine abonnierte Adresse abrufen -> (termine, fehler).

    `termine` = [{"beginn", "ende", "titel", "ort", "uid"}], aufsteigend.
    Wirft nie: eine unerreichbare Quelle darf keine Seite und keinen
    Werkzeugaufruf kosten, sie kostet nur ihre eigenen Termine.
    """
    url = (url or "").strip()
    zerlegt = urllib.parse.urlsplit(url)
    if zerlegt.scheme not in _SCHEMATA:
        return [], ("Die Adresse muss mit http:// oder https:// beginnen — "
                    f"gefunden wurde '{zerlegt.scheme or 'nichts'}'.")
    try:
        anfrage = urllib.request.Request(
            url, method="GET", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            # Ein Byte mehr als erlaubt lesen: nur so laesst sich "zu gross"
            # von "genau an der Grenze" unterscheiden, ohne dem
            # Content-Length-Kopf zu glauben.
            roh = antwort.read(MAX_BYTES + 1)
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

    termine = []
    for teil in text.split("BEGIN:VEVENT")[1:]:
        block = teil.split("END:VEVENT", 1)[0]
        beginn = kalender._ics_zeit(kalender._ics_feld(block, "DTSTART"),
                                    kalender._ics_tzid(block, "DTSTART"))
        if beginn is None:
            continue
        ende = kalender._ics_zeit(kalender._ics_feld(block, "DTEND"),
                                  kalender._ics_tzid(block, "DTEND"))
        termine.append({
            "beginn": beginn,
            # Ohne DTEND gilt der Termin als punktuell. NICHT geraten: eine
            # erfundene Dauer erzeugte Kollisionen, die es nicht gibt.
            "ende": ende if ende and ende > beginn else beginn,
            "titel": kalender._ics_feld(block, "SUMMARY")[:200],
            "ort": kalender._ics_feld(block, "LOCATION")[:120],
            "uid": kalender._ics_feld(block, "UID")[:120]})
    termine.sort(key=lambda t: t["beginn"])
    return termine, None
