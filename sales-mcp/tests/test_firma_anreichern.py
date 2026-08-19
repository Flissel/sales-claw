"""Vertragstests fuer `firma_anreichern` gegen sales_test + Website-Stub.

Wie test_recherche.py: die Suite laeuft NIE gegen `sales` und spricht NIE mit
einer echten Website. Der Ersatz ist ein `http.server`-Thread auf einem vom
Betriebssystem vergebenen Port, der eine kleine Handwerker-Website mit
Impressum-Link ausliefert — nachgebaut nach den vier echten Lead-Websites, die
fuer die Messentscheidung abgerufen wurden (statisches HTML, Impressum von der
Startseite verlinkt).

Ein Unterschied zu test_recherche.py ist wichtig: `firma_anreichern` geht NICHT
ueber Apify, es holt die Seiten selbst. Es gibt hier also kein Guthaben zu
schuetzen — wohl aber die Kante, die das Werkzeug ueberhaupt erst zulaessig
macht: es arbeitet ausschliesslich auf Kontakten mit `company`.
"""
import json
import os
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import recherche  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# Website-Stub
# ---------------------------------------------------------------------------

def _html(titel: str, rumpf: str) -> bytes:
    return (f"<!doctype html><html><head><title>{titel}</title>"
            f"<style>body{{color:red}}</style>"
            f"<script>var x = 'BITTE NICHT ALS TEXT LESEN';</script>"
            f"</head><body>{rumpf}</body></html>").encode("utf-8")


# Die Startseite verlinkt absichtlich mehr als die vier Unterseiten, die
# hoechstens geholt werden duerfen — plus einen fremden Auftritt und
# nicht-holbare Schemata (mailto:/tel:/#), die alle aussen vor bleiben muessen.
_START = _html("Muster Haustechnik GmbH", """
  <nav>
    <a href="/impressum/">Impressum</a>
    <a href="ueber-uns.html">&Uuml;ber uns</a>
    <a href="/kontakt">Kontakt</a>
    <a href="/leistungen">Leistungen</a>
    <a href="/service/wartung">Wartung</a>
    <a href="/referenzen">Referenzen</a>
    <a href="/team/">Team</a>
    <a href="https://www.facebook.com/musterhaustechnik">Facebook</a>
    <a href="mailto:info@muster-haustechnik.de">Mail</a>
    <a href="tel:+499411234567">Anrufen</a>
    <a href="#oben">nach oben</a>
  </nav>
  <h1>Muster Haustechnik GmbH</h1>
  <p>Heizung, Sanitaer und Klima aus Regensburg.</p>
""")

# Schreibweise mit echten Umlauten — so steht es auf den allermeisten
# Impressum-Seiten. Die Umschreibung („Geschaeftsfuehrer") kommt daneben vor
# und wird von test_vertretung_auch_in_umschriebener_schreibweise geprueft.
_IMPRESSUM = _html("Impressum", """
  <h1>Impressum</h1>
  <p>Muster Haustechnik GmbH<br>Musterstrasse 1, 93047 Regensburg</p>
  <p>Gesch&auml;ftsf&uuml;hrer: Denis Mustermann<br>
     Telefon: +49 941 1234567</p>
  <p>Registergericht: Amtsgericht Regensburg, HRB 12345</p>
""")

_UEBER_UNS = _html("Ueber uns", """
  <h1>Ueber uns</h1>
  <p>Unser Familienbetrieb besteht seit 1998 und wird in zweiter Generation
     gefuehrt. Heute arbeiten 24 Mitarbeiter fuer unsere Kunden.</p>
""")

_SEITEN = {
    "/": _START,
    "/impressum/": _IMPRESSUM,
    "/ueber-uns.html": _UEBER_UNS,
    "/kontakt": _html("Kontakt", "<p>Rufen Sie uns an.</p>"),
    "/leistungen": _html("Leistungen", "<p>Heizungswartung, Bad, Klima.</p>"),
    "/service/wartung": _html("Wartung", "<p>Wartungsvertraege.</p>"),
    "/referenzen": _html("Referenzen", "<p>Projekte.</p>"),
    "/team/": _html("Team", "<p>Unsere Leute.</p>"),
}


