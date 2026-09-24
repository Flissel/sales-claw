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
from dataclasses import dataclass
from email.message import EmailMessage

import psycopg

import dispatch
import mailadresse
import passwort_reset
import medien
import postfach
import server
import verlinken
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORT = os.environ.get("SMTP_PASSWORT", "")
EMAIL_ABSENDER = os.environ.get("EMAIL_ABSENDER", "").strip()

# Zweite Identitaet (24.09.2026): NUR fuer Konto-Mails aus `benutzer_mails`
# - die Adresse des Betreibers, damit auch ein Laden ohne eigenes Postfach
# "Passwort vergessen" und Willkommensmails verschicken kann. Kundenentwuerfe
# laufen NIE hierueber (siehe eine_runde). Fehlt sie, gelten fuer
# Konto-Mails die SMTP_* oben - im Basis-Laden ist das dieselbe Person.
SYSTEM_SMTP_HOST = os.environ.get("SYSTEM_SMTP_HOST", "").strip()
SYSTEM_SMTP_PORT = int(os.environ.get("SYSTEM_SMTP_PORT", "587") or "587")
SYSTEM_SMTP_USER = os.environ.get("SYSTEM_SMTP_USER", "").strip()
SYSTEM_SMTP_PASSWORT = os.environ.get("SYSTEM_SMTP_PASSWORT", "")
SYSTEM_ABSENDER = os.environ.get("SYSTEM_ABSENDER", "").strip()

# Wohin der Link in der Passwort-Mail zeigt. Fehlt sie, wird KEIN
# Konto-Zettel versendet - lieber gar keine Mail als eine mit einem Link,
# der ins Leere zeigt. Je Laden verschieden (der zweite traegt seinen
# eigenen Serve-Port), deshalb aus der Umgebung und nicht geraten.
UI_BASIS_URL = os.environ.get("UI_BASIS_URL", "").strip()

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


@dataclass(frozen=True)
class Identitaet:
    """Mit wessen Zugangsdaten und unter welcher Adresse eine Mail rausgeht."""
    art: str            # "kunde" | "system" - nur fuer Log und Fehlertexte
    host: str
    port: int
    user: str
    passwort: str
    absender: str

    def vollstaendig(self) -> bool:
        return bool(self.host and self.user and self.passwort and self.absender)

    def brauchbar(self) -> bool:
        return self.vollstaendig() and bool(mailadresse.pruefe(self.absender)[0])


def kunden_identitaet() -> Identitaet:
    """Die Identitaet des Ladens selbst. Liest die Modulkonstanten bei jedem
    Aufruf, damit Tests sie wie bisher umbiegen koennen."""
    return Identitaet("kunde", SMTP_HOST, SMTP_PORT, SMTP_USER,
                      SMTP_PASSWORT, EMAIL_ABSENDER)


def system_identitaet() -> Identitaet:
    """Fuer Konto-Mails: die des Betreibers, wenn BRAUCHBAR (vollstaendig
    UND eine gueltige Absenderadresse), sonst die des Ladens.

    Review-Befund (Fix-Runde 1, 24.09.2026): auf `vollstaendig()` allein
    zurueckzufallen war zu schwach - waeren Host/User/Passwort gesetzt, aber
    `SYSTEM_ABSENDER` keine brauchbare Adresse, gaelte die Identitaet hier
    als "vollstaendig" und `eine_runde` haette jeden Konto-Zettel damit als
    `fehler` verbrannt, statt auf die funktionierende Laden-Identitaet
    auszuweichen. `brauchbar()` prueft beides.
    """
    eigen = Identitaet("system", SYSTEM_SMTP_HOST, SYSTEM_SMTP_PORT,
                       SYSTEM_SMTP_USER, SYSTEM_SMTP_PASSWORT, SYSTEM_ABSENDER)
    return eigen if eigen.brauchbar() else kunden_identitaet()


class VersandFehler(Exception):
    """Fehlgeschlagener Zustellversuch mit menschenlesbarem Grund."""


