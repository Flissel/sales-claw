"""Vertragstests der Recherche-Werkzeuge gegen sales_test + Apify-Stub.

Wie test_dispatch.py: die Suite darf NIE gegen `sales` laufen, und sie
spricht NIE mit dem echten Apify. Der Ersatz ist ein `http.server`-Thread auf
einem vom Betriebssystem vergebenen Port; `recherche.APIFY_BASIS` wird auf ihn
umgebogen. Das ist hier nicht nur Sauberkeit, sondern Budget: jeder echte Lauf
kostet Guthaben vom $5-Monatskontingent des Free-Plans.
"""
import json
import os
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import recherche  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein."""
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# Apify-Stub
# ---------------------------------------------------------------------------

class _Stub:
    """Konfigurierbarer Apify-Ersatz: Status und Rumpf je Test."""

    def __init__(self):
        self.status = 200
        self.rumpf = b"[]"
        self.aufrufe = []
        self.sperre = threading.Lock()

    def antworte_mit(self, datensaetze):
        self.status = 200
        self.rumpf = json.dumps(datensaetze).encode("utf-8")

    def zuruecksetzen(self):
        self.status = 200
        self.rumpf = b"[]"
        with self.sperre:
            self.aufrufe.clear()


STUB = _Stub()
STUB_BASIS = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        laenge = int(self.headers.get("Content-Length", "0"))
        roh = self.rfile.read(laenge) if laenge else b""
        zerlegt = urlsplit(self.path)
        with STUB.sperre:
            STUB.aufrufe.append({
                "pfad": zerlegt.path,
                "query": {k: v[0] for k, v in parse_qs(zerlegt.query).items()},
                "eingabe": json.loads(roh or b"{}"),
            })
        rumpf = STUB.rumpf
        self.send_response(STUB.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def log_message(self, *_):  # kein Rauschen im Testlauf
        pass


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    global STUB_BASIS
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.daemon_threads = True
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    STUB_BASIS = f"http://127.0.0.1:{dienst.server_address[1]}/v2"
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def saubere_umgebung(tmp_path, monkeypatch):
    monkeypatch.setattr(recherche, "APIFY_BASIS", STUB_BASIS)
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path / "reports"))
    monkeypatch.setenv("APIFY_TOKEN", "stub-token")
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    sammel = server._q(
        "insert into leads (name, source) values "
        "('RECHERCHE (Sammelkontakt)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(recherche, "RECHERCHE_LEAD_ID", str(sammel))
    STUB.zuruecksetzen()
    yield


# ---------------------------------------------------------------------------
# Helfer — Datensaetze in der Form, die der Actor laut gemessenem
# Dataset-Schema liefert (title/address/phone/phoneUnformatted/website/
# categoryName/categories/totalScore/reviewsCount/permanentlyClosed/url).
# ---------------------------------------------------------------------------

def _ort(name, telefon="+499411234567", anzeige="0941 1234567",
         website="https://beispiel.de", kategorie="Versicherungsmakler",
         bewertung=4.5, bewertungen=12, geschlossen=False):
    return {
        "title": name,
        "address": "Beispielstrasse 1, 93047 Regensburg",
        "street": "Beispielstrasse 1",
        "city": "Regensburg",
        "postalCode": "93047",
        "phone": anzeige,
        "phoneUnformatted": telefon,
        "website": website,
        "categoryName": kategorie,
        "categories": [kategorie],
        "totalScore": bewertung,
        "reviewsCount": bewertungen,
        "permanentlyClosed": geschlossen,
        "temporarilyClosed": False,
        "url": "https://www.google.com/maps/search/?api=1&query=" + name,
    }


def _markt(**kw):
    return json.loads(server.marktanalyse(**kw))


def _b2b(**kw):
    return json.loads(server.b2b_leads(**kw))


def _letzte_eingabe():
    with STUB.sperre:
        return STUB.aufrufe[-1]


# ---------------------------------------------------------------------------
# Normalisierung und Slug (ohne HTTP, ohne DB)
# ---------------------------------------------------------------------------

def test_treffer_normalisierung_nimmt_die_internationale_nummer():
    """`phone` ist national notiert ("0941 …") und waere nach nummern.py
    unzustellbar — `phoneUnformatted` bringt die Landesvorwahl mit."""
    t = recherche.treffer_aus(_ort("Muster Makler"))
    assert t["telefon"] == "+499411234567"
    assert t["telefon_anzeige"] == "0941 1234567"
    assert t["name"] == "Muster Makler"
    assert t["adresse"].startswith("Beispielstrasse")
    assert t["kategorie"] == "Versicherungsmakler"
    assert t["bewertung"] == 4.5


def test_treffer_normalisierung_haelt_leere_felder_aus():
    t = recherche.treffer_aus({"title": "Ohne alles"})
    assert t["telefon"] == "" and t["website"] == "" and t["bewertung"] is None
    assert t["bewertungen"] == 0 and t["geschlossen"] is False


@pytest.mark.parametrize("roh", [
    "../../etc/passwd", "..\\windows\\system.ini", "C:pfad", "./../x",
    "Versicherungsmakler / Regensburg", "…", "..",
])
def test_slug_laesst_nur_kleinbuchstaben_und_ziffern_durch(roh):
    ergebnis = recherche.slug(roh)
    assert ergebnis
    assert all(c.islower() or c.isdigit() or c == "-" for c in ergebnis)
    assert "/" not in ergebnis and "\\" not in ergebnis
    assert "." not in ergebnis and ":" not in ergebnis


def test_slug_uebersetzt_umlaute():
    assert recherche.slug("Bäckerei Müßig", "Köln") == "baeckerei-muessig-koeln"


@pytest.mark.parametrize("wunsch, erwartet", [
    (20, 20), (50, 50), (51, 50), (999, 50), (0, 1), (-5, 1),
    (None, 20), ("viele", 20), ("10", 10),
])
def test_limit_wird_gekappt_statt_abgelehnt(wunsch, erwartet):
    assert recherche.kappe_limit(wunsch) == erwartet


def test_kosten_folgen_dem_gemessenen_ereignistarif():
    # $0.00005 Start + n x $0.004 je Treffer (FREE-Tarif, gemessen).
    assert recherche.kosten_usd(0) == 0.00005
    assert recherche.kosten_usd(10) == round(0.00005 + 0.04, 5)
    assert recherche.kosten_usd(50) == round(0.00005 + 0.2, 5)


# ---------------------------------------------------------------------------
# marktanalyse
# ---------------------------------------------------------------------------

def test_marktanalyse_schreibt_report_mit_allen_abschnitten():
    STUB.antworte_mit([
        _ort("Alpha Makler", bewertung=4.9, bewertungen=80),
        _ort("Beta Finanz", telefon="", anzeige="", website="",
             kategorie="Finanzberatung", bewertung=None, bewertungen=0),
        _ort("Gamma Vorsorge", telefon="+499419876543", geschlossen=True),
    ])
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg", limit=10)
    assert antwort["treffer"] == 3
    assert antwort["ueberschrieben"] is False
    inhalt = open(antwort["report"], encoding="utf-8").read()
    for abschnitt in ("# Marktanalyse: Versicherungsmakler in Regensburg",
                      "## Ueberblick", "## Cluster nach Kategorie",
                      "## Top-Bewertete", "## Auffaelligkeiten",
                      "## Alle Treffer"):
        assert abschnitt in inhalt, f"Abschnitt fehlt: {abschnitt}"
    # Quellenzeile mit Datum, Actor und Kosten.
    assert date.today().isoformat() in inhalt
    assert "compass/crawler-google-places" in inhalt
    assert "Kosten dieses Laufs" in inhalt
    # Inhalte aus der Normalisierung
    assert "Alpha Makler" in inhalt and "Finanzberatung" in inhalt
    assert "*(geschlossen)*" in inhalt


def test_marktanalyse_gibt_fuenf_zeilen_kurzfassung_und_pfad():
    STUB.antworte_mit([_ort(f"Makler {i}") for i in range(4)])
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert len(antwort["kurzfassung"]) == 5
    assert antwort["report"].endswith(
        f"versicherungsmakler-regensburg-{date.today().isoformat()}.md")


def test_marktanalyse_ohne_treffer_schreibt_keinen_report():
    STUB.antworte_mit([])
    antwort = _markt(thema="Nichts dergleichen", region="Regensburg")
    assert antwort["treffer"] == 0
    assert "report" not in antwort
    assert "keine Treffer" in antwort["hinweis"]


def test_marktanalyse_verwirft_zeilen_ohne_namen():
    """Der Actor legt bei erfolgloser Suche eine Hinweiszeile ohne `title` ab."""
    STUB.antworte_mit([{"searchString": "x", "error": "no_results"},
                       _ort("Echter Treffer")])
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert antwort["treffer"] == 1


def test_zweiter_lauf_am_selben_tag_meldet_das_ueberschreiben():
    STUB.antworte_mit([_ort("Alpha Makler")])
    erst = _markt(thema="Versicherungsmakler", region="Regensburg")
    zweit = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert erst["ueberschrieben"] is False
    assert zweit["ueberschrieben"] is True
    assert erst["report"] == zweit["report"]


def test_slug_traversal_landet_trotzdem_im_reportordner(tmp_path):
    STUB.antworte_mit([_ort("Alpha Makler")])
    antwort = _markt(thema="../../etc/passwd", region="../..")
    pfad = antwort["report"]
    wurzel = os.path.realpath(str(tmp_path / "reports"))
    assert os.path.dirname(os.path.realpath(pfad)) == wurzel
    assert ".." not in os.path.basename(pfad)
    assert os.path.basename(pfad).endswith(".md")


def test_report_ordner_fehlt_kostet_nicht_das_ergebnis(monkeypatch):
    """Ein bezahlter Lauf darf nicht an einem Schreibfehler verpuffen."""
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", "/proc/kein/ordner")
    STUB.antworte_mit([_ort("Alpha Makler")])
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert antwort["treffer"] == 1
    assert len(antwort["kurzfassung"]) == 5
    assert "Report konnte nicht abgelegt werden" in antwort["fehler"]


# ---------------------------------------------------------------------------
# Budget-Kanten
# ---------------------------------------------------------------------------

def test_limit_ueber_50_wird_beim_actor_gekappt():
    STUB.antworte_mit([_ort("Alpha Makler")])
    _markt(thema="Versicherungsmakler", region="Regensburg", limit=500)
    assert _letzte_eingabe()["eingabe"]["maxCrawledPlacesPerSearch"] == 50


def test_lauf_traegt_budgetdeckel_und_laufzeitgrenze():
    """Ohne `timeout` gaelte defaultRunOptions.timeoutSecs = 604800 (7 Tage);
    ohne `maxTotalChargeUsd` gaebe es keine Obergrenze fuer die Kosten."""
    STUB.antworte_mit([_ort("Alpha Makler")])
    _markt(thema="Versicherungsmakler", region="Regensburg")
    query = _letzte_eingabe()["query"]
    assert query["maxTotalChargeUsd"] == str(recherche.MAX_TOTAL_CHARGE_USD)
    assert query["timeout"] == str(recherche.LAUF_TIMEOUT_S)
    assert _letzte_eingabe()["pfad"].endswith(
        "/acts/compass~crawler-google-places/run-sync-get-dataset-items")


def test_keine_kostenpflichtigen_zusatzoptionen_im_eingang():
    """Filter und Anreicherungen kosten je Treffer extra (gemessen) — sie
    duerfen sich nicht unbemerkt einschleichen."""
    STUB.antworte_mit([_ort("Alpha Makler")])
    _markt(thema="Versicherungsmakler", region="Regensburg")
    eingabe = _letzte_eingabe()["eingabe"]
    for teuer in ("skipClosedPlaces", "placeMinimumStars", "website",
                  "categoryFilterWords", "searchMatching", "scrapeContacts",
                  "scrapePlaceDetailPage", "maxReviews", "maxImages"):
        assert teuer not in eingabe, f"kostenpflichtige Option gesetzt: {teuer}"
    assert eingabe["language"] == "de"


# ---------------------------------------------------------------------------
# Fehlerwege
# ---------------------------------------------------------------------------

def test_ohne_token_kein_http_und_sprechender_fehler(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "APIFY_TOKEN" in antwort["fehler"]
    with STUB.sperre:
        assert STUB.aufrufe == [], "Ohne Token darf keine Anfrage rausgehen."


def test_ohne_token_auch_bei_b2b_leads_kein_http(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    antwort = _b2b(branche="Handwerk", region="Regensburg")
    assert "APIFY_TOKEN" in antwort["fehler"]
    with STUB.sperre:
        assert STUB.aufrufe == []


@pytest.mark.parametrize("status", [402, 403, 429])
def test_apify_4xx_nennt_das_guthaben(status):
    STUB.status = status
    STUB.rumpf = b'{"error":{"type":"insufficient-usage","message":"..."}}'
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "Guthaben" in antwort["fehler"]
    assert str(status) in antwort["fehler"]


def test_apify_401_verweist_auf_den_token():
    STUB.status = 401
    STUB.rumpf = b'{"error":{"type":"token-not-found","message":"..."}}'
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "APIFY_TOKEN" in antwort["fehler"]


def test_apify_5xx_meldet_stoerung():
    STUB.status = 503
    STUB.rumpf = b'{"error":"upstream"}'
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "Stoerung" in antwort["fehler"] and "503" in antwort["fehler"]


def test_apify_unerreichbar_wird_zur_meldung(monkeypatch):
    monkeypatch.setattr(recherche, "APIFY_BASIS", "http://127.0.0.1:1/v2")
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "nicht erreichbar" in antwort["fehler"]


def test_fehlertext_traegt_nie_den_token(monkeypatch):
    """Fremde Fehlerrumpfe spiegeln Anfragen manchmal zurueck."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_GEHEIM")
    STUB.status = 400
    STUB.rumpf = b'{"error":"bad request for token apify_api_GEHEIM"}'
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "apify_api_GEHEIM" not in antwort["fehler"]
    assert "***" in antwort["fehler"]


