"""Betreiber-Postfach LESEN (IMAP) — nie veraendern (31.08.2026).

Jede Verbindung oeffnet den Ordner READONLY: kein \\Seen-Flag, kein
Loeschen, kein Verschieben. Das ist die Bedingung, unter der der
Assistent ueberhaupt ins Postfach schauen darf — ein Lesefehler kann
nie eine Mail kosten.

Konfiguration: IMAP_HOST/IMAP_PORT/IMAP_USER/IMAP_PASSWORT, mit
Rueckfall auf die SMTP-Werte — bei Namecheap Private Email (dem Konto
des Betreibers) sind Host und Zugangsdaten fuer beide Wege identisch,
nur der Port unterscheidet sich (993 statt 465).

Alles, was aus einer Mail kommt, ist FREMDDATUM: Header werden
dekodiert und gedeckelt, HTML wird zu Text gestrippt, und nichts davon
ist je eine Anweisung (AGENTS.md, Abschnitt Betreiber-Postfach).
Vertragstests: tests/test_postfach.py (Stub); die Live-Verbindung misst
der Rollout.

Die „nur lesend"-Zusage gilt fuer das IMAP-Postfach des Betreibers, NICHT
fuer die eigene Datenbank: `lesen()` erkennt Antworten auf Einladungen
(Aufgabe 4, 11.09.2026) und haelt sie als Aktivitaet am Kontakt fest —
ein Schreiben im eigenen Protokoll, kein IMAP-Schreiben. Beantwortet oder
markiert wird dabei nichts.
"""
import email
import email.header
import email.utils
import imaplib
import json
import logging
import os
import re
import ssl
from datetime import datetime, timezone

import kalender

# Eigene, aber identisch hergeleitete Zone statt eines Rueckimports aus
# kalender.py oder ui.py — derselbe Grund, den kalender.py fuer seine
# _ORTSZONE dokumentiert: ein Modul soll nicht an der privaten Zonen-
# Instanz eines anderen haengen. Nur fuer die Lesbarkeit der Wiedervorlage-
# Notiz bei einem Gegenvorschlag gebraucht (Aufgabe 5) — die eigentliche
# Auswertung von `neuer_beginn` bleibt zonenbehaftetes UTC aus kalender.py.
try:
    from zoneinfo import ZoneInfo
except Exception:                    # noqa: BLE001 — kein zoneinfo verfuegbar
    ZoneInfo = None
try:
    _ORTSZONE = (ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
                 if ZoneInfo is not None else None)
except Exception:                    # noqa: BLE001 — ohne tzdata: UTC
    _ORTSZONE = None

IMAP_HOST = os.environ.get(
    "IMAP_HOST", os.environ.get("SMTP_HOST", "")).strip()
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ.get(
    "IMAP_USER", os.environ.get("SMTP_USER", "")).strip()
IMAP_PASSWORT = os.environ.get(
    "IMAP_PASSWORT", os.environ.get("SMTP_PASSWORT", ""))

AUSZUG_MAX = 300      # Zeichen je Mail in der Liste
TEXT_MAX = 20000      # Zeichen Volltext — Fremddatum bleibt gedeckelt
ANZAHL_MAX = 25       # Mails je Liste

# Sichtbares Signal, wenn eine Kalenderantwort keinem Teilnehmer zugeordnet
# werden kann (Fix-Runde 3): ohne eigenes Logging-Setup nutzt Python den
# "handler of last resort" und schreibt WARNING+ nach stderr — genug, damit
# so ein Fall nicht stumm bleibt, ohne dass postfach.py (reine Bibliothek,
# kein eigener Prozess wie dispatch.py/inbox.py) eine eigene Handler-
# Konfiguration braucht.
LOG = logging.getLogger("sales-postfach")


def konfiguriert() -> bool:
    return bool(IMAP_HOST and IMAP_USER)


def _verbinden():
    kasten = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT,
                               ssl_context=ssl.create_default_context())
    kasten.login(IMAP_USER, IMAP_PASSWORT)
    return kasten