def _ohne_geheimnis(text: str) -> str:
    """Das SMTP-Passwort darf in keinem Fehlertext landen.

    Es geht in `drafts.error`, von dort in die Freigabe-Anzeige und in den
    Chat. Fremde Antworttexte spiegeln Anfragen manchmal zurueck; die Zeile
    kostet nichts und schliesst die Klasse Vorfall aus.
    """
    # Seit 24.09.2026 fuer BEIDE Identitaeten.
    for user, passwort in ((SMTP_USER, SMTP_PASSWORT),
                           (SYSTEM_SMTP_USER, SYSTEM_SMTP_PASSWORT)):
        if not passwort:
            continue
        # Auch die kodierten Formen (Review-Befund H2): auf der Leitung
        # reist das Passwort als Base64 - allein (AUTH LOGIN) oder als
        # \0user\0passwort-Block (AUTH PLAIN).
        text = text.replace(passwort, "***")
        text = text.replace(base64.b64encode(
            passwort.encode("utf-8")).decode("ascii"), "***")
        text = text.replace(base64.b64encode(
            f"\0{user}\0{passwort}".encode("utf-8")).decode("ascii"), "***")
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
        "returning id, lead_id, recipient, subject, body, media_ref, cc",
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


def nachricht_bauen(adresse: str, betreff: str, rumpf: str,
                    cc=None, absender=None) -> EmailMessage:
    """Der fertige Text als text/plain, UTF-8.

    `EmailMessage` statt zusammengesetzter Zeichenketten: es kodiert
    Kopfzeilen und Rumpf nach den Regeln, statt sie zu verketten — der
    Umlaut in „Grüße" braucht sonst eine Handkodierung, und Handkodierung
    ist die Stelle, an der Kopfzeilen-Injektionen entstehen.
    """
    nachricht = EmailMessage()
    nachricht["From"] = absender or EMAIL_ABSENDER
    nachricht["To"] = adresse
    # CC (03.09.2026): kommt geprueft aus drafts.cc (mailadresse.pruefe je
    # Adresse beim Anlegen/Bearbeiten); hier nur noch einzeilig gemacht, aus
    # demselben Grund wie beim Betreff. send_message nimmt To UND Cc als
    # Umschlag-Empfaenger.
    cc_zeile = " ".join(str(cc or "").split())
    if cc_zeile:
        nachricht["Cc"] = cc_zeile
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
    # HTML-FASSUNG, SOBALD EIN LINK IM TEXT STEHT (23.09.2026). Der Betreiber
    # hatte am 03.09.2026 klickbare Hyperlinks verlangt; umgesetzt wurde das
    # nur in der Oberflaeche. Gemessen am 23.09.2026: eine Terminbestaetigung
    # an einen Kunden trug ihren Konferenzlink als nackte Zeichenkette — ob
    # er klickbar war, entschied allein das Mailprogramm des Empfaengers.
    #
    # Die Textfassung bleibt WOERTLICH, was freigegeben wurde; die HTML-
    # Fassung ist nur ihre Darstellung, nach derselben Regel wie in der
    # Oberflaeche (`verlinken.py`: erst escapen, dann verlinken, nur http(s)).
    # Ohne Link bleibt die Mail reiner Text — kein Anlass, kein Umbau.
    if verlinken.enthaelt_link(rumpf):
        nachricht.add_alternative(_html_fassung(rumpf), subtype="html",
                                  charset="utf-8", cte="quoted-printable")
    return nachricht


def _html_fassung(rumpf: str) -> str:
    """Der Text als schlichtes HTML: Zeilen bleiben Zeilen, Links werden Links.

    `<br>` statt `white-space: pre-wrap`, weil Outlook Stilangaben dieser Art
    verwirft und den Text dann in eine einzige Zeile zoege.
    """
    zeilen = verlinken.text_html(rumpf).split("\n")
    return ('<!doctype html><html><body style="font-family:Arial,sans-serif;'
            'font-size:14px;line-height:1.5">' + "<br>\n".join(zeilen)
            + "</body></html>")


