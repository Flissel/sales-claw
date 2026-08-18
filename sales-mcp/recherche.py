"""Recherche — Markt- und Firmendaten aus Google Maps ueber Apify.

Eigenes Modul, gleiche Begruendung wie bei `nummern.py` und `medien.py`:
`server.py` ist gross genug, und was hier steht, ist eine in sich geschlossene
Aussenanbindung — HTTP zu einem fremden Dienst, Normalisierung seiner Antwort,
ein Markdown-Report. Dieses Modul importiert `server.py` NICHT (das waere ein
Zirkelimport, server importiert recherche); es kennt weder Datenbank noch
Werkzeugschicht. Die beiden Werkzeuge `marktanalyse` und `b2b_leads` stehen
in `server.py` und benutzen von hier nur Funktionen.

GEMESSEN (Apify-REST mit dem Token aus der Umgebung, nichts geraten)
--------------------------------------------------------------------
Actor `compass~crawler-google-places` (GET /v2/acts/compass~crawler-google-places
-> HTTP 200): id nwua9Gu5YrADL7ZDj, "Google Maps Scraper", oeffentlich, nicht
deprecated, 3,35 Mio. Laeufe in 30 Tagen (94 % SUCCEEDED). Reserve-Actor, falls
er je verschwindet: `lukaskrivka~google-maps-with-contact-details` — gleiche
Datenfamilie, teurer.

**Preismodell PAY_PER_EVENT** (pricingInfos, Tarifstufe FREE):

    place-scraped            $0.004    je gelieferten Treffer  (Primaerereignis)
    apify-actor-start        $0.00005  je Lauf
    filter-applied           $0.001    je Treffer JE gesetztem Filter
    place-details-scraped    $0.002    je Treffer (Detailseite)
    contact-details-scraped  $0.002    je Treffer (Kontaktanreicherung)
    lead-scraped             $0.1      je Treffer (Personen-Anreicherung)

Daraus folgen zwei Entscheidungen, die im Code sichtbar sind:

1. **Keine Actor-seitigen Filter.** `skipClosedPlaces`, `placeMinimumStars`,
   `website`, `categoryFilterWords` und `searchMatching` kosten je $0.001 pro
   Treffer — ein Aufschlag von 25 % auf den Grundpreis, fuer eine Auswahl, die
   wir umsonst selbst treffen koennen: `permanentlyClosed`/`temporarilyClosed`
   stehen ohnehin in jedem Datensatz. Bei $5 Monatsguthaben ist das kein
   Detail.
2. **Keine Anreicherung.** `scrapeContacts`, `scrapePlaceDetailPage` und
   erst recht `lead-scraped` (Personen!) bleiben aus — teuer, und der
   Grundsatz des Plans lautet: nur Firmendaten aus oeffentlichen Quellen,
   kein Personen-Scraping.

Kosten eines Laufs also: `$0.00005 + n * $0.004` — 20 Treffer ≈ $0.08,
50 Treffer (das Maximum hier) ≈ $0.20. Konto: Plan FREE, $5 Monatsguthaben.

**Input-Schema** (aus dem latest-Build gelesen, 39 Properties, required: []):
`searchStringsArray` (array), `locationQuery` (string, "Stadt, Land" ist die
empfohlene Form), `maxCrawledPlacesPerSearch` (integer), `language` (Default
"en" — wir setzen "de", sonst kaemen englische Kategorienamen).

**Dataset-Schema** (actorDefinition.storages.datasets.default.fields, 97
Felder). Verwendet werden `title`, `address`/`street`/`city`/`postalCode`,
`phone`, `phoneUnformatted`, `website`, `categoryName`, `categories`,
`totalScore`, `reviewsCount`, `permanentlyClosed`, `temporarilyClosed`, `url`.

WARUM `phoneUnformatted` UND NICHT `phone`
------------------------------------------
`phone` ist die Anzeigeform, und ihre Schreibweise haengt am Land: das
Dataset-Schema nennt als Beispiel "(407) 896-9355" (US, national), in der
Live-Abnahme kamen deutsche Nummern als "+49 941 7844646" (international)
zurueck. Auf eine Schreibweise, die sich je Treffer aendern kann, wird hier
nichts gebaut — `phoneUnformatted` traegt laut Schema immer die
Landesvorwahl und keine Trenner ("+14078969355"). Genau das braucht
`nummern.py`: eine national notierte Nummer weist es zurueck
(FEHLER_NATIONALE_SCHREIBWEISE), und zwar zu Recht — aus `0664…` wuerde sonst
die Nummer eines unbeteiligten deutschen Anschlusses. Ein Recherche-Lead
bekommt deshalb `phoneUnformatted` in `leads.phone` — dieselbe Nummer, die
spaeter die Dedup-Kante in `kontakt_anlegen` sieht. Die Anzeigeform wandert
nur in den Report, wo ein Mensch sie liest.

FIRMEN-ANREICHERUNG (Stufe 6): GEMESSEN, DANN GEGEN APIFY ENTSCHIEDEN
---------------------------------------------------------------------
`firma_daten` unten holt die Website eines bestehenden Firmenkontakts
SELBST per urllib — ohne Apify, ohne Token, ohne Kosten. Das ist eine
Entscheidung nach Messung, keine Bequemlichkeit.

Gemessen wurden beide vom Auftrag genannten Actors (GET /v2/acts/<id>,
je HTTP 200):

    apify~website-content-crawler  id aYG0l9s7dbB7j3gbS, oeffentlich,
        nicht deprecated, 2,42 Mio. Laeufe/30 T. **pricingInfos: FEHLT**
        defaultRunOptions: memoryMbytes 8192, timeoutSecs 360000 (100 h)
        Defaults im Input-Schema: maxCrawlPages 9999999, maxCrawlDepth 20,
        maxResults 9999999, crawlerType "playwright:adaptive" (Browser!)
        required: startUrls, proxyConfiguration

    apify~cheerio-scraper          id YrQuEkowkNCLdk4j2, oeffentlich,
        nicht deprecated. **pricingInfos: FEHLT**
        defaultRunOptions: memoryMbytes 1024, timeoutSecs 3600
        required: startUrls, **pageFunction**, proxyConfiguration

Das fehlende `pricingInfos` ist der ganze Befund. `compass~crawler-google-places`
(oben) TRAEGT es und ist PAY_PER_EVENT — nur deshalb greift dort der
Query-Parameter `maxTotalChargeUsd`, ein serverseitig erzwungener
Dollar-Deckel. Beide Kandidaten hier haben kein Ereignis-Preismodell; sie
werden ueber Plattformverbrauch abgerechnet. Der Tarif des Kontos, ebenfalls
gemessen (GET /v2/users/me -> plan.planPricing.chargeableServiceUnitPricesUsd):

    ACTOR_COMPUTE_UNITS  $0.2 je CU (1 CU = 1 GB-Stunde), Plan FREE,
    $5 Monatsguthaben, Stand des Zyklus 2026-08-18..2026-09-17: $0.061.

Fuer ein CU-Modell gibt es KEINEN Dollar-Deckel — `maxTotalChargeUsd` ist ein
Parameter des Ereignismodells und bliebe hier wirkungslos. Die einzige
Obergrenze waere das Produkt `memory x timeout`, also zwei Query-Parameter,
die beide richtig gesetzt sein muessen: bei den Vorgabewerten des
Website-Content-Crawlers waeren das 8 GB x 100 h = 800 CU = $160 je Lauf —
das 32-fache des Monatsguthabens aus einem einzigen vergessenen Parameter.
Ein Deckel, den der Aufrufer selbst zusammenrechnen muss, ist genau die
Sorte Kostenkontrolle, die dieses Modul an anderer Stelle (siehe
`_lauf_deckel`) ausdruecklich nicht akzeptiert.

Dagegen die Messung des Direkt-Wegs, gegen die vier echten Lead-Websites aus
der bestehenden Recherche (schlichter GET, User-Agent gesetzt, 20 s Timeout):

    pfeifer-haustechnik.de        HTTP 200, 1,41 s,  26 KB, Impressum-Link da
    koller-ht.de                  HTTP 200, 1,27 s,  81 KB, Impressum-Link da
    klimaservice-regensburg.de    HTTP 200, 0,37 s, 426 KB, Impressum-Link da
    markuskuehner.de              HTTP 200, 0,38 s,  71 KB, Impressum-Link da

Vier von vier lieferten statisches HTML mit lesbarem Text (1 937 bis 8 855
Zeichen) und einem Impressum-Link auf der Startseite. Kein Browser noetig,
kein Proxy, keine Wartezeit auf einen Actor-Start — und $0.00 je Lauf.
Das ist der Kern der Entscheidung: ein deutsches Impressum ist gesetzlich
vorgeschrieben (§ 5 DDG) und steht bei Handwerksbetrieben dieser Groesse als
statisches HTML im Netz. Dafuer einen Browser-Actor ohne Dollar-Deckel gegen
ein $5-Guthaben laufen zu lassen, waere Aufwand ohne Gegenwert.

Preis der Entscheidung, ehrlich benannt: rein per JavaScript aufgebaute
Seiten liefern hier keinen Text, und wer uns aussperrt (Bot-Schutz), bleibt
ausgesperrt. Beides wird gemeldet, nicht umgangen — umgangen wuerde es auch
mit Apify nur gegen Geld.

DASS SIE NIE ANGESCHRIEBEN WERDEN, IST EINE REGEL, KEIN ZUFALL
--------------------------------------------------------------
Recherche-Leads entstehen mit `consent_status='unknown'` und
`source='recherche'`. Werbliche Kaltansprache per WhatsApp waere ohne
Einwilligung ein UWG-Verstoss (§ 7 Abs. 2 UWG); der Erstkontakt gehoert in
Menschenhand (Telefon/Brief/LinkedIn). Technisch kann hier nichts von selbst
rausgehen — versendet wird ausschliesslich aus `drafts(status='approved')`
durch den Dispatcher —, die Regel steht zusaetzlich in AGENTS.md
("Recherche").
"""
import http.client
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from html.parser import HTMLParser

