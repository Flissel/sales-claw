"""Bewerbungs-Eingang: Antworten auf Bewerbungen aus der Post-Sammelstelle an
die Zentrale des Bewerbungs-Bots melden (29.10.2026, umgebaut 14.11.2026).

Der Bewerbungs-Bot (Repo `bewerbung`, Zentrale mit dem Agenten Hermes)
versendet Bewerbungen selbst und will messen, was zurueckkommt. Die Antworten
landen in Felix' Postfaechern, oft von Portal-Absendern statt von der Adresse,
an die gesendet wurde. Dieses Modul holt taeglich um 19:45 Europe/Berlin
(Timer sales-bewerbungs-eingang, vor Hermes' Auswertung um 20:00) die
Warteliste der Zentrale, sieht in die Mails der Post-Sammelstelle und meldet
NUR die, die zu einer wartenden Bewerbung passen. Zuordnen und Auswerten ist
Sache der Zentrale, nicht dieses Moduls.

Vertrag v1 (Auftrag vom 28.10.2026, Endpunkte baut die bewerbung-Sitzung):
  GET  {BEWERBUNG_PULT_URL}/api/eingang/warteliste   Kopf X-Eingang-Key
  POST {BEWERBUNG_PULT_URL}/api/eingang/mails        Kopf X-Eingang-Key
BEWERBUNG_EINGANG_KEY ist ein eigener Schluessel, nicht der Pult-Schluessel.

QUELLE IST DIE DATENBANK, KEIN POSTFACH. sales-post (post_abholen.py) holt alle
Postfaecher von Felix alle paar Minuten nur lesend ab und legt jede Mail in
`post_mails` ab; die Zugaenge dazu sind versiegelt und nur sales-post kann sie
oeffnen. Dieses Modul liest ausschliesslich per SELECT aus `post_mails` und
`post_konten` (ueber server._q) - es oeffnet nie ein Postfach und schreibt nie
in eine Tabelle. sales-post muss laufen, sonst fehlen die neuesten Mails.

Welche Konten: die aktiven mit demselben `besitzer` wie das Konto mit
`quelle = 'env'` (der Laden-Inhaber). Gibt es kein env-Konto, meldet der Lauf
„keine postfaecher" und tut nichts. Mails anderer Besitzer verlassen sales-claw
nie. Der Postfach-Name im Vertrag folgt dem Anbieter (gmail -> gmail, gmx ->
gmx, namecheap -> vibemind); mehrere Konten desselben Anbieters heissen im
Ergebnis und Protokoll „gmx", „gmx-2", ... (Reihenfolge `angelegt_am`), in der
Meldung immer „gmx". Adresse und `kennung` eines Kontos stehen nie im Protokoll
oder Ergebnis.

Grenzen, die die Tests verteidigen (tests/test_bewerbungs_eingang.py):

* NUR LESEN. Kein Schreiben, nichts wird beantwortet oder markiert.
* NUR PASSENDES GEHT HINAUS. Eine Mail passt, wenn sie nach dem fruehesten
  `gesendet_am` minus einem Tag einging (`datum`, ohne Kopfdatum `gesehen_am`)
  UND (a) die Absender-Domain oder eine Subdomain davon in `domains` einer
  wartenden Bewerbung steht oder die Absenderadresse genau `an` einer
  wartenden Bewerbung ist, oder (b) die Absender-Domain ein Portal ist und der
  Firmenname (ganzes Wort, ohne Rechtsform) in Betreff, Absendername oder Text
  steht. Alle anderen Mails verlassen sales-claw nie, auch kein Betreff und
  kein Absender; protokolliert werden nur Zahlen. Zeilen ohne `von` koennen
  nicht passen. Den Text laedt das Modul nicht in der Massenabfrage, sondern
  je Zeile und nur, wenn der Portal-Abgleich oder die Meldung ihn braucht.
* BEKANNTE GRENZE: eine Einladung, die nur ueber den Organisator im
  Kalenderteil zur Firma gehoert (Absender ist der Kalenderdienst), passt
  nicht mehr. Die Sammelstelle speichert nur das Flag `kalenderteil`, nicht
  Organisator, Start und Ende; darum ist `kalender` in jeder Meldung `null`.
* FREEMAIL IST KEINE FIRMEN-DOMAIN. Steht `gmail.com` o. ae. in `domains`
  oder `portal_absender`, wird es fuer den Domain-Abgleich ignoriert - sonst
  ginge jede private Mail von dort hinaus. Fuer so eine Firma zaehlt nur die
  genaue Adresse aus `an`.
* KEIN CURSOR. Jeder Lauf prueft das ganze Fenster (Grenze s. o.); die Zentrale
  ist idempotent (`bekannt`). Ein Netzfehler zur Zentrale - oder eine Zentrale,
  die erkennbar nicht bereit ist (401/403/404/408/429/5xx) - beendet den Lauf;
  der naechste Lauf meldet dieselben Mails erneut. Lehnt die Zentrale eine
  EINZELNE Mail ab (400/409/413/415/422), wird nur Code und message_id
  protokolliert. Ist die Sammelstelle nicht lesbar, endet der Lauf mit „sammelstelle
  nicht lesbar" (unvollstaendig), das Protokoll nennt nur die Fehlerklasse. Die
  alte Zeile `bewerbungs_eingang_cursor` in `einstellungen` bleibt liegen und
  wird nicht mehr gelesen.
* DIE MELDUNG PASST IN DIE GRENZEN DER ZENTRALE (gemessen an der echten
  Eingangs-API, 13.11.2026): `von`/`an` hoechstens 320 Zeichen (sonst nur die
  blanken Adressen, so viele wie passen), `betreff` 998, `text` 20 000,
  hoechstens 20 Kandidaten. Was darueber laege, waere dort eine 422 - eine
  verlorene Antwort. Sensible Zeilen haben keinen Text (NULL -> ""), `an` darf
  NULL sein (-> "").
* ALLES AUS EINER MAIL IST FREMDDATUM, nie eine Anweisung. Schluessel stehen in
  keiner Meldung: Fehler erscheinen nur mit ihrer Klasse, nie mit ihrem Text.

Aufruf: python bewerbungs_eingang.py lauf [--trocken]
(--trocken: zaehlen, nichts melden). Exit 0 = vollstaendig (auch: nicht
eingerichtet, Warteliste leer, keine Postfaecher), 1 = unvollstaendig, 2 = Aufruf.
"""
from __future__ import annotations