# Was ausser dem Kalender an eine Mail darf, mit dem Medientyp, unter dem es
# reist. Bewusst KURZ: was hier nicht steht, geht nicht raus.
ANHANG_TYPEN = {
    ".pdf": ("application", "pdf"),
    ".png": ("image", "png"),
    ".jpg": ("image", "jpeg"),
    ".jpeg": ("image", "jpeg"),
}

# Eigene, ENGERE Schranke als medien.MAX_BYTES (15 MB). Eine Mail waechst
# durch die Base64-Kodierung um rund ein Drittel, und die meisten Empfaenger
# — Gmail eingeschlossen — weisen ueber 25 MB Nachrichtengroesse ab. 8 MB
# roh werden zu etwa 10,7 MB Nachricht und passen ueberall; 15 MB roh waeren
# 20 MB und stiessen bei manchen an. Lieber hier mit klarem Satz ablehnen
# als beim Empfaenger unzustellbar sein.
ANHANG_MAX_BYTES = 8 * 1024 * 1024


def _anhang_erlaubt(dateiname: str) -> bool:
    """Kalenderdaten, PDF und Bilder duerfen an eine Mail — sonst nichts.

    HIER STAND BIS ZUM 12.09.2026 „nur .ics", mit der Begruendung: „ein
    PDF-Anhang waere ein neuer Weg nach draussen, und den gibt es hier
    bewusst nicht." Diese Begruendung ist entfallen, und zwar aus einem
    nachpruefbaren Grund — nicht weil sie unbequem war:

    Als sie geschrieben wurde, war der Mailweg EIN Weg nach draussen unter
    mehreren, und Marketing hatte einen eigenen daneben. Seit dem
    Betreiber-Entscheid vom selben Tag ist sales-claw der EINZIGE Versandweg
    des Hauses: jede Nachricht — auch jede aus dem Marketing — laeuft durch
    `entwurf_erstellen` (gemeinsame Verbotsliste, Loeschantrag, Privat-Flag,
    UWG, Kontakt-Freigabe, Anhangspruefung), landet als Entwurf in der
    Warteschlange und wartet auf einen Menschen. Ein Anhang ist damit kein
    zusaetzlicher Weg mehr, sondern Fracht auf einem Weg, der bereits
    bewacht ist.

    Der Anlass war konkret: Layout-Vorlagen sollen dem Betreiber als
    Musterblatt an seine Firmenadresse gehen, damit er sie ansieht, bevor er
    sie freigibt. Eine Freigabe ohne Anschauung ist keine.

    WAS BLEIBT: die Regel „lieber kein Versand als einer ohne die
    freigegebene Unterlage". Was hier durchfaellt, wird fehlgeschlagen
    gebucht — es geht NIE ein Ersatztext ohne Anhang raus.
    """
    name = (dateiname or "").lower()
    return name.endswith(".ics") or any(name.endswith(e) for e in ANHANG_TYPEN)


def _anhang_anfuegen(nachricht, basis: str, roh: bytes) -> str:
    """Haengt `roh` als Datei an. Gibt '' zurueck oder einen Grund.

    Der Dateiname reist so, wie er im Medienordner heisst: der Empfaenger
    soll `muster-vorlage-warm-sand.pdf` sehen und nicht `anhang.bin`.
    """
    endung = "." + basis.rsplit(".", 1)[-1].lower() if "." in basis else ""
    typ = ANHANG_TYPEN.get(endung)
    if typ is None:
        return f"Anhang '{basis}' hat keinen Typ, den der Mailweg kennt."
    if len(roh) > ANHANG_MAX_BYTES:
        return (f"Anhang '{basis}' ist {len(roh) // 1048576} MB gross; per "
                f"Mail gehen hoechstens {ANHANG_MAX_BYTES // 1048576} MB "
                f"(die Kodierung schlaegt noch ein Drittel drauf, und viele "
                f"Empfaenger weisen ueber 25 MB ab).")
    nachricht.add_attachment(roh, maintype=typ[0], subtype=typ[1],
                             filename=basis)
    return ""


