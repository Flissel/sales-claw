"""sales-mail — der Zwilling des Dispatchers fuer den Kanal E-Mail.

Er liest AUSSCHLIESSLICH freigegebene E-Mail-Entwuerfe
(`drafts.status='approved' and channel='email'`) und stellt sie ueber SMTP
zu. Das Freigabe-Gate ist damit auch hier die Datenbank und nicht das
Verhalten eines Sprachmodells (Stufe-3-Plan, Grundsatzentscheidung 1) —
`channel='email'` steht in jeder Query, auch im Claim, genauso wie
`channel='whatsapp'` in dispatch.py steht.

WAS AUS dispatch.py IMPORTIERT WIRD — und warum nicht kopiert
-------------------------------------------------------------
Claim-Marke, Erfolgs- und Fehlerbuchung sind kanalunabhaengig; sie
arbeiten auf `drafts.status` und `drafts.error`. Sie werden deshalb
IMPORTIERT (`dispatch._claim_marke`, `_als_gesendet_buchen`,
`_als_fehler_buchen`, `_einzeilig`), nicht abgeschrieben. Das ist keine
Sparsamkeit: `entwurf_erneut_freigeben` in server.py erkennt einen
haengenden Versand daran, dass `drafts.error` mit `dispatch.CLAIM_PRAEFIX`
beginnt — dem Praefix, das `_claim_marke` schreibt. Gaebe es hier eine
zweite, aehnliche Marke, waere die Schutzkante gegen Doppelversand fuer
E-Mail-Entwuerfe still ausser Kraft. Kein Zirkelimport: mail_dispatch ->
dispatch -> server.

Eigen ist genau das, was WhatsApp-spezifisch war: der Claim mit
`channel='email'`, die Empfaengerpruefung (`mailadresse.pruefe` statt
`nummern.normalisiere_empfaenger`) und der Versandweg (smtplib statt
OpenWA-HTTP).

CLAIM, at-most-once, kein Retry
-------------------------------
Wortgleich zu dispatch.py, inklusive Begruendung: der Claim laeuft ueber
den erlaubten Uebergang approved -> failed mit einer Marke im `error`-Feld
(DDL ist der Rolle `sales_app` verboten, ein Status 'sending' existiert
nicht). Er ist VOR dem Senden committet. Stirbt der Prozess mitten im
Versand, bleibt der Entwurf liegen und wird nie erneut versendet. Ein
liegengebliebener Entwurf ist das kleinere Uebel gegenueber einer zweiten
Mail an einen echten Menschen. Fehlgeschlagene Entwuerfe werden NIE
automatisch wiederholt — der Weg zurueck fuehrt ueber einen Menschen, der
neu freigibt.

KEINE ANHAENGE — bis auf GENAU EINE Ausnahme, und deshalb auch kein
stiller Versand ohne die Unterlage
---------------------------------------------------------------------
Diese Fassung versendet reinen Text (text/plain, UTF-8). Traegt ein
Entwurf ein `media_ref`, wird er ausdruecklich FEHLGESCHLAGEN gebucht,
statt ohne die Unterlage rauszugehen. Der Plan sah vor, `media_ref` bei
E-Mail „wie bisher als Merkposten zu ignorieren" — das galt, solange
E-Mail ein reiner Handversand-Kanal war. Seit dieser Stufe geht die Mail
automatisch raus, und dann ist Ignorieren genau der Fehler, den der
WhatsApp-Weg ausdruecklich nicht macht („Ein Ersatzversand als reiner Text
findet ausdruecklich NICHT statt: freigegeben wurde eine Nachricht mit
Unterlage", dispatch.py). Dieselbe Regel, derselbe Grund.

Termin-Einladungen (Aufgabe 2, 2026-09-11) durchbrechen das NICHT, sondern
sind die eine begruendete Ausnahme: `_anhang_erlaubt` laesst ausschliesslich
`.ics` durch, und die reist dann nicht als Anhang, sondern als
Kalenderteil (`nachricht_mit_einladung`, `method=REQUEST`) — siehe dort.
Ein PDF oder Bild bleibt wie zuvor FEHLGESCHLAGEN.

TLS: DER PORT ENTSCHEIDET (gemessen)
------------------------------------
Der konfigurierte Anbieter (Namecheap PrivateEmail) spricht Port 465 mit
IMPLIZITEM TLS — die Verbindung ist ab dem ersten Byte verschluesselt
(`smtplib.SMTP_SSL`). Der Plan nannte nur STARTTLS/587; beides ist
gebaut, entschieden wird am Port. Unverschluesselt geht es NIE: ohne TLS
reisten Zugangsdaten und Kundentext im Klartext, und `login()` wuerde das
Passwort im Netz ausbreiten.

GEHEIMNISSE: SMTP-Antworten koennen die eigene Anfrage spiegeln (Relays,
Gateways, manche Auth-Fehlertexte). Jeder Fehlertext geht deshalb durch
`_ohne_geheimnis` — dieselbe Klasse wie `_ohne_token` in recherche.py —,
bevor er in `drafts.error`, in den Chat oder ins Log geraet.
"""
import base64
import imaplib
import json
import logging
import os
import re
import signal
import smtplib
import ssl
import sys
import threading
import time
from email.message import EmailMessage

