"""Vertragstests der LID-Aufloesung (Stufe 11, T2) gegen sales_test + HTTP-Stub.

Wie test_dispatch.py: die Suite laeuft NIE gegen `sales`, und der OpenWA-Ersatz
ist ein echter `http.server`-Thread auf einem vom Betriebssystem vergebenen
Port — kein gemocktes `urlopen`. Gemessen wird damit das, worauf es ankommt:
WELCHE URL rausgeht (das `@lid`-Suffix ist Pflicht und muss kodiert sein) und
WAS aus welchem Statuscode geschlossen wird (429 sagt nichts ueber die
Kennung).

Es geht in diesen Tests zu keinem Zeitpunkt eine WhatsApp-Nachricht raus.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest

# HART, nicht setdefault (wie test_dispatch/test_inbox): eine von aussen
# gesetzte SALES_DB_SCHEMA=sales wuerde die truncate-Fixture auf die echten
# Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import lid  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# OpenWA-Stub
# ---------------------------------------------------------------------------

class _Stub:
    def __init__(self):
        self.zuruecksetzen()

    def zuruecksetzen(self):
        self.session_status = "ready"
        self.session_code = 200
        # kennung (blanke Ziffern) -> (status, rumpf-objekt)
        self.antworten = {}
        self.vorgabe = (200, None)     # None => phone: null
        self.aufrufe = []
        self.sperre = threading.Lock()


STUB = _Stub()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        with STUB.sperre:
            STUB.aufrufe.append({"pfad": self.path,
                                 "api_key": self.headers.get("X-API-Key")})
        teile = self.path.strip("/").split("/")
        if teile[-1] == "phone":
            # …/contacts/<kodierte kennung>/phone — erst dekodieren, DANN die
            # Ziffern nehmen: `%40` traegt selbst zwei Ziffern.
            kennung = unquote(teile[-2])
            ziffern = "".join(z for z in kennung.split("@", 1)[0]
                              if z.isdigit())
            status, telefon = STUB.antworten.get(ziffern, STUB.vorgabe)
            rumpf = {"contactId": kennung, "phone": telefon}
        else:
            status, rumpf = STUB.session_code, {"id": "stub-session",
                                                "status": STUB.session_status}
        roh = json.dumps(rumpf).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.daemon_threads = True
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    lid.OPENWA_URL = f"http://127.0.0.1:{dienst.server_address[1]}"
    lid.OPENWA_SESSION_ID = "stub-session"
    lid.OPENWA_API_KEY = "stub-schluessel"
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    STUB.zuruecksetzen()
    lid.HTTP_TIMEOUT_S = 5.0
    # Die Drossel ist im Betrieb 1,5 s; im Test wuerde sie jede Runde
    # kuenstlich verlangsamen. Die Drossel SELBST wird eigens geprueft.
    lid.PAUSE_S = 0.0
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = ""
    yield
    server.UNBEKANNT_LEAD_ID = vorher


def _pfade():
    with STUB.sperre:
        return [a["pfad"] for a in STUB.aufrufe]


# ---------------------------------------------------------------------------
# Kennungen — ohne Netz
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("roh, erwartet", [
    ("183096603361451@lid", "183096603361451"),
    ("491701234567:12@s.whatsapp.net", "491701234567"),
    ("491701234567@c.us", "491701234567"),
    ("", ""), (None, ""), ("keine-ziffern@lid", ""),
])
def test_ziffern(roh, erwartet):
    assert lid.ziffern(roh) == erwartet


@pytest.mark.parametrize("roh, gruppe", [
    ("120363421499541820@g.us", True),
    # Gemessene Gruppen-Kennung, 18-stellig — auch ohne Domain erkennbar.
    ("120363421499541820", True),
    ("120363421499541820@lid", True),
    ("183096603361451@lid", False),      # gemessene LID, 15-stellig
    ("491701234567@c.us", False),
    ("4915199999999@broadcast", True),
])
def test_gruppenkennungen_werden_gar_nicht_erst_gefragt(roh, gruppe):
    assert lid.ist_gruppe(roh) is gruppe


def test_als_lid_gibt_niemals_eine_rufnummern_domain():
    """Review-Befund H1: eine als `@c.us` ausgegebene LID hat schon einmal dazu
    verleitet, sie als Telefonnummer eines Kontakts anzulegen."""
    assert lid.als_lid("183096603361451@lid") == "183096603361451@lid"
    assert lid.als_lid("183096603361451") == "183096603361451@lid"
    assert lid.als_lid("ohne-ziffern") == ""


# ---------------------------------------------------------------------------
# Der Abruf — die gemessenen Endpunkt-Fakten
# ---------------------------------------------------------------------------

def test_das_lid_suffix_geht_kodiert_mit_raus():
    """Der teuerste Befund des Plans: dieselbe Kennung OHNE Suffix liefert
    stillschweigend `phone: null`. Wer nur die Ziffern schickt, haelt ein
    Nichtergebnis faelschlich fuer 'nicht aufloesbar'."""
    STUB.antworten["183096603361451"] = (200, "491729186846")
    ergebnis = lid.aufloesen("183096603361451@lid")
    assert ergebnis.telefon == "491729186846@c.us"
    assert ergebnis.typ == lid.TYP_RUFNUMMER
    assert ergebnis.transient is False
    pfad = _pfade()[-1]
    assert "183096603361451%40lid" in pfad
    assert pfad.endswith("/phone")


def test_blanke_msisdn_laeuft_durch_nummern_py():
    """OpenWA liefert `491729186846` ohne `+`. Ausdruecklich als `+<ziffern>`
    normalisieren, sonst greift die 49-Sonderregel fuer blanke Folgen."""
    STUB.antworten["44199592386700"] = (200, "4315208874679")   # AT-Nummer
    assert lid.aufloesen("44199592386700@lid").telefon == "4315208874679@c.us"


def test_phone_null_ist_ein_echtes_negativergebnis():
    STUB.antworten["999888777666555"] = (200, None)
    ergebnis = lid.aufloesen("999888777666555@lid")
    assert ergebnis.telefon == ""
    assert ergebnis.typ == lid.TYP_UNAUFLOESBAR
    assert ergebnis.transient is False


def test_429_ist_transient_und_niemals_ein_negativergebnis():
    """Das Rate-Limit sagt etwas ueber den Moment, nichts ueber die Kennung.
    Waere es ein Negativergebnis, braennte es sich in die Zuordnung ein."""
    STUB.antworten["183096603361451"] = (429, None)
    ergebnis = lid.aufloesen("183096603361451@lid")
    assert ergebnis.transient is True
    assert ergebnis.typ == ""
    assert "429" in ergebnis.grund


@pytest.mark.parametrize("code", [400, 409, 500, 503])
def test_nicht_bereite_engine_ist_transient(code):
    """400 kam gemessen bei `disconnected`, 409 dokumentiert der Controller
    als 'engine not ready'. Beides ist kein Befund ueber die Kennung."""
    STUB.antworten["183096603361451"] = (code, None)
    assert lid.aufloesen("183096603361451@lid").transient is True


def test_404_bleibt_ein_negativergebnis():
    STUB.antworten["183096603361451"] = (404, None)
    ergebnis = lid.aufloesen("183096603361451@lid")
    assert ergebnis.transient is False
    assert ergebnis.typ == lid.TYP_UNAUFLOESBAR


def test_gruppe_beruehrt_das_netz_nie():
    ergebnis = lid.aufloesen("120363421499541820@lid")
    assert ergebnis.typ == lid.TYP_GRUPPE
    assert ergebnis.transient is False
    assert _pfade() == []


def test_der_api_schluessel_steht_in_keinem_fehlertext():
    """Fremde Fehlerrumpfe spiegeln Anfragen manchmal zurueck (Proxys) —
    dieselbe Vorsorge wie `_ohne_token` in recherche.py."""
    STUB.antworten["183096603361451"] = (
        500, "abgelehnt fuer key stub-schluessel")
    ergebnis = lid.aufloesen("183096603361451@lid")
    assert "stub-schluessel" not in ergebnis.grund
    assert "***" in ergebnis.grund


def test_ohne_konfiguration_wird_nichts_abgefragt():
    vorher = lid.OPENWA_API_KEY
    lid.OPENWA_API_KEY = ""
    try:
        ergebnis = lid.aufloesen("183096603361451@lid")
    finally:
        lid.OPENWA_API_KEY = vorher
    assert ergebnis.transient is True
    assert _pfade() == []


# ---------------------------------------------------------------------------
# Sessionstatus und Drossel
# ---------------------------------------------------------------------------

def test_bereit_meldet_eine_nicht_ready_session():
    STUB.session_status = "disconnected"
    grund = lid.bereit()
    assert "disconnected" in grund and "ready" in grund


def test_bereit_ist_still_wenn_die_session_steht():
    assert lid.bereit() == ""


def test_mehrere_drosselt_zwischen_zwei_abfragen(monkeypatch):
    pausen = []
    monkeypatch.setattr(lid.time, "sleep", pausen.append)
    STUB.vorgabe = (200, "491701234567")
    list(lid.mehrere(["111111111111111@lid", "222222222222222@lid",
                      "333333333333333@lid"], pause=1.5))
    # Vor der ERSTEN Abfrage wird nicht gewartet, danach vor jeder weiteren.
    assert pausen == [1.5, 1.5]


def test_mehrere_wartet_nicht_wegen_einer_gruppe(monkeypatch):
    pausen = []
    monkeypatch.setattr(lid.time, "sleep", pausen.append)
    STUB.vorgabe = (200, "491701234567")
    list(lid.mehrere(["120363421499541820@g.us", "111111111111111@lid"],
                     pause=1.5))
    assert pausen == []          # die Gruppe hat das Netz nie beruehrt


def test_mehrere_bricht_beim_ersten_429_ab():
    """Nach einem Rate-Limit laufen die folgenden Abfragen ohnehin in denselben
    Fehler — jede weitere verlaengert nur die Sperre."""
    STUB.vorgabe = (429, None)
    ergebnisse = list(lid.mehrere(["111111111111111@lid",
                                   "222222222222222@lid"], pause=0))
    assert len(ergebnisse) == 1
    assert ergebnisse[0][1].transient is True


# ---------------------------------------------------------------------------
# absender_aufloesen — das Werkzeug drumherum
# ---------------------------------------------------------------------------

def _sammel():
    lead = str(server._q(
        "insert into leads (name, source) values "
        "('Unbekannte Eingaenge', 'system') returning id")[0]["id"])
    server.UNBEKANNT_LEAD_ID = lead
    return lead


def _eingang(lead, absender, text="Hallo?", vor_stunden=1):
    return str(server._q(
        "insert into activities (lead_id, type, payload, actor, created_at) "
        "values (%s, 'kundenantwort', %s, 'human', "
        "        now() - (%s * interval '1 hour')) returning id",
        (lead, json.dumps({"text": text, "richtung": "eingehend",
                           "absender": absender,
                           "message_id": f"wa-{absender}-{vor_stunden}"}),
         vor_stunden))[0]["id"])


def _aufloesen(**kw):
    return json.loads(server.absender_aufloesen(**kw))


def test_nicht_ready_session_fragt_gar_nichts_ab():
    sammel = _sammel()
    _eingang(sammel, "183096603361451@lid")
    STUB.session_status = "disconnected"
    antwort = _aufloesen()
    assert "fehler" in antwort and antwort["geprueft"] == 0
    assert not any("/phone" in p for p in _pfade())
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.LID_ZUORDNUNG,))[0]["n"] == 0


def test_aufgeloeste_kennung_wird_gespiegelt_und_ist_danach_bekannt():
    sammel = _sammel()
    _eingang(sammel, "183096603361451@lid")
    STUB.antworten["183096603361451"] = (200, "491729186846")
    antwort = _aufloesen()
    # Die Kennung bleibt in ihrer unaufgeloesten Form stehen — sie ist der
    # Wiedererkennungswert im Posteingang.
    assert antwort["aufgeloest"] == [{"kennung": "183096603361451@lid",
                                      "telefon": "491729186846@c.us"}]
    assert server.lid_telefon("183096603361451@lid") == "491729186846@c.us"


def test_429_schreibt_kein_negativergebnis_in_die_zuordnung():
    sammel = _sammel()
    _eingang(sammel, "183096603361451@lid")
    STUB.antworten["183096603361451"] = (429, None)
    antwort = _aufloesen()
    assert antwort["abgebrochen"] and "429" in antwort["abgebrochen"]
    assert antwort["geprueft"] == 0
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.LID_ZUORDNUNG,))[0]["n"] == 0
    assert server.lid_telefon("183096603361451@lid") == ""


def test_gruppe_wird_vermerkt_statt_wiederholt_zu_scheitern():
    sammel = _sammel()
    _eingang(sammel, "120363421499541820@lid")
    antwort = _aufloesen()
    assert antwort["gruppen"] == 1
    zeile = server._q("select payload from activities where type = %s",
                      (server.LID_ZUORDNUNG,))[0]["payload"]
    assert zeile["typ"] == "gruppe" and zeile["telefon"] is None
    # Zweiter Lauf fragt dieselbe Kennung nicht noch einmal.
    assert _aufloesen()["geprueft"] == 0


def test_schon_gefragte_kennungen_kommen_nicht_erneut_dran():
    sammel = _sammel()
    _eingang(sammel, "999888777666555@lid")
    STUB.antworten["999888777666555"] = (200, None)
    assert _aufloesen()["unaufloesbar"] == 1
    assert _aufloesen()["geprueft"] == 0
    # …ausser der Betreiber fragt ausdruecklich nach dieser einen.
    STUB.antworten["999888777666555"] = (200, "491701234567")
    antwort = _aufloesen(kennung="999888777666555@lid")
    assert antwort["aufgeloest"][0]["telefon"] == "491701234567@c.us"


def test_limit_wird_gekappt_statt_abgelehnt():
    sammel = _sammel()
    for i in range(4):
        _eingang(sammel, f"18309660336145{i}@lid", vor_stunden=i + 1)
    STUB.vorgabe = (200, None)
    assert _aufloesen(limit=2)["geprueft"] == 2
    assert _aufloesen(limit="viele")["geprueft"] == 2   # Rest, Vorgabe 5


def test_bekannte_rufnummern_kosten_kein_budget():
    """Ein Absender, dessen Nummer schon einem Kontakt gehoert, muss nicht
    aufgeloest werden — er IST bereits eine Rufnummer."""
    sammel = _sammel()
    server._q("insert into leads (name, phone, source) values "
              "('Max Bekannt', '+491701234567', 'whatsapp') returning id")
    _eingang(sammel, "491701234567@c.us")
    assert _aufloesen()["geprueft"] == 0
    assert not any("/phone" in p for p in _pfade())


def test_registrierung_und_signatur():
    import inspect
    parameter = inspect.signature(server.absender_aufloesen).parameters
    assert list(parameter) == ["limit", "kennung"]
    assert parameter["limit"].default == server.AUFLOESEN_LIMIT_VORGABE
    assert server.absender_aufloesen in server.WERKZEUGE
