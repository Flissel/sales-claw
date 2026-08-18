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
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date

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