def test_leere_suchbegriffe_gehen_gar_nicht_erst_raus():
    antwort = _markt(thema="   ", region="Regensburg")
    assert "Kein Suchbegriff" in antwort["fehler"]
    antwort = _markt(thema="Versicherungsmakler", region="")
    assert "Keine Region" in antwort["fehler"]
    with STUB.sperre:
        assert STUB.aufrufe == []


# ---------------------------------------------------------------------------
# b2b_leads
# ---------------------------------------------------------------------------

def test_b2b_leads_legt_kontakte_ohne_einwilligung_an():
    STUB.antworte_mit([_ort("Alpha GmbH"), _ort("Beta AG",
                                                telefon="+499419876543")])
    antwort = _b2b(branche="Handwerksbetrieb", region="Regensburg", limit=10)
    assert antwort["angelegt"] == 2
    assert antwort["erste_namen"] == ["Alpha GmbH", "Beta AG"]
    zeilen = server._q("select name, company, phone, source, consent_status, "
                       "notes from leads where source = 'recherche' "
                       "order by name")
    assert [z["name"] for z in zeilen] == ["Alpha GmbH", "Beta AG"]
    assert all(z["company"] == z["name"] for z in zeilen)
    assert all(z["consent_status"] == "unknown" for z in zeilen)
    # Internationale Schreibweise — die national notierte waere unzustellbar.
    assert zeilen[0]["phone"] == "+499411234567"
    for stichwort in ("Adresse:", "Website:", "Kategorie:", "Quelle:",
                      "NICHT per WhatsApp"):
        assert stichwort in zeilen[0]["notes"]