import psycopg

import dispatch
import mailadresse
import medien
import postfach
import server
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORT = os.environ.get("SMTP_PASSWORT", "")
EMAIL_ABSENDER = os.environ.get("EMAIL_ABSENDER", "").strip()

SMTP_TIMEOUT_S = float(os.environ.get("SMTP_TIMEOUT_S", "30"))
MAIL_INTERVAL_S = float(os.environ.get("MAIL_INTERVAL_S", "10"))
MAIL_ONCE = os.environ.get("MAIL_ONCE", "").strip().lower() in (
    "1", "true", "yes", "ja")

# Der Port mit implizitem TLS. Alles andere geht ueber STARTTLS (siehe Kopf).
SMTP_SSL_PORT = 465

STAPEL = 5                 # Entwuerfe je Runde, wie beim Dispatcher
SENDE_PAUSE_S = float(os.environ.get("MAIL_SENDE_PAUSE_S", "1.0"))

# Fallback-Betreff. `drafts.subject` ist optional (nullif(%s,'') in
# entwurf_erstellen) — eine Mail ohne Betreff landet bei manchen
# Empfaengern im Spam, und beim Menschen sieht sie nach Versehen aus.
BETREFF_VORGABE = "Nachricht von unserem Haus"
BETREFF_MAXLAENGE = 200

LOG = logging.getLogger("sales-mail")
_STOPP = threading.Event()

# Ausgaenge, nach denen tatsaechlich eine Verbindung zum Mailserver
# stattgefunden hat — nur danach wird pausiert (gleiche Regel wie im
# Dispatcher: die Pause gilt dem Empfaengerdienst, nicht der Datenbank).
_NETZ_AUSGAENGE = frozenset(("gesendet", "fehler", "gesendet_ohne_buchung"))


class VersandFehler(Exception):
    """Fehlgeschlagener Zustellversuch mit menschenlesbarem Grund."""


def _ohne_geheimnis(text: str) -> str:
    """Das SMTP-Passwort darf in keinem Fehlertext landen.

    Es geht in `drafts.error`, von dort in die Freigabe-Anzeige und in den
    Chat. Fremde Antworttexte spiegeln Anfragen manchmal zurueck; die Zeile
    kostet nichts und schliesst die Klasse Vorfall aus.
    """
    if not SMTP_PASSWORT:
        return text
    # Auch die kodierten Formen (Review-Befund H2): auf der Leitung reist
    # das Passwort als Base64 — allein (AUTH LOGIN) oder als
    # \0user\0passwort-Block (AUTH PLAIN). Ein spiegelnder Gateway gaebe
    # genau diese Darstellung zurueck, nicht den Klartext. Der
    # CalDAV-Zwilling (kalender.py) filtert aus demselben Grund zwei Formen.
    text = text.replace(SMTP_PASSWORT, "***")
    text = text.replace(base64.b64encode(
        SMTP_PASSWORT.encode("utf-8")).decode("ascii"), "***")
    text = text.replace(base64.b64encode(
        f"\0{SMTP_USER}\0{SMTP_PASSWORT}".encode("utf-8")).decode("ascii"),
        "***")
    return text


