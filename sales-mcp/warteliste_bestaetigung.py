"""Bestaetigungsmails fuer die Warteliste von vibemind.space (seit 13.11.2026).

Wer sich auf vibemind.space auf die Warteliste setzt, bekommt EINE Mail mit
einem Link und steht erst nach dem Klick auf der Liste (Double-Opt-in). Die
Website kann selbst keine Mails verschicken; das uebernimmt dieser Laden mit
seinem eigenen Postfach.

  1. Das Formular der Website merkt die Adresse als "wartet auf ihre Mail" vor.
  2. `deploy/warteliste-bestaetigung.sh` holt jede Minute auf dem Wirt die
     wartenden Adressen ab - je Adresse mit einem frischen Einmal-Token - und
     reicht das Dokument auf der Standardeingabe hierher.
  3. Dieses Modul verschickt je Adresse die Mail mit dem Link.
  4. Was der Mailserver nicht angenommen hat, gibt es auf der Standardausgabe
     zurueck; das Skript meldet diese Adressen der Website, und sie sind beim
     naechsten Lauf wieder dabei (hoechstens drei Versuche in 24 Stunden).

FESTER TEXT, KEINE FREIGABE. Die Mail antwortet nur dem, dessen Adresse gerade
im Formular stand, mit immer demselben Wortlaut - derselbe Betreiber-Entscheid
wie bei der Newsletter-Anmeldung per Mail (newsletter_anmeldung.py). Kein
Sprachmodell, kein Fremdtext: in die Mail gelangt ausser der Empfaengeradresse
nur der Token, und der besteht aus 64 Hex-Zeichen.

KEIN KONTAKT, KEINE BUCHUNG. Eine unbestaetigte Adresse ist noch niemand: sie
wird hier weder als Kontakt angelegt noch irgendwo gebucht. Erst nach dem Klick
liefert die Website sie im naechtlichen Abgleich (warteliste_abgleich.py).

VERBOTSLISTE. Wer auf der gemeinsamen Verbotsliste steht, bekommt auch diese
Mail nicht - "nie wieder anschreiben" gilt ohne Ausnahme. Die Anmeldung
verfaellt dann bei der Website nach sieben Tagen. Laesst sich die Liste nicht
lesen, geht die Mail NICHT raus; die Adresse wird zurueckgemeldet.

KEIN SCHLUESSEL HIER. Den Abholschluessel kennt nur der Wirt. Der Token steht
nie in einem Argument und nie im Log; Adressen stehen im Log nur verdeckt.

KEINE KOPIE IM GESENDET-ORDNER. Die Mail traegt einen Einmal-Link; im Postfach
des Betreibers hat er nichts verloren.

CLI (Arbeitsverzeichnis /app im Container sales-mail, Dokument auf stdin):
  python warteliste_bestaetigung.py senden [--seite URL]
    --seite URL   Adresse der Bestaetigungsseite (Vorgabe: vibemind.space)
  Standardausgabe: EINE Zeile JSON - die Liste der Adressen, die zurueck in
                   die Warteschlange sollen (meist `[]`).
  Fehlerausgabe:   eine Zeile JSON mit Zahlen, dazu Warnungen ohne Adressen.
  Exit 0 ok · 2 Eingabe unbrauchbar (nichts versendet) · 3 mindestens eine
  Mail ging nicht raus (ihre Adressen stehen auf der Standardausgabe)
"""
import json
import re
import sys
import time
from typing import Callable, List, Tuple

SEITE = "https://vibemind.space/waitlist/confirm"
HOECHSTENS = 50              # mehr liefert die Website in einem Abruf nie

BETREFF = "Confirm your place on the Vibemind waitlist"
RUMPF = (
    "Hello,\n\n"
    "this address was entered in the waitlist form on vibemind.space. "
    "If that was you, please confirm it here:\n\n"
    "{link}\n\n"
    "The link works for seven days. You are on the waitlist once you have "
    "confirmed.\n\n"
    "If it was not you, you can ignore this mail. Without the confirmation "
    "the request expires after seven days.\n\n"
    "Vibemind\n"
    "Imprint and privacy: https://vibemind.space/privacy\n")