def test_b2b_leads_ueberspringt_bekannte_nummern():
    """Dieselbe Nummer in anderer Schreibweise — die Dedup-Kante aus
    kontakt_anlegen muss greifen, weil b2b_leads ueber sie geht."""
    server.kontakt_anlegen(name="Alpha GmbH", phone="0049 941 1234567",
                           source="whatsapp")
    STUB.antworte_mit([_ort("Alpha GmbH"), _ort("Beta AG",
                                                telefon="+499419876543")])
    antwort = _b2b(branche="Handwerksbetrieb", region="Regensburg")
    assert antwort["angelegt"] == 1
    assert antwort["uebersprungen_dublette"] == 1
    assert antwort["erste_namen"] == ["Beta AG"]
    assert server._q("select count(*) as n from leads")[0]["n"] == 3  # + Sammel-Lead


def test_b2b_leads_legt_ohne_nummer_keinen_lead_an():
    STUB.antworte_mit([_ort("Alpha GmbH", telefon="", anzeige=""),
                       _ort("Beta AG")])
    antwort = _b2b(branche="Handwerksbetrieb", region="Regensburg")
    assert antwort["angelegt"] == 1
    assert antwort["ohne_nummer"] == 1
    assert antwort["ohne_nummer_namen"] == ["Alpha GmbH"]
    assert server._q(
        "select count(*) as n from leads where name = 'Alpha GmbH'")[0]["n"] == 0


