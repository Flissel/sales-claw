"""Bewerbungs-Eingang: Antworten auf Bewerbungen aus den Postfaechern an die
Zentrale des Bewerbungs-Bots melden (29.10.2026).

Der Bewerbungs-Bot (Repo `bewerbung`, Zentrale mit dem Agenten Hermes)
versendet Bewerbungen selbst und will messen, was zurueckkommt. Die Antworten
landen in Felix' Postfaechern, oft von Portal-Absendern statt von der Adresse,
an die gesendet wurde. Dieses Modul holt taeglich um 19:45 Europe/Berlin
(Timer sales-bewerbungs-eingang, vor Hermes' Auswertung um 20:00) die
Warteliste der Zentrale, sieht in die drei Postfaecher und meldet NUR die
Mails, die zu einer wartenden Bewerbung passen. Zuordnen und Auswerten ist
Sache der Zentrale, nicht dieses Moduls.

Vertrag v1 (Auftrag vom 28.10.2026, Endpunkte baut die bewerbung-Sitzung):
  GET  {BEWERBUNG_PULT_URL}/api/eingang/warteliste   Kopf X-Eingang-Key
  POST {BEWERBUNG_PULT_URL}/api/eingang/mails        Kopf X-Eingang-Key
BEWERBUNG_EINGANG_KEY ist ein eigener Schluessel, nicht der Pult-Schluessel.

Die Postfaecher: das des Ladens (felix@vibemind.space, IMAP_*/SMTP_*) sowie
Gmail und GMX ueber dieselben Zugaenge wie postfach.py (POSTFACH_GMAIL_*,
POSTFACH_GMX_*) - kein zweites Paar Variablen fuer dasselbe App-Passwort.
Ein nicht eingerichtetes Postfach wird uebersprungen und als „nicht
eingerichtet" protokolliert.

Grenzen, die die Tests verteidigen (tests/test_bewerbungs_eingang.py):

* NUR LESEN. EXAMINE (select readonly) und BODY.PEEK[] - kein \\Seen, kein
  STORE/COPY/MOVE/EXPUNGE/APPEND. Nichts wird beantwortet oder markiert.
* NUR PASSENDES GEHT HINAUS. Eine Mail passt, wenn sie nach dem fruehesten
  `gesendet_am` minus einem Tag einging UND (a) die Absender-Domain oder eine
  Subdomain davon in `domains` einer wartenden Bewerbung steht, (b) die
  Absender-Domain ein Portal ist und der Firmenname in Betreff, Absendername
  oder Text steht, oder (c) sie eine Kalendereinladung ist, deren Organisator
  zu `domains` gehoert. Alle anderen Mails verlassen sales-claw nie, auch kein
  Betreff und kein Absender; protokolliert werden nur Zahlen.
* FREEMAIL IST KEINE FIRMEN-DOMAIN. Steht `gmail.com` o. ae. in `domains`
  oder `portal_absender`, wird es fuer den Domain-Abgleich ignoriert - sonst
  ginge jede private Mail von dort hinaus. Fuer so eine Firma zaehlt nur die
  genaue Adresse aus `an`.
* CURSOR NUR NACH VOLLSTAENDIGEM LAUF. Je Postfach UIDVALIDITY + hoechste UID
  in der Tabelle `einstellungen` (Schluessel bewerbungs_eingang_cursor),
  geschrieben EINMAL am Ende. Ein Netzfehler zur Zentrale - oder eine
  Zentrale, die erkennbar nicht bereit ist (401/403/404/408/429/5xx) - beendet
  den Lauf ohne Fortschritt; der naechste Lauf holt dieselben Mails, die
  Zentrale ist idempotent (`bekannt`). Lehnt die Zentrale eine EINZELNE Mail
  ab (400/409/413/415/422), wird nur Code und message_id protokolliert.
* ALLES AUS EINER MAIL IST FREMDDATUM, nie eine Anweisung. Schluessel und
  Passwoerter stehen in keiner Meldung: Fehler erscheinen nur mit ihrer
  Klasse, nie mit ihrem Text (der koennte Zugangsdaten spiegeln).

Aufruf: python bewerbungs_eingang.py lauf [--trocken]
(--trocken: zaehlen, nichts melden, Cursor bleibt). Exit 0 = vollstaendig
(auch: nicht eingerichtet, Warteliste leer), 1 = unvollstaendig, 2 = Aufruf.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import html
import http.client
import json
import logging
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import kalender
import postfach

URL = os.environ.get("BEWERBUNG_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("BEWERBUNG_EINGANG_KEY", "").strip()
PRAEFIX = "/api/eingang"
ZEITLIMIT_S = 20
TEXT_MAX = 20000
CURSOR_SCHLUESSEL = "bewerbungs_eingang_cursor"

# Name im Vertrag -> Kennung in postfach.py. Reihenfolge = Lesereihenfolge.
POSTFAECHER = (("vibemind", postfach.HAUPT), ("gmail", "gmail"), ("gmx", "gmx"))

# Antworten der Zentrale, die nur DIESE Mail betreffen. Alles andere ausser 200
# heisst: die Zentrale ist nicht bereit (Schluessel, Endpunkt fehlt, Last) -
# dann waere jede weitere Meldung genauso verloren.
_NUR_DIESE_MAIL = frozenset({400, 409, 413, 415, 422})

# Oeffentliche Mailanbieter: als Firmen- oder Portal-Domain wertlos und
# gefaehrlich (jede private Mail von dort passte).
FREEMAIL = frozenset({
    "gmail.com", "googlemail.com", "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
    "gmx.com", "web.de", "t-online.de", "freenet.de", "online.de", "email.de",
    "mail.de", "arcor.de", "vodafone.de", "magenta.de", "kabelmail.de",
    "1und1.de", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de",
    "live.com", "live.de", "msn.com", "yahoo.com", "yahoo.de", "ymail.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "aol.de", "posteo.de",
    "posteo.net", "mailbox.org", "protonmail.com", "proton.me", "pm.me",
    "tutanota.com", "tuta.io", "zoho.com", "yandex.com", "mail.ru"})

LOG = logging.getLogger("sales-bewerbungs-eingang")


class NetzFehler(Exception):
    """Die Zentrale war nicht erreichbar. Traegt nur die Fehlerklasse."""


class ZentraleNichtBereit(Exception):
    """Die Zentrale antwortet, aber nicht so, dass weitere Meldungen ankaemen."""

    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class WartelisteUngueltig(Exception):
    pass


def eingerichtet() -> bool:
    # Wie bewerbung_pult.eingerichtet: ein Schluessel, den http.client als Kopf
    # ablehnen wuerde, gilt als nicht eingerichtet - der ValueError truege ihn
    # sonst im Text.
    return bool(URL.startswith(("http://", "https://")) and KEY and KEY.isascii()
                and KEY.isprintable() and not any(z.isspace() for z in KEY))


# ---------------------------------------------------------------------------
# Zentrale
# ---------------------------------------------------------------------------

def _http(methode: str, url: str, kopf: dict, koerper, zeitlimit: float) -> tuple:
    """-> (Status, Rumpf-Bytes). Netz- und Protokollfehler kommen nur als
    NetzFehler heraus, ohne Ausnahmekette."""
    try:
        req = urllib.request.Request(url, data=koerper, method=methode, headers={
            "Content-Type": "application/json", "Accept": "application/json"})
        for name, wert in kopf.items():
            # Der Schluessel folgt keiner Umleitung (wie pult_http).
            req.add_unredirected_header(name, wert)
        try:
            with urllib.request.urlopen(req, timeout=zeitlimit) as antwort:
                return antwort.status, antwort.read()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read()
            except (OSError, http.client.HTTPException):
                return e.code, b""
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as e:
            art = type(e).__name__
    except ValueError:
        # Adresse oder Kopf abgelehnt - der Text truege den Kopfwert. Erst nach
        # dem except-Block werfen, damit keine Kette ihn mitschleppt.
        art = "Anfrage ungueltig"
    raise NetzFehler(art)


HTTP = _http


def _anfrage(methode: str, pfad: str, daten: dict | None = None) -> tuple:
    koerper = (json.dumps(daten, ensure_ascii=False).encode("utf-8")
               if daten is not None else None)
    try:
        status, roh = HTTP(methode, f"{URL}{PRAEFIX}{pfad}",
                           {"X-Eingang-Key": KEY}, koerper, ZEITLIMIT_S)
    except NetzFehler:
        raise
    except Exception as e:           # noqa: BLE001 - Klasse ja, Text nie
        art = type(e).__name__
    else:
        try:
            antwort = json.loads(roh or b"{}")
        except ValueError:
            antwort = None
        return status, antwort if isinstance(antwort, dict) else None
    raise NetzFehler(art)


def _domain(roh: str) -> str:
    d = (roh or "").strip().lower().lstrip("@").rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    if not d.isascii():
        try:
            d = d.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
    return d if "." in d and re.fullmatch(r"[a-z0-9.-]+", d) else ""


def _passt(domain: str, liste) -> bool:
    return bool(domain) and any(domain == d or domain.endswith("." + d) for d in liste)


# Rechtsformen am Ende eines Firmennamens: Portale schreiben oft nur
# „Bewerbung bei Beispiel" statt „Beispiel GmbH".
_RECHTSFORM = re.compile(
    r"[\s,]+(?:gmbh\s*&\s*co\.?\s*kgaa|gmbh\s*&\s*co\.?\s*kg|ag\s*&\s*co\.?\s*kg"
    r"|ggmbh|gmbh|mbh|kgaa|ag|se|kg|ohg|gbr|partg(?:\s*mbb)?"
    r"|ug(?:\s*\(haftungsbeschr(?:ä|ae)nkt\))?|e\.\s?v\.|eg|inc\.?|ltd\.?|llc|plc"
    r"|corp\.?)$", re.I)


def _namensmuster(firma: str) -> tuple:
    """Firmenname als ganzes Wort, Gross/Klein egal - mit und ohne Rechtsform
    (der Kern nur ab drei Zeichen wie „SAP", sonst traefe „AB" zu viel; gesucht
    wird ohnehin nur in Mails von Portal-Domains)."""
    voll = " ".join((firma or "").split())
    formen = [voll] if voll else []
    kern = voll
    while True:
        kuerzer = _RECHTSFORM.sub("", kern).strip(" ,")
        if kuerzer == kern:
            break
        kern = kuerzer
    if kern and kern != voll and len(kern) >= 3:
        formen.append(kern)
    return tuple(
        re.compile(r"(?<!\w)" + r"\s+".join(re.escape(t) for t in f.split()) + r"(?!\w)",
                   re.I)
        for f in formen)


@dataclass(frozen=True)
class Bewerbung:
    application_id: str
    domains: tuple
    an: str
    namen: tuple
    gesendet_am: datetime


@dataclass(frozen=True)
class Warteliste:
    bewerbungen: tuple
    portale: tuple

    @property
    def grenze(self) -> datetime:
        return min(b.gesendet_am for b in self.bewerbungen) - timedelta(days=1)

    def kandidaten(self, adresse, domain, absendername, betreff, text_holen,
                   einladung) -> list:
        treffer = set()
        for b in self.bewerbungen:
            if _passt(domain, b.domains) or (b.an and adresse == b.an):
                treffer.add(b.application_id)
        if _passt(domain, self.portale):
            felder = (absendername, betreff, text_holen())
            for b in self.bewerbungen:
                if any(m.search(f or "") for m in b.namen for f in felder):
                    treffer.add(b.application_id)
        if einladung:
            organisator = _domain(einladung["organisator"].rpartition("@")[2])
            for b in self.bewerbungen:
                if _passt(organisator, b.domains):
                    treffer.add(b.application_id)
        return [b.application_id for b in self.bewerbungen if b.application_id in treffer]


def _zeitpunkt(roh) -> datetime | None:
    if not isinstance(roh, str) or not roh.strip():
        return None
    try:
        wert = datetime.fromisoformat(roh.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)


def _warteliste_holen() -> Warteliste:
    status, antwort = _anfrage("GET", "/warteliste")
    if status != 200:
        raise ZentraleNichtBereit(status)
    if antwort is None or not isinstance(antwort.get("bewerbungen"), list):
        raise WartelisteUngueltig()
    bewerbungen, unbrauchbar = [], 0
    for eintrag in antwort["bewerbungen"]:
        if not isinstance(eintrag, dict):
            unbrauchbar += 1
            continue
        kennung = eintrag.get("application_id")
        gesendet = _zeitpunkt(eintrag.get("gesendet_am"))
        if not isinstance(kennung, str) or not kennung or gesendet is None:
            unbrauchbar += 1
            continue
        domains = tuple(d for d in (_domain(x) for x in eintrag.get("domains") or []
                                    if isinstance(x, str)) if d and d not in FREEMAIL)
        an = eintrag.get("an")
        firma = eintrag.get("firma")
        bewerbungen.append(Bewerbung(
            kennung, domains, an.strip().lower() if isinstance(an, str) else "",
            _namensmuster(firma) if isinstance(firma, str) else (), gesendet))
    portale = tuple(d for d in (_domain(x) for x in antwort.get("portal_absender") or []
                                if isinstance(x, str)) if d and d not in FREEMAIL)
    LOG.info("Warteliste: %d Bewerbungen, %d Portale, %d Eintraege unbrauchbar",
             len(bewerbungen), len(portale), unbrauchbar)
    return Warteliste(tuple(bewerbungen), portale)


# ---------------------------------------------------------------------------
# Mail lesen (Fremddatum)
# ---------------------------------------------------------------------------

def _dekodiert(roh) -> str:
    teile = []
    for wert, zeichensatz in email.header.decode_header(str(roh or "")):
        if isinstance(wert, bytes):
            try:
                teile.append(wert.decode(zeichensatz or "utf-8", errors="replace"))
            except LookupError:
                teile.append(wert.decode("utf-8", errors="replace"))
        else:
            teile.append(wert)
    return " ".join("".join(teile).split())


def _aufgeraeumt(text: str) -> str:
    zeilen = [re.sub(r"[^\S\n]+", " ", z).strip()
              for z in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    ergebnis, leer = [], False
    for z in zeilen:
        if z or not leer:
            ergebnis.append(z)
        leer = not z
    return "\n".join(ergebnis).strip()


def _html_zu_text(roh: str) -> str:
    t = re.sub(r"(?s)<!--.*?-->", " ", roh)
    t = re.sub(r"(?is)<(script|style|head|title)\b.*?</\1\s*>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(?:p|div|tr|li|h[1-6]|table|blockquote)\s*>", "\n", t)
    t = re.sub(r"(?s)<[^>]*>", " ", t)
    return _aufgeraeumt(html.unescape(t))


def _teile(nachricht, passt):
    """(Teil, dekodierter Text) fuer jeden Blatt-Teil, auf den `passt(teil)`
    zutrifft - erst pruefen, dann dekodieren: ein PDF-Anhang wird nie Text."""
    for teil in nachricht.walk():
        if teil.is_multipart() or not passt(teil):
            continue
        roh = teil.get_payload(decode=True)
        if roh is None:
            continue
        try:
            wert = roh.decode(teil.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            wert = roh.decode("utf-8", errors="replace")
        yield teil, wert


def _ist_lesetext(teil) -> bool:
    return (teil.get_content_disposition() != "attachment"
            and teil.get_content_type() in ("text/plain", "text/html"))


def _ist_kalender(teil) -> bool:
    return (teil.get_content_type() in ("text/calendar", "application/ics")
            or (teil.get_filename() or "").lower().endswith(".ics"))


def _klartext(nachricht) -> str:
    """text/plain bevorzugt, sonst HTML ohne Tags; Anhaenge zaehlen nicht."""
    klar = gestaltet = None
    for teil, wert in _teile(nachricht, _ist_lesetext):
        typ = teil.get_content_type()
        if typ == "text/plain" and klar is None and wert.strip():
            klar = wert
        elif typ == "text/html" and gestaltet is None:
            gestaltet = wert
    if klar is not None:
        return _aufgeraeumt(klar)
    return _html_zu_text(gestaltet) if gestaltet else ""


def _utc_text(zeit: datetime | None) -> str | None:
    return zeit.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if zeit else None


def _einladung(nachricht) -> dict | None:
    """Erste Kalendereinladung der Mail (text/calendar oder .ics-Anhang) ->
    {start, ende, organisator} - oder None. Antworten, Absagen und
    Gegenvorschlaege sind keine Einladung."""
    for _, wert in _teile(nachricht, _ist_kalender):
        entfaltet =wert.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
        if "BEGIN:VEVENT" not in entfaltet:
            continue
        methode = ""
        for zeile in entfaltet.split("\n"):
            name, _, inhalt = zeile.partition(":")
            if name.split(";")[0].strip().upper() == "METHOD":
                methode = inhalt.strip().upper()
                break
        if methode in ("REPLY", "COUNTER", "CANCEL", "DECLINECOUNTER", "REFRESH"):
            continue
        # Erst den VEVENT-Block, dann darin lesen - ein VTIMEZONE davor traegt
        # eigene DTSTART-Zeilen (dieselbe Falle wie in kalender.ics_antwort_lesen).
        block = entfaltet.split("BEGIN:VEVENT", 1)[1].split("END:VEVENT", 1)[0]
        organisator = kalender._ics_feld(block, "ORGANIZER")
        if organisator.lower().startswith("mailto:"):
            organisator = organisator[7:]
        return {
            "start": _utc_text(kalender._ics_zeit(kalender._ics_feld(block, "DTSTART"),
                                                  kalender._ics_tzid(block, "DTSTART"))),
            "ende": _utc_text(kalender._ics_zeit(kalender._ics_feld(block, "DTEND"),
                                                 kalender._ics_tzid(block, "DTEND"))),
            "organisator": organisator.strip().lower(),
        }
    return None


_MONATE = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
           "Nov", "Dec")
_INTERNALDATE = re.compile(
    rb'INTERNALDATE "\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) '
    rb'([+-])(\d{2})(\d{2})"')


def _imap_tag(zeit: datetime) -> str:
    # Von Hand statt strftime("%b"): der Monatsname haengt sonst an der Locale.
    return f"{zeit.day:02d}-{_MONATE[zeit.month - 1]}-{zeit.year}"


def _eingang(kopf: bytes) -> datetime | None:
    """INTERNALDATE (Eingang beim Server) aus der FETCH-Antwort."""
    t = _INTERNALDATE.search(kopf or b"")
    if not t:
        return None
    try:
        monat = _MONATE.index(t[2].decode().title()) + 1
        versatz = timedelta(hours=int(t[8]), minutes=int(t[9]))
        zone = timezone(versatz if t[7] == b"+" else -versatz)
        return datetime(int(t[3]), monat, int(t[1]), int(t[4]), int(t[5]), int(t[6]),
                        tzinfo=zone)
    except ValueError:
        return None


def _kopfdatum(nachricht) -> datetime | None:
    try:
        zeit = email.utils.parsedate_to_datetime(postfach._kopf(nachricht, "Date"))
    except (TypeError, ValueError, IndexError):
        return None
    return zeit if zeit.tzinfo else zeit.replace(tzinfo=timezone.utc)


def _auswerten(roh: bytes, kopf: bytes, liste: Warteliste, name: str,
               uidvalidity, uid: int) -> dict | None:
    """Der Meldungsrumpf (Vertrag v1) - oder None, wenn die Mail nicht passt.
    Bei None verlaesst nichts aus dieser Mail die Funktion."""
    nachricht = email.message_from_bytes(roh)
    eingang = _eingang(kopf) or _kopfdatum(nachricht)
    if eingang is not None and eingang < liste.grenze:
        return None
    name_roh, adresse = email.utils.parseaddr(str(nachricht.get("From", "") or ""))
    adresse = adresse.strip().lower()
    absendername = _dekodiert(name_roh)
    betreff = postfach._kopf(nachricht, "Subject")
    text = []

    def text_holen():
        if not text:
            text.append(_klartext(nachricht))
        return text[0]

    einladung = _einladung(nachricht)
    kandidaten = liste.kandidaten(
        adresse, _domain(adresse.rpartition("@")[2]) if "@" in adresse else "",
        absendername, betreff, text_holen, einladung)
    if not kandidaten:
        return None
    kennung = "".join(postfach._kopf(nachricht, "Message-ID").split())
    if not kennung:
        # Ohne Message-ID braucht die Zentrale trotzdem einen stabilen Schluessel.
        kennung = f"<{name}.{uidvalidity}.{uid}@bewerbungs-eingang.sales-claw.invalid>"
    elif not kennung.startswith("<"):
        kennung = f"<{kennung}>"
    return {
        "postfach": name,
        "message_id": kennung,
        "von": postfach._kopf(nachricht, "From"),
        "an": postfach._kopf(nachricht, "To"),
        "betreff": betreff,
        "datum": _utc_text(eingang) or "",
        "text": text_holen()[:TEXT_MAX],
        "kalender": einladung,
        "kandidaten": kandidaten,
    }


# ---------------------------------------------------------------------------
# Ein Postfach
# ---------------------------------------------------------------------------

class _PostfachFehler(Exception):
    pass


def _zahl(antwort):
    try:
        return int((antwort[1] or [None])[0])
    except (TypeError, ValueError, IndexError):
        return None


def _abholen(daten) -> tuple:
    for teil in daten or []:
        if isinstance(teil, tuple) and len(teil) >= 2 and teil[1]:
            return teil[0] or b"", teil[1]
    return b"", None


def _melden(rumpf: dict, zaehler: dict) -> None:
    status, antwort = _anfrage("POST", "/mails", rumpf)
    ergebnis = (antwort or {}).get("status") if status == 200 else None
    if ergebnis in ("angenommen", "bekannt"):
        zaehler[ergebnis] += 1
    elif status == 200 or status in _NUR_DIESE_MAIL:
        zaehler["abgelehnt"] += 1
        LOG.warning("Zentrale lehnt Mail ab (HTTP %s, message_id=%s)",
                    status, rumpf["message_id"])
    else:
        raise ZentraleNichtBereit(status)


def _postfach_abarbeiten(name: str, kennung: str, liste: Warteliste, alt,
                         zaehler: dict, trocken: bool) -> dict:
    """Ein Postfach lesen und Passendes melden -> neuer Cursor. Wirft bei
    IMAP-Problemen (der Aufrufer zaehlt das Postfach dann als Fehler) und
    reicht NetzFehler/ZentraleNichtBereit durch (Abbruch des ganzen Laufs)."""
    kasten = postfach.oeffnen(kennung)
    try:
        status, _ = kasten.select("INBOX", readonly=True)
        if status != "OK":
            raise _PostfachFehler("select")
        uidvalidity = _zahl(kasten.response("UIDVALIDITY"))
        uidnext = _zahl(kasten.response("UIDNEXT"))
        bisher = 0
        if (isinstance(alt, dict) and alt.get("uidvalidity") == uidvalidity
                and isinstance(alt.get("uid"), int)):
            bisher = alt["uid"]
        status, daten = kasten.uid("search", None, "UID", f"{bisher + 1}:*", "SINCE",
                                   _imap_tag(liste.grenze - timedelta(days=1)))
        if status != "OK":
            raise _PostfachFehler("search")
        # "n:*" liefert die hoechste UID auch dann, wenn sie kleiner als n ist
        # (RFC 3501) - darum hier noch einmal filtern.
        uids = sorted({int(u) for u in (daten[0] or b"").split()
                       if u.isdigit() and int(u) > bisher})
        for uid in uids:
            status, daten = kasten.uid("fetch", str(uid), "(UID INTERNALDATE BODY.PEEK[])")
            if status != "OK":
                raise _PostfachFehler("fetch")
            kopf, roh = _abholen(daten)
            if roh is None:
                continue                 # zwischen SEARCH und FETCH verschwunden
            zaehler["geprueft"] += 1
            try:
                rumpf = _auswerten(roh, kopf, liste, name, uidvalidity, uid)
            except Exception as e:   # noqa: BLE001 - Fremddatum, nur die Klasse
                # Eine Mail, an der das Lesen scheitert, darf den Cursor nicht
                # fuer immer festhalten; gemeldet wird von ihr nichts.
                zaehler["unlesbar"] += 1
                LOG.warning("%s: eine Mail nicht auswertbar (%s) - uebersprungen",
                            name, type(e).__name__)
                continue
            if rumpf is None:
                continue
            zaehler["passend"] += 1
            if not trocken:
                _melden(rumpf, zaehler)
        hoechste = max([bisher] + uids + ([uidnext - 1] if uidnext else []))
        return {"uidvalidity": uidvalidity, "uid": hoechste,
                "stand": _utc_text(datetime.now(timezone.utc))}
    finally:
        try:
            kasten.logout()
        except Exception:            # noqa: BLE001 - Abmelden ist kein Befund
            pass


# ---------------------------------------------------------------------------
# Cursor (eigene Datenbank, nicht das Postfach)
# ---------------------------------------------------------------------------

def _cursor_lesen() -> dict:
    import server                    # erst hier: braucht SALES_DB_URL
    zeilen = server._q("select wert from einstellungen where schluessel = %s",
                       (CURSOR_SCHLUESSEL,))
    wert = zeilen[0]["wert"] if zeilen else {}
    return wert if isinstance(wert, dict) else {}


def _cursor_schreiben(daten: dict) -> None:
    import server
    server._q("insert into einstellungen (schluessel, wert, geaendert_von) "
              "values (%s, %s::jsonb, %s) on conflict (schluessel) do update set "
              "wert = excluded.wert, geaendert_am = now(), "
              "geaendert_von = excluded.geaendert_von returning schluessel",
              (CURSOR_SCHLUESSEL, json.dumps(daten), "bewerbungs-eingang"))


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def lauf(trocken: bool = False) -> dict:
    """Ein Lauf -> {"status", "vollstaendig", "postfaecher": {name: Zahlen}}.
    Das Ergebnis enthaelt nur Zahlen und feste Woerter."""
    ergebnis = {"status": "", "vollstaendig": False, "postfaecher": {}}
    if not eingerichtet():
        LOG.info("Bewerbungs-Eingang nicht eingerichtet "
                 "(BEWERBUNG_PULT_URL/BEWERBUNG_EINGANG_KEY fehlt)")
        ergebnis.update(status="nicht eingerichtet", vollstaendig=True)
        return ergebnis
    try:
        liste = _warteliste_holen()
    except NetzFehler as e:
        LOG.error("Zentrale nicht erreichbar (%s) - Lauf beendet", e)
        ergebnis["status"] = "zentrale nicht erreichbar"
        return ergebnis
    except ZentraleNichtBereit as e:
        LOG.error("Zentrale nicht bereit (HTTP %s) - Lauf beendet", e.code)
        ergebnis["status"] = "zentrale nicht bereit"
        return ergebnis
    except WartelisteUngueltig:
        LOG.error("Warteliste ist kein Vertrag-v1-Dokument - Lauf beendet")
        ergebnis["status"] = "warteliste ungueltig"
        return ergebnis
    if not liste.bewerbungen:
        LOG.info("Warteliste leer - nichts zu tun")
        ergebnis.update(status="warteliste leer", vollstaendig=True)
        return ergebnis
    try:
        cursor = _cursor_lesen()
    except Exception as e:           # noqa: BLE001
        LOG.error("Cursor nicht lesbar (%s) - Lauf beendet", type(e).__name__)
        ergebnis["status"] = "cursor nicht lesbar"
        return ergebnis

    vollstaendig, neu = True, {}
    try:
        for name, kennung in POSTFAECHER:
            if kennung not in postfach.kennungen():
                LOG.info("%s: nicht eingerichtet", name)
                ergebnis["postfaecher"][name] = {"status": "nicht eingerichtet"}
                continue
            zaehler = {"status": "ok", "geprueft": 0, "passend": 0, "angenommen": 0,
                       "bekannt": 0, "abgelehnt": 0, "unlesbar": 0}
            ergebnis["postfaecher"][name] = zaehler
            try:
                neu[name] = _postfach_abarbeiten(name, kennung, liste, cursor.get(name),
                                                 zaehler, trocken)
            except (NetzFehler, ZentraleNichtBereit):
                zaehler["status"] = "abgebrochen"
                raise
            except Exception as e:   # noqa: BLE001 - je Postfach, nur die Klasse
                zaehler["status"] = "fehler"
                vollstaendig = False
                LOG.warning("%s: nicht lesbar (%s) - Cursor bleibt", name, type(e).__name__)
                continue
            LOG.info("%s: %d geprueft, %d passend, %d angenommen, %d bekannt, "
                     "%d abgelehnt, %d unlesbar", name, zaehler["geprueft"],
                     zaehler["passend"], zaehler["angenommen"], zaehler["bekannt"],
                     zaehler["abgelehnt"], zaehler["unlesbar"])
    except NetzFehler as e:
        LOG.error("Zentrale nicht erreichbar (%s) - Lauf beendet, Cursor bleibt", e)
        ergebnis["status"] = "zentrale nicht erreichbar"
        return ergebnis
    except ZentraleNichtBereit as e:
        LOG.error("Zentrale nicht bereit (HTTP %s) - Lauf beendet, Cursor bleibt",
                  e.code)
        ergebnis["status"] = "zentrale nicht bereit"
        return ergebnis

    if neu and not trocken:
        try:
            _cursor_schreiben({**cursor, **neu})
        except Exception as e:       # noqa: BLE001
            LOG.error("Cursor nicht gespeichert (%s) - naechster Lauf meldet erneut",
                      type(e).__name__)
            vollstaendig = False
    ergebnis.update(status="ok" if vollstaendig else "unvollstaendig",
                    vollstaendig=vollstaendig)
    return ergebnis


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout (wie telegram_dispatch): `import server`
    zieht ueber das mcp-Paket eine Root-Konfiguration hoch, ein
    `logging.basicConfig()` waere dann ein stiller No-op."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main(argv) -> int:
    _logging_einrichten()
    if argv not in (["lauf"], ["lauf", "--trocken"]):
        sys.stderr.write("Aufruf: python bewerbungs_eingang.py lauf [--trocken]\n")
        return 2
    try:
        ergebnis = lauf(trocken=len(argv) == 2)
    except Exception as e:           # noqa: BLE001 - nie der Text, nur Ort und Klasse
        ort = traceback.extract_tb(e.__traceback__)[-1]
        LOG.error("Lauf abgebrochen (%s in %s:%s)", type(e).__name__,
                  os.path.basename(ort.filename), ort.lineno)
        return 1
    sys.stdout.write(json.dumps(ergebnis, ensure_ascii=False) + "\n")
    return 0 if ergebnis["vollstaendig"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
