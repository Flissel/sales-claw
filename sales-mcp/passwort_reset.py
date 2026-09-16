"""Passwort vergessen — der Einmal-Link (Betreiber-Auftrag 16.09.2026).

WARUM ES DAS BRAUCHT, obwohl es `benutzer_anlegen.py` gibt: jenes setzt
Passwoerter ueber die Kommandozeile IM CONTAINER. Das kann nur, wer eine
Shell auf der VM hat. Der zweite Benutzer dieses Hauses (Rolle `kalender`)
hat die nicht — fuer ihn war Aussperrung bisher endgueltig, und der einzige
Ausweg war, den Betreiber zu bitten.

WARUM DIESE MAIL NICHT DURCH DIE FREIGABE-QUEUE GEHT
-----------------------------------------------------
Seit dem Betreiber-Entscheid vom 12.09.2026 laeuft JEDE Nachricht dieses
Hauses ueber `entwurf_erstellen`, wird Entwurf und wartet auf einen
Menschen. Hier waere das ein Zirkel: der Mensch, der freigibt, ist gerade
der Ausgesperrte.

Die Ausnahme ist eng und nachpruefbar, und sie ist KEIN Schlupfloch:

  * Sie geht ausschliesslich an `benutzer.email` eines BESTEHENDEN, aktiven
    Kontos — nie an eine Adresse, die ein Aufrufer mitbringt.
  * Der Text ist fest. Es gibt keinen Parameter, mit dem jemand eigenen
    Inhalt hineinschreiben koennte; die Mail traegt genau einen Link.
  * Sie ist keine Ansprache, sondern eine Kontoauskunft an den
    Kontoinhaber. Die Tore in `entwurf_erstellen` (Verbotsliste,
    UWG-Erstansprache, Einwilligung) schuetzen KUNDEN vor ungebetener Post;
    hier schreibt das Haus an sich selbst.
  * Eine Bremse je Konto verhindert, dass jemand ueber das Formular eine
    Mailflut ausloest.

WAS DIE DATENBANK SIEHT
------------------------
Nur der HASH des Tokens, nie der Token. Wer die Datenbank liest, darf damit
kein Konto uebernehmen koennen — dieselbe Ueberlegung wie beim
`passwort_hash` daneben. sha256 reicht hier, anders als beim Passwort: ein
Token ist 32 zufaellige Bytes und nicht zu erraten, waehrend ein Passwort
aus einem Kopf stammt und deshalb scrypt braucht.

NUR STANDARDBIBLIOTHEK und keine Datenbank: dieses Modul rechnet, es greift
nirgends zu. Deshalb ist es ohne alles pruefbar — und deshalb koennen die
Oberflaeche und ein spaeterer Kommandozeilenweg dieselbe Regel benutzen,
statt zwei zu haben.
"""
import hashlib
import hmac
import secrets
import time

# 30 Minuten. Kurz genug, dass ein abgefangener Link meist tot ist; lang
# genug, dass jemand das Postfach am Handy erst spaeter aufmacht.
GUELTIG_S = 30 * 60

# Eine Mail je Konto und Viertelstunde. Wer das Formular zehnmal abschickt,
# soll nicht zehn Mails ausloesen - und der Ausgesperrte soll trotzdem nicht
# lange warten muessen, wenn die erste im Spam gelandet ist.
BREMSE_S = 15 * 60

# 32 Bytes Zufall, urlsafe kodiert. Nicht zu erraten und ohne Zeichen, die
# ein Mailprogramm beim Verlinken zerlegt.
TOKEN_BYTES = 32


def token_erzeugen() -> tuple:
    """(klartext, hash) - der Klartext geht in die Mail, der Hash in die DB."""
    klartext = secrets.token_urlsafe(TOKEN_BYTES)
    return klartext, token_hashen(klartext)


def token_hashen(klartext: str) -> str:
    return hashlib.sha256((klartext or "").encode("utf-8")).hexdigest()


def token_stimmt(klartext: str, gespeichert: str) -> bool:
    """Vergleich in konstanter Zeit. Leerer Speicher heisst NEIN.

    Ohne die Leerpruefung waere ein Konto ohne offenen Reset angreifbar:
    `token_hashen("")` ergibt einen gueltigen sha256, und ein leeres
    `reset_hash` in der Datenbank wuerde dagegen verglichen.
    """
    if not klartext or not gespeichert:
        return False
    return hmac.compare_digest(token_hashen(klartext), gespeichert)


def ablauf(jetzt: float = None) -> float:
    return (time.time() if jetzt is None else jetzt) + GUELTIG_S


def abgelaufen(bis, jetzt: float = None) -> bool:
    """`bis` ist ein Zeitstempel (float) oder ein datetime aus der DB.
    Fehlt er, gilt das als abgelaufen - fail-closed."""
    if bis is None:
        return True
    jetzt = time.time() if jetzt is None else jetzt
    if hasattr(bis, "timestamp"):
        return bis.timestamp() < jetzt
    return float(bis) < jetzt


def bremse_greift(zuletzt, jetzt: float = None) -> bool:
    """True, wenn fuer dieses Konto gerade erst ein Link ging."""
    if zuletzt is None:
        return False
    jetzt = time.time() if jetzt is None else jetzt
    wert = zuletzt.timestamp() if hasattr(zuletzt, "timestamp") else float(zuletzt)
    return (jetzt - wert) < BREMSE_S


def passwort_taugt(klartext: str) -> str:
    """'' wenn brauchbar, sonst der Grund - im Wortlaut fuer den Benutzer.

    Dieselbe Mindestlaenge wie `benutzer_anlegen.anlegen` (10). Sie steht
    hier noch einmal, weil dieses Modul ohne jenes lauffaehig sein soll;
    laufen sie auseinander, faellt es in test_passwort_reset.py auf.
    """
    if len(klartext or "") < 10:
        return "Das Passwort braucht mindestens 10 Zeichen."
    if (klartext or "").strip() != klartext:
        return "Das Passwort faengt oder endet mit einem Leerzeichen."
    return ""


def link_bauen(basis: str, name: str, token: str) -> str:
    """Der Link, der in die Mail geht.

    `basis` kommt aus der Umgebung (UI_BASIS_URL), nicht aus der Anfrage:
    wer den Host-Header faelschen kann, wuerde sonst den Link auf seinen
    eigenen Rechner zeigen lassen und den Token einsammeln.
    """
    import urllib.parse
    return (basis.rstrip("/") + "/passwort-neu?name="
            + urllib.parse.quote(name, safe="")
            + "&token=" + urllib.parse.quote(token, safe=""))


BETREFF = "Neues Passwort fuer die sales-claw-Oberflaeche"


def mailtext(name: str, link: str) -> str:
    """Fester Text. Kein Parameter fuer Inhalt - eine Mail, die jemand von
    aussen mit eigenem Text fuellen koennte, waere ein Versandweg."""
    return (
        f"Hallo {name},\n\n"
        f"jemand hat fuer dein Konto ein neues Passwort angefordert.\n\n"
        f"{link}\n\n"
        f"Der Link gilt {GUELTIG_S // 60} Minuten und genau einmal.\n\n"
        f"Warst du das nicht, musst du nichts tun - ohne den Link aendert\n"
        f"sich nichts, und dein bisheriges Passwort gilt weiter.\n")
