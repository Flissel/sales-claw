"""E-Mail-Empfaenger — EINE Regel fuer Anzeige und Versand.

Wortgleiche Begruendung wie `nummern.py`: `entwuerfe_offen` zeigt dem
Betreiber VOR der Freigabe an, an welche Adresse ein Entwurf ginge — und
`mail_dispatch.py` entscheidet beim Versand, ob sie zustellbar ist. Diese
beiden Urteile duerfen nie auseinanderlaufen, sonst gibt jemand etwas
anderes frei als das, was passiert. Ein eigenes Modul, weil `server.py`
den Dispatcher nicht importieren kann (der importiert `server`).

WARUM EINE WHITELIST UND KEINE RFC-5322-TREUE
---------------------------------------------
Die vollstaendige Grammatik erlaubt Dinge, die hier niemand braucht
(Anfuehrungszeichen, Kommentare in Klammern, Leerzeichen in Anfuehrungs-
zeichen, IP-Literale in eckigen Klammern). Sie erlaubt damit auch Zeichen,
die als Empfaenger einer Kopfzeile gefaehrlich sind. Der Empfaenger geht
in den `To:`-Kopf einer echten Mail; ein `\\r` oder `\\n` darin ist eine
Kopfzeilen-Injektion, ein Komma oder Semikolon macht aus einem Empfaenger
still zwei. Deshalb steht hier eine Whitelist erlaubter Zeichen — was sie
nicht nennt, ist nicht zustellbar. Der Preis ist eine exotische Adresse,
die abgelehnt wird; der Gegenwert ist, dass eine freigegebene Nachricht
nicht an einen zweiten, ungenannten Empfaenger geht.
"""
import re

# RFC 5321 §4.5.3.1.3: der Pfad (lokal@domain) hoechstens 256 Oktette
# einschliesslich der spitzen Klammern, also 254 fuer die Adresse selbst.
MAX_LAENGE = 254

FEHLER_UNZUSTELLBAR = ("kein zustellbarer E-Mail-Empfaenger (erwartet: "
                       "name@domain.tld)")

# Genau ein '@'; links die uebliche „dot-atom"-Zeichenmenge, rechts nur
# Buchstaben, Ziffern, Punkt und Bindestrich. Kein Leerzeichen, kein
# Steuerzeichen, kein Komma, kein Semikolon, keine spitzen Klammern —
# siehe Moduldocstring.
_FORM = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
                   r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
                   r"@"
                   r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*")


def pruefe(roh):
    """Adresse -> (adresse, None) | (None, fehler). Wirft nie.

    Gekuerzt wird nur aussen (`strip`) — innen wird nichts repariert. Eine
    Adresse, die eine Reparatur braucht, ist eine geratene Adresse, und
    geraten wird bei Empfaengern nicht (dieselbe Regel wie bei den Nummern:
    lieber eine Rueckfrage als eine Nachricht an einen Fremden).
    """
    adresse = (roh or "").strip()
    if not adresse or len(adresse) > MAX_LAENGE:
        return None, FEHLER_UNZUSTELLBAR
    if adresse.count("@") != 1:
        return None, FEHLER_UNZUSTELLBAR
    if not _FORM.fullmatch(adresse):
        return None, FEHLER_UNZUSTELLBAR
    # Die Domain muss einen Punkt tragen: `max@localhost` ist im lokalen
    # Netz gueltig, aus einem CRM heraus aber immer ein Erfassungsfehler.
    if "." not in adresse.rsplit("@", 1)[1]:
        return None, FEHLER_UNZUSTELLBAR
    return adresse, None