class _Stub:
    def __init__(self):
        self.aufrufe = []
        self.sperre = threading.Lock()
        self.weiterleitung = None       # (von_pfad, ziel_url) oder None
        self.status_erzwungen = None    # z. B. 403 fuer alle Seiten

    def zuruecksetzen(self):
        with self.sperre:
            self.aufrufe.clear()
        self.weiterleitung = None
        self.status_erzwungen = None

    @property
    def pfade(self):
        with self.sperre:
            return list(self.aufrufe)


STUB = _Stub()
STUB_BASIS = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        with STUB.sperre:
            STUB.aufrufe.append(self.path)
        if STUB.weiterleitung and self.path == STUB.weiterleitung[0]:
            self.send_response(302)
            self.send_header("Location", STUB.weiterleitung[1])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if STUB.status_erzwungen:
            self.send_response(STUB.status_erzwungen)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rumpf = _SEITEN.get(self.path)
        if rumpf is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    global STUB_BASIS
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.daemon_threads = True
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    STUB_BASIS = f"http://127.0.0.1:{dienst.server_address[1]}"
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch):
    # Der Stub laeuft auf 127.0.0.1 — im Betrieb weist `_ziel_erlaubt` genau
    # dorthin ab (SSRF-Kante). Die Kante wird hier NICHT entfernt, sondern
    # ueber ihr Modulattribut geoeffnet; dass sie im Vorgabezustand greift,
    # prueft test_private_adressen_werden_abgewiesen weiter unten.
    monkeypatch.setattr(recherche, "FIRMA_PRIVATE_ZIELE_ERLAUBT", True)
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
# Helfer
# ---------------------------------------------------------------------------

def _firmenlead(name="Muster Haustechnik GmbH", website=None, notes=None):
    """Ein Firmenkontakt, wie b2b_leads ihn anlegt (name == company)."""
    if notes is None:
        adresse = STUB_BASIS + "/" if website is None else website
        notes = recherche.lead_notiz(
            {"adresse": "Musterstrasse 1", "website": adresse,
             "kategorie": "Heizungsmonteur", "bewertung": 5.0,
             "bewertungen": 31},
            "Handwerksbetrieb", "Regensburg")
    return str(server._q(
        "insert into leads (name, company, phone, source, notes, consent_status) "
        "values (%s, %s, '+499411234567', 'recherche', %s, 'unknown') "
        "returning id", (name, name, notes))[0]["id"])


def _personenlead(name="Lisa Probekunde"):
    """Ein Kundenkontakt — company bleibt NULL."""
    return json.loads(server.kontakt_anlegen(
        name=name, phone="+491701234567", source="whatsapp"))["lead_id"]


def _anreichern(**kw):
    return json.loads(server.firma_anreichern(**kw))


def _enrichment(lead_id):
    return server._q("select enrichment from leads where id = %s",
                     (lead_id,))[0]["enrichment"]


# ---------------------------------------------------------------------------
# Die Kante: nur Firmenkontakte — und zwar VOR jedem HTTP
# ---------------------------------------------------------------------------

def test_personenkontakt_wird_abgewiesen_ohne_jeden_abruf():
    """Der Kern des Werkzeugs. Kein Personen-Scraping heisst hier nicht
    „das Modell soll es lassen", sondern: es kommt gar nicht erst dazu."""
    lead = _personenlead()
    antwort = _anreichern(lead_id=str(lead))
    assert "nur fuer Firmenkontakte" in antwort["fehler"].replace(
        "ausschliesslich fuer", "nur fuer")
    assert "Bedarfsanalyse" in antwort["fehler"]
    assert STUB.pfade == [], "Fuer einen Personenkontakt darf nichts rausgehen."


def test_personenkontakt_wird_auch_mit_uebergebener_website_abgewiesen():
    """Die Kante haengt am Kontakt, nicht an der fehlenden Adresse — sonst
    liesse sie sich durch Mitliefern der URL umgehen."""
    lead = _personenlead()
    antwort = _anreichern(lead_id=str(lead), website=STUB_BASIS + "/")
    assert "fehler" in antwort
    assert STUB.pfade == []