def test_b2b_leads_traegt_die_uwg_warnung_in_der_antwort():
    STUB.antworte_mit([_ort("Alpha GmbH")])
    antwort = _b2b(branche="Handwerksbetrieb", region="Regensburg")
    assert "UWG" in antwort["hinweis"] or "nicht per WhatsApp" in antwort["hinweis"]
    assert "Einwilligung" in antwort["hinweis"]


def test_b2b_leads_kappt_das_limit_ebenfalls():
    STUB.antworte_mit([_ort("Alpha GmbH")])
    _b2b(branche="Handwerksbetrieb", region="Regensburg", limit=100)
    assert _letzte_eingabe()["eingabe"]["maxCrawledPlacesPerSearch"] == 50


# ---------------------------------------------------------------------------
# Protokoll am Sammel-Lead
# ---------------------------------------------------------------------------

def test_marktanalyse_protokolliert_am_sammel_lead():
    STUB.antworte_mit([_ort("Alpha Makler")])
    _markt(thema="Versicherungsmakler", region="Regensburg", limit=7)
    zeilen = server._q("select type, payload, lead_id from activities")
    assert len(zeilen) == 1
    assert zeilen[0]["type"] == "recherche"
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["werkzeug"] == "marktanalyse"
    assert nutzlast["thema"] == "Versicherungsmakler"
    assert nutzlast["limit"] == 7 and nutzlast["treffer"] == 1
    assert str(zeilen[0]["lead_id"]) == recherche.RECHERCHE_LEAD_ID