def _kopf(nachricht, name: str) -> str:
    roh = nachricht.get(name, "")
    teile = []
    for wert, zeichensatz in email.header.decode_header(roh):
        if isinstance(wert, bytes):
            teile.append(wert.decode(zeichensatz or "utf-8",
                                     errors="replace"))
        else:
            teile.append(wert)
    return "".join(teile).strip()


def _html_zu_text(html: str) -> str:
    # Script/Style samt Inhalt weg, dann alle Tags — grob, aber ehrlich:
    # das ist eine Lesehilfe, kein Browser.
    ohne = re.sub(r"<(script|style)\b.*?</\1>", " ", html,
                  flags=re.S | re.I)
    ohne = re.sub(r"<[^>]+>", " ", ohne)
    return " ".join(ohne.split())


def _text(nachricht) -> str:
    """text/plain bevorzugt; sonst text/html gestrippt; sonst leer."""
    kandidaten = (nachricht.walk()
                  if nachricht.is_multipart() else [nachricht])
    html = None
    for teil in kandidaten:
        typ = teil.get_content_type()
        if typ not in ("text/plain", "text/html"):
            continue
        roh = teil.get_payload(decode=True)
        if roh is None:
            continue
        zeichensatz = teil.get_content_charset() or "utf-8"
        wert = roh.decode(zeichensatz, errors="replace")
        if typ == "text/plain":
            return wert.strip()
        if html is None:
            html = wert
    return _html_zu_text(html) if html else ""


def _kalender_teil(nachricht) -> str:
    """Den `text/calendar`-Teil einer Nachricht als Text — leer, wenn
    keiner vorhanden ist.

    Eine Antwort auf eine Einladung (METHOD:REPLY/COUNTER) traegt die
    Kalenderdatei als eigenen MIME-Teil (so verschickt es auch
    `mail_dispatch.nachricht_mit_einladung` beim Versand), nicht als
    generischer Anhang im Sinne von `medien.py`. Decodierung analog zu
    `_text()` oben."""
    kandidaten = (nachricht.walk()
                  if nachricht.is_multipart() else [nachricht])
    for teil in kandidaten:
        if teil.get_content_type() != "text/calendar":
            continue
        roh = teil.get_payload(decode=True)
        if roh is None:
            continue
        zeichensatz = teil.get_content_charset() or "utf-8"
        return roh.decode(zeichensatz, errors="replace")
    return ""


def _absenderadresse(nachricht) -> str:
    """Die reine Adresse aus dem `From`-Header — ohne Anzeigename.

    Fix-Runde 2 (Koordinator, 11.09.2026, Mangel 1): bei einer Antwort auf
    eine Einladung an mehrere Empfaenger ist der Absender der Mail die
    einzige verlaessliche Zuordnung zum tatsaechlich Antwortenden — die
    ICS-Datei selbst spiegelt oft die komplette urspruengliche
    Teilnehmerliste zurueck und aendert nur EINEN Status, die Reihenfolge
    der ATTENDEE-Zeilen verraet also nicht, wer geantwortet hat."""
    _, adresse = email.utils.parseaddr(_kopf(nachricht, "From"))
    return adresse.strip()


def _normalisierte_adresse(adresse: str) -> str:
    """Fuer den Adressvergleich: Leerraum weg, komplett kleingeschrieben.

    Fix-Runde 3 (Koordinator, 11.09.2026): der Domaenenteil einer
    E-Mail-Adresse ist ohnehin nicht schreibungsempfindlich, und viele
    Mailanbieter normalisieren zwar die Domaene automatisch, den lokalen
    Teil aber nicht — eine abweichende Schreibweise zwischen dem
    `From`-Header und der `mailto:`-Zeile in der ICS-Datei ist deshalb
    Alltag, kein Sonderfall. Ausdrueckliche Vorgabe des Koordinators:
    Unterschiede im lokalen Teil als Tippfehler behandeln, nicht als
    absichtliche Unterscheidung — deshalb hier die GANZE Adresse
    kleingeschrieben, nicht nur die Domaene."""
    return (adresse or "").strip().lower()