def test_leerer_firmeneintrag_zaehlt_nicht_als_firma():
    """company = '   ' ist kein Firmenkontakt."""
    lead = str(server._q(
        "insert into leads (name, company, source) values "
        "('Leerfirma', '   ', 'recherche') returning id")[0]["id"])
    antwort = _anreichern(lead_id=lead)
    assert "fehler" in antwort
    assert STUB.pfade == []


def test_unbekannte_lead_id_meldet_das_und_ruft_nichts_ab():
    antwort = _anreichern(lead_id="00000000-0000-0000-0000-000000000000")
    assert "Kein Kontakt" in antwort["fehler"]
    assert STUB.pfade == []


# ---------------------------------------------------------------------------
# Adressermittlung
# ---------------------------------------------------------------------------

def test_ohne_auffindbare_website_kommt_ein_sprechender_fehler():
    lead = _firmenlead(notes="Adresse: Musterstrasse 1 | Website: keine")
    antwort = _anreichern(lead_id=lead)
    assert "keine Website hinterlegt" in antwort["fehler"]
    assert "firma_anreichern(lead_id, website=" in antwort["fehler"]
    assert STUB.pfade == []


def test_website_wird_aus_der_notizzeile_von_b2b_leads_gelesen():
    """b2b_leads schreibt „Website: …" in notes — genau die Zeile wird hier
    wieder gelesen (recherche.lead_notiz ist der Schreiber)."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert antwort["seiten_anzahl"] >= 1
    assert "/" in STUB.pfade


@pytest.mark.parametrize("roh", ["keine", "unbekannt", "-", "n/a", "  "])
def test_platzhalter_in_der_notiz_gelten_als_keine_website(roh):
    assert recherche.website_aus_notiz(f"Adresse: X | Website: {roh} | K: Y") == ""


def test_parameter_schlaegt_notiz_und_gespeicherte_adresse():
    lead = _firmenlead(website="https://beispiel-existiert-nicht.invalid/")
    antwort = _anreichern(lead_id=lead, website=STUB_BASIS + "/")
    assert "fehler" not in antwort
    assert antwort["website"].startswith(STUB_BASIS)


def test_zweiter_lauf_nimmt_die_gespeicherte_adresse_ohne_parameter():
    """Nach dem ersten Lauf steht die Adresse in enrichment.firma.website —
    ein Folgeaufruf braucht weder Parameter noch Notiz."""
    lead = _firmenlead(notes="Adresse: Musterstrasse 1 | Website: keine")
    erst = _anreichern(lead_id=lead, website=STUB_BASIS + "/")
    assert "fehler" not in erst
    STUB.zuruecksetzen()
    zweit = _anreichern(lead_id=lead)
    assert "fehler" not in zweit
    assert zweit["website"].startswith(STUB_BASIS)
    assert "/" in STUB.pfade


# ---------------------------------------------------------------------------
# Erfolgsfall
# ---------------------------------------------------------------------------

def test_erfolgsfall_schreibt_enrichment_firma_und_aktivitaet():
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)

    assert antwort["seiten_anzahl"] == 5
    assert antwort["kosten_usd"] == 0.0
    assert len(antwort["kurzfassung"]) == 5

    firma = _enrichment(lead)["firma"]
    assert firma["website"].startswith(STUB_BASIS)
    assert firma["stand"] == date.today().isoformat()
    assert len(firma["seiten"]) == 5
    typen = {s["typ"] for s in firma["seiten"]}
    assert "impressum" in typen and "ueber_uns" in typen
    for seite in firma["seiten"]:
        assert set(seite) == {"url", "typ", "titel", "text", "status", "bytes"}
        assert seite["status"] == 200

    # Aktivitaet AM Firmenlead (nicht nur am Sammelkontakt).
    am_lead = server._q(
        "select type, payload from activities where lead_id = %s", (lead,))
    assert len(am_lead) == 1
    assert am_lead[0]["type"] == "recherche"
    assert am_lead[0]["payload"]["werkzeug"] == "firma_anreichern"
    assert am_lead[0]["payload"]["seiten_anzahl"] == 5
    assert am_lead[0]["payload"]["kosten_usd"] == 0.0

    # Und zusaetzlich am Sammelkontakt (Muster marktanalyse/b2b_leads).
    am_sammel = server._q(
        "select payload from activities where lead_id = %s",
        (recherche.RECHERCHE_LEAD_ID,))
    assert len(am_sammel) == 1
    assert am_sammel[0]["payload"]["werkzeug"] == "firma_anreichern"
    assert am_sammel[0]["payload"]["name"] == "Muster Haustechnik GmbH"


def test_impressum_wird_gelesen_und_die_angaben_stehen_in_der_kurzfassung():
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    zusammen = " ".join(antwort["kurzfassung"])
    assert "Denis Mustermann" in zusammen         # Geschaeftsfuehrer, Impressum
    assert "1998" in zusammen                     # „besteht seit 1998"
    assert "24" in zusammen                       # „24 Mitarbeiter"
    hinweise = _enrichment(lead)["firma"]["hinweise"]
    assert hinweise["vertretung"] == "Denis Mustermann"
    assert hinweise["seit_jahr"] == 1998
    assert hinweise["mitarbeiter_genannt"] == 24
    assert hinweise["handelsregister"] == "HRB 12345"


def test_skript_und_stil_landen_nicht_im_text():
    """Sonst stuende der halbe JavaScript-Quelltext in leads.enrichment."""
    lead = _firmenlead()
    _anreichern(lead_id=lead)
    volltext = " ".join(s["text"] for s in _enrichment(lead)["firma"]["seiten"])
    assert "BITTE NICHT ALS TEXT LESEN" not in volltext
    assert "color:red" not in volltext
    assert "Heizung, Sanitaer und Klima" in volltext


def test_navigationstext_landet_nicht_im_text():
    """Der Menueblock steht auf jeder Unterseite identisch (Live-Messung
    pfeifer-haustechnik.de: rund 450 Zeichen, ~22 % von FIRMA_TEXT_MAX je
    Seite) und traegt nichts, was _firma_hinweise sucht. Die Links aus <nav>
    muessen aber weiter verfolgt werden — sonst faende das Werkzeug keine
    Unterseiten mehr."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    seiten = _enrichment(lead)["firma"]["seiten"]
    start = next(s for s in seiten if s["url"].rstrip("/") == STUB_BASIS)
    assert "nach oben" not in start["text"]              # Ankertext aus <nav>
    assert "Anrufen" not in start["text"]
    assert "Heizung, Sanitaer und Klima" in start["text"]  # <body> bleibt
    assert antwort["seiten_anzahl"] == 5                 # <nav>-Links verfolgt