# Dieselbe Form, die Website und Wartelisten-Tabelle verlangen. Sie laesst
# weder Leerzeichen noch Zeilenumbrueche, Kommas oder Klammern zu - nichts,
# was aus einem Empfaenger zwei oder eine zweite Kopfzeile machen koennte.
_ADRESSE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_SEITE = re.compile(r"^https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?:/[A-Za-z0-9_/-]*)?$")


class EingabeFehler(ValueError):
    """Das Dokument ist nicht das, was die Website liefert - nichts versenden."""


def maskiert(adresse: str) -> str:
    """Fuer Logzeilen: zwei Zeichen und die Domain (wie mail_dispatch._maskiert)."""
    lokal, _, domain = (adresse or "").partition("@")
    return f"{lokal[:2]}…@{domain}" if domain else "…"


def eintraege_lesen(dokument) -> Tuple[List[Tuple[str, str]], int]:
    """([(adresse, token), ...], anzahl_unbrauchbar) aus dem Dokument der Website.

    Erwartet `{"count": n, "rows": [{email, token}, ...]}`. Passt `count`
    nicht zur Zeilenzahl, ist das Dokument abgeschnitten -> EingabeFehler.
    Eine einzelne unbrauchbare Zeile wird gezaehlt und uebergangen; eine
    Adresse, die zweimal vorkommt, bekommt eine Mail (die erste Zeile)."""
    if not isinstance(dokument, dict) or not isinstance(dokument.get("rows"), list):
        raise EingabeFehler("kein Warteschlangen-Dokument (rows fehlt)")
    zeilen = dokument["rows"]
    if dokument.get("count") != len(zeilen):
        raise EingabeFehler("Warteschlangen-Dokument unvollstaendig (count passt nicht zu rows)")
    if len(zeilen) > HOECHSTENS:
        raise EingabeFehler(f"Warteschlangen-Dokument mit mehr als {HOECHSTENS} Zeilen")
    eintraege: List[Tuple[str, str]] = []
    gesehen = set()
    unbrauchbar = 0
    for z in zeilen:
        adresse = z.get("email") if isinstance(z, dict) else None
        token = z.get("token") if isinstance(z, dict) else None
        if (not isinstance(adresse, str) or not isinstance(token, str)
                or not 5 <= len(adresse) <= 255 or not _ADRESSE.fullmatch(adresse)
                or not _TOKEN.fullmatch(token)):
            unbrauchbar += 1
            continue
        if adresse in gesehen:
            continue
        gesehen.add(adresse)
        eintraege.append((adresse, token))
    return eintraege, unbrauchbar


def rumpf(token: str, seite: str = SEITE) -> str:
    """Der Wortlaut der Mail. Der Token steht hinter dem `#`: dieser Teil der
    Adresse wird beim Aufruf an keinen Server geschickt und steht in keinem
    Zugriffsprotokoll; die Seite liest ihn im Browser."""
    if not _TOKEN.fullmatch(token or ""):
        raise ValueError("Token hat nicht 64 Hex-Zeichen")
    if not _SEITE.fullmatch(seite or ""):
        raise ValueError("Bestaetigungsseite ist keine https-Adresse")
    return RUMPF.format(link=f"{seite}#{token}")


def verschicken(eintraege: List[Tuple[str, str]], *,
                gesperrt: Callable[[str], bool],
                senden: Callable[[str, str, str], None],
                seite: str = SEITE, pause: float = 0.0,
                schlafen: Callable[[float], None] = time.sleep,
                warnen: Callable[[str], None] = lambda text: None) -> dict:
    """Je Adresse eine Mail. Gibt Zahlen und die Liste `erneut` zurueck.

    `gesperrt(adresse)` und `senden(adresse, betreff, text)` kommen vom
    Aufrufer (Verbotsliste und Mailserver) - so laeuft die Logik im Test ohne
    Datenbank und ohne Netz. Wirft eine der beiden, geht fuer diese Adresse
    nichts raus und sie steht in `erneut`. Gewarnt wird ohne Adresse und ohne
    den Wortlaut des Mailservers (der nennt den Empfaenger)."""
    zahlen = {"gesendet": 0, "gesperrt": 0, "fehler": 0}
    erneut: List[str] = []
    for nummer, (adresse, token) in enumerate(eintraege):
        try:
            if gesperrt(adresse):
                zahlen["gesperrt"] += 1
                continue
        except Exception as e:                      # noqa: BLE001 - nie ungeprueft senden
            zahlen["fehler"] += 1
            erneut.append(adresse)
            warnen(f"Verbotsliste nicht lesbar ({type(e).__name__}) - "
                   f"Mail an {maskiert(adresse)} zurueckgestellt")
            continue
        if nummer and pause > 0:
            schlafen(pause)
        try:
            senden(adresse, BETREFF, rumpf(token, seite))
        except Exception as e:                      # noqa: BLE001 - der Lauf geht weiter
            zahlen["fehler"] += 1
            erneut.append(adresse)
            warnen(f"Versand an {maskiert(adresse)} gescheitert ({type(e).__name__})")
            continue
        zahlen["gesendet"] += 1
    return {**zahlen, "erneut": erneut}