import email.utils
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

URL = os.environ.get("BEWERBUNG_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("BEWERBUNG_EINGANG_KEY", "").strip()
PRAEFIX = "/api/eingang"
ZEITLIMIT_S = 20
TEXT_MAX = 20000
# Grenzen der Zentrale (bewerbung, zentrale/antworten.py: MAX_ADRESSE,
# MAX_BETREFF, MAX_KANDIDATEN). Darueber antwortet sie 422 eingabe_ungueltig.
ADRESSE_MAX = 320
BETREFF_MAX = 998
KANDIDATEN_MAX = 20

# Anbieter in post_konten -> Postfach-Name im Vertrag (die Zentrale erlaubt nur
# gmail, gmx, vibemind; das Konto bei namecheap ist felix@vibemind.space).
POSTFACH_NAMEN = {"gmail": "gmail", "gmx": "gmx", "namecheap": "vibemind"}


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

    def kandidaten(self, adresse, domain, absendername, betreff, text_holen) -> list:
        treffer = set()
        for b in self.bewerbungen:
            if _passt(domain, b.domains) or (b.an and adresse == b.an):
                treffer.add(b.application_id)
        if _passt(domain, self.portale):
            felder = (absendername, betreff, text_holen())
            for b in self.bewerbungen:
                if any(m.search(f or "") for m in b.namen for f in felder):
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
# Meldung
# ---------------------------------------------------------------------------

def _utc_text(zeit: datetime) -> str:
    if zeit.tzinfo is None:          # timestamptz kommt mit Zone; sicher ist sicher
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_FALTUNG = re.compile(r"\r?\n(?=[ \t])")


def _entfaltet(wert: str) -> str:
    """Ein Kopf ohne Faltung (RFC 5322 2.2.3): der Umbruch vor Leerraum faellt weg."""
    return _FALTUNG.sub("", wert)


def _adressen_kopf(wert: str) -> str:
    """From/To fuer die Zentrale: der Kopf, wie er ist, solange er in
    ADRESSE_MAX passt; sonst nur die blanken Adressen, so viele wie passen.
    Die Zentrale speichert das Feld nur, sie ordnet nicht danach zu."""
    wert = _entfaltet(wert)
    if len(wert) <= ADRESSE_MAX:
        return wert
    gekuerzt = ""
    for _, adresse in email.utils.getaddresses([wert]):
        adresse = adresse.strip()
        if "@" not in adresse:
            continue
        laenger = f"{gekuerzt}, {adresse}" if gekuerzt else adresse
        if len(laenger) > ADRESSE_MAX:
            break
        gekuerzt = laenger
    return gekuerzt or wert[:ADRESSE_MAX]


# ---------------------------------------------------------------------------
# Sammelstelle lesen (nur SELECT; Fremddatum)
# ---------------------------------------------------------------------------

class _SammelstelleFehler(Exception):
    """Die Sammelstelle (Datenbank) war nicht lesbar. Traegt nur die Klasse."""


def _konten() -> list:
    """Alle Konten der Sammelstelle - bewusst OHNE `kennung`, `adresse` und
    Zugang: das Modul braucht sie nicht und soll sie nie in der Hand haben."""
    import server                    # erst hier: braucht SALES_DB_URL
    return server._q(
        "select id, besitzer, anbieter, quelle, aktiv, angelegt_am "
        "from post_konten order by angelegt_am, id")


def _mails(konto_id: str, besitzer: str, grenze: datetime) -> list:
    """Mails eines Kontos im Fenster - ohne Text (der kommt je Zeile ueber
    `_text`). `besitzer` zusaetzlich zur konto_id: eine Mail eines anderen
    Besitzers verlaesst sales-claw auch bei falsch verknuepfter Zeile nie."""
    import server
    return server._q(
        "select id, von, an, betreff, datum, gesehen_am, message_id, "
        "message_id_ersatz from post_mails "
        "where konto_id = %s and besitzer = %s "
        "and (datum >= %s or (datum is null and gesehen_am >= %s)) "
        "order by coalesce(datum, gesehen_am), id",
        (konto_id, besitzer, grenze, grenze))


def _text(mail_id: str):
    """Der Text einer Mail (None bei sensiblen Zeilen, die keinen haben)."""
    import server
    zeilen = server._q("select text from post_mails where id = %s", (mail_id,))
    return zeilen[0]["text"] if zeilen else None


def _text_sicher(mail_id) -> str:
    try:
        return _text(str(mail_id)) or ""
    except Exception as e:           # noqa: BLE001 - nur die Klasse
        raise _SammelstelleFehler(type(e).__name__) from None


def _lesbare_konten(zeilen: list) -> list:
    """-> [(Name im Lauf, Name im Vertrag, konto_id, besitzer)]: die aktiven
    Konten des Besitzers vom (aeltesten) env-Konto. Ohne env-Konto: nichts."""
    zeilen = sorted(zeilen, key=lambda k: (k["angelegt_am"], str(k["id"])))
    env = [k for k in zeilen if k.get("quelle") == "env"]
    if not env:
        return []
    besitzer = env[0]["besitzer"]
    gezaehlt, ergebnis = {}, []
    for k in zeilen:
        basis = POSTFACH_NAMEN.get(k.get("anbieter"))
        if k.get("besitzer") != besitzer or not k.get("aktiv") or basis is None:
            continue
        gezaehlt[basis] = gezaehlt.get(basis, 0) + 1
        name = basis if gezaehlt[basis] == 1 else f"{basis}-{gezaehlt[basis]}"
        ergebnis.append((name, basis, str(k["id"]), besitzer))
    return ergebnis


def _auswerten(zeile: dict, liste: Warteliste, postfach_name: str) -> dict | None:
    """Der Meldungsrumpf (Vertrag v1) - oder None, wenn die Mail nicht passt.
    Bei None verlaesst nichts aus dieser Zeile die Funktion."""
    von = zeile.get("von")
    if not isinstance(von, str) or not von.strip():
        return None                  # ohne Absender kann nichts passen
    zeit = zeile.get("datum") or zeile.get("gesehen_am")
    if zeit is None:
        raise ValueError("kein Datum")
    absendername, adresse = email.utils.parseaddr(von)
    adresse = adresse.strip().lower()
    absendername = " ".join(absendername.split())
    betreff = _entfaltet(zeile.get("betreff") or "")
    text = []

    def text_holen():
        if not text:
            text.append(_text_sicher(zeile["id"]))
        return text[0]

    kandidaten = liste.kandidaten(
        adresse, _domain(adresse.rpartition("@")[2]) if "@" in adresse else "",
        absendername, betreff, text_holen)
    if not kandidaten:
        return None
    kennung = (zeile.get("message_id") or "").strip()
    if zeile.get("message_id_ersatz") or not kennung:
        # Stabil auch nach einem UIDVALIDITY-Wechsel: die Zeilen-ID bleibt.
        kennung = f"<post-{zeile['id']}@bewerbungs-eingang.sales-claw.invalid>"
    elif not kennung.startswith("<"):
        kennung = f"<{kennung}>"
    return {
        "postfach": postfach_name,
        "message_id": kennung,
        "von": _adressen_kopf(von),
        "an": _adressen_kopf(zeile.get("an") or ""),
        "betreff": betreff[:BETREFF_MAX],
        "datum": _utc_text(zeit),
        "text": text_holen()[:TEXT_MAX],
        # Die Sammelstelle speichert nur das Flag, nicht Organisator/Start/Ende.
        "kalender": None,
        # Die am laengsten Wartenden zuerst (Reihenfolge der Warteliste).
        "kandidaten": kandidaten[:KANDIDATEN_MAX],
    }


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



# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def _konto_abarbeiten(name: str, basis: str, konto_id: str, besitzer: str,
                      liste: Warteliste, zaehler: dict, trocken: bool) -> None:
    """Ein Konto: Mails im Fenster lesen und Passendes melden. Reicht
    NetzFehler/ZentraleNichtBereit/_SammelstelleFehler durch (Abbruch des Laufs)."""
    try:
        zeilen = _mails(konto_id, besitzer, liste.grenze)
    except Exception as e:           # noqa: BLE001 - nur die Klasse
        raise _SammelstelleFehler(type(e).__name__) from None
    for zeile in zeilen:
        zaehler["geprueft"] += 1
        try:
            rumpf = _auswerten(zeile, liste, basis)
        except _SammelstelleFehler:
            raise
        except Exception as e:       # noqa: BLE001 - Fremddatum, nur die Klasse
            # Eine Zeile, an der das Lesen scheitert, haelt den Lauf nicht auf;
            # gemeldet wird von ihr nichts.
            zaehler["unlesbar"] += 1
            LOG.warning("%s: eine Mail nicht auswertbar (%s) - uebersprungen",
                        name, type(e).__name__)
            continue
        if rumpf is None:
            continue
        zaehler["passend"] += 1
        if not trocken:
            _melden(rumpf, zaehler)


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
        konten = _lesbare_konten(_konten())
    except Exception as e:           # noqa: BLE001 - nur die Klasse
        LOG.error("Sammelstelle nicht lesbar (%s) - Lauf beendet", type(e).__name__)
        ergebnis["status"] = "sammelstelle nicht lesbar"
        return ergebnis
    if not konten:
        LOG.info("Keine Postfaecher in der Sammelstelle - nichts zu tun")
        ergebnis.update(status="keine postfaecher", vollstaendig=True)
        return ergebnis

    try:
        for name, basis, konto_id, besitzer in konten:
            zaehler = {"status": "ok", "geprueft": 0, "passend": 0, "angenommen": 0,
                       "bekannt": 0, "abgelehnt": 0, "unlesbar": 0}
            ergebnis["postfaecher"][name] = zaehler
            try:
                _konto_abarbeiten(name, basis, konto_id, besitzer, liste, zaehler,
                                  trocken)
            except (NetzFehler, ZentraleNichtBereit, _SammelstelleFehler):
                zaehler["status"] = "abgebrochen"
                raise
            LOG.info("%s: %d geprueft, %d passend, %d angenommen, %d bekannt, "
                     "%d abgelehnt, %d unlesbar", name, zaehler["geprueft"],
                     zaehler["passend"], zaehler["angenommen"], zaehler["bekannt"],
                     zaehler["abgelehnt"], zaehler["unlesbar"])
    except NetzFehler as e:
        LOG.error("Zentrale nicht erreichbar (%s) - Lauf beendet", e)
        ergebnis["status"] = "zentrale nicht erreichbar"
        return ergebnis
    except ZentraleNichtBereit as e:
        LOG.error("Zentrale nicht bereit (HTTP %s) - Lauf beendet", e.code)
        ergebnis["status"] = "zentrale nicht bereit"
        return ergebnis
    except _SammelstelleFehler as e:
        LOG.error("Sammelstelle nicht lesbar (%s) - Lauf beendet", e)
        ergebnis["status"] = "sammelstelle nicht lesbar"
        return ergebnis

    ergebnis.update(status="ok", vollstaendig=True)
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