def test_profil_lesen_zeigt_den_volltext_unter_firma():
    """Das Werkzeug verspricht in seiner Antwort, profil_lesen zeige den
    Volltext — dieser Test haelt das Versprechen ueberpruefbar."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert "profil_lesen" in antwort["hinweis"]
    profil = json.loads(server.profil_lesen(lead))
    assert profil["firma"]["website"].startswith(STUB_BASIS)
    assert any("Denis Mustermann" in s["text"] for s in profil["firma"]["seiten"])


def test_ohne_anreicherung_bleibt_firma_im_profil_leer():
    lead = _firmenlead()
    assert json.loads(server.profil_lesen(lead))["firma"] == {}


# ---------------------------------------------------------------------------
# Kappung und Auswahl der Unterseiten
# ---------------------------------------------------------------------------

def test_hoechstens_fuenf_seiten_werden_geholt():
    """Die Startseite verlinkt acht passende Unterseiten — geholt werden
    Startseite + vier."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert antwort["seiten_anzahl"] == recherche.FIRMA_MAX_SEITEN == 5
    assert len(STUB.pfade) == 5, f"zu viele Abrufe: {STUB.pfade}"


def test_impressum_hat_vorrang_vor_den_uebrigen_unterseiten():
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    typen = [s["typ"] for s in antwort["gelesene_seiten"]]
    assert typen[0] == "sonstige"          # die Startseite selbst
    assert typen[1] == "impressum"         # danach zuerst das Impressum
    assert "ueber_uns" in typen and "kontakt" in typen