def _maskiert(adresse: str) -> str:
    """Fuer Logzeilen: erste zwei Zeichen und die Domain, Rest verdeckt.

    Die vollstaendige Adresse steht in der versand-Aktivitaet in der
    Datenbank, wo sie hingehoert — nicht in einem Containerlog, das jeder
    `docker logs` ausspuckt. Gleiche Regel wie `dispatch._maskiert` fuer
    Telefonnummern.
    """
    lokal, _, domain = (adresse or "").partition("@")
    return f"{lokal[:2]}…@{domain}" if domain else "…"


# ---------------------------------------------------------------------------
# Claim / Buchung
# ---------------------------------------------------------------------------

def claim(draft_id):
    """Atomarer Claim approved -> failed+Marke, NUR fuer channel='email'.

    Eigene Fassung statt `dispatch.claim`, weil dort `channel = 'whatsapp'`
    im WHERE steht — und genau diese Klausel ist die Kanaltrennung. Marke
    und Semantik sind dieselben (siehe Moduldocstring).
    """
    marke = _claim_marke()
    zeilen = server._q(
        "update drafts set status = 'failed', error = %s "
        "where id = %s and status = 'approved' and channel = 'email' "
        "returning id, lead_id, recipient, subject, body, media_ref",
        (marke, draft_id))
    if not zeilen:
        return None
    geclaimt = dict(zeilen[0])
    geclaimt["marke"] = marke
    return geclaimt


def _versand_loggen(geclaimt, adresse) -> None:
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": "email",
                     "weg": "mail-dispatcher", "empfaenger": adresse},
                    ensure_ascii=False)))


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

def _betreff(roh: str) -> str:
    """Betreff saeubern — und das ist keine Kosmetik.

    Der Betreff kommt aus `drafts.subject`, also aus einem Text, den ein
    Sprachmodell geschrieben hat. Ein Zeilenumbruch darin waere eine
    Kopfzeilen-Injektion: alles nach dem Umbruch stuende als EIGENE
    Kopfzeile in der Mail (`Bcc:` zum Beispiel). Deshalb werden hier alle
    Zeilenumbrueche und Steuerzeichen zu Leerzeichen und der Rest gekuerzt.
    Dieselbe Ueberlegung wie bei der Empfaengerpruefung in mailadresse.py.
    """
    sauber = " ".join((roh or "").split())
    sauber = "".join(z for z in sauber if z.isprintable())
    return sauber[:BETREFF_MAXLAENGE] or BETREFF_VORGABE


def nachricht_bauen(adresse: str, betreff: str, rumpf: str) -> EmailMessage:
    """Der fertige Text als text/plain, UTF-8.

    `EmailMessage` statt zusammengesetzter Zeichenketten: es kodiert
    Kopfzeilen und Rumpf nach den Regeln, statt sie zu verketten — der
    Umlaut in „Grüße" braucht sonst eine Handkodierung, und Handkodierung
    ist die Stelle, an der Kopfzeilen-Injektionen entstehen.
    """
    nachricht = EmailMessage()
    nachricht["From"] = EMAIL_ABSENDER
    nachricht["To"] = adresse
    nachricht["Subject"] = _betreff(betreff)
    # `cte="quoted-printable"` ist NICHT Geschmack, sondern ein gemessener
    # Fix. Ohne Angabe waehlt `set_content` die Kodierung selbst — und fuer
    # kurze Texte mit Umlauten faellt die Heuristik auf CTE `8bit` zurueck
    # (policy.default hat `cte_type='8bit'`). Diese Verbindung handelt aber
    # kein 8BITMIME aus; smtplib serialisiert den Rumpf dann ueber
    # `BytesGenerator` mit ASCII-Ersatzzeichen, und beim Empfaenger stand
    # „Gr??e" statt „Grüße", das Gedankenstrich-Zeichen sogar als
    # Rohsequenz. Gemessen am Stub der Testsuite
    # (test_umlaute_ueberleben_den_versand faengt genau das ab).
    # Quoted-Printable ist ueberall 7-bit-sicher und bleibt fuer einen
    # deutschen Text kompakt und im Rohtext lesbar.
    nachricht.set_content(rumpf or "", subtype="plain", charset="utf-8",
                          cte="quoted-printable")
    return nachricht