# Modulattribute statt Konstanten im Code: die Testsuite biegt `APIFY_BASIS`
# auf einen lokalen HTTP-Stub und `REPORT_VERZEICHNIS` auf ein tmp-Verzeichnis
# um — genauso, wie test_dispatch.py es mit `dispatch.OPENWA_URL` macht. Es
# geht in Tests zu keinem Zeitpunkt eine echte (kostenpflichtige) Anfrage an
# Apify raus.
APIFY_BASIS = os.environ.get("APIFY_BASIS", "https://api.apify.com/v2")
ACTOR = os.environ.get("APIFY_ACTOR", "compass~crawler-google-places")

# Zwei Uhren, und ihre Reihenfolge ist der ganze Punkt.
#
# LAUF_TIMEOUT_S ist der Deckel FUER DEN ACTOR (Query-Parameter `timeout`).
# Ohne ihn gilt `defaultRunOptions.timeoutSecs` = 604800 — sieben Tage.
# HTTP_TIMEOUT_S ist, wie lange wir zuhoeren.
#
# Der Actor-Deckel liegt bewusst UNTER dem HTTP-Timeout: so hoeren wir immer
# das Ende des Laufs, statt ihn abzubrechen, waehrend er bei Apify
# weiterlaeuft und weiter Guthaben verbraucht. Der teure Fehler waere „bezahlt,
# aber nichts bekommen"; er ist mit dieser Reihenfolge ausgeschlossen.
#
# Gemessen (Live-Abnahme): 10 Treffer in 15,5 s, also rund 5 s Actor-Start plus
# gut 1 s je Treffer — die 50 erlaubten Treffer landen bei etwa 80 s. Der Plan
# sah 120 s HTTP-Timeout vor; 150/180 lassen dieser Schaetzung Luft nach oben,
# ohne Apifys eigene Grenze fuer den sync-Endpunkt (300 s) zu beruehren.
HTTP_TIMEOUT_S = float(os.environ.get("APIFY_TIMEOUT_S", "180"))


def _lauf_deckel(lauf: int, http: float) -> int:
    """Erzwingt die Reihenfolge LAUF < HTTP (mindestens 30 s Abstand).

    Die Reihenfolge oben ist keine Bitte: wer per Umgebung LAUF ueber HTTP
    stellt, stellt genau den teuren Fehler her, den dieses Modul ausschliessen
    will — Review-Befund B2, deshalb erzwungen statt nur kommentiert.
    Untergrenze 1 s: ein Deckel von 0 hiesse fuer Apify "kein Deckel".
    """
    return max(1, min(lauf, int(http) - 30))


LAUF_TIMEOUT_S = _lauf_deckel(
    int(os.environ.get("APIFY_LAUF_TIMEOUT_S", "150")), HTTP_TIMEOUT_S)

# Harte Budgetgrenze je Lauf (Query-Parameter `maxTotalChargeUsd`). Apify
# erlaubt fuer diesen Actor keinen kleineren Wert als 0.5
# (`minimalMaxTotalChargeUsd`), unser teuerster erlaubter Lauf kostet 0.20 —
# der Deckel greift also nie im Normalbetrieb. Er ist der Fangnetz gegen einen
# Actor, der sich anders verhaelt als gemessen (z. B. mehr Treffer liefert als
# bestellt): dann bricht Apify ab, statt das Monatsguthaben zu leeren.
MAX_TOTAL_CHARGE_USD = 0.5

# Preise fuer die Kostenzeile im Report (Tarifstufe FREE, oben gemessen).
PREIS_START_USD = 0.00005
PREIS_JE_TREFFER_USD = 0.004

LIMIT_VORGABE = 20
LIMIT_MAX = 50
SPRACHE = "de"

# Beschreibbarer Bind `./reports:/reports` an sales-mcp (docker-compose.yml).
REPORT_VERZEICHNIS = os.environ.get("REPORT_DIR", "/reports")

# Sammel-Lead „RECHERCHE (Sammelkontakt)" — dort haengen die
# `activities`-Zeilen vom Typ `recherche`. Gleiches Muster wie
# INBOX_UNBEKANNT_LEAD_ID (inbox.py): ein fester Kontakt statt einer
# Protokollzeile ohne Ort. Fehlt er, laeuft die Recherche trotzdem (siehe
# server.py `_recherche_loggen`) — ein bezahlter Apify-Lauf darf nicht an
# einer fehlenden Konfigurationszeile verloren gehen.
RECHERCHE_LEAD_ID = os.environ.get("RECHERCHE_LEAD_ID", "")

FEHLER_KEIN_TOKEN = (
    "Kein APIFY_TOKEN konfiguriert — ohne ihn ist keine Recherche moeglich. "
    "Der Token gehoert in die .env des Projekts (Variable APIFY_TOKEN); "
    "danach muss sales-mcp neu erzeugt werden. Es wurde nichts abgefragt.")


def token() -> str:
    """Zur Aufrufzeit gelesen, nicht beim Import — sonst koennte die Suite den
    fehlenden Token nicht pruefen und ein spaeter nachgetragener Wert wuerde
    erst nach einem Neustart wirken."""
    return os.environ.get("APIFY_TOKEN", "").strip()


def _ohne_token(text: str) -> str:
    """Der Token darf in keinem Fehlertext landen — der geht in die Antwort
    des Werkzeugs, von dort in den Chat und ins Log. Fremde Fehlerrumpfe
    spiegeln Anfragen manchmal zurueck (Proxys, Gateways); die Zeile kostet
    nichts und schliesst die Klasse Vorfall aus."""
    tok = token()
    return text.replace(tok, "***") if tok else text


def kappe_limit(limit) -> int:
    """Wunsch -> erlaubte Trefferzahl. Kappung, kein Fehler.

    Ein zu grosses `limit` ist kein Bedienfehler, sondern eine Schaetzung —
    der Aufruf soll laufen, nur eben nicht das Monatsguthaben verbrauchen.
    Unlesbares (None, "viele") faellt auf die Vorgabe zurueck.
    """
    try:
        wert = int(limit)
    except (TypeError, ValueError):
        return LIMIT_VORGABE
    return max(1, min(wert, LIMIT_MAX))


_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
            "Ä": "ae", "Ö": "oe", "Ü": "ue"}
_NICHT_SLUG = re.compile(r"[^a-z0-9]+")