def test_fremde_auftritte_und_nicht_holbare_verweise_bleiben_aussen_vor():
    """Facebook, mailto:, tel: und Anker duerfen nicht mitgelesen werden —
    das Werkzeug liest die Website DIESER Firma, sonst nichts."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    for seite in antwort["gelesene_seiten"]:
        assert seite["url"].startswith(STUB_BASIS)
    assert all("facebook" not in p for p in STUB.pfade)


def test_kaputte_unterseite_kostet_nicht_das_ganze_ergebnis(monkeypatch):
    """Eine 404-Unterseite wird gemeldet, der Rest kommt trotzdem zurueck."""
    monkeypatch.setitem(
        _SEITEN, "/",
        _html("Muster Haustechnik GmbH",
              '<a href="/impressum/">Impressum</a>'
              '<a href="/gibt-es-nicht-kontakt">Kontakt</a>'))
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert antwort["seiten_anzahl"] == 2          # Start + Impressum
    assert any("gibt-es-nicht" in u for u in antwort["nicht_gelesen"])
    assert _enrichment(lead)["firma"]["seiten"]


def test_startseite_nicht_erreichbar_ist_ein_fehler_ohne_ablage():
    lead = _firmenlead(website=STUB_BASIS + "/gibt-es-nicht/")
    antwort = _anreichern(lead_id=lead)
    assert "404" in antwort["fehler"]
    assert _enrichment(lead) == {}, "Bei einem Fehler wird nichts abgelegt."
    assert server._q("select count(*) as n from activities where lead_id = %s",
                     (lead,))[0]["n"] == 0


def test_aussperrender_server_wird_gemeldet_statt_umgangen():
    """403 heisst 403. Es wird nichts getarnt und nichts erneut versucht."""
    STUB.status_erzwungen = 403
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert "403" in antwort["fehler"]
    assert "von Hand" in antwort["fehler"]


def test_text_wird_auf_die_obergrenze_gekuerzt(monkeypatch):
    monkeypatch.setattr(recherche, "FIRMA_TEXT_MAX", 50)
    monkeypatch.setitem(_SEITEN, "/", _html("Lang", "<p>" + "wort " * 400 + "</p>"))
    lead = _firmenlead()
    _anreichern(lead_id=lead)
    for seite in _enrichment(lead)["firma"]["seiten"]:
        assert len(seite["text"]) <= 50


# ---------------------------------------------------------------------------
# Haertung: SSRF, Weiterleitungen, Schemata, Token
# ---------------------------------------------------------------------------

def test_private_adressen_werden_abgewiesen(monkeypatch):
    """Die Adresse stammt aus einem Google-Maps-Datensatz, also aus fremder
    Hand. Ein Eintrag auf 127.0.0.1 wuerde diesen Container gegen seine
    eigenen Dienste laufen lassen — im selben Netz haengt Postgres."""
    monkeypatch.setattr(recherche, "FIRMA_PRIVATE_ZIELE_ERLAUBT", False)
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    # Der Stub laeuft auf 127.0.0.1:<zufallsport> — im Vorgabezustand greift
    # je nach Adresse die Port-Kante (kein 80/443) oder die
    # is_global-Pruefung. Beides ist dieselbe Abweisung.
    assert "wird nicht abgerufen" in antwort["fehler"]
    assert ("geroutete" in antwort["fehler"] or "Port" in antwort["fehler"])
    assert STUB.pfade == [], "Es darf nicht einmal verbunden werden."


@pytest.mark.parametrize("adresse", [
    "file:///etc/passwd", "ftp://beispiel.de/x", "javascript:alert(1)",
    "gopher://beispiel.de/",
])
def test_nur_http_und_https_werden_abgerufen(adresse):
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead, website=adresse)
    assert "http" in antwort["fehler"]
    assert STUB.pfade == []


@pytest.mark.parametrize("adresse", [
    "http://127.0.0.1:8765/", "http://10.0.0.5/", "http://192.168.178.1/",
    "http://[::1]/", "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/",
])
def test_ziel_pruefung_weist_private_adressen_ab(adresse, monkeypatch):
    """169.254.169.254 ist kein willkuerliches Beispiel — das ist der
    Metadaten-Dienst der grossen Cloud-Anbieter, das klassische SSRF-Ziel."""
    monkeypatch.setattr(recherche, "FIRMA_PRIVATE_ZIELE_ERLAUBT", False)
    erlaubt, grund = recherche._ziel_erlaubt(adresse)
    # "keine oeffentlich geroutete Adresse" (is_global-Pruefung) oder die
    # Port-Kante (127.0.0.1:8765) — beides weist ab, bevor verbunden wird.
    assert not erlaubt and ("geroutete" in grund or "Port" in grund)


def test_weiterleitung_ins_private_netz_wird_abgewiesen(monkeypatch):
    """Ohne Pruefung JEDES Sprungs waere die Adresspruefung wertlos: eine
    oeffentlich erreichbare Seite darf mit HTTP 302 auf 127.0.0.1 zeigen, und
    urllib folgt von sich aus. Geprueft wird der Weiterleitungspruefer selbst
    — ein echter Sprung braeuchte einen oeffentlichen Namen im Netz."""
    monkeypatch.setattr(recherche, "FIRMA_PRIVATE_ZIELE_ERLAUBT", False)
    pruefer = recherche._GepruefteWeiterleitung()
    with pytest.raises(recherche._ZielAbgewiesen) as fehler:
        pruefer.redirect_request(None, None, 302, "Found", {},
                                 "http://127.0.0.1:8765/")
    assert ("geroutete" in str(fehler.value) or "Port" in str(fehler.value))


def test_vertretung_auch_in_umschriebener_schreibweise():
    """Im Netz stehen beide Schreibweisen; eine Regel, die nur Umlaute kennt,
    findet die halbe Wirklichkeit nicht."""
    for form in ("Geschäftsführer: Denis Mustermann",
                 "Geschaeftsfuehrer: Denis Mustermann",
                 "Inhaber: Denis Mustermann",
                 "Vertreten durch: Denis Mustermann"):
        seiten = [{"typ": "impressum", "text": f"Muster GmbH {form} Telefon: 1"}]
        assert recherche._firma_hinweise(seiten).get("vertretung") == \
            "Denis Mustermann", form


def test_weiterleitung_innerhalb_der_website_wird_gefolgt():
    """Gemessen an echten Seiten: www.koller-ht.de leitet auf koller-ht.de
    und / auf /startseite.html — ohne Folgen gaebe es keinen Text."""
    STUB.weiterleitung = ("/start", STUB_BASIS + "/")
    lead = _firmenlead(website=STUB_BASIS + "/start")
    antwort = _anreichern(lead_id=lead)
    assert "fehler" not in antwort
    assert antwort["website"].endswith("/")
    assert "/start" in STUB.pfade and "/" in STUB.pfade


def test_der_direkte_weg_braucht_keinen_apify_token(monkeypatch):
    """Die Messentscheidung in Zahlen: dieses Werkzeug kostet nichts und
    haengt an keinem Fremddienst. Ohne Token laeuft es unveraendert."""
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert "fehler" not in antwort
    assert antwort["seiten_anzahl"] == 5
    assert antwort["kosten_usd"] == 0.0


def test_fehlertext_traegt_nie_den_token(monkeypatch):
    """Steht der Token je in einer abgerufenen Adresse, darf er nicht ueber
    den Fehlertext in Chat und Log wandern (Muster aus _lauf)."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_GEHEIM")
    lead = _firmenlead(website=STUB_BASIS + "/apify_api_GEHEIM/weg")
    antwort = _anreichern(lead_id=lead)
    assert "apify_api_GEHEIM" not in antwort["fehler"]
    assert "***" in antwort["fehler"]