def _anhang_erlaubt(dateiname: str) -> bool:
    """Nur Kalenderdaten duerfen an eine Mail — sonst nichts.

    Der Mailweg lehnte Anhaenge bisher vollstaendig ab
    (`anhang_nicht_unterstuetzt`). Diese eine Ausnahme entsteht, weil eine
    Einladung ohne Kalenderteil keine Einladung ist, sondern eine Textmail.
    Alles andere bleibt abgelehnt: ein PDF-Anhang waere ein neuer Weg nach
    draussen, und den gibt es hier bewusst nicht.
    """
    return (dateiname or "").lower().endswith(".ics")


def nachricht_mit_einladung(adresse: str, betreff: str, rumpf: str,
                            ics_text: str,
                            methode: str = "REQUEST") -> EmailMessage:
    """Eine Mail, die eine Kalendereinladung traegt.

    Der Kalender reist als ALTERNATIVE zum Text, nicht als Anhang daneben:
    so zeigt ein Mailprogramm die Schaltflaechen zum Annehmen und Ablehnen,
    waehrend ein Programm ohne Kalenderunterstuetzung weiterhin den lesbaren
    Text zeigt. Ein zusaetzlicher Anhang derselben Datei ist bewusst NICHT
    dabei — manche Programme zeigen die Einladung dann doppelt.

    `params=` an `add_alternative`: gemessen gegen python:3.12-slim (das
    Image dieses Dienstes) — funktioniert dort, deshalb kein Ausweichen auf
    das nachtraegliche `set_param`.
    """
    if methode not in ("REQUEST", "REPLY", "CANCEL", "COUNTER"):
        raise ValueError(f"unbekannte Methode: {methode!r}")
    nachricht = nachricht_bauen(adresse, betreff, rumpf)
    nachricht.add_alternative(
        ics_text, subtype="calendar", charset="utf-8",
        params={"method": methode, "component": "VEVENT"})
    return nachricht


def _verbindung():
    """Offene, VERSCHLUESSELTE SMTP-Verbindung. Der Port entscheidet.

    465 = implizites TLS (SMTP_SSL, ab dem ersten Byte verschluesselt),
    sonst STARTTLS auf einer zuerst blanken Verbindung. Ohne TLS wird
    nichts gesendet — `login()` wuerde sonst das Passwort im Klartext
    ausbreiten. `create_default_context()` prueft Zertifikat und Hostname
    (Vorgabe der Standardbibliothek); das bleibt so.

    Eigene Funktion, damit die Testsuite genau hier ansetzen kann: sie
    biegt `_verbindung` auf eine blanke Verbindung zum lokalen Stub um und
    beruehrt so nie einen echten Mailserver.
    """
    kontext = ssl.create_default_context()
    if SMTP_PORT == SMTP_SSL_PORT:
        return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_S,
                                context=kontext)
    verbindung = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_S)
    verbindung.ehlo()
    verbindung.starttls(context=kontext)
    verbindung.ehlo()
    return verbindung


def senden(nachricht: EmailMessage) -> None:
    """Eine Nachricht zustellen. Wirft VersandFehler mit lesbarem Grund.

    Die Abbildung der Ausfaelle auf lesbare Texte steht an EINER Stelle —
    sonst liest der Betreiber je nach Ausfallart etwas anderes fuer
    dieselbe Ursache (gleiche Ueberlegung wie `dispatch._senden`).
    """
    verbindung = None
    try:
        verbindung = _verbindung()
        if SMTP_USER:
            verbindung.login(SMTP_USER, SMTP_PASSWORT)
        verbindung.send_message(nachricht)
    except smtplib.SMTPAuthenticationError as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"SMTP-Anmeldung abgelehnt ({e.smtp_code}) — SMTP_USER/"
            f"SMTP_PASSWORT in der .env pruefen (viele Anbieter verlangen "
            f"ein App-Passwort). Antwort: "
            f"{e.smtp_error.decode('utf-8', 'replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"
        ))) from None
    except smtplib.SMTPRecipientsRefused as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"Mailserver weist den Empfaenger zurueck: {e.recipients}"))) from None
    except smtplib.SMTPResponseException as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"Mailserver antwortet mit {e.smtp_code}: "
            f"{e.smtp_error.decode('utf-8', 'replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"
        ))) from None
    except TimeoutError:                # ab 3.10 identisch mit socket.timeout
        raise VersandFehler(
            f"Mailserver antwortet nicht innerhalb von "
            f"{SMTP_TIMEOUT_S:g} s.") from None
    except ssl.SSLError as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"TLS-Fehler zum Mailserver: {e}. Stimmt SMTP_PORT? 465 ist "
            f"implizites TLS, 587 ist STARTTLS."))) from None
    except (OSError, smtplib.SMTPException) as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"Mailserver nicht erreichbar ({type(e).__name__}): {e}"))) from None
    except Exception as e:              # noqa: BLE001 — nie als Traceback sterben
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"Versandfehler {type(e).__name__}: {e}"))) from None
    finally:
        if verbindung is not None:
            try:
                verbindung.quit()
            except Exception:           # noqa: BLE001 — das Abmelden ist Beiwerk
                pass