def nachricht_mit_einladung(adresse: str, betreff: str, rumpf: str,
                            ics_text: str,
                            methode: str = "REQUEST",
                            cc=None) -> EmailMessage:
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
    # `cc` durchgereicht (Merge 12.09.2026): sonst traegt eine Einladung als
    # einzige ausgehende Mailart kein CC, obwohl drafts.cc gefuellt sein kann.
    nachricht = nachricht_bauen(adresse, betreff, rumpf, cc=cc)
    nachricht.add_alternative(
        ics_text, subtype="calendar", charset="utf-8",
        params={"method": methode, "component": "VEVENT"})
    return nachricht


def _verbindung(identitaet=None):
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
    ident = identitaet or kunden_identitaet()
    kontext = ssl.create_default_context()
    if ident.port == SMTP_SSL_PORT:
        return smtplib.SMTP_SSL(ident.host, ident.port,
                                timeout=SMTP_TIMEOUT_S, context=kontext)
    verbindung = smtplib.SMTP(ident.host, ident.port, timeout=SMTP_TIMEOUT_S)
    verbindung.ehlo()
    verbindung.starttls(context=kontext)
    verbindung.ehlo()
    return verbindung


def senden(nachricht: EmailMessage, identitaet=None) -> None:
    """Eine Nachricht zustellen. Wirft VersandFehler mit lesbarem Grund.

    Die Abbildung der Ausfaelle auf lesbare Texte steht an EINER Stelle —
    sonst liest der Betreiber je nach Ausfallart etwas anderes fuer
    dieselbe Ursache (gleiche Ueberlegung wie `dispatch._senden`).
    """
    ident = identitaet or kunden_identitaet()
    praefix = "SYSTEM_SMTP" if ident.art == "system" else "SMTP"
    verbindung = None
    try:
        verbindung = _verbindung(ident)
        if ident.user:
            verbindung.login(ident.user, ident.passwort)
        verbindung.send_message(nachricht)
    except smtplib.SMTPAuthenticationError as e:
        raise VersandFehler(_ohne_geheimnis(_einzeilig(
            f"SMTP-Anmeldung abgelehnt ({e.smtp_code}) — {praefix}_USER/"
            f"{praefix}_PASSWORT in der .env pruefen (viele Anbieter verlangen "
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
            f"TLS-Fehler zum Mailserver: {e}. Stimmt {praefix}_PORT? 465 ist "
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
    # wartet, als eine Mail ohne die freigegebene Unterlage. Seit dem
    # 12.09.2026 duerfen ausser der Kalenderdatei auch PDF und Bilder mit
    # (`_anhang_erlaubt`, Begruendung dort) — die Regel „kein Ersatzversand
    # ohne Anhang" bleibt dabei unveraendert.
    ics_text = None
    anhang = None                 # (basis, roh) fuer alles ausser .ics
    if geclaimt["media_ref"]:
        if not _anhang_erlaubt(geclaimt["media_ref"]):
            grund = (f"Anhang '{geclaimt['media_ref']}' — der E-Mail-Versand "
                     f"kennt diesen Typ nicht. Es ging NICHTS raus (auch kein "
                     f"Text ohne Anhang). Erlaubt sind .ics, .pdf, .png, .jpg "
                     f"und .jpeg; alles andere von Hand aus dem Mailprogramm "
                     f"schicken — dieser Entwurf bleibt dann als failed "
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
                draft_id, marke, f"Anhang nicht versandfaehig: {medienfehler}")
            LOG.info("draft=%s nicht zugestellt (%s)", draft_id, medienfehler)
            return "anhang_fehlt"

        ist_kalender = basis.lower().endswith(".ics")
        try:
            roh = medien.lies(basis)
        except OSError as e:
            _als_fehler_buchen(
                draft_id, marke,
                f"Anhang '{basis}' nicht lesbar ({type(e).__name__}).")
            LOG.info("draft=%s nicht zugestellt (Anhang nicht lesbar)", draft_id)
            return "anhang_fehlt"
        if ist_kalender:
            try:
                ics_text = roh.decode("utf-8")
            except UnicodeDecodeError as e:
                _als_fehler_buchen(
                    draft_id, marke,
                    f"Kalenderdatei '{basis}' nicht lesbar ({type(e).__name__}).")
                LOG.info("draft=%s nicht zugestellt (Kalenderdatei nicht lesbar)",
                         draft_id)
                return "anhang_fehlt"
        else:
            anhang = (basis, roh)

    try:
        # Merge 12.09.2026: hier trafen zwei Aenderungen aufeinander — der
        # Einladungszweig (ics_text) und CC aus drafts.cc. Beide bleiben, und
        # CC gilt AUCH fuer Einladungen: wer einen Termin vorschlaegt, will
        # den Kollegen genauso in Kopie setzen koennen wie bei jeder anderen
        # Mail. Ohne die Durchreichung waere CC bei Einladungen still
        # verschwunden.
        if ics_text is not None:
            nachricht = nachricht_mit_einladung(adresse, geclaimt["subject"],
                                                geclaimt["body"], ics_text,
                                                cc=geclaimt.get("cc"))
        else:
            nachricht = nachricht_bauen(adresse, geclaimt["subject"],
                                        geclaimt["body"],
                                        cc=geclaimt.get("cc"))
        if anhang is not None:
            # NACH dem Bauen, VOR dem Senden: schlaegt das Anhaengen fehl
            # (zu gross, unbekannter Typ), geht nichts raus — dieselbe
            # Regel wie oben, nur an der letzten moeglichen Stelle.
            fehler_anhang = _anhang_anfuegen(nachricht, anhang[0], anhang[1])
            if fehler_anhang:
                _als_fehler_buchen(draft_id, marke, fehler_anhang)
                LOG.info("draft=%s nicht zugestellt (%s)", draft_id,
                         _einzeilig(fehler_anhang)[:120])
                return "anhang_nicht_unterstuetzt"
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


def verarbeite_kontomail(zettel_id) -> str:
    """Eine Mail des Hauses AN SICH SELBST (17.09.2026).

    WARUM HIER UND NICHT IN DER OBERFLAECHE: nach T5a liegt Sendemacht
    ausschliesslich bei den Versand-Diensten, damit das Freigabe-Tor die
    Datenbank bleibt. `sales-ui` hat keine SMTP-Zugangsdaten und darf
    keine bekommen; sie legt deshalb nur einen Zettel in
    `benutzer_mails`, und abgeholt wird er hier.

    WARUM DIESE MAIL NICHT DURCH `drafts` GEHT: das waere ein Zirkel -
    wer freigibt, ist gerade der Ausgesperrte. Die Ausnahme ist eng, und
    die Regeln stehen JETZT dort, wo auch die Sendemacht liegt:
      * Empfaenger ist ausschliesslich `benutzer.email` eines
        BESTEHENDEN, AKTIVEN Kontos - nie eine Adresse vom Zettel.
      * Der Text ist fest (`passwort_reset.mailtext`); es gibt keinen
        Parameter, mit dem jemand eigenen Inhalt hineinschriebe.
      * Der Zettel traegt nur einen Kontonamen. Wer ihn faelschen
        koennte, loeste dieselbe Mail an dieselbe Adresse aus wie ueber
        das Formular - keine neue Macht.

    DER TOKEN ENTSTEHT HIER, nicht in der Oberflaeche: so erreicht der
    Klartext die Datenbank nie, auch nicht fuer die Sekunden, die ein
    Zettel liegt. Gespeichert wird nur sein sha256-Hash.
    """
    zeilen = server._q(
        "select id, benutzer, art, status from benutzer_mails where id = %s",
        (zettel_id,))
    if not zeilen or zeilen[0]["status"] != "offen":
        return "uebersprungen"
    zettel = zeilen[0]

    def _schliessen(status, grund=""):
        server._q("update benutzer_mails set status = %s, grund = %s, "
                  "erledigt_am = now() where id = %s returning id",
                  (status, grund[:500], zettel["id"]))
        return status

    def _bremse_freigeben(name):
        # Ein Fehlschlag, den der Mensch nicht verursacht hat, darf ihn
        # nicht aussperren. Ohne diese Zeile blieb er eine Viertelstunde
        # draussen - und die immer gleiche Antwort der Seite verbarg es
        # (gemessen 17.09.2026).
        server._q("update benutzer set reset_hash = null, reset_bis = null, "
                  "reset_zuletzt = null where name = %s returning name",
                  (name,))

    arten = {
        "passwort_reset": (passwort_reset.GUELTIG_S, passwort_reset.BETREFF,
                           passwort_reset.mailtext),
        "willkommen": (passwort_reset.WILLKOMMEN_GUELTIG_S,
                       passwort_reset.WILLKOMMEN_BETREFF,
                       passwort_reset.willkommenstext),
    }
    if zettel["art"] not in arten:
        return _schliessen("fehler", "unbekannte Art: %s" % zettel["art"])
    gueltig_s, betreff, text = arten[zettel["art"]]

    if not UI_BASIS_URL:
        # Lieber keine Mail als eine mit totem Link. Die Bremse geht auf,
        # damit ein spaeterer Versuch nach dem Nachtragen sofort greift.
        _bremse_freigeben(zettel["benutzer"])
        LOG.error("UI_BASIS_URL fehlt in der Umgebung dieses Dienstes - der "
                  "Link in der Passwort-Mail zeigte auf nichts. Zettel %s "
                  "nicht versendet.", zettel["id"])
        return _schliessen("fehler", "UI_BASIS_URL fehlt")

    konten = server._q(
        "select name, email, aktiv from benutzer where name = %s",
        (zettel["benutzer"],))
    if (not konten or not konten[0]["aktiv"]
            or not (konten[0]["email"] or "").strip()):
        # Zwischen Zettel und Versand kann sich etwas geaendert haben -
        # deshalb hier NOCH EINMAL pruefen, nicht der Oberflaeche glauben.
        _bremse_freigeben(zettel["benutzer"])
        return _schliessen("fehler", "kein brauchbares Konto")
    konto = konten[0]

    klartext, gehasht = passwort_reset.token_erzeugen()
    server._q(
        "update benutzer set reset_hash = %s, "
        "reset_bis = now() + make_interval(secs => %s) "
        "where name = %s returning name",
        (gehasht, gueltig_s, konto["name"]))
    try:
        # Konto-Mail (24.09.2026): geht IMMER ueber die Betreiber-Identitaet,
        # wenn sie vollstaendig gesetzt ist - nie ueber die des Ladens, damit
        # auch ein Laden ohne eigenes Postfach seinen Menschen den Zugang
        # zurueckgeben kann. `system_identitaet()` faellt sonst selbst auf die
        # des Ladens zurueck (siehe dort).
        system = system_identitaet()
        nachricht = nachricht_bauen(
            konto["email"], betreff,
            text(konto["name"],
                 passwort_reset.link_bauen(UI_BASIS_URL, konto["name"],
                                           klartext)),
            absender=system.absender)
        senden(nachricht, identitaet=system)
    except Exception as e:      # noqa: BLE001 - ein Ausfall darf die Runde nicht reissen
        # Der Token darf nicht stehenbleiben: ein gueltiger Token ohne
        # Empfaenger ist ein offenes Fenster, das niemand bemerkt.
        _bremse_freigeben(konto["name"])
        grund = _ohne_geheimnis("%s: %s" % (type(e).__name__, e))
        LOG.warning("Passwort-Mail nicht versendet (%s)", grund)
        return _schliessen("fehler", grund)

    LOG.info("Konto-Mail (%s) versendet an %s", zettel["art"],
             _maskiert(konto["email"]))
    return _schliessen("gesendet")


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene E-Mail-Entwuerfe, aelteste zuerst."""
    # DIE WEICHE (24.09.2026): Kundenentwuerfe nur mit der EIGENEN Identitaet
    # des Ladens. Fehlt sie, bleiben sie `approved` liegen und gehen raus,
    # sobald das Postfach eingetragen ist - nie ueber die des Betreibers.
    if kunden_identitaet().brauchbar():
        zeilen = server._q(
            "select id from drafts where status = 'approved' "
            "and channel = 'email' order by created_at limit %s", (STAPEL,))
    else:
        zeilen = []
    bilanz = {}
    letzter_ausgang = None
    for z in zeilen:
        if letzter_ausgang in _NETZ_AUSGAENGE and SENDE_PAUSE_S > 0:
            _STOPP.wait(SENDE_PAUSE_S)      # unterbrechbar durch SIGTERM
        letzter_ausgang = verarbeite_draft(z["id"])
        bilanz[letzter_ausgang] = bilanz.get(letzter_ausgang, 0) + 1

    # Konto-Zettel NACH den Entwuerfen, aber in derselben Runde: sie sind
    # selten und klein, und ein Mensch, der sich ausgesperrt hat, wartet
    # sonst bis zum naechsten Durchlauf. Eigene Zaehler, damit die Bilanz
    # im Log die beiden Arten nicht vermischt.
    for z in server._q(
            "select id from benutzer_mails where status = 'offen' "
            "order by erstellt_am limit %s", (STAPEL,)):
        if letzter_ausgang in _NETZ_AUSGAENGE and SENDE_PAUSE_S > 0:
            _STOPP.wait(SENDE_PAUSE_S)
        letzter_ausgang = verarbeite_kontomail(z["id"])
        schluessel = "konto:%s" % letzter_ausgang
        bilanz[schluessel] = bilanz.get(schluessel, 0) + 1
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

    kunde_aktiv = kunden_identitaet().brauchbar()
    system = system_identitaet()
    konto_aktiv = system.brauchbar()
    if not (kunde_aktiv or konto_aktiv):
        # Exit 0, nicht 2: ein nicht eingerichteter E-Mail-Kanal ist ein
        # gueltiger Zustand dieses Prototyps, kein Ausfall.
        fehlend = _fehlende_konfiguration()
        if fehlend:
            LOG.warning("E-Mail-Kanal nicht eingerichtet — %s fehlt in der "
                        "Umgebung (.env). Es wird nichts versendet; "
                        "freigegebene E-Mail-Entwuerfe bleiben unangetastet "
                        "liegen.", ", ".join(fehlend))
        else:
            LOG.error("EMAIL_ABSENDER ist keine brauchbare Adresse — es wird "
                      "nichts versendet.")
        return 0
    LOG.info("Aktiv: kundenmails=%s kontomails=%s (identitaet=%s)",
             "ja" if kunde_aktiv else "nein — Entwuerfe bleiben liegen",
             "ja" if konto_aktiv else "nein", system.art)

    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) — dann eben ohne Handler
    # Weder Passwort noch Absenderadresse ins Log: das eine ist ein
    # Geheimnis, das andere ein Personenbezug. Seit Fix-Runde 1 (24.09.2026)
    # nennt die Zeile Host/Port der TATSAECHLICH aktiven Identitaet(en) statt
    # blind SMTP_HOST/SMTP_PORT — bei reiner System-Identitaet waren die
    # sonst leer. Der Entwurfs-Hinweis steht nur, wenn Kundenmails aktiv sind.
    teile = []
    if kunde_aktiv:
        modus = "SSL" if SMTP_PORT == SMTP_SSL_PORT else "STARTTLS"
        teile.append(f"kunde={SMTP_HOST}:{SMTP_PORT} ({modus})")
    if konto_aktiv:
        modus = "SSL" if system.port == SMTP_SSL_PORT else "STARTTLS"
        teile.append(f"system={system.host}:{system.port} ({modus})")
    LOG.info("Start: schema=%s %s intervall=%gs pause=%gs once=%s%s",
             server.SCHEMA, " ".join(teile), MAIL_INTERVAL_S, SENDE_PAUSE_S,
             MAIL_ONCE,
             " — warte auf freigegebene E-Mail-Entwuerfe." if kunde_aktiv else "")

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