def test_kaputte_adresse_leakt_den_token_nicht(monkeypatch):
    """T1, hier auf dem Direkt-Weg: Steuerzeichen im Pfad -> InvalidURL
    (http.client.HTTPException), deren Meldung die volle Adresse nennt."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_GEHEIM")
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead,
                          website=STUB_BASIS + "/boese\nzeile?t=apify_api_GEHEIM")
    assert "fehler" in antwort
    assert "apify_api_GEHEIM" not in antwort["fehler"]


def test_grosse_seiten_werden_beim_lesen_gedeckelt(monkeypatch):
    monkeypatch.setattr(recherche, "FIRMA_BYTES_MAX", 500)
    lead = _firmenlead()
    _anreichern(lead_id=lead)
    for seite in _enrichment(lead)["firma"]["seiten"]:
        assert seite["bytes"] <= 500


# ---------------------------------------------------------------------------
# Registrierung und Signatur
# ---------------------------------------------------------------------------

def test_signatur_ueberlebt_den_dekorator():
    """Ohne functools.wraps waere das MCP-Schema leer (Task-4-Vorfall)."""
    import inspect
    parameter = inspect.signature(server.firma_anreichern).parameters
    assert list(parameter) == ["lead_id", "website"]
    assert parameter["website"].default == ""


def test_werkzeug_ist_registriert():
    assert server.firma_anreichern in server.WERKZEUGE
    namen = [f.__name__ for f in server.WERKZEUGE]
    assert namen.count("firma_anreichern") == 1


# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Review (Befunde S2/S3/S4, R1, G1, H1 + E2E-Redirect)
# ---------------------------------------------------------------------------

def test_kaputtes_ipv6_literal_gibt_fehlertext_statt_traceback():
    """S4: urlsplit wirft bei 'http://[::1' einen ValueError — vor der
    Nachbesserung verliess er firma_daten als Traceback."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead, website="http://[::1")
    assert "fehler" in antwort
    assert "nicht lesbar" in antwort["fehler"]
    assert STUB.pfade == []


