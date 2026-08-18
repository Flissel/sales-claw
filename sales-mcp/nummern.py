"""Empfaenger-Normalisierung — die eine Wahrheit fuer Anzeige und Versand.

Eigenes Modul, weil zwei Komponenten dieselbe Antwort geben muessen:
`dispatch.py` entscheidet damit, wohin eine Nachricht tatsaechlich geht, und
`server.py` zeigt dem Betreiber in `entwuerfe_offen` an, wohin sie ginge.
Liefen die beiden auseinander, waere die Freigabe eine Freigabe fuer etwas
anderes als das, was passiert — genau das darf bei einer Nachricht an einen
echten Menschen nicht sein. Deshalb importieren beide Seiten diese Funktion,
statt die Regel je einmal zu schreiben. (`server.py` kann `dispatch.py` nicht
importieren: dispatch importiert bereits server, das waere ein Zirkelimport.
Ein drittes, abhaengigkeitsfreies Modul loest das.)

GRUNDREGEL — es wird nicht geraten
----------------------------------
Zustellbar ist nur eine Nummer, die ihre Landesvorwahl selbst mitbringt:

    +<landesvorwahl><nummer>     ->  <ziffern>@c.us
    00<landesvorwahl><nummer>    ->  <ziffern>@c.us
    <landesvorwahl><nummer>      ->  <ziffern>@c.us   (>= 10 Stellen, keine
                                                       fuehrende 0)

Eine mit `0` beginnende Nummer OHNE `00` ist nationale Schreibweise und wird
zurueckgewiesen. Bis Stufe 3 galt hier eine „Amtsnull-Regel": `0…` wurde als
deutsche Nummer gelesen (`0170…` -> `49170…`). Die Batch-Review hat den Preis
dieser Bequemlichkeit sichtbar gemacht — sie gilt fuer JEDE national
notierte Nummer, auch fuer die oesterreichische `0664 1234567`, aus der so
`496641234567@c.us` wurde: die Nummer eines echten, voellig unbeteiligten
deutschen Menschen, an den eine Vertriebsnachricht gegangen waere. Eine
Rueckfrage ist billiger als eine Nachricht an den Falschen.

Mischformen wie „Herr Mueller 0170 1234567" werden weiterhin nicht
auseinandergenommen — nur etwas, das als GANZES eine Nummer ist, zaehlt.

Was bewusst bleibt: der Einschub „(0)" (`+49 (0)170 …`) ist keine Ratung,
sondern die uebliche, ausdrueckliche Notation fuer „Amtsnull hier weglassen",
und wird entfernt. Ebenso wird eine Amtsnull direkt hinter einer
AUSGESCHRIEBENEN `49` gestrichen (`+49 0170 …` -> `49170…`): dort steht die
Landesvorwahl bereits da, es kann also nichts verwechselt werden, und ohne
diese Regel ginge die Nachricht an `4901701234567` — eine Nummer, die es so
nicht gibt. Andere Landesvorwahlen bleiben unangetastet.
"""
import re

# Trenner, die in notierten Telefonnummern ueblich sind. Alles andere macht
# den Empfaenger unzustellbar — wir raten nicht.
_TRENNER = re.compile(r"[\s\-./() ‑]")
_NUMMER = re.compile(r"(\+|00)?\d{8,15}\Z")

# Ohne + und ohne 00 muss die Ziffernfolge lang genug sein, um glaubhaft eine
# Landesvorwahl zu enthalten. Kuerzeres ist eher ein Fragment als eine Nummer.
MINDESTLAENGE_OHNE_PRAEFIX = 10

FEHLER_UNZUSTELLBAR = "kein zustellbarer Empfaenger"
FEHLER_NATIONALE_SCHREIBWEISE = (
    "Empfaenger ohne Landesvorwahl ('0…') — mit +Vorwahl erfassen, "
    "nationaler Schreibweise wird nicht vertraut")


def normalisiere_empfaenger(recipient):
    """`recipient` -> ("49…@c.us", None) oder (None, Fehlertext).

    Der Fehlertext ist fuer einen Menschen geschrieben: er landet unveraendert
    in `drafts.error` und wird dem Betreiber vorgelesen.
    """
    roh = (recipient or "").strip()
    if not roh:
        return None, FEHLER_UNZUSTELLBAR

    kern = _TRENNER.sub("", roh.replace("(0)", ""))
    if not _NUMMER.fullmatch(kern):
        return None, FEHLER_UNZUSTELLBAR

    if kern.startswith("+"):
        ziffern = kern[1:]
    elif kern.startswith("00"):          # muss vor der 0-Pruefung stehen
        ziffern = kern[2:]
    elif kern.startswith("0"):
        return None, FEHLER_NATIONALE_SCHREIBWEISE
    else:
        if len(kern) < MINDESTLAENGE_OHNE_PRAEFIX:
            return None, FEHLER_UNZUSTELLBAR
        ziffern = kern

    if ziffern.startswith("490"):        # Amtsnull hinter ausgeschriebener 49
        ziffern = "49" + ziffern[3:]

    if not 8 <= len(ziffern) <= 15:      # E.164
        return None, FEHLER_UNZUSTELLBAR
    return f"{ziffern}@c.us", None


def zielnummer(recipient):
    """Nur die Chat-ID, oder None — fuer Anzeigen, die den Grund nicht brauchen."""
    chat_id, _ = normalisiere_empfaenger(recipient)
    return chat_id