def _passenden_teilnehmer_waehlen(antwort: dict, absender: str):
    """Bei mehreren ATTENDEE-Zeilen in `antwort["teilnehmende"]` die Zeile
    waehlen, deren (normalisierte) Adresse zum Mail-Absender passt, mit
    `teilnehmer`/`status` darauf gesetzt — oder None (Fix-Runde 2/3,
    Mangel 1).

    KEIN Rueckfall mehr auf die erste Zeile (Fix-Runde 3, ausdrueckliche
    Vorgabe des Koordinators, nachdem Fix-Runde 2 genau das noch tat):
    findet sich der Absender in keiner Zeile — Tippfehler in der
    Schreibweise sind durch `_normalisierte_adresse` bereits
    ausgeschlossen, trotzdem kein Treffer, etwa bei einer Weiterleitung
    von fremder Adresse oder einer Antwort ganz ohne ATTENDEE —, liefert
    diese Funktion None. Der Aufrufer haelt dann NICHTS in der Datenbank
    fest: lieber eine fehlende Aktivitaet als eine falsche unter fremdem
    Namen. Ein Rueckfall auf „irgendeine" Zeile haette genau den
    Verlustmechanismus reproduziert, den Mangel 1 beheben sollte — nur an
    eine andere Bedingung (kein Absender-Treffer statt keine ATTENDEE-
    Zeile ueberhaupt) geknuepft."""
    ziel = _normalisierte_adresse(absender)
    for eintrag in antwort.get("teilnehmende") or []:
        if _normalisierte_adresse(eintrag.get("teilnehmer", "")) == ziel:
            antwort = dict(antwort)
            antwort["teilnehmer"] = eintrag["teilnehmer"]
            antwort["status"] = eintrag["status"]
            return antwort
    return None