def test_kaputter_verweis_auf_der_seite_stuerzt_nicht_ab(monkeypatch):
    """S4, zweite Fundstelle: ein wirrer Link im HTML der FREMDEN Seite darf
    das Werkzeug nicht abbrechen — er wird uebersprungen."""
    seite = _html("Kaputt", '<a href="http://[::1">defekt</a>'
                            '<a href="/impressum/">Impressum</a>')
    monkeypatch.setitem(_SEITEN, "/kaputt", seite)
    daten, fehler = recherche.firma_daten(STUB_BASIS + "/kaputt")
    assert fehler is None
    assert any("/impressum" in s["url"] for s in daten["seiten"])


@pytest.mark.parametrize("ziel,grund_teil", [
    ("http://100.64.0.1/", "geroutete"),          # CGNAT — S2
    ("http://192.0.2.1/", "geroutete"),           # TEST-NET — nur is_global
    ("http://example.com:5432/", "Port 5432"),    # Dienstport — S3
    ("http://example.com:22/", "Port 22"),
])
def test_nicht_globale_ziele_und_dienstports_werden_abgewiesen(
        monkeypatch, ziel, grund_teil):
    monkeypatch.setattr(recherche, "FIRMA_PRIVATE_ZIELE_ERLAUBT", False)
    erlaubt, grund = recherche._ziel_erlaubt(ziel)
    assert erlaubt is False
    assert grund_teil in grund


