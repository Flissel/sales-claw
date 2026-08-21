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
    49<nummer>                   ->  <ziffern>@c.us   (11–15 Stellen)

Blank, also ohne `+` und ohne `00`, wird ausschliesslich `49…` vertraut —
die einzige Vorwahl, die dieser Einsatz (deutscher Finanzvertrieb) ohne
ausdrueckliches Zeichen annehmen darf. `1701234567` waere sonst als US-Nummer
1+701 durchgegangen, statt als die deutsche Mobilnummer, die sie ist. Details
bei BLANK_PRAEFIX.

Eine mit `0` beginnende Nummer OHNE `00` ist nationale Schreibweise und wird
zurueckgewiesen. Bis Stufe 3 galt hier eine „Amtsnull-Regel": `0…` wurde als
deutsche Nummer gelesen (`0170…` -> `49170…`). Die Batch-Review hat den Preis
dieser Bequemlichkeit sichtbar gemacht — sie gilt fuer JEDE national
notierte Nummer, auch fuer die oesterreichische `0664 1234567`, aus der so
`496641234567@c.us` wurde: die Nummer eines echten, voellig unbeteiligten
deutschen Menschen, an den eine Vertriebsnachricht gegangen waere. Eine
Rueckfrage ist billiger als eine Nachricht an den Falschen.

Und nach dem Abtrennen von `+`/`00` darf keine `0` mehr vorne stehen: eine
Landesvorwahl beginnt nie mit 0 (E.164 §2.2). `+0…`, `00 0…` und
`000000000000` sind damit keine Nummern. Bis zur Fix-Runde zu Review-Befund
M7 wurde `000000000000` klaglos zu `0000000000@c.us`.

Mischformen wie „Herr Mueller 0170 1234567" werden weiterhin nicht
auseinandergenommen — nur etwas, das als GANZES eine Nummer ist, zaehlt.

Fuer Werte, die kein Mensch getippt hat (JID-Ziffern, OpenWAs `phone`), gibt
es `normalisiere_msisdn` — dieselbe Regel, nur mit der Erlaubnis, das fehlende
`+` zu ergaenzen. Siehe dort.

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

# Blanke Ziffernfolgen (ohne + und ohne 00): NUR mit 49-Praefix und 11–15
# Stellen, also `49` + deutsche Rufnummer.
#
# Bis zur Fix-Runde reichte hier "mindestens 10 Stellen" unter der ANNAHME,
# eine so lange Folge bringe ihre Landesvorwahl schon mit — geprueft wurde das
# nie. `1701234567` ist eine deutsche Mobilnummer, der `+49` und die fuehrende
# `0` fehlen; gelesen wurde sie als US-Vorwahl 1 + 701, ein realer
# Vorwahlbereich in North Dakota. Dieselbe Klasse Fehler wie die Amtsnull-Regel,
# nur eine Ebene tiefer: aus einer unvollstaendigen Angabe wurde stillschweigend
# eine gueltige fremde Nummer.
#
# In diesem Einsatz (deutscher Finanzvertrieb) ist `49…` die einzige Vorwahl,
# der wir ohne ausdrueckliches `+` vertrauen. Jede andere Nummer muss ihre
# Vorwahl ausdruecklich mitbringen.
BLANK_PRAEFIX = "49"
BLANK_MIN, BLANK_MAX = 11, 15

FEHLER_UNZUSTELLBAR = "kein zustellbarer Empfaenger"
FEHLER_NATIONALE_SCHREIBWEISE = (
    "Empfaenger ohne Landesvorwahl ('0…') — mit +Vorwahl erfassen, "
    "nationaler Schreibweise wird nicht vertraut")
FEHLER_VORWAHL_UNBEKANNT = (
    "Landesvorwahl nicht erkennbar — Empfaenger mit +Vorwahl erfassen")
FEHLER_VORWAHL_NULL = (
    "Landesvorwahl beginnt mit 0 — die gibt es nicht (E.164)")


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
        # Blank: nur `49` + deutsche Rufnummer. Siehe BLANK_PRAEFIX oben.
        if not (kern.startswith(BLANK_PRAEFIX)
                and BLANK_MIN <= len(kern) <= BLANK_MAX):
            return None, FEHLER_VORWAHL_UNBEKANNT
        ziffern = kern

    if ziffern.startswith("490"):        # Amtsnull hinter ausgeschriebener 49
        ziffern = "49" + ziffern[3:]

    # Eine Landesvorwahl beginnt nie mit 0 (E.164 §2.2). `00 0…` und `+0…`
    # sind damit keine Nummern, sondern Muell — und wurden bis zur Fix-Runde
    # klaglos zu einer Chat-ID (`000000000000` -> `0000000000@c.us`, gemessen
    # im Review zu Befund M7). Die Pruefung steht NACH der 490-Regel, sonst
    # fiele `+49 0170 …` darunter, wo die Vorwahl ausgeschrieben danebensteht.
    if ziffern.startswith("0"):
        return None, FEHLER_VORWAHL_NULL

    if not 8 <= len(ziffern) <= 15:      # E.164
        return None, FEHLER_UNZUSTELLBAR
    return f"{ziffern}@c.us", None


def normalisiere_msisdn(roh):
    """Wie `normalisiere_empfaenger`, aber fuer TECHNISCH gelieferte Werte.

    Gemeint sind Werte, die kein Mensch getippt hat: der Ziffernteil eines
    WhatsApp-JID (`491701234567:12@s.whatsapp.net`) und OpenWAs `phone`-Feld
    (blanke MSISDN, `491729186846`). Sie bringen ihre Landesvorwahl technisch
    immer mit, tragen aber kein `+` — deshalb wird eines vorangestellt, damit
    die 49-Sonderregel fuer blanke Folgen (BLANK_PRAEFIX) gar nicht erst
    greift und eine oesterreichische Nummer nicht als unzustellbar gilt.

    DER UNTERSCHIED ZU FRUEHER (Review-Befund M7). An drei Stellen stand
    `normalisiere_empfaenger("+" + ziffern(roh))`. `ziffern()` wirft jedes
    Zeichen weg, das keine Ziffer ist, und das vorangestellte `+` erklaerte
    das Ergebnis zur internationalen Schreibweise — damit war dieses Modul
    ausgehebelt. Gemessen wurden so gespeichert:

        '0170123456'      -> 0170123456@c.us       (nationale Schreibweise)
        '004917612345678' -> 004917612345678@c.us  (00 einbetoniert)
        '000000000000'    -> 000000000000@c.us     (Vorwahl 0)
        '49a17b29186846'  -> 491729186846@c.us     (= die Nummer eines
                                                     ECHTEN Kunden)

    Die Regel hier: das `+` kommt nur davor, wenn der Wert weder `+` noch
    `00` noch eine fuehrende `0` mitbringt. Alles Weitere entscheidet
    `normalisiere_empfaenger` — es gibt weiterhin genau eine Nummernregel in
    diesem Haus. Ein Wert mit Zeichen, die dort nicht als Trenner gelten
    (Buchstaben etwa), wird VERWORFEN statt stillschweigend gefiltert.
    """
    wert = str(roh or "").strip()
    if not wert:
        return None, FEHLER_UNZUSTELLBAR
    if not wert.startswith(("+", "00", "0")):
        wert = "+" + wert
    return normalisiere_empfaenger(wert)


def zielnummer(recipient):
    """Nur die Chat-ID, oder None — fuer Anzeigen, die den Grund nicht brauchen."""
    chat_id, _ = normalisiere_empfaenger(recipient)
    return chat_id