def _melden(zahlen: dict, unbrauchbar: int, fehlerausgabe) -> None:
    print(json.dumps({"gesendet": zahlen["gesendet"], "gesperrt": zahlen["gesperrt"],
                      "fehler": zahlen["fehler"], "unbrauchbar": unbrauchbar}),
          file=fehlerausgabe)


def main(argv, eingabe=None, ausgabe=None, fehlerausgabe=None, werkzeuge=None) -> int:
    ausgabe = ausgabe if ausgabe is not None else sys.stdout
    fehlerausgabe = fehlerausgabe if fehlerausgabe is not None else sys.stderr
    if not argv or argv[0] != "senden":
        print(__doc__.split("CLI", 1)[1], file=fehlerausgabe)
        return 2
    seite, rest = SEITE, list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == "--seite" and rest and _SEITE.fullmatch(rest[0]):
            seite = rest.pop(0)
        else:
            print(f"FEHLER: unbekanntes oder unbrauchbares Argument {a!r}", file=fehlerausgabe)
            return 2
    roh = (eingabe if eingabe is not None else sys.stdin).read()
    try:
        dokument = json.loads(roh) if roh.strip() else None
        eintraege, unbrauchbar = eintraege_lesen(dokument)
    except (ValueError, EingabeFehler) as e:
        grund = str(e) if isinstance(e, EingabeFehler) else "Dokument ist kein JSON"
        print(f"FEHLER: {grund} - nichts versendet.", file=fehlerausgabe)
        return 2
    if not eintraege:
        print("[]", file=ausgabe)
        _melden({"gesendet": 0, "gesperrt": 0, "fehler": 0}, unbrauchbar, fehlerausgabe)
        return 0

    def warnen(text: str) -> None:
        print(f"WARNUNG: {text}", file=fehlerausgabe)

    gesperrt, senden, pause = (werkzeuge or _werkzeuge)()
    if senden is None:
        # Ohne brauchbares Postfach geht nichts raus; alle zurueck in die Schlange.
        print(json.dumps([a for a, _ in eintraege], separators=(",", ":")), file=ausgabe)
        print("FEHLER: SMTP_*/EMAIL_ABSENDER unvollstaendig - nichts versendet, "
              "alle Adressen zurueckgemeldet.", file=fehlerausgabe)
        return 3
    zahlen = verschicken(eintraege, gesperrt=gesperrt, senden=senden, seite=seite,
                         pause=pause, warnen=warnen)
    print(json.dumps(zahlen["erneut"], separators=(",", ":")), file=ausgabe)
    _melden(zahlen, unbrauchbar, fehlerausgabe)
    return 3 if zahlen["fehler"] else 0


def _werkzeuge():
    """(gesperrt, senden, pause) aus dem laufenden Laden. Spaet importiert:
    mail_dispatch zieht die Datenbank und die SMTP-Zugangsdaten nach."""
    import mail_dispatch
    import server
    import sperrliste

    identitaet = mail_dispatch.kunden_identitaet()
    if not identitaet.brauchbar():
        return None, None, 0.0

    def gesperrt(adresse: str) -> bool:
        return bool(sperrliste.gesperrt(server._q, email=adresse))

    def senden(adresse: str, betreff: str, text: str) -> None:
        nachricht = mail_dispatch.nachricht_bauen(adresse, betreff, text,
                                                  absender=identitaet.absender)
        # Eine Abwesenheitsnotiz soll auf diese Mail nicht antworten (RFC 3834).
        nachricht["Auto-Submitted"] = "auto-generated"
        mail_dispatch.senden(nachricht, identitaet)

    return gesperrt, senden, mail_dispatch.SENDE_PAUSE_S


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