# ---------------------------------------------------------------------------
# Schleife
# ---------------------------------------------------------------------------

# --- Sent-Kopie (01.09.2026) -----------------------------------------------
# SMTP stellt zu, legt aber nichts in den „Gesendet"-Ordner — der Betreiber
# fand seine erste Betreiber-Mail dort nicht und hielt sie fuer nicht
# versendet. Nach jedem erfolgreichen Versand wird die Mail deshalb per
# IMAP-APPEND in den Sent-Ordner gelegt. BEST EFFORT: die Mail IST beim
# Empfaenger — ein Kopie-Fehler aendert nie die Buchung, er steht im Log.
# Die postfach-WERKZEUGE bleiben strikt readonly; der eine Schreibzugriff
# (die eigene, bereits versendete Mail ablegen) lebt hier beim Versender.

def _sent_moeglich() -> bool:
    return postfach.konfiguriert()


def _sent_verbinden():
    return postfach._verbinden()


def _sent_ordner(kasten) -> str:
    """Der Sent-Ordner laut SPECIAL-USE-Flag (\\Sent) — Namen wie
    'INBOX.Sent' vergibt der Server, nicht wir. Ohne Flag: 'Sent'."""
    status, zeilen = kasten.list()
    if status == "OK":
        for zeile in zeilen or []:
            roh = (zeile.decode("utf-8", "replace")
                   if isinstance(zeile, bytes) else str(zeile))
            if "\\Sent" in roh:
                m = re.search(r'"([^"]+)"\s*$', roh)
                return m.group(1) if m else roh.split()[-1]
    return "Sent"


def _sent_ablegen(nachricht: EmailMessage) -> None:
    kasten = _sent_verbinden()
    try:
        ordner = _sent_ordner(kasten)
        kasten.append(f'"{ordner}"', "\\Seen",
                      imaplib.Time2Internaldate(time.time()),
                      nachricht.as_bytes())
    finally:
        kasten.logout()