def slug(*teile) -> str:
    """Freitext -> Dateinamens-Kern, ausschliesslich [a-z0-9-].

    Whitelist statt Blacklist: alles, was nicht Kleinbuchstabe oder Ziffer
    ist, wird zum Trenner. Ein Traversal-Versuch (`../../etc/passwd`,
    `..\\windows\\system.ini`, `C:datei`) kann diese Funktion also nicht
    ueberleben — Punkt, Schraegstrich, Backslash und Doppelpunkt gibt es im
    Ergebnis nicht. Das ist die erste von zwei Sicherungen; die zweite steht
    in `report_schreiben` (Einbettungspruefung gegen den Reportordner),
    dasselbe zweistufige Muster wie in `medien.py`.
    """
    roh = "-".join(str(t or "") for t in teile).lower()
    for a, b in _UMLAUTE.items():
        roh = roh.replace(a.lower(), b)
    kern = _NICHT_SLUG.sub("-", roh).strip("-")[:60].strip("-")
    return kern or "recherche"


def report_name(thema: str, region: str, tag=None) -> str:
    """`<slug>-<datum>.md` — vorhersagbar, damit der Betreiber den Report auch
    ohne Rueckfrage wiederfindet. Zweimal dasselbe Thema am selben Tag
    ueberschreibt den Report; `report_schreiben` meldet das ausdruecklich
    zurueck, statt es stillschweigend zu tun."""
    return f"{slug(thema, region)}-{(tag or date.today()).isoformat()}.md"


def report_schreiben(dateiname: str, inhalt: str):
    """Report ablegen -> (pfad, ueberschrieben). Wirft OSError/ValueError.

    Der Ordner wird angelegt, falls er fehlt: im Betrieb ist er der Bind
    `./reports:/reports`, in Tests ein tmp-Verzeichnis.
    """
    wurzel = os.path.realpath(REPORT_VERZEICHNIS)
    os.makedirs(wurzel, exist_ok=True)
    basis = os.path.basename(dateiname)
    ziel = os.path.join(wurzel, basis)
    # Zweite Sicherung (siehe `slug`): der Name verlaesst hier die Funktion in
    # einen Dateizugriff. Die Erzwingung gehoert an die Stelle, an der
    # geschrieben wird — nicht nur in eine vorgelagerte Pruefung.
    if os.path.dirname(os.path.realpath(ziel)) != wurzel:
        raise ValueError(f"Reportname '{dateiname}' zeigt aus {wurzel} heraus.")
    ueberschrieben = os.path.exists(ziel)
    with open(ziel, "w", encoding="utf-8", newline="\n") as f:
        f.write(inhalt)
    return ziel, ueberschrieben


# ---------------------------------------------------------------------------
# Apify
# ---------------------------------------------------------------------------

def _fehler_http(e: urllib.error.HTTPError) -> str:
    """HTTP-Fehler -> Satz, den der Betreiber versteht und der ihm sagt, was
    jetzt zu tun ist. Der Rumpf wird gekuerzt mitgegeben (er nennt oft den
    genauen Grund) — vorher durch `_ohne_token`."""
    try:
        rumpf = _ohne_token(e.read().decode("utf-8", "replace"))[:300]
    except Exception:                       # noqa: BLE001 — Rumpf ist Beiwerk
        rumpf = ""
    if e.code in (401, 403) and "usage" not in rumpf and "credit" not in rumpf:
        return (f"Apify weist den Token zurueck (HTTP {e.code}). APIFY_TOKEN in "
                f"der .env pruefen und sales-mcp neu erzeugen. Antwort: {rumpf}")
    if 400 <= e.code < 500:
        return (f"Apify hat den Lauf abgelehnt (HTTP {e.code}). Wahrscheinlichste "
                f"Ursache auf dem Free-Plan: das Monatsguthaben ($5) ist "
                f"aufgebraucht — dann geht bis zum Zyklusende keine Recherche "
                f"mehr. Guthaben auf console.apify.com pruefen. Antwort: {rumpf}")
    return (f"Apify meldet eine Stoerung (HTTP {e.code}) — spaeter erneut "
            f"versuchen. Antwort: {rumpf}")