def test_latin1_impressum_ohne_header_charset_verliert_den_fund_nicht(monkeypatch):
    """R1: aeltere Seiten liefern ISO-8859-1 ohne charset im Header und
    nennen ihn nur im <meta>. Vorher: Mojibake, kein Vertretungs-Fund."""
    rumpf = ("<!doctype html><html><head>"
             '<meta charset="iso-8859-1"><title>Impressum</title></head>'
             "<body><p>Geschäftsführer: Jörg Müller</p>"
             "</body></html>").encode("iso-8859-1")

    def antworte(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html")   # KEIN charset
        handler.send_header("Content-Length", str(len(rumpf)))
        handler.end_headers()
        handler.wfile.write(rumpf)

    urspruenglich = _Handler.do_GET

    def do_get(handler):
        if handler.path == "/latin1":
            with STUB.sperre:
                STUB.aufrufe.append(handler.path)
            antworte(handler)
        else:
            urspruenglich(handler)

    monkeypatch.setattr(_Handler, "do_GET", do_get)
    seite, fehler = recherche._hole_seite(STUB_BASIS + "/latin1")
    assert fehler is None
    assert "Geschäftsführer: Jörg Müller" in seite["text"]
    hinweise = recherche._firma_hinweise([seite])
    assert hinweise["vertretung"] == "Jörg Müller"


def test_team_seite_wird_nicht_gelesen():
    """G1: eine Team-Seite ist eine Namensliste von Beschaeftigten —
    Personendaten, die dieses Werkzeug nicht erhebt. Der Link liegt auf der
    Stub-Startseite bereit; er darf nicht abgerufen werden."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    assert "fehler" not in antwort
    assert all("/team" not in p for p in STUB.pfade), STUB.pfade
    typen = {s["typ"] for s in _enrichment(lead)["firma"]["seiten"]}
    assert "leistungen" in typen           # der Nachruecker fuer team


def test_mehrdeutige_jahresangaben_werden_nicht_zur_falschen_zahl(monkeypatch):
    """H1: 'seit 1985 verbaute Anlagen' (Werbetext) gegen 'besteht seit
    2004' — vorher gewann min() und die Kurzfassung behauptete 1985."""
    seite = {"url": "https://x.de/", "typ": "ueber_uns", "titel": "x",
             "text": ("Wir arbeiten seit 1985 verbaute Anlagen auf und "
                      "unser Betrieb besteht seit 2004."),
             "status": 200, "bytes": 1}
    hinweise = recherche._firma_hinweise([seite])
    assert "seit_jahr" not in hinweise
    assert hinweise["seit_jahr_kandidaten"] == [1985, 2004]
    zeilen = recherche.firma_kurzfassung("X GmbH", {
        "website": "https://x.de/", "seiten": [seite], "hinweise": hinweise})
    assert any("uneindeutig (1985, 2004)" in z for z in zeilen)
    assert not any("Am Markt" in z and "1985" in z for z in zeilen)


def test_eindeutige_angaben_werden_mit_herkunft_genannt():
    """H1, Gegenprobe: ein eindeutiger Fund bleibt ein Fund — aber die
    Kurzfassung nennt die Herkunft ('laut Website')."""
    lead = _firmenlead()
    antwort = _anreichern(lead_id=lead)
    zusammen = " ".join(antwort["kurzfassung"])
    assert "Laut Website am Markt seit 1998" in zusammen
    assert "laut Website 24 Mitarbeitende" in zusammen


def test_weiterleitung_wird_im_echten_opener_abgefangen(monkeypatch):
    """E2E-Luecke aus dem Review: der bisherige Test rief redirect_request
    direkt auf — hier laeuft der Sprung durch build_opener/oeffner.open, und
    die Abweisung muss als Fehlertext ankommen, nicht als Ausnahme."""
    echt = recherche._ziel_erlaubt

    def waechter(url):
        if "boese.invalid" in url:
            return False, "Testziel gesperrt."
        return echt(url)

    monkeypatch.setattr(recherche, "_ziel_erlaubt", waechter)
    STUB.weiterleitung = ("/", "http://boese.invalid/")
    daten, fehler = recherche.firma_daten(STUB_BASIS + "/")
    assert daten is None
    assert "Weiterleitung abgewiesen" in fehler
    assert STUB.pfade == ["/"], "dem Sprungziel darf nie nachgegangen werden"


def test_zweiter_lauf_ersetzt_den_stand_vollstaendig(monkeypatch):
    """Review-Restpunkt: jsonb_set ersetzt den Knoten — ein Schluessel aus
    Lauf 1 darf Lauf 2 nicht ueberleben."""
    lead = _firmenlead()
    _anreichern(lead_id=lead)
    server._q("update leads set enrichment = jsonb_set(enrichment, "
              "'{firma,marker_aus_lauf_1}', '\"bleibt nicht\"'::jsonb, true) "
              "where id = %s returning id", (lead,))
    _anreichern(lead_id=lead)
    firma = _enrichment(lead)["firma"]
    assert "marker_aus_lauf_1" not in firma
    assert "nicht_gelesen" in firma        # neuer Bestandteil der Ablage
