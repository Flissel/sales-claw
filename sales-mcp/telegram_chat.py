"""Telegram-Empfaenger — EINE Regel fuer Anzeige und Versand.

Wortgleiche Begruendung wie `mailadresse.py` und `nummern.py`:
`entwuerfe_offen` zeigt dem Betreiber VOR der Freigabe, an welchen Chat ein
Entwurf ginge — und `telegram_dispatch.py` entscheidet beim Versand, ob er
zustellbar ist. Diese beiden Urteile duerfen nie auseinanderlaufen, sonst
gibt jemand etwas anderes frei als das, was passiert. Ein eigenes Modul,
weil `server.py` den Dispatcher nicht importieren kann (der importiert
`server`).

WAS EINE CHAT-ID IST — und warum sie KEINE Telefonnummer ist
-------------------------------------------------------------
Telegram adressiert Menschen ueber eine numerische `chat_id` (int64). Sie
sieht einer Telefonnummer zum Verwechseln aehnlich — die des Betreibers ist
`1092040975`, zehn Ziffern — und genau das ist die Falle: `nummern.py` bzw.
`sperrliste.kennung_tel` wuerde daraus `tel:+491092040975` machen und damit
eine fremde Festnetznummer in Berlin behaupten. Chat-IDs werden deshalb
NIE durch die Telefon-Normalisierung geschickt; ihre Kennungsform ist
`tg:<ziffern>`.

Negative IDs sind gueltig: Telegram vergibt sie an Gruppen und Kanaele
(`-100…` fuer Supergruppen). Dieses Haus schreibt aber an PERSONEN, und
eine Nachricht, die an eine Gruppe statt an einen Menschen geht, ist der
teuerste denkbare Irrtum. Deshalb laesst dieses Modul ausschliesslich
POSITIVE IDs zu — wer wirklich in eine Gruppe schreiben will, muss das
bewusst hier aendern und dabei ueber die Folge nachdenken.

WARUM DIE BOT-API DIE EINWILLIGUNG NICHT ERSETZT
-------------------------------------------------
Ein Bot kann keinen Chat eroeffnen: die Gegenseite muss ihn zuerst mit
`/start` angeschrieben haben. Dass eine chat_id ueberhaupt existiert, ist
also ein von der Plattform erzwungener Kontakt — aber es ist eine
ERREICHBARKEIT, keine Erlaubnis zur Werbung. Beides bleibt getrennt:
`telegram_freigeben` haelt die Erreichbarkeit fest, `einwilligung_erfassen`
die Erlaubnis. Ein Werkzeug, das aus dem einen das andere schliesst, waere
genau die Abkuerzung, die dieses Haus nicht nimmt.
"""

# Telegram-IDs sind int64. Die Obergrenze steht hier nicht als Schoenheit,
# sondern damit eine versehentlich eingefuegte Kontonummer oder ein
# Zeitstempel in Millisekunden auffaellt statt zugestellt zu werden.
MAX_ID = 2 ** 53          # was JSON noch verlustfrei traegt — Telegrams eigene Grenze

FEHLER_UNZUSTELLBAR = ("kein zustellbarer Telegram-Empfaenger (erwartet: "
                       "eine positive numerische chat_id, z. B. 1092040975)")


def pruefe(roh):
    """chat_id -> (chat_id_als_text, None) | (None, fehler). Wirft nie.

    Gekuerzt wird nur aussen (`strip`) — innen wird nichts repariert. Eine
    ID, die eine Reparatur braucht, ist eine geratene ID, und geraten wird
    bei Empfaengern nicht (dieselbe Regel wie bei Nummern und Adressen:
    lieber eine Rueckfrage als eine Nachricht an einen Fremden).
    """
    text = str(roh or "").strip()
    if not text:
        return None, FEHLER_UNZUSTELLBAR
    # Ausdruecklich KEIN int(text, 0) und kein Entfernen von Trennzeichen:
    # „1.092.040.975" oder „0x41…" sind keine chat_ids, sondern Eingaben,
    # die jemand falsch verstanden hat.
    if not text.isdigit():
        return None, FEHLER_UNZUSTELLBAR
    wert = int(text)
    if wert <= 0 or wert >= MAX_ID:
        return None, FEHLER_UNZUSTELLBAR
    return str(wert), None


def kennung(roh):
    """`tg:<ziffern>` oder None — die Kennungsform fuer Wiedererkennung.

    Bewusst NICHT `tel:` (siehe Moduldocstring) und bewusst nicht in
    `compliance.sperrliste` eintragbar: deren CHECK kennt nur `email:` und
    `tel:`. Die Verbotsliste greift bei Telegram ueber den KONTAKT — seine
    E-Mail und seine Telefonnummer werden in `entwurf_erstellen` wie bei
    jedem anderen Kanal geprueft. Ein Mensch, der irgendwo „nein" gesagt
    hat, bekommt also auch hier nichts.
    """
    wert, fehler = pruefe(roh)
    return None if fehler else "tg:" + wert