def _lauf(eingabe: dict):
    """Ein synchroner Actor-Lauf -> (dataset-items, None) | (None, fehlertext).

    `run-sync-get-dataset-items` startet den Actor, wartet und liefert die
    Datensaetze in einem Aufruf — es gibt hier nichts zu pollen und keinen
    Zustand, der zwischen zwei Aufrufen haengen bliebe.
    """
    tok = token()
    if not tok:
        # KEIN HTTP: ohne Token gaebe es nur einen 401, aber der Fehlertext
        # soll sagen, was fehlt, statt was der fremde Dienst antwortet.
        return None, FEHLER_KEIN_TOKEN
    frage = urllib.parse.urlencode({
        "token": tok,
        "timeout": LAUF_TIMEOUT_S,
        "maxTotalChargeUsd": MAX_TOTAL_CHARGE_USD,
        # `clean` wirft Felder ohne Wert und Zwischenzeilen des Actors raus —
        # die Antwort wird spuerbar kleiner, die Normalisierung unten kuerzer.
        "clean": "true",
    })
    # Der Token reist im Query-String — so sieht es die Apify-API-Konvention
    # vor. Er steht damit NICHT in argv (kein Aufruf ueber die Kommandozeile)
    # und wird nirgends geloggt. URL-Konstruktion und Request stehen IM try —
    # dieselbe Lehre wie in dispatch.py (T5a): eine Basis-URL ohne Schema oder
    # ein Steuerzeichen im Actor-Namen wirft ValueError bzw. InvalidURL, und
    # deren Meldung traegt die volle URL SAMT Token. Ausserhalb des try
    # entkaeme sie ungefiltert an den Aufrufer (Review-Befund T1, im Container
    # reproduziert); hier unten faengt sie die letzte except-Klausel und
    # `_ohne_token` filtert.
    try:
        url = f"{APIFY_BASIS}/acts/{ACTOR}/run-sync-get-dataset-items?{frage}"
        anfrage = urllib.request.Request(
            url, data=json.dumps(eingabe).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(anfrage, timeout=HTTP_TIMEOUT_S) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as e:      # muss vor URLError stehen
        return None, _fehler_http(e)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, _ohne_token(
            f"Apify nicht erreichbar oder der Lauf war zu langsam "
            f"({type(e).__name__}: {e}). Der Lauf kann bei Apify weitergelaufen "
            f"sein und Guthaben verbraucht haben — vor einem zweiten Versuch "
            f"kurz auf console.apify.com nachsehen.")
    except (ValueError, http.client.HTTPException) as e:
        # ValueError: urlopen bei URL ohne Schema. InvalidURL (Unterklasse von
        # HTTPException) bei Steuerzeichen im Pfad. Beide nennen die URL.
        return None, _ohne_token(
            f"Apify-Aufruf nicht konstruierbar ({type(e).__name__}: {e}). "
            f"APIFY_BASIS und APIFY_ACTOR in der Umgebung pruefen.")
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "Apify hat kein lesbares JSON geliefert."
    if not isinstance(daten, list):
        return None, f"Unerwartete Antwortform von Apify: {type(daten).__name__}."
    return daten, None


def _text(wert) -> str:
    return str(wert).strip() if wert not in (None, "") else ""


def _zahl(wert):
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def treffer_aus(eintrag: dict) -> dict:
    """Ein Google-Maps-Datensatz -> die sechs Angaben, die uns interessieren.

    Absichtlich schmal: Name, Adresse, Telefon, Website, Kategorie, Bewertung
    (plus Anzahl Bewertungen, Geschlossen-Kennzeichen und Maps-Link fuer den
    Report). Alles andere der 97 Felder — Oeffnungszeiten, Bilder, Rezensionen,
    Fragen — braucht hier niemand und bliebe nur als Datenhalde liegen.
    """
    telefon = _text(eintrag.get("phoneUnformatted")) or _text(eintrag.get("phone"))
    return {
        "name": _text(eintrag.get("title")),
        "adresse": _text(eintrag.get("address")),
        "ort": _text(eintrag.get("city")),
        # Anzeigeform daneben, weil ein Mensch "0941 123456" leichter liest
        # als "+49941123456" — gespeichert wird trotzdem die internationale.
        "telefon": telefon,
        "telefon_anzeige": _text(eintrag.get("phone")) or telefon,
        "website": _text(eintrag.get("website")),
        "kategorie": _text(eintrag.get("categoryName")),
        "kategorien": [_text(k) for k in (eintrag.get("categories") or [])
                       if _text(k)],
        "bewertung": _zahl(eintrag.get("totalScore")),
        "bewertungen": int(_zahl(eintrag.get("reviewsCount")) or 0),
        "geschlossen": bool(eintrag.get("permanentlyClosed")
                            or eintrag.get("temporarilyClosed")),
        "maps_url": _text(eintrag.get("url")),
    }


def kosten_usd(anzahl: int) -> float:
    """Rechnerischer Preis eines Laufs nach dem gemessenen Ereignistarif."""
    return round(PREIS_START_USD + anzahl * PREIS_JE_TREFFER_USD, 5)


def suche(thema: str, region: str, limit=LIMIT_VORGABE):
    """Google-Maps-Suche -> (ergebnis, None) | (None, fehlertext).

    `ergebnis` = {"treffer": [...], "limit": n, "kosten_usd": x, "thema", "region"}.
    """
    thema = (thema or "").strip()
    region = (region or "").strip()
    if not thema:
        return None, "Kein Suchbegriff angegeben — ohne Thema keine Recherche."
    if not region:
        return None, "Keine Region angegeben — ohne Ort waere die Suche weltweit."
    n = kappe_limit(limit)
    eingabe = {
        "searchStringsArray": [thema],
        "locationQuery": region,
        "maxCrawledPlacesPerSearch": n,
        "language": SPRACHE,
    }
    daten, fehler = _lauf(eingabe)
    if fehler:
        return None, fehler
    # Der Actor legt bei erfolgloser Suche eine Hinweiszeile ohne `title` ins
    # Dataset; die faellt hier raus. Die zweite Kappung auf `n` ist Vorsicht
    # gegenueber einem Actor, der mehr liefert als bestellt — bezahlt waere
    # das trotzdem, aber der Report bliebe wenigstens bei der Groesse, die
    # angefordert wurde.
    treffer = [t for t in (treffer_aus(e) for e in daten if isinstance(e, dict))
               if t["name"]][:n]
    return {"thema": thema, "region": region, "limit": n, "treffer": treffer,
            "kosten_usd": kosten_usd(len(treffer))}, None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _bewertung_text(t: dict) -> str:
    if t["bewertung"] is None:
        return "—"
    return f"{t['bewertung']:.1f}".replace(".", ",") + f" ({t['bewertungen']})"


def _feld(wert: str) -> str:
    """Tabellenzelle: leer wird zu „—", Pipes koennen die Tabelle nicht
    zerreissen (Firmennamen mit `|` gibt es wirklich)."""
    return (wert or "").replace("|", "/") or "—"


def lead_notiz(t: dict, thema: str, region: str, tag=None) -> str:
    """Die `notes`-Zeile eines Recherche-Leads — knapp und vollstaendig genug,
    dass der Betreiber ohne Rueckfrage weiss, woher der Kontakt kommt."""
    teile = [
        f"Adresse: {t['adresse'] or 'unbekannt'}",
        f"Website: {t['website'] or 'keine'}",
        f"Kategorie: {t['kategorie'] or 'unbekannt'}",
        f"Bewertung: {_bewertung_text(t)}",
        f"Quelle: Google Maps (Apify), Suche '{thema}' in '{region}' am "
        f"{(tag or date.today()).isoformat()}",
        "Recherche-Lead: keine Einwilligung, NICHT per WhatsApp anschreiben.",
    ]
    return " | ".join(teile)


# Genau die Zeile, die `lead_notiz` oben schreibt — deshalb steht der Leser
# direkt unter dem Schreiber. Wer das Format dort aendert, sieht hier, was
# sonst stillschweigend aufhoert zu funktionieren. Kein Datenbankwissen: die
# Funktion bekommt eine Zeichenkette, nicht eine Zeile aus `leads`.
_RE_NOTIZ_WEBSITE = re.compile(r"Website:\s*([^|\n]+)", re.I)

# Was `lead_notiz` schreibt, wenn es keine Website gab ("Website: keine") —
# und was Menschen sonst noch in dieses Feld tippen.
_KEINE_WEBSITE = {"keine", "keine website", "unbekannt", "-", "--", "—", "n/a",
                  "nichts", "none", "null"}


def website_aus_notiz(notes: str) -> str:
    """`notes` -> Website-Adresse oder "" — der Umkehrschluss zu `lead_notiz`."""
    treffer = _RE_NOTIZ_WEBSITE.search(notes or "")
    if not treffer:
        return ""
    wert = treffer.group(1).strip().strip(",;.")
    return "" if wert.lower() in _KEINE_WEBSITE else wert


def _auffaelligkeiten(treffer: list) -> list:
    """Nur, was sich aus den Daten ausrechnen laesst — keine Deutung.

    Der Report wird von einem Menschen im Vertrieb gelesen; eine erfundene
    „Markteinschaetzung" waere hier schlimmer als keine.
    """
    n = len(treffer)
    ohne_website = sum(1 for t in treffer if not t["website"])
    ohne_telefon = sum(1 for t in treffer if not t["telefon"])
    ohne_bewertung = sum(1 for t in treffer if t["bewertung"] is None)
    geschlossen = sum(1 for t in treffer if t["geschlossen"])
    bewertet = [t["bewertung"] for t in treffer if t["bewertung"] is not None]
    zeilen = []
    if bewertet:
        schnitt = sum(bewertet) / len(bewertet)
        zeilen.append(
            f"Durchschnittsbewertung der {len(bewertet)} bewerteten Anbieter: "
            f"{schnitt:.2f}".replace(".", ",") + " von 5,0.")
    zeilen.append(
        f"Ohne eigene Website: {ohne_website} von {n} "
        f"({ohne_website * 100 // n if n else 0} %).")
    zeilen.append(f"Ohne hinterlegte Telefonnummer: {ohne_telefon} von {n}.")
    if ohne_bewertung:
        zeilen.append(
            f"Ohne jede Bewertung: {ohne_bewertung} — typisch fuer junge oder "
            f"sehr kleine Anbieter.")
    if geschlossen:
        zeilen.append(
            f"Als geschlossen gekennzeichnet: {geschlossen} — im Wettbewerb "
            f"nicht mehr mitzaehlen.")
    return zeilen


def markt_report(thema: str, region: str, treffer: list, limit: int,
                 kosten: float = None, tag=None) -> str:
    """Markdown-Report einer Marktanalyse."""
    tag = tag or date.today()
    n = len(treffer)
    kategorien = Counter(t["kategorie"] or "ohne Kategorie" for t in treffer)
    top = sorted((t for t in treffer if t["bewertung"] is not None),
                 key=lambda t: (t["bewertung"], t["bewertungen"]), reverse=True)[:10]
    mit_telefon = sum(1 for t in treffer if t["telefon"])
    mit_website = sum(1 for t in treffer if t["website"])

    z = [f"# Marktanalyse: {thema} in {region}", "",
         f"Erhoben am {tag.isoformat()} ueber Google Maps. {n} Treffer "
         f"(angefordert: {limit}).", "",
         "## Ueberblick", "",
         f"- Treffer gesamt: **{n}**",
         f"- mit Telefonnummer: {mit_telefon}",
         f"- mit Website: {mit_website}",
         f"- verschiedene Kategorien: {len(kategorien)}", "",
         "## Cluster nach Kategorie", "",
         "| Kategorie | Anzahl |", "| --- | ---: |"]
    for name, anzahl in kategorien.most_common():
        z.append(f"| {_feld(name)} | {anzahl} |")
    z += ["", "## Top-Bewertete", ""]
    if top:
        z += ["| # | Name | Bewertung | Kategorie | Ort |",
              "| ---: | --- | --- | --- | --- |"]
        for i, t in enumerate(top, 1):
            z.append(f"| {i} | {_feld(t['name'])} | {_bewertung_text(t)} | "
                     f"{_feld(t['kategorie'])} | {_feld(t['ort'])} |")
    else:
        z.append("Keiner der Treffer hat eine Bewertung.")
    z += ["", "## Auffaelligkeiten", ""]
    z += [f"- {s}" for s in _auffaelligkeiten(treffer)]
    z += ["", "## Alle Treffer", "",
          "| Name | Adresse | Telefon | Website | Kategorie | Bewertung |",
          "| --- | --- | --- | --- | --- | --- |"]
    for t in treffer:
        name = _feld(t["name"]) + (" *(geschlossen)*" if t["geschlossen"] else "")
        z.append(f"| {name} | {_feld(t['adresse'])} | "
                 f"{_feld(t['telefon_anzeige'])} | {_feld(t['website'])} | "
                 f"{_feld(t['kategorie'])} | {_bewertung_text(t)} |")
    kosten = kosten_usd(n) if kosten is None else kosten
    z += ["", "---", "",
          f"Quelle: Google Maps, erhoben am {tag.isoformat()} ueber den "
          f"Apify-Actor `{ACTOR.replace('~', '/')}`; Suchbegriff \"{thema}\", "
          f"Region \"{region}\", Obergrenze {limit} Treffer. Rechnerische "
          f"Kosten dieses Laufs: ${kosten:.5f} "
          f"(${PREIS_START_USD:.5f} Start + {n} x ${PREIS_JE_TREFFER_USD:.3f}). "
          f"Ausschliesslich oeffentliche Firmendaten — keine Personendaten.",
          ""]
    return "\n".join(z)


def kurzfassung(thema: str, region: str, treffer: list) -> list:
    """Fuenf Zeilen fuer den Chat — der Report ist zum Nachlesen da, hier soll
    der Betreiber in einem Atemzug hoeren, was rauskam."""
    n = len(treffer)
    kategorien = Counter(t["kategorie"] or "ohne Kategorie" for t in treffer)
    bewertet = [t["bewertung"] for t in treffer if t["bewertung"] is not None]
    top = max(treffer, key=lambda t: (t["bewertung"] or 0, t["bewertungen"]),
              default=None)
    haeufigste = ", ".join(f"{k} ({v})" for k, v in kategorien.most_common(3))
    schnitt = (f"{sum(bewertet) / len(bewertet):.2f}".replace(".", ",")
               if bewertet else "keine Bewertungen")
    return [
        f"{n} Anbieter zu \"{thema}\" in {region} erfasst.",
        f"Haeufigste Kategorien: {haeufigste or '—'}.",
        f"Durchschnittsbewertung: {schnitt}"
        + (f" (von {len(bewertet)} bewerteten)." if bewertet else "."),
        (f"Bestbewertet: {top['name']} mit {_bewertung_text(top)}."
         if top and top["bewertung"] is not None else
         "Kein Anbieter mit Bewertung darunter."),
        f"Ohne eigene Website: {sum(1 for t in treffer if not t['website'])} "
        f"von {n} — moeglicher Anknuepfungspunkt.",
    ]


# ---------------------------------------------------------------------------
# Firmen-Anreicherung (Stufe 6) — die Website eines bestehenden
# Firmenkontakts selbst lesen. Warum ohne Apify: siehe Moduldocstring.
# ---------------------------------------------------------------------------

# Obergrenze der Seiten je Firma. Fuenf, weil der Auftrag es so setzt, und
# weil mehr nichts brachte: Startseite + Impressum + Ueber-uns + Kontakt sind
# das, was ein Handwerksbetrieb an Text ueberhaupt hat.
FIRMA_MAX_SEITEN = 5

# Je Seite eine eigene Uhr — anders als beim Actor-Lauf gibt es hier nichts,
# was nach einem Abbruch weiterliefe und Geld kostete; der Timeout schuetzt
# nur davor, dass ein haengender Server das Werkzeug blockiert.
FIRMA_TIMEOUT_S = float(os.environ.get("FIRMA_TIMEOUT_S", "20"))

# ... und EINE Uhr fuer den ganzen Lauf (Review-Befund R3): 5 Seiten x 20 s
# waeren sonst 100 Sekunden, in denen der Agent scheinbar haengt — und der
# Timeout je Socket-Operation haelt einen troepfelnden Server nicht auf.
# Ist das Budget verbraucht, kommen die restlichen Seiten als
# `nicht_gelesen` zurueck statt gar nichts.
FIRMA_ZEITBUDGET_S = float(os.environ.get("FIRMA_ZEITBUDGET_S", "60"))

# Gekuerzter Text je Seite. Der Volltext einer Handwerker-Startseite lag in
# der Messung bei 1 937 bis 8 855 Zeichen; 2 000 je Seite reichen fuer die
# Gespraechsvorbereitung und halten `leads.enrichment` klein.
FIRMA_TEXT_MAX = 2000

# Leseobergrenze in Bytes, VOR dem Dekodieren. Ohne sie koennte eine einzige
# Seite (oder ein als text/html ausgeliefertes Grossobjekt) den Speicher des
# Containers fuellen. Die groesste gemessene echte Seite hatte 426 KB.
FIRMA_BYTES_MAX = 3_000_000

# Ein sprechender User-Agent statt python-urllib: wer in seinem Serverlog
# nachsieht, wer da liest, soll es beantwortet bekommen. Manche Server
# weisen den Vorgabe-Agent von urllib ausserdem rundheraus ab.
FIRMA_USER_AGENT = os.environ.get(
    "FIRMA_USER_AGENT",
    "Mozilla/5.0 (compatible; sales-claw/1.0; Firmenrecherche)")

# Der Direkt-Weg kostet nichts — die Null steht trotzdem in jeder Rueckgabe,
# an derselben Stelle, an der marktanalyse/b2b_leads ihre Kosten nennen.
# Ein Werkzeug, das die Kostenzeile einfach weglaesst, waere im Betrieb nicht
# von einem zu unterscheiden, das sie vergessen hat.
FIRMA_KOSTEN_USD = 0.0

# Nur fuer die Testsuite: der Stub laeuft auf 127.0.0.1, und genau dorthin
# laesst `_ziel_erlaubt` im Betrieb nicht. Gleiches Muster wie APIFY_BASIS —
# ein Modulattribut, das die Suite umbiegt (monkeypatch), keine Abschwaechung
# der Kante selbst. Der Vorgabewert ist und bleibt False.
FIRMA_PRIVATE_ZIELE_ERLAUBT = os.environ.get("FIRMA_PRIVATE_ZIELE", "") == "1"

# Seitentypen in Bearbeitungsreihenfolge — die erste passende Regel gewinnt.
# Impressum zuerst, weil dort steht, was den Erstkontakt traegt (Inhaber,
# Rechtsform, Registereintrag); danach die Selbstbeschreibung, dann Kontakt,
# zuletzt das Leistungsangebot.
_SEITEN_TYPEN = (
    ("impressum", re.compile(r"impressum|imprint|anbieterkennzeichnung", re.I)),
    # `team` steht hier bewusst NICHT (Review-Befund G1): eine Team-Seite ist
    # eine Namensliste von Beschaeftigten — Personendaten, die dieses
    # Werkzeug ausdruecklich nicht erhebt. Was es an Personenbezug gibt, ist
    # allein der Name der Vertretung aus der Impressumspflicht.
    ("ueber_uns", re.compile(
        r"ueber-?uns|über-?uns|about|unternehmen|philosophie|betrieb|"
        r"historie|geschichte|wir-?ueber", re.I)),
    ("kontakt", re.compile(r"kontakt|contact|anfahrt", re.I)),
    ("leistungen", re.compile(
        r"leistung|service|angebot|kompetenz|produkt|referenz|gewerke", re.I)),
)

_NICHT_HOLBAR = re.compile(r"^\s*(mailto:|tel:|javascript:|data:|#)", re.I)


class _ZielAbgewiesen(Exception):
    """Eine Weiterleitung zeigte aus dem oeffentlichen Netz heraus.

    Eigene Klasse statt HTTPError: der Fall ist kein Fehler des fremden
    Servers, sondern unsere eigene Kante — und er darf nicht in der
    HTTP-Fehlerabbildung landen, die von Serverstoerungen spricht.
    """


def _ziel_erlaubt(url: str):
    """Darf diese Adresse abgerufen werden? -> (True, None) | (False, grund).

    Die Adresse stammt NICHT vom Betreiber allein: sie kommt im Regelfall aus
    `leads.notes`, dort aus einem Google-Maps-Datensatz — also aus einer
    fremden Quelle, die ein Dritter befuellt hat. Ein Eintrag mit
    `http://127.0.0.1:8765/` oder einer Adresse im Docker-Netz wuerde diesen
    Container gegen seine eigenen Dienste laufen lassen (SSRF); im selben Netz
    haengen Postgres und der MCP-Port. Deshalb wird der Hostname aufgeloest und
    JEDE Antwort geprueft, nicht nur die Schreibweise der URL.

    DEKLARIERTES RESTRISIKO — DNS-Rebinding (Review-Befund S1): aufgeloest
    wird hier EINMAL; den Verbindungsaufbau macht urllib spaeter mit einer
    EIGENEN Aufloesung. Ein Angreifer mit eigenem Nameserver kann zwischen
    beiden Antworten wechseln (oeffentlich -> privat). Die Abwehr braeuchte
    IP-Pinning im Verbindungsaufbau (eigene HTTPConnection, Host-Header und
    SNI von Hand) — gemessen am Bedrohungsraum dieses Werkzeugs
    (Firmen-Websites aus Google Maps, vom Betreiber je Lead beauftragt, kein
    unbeaufsichtigter Massenlauf) steht der Aufwand in keinem Verhaeltnis.
    Bewusst getragen, nicht uebersehen.
    """
    try:
        teile = urllib.parse.urlsplit(url)
    except ValueError as e:
        # urlsplit selbst wirft bei kaputten IPv6-Literalen ("http://[::1").
        # Ausserhalb eines try verliesse das als Traceback das Werkzeug —
        # exakt die T1-Lehre aus dem Stufe-5-Review, hier Befund S4.
        return False, f"Adresse nicht lesbar ({type(e).__name__}: {e})."
    if teile.scheme not in ("http", "https"):
        return False, (f"nur http/https werden abgerufen, hier steht "
                       f"'{teile.scheme or 'kein Schema'}'.")
    try:
        gastgeber = teile.hostname
        port = teile.port or (443 if teile.scheme == "https" else 80)
    except ValueError as e:
        # urlsplit prueft Port und Host-Syntax erst beim Zugriff (":abc").
        return False, f"Adresse nicht lesbar ({type(e).__name__}: {e})."
    if not gastgeber:
        return False, "die Adresse nennt keinen Hostnamen."
    if FIRMA_PRIVATE_ZIELE_ERLAUBT:
        return True, None
    if port not in (80, 443):
        # Firmenwebsites antworten auf 80/443. Alles andere ist ein DIENST
        # (5432, 22, 6379, ...), den dieses Werkzeug nichts angeht — auch
        # nicht auf oeffentlichen Adressen (Review-Befund S3).
        return False, (f"Port {port} wird nicht abgerufen — Firmenwebsites "
                       f"antworten auf 80 oder 443.")
    try:
        infos = socket.getaddrinfo(gastgeber, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError, OSError) as e:
        return False, (f"der Hostname '{gastgeber}' ist nicht aufloesbar "
                       f"({type(e).__name__}).")
    for info in infos:
        try:
            adresse = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except ValueError:
            return False, f"unlesbare IP-Adresse zu '{gastgeber}'."
        # `not is_global` statt einer Positivliste einzelner Flags: die Liste
        # (is_private, is_loopback, ...) liess 100.64.0.0/10 durch — CGNAT,
        # u. a. Tailscale-Netze, und in Python 3.12 ausdruecklich NICHT
        # is_private (gh-113171). is_global stellt die Frage, um die es hier
        # wirklich geht: oeffentlich geroutet, ja oder nein
        # (Review-Befund S2).
        if not adresse.is_global:
            return False, (f"'{gastgeber}' zeigt auf {adresse} — keine "
                           f"oeffentlich geroutete Adresse. Abgerufen werden "
                           f"nur oeffentlich erreichbare Firmenwebsites.")
    return True, None


class _GepruefteWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Prueft JEDEN Weiterleitungssprung, nicht nur die Startadresse.

    Ohne das waere `_ziel_erlaubt` wirkungslos: eine oeffentlich erreichbare
    Seite darf mit HTTP 302 auf `http://127.0.0.1/` zeigen, und urllib folgt
    von sich aus. Die Pruefung gehoert deshalb an jeden Sprung.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        erlaubt, grund = _ziel_erlaubt(newurl)
        if not erlaubt:
            raise _ZielAbgewiesen(f"Weiterleitung abgewiesen — {grund}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _SeitenLeser(HTMLParser):
    """HTML -> Titel, sichtbarer Text, Links. Absichtlich anspruchslos.

    Kein BeautifulSoup, kein lxml: die Aufgabe ist „Fliesstext und
    Verweise aus statischem HTML", dafuer reicht die Standardbibliothek.
    `script`/`style` und Verwandte werden gezaehlt statt bloss erkannt —
    verschachtelte oder unsauber geschlossene Tags gibt es auf echten Seiten
    reichlich, und ein einzelnes Flag waere danach dauerhaft verstellt.
    """

    # `head` steht hier bewusst NICHT drin, obwohl es verlockend waere: der
    # Titel liegt darin, und ein stummes `head` haette ihn mitverschluckt
    # (im Test aufgefallen — die Startseite „trug keinen Titel", obwohl sie
    # einen hat). Was in `head` sonst Text traegt, ist ohnehin erfasst:
    # `script` und `style` stehen unten, `meta`/`link` haben keinen Inhalt.
    _STUMM = frozenset(("script", "style", "noscript", "template", "svg",
                        "iframe"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titel = ""
        self.links = []
        self._teile = []
        self._stumm = 0
        self._im_titel = False

    def handle_starttag(self, tag, attrs):
        if tag in self._STUMM:
            self._stumm += 1
        elif tag == "title":
            self._im_titel = True
        elif tag == "a":
            for name, wert in attrs:
                if name == "href" and wert:
                    self.links.append(wert)
                    break

    def handle_endtag(self, tag):
        if tag in self._STUMM:
            self._stumm = max(0, self._stumm - 1)
        elif tag == "title":
            self._im_titel = False

    def handle_data(self, daten):
        if self._stumm:
            return
        if self._im_titel:
            self.titel += daten
            return
        gestutzt = daten.strip()
        if gestutzt:
            self._teile.append(gestutzt)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._teile)).strip()


def _seitentyp(url: str, titel: str) -> str:
    """URL- und Titel-Heuristik -> impressum | ueber_uns | kontakt |
    leistungen | sonstige. Die URL zaehlt mehr als der Titel: sie ist vom
    Betreiber der Seite bewusst vergeben, der Titel oft nur Werbetext."""
    pfad = urllib.parse.urlsplit(url).path
    for name, muster in _SEITEN_TYPEN:
        if muster.search(pfad):
            return name
    for name, muster in _SEITEN_TYPEN:
        if muster.search(titel or ""):
            return name
    return "sonstige"


def _gleiche_firma(basis: str, kandidat: str) -> bool:
    """Bleibt der Verweis auf der Website der Firma?

    Ohne diese Kante wuerde der erste Facebook- oder Herstellerlink der
    Startseite mitgelesen — Daten, die nicht der Firma gehoeren, in einem
    Werkzeug, dessen ganze Rechtfertigung „die eigene Website des
    Firmenkontakts" ist. `www.` wird auf beiden Seiten abgeschnitten, weil
    Seiten regelmaessig zwischen beiden Schreibweisen springen (gemessen:
    www.koller-ht.de leitet auf koller-ht.de).
    """
    def kern(u):
        gastgeber = (urllib.parse.urlsplit(u).hostname or "").lower()
        return gastgeber[4:] if gastgeber.startswith("www.") else gastgeber
    return bool(kern(basis)) and kern(basis) == kern(kandidat)


def _schluessel(url: str) -> str:
    """Vergleichsform einer Adresse — ohne Fragment, ohne Schluss-Schraegstrich
    und ohne www., damit dieselbe Seite nicht zweimal geholt wird."""
    t = urllib.parse.urlsplit(url)
    gastgeber = (t.hostname or "").lower()
    if gastgeber.startswith("www."):
        gastgeber = gastgeber[4:]
    return f"{gastgeber}{(t.path or '/').rstrip('/') or '/'}?{t.query}"


def _fehler_seite_http(url: str, e: urllib.error.HTTPError) -> str:
    """HTTP-Fehler einer Firmenwebsite -> Satz fuer den Betreiber.

    Bewusst NICHT `_fehler_http`: das spricht von Apify-Token und
    Monatsguthaben. Hier antwortet der Webserver eines Handwerksbetriebs,
    und die einzig sinnvolle Auskunft ist, ob die Seite weg ist (404), uns
    aussperrt (403/429) oder gerade streikt (5xx).
    """
    if e.code == 404:
        return (f"{url} antwortet mit HTTP 404 — die Seite gibt es unter "
                f"dieser Adresse nicht (mehr). Website im Kontakt pruefen.")
    if e.code in (401, 403, 429):
        return (f"{url} verweigert den Abruf (HTTP {e.code}) — die Seite "
                f"sperrt automatisierte Zugriffe aus. Diese Firma muss von "
                f"Hand angesehen werden; es wird nichts umgangen.")
    if 400 <= e.code < 500:
        return f"{url} weist den Abruf ab (HTTP {e.code})."
    if 300 <= e.code < 400:
        # Hierher kommt eine Weiterleitung, der NICHT gefolgt wurde — etwa
        # weil urllib das Zielschema ablehnt (file:, ftp:). Ohne den Zweig
        # hiesse eine Sicherheitsabweisung "Serverstoerung, spaeter erneut
        # versuchen" (Review-Befund S5).
        return (f"{url} leitet weiter (HTTP {e.code}), aber dem Ziel wird "
                f"nicht gefolgt (unzulaessiges Schema oder Ziel) — diese "
                f"Firma von Hand ansehen.")
    return (f"{url} meldet eine Serverstoerung (HTTP {e.code}) — spaeter "
            f"erneut versuchen.")


def _hole_seite(url: str):
    """Eine Seite -> (seite, None) | (None, fehlertext). Wirft nie.

    `seite` = {"url", "typ", "titel", "text", "status", "bytes"}.

    Die Request-Konstruktion steht VOLLSTAENDIG im try — dieselbe Lehre wie
    in `_lauf` (Review-Befund T1): eine Adresse ohne Schema laesst urlopen
    einen ValueError werfen, ein Steuerzeichen im Pfad eine InvalidURL
    (http.client.HTTPException, weder URLError noch OSError). Beide nennen
    die volle URL. Ausserhalb des try entkaemen sie ungefiltert; hier faengt
    sie die letzte Klausel, und `_ohne_token` filtert. Dass in einer
    Website-URL normalerweise kein Apify-Token steckt, ist dabei kein
    Argument, es wegzulassen: die Filterung kostet nichts und gilt im ganzen
    Modul einheitlich.
    """
    try:
        anfrage = urllib.request.Request(url, headers={
            "User-Agent": FIRMA_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9",
        })
        oeffner = urllib.request.build_opener(_GepruefteWeiterleitung)
        with oeffner.open(anfrage, timeout=FIRMA_TIMEOUT_S) as antwort:
            status = getattr(antwort, "status", 200)
            kopf = antwort.headers
            roh = antwort.read(FIRMA_BYTES_MAX)
            endgueltig = antwort.geturl()
    except _ZielAbgewiesen as e:
        return None, _ohne_token(f"{url}: {e}")
    except urllib.error.HTTPError as e:
        return None, _ohne_token(_fehler_seite_http(url, e))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, _ohne_token(
            f"{url} ist nicht erreichbar ({type(e).__name__}: {e}) — "
            f"Adresse pruefen oder spaeter erneut versuchen.")
    except (ValueError, http.client.HTTPException) as e:
        return None, _ohne_token(
            f"Abruf von {url} nicht konstruierbar ({type(e).__name__}: {e}).")

    art = (kopf.get("Content-Type") or "").lower()
    if art and not ("html" in art or "text/plain" in art or "xml" in art):
        return None, (f"{endgueltig} liefert '{art.split(';')[0]}' statt einer "
                      f"Webseite — daraus wird hier kein Text gelesen.")
    if not art and (b"\x00" in roh[:1024] or roh.startswith(b"%PDF-")):
        # Ohne Content-Type-Header griff die Pruefung oben nicht und
        # Binaerdaten landeten als "Text" in der Ablage (Review-Befund R2).
        return None, (f"{endgueltig} liefert Binaerdaten ohne Content-Type — "
                      f"daraus wird hier kein Text gelesen.")
    zeichensatz = kopf.get_content_charset()
    if not zeichensatz:
        # Aeltere Handwerker-Seiten liefern ISO-8859-1 OHNE charset im
        # Header und nennen ihn nur im <meta>. utf-8/replace macht daraus
        # Ersatzzeichen — und "Geschäftsführer" wird fuer die Hinweis-Regex
        # unauffindbar, obwohl er dasteht (Review-Befund R1, gemessen).
        # latin-1 dekodiert jedes Byte verlustfrei — gut genug zum Suchen.
        kopfstueck = roh[:4096].decode("latin-1", "replace")
        m = (re.search(r'<meta[^>]+charset=["\']?\s*([A-Za-z0-9_.\-]+)',
                       kopfstueck, re.I)
             or re.search(r'<\?xml[^>]+encoding=["\']([A-Za-z0-9_.\-]+)',
                          kopfstueck, re.I))
        zeichensatz = m.group(1) if m else "utf-8"
    try:
        inhalt = roh.decode(zeichensatz, "replace")
    except (LookupError, UnicodeDecodeError):
        # Unbekannt benannter Zeichensatz (es gibt Server, die Fantasienamen
        # schicken) — utf-8 mit Ersatzzeichen ist hier besser als kein Text.
        inhalt = roh.decode("utf-8", "replace")
    leser = _SeitenLeser()
    try:
        leser.feed(inhalt)
        leser.close()
    except Exception:                   # noqa: BLE001 — Rest zaehlt, nicht der Fehler
        # HTMLParser ist nachsichtig, aber nicht unfehlbar. Was bis zum
        # Abbruch gelesen wurde, ist brauchbar und geht nicht verloren.
        pass
    titel = re.sub(r"\s+", " ", leser.titel).strip()
    return {"url": endgueltig, "typ": _seitentyp(endgueltig, titel),
            "titel": titel[:200], "text": leser.text[:FIRMA_TEXT_MAX],
            "status": status, "bytes": len(roh),
            "_links": leser.links}, None


def _unterseiten(start: dict) -> list:
    """Verweise der Startseite -> Kandidaten, nach Seitentyp sortiert.

    Zurueck kommen nur Adressen auf derselben Firmen-Website, die einem der
    gesuchten Typen entsprechen — es wird NICHT die ganze Seite durchkrochen.
    Sortiert nach der Reihenfolge in `_SEITEN_TYPEN`: Impressum zuerst.
    """
    rang = {name: i for i, (name, _) in enumerate(_SEITEN_TYPEN)}
    gesehen = {_schluessel(start["url"])}
    kandidaten = []
    for verweis in start.get("_links", []):
        if _NICHT_HOLBAR.match(verweis or ""):
            continue
        try:
            voll = urllib.parse.urljoin(start["url"], verweis.strip())
            voll = urllib.parse.urldefrag(voll)[0]
            if not _gleiche_firma(start["url"], voll):
                continue
            typ = _seitentyp(voll, "")
            if typ == "sonstige":
                continue
            s = _schluessel(voll)
        except ValueError:
            # Ein kaputter Verweis der fremden Seite ("http://[::1", wirres
            # IPv6-Literal) laesst urldefrag/urlsplit einen ValueError werfen
            # — ein fremder Link darf das Werkzeug nicht zum Absturz bringen
            # (Review-Befund S4, zweite Fundstelle).
            continue
        if s in gesehen:
            continue
        gesehen.add(s)
        kandidaten.append((rang[typ], len(kandidaten), voll))
    kandidaten.sort()
    return [url for _, _, url in kandidaten]


# Fakten, die sich aus dem Text ABLESEN lassen. Frueher stand hier min()/
# max() ueber alle Treffer aller Seiten — das WAR eine Deutung, und eine
# falsche dazu: "seit 1985 verbaute Anlagen" (Werbetext) gewann gegen
# "besteht seit 2004" (Review-Befund H1, gemessen). Jetzt gilt: genau EIN
# eindeutiger Treffer -> Hinweis; mehrere verschiedene -> Kandidatenliste,
# und die Kurzfassung sagt ausdruecklich "uneindeutig". Was der Betreiber im
# Gespraech verwendet, muss er im mitgelieferten Volltext nachlesen koennen —
# deshalb heissen sie „Hinweise" und nicht „Firmendaten".
_RE_JAHR = re.compile(
    r"(?:seit|gegr[uü]ndet|gegruendet|besteht\s+seit|familienbetrieb\s+seit)"
    r"(?:\s+dem\s+Jahr|\s+im\s+Jahr)?\s+(\d{4})", re.I)
# Umlaute UND ihre Umschreibung: im Netz stehen beide Schreibweisen
# („Geschäftsführer" auf den meisten Seiten, „Geschaeftsfuehrer" auf aelteren
# oder umlautscheuen). Eine Regel, die nur die eine kennt, findet die halbe
# Wirklichkeit nicht — im Test aufgefallen.
_RE_VERTRETUNG = re.compile(
    r"(?:Gesch(?:ä|ae)ftsf(?:ü|ue)hr(?:er|erin|ung)|Inhaber(?:in)?"
    r"|Firmeninhaber|Vertreten\s+durch|Vertretungsberechtigt(?:er)?)"
    r"\s*(?:ist|sind)?\s*[:\-–]?\s*([A-ZÄÖÜ][^|·•\n;]{2,60})")
_RE_MITARBEITER = re.compile(
    r"(\d{1,4})\s*(?:Mitarbeiter|Besch[äa]ftigte|Kolleg|Angestellte|"
    r"Mitarbeitende)", re.I)
_RE_HANDELSREGISTER = re.compile(r"(HRA|HRB)\s*[:\-]?\s*(\d{1,7})", re.I)


def _firma_hinweise(seiten: list) -> dict:
    """Die vier Angaben des Auftrags, soweit sie woertlich dastehen."""
    # Impressum zuerst befragen: dort ist die Vertretung eine Pflichtangabe
    # (§ 5 DDG) und steht in fester Form, waehrend die Startseite denselben
    # Namen oft nur im Werbetext streift.
    geordnet = sorted(seiten, key=lambda s: 0 if s["typ"] == "impressum" else 1)
    ganzer = " ".join(s["text"] for s in geordnet)
    hinweise = {}

    m = _RE_VERTRETUNG.search(ganzer)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,:-–")
        # Ein Treffer, der schon wieder in die naechste Pflichtangabe
        # hineinlaeuft ("... Musterstrasse 1 Telefon"), ist keiner.
        name = re.split(r"\s+(?:Telefon|Tel\.|E-?Mail|Registergericht|"
                        r"Umsatzsteuer|USt|Sitz|Anschrift)\b", name)[0].strip()
        if 2 < len(name) <= 60:
            hinweise["vertretung"] = name

    heuer = date.today().year
    jahre = sorted({int(j) for j in _RE_JAHR.findall(ganzer)
                    if 1700 <= int(j) <= heuer})
    if len(jahre) == 1:
        hinweise["seit_jahr"] = jahre[0]
    elif jahre:
        hinweise["seit_jahr_kandidaten"] = jahre

    zahlen = sorted({int(z) for z in _RE_MITARBEITER.findall(ganzer)
                     if 0 < int(z) < 5000})
    if len(zahlen) == 1:
        hinweise["mitarbeiter_genannt"] = zahlen[0]
    elif zahlen:
        hinweise["mitarbeiter_kandidaten"] = zahlen

    hr = _RE_HANDELSREGISTER.search(ganzer)
    if hr:
        hinweise["handelsregister"] = f"{hr.group(1).upper()} {hr.group(2)}"
    return hinweise


def firma_daten(website_url: str, max_seiten: int = FIRMA_MAX_SEITEN):
    """Firmenwebsite lesen -> (daten, None) | (None, fehlertext).

    `daten` = {"website", "seiten": [{url, typ, titel, text, status, bytes}],
    "seiten_anzahl", "nicht_gelesen": [...], "hinweise": {...},
    "kosten_usd": 0.0}.

    Gelesen werden die Startseite und, nach Typ sortiert, bis zu vier
    Unterseiten derselben Website (Impressum, Ueber uns, Kontakt,
    Leistungen). Scheitert die STARTSEITE, ist das ein Fehler; scheitert eine
    Unterseite, steht sie unter `nicht_gelesen` und der Rest kommt trotzdem
    zurueck — dieselbe Haltung wie beim Report in `marktanalyse`: ein
    Teilergebnis ist besser als eine Fehlermeldung.
    """
    url = (website_url or "").strip()
    if not url:
        return None, ("Keine Website angegeben — ohne Adresse gibt es nichts "
                      "zu lesen.")
    if "://" not in url:
        # Google Maps liefert Adressen gelegentlich ohne Schema.
        url = "https://" + url.lstrip("/")
    erlaubt, grund = _ziel_erlaubt(url)
    if not erlaubt:
        return None, f"'{url}' wird nicht abgerufen: {grund}"
    try:
        deckel = max(1, min(int(max_seiten), FIRMA_MAX_SEITEN))
    except (TypeError, ValueError):
        deckel = FIRMA_MAX_SEITEN

    beginn = time.monotonic()
    start, fehler = _hole_seite(url)
    if fehler:
        return None, fehler
    seiten, nicht_gelesen = [start], []
    for kandidat in _unterseiten(start):
        if len(seiten) >= deckel:
            break
        if time.monotonic() - beginn > FIRMA_ZEITBUDGET_S:
            # Gesamtbudget statt nur Einzel-Timeouts (Review-Befund R3):
            # was nicht mehr drankam, steht ausdruecklich in nicht_gelesen.
            nicht_gelesen.append({"url": kandidat, "grund": (
                f"Gesamt-Zeitbudget ({FIRMA_ZEITBUDGET_S:.0f} s) erschoepft "
                f"— nicht mehr abgerufen.")})
            continue
        erlaubt, grund = _ziel_erlaubt(kandidat)
        if not erlaubt:
            nicht_gelesen.append({"url": kandidat, "grund": grund})
            continue
        seite, fehler = _hole_seite(kandidat)
        if fehler:
            nicht_gelesen.append({"url": kandidat, "grund": fehler})
            continue
        seiten.append(seite)
    for seite in seiten:
        seite.pop("_links", None)       # Arbeitsdaten, nichts fuer die Ablage
    return {"website": start["url"], "seiten": seiten,
            "seiten_anzahl": len(seiten), "nicht_gelesen": nicht_gelesen,
            "hinweise": _firma_hinweise(seiten),
            "kosten_usd": FIRMA_KOSTEN_USD}, None


def firma_kurzfassung(name: str, daten: dict) -> list:
    """Fuenf Zeilen fuer den Chat — was fuer den bAV-Erstkontakt zaehlt.

    Was nicht dasteht, wird als „nicht gefunden" gemeldet und nicht geraten.
    Ein erfundener Inhabername waere im Erstgespraech schlimmer als gar
    keiner.
    """
    seiten = daten.get("seiten") or []
    hinweise = daten.get("hinweise") or {}
    typen = [s["typ"] for s in seiten]
    gefunden = ", ".join(dict.fromkeys(typen)) or "keine"
    start = seiten[0] if seiten else {}

    vertretung = hinweise.get("vertretung")
    jahr = hinweise.get("seit_jahr")
    jahr_mehrere = hinweise.get("seit_jahr_kandidaten")
    leute = hinweise.get("mitarbeiter_genannt")
    leute_mehrere = hinweise.get("mitarbeiter_kandidaten")
    register = hinweise.get("handelsregister")

    # Jede Zeile mit Herkunft ("laut Website") und ohne Selbstsicherheit, die
    # der Text nicht hergibt — eine falsche Zahl im Erstgespraech ist
    # schlimmer als keine (Review-Befund H1).
    zeilen = [
        f"{name}: {len(seiten)} Seite(n) von {daten.get('website', '—')} "
        f"gelesen ({gefunden}).",
        (f"Inhaber/Geschaeftsfuehrung laut Website: {vertretung} — im "
         f"Impressum gegenpruefen."
         if vertretung else
         "Inhaber/Geschaeftsfuehrung: im Text nicht gefunden — im Impressum "
         "selbst nachsehen."),
        (f"Laut Website am Markt seit {jahr} "
         f"(rund {date.today().year - jahr} Jahre)."
         if jahr else
         (f"Jahresangaben uneindeutig "
          f"({', '.join(str(j) for j in jahr_mehrere)}) — im Volltext "
          f"pruefen." if jahr_mehrere else "Gruendungsjahr: nicht gefunden.")),
        (f"Betriebsgroesse: laut Website {leute} Mitarbeitende."
         if leute else
         (f"Mitarbeiterzahlen uneindeutig "
          f"({', '.join(str(z) for z in leute_mehrere)}) — im Volltext "
          f"pruefen." if leute_mehrere else
          ("Mitarbeiterzahl nicht genannt"
           + (f"; Handelsregister {register}." if register else
              " — Betriebsgroesse im Gespraech erfragen.")))),
        (f"Auftritt: \"{start.get('titel')}\"." if start.get("titel") else
         "Die Startseite traegt keinen Titel."),
    ]
    return zeilen