def test_b2b_leads_protokolliert_suchparameter_und_zaehler():
    STUB.antworte_mit([_ort("Alpha GmbH"), _ort("Beta AG", telefon="",
                                                anzeige="")])
    _b2b(branche="Handwerksbetrieb", region="Regensburg", limit=5)
    nutzlast = server._q(
        "select payload from activities where type = 'recherche'")[0]["payload"]
    assert nutzlast["werkzeug"] == "b2b_leads"
    assert nutzlast["branche"] == "Handwerksbetrieb"
    assert nutzlast["region"] == "Regensburg" and nutzlast["limit"] == 5
    assert nutzlast["angelegt"] == 1 and nutzlast["ohne_nummer"] == 1
    assert nutzlast["uebersprungen_dublette"] == 0


def test_ohne_sammel_lead_kommt_ein_hinweis_statt_eines_fehlers(monkeypatch):
    monkeypatch.setattr(recherche, "RECHERCHE_LEAD_ID", "")
    STUB.antworte_mit([_ort("Alpha Makler")])
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert antwort["treffer"] == 1 and antwort["report"]
    assert "RECHERCHE_LEAD_ID" in antwort["protokoll"]
    assert server._q("select count(*) as n from activities")[0]["n"] == 0


def test_recherche_kontakte_verstopfen_den_digest_nicht():
    """Ein recherchierter Firmeneintrag hat nie ein Gespraech gefuehrt — er
    gehoert nicht in den Block „unvollstaendige Bedarfsanalysen" des
    Morgen-Digests, sonst verdraengt er dort die echten Kontakte."""
    server.kontakt_anlegen(name="Echte Kundin", phone="+491701234567",
                           source="whatsapp")
    STUB.antworte_mit([_ort("Alpha GmbH"), _ort("Beta AG",
                                                telefon="+499419876543")])
    _b2b(branche="Handwerksbetrieb", region="Regensburg")
    namen = [e["name"] for e in
             json.loads(server.digest())["unvollstaendige_bedarfsanalysen"]]
    assert namen == ["Echte Kundin"]


def test_werkzeug_signaturen_ueberleben_den_dekorator():
    """Ohne functools.wraps waere das MCP-Schema leer und kein Agent koennte
    die Werkzeuge aufrufen (Task-4-Vorfall)."""
    import inspect
    markt = inspect.signature(server.marktanalyse).parameters
    b2b = inspect.signature(server.b2b_leads).parameters
    assert "thema" in markt and "region" in markt and "limit" in markt
    assert "branche" in b2b and "region" in b2b and "limit" in b2b
    assert markt["region"].default == "Regensburg"
    assert b2b["limit"].default == recherche.LIMIT_VORGABE