def verarbeite_draft(draft_id) -> str:
    """Ein Entwurf: claimen, pruefen, senden, buchen. Gibt den Ausgang zurueck."""
    geclaimt = claim(draft_id)
    if geclaimt is None:
        LOG.info("draft=%s uebersprungen (nicht mehr approved oder fremd "
                 "geclaimt)", draft_id)
        return "uebersprungen"
    marke = geclaimt["marke"]

    adresse, fehler = mailadresse.pruefe(geclaimt["recipient"])
    if fehler:
        _als_fehler_buchen(draft_id, marke, fehler)
        LOG.info("draft=%s nicht zugestellt (%s)", draft_id, fehler)
        return "unzustellbar"

    # Siehe Moduldocstring: lieber ein Entwurf, der auf einen Menschen
    # wartet, als eine Mail ohne die freigegebene Unterlage. Die EINE
    # Ausnahme (Aufgabe 2, 2026-09-11): eine Kalenderdatei geht als
    # Einladung mit, alles andere bleibt abgelehnt — `_anhang_erlaubt`
    # ist dieselbe Regel wie im Kalenderteil-Test.
    ics_text = None
    if geclaimt["media_ref"]:
        if not _anhang_erlaubt(geclaimt["media_ref"]):
            grund = (f"Anhang '{geclaimt['media_ref']}' — der E-Mail-Versand "
                     f"schickt nur Text. Es ging NICHTS raus (auch kein Text "
                     f"ohne Anhang). Ohne Anhang neu erstellen und freigeben — "
                     f"oder die Unterlage von Hand aus dem Mailprogramm "
                     f"schicken; dieser Entwurf bleibt dann als failed "
                     f"dokumentiert (entwurf_manuell_gesendet gilt NUR fuer "
                     f"LinkedIn).")
            _als_fehler_buchen(draft_id, marke, grund)
            LOG.info("draft=%s nicht zugestellt (Anhang, kein Ersatzversand)",
                     draft_id)
            return "anhang_nicht_unterstuetzt"

        # Zweitpruefung unmittelbar vor dem Versand — dieselbe Ueberlegung
        # wie beim WhatsApp-Weg (dispatch.py): zwischen Freigabe und
        # Zustellung koennen Minuten liegen, media/ ist ein Host-Bind, den
        # der Betreiber jederzeit aufraeumen kann.
        basis, medienfehler = medien.pruefe(geclaimt["media_ref"])
        if medienfehler:
            _als_fehler_buchen(
                draft_id, marke,
                f"Kalenderdatei nicht versandfaehig: {medienfehler}")
            LOG.info("draft=%s nicht zugestellt (%s)", draft_id, medienfehler)
            return "anhang_fehlt"
        try:
            ics_text = medien.lies(basis).decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _als_fehler_buchen(
                draft_id, marke,
                f"Kalenderdatei '{basis}' nicht lesbar ({type(e).__name__}).")
            LOG.info("draft=%s nicht zugestellt (Kalenderdatei nicht lesbar)",
                     draft_id)
            return "anhang_fehlt"

    try:
        if ics_text is not None:
            nachricht = nachricht_mit_einladung(adresse, geclaimt["subject"],
                                                geclaimt["body"], ics_text)
        else:
            nachricht = nachricht_bauen(adresse, geclaimt["subject"],
                                        geclaimt["body"])
        senden(nachricht)
    except VersandFehler as e:
        _als_fehler_buchen(draft_id, marke, str(e))
        LOG.info("draft=%s fehlgeschlagen an %s (%s)", draft_id,
                 _maskiert(adresse), _einzeilig(str(e)))
        return "fehler"
    except Exception as e:                  # noqa: BLE001 — bewusst breit
        # Review-Befund H1: `nachricht_bauen` liegt ausserhalb von `senden`s
        # eigenem Fangnetz. Ein Header-ValueError (heute durch die
        # Adress-/Betreffpruefung unerreichbar, aber Konstruktions- statt
        # Verhaltensgarantie) risse sonst den Dienst ab (restart "no") und
        # liesse den Entwurf mit Claim-Marke liegen. Hier wird er zur
        # regulaeren Fehlerbuchung — dieselbe T1/T5a-Lehre wie ueberall.
        grund = _ohne_geheimnis(f"Nachricht nicht konstruierbar "
                                f"({type(e).__name__}: "
                                f"{_einzeilig(str(e))[:200]})")
        _als_fehler_buchen(draft_id, marke, grund)
        LOG.info("draft=%s nicht konstruierbar (%s)", draft_id,
                 type(e).__name__)
        return "fehler"

    # Sent-Kopie NACH dem Versand und VOR der Buchung — die Mail ist raus,
    # die Kopie gehoert ins Postfach, selbst wenn die Buchung scheitert.
    if _sent_moeglich():
        try:
            _sent_ablegen(nachricht)
        except Exception as e:              # noqa: BLE001 — best effort
            LOG.warning("draft=%s gesendet, Sent-Kopie scheiterte (%s: %s)",
                        draft_id, type(e).__name__,
                        _ohne_geheimnis(_einzeilig(str(e))[:120]))

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
        if gebucht:
            _versand_loggen(geclaimt, adresse)
    except psycopg.Error as e:
        gebucht = False
        LOG.critical("draft=%s GESENDET, Buchung scheiterte: %s", draft_id,
                     _einzeilig(str(e)))
    if not gebucht:
        LOG.critical("draft=%s GESENDET, aber Status nicht auf 'sent' gebucht "
                     "— Entwurf bleibt geclaimt liegen, kein zweiter Versand",
                     draft_id)
        return "gesendet_ohne_buchung"

    LOG.info("draft=%s gesendet an %s", draft_id, _maskiert(adresse))
    return "gesendet"


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene E-Mail-Entwuerfe, aelteste zuerst."""
    zeilen = server._q(
        "select id from drafts where status = 'approved' and channel = 'email' "
        "order by created_at limit %s", (STAPEL,))
    bilanz = {}
    letzter_ausgang = None
    for z in zeilen:
        if letzter_ausgang in _NETZ_AUSGAENGE and SENDE_PAUSE_S > 0:
            _STOPP.wait(SENDE_PAUSE_S)      # unterbrechbar durch SIGTERM
        letzter_ausgang = verarbeite_draft(z["id"])
        bilanz[letzter_ausgang] = bilanz.get(letzter_ausgang, 0) + 1
    return bilanz


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen — Ende nach der laufenden Runde.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout (gleiche Lehre wie in dispatch.py).

    `import server` zieht ueber das mcp-Paket eine Root-Konfiguration hoch
    (StreamHandler auf stderr); `logging.basicConfig()` waere danach ein
    stiller No-op. Der Handler haengt deshalb direkt am Modul-Logger.

    Und ausdruecklich AUCH an `dispatch.LOG`: die importierten
    Buchungshelfer loggen ihre `critical`-Saetze dorthin, und die duerfen
    im Log dieses Dienstes nicht fehlen — es sind genau die Saetze, die
    einen Menschen rufen.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for logger in (LOG, dispatch.LOG):
        if logger.handlers:
            continue
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _fehlende_konfiguration() -> list:
    return [name for name, wert in (("SMTP_HOST", SMTP_HOST),
                                    ("SMTP_USER", SMTP_USER),
                                    ("SMTP_PASSWORT", SMTP_PASSWORT),
                                    ("EMAIL_ABSENDER", EMAIL_ABSENDER))
            if not wert]


def main() -> int:
    _logging_einrichten()

    fehlend = _fehlende_konfiguration()
    if fehlend:
        # Exit 0, nicht 2: ein nicht eingerichteter E-Mail-Kanal ist ein
        # gueltiger Zustand dieses Prototyps, kein Ausfall. Der Dienst ist
        # gebaut und getestet, aber inert, bis der Betreiber Zugangsdaten
        # eintraegt — und ein Container, der als „Exited (2)" dasteht,
        # sieht aus wie ein Fehler und wird gesucht.
        LOG.warning("E-Mail-Kanal nicht eingerichtet — %s fehlt in der "
                    "Umgebung (.env). Es wird nichts versendet; freigegebene "
                    "E-Mail-Entwuerfe bleiben unangetastet liegen.",
                    ", ".join(fehlend))
        return 0
    if not mailadresse.pruefe(EMAIL_ABSENDER)[0]:
        LOG.error("EMAIL_ABSENDER ist keine brauchbare Adresse — es wird "
                  "nichts versendet.")
        return 0

    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) — dann eben ohne Handler
    # Weder Passwort noch Absenderadresse ins Log: das eine ist ein
    # Geheimnis, das andere ein Personenbezug.
    LOG.info("Start: schema=%s smtp=%s:%s tls=%s intervall=%gs pause=%gs "
             "once=%s — warte auf freigegebene E-Mail-Entwuerfe.",
             server.SCHEMA, SMTP_HOST, SMTP_PORT,
             "implizit (SSL)" if SMTP_PORT == SMTP_SSL_PORT else "STARTTLS",
             MAIL_INTERVAL_S, SENDE_PAUSE_S, MAIL_ONCE)

    while not _STOPP.is_set():
        try:
            bilanz = eine_runde()
            if bilanz:
                LOG.info("Runde: %s", bilanz)
        except psycopg.Error as e:
            LOG.error("Datenbankfehler — Runde uebersprungen: %s",
                      _einzeilig(str(e)))
        if MAIL_ONCE:
            LOG.info("MAIL_ONCE — eine Runde gelaufen, Ende.")
            break
        _STOPP.wait(MAIL_INTERVAL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