def _antwort_festhalten(antwort: dict) -> None:
    """Eine gelesene Kalenderantwort als Aktivitaet `einladung_antwort` am
    passenden Kontakt festhalten (Aufgabe 6 zeigt sie im Kontakt-Verlauf).
    Bei einem Gegenvorschlag (METHOD:COUNTER) kommt zusaetzlich eine
    Wiedervorlage dazu, die dem Betreiber die neue Zeit vorlegt (Aufgabe
    5, siehe `_gegenvorschlag_vorlegen`).

    Das ist ein Schreiben in der EIGENEN Datenbank, kein IMAP-Schreiben —
    die Zusage „nur lesend" am Modulkopf gilt fuer das Postfach des
    Betreibers, nicht fuer das eigene Protokoll. Es wird nichts
    beantwortet und keine fremde Mail veraendert oder markiert.

    `server` wird erst HIER importiert, nicht am Dateikopf: `server.py`
    importiert seinerseits `postfach` auf Modulebene (fuer die Werkzeuge
    `postfach_lesen`/`postfach_mail_lesen`) — ein Import am Kopf dieser
    Datei waere derselbe Ringschluss, den `server.termin_einladen` fuer
    `mail_dispatch`/`dispatch` bereits dokumentiert (dort per
    funktionslokalem Import geloest); hier nur einen Schritt naeher am
    Ring, weil `postfach` direkt in `server`s eigener Importkette steht.

    Findet sich zur Antwortadresse kein Kontakt, wird NICHTS geschrieben
    — eine Antwort von unbekannter Adresse laesst sich niemandem
    zuordnen. Ein zweites Lesen DERSELBEN Antwort (gleicher Kontakt,
    gleiche uid/folge/status/grund) erzeugt keine weitere Zeile: `lesen()`
    ist ein reiner Lesevorgang und darf beliebig oft wiederholt werden,
    ohne das Protokoll bei jedem Aufruf erneut zu befuellen.

    Der GRUND gehoert bewusst mit in den Dedup-Schluessel (Fix-Runde 1,
    Koordinator, 11.09.2026): eine kurze Absage ("kann nicht"), der kurz
    danach eine ausfuehrlichere Begruendung folgt (gleicher Status, gleiche
    SEQUENCE) — genau der Fall, wegen dem der Betreiber ueberhaupt
    hinsieht —, wuerde sonst als Dublette erkannt und die zweite, bessere
    Begruendung verschluckt. Bei tatsaechlich MEHRFACHER Verarbeitung
    derselben Mail bleibt der Schutz erhalten: dieselbe Mail liefert auch
    denselben Grund.

    Ein LEERER Status (Fix-Runde 2, Koordinator, Mangel 2) wird verworfen,
    nicht geschrieben: fehlt PARTSTAT in der ATTENDEE-Zeile, liefert
    `kalender.ics_antwort_lesen` `status == ""` — Aufgabe 6 uebersetzt
    Status-Werte fuer die Anzeige und haette fuer einen leeren Wert keine
    Uebersetzung. Ein Abbilden auf einen erfundenen Ersatzwert (etwa
    "UNKNOWN") wuerde nur vortaeuschen, es sei eine echte Antwort gelesen
    worden — das Verwerfen ist ehrlicher: keine auswertbare Antwort, keine
    Aktivitaet.
    """
    import server
    teilnehmer = (antwort.get("teilnehmer") or "").strip()
    if not teilnehmer:
        return
    status = antwort.get("status") or ""
    if not status:
        return
    leads = server._q("select id from leads where email = %s", (teilnehmer,))
    if not leads:
        return
    lead_id = leads[0]["id"]
    uid = antwort.get("uid") or ""
    folge = antwort.get("folge") or 0
    grund = antwort.get("grund") or ""
    vorhanden = server._q(
        "select 1 from activities where lead_id = %s and "
        "type = 'einladung_antwort' and payload->>'uid' = %s and "
        "payload->>'folge' = %s and payload->>'status' = %s and "
        "payload->>'grund' = %s limit 1",
        (lead_id, uid, str(folge), status, grund))
    if vorhanden:
        return
    neuer_beginn = antwort.get("neuer_beginn")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead_id, json.dumps({
            "uid": uid, "methode": antwort.get("methode") or "",
            "teilnehmer": teilnehmer, "status": status,
            "grund": grund, "folge": folge,
            "neuer_beginn": (neuer_beginn.isoformat()
                            if neuer_beginn else None)})))
    # Aufgabe 5 (11.09.2026): ein Gegenvorschlag ist keine Absage — er
    # traegt einen KONKRETEN neuen Termin, ueber den der Betreiber
    # entscheiden soll. Der Dedup-Schutz oben (fruehes `return` bei
    # `vorhanden`) deckt auch diesen Zweig mit ab: dieselbe Antwort legt
    # nie eine zweite Wiedervorlage an.
    if antwort.get("methode") == "COUNTER" and neuer_beginn is not None:
        _gegenvorschlag_vorlegen(server, lead_id, teilnehmer, neuer_beginn,
                                 grund, uid, folge)