def test_beide_werkzeuge_sind_registriert():
    namen = [f.__name__ for f in server.WERKZEUGE]
    assert "marktanalyse" in namen and "b2b_leads" in namen
    # Stufe 6: firma_anreichern kam dazu (tests/test_firma_anreichern.py).
    assert "firma_anreichern" in namen
    # Stufe 7: vertrag_speichern und vertraege_ablaufend (test_vertraege.py),
    # wochenbericht (test_wochenbericht.py) und uebergabe_erstellen
    # (test_uebergabe.py). Stufe 8: posteingang (test_posteingang.py).
    # Stufe 9: termin_bestaetigen (test_termin.py). Dazu die Kontakt-Freigabe
    # und der Auto-Betrieb: kontakt_freigeben, kontakt_freigabe_entziehen,
    # kontakte_freigegeben (test_kontakt_freigabe.py). Stufe 11:
    # eingang_einordnen und absender_aufloesen (test_einordnung.py,
    # test_lid.py). Kontaktpflege 21.08.2026: kontakt_archivieren und
    # kontakt_wiederherstellen (test_ui.py) — ein Loesch-Werkzeug gibt es
    # bewusst nicht, siehe dort. Betreiber-Wuensche 22.08.2026:
    # entwurf_verwerfen (test_verwerfen.py) sowie chat_reports_faellig,
    # chat_verlauf und chat_report_speichern (test_chat_report.py).
    # Updates per Bot-Anfrage 27.08.2026: update_anfordern und
    # update_ergebnis (test_auftraege.py) — bestellen ja, ausfuehren nie.
    # Dazu am selben Tag linkedin_versand_anfordern und
    # linkedin_versand_ergebnis (ebenfalls test_auftraege.py) sowie
    # kontakt_stufe_setzen (test_pipeline.py) und das DSGVO-Paar
    # kontakt_auskunft/loeschantrag_vermerken (test_dsgvo.py).
    assert len(namen) == len(set(namen)) == 58

# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Stufe-5-Review (Befunde T1, B2, D2)
# ---------------------------------------------------------------------------

def test_kaputte_basis_url_leakt_den_token_nicht(monkeypatch):
    """T1: eine Basis-URL ohne Schema laesst urlopen einen ValueError werfen,
    dessen Meldung die volle URL SAMT Token traegt. Vor der Nachbesserung
    entkam er ungefiltert aus _lauf — jetzt wird er zum Fehlertext, und
    _ohne_token filtert."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_GEHEIM")
    monkeypatch.setattr(recherche, "APIFY_BASIS", "api.apify.com/v2")  # kein http://
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "fehler" in antwort
    assert "apify_api_GEHEIM" not in antwort["fehler"]
    assert "nicht konstruierbar" in antwort["fehler"]


def test_steuerzeichen_im_actor_leaken_den_token_nicht(monkeypatch):
    """T1, zweiter gemessener Weg: InvalidURL (http.client) ist weder URLError
    noch OSError und nennt Pfad und Query inklusive Token."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_GEHEIM")
    monkeypatch.setattr(recherche, "ACTOR", "boese\nzeile")
    antwort = _markt(thema="Versicherungsmakler", region="Regensburg")
    assert "fehler" in antwort
    assert "apify_api_GEHEIM" not in antwort["fehler"]


@pytest.mark.parametrize("lauf,http,erwartet", [
    (150, 180.0, 150),   # Vorgabe: bleibt
    (240, 180.0, 150),   # der .env.example-Fehlkonfig-Fall: gekappt
    (9999, 180.0, 150),  # beliebig gross: gekappt
    (60, 180.0, 60),     # kleiner geht immer
    (150, 20.0, 1),      # absurdes HTTP-Timeout: Deckel bleibt > 0
])
def test_lauf_deckel_erzwingt_die_reihenfolge(lauf, http, erwartet):
    """B2: LAUF < HTTP ist die Kern-Invariante des Moduls („bezahlt, aber
    nichts bekommen" ausgeschlossen) — Konstruktion, nicht Konvention."""
    assert recherche._lauf_deckel(lauf, http) == erwartet


def test_dublette_laesst_den_bestandslead_unangetastet():
    """D2: das company-Nachtrags-UPDATE darf nur den FRISCH angelegten Lead
    treffen. Eine Mutation, die es auch im Dublettenfall ausfuehrt, wuerde
    einen fremden Bestandslead ueberschreiben — dieser Test beisst dann."""
    server.kontakt_anlegen(name="Alpha Ansprechpartner",
                           phone="0049 941 1234567", source="whatsapp")
    STUB.antworte_mit([_ort("Alpha GmbH")])
    antwort = _b2b(branche="Handwerksbetrieb", region="Regensburg")
    assert antwort["uebersprungen_dublette"] == 1
    # Suche ueber den Namen: kontakt_anlegen speichert die Nummer in der
    # Schreibweise des Aufrufers, die Dedup-Kante vergleicht normalisiert.
    bestand = server._q("select company, source from leads "
                        "where name = 'Alpha Ansprechpartner'")[0]
    assert bestand["company"] is None
    assert bestand["source"] == "whatsapp"