def _gegenvorschlag_vorlegen(server, lead_id: str, teilnehmer: str,
                             neuer_beginn, grund: str, uid: str,
                             folge: int) -> None:
    """Einen Gegenvorschlag (METHOD:COUNTER) dem Betreiber vorlegen —
    ueber dieselbe Wiedervorlage, die auch `termin_bestaetigen` fuer seine
    Terminerinnerung anlegt (`server._wiedervorlage_anlegen`, EIN
    Insert-Muster fuer alle Wiedervorlagen im Projekt).

    `faellig_am` ist HEUTE, nicht der neue Termin: die Entscheidung ist
    sofort faellig, nicht erst am Tag der vorgeschlagenen Zeit — die
    Wiedervorlage erscheint dadurch ab dem naechsten Digest.

    Fix-Runde 2 (Koordinator, 11.09.2026): die Notiz nennt zusaetzlich die
    ALTE Zeit ("statt … jetzt …") — sonst muesste der Betreiber erst in
    der Vorgangshistorie nachsehen, wovon ueberhaupt verschoben wird, und
    die Wiedervorlage waere keine Entscheidungsgrundlage fuer sich allein
    mehr. Die alte Zeit steht in derselben `einladung_entworfen`-
    Aktivitaet, aus der `server.termin_einladen` beim Fortschreiben
    bereits die bisherige `folge` liest (siehe dortige Validierung) —
    hier nur zusaetzlich `datum`/`uhrzeit` derselben Zeile gelesen, kein
    zweiter Abfrageweg. Findet sich keine (z. B. weil der Gegenvorschlag
    zu einer Buchung kam, die nicht ueber `termin_einladen` entstand),
    faellt die Notiz auf die reine „neue Zeit"-Formulierung zurueck, statt
    zu raten oder die Vorlage ganz zu unterlassen.

    Ausdruecklich KEINE automatische Zusage, KEINE automatische neue
    Einladung, KEIN Kalendereintrag (Randbedingungen dieser Stufe): die
    Notiz beschreibt nur, was der Betreiber bei Annahme selbst ausloesen
    muesste — `termin_einladen` mit der neuen Zeit, unter derselben
    Kennung mit erhoehter `folge`."""
    heute = datetime.now(timezone.utc).date()
    lokal = neuer_beginn.astimezone(_ORTSZONE) if _ORTSZONE else neuer_beginn
    bisherige = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_entworfen' and payload->>'uid' = %s "
        "order by (payload->>'folge')::int desc limit 1", (lead_id, uid))
    alt = None
    if bisherige:
        p = bisherige[0]["payload"] or {}
        try:
            alt = datetime.strptime(f"{p.get('datum')} {p.get('uhrzeit')}",
                                    "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            # Unbrauchbares/fehlendes Datum in der alten Aktivitaet — lieber
            # ohne die alte Zeit vorlegen als mit einem falschen Wert.
            alt = None
    kern = (f"statt {alt:%d.%m.%Y %H:%M} jetzt {lokal:%d.%m.%Y %H:%M} Uhr"
            if alt is not None else f"neue Zeit {lokal:%d.%m.%Y %H:%M} Uhr")
    notiz = (f"Gegenvorschlag von {teilnehmer}: {kern} vorgeschlagen"
             + (f" — Grund: {grund}" if grund else "") +
             f". Automatisch passiert nichts — bei Zusage "
             f"termin_einladen mit dieser Zeit aufrufen (bisherige "
             f"Kennung {uid}, folge {folge + 1}).")
    server._wiedervorlage_anlegen(lead_id, heute, notiz)


def _holen(kasten, uid: bytes):
    status, daten = kasten.uid("fetch", uid, "(RFC822)")
    if status != "OK":
        return None
    for teil in daten:
        if isinstance(teil, tuple) and len(teil) >= 2 and teil[1]:
            return email.message_from_bytes(teil[1])
    return None


def liste(anzahl: int = 10) -> list:
    """Die neuesten Mails der INBOX, neueste zuerst — uid, von, betreff,
    datum, auszug, kalenderteil. Wirft bei Verbindungsproblemen (der
    Aufrufer in server.py macht daraus die lesbare Meldung).

    `kalenderteil` (W1, Schlusspruefung 11.09.2026): True, wenn die Mail
    einen `text/calendar`-Teil traegt — genau die Voraussetzung, unter der
    `lesen()` eine Antwort auf eine Einladung erkennt und protokolliert.
    Ohne dieses Feld war eine Antwort nur auffindbar, wenn jemand GENAU
    diese Mail von Hand oeffnete, und nichts in der Liste wies darauf hin,
    dass es sie ueberhaupt gibt — `liste()` wertete den Kalenderteil bisher
    gar nicht aus. Bewusst nur die Anwesenheit des Teils, nicht dessen
    Auswertung (kein `kalender.ics_antwort_lesen` hier): das bliebe
    `lesen()` vorbehalten, das die Antwort auch tatsaechlich festhaelt —
    zwei Stellen, die denselben ICS-Text unterschiedlich weit auswerten,
    driften sonst leicht auseinander (dieselbe Erwaegung wie bei
    `_ics_tzid`, siehe kalender.py)."""
    anzahl = max(1, min(int(anzahl), ANZAHL_MAX))
    kasten = _verbinden()
    try:
        kasten.select("INBOX", readonly=True)
        status, daten = kasten.uid("search", None, "ALL")
        if status != "OK":
            return []
        uids = (daten[0] or b"").split()
        ergebnis = []
        for uid in reversed(uids[-anzahl:]):
            nachricht = _holen(kasten, uid)
            if nachricht is None:
                continue
            text = " ".join(_text(nachricht).split())
            ergebnis.append({
                "uid": uid.decode("ascii", errors="replace"),
                "von": _kopf(nachricht, "From"),
                "betreff": _kopf(nachricht, "Subject"),
                "datum": _kopf(nachricht, "Date"),
                "auszug": (text[:AUSZUG_MAX] + "…"
                           if len(text) > AUSZUG_MAX else text),
                "kalenderteil": bool(_kalender_teil(nachricht)),
            })
        return ergebnis
    finally:
        kasten.logout()


def lesen(uid: str):
    """Eine Mail im Volltext (gedeckelt) — oder None, wenn es sie nicht
    gibt.

    Traegt sie einen `text/calendar`-Teil mit einer erkennbaren Antwort
    (METHOD:REPLY/COUNTER), steht das Ergebnis zusaetzlich unter
    `kalender_antwort` und wird als Aktivitaet am passenden Kontakt
    festgehalten (siehe `_antwort_festhalten`). Rein lesend bleibt dabei
    nur das IMAP-Postfach — das eigene Protokoll darf mitschreiben."""
    kasten = _verbinden()
    try:
        kasten.select("INBOX", readonly=True)
        nachricht = _holen(kasten, str(uid).encode("ascii",
                                                   errors="replace"))
        if nachricht is None:
            return None
        text = _text(nachricht)
        if len(text) > TEXT_MAX:
            text = text[:TEXT_MAX] + "…"
        ergebnis = {"uid": str(uid), "von": _kopf(nachricht, "From"),
                   "an": _kopf(nachricht, "To"),
                   "betreff": _kopf(nachricht, "Subject"),
                   "datum": _kopf(nachricht, "Date"), "text": text}
        # Antworten auf Einladungen (Aufgabe 4): ein text/calendar-Teil mit
        # METHOD:REPLY/COUNTER wird erkannt und am Kontakt festgehalten.
        # Alles andere (kein Kalenderteil, oder ein Teil ohne METHOD:REPLY/
        # COUNTER wie eine faelschlich hier gelandete REQUEST-Einladung)
        # bleibt folgenlos — `kalender.ics_antwort_lesen` liefert dafuer
        # bewusst None.
        kalender_text = _kalender_teil(nachricht)
        if kalender_text:
            antwort = kalender.ics_antwort_lesen(kalender_text)
            if antwort is not None:
                # Mangel 1 (Fix-Runde 2/3): die ICS-Datei allein kennt bei
                # mehreren Teilnehmern nicht, wer geantwortet hat — der
                # Absender der Mail schon (normalisiert verglichen, kein
                # Rueckfall auf die erste Zeile).
                gewaehlt = _passenden_teilnehmer_waehlen(
                    antwort, _absenderadresse(nachricht))
                ergebnis["kalender_antwort"] = (
                    gewaehlt if gewaehlt is not None else antwort)
                if gewaehlt is not None:
                    _antwort_festhalten(gewaehlt)
                else:
                    LOG.warning(
                        "Kalenderantwort (uid=%s) ohne zuordenbaren "
                        "Teilnehmer — keine Aktivitaet festgehalten",
                        antwort.get("uid") or "?")
        return ergebnis
    finally:
        kasten.logout()
