"""Vertragstests des Dispatchers gegen sales_test + HTTP-Stub.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen. Der
OpenWA-Ersatz ist ein `http.server`-Thread auf einem vom Betriebssystem
vergebenen Port; `dispatch.OPENWA_URL/SESSION_ID/API_KEY` werden auf ihn
umgebogen. Es geht in diesen Tests zu keinem Zeitpunkt eine echte
WhatsApp-Nachricht raus.
"""
import base64
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die Suite sonst gegen die echten Kundendaten laufen lassen —
# `sales.activities` ist append-only und liesse sich nicht zuruecksetzen, die
# autouse-Fixture unten truncatet aber. Der Schutz muss konstruktiv sein,
# nicht von der Disziplin des Aufrufers abhaengen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import dispatch  # noqa: E402  — liest SALES_DB_SCHEMA ueber server beim Import
import medien  # noqa: E402
import nummern  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein.

    `server.SCHEMA` wird beim Import ausgewertet und steuert den
    search_path des Verbindungspools. Stimmt er nicht, bricht die Suite ab,
    BEVOR die erste Fixture etwas truncatet."""
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# OpenWA-Stub
# ---------------------------------------------------------------------------

class _Stub:
    """Konfigurierbarer OpenWA-Ersatz: Status, Rumpf, Verzoegerung."""

    def __init__(self):
        self.status = 200
        self.rumpf = b'{"id":"stub-1","status":"queued"}'
        self.verzoegerung = 0.0
        self.aufrufe = []
        self.sperre = threading.Lock()

    def zuruecksetzen(self):
        self.status = 200
        self.rumpf = b'{"id":"stub-1","status":"queued"}'
        self.verzoegerung = 0.0
        with self.sperre:
            self.aufrufe.clear()


STUB = _Stub()
STUB_URL = ""      # von der Fixture gesetzt, fuer Tests die die URL kurz umbiegen


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        laenge = int(self.headers.get("Content-Length", "0"))
        roh = self.rfile.read(laenge) if laenge else b""
        with STUB.sperre:
            STUB.aufrufe.append({
                "pfad": self.path,
                "api_key": self.headers.get("X-API-Key"),
                "content_type": self.headers.get("Content-Type"),
                "json": json.loads(roh or b"{}"),
            })
        if STUB.verzoegerung:
            time.sleep(STUB.verzoegerung)
        try:
            self.send_response(STUB.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(STUB.rumpf)))
            self.end_headers()
            self.wfile.write(STUB.rumpf)
        except OSError:
            # Der Timeout-Test schliesst die Verbindung, bevor wir antworten.
            pass

    def log_message(self, *_):  # kein Rauschen im Testlauf
        pass


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    global STUB_URL
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.daemon_threads = True
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    STUB_URL = f"http://127.0.0.1:{dienst.server_address[1]}"
    dispatch.OPENWA_SESSION_ID = "stub-session"
    dispatch.OPENWA_API_KEY = "stub-key"
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def saubere_tabellen():
    dispatch.OPENWA_URL = STUB_URL
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    STUB.zuruecksetzen()
    dispatch.HTTP_TIMEOUT_S = 5.0
    # Die Sendepause (T5a) ist im Betrieb 1 s; im Test wuerde sie jede Runde
    # mit mehreren Entwuerfen um Sekunden verlaengern. Der Test, der die Pause
    # selbst prueft, setzt sie ausdruecklich wieder hoch.
    dispatch.SENDE_PAUSE_S = 0.0
    yield


class _Mitschnitt(logging.Handler):
    """Faengt Logsaetze des Dispatchers ab.

    pytests `caplog` haengt an der Wurzel — `dispatch.LOG` hat aber
    `propagate = False` (bewusst, siehe `_logging_einrichten`), die Saetze
    kommen dort also nie an. Deshalb ein eigener Handler direkt am
    Modul-Logger."""

    def __init__(self):
        super().__init__()
        self.saetze = []

    def emit(self, record):
        self.saetze.append(record)

    def texte(self, level=None):
        return [s.getMessage() for s in self.saetze
                if level is None or s.levelno == level]

    def __enter__(self):
        dispatch.LOG.addHandler(self)
        return self

    def __exit__(self, *_):
        dispatch.LOG.removeHandler(self)
        return False


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead(name="Max Testperson", phone="+491701234567"):
    # Mit gesetzter Kontakt-Freigabe: diese Suite testet die Zustellmechanik
    # HINTER dem Gate. Das Gate selbst (nicht freigegebene Kontakte, Entzug
    # zwischen Freigabe und Zustellung, Entwurf ohne Kontakt) prueft
    # tests/test_kontakt_freigabe.py.
    return server._q(
        "insert into leads (name, phone, source, enrichment) values "
        "(%s, %s, 'whatsapp', "
        "'{\"whatsapp_freigabe\": {\"freigegeben\": true}}'::jsonb) "
        "returning id", (name, phone))[0]["id"]


def _draft(lead_id, recipient, kanal="whatsapp", status="approved",
           body="Hallo Herr Testperson!"):
    return server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, "
        "approved_by, approved_at) values (%s, %s, %s, %s, %s, 'betreiber', now()) "
        "returning id", (lead_id, kanal, recipient, body, status))[0]["id"]


def _zeile(draft_id):
    return server._q(
        "select status, error, sent_at, recipient, channel from drafts "
        "where id = %s", (draft_id,))[0]


# ---------------------------------------------------------------------------
# Empfaenger-Normalisierung (ohne DB, ohne HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("roh, erwartet", [
    ("+491701234567", "491701234567@c.us"),
    ("+49 170 1234567", "491701234567@c.us"),
    ("+49-170-1234567", "491701234567@c.us"),
    ("0049 170 1234567", "491701234567@c.us"),
    ("491701234567", "491701234567@c.us"),
    ("+49 (0)170 1234567", "491701234567@c.us"),
    ("+1 202 555 0143", "12025550143@c.us"),
    # T5a — Landesvorwahl ausgeschrieben, egal welches Land:
    ("+436641234567", "436641234567@c.us"),          # AT, korrekt erfasst
    ("+43 664 1234567", "436641234567@c.us"),
    ("0043 664 1234567", "436641234567@c.us"),
    ("00491701234567", "491701234567@c.us"),
])
def test_normalisierung_gueltiger_nummern(roh, erwartet):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert fehler is None
    assert chat_id == erwartet


@pytest.mark.parametrize("roh", [
    "Max Testperson",
    "Herr Mueller 0170 1234567",   # Mischform: bewusst nicht geraten
    "max@example.com",
    "0170 123",                    # weniger als 8 Ziffern — Form schon kaputt
    "1234567890123456789",         # laenger als E.164 erlaubt
    "",
    "   ",
    None,
])
def test_normalisierung_lehnt_unzustellbare_empfaenger_ab(roh):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert chat_id is None
    assert fehler == nummern.FEHLER_UNZUSTELLBAR


# --- T5a: nationale Schreibweise wird NICHT mehr als deutsch geraten -------
#
# Der ernsteste Befund der Batch-Review: die alte Amtsnull-Regel machte aus
# JEDER national geschriebenen Nummer eine deutsche. `0664 1234567` ist in
# Oesterreich eine gaengige Mobilnummer — daraus wurde `491701…`-artig
# `496641234567@c.us`, also die Nummer eines echten, voellig unbeteiligten
# deutschen Menschen. Eine Vertriebsnachricht an einen Fremden ist teurer als
# jede Rueckfrage.

@pytest.mark.parametrize("roh", [
    "0664 1234567",        # AT-Mobil — der Ausloeser dieser Regel
    "06641234567",
    "0664-123 4567",
    "0170 1234567",        # DE-Mobil, national geschrieben: ebenfalls Rueckfrage
    "0170-123 4567",
    "089 12345678",        # DE-Festnetz, national geschrieben
    "0 664 1234567",
])
def test_nationale_schreibweise_wird_nicht_geraten(roh):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert chat_id is None
    assert fehler == nummern.FEHLER_NATIONALE_SCHREIBWEISE
    assert fehler == ("Empfaenger ohne Landesvorwahl ('0…') — mit +Vorwahl "
                      "erfassen, nationaler Schreibweise wird nicht vertraut")


def test_at_nummer_wird_niemals_zu_einer_deutschen():
    """Die Regressionsprobe zum Befund: `0664…` darf unter keinen Umstaenden
    als `49…` herauskommen."""
    chat_id, fehler = dispatch.normalisiere_empfaenger("0664 1234567")
    assert chat_id is None
    assert fehler is not None
    assert "49" not in (chat_id or "")


def test_at_draft_wird_failed_und_geht_nie_an_openwa():
    draft = _draft(_lead(phone="0664 1234567"), "0664 1234567")

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"] == nummern.FEHLER_NATIONALE_SCHREIBWEISE
    assert zeile["sent_at"] is None
    assert STUB.aufrufe == []        # kein HTTP-Aufruf, kein Zustellversuch
    akt = server._q("select count(*) as n from activities where type = 'versand'")
    assert akt[0]["n"] == 0


# --- Fix-Runde 1: blanke Ziffernfolgen brauchen den 49-Praefix ------------
#
# Dieselbe Falle wie die Amtsnull, eine Ebene tiefer: eine blanke Ziffernfolge
# wurde akzeptiert unter der ANNAHME, sie bringe ihre Landesvorwahl mit —
# ungeprueft. `1701234567` ist eine deutsche Mobilnummer, der `+49` und die
# fuehrende `0` fehlen. Gelesen wurde sie als US-Vorwahl 1 + 701 (ein realer
# Vorwahlbereich in North Dakota): stille Zustellung an eine falsche reale
# Person. Blank vertrauen wir nur noch `49…`.

@pytest.mark.parametrize("roh", [
    "491701234567",        # 12 Stellen — 49 + deutsche Mobilnummer
    "49891234567890",      # 14 Stellen
    "49123456789",         # 11 Stellen — Untergrenze
])
def test_blanke_ziffernfolge_mit_49_ist_zustellbar(roh):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert fehler is None
    assert chat_id == f"{roh}@c.us"


@pytest.mark.parametrize("roh", [
    "1701234567",          # DER BEFUND: DE-Mobil ohne +49, gelesen als US 1+701
    "436641234567",        # AT muss +43 ausschreiben
    "12025550143",         # US muss +1 ausschreiben
    "4917012345",          # 49, aber nur 10 Stellen
    "491701234",           # 49, aber nur 9 Stellen
    "12345678",            # gar keine erkennbare Vorwahl
    "4917012345678901",    # 16 Stellen — jenseits von E.164
])
def test_blanke_ziffernfolge_ohne_49_praefix_wird_abgelehnt(roh):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert chat_id is None
    assert fehler in (nummern.FEHLER_VORWAHL_UNBEKANNT,
                      nummern.FEHLER_UNZUSTELLBAR)


@pytest.mark.parametrize("roh", [
    "1701234567",
    "436641234567",
    "12025550143",
    "4917012345",
    "12345678",
])
def test_blanke_ziffernfolge_nennt_die_fehlende_vorwahl(roh):
    """Der Fehlertext muss sagen, was zu tun ist — er landet in drafts.error
    und wird dem Betreiber vorgelesen."""
    _chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert fehler == nummern.FEHLER_VORWAHL_UNBEKANNT
    assert fehler == ("Landesvorwahl nicht erkennbar — Empfaenger mit "
                      "+Vorwahl erfassen")


def test_deutsche_mobilnummer_ohne_vorwahl_wird_nie_amerikanisch():
    """Regressionsprobe zum Befund der Fix-Runde."""
    chat_id, fehler = dispatch.normalisiere_empfaenger("1701234567")
    assert chat_id is None
    assert fehler is not None


def test_ausgeschriebene_vorwahl_bleibt_von_der_49_regel_unberuehrt():
    """Die 49-Bedingung gilt NUR fuer blanke Folgen. Wer `+`/`00` schreibt,
    nennt seine Vorwahl ausdruecklich und wird nicht auf Deutschland
    eingeengt."""
    for roh, erwartet in (("+436641234567", "436641234567@c.us"),
                          ("0043 664 1234567", "436641234567@c.us"),
                          ("+1 202 555 0143", "12025550143@c.us"),
                          ("+49 (0)170 1234567", "491701234567@c.us")):
        chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
        assert fehler is None, roh
        assert chat_id == erwartet


def test_dispatcher_und_server_teilen_dieselbe_normalisierung():
    """Anzeige (entwuerfe_offen) und Versand (Dispatcher) duerfen nie
    auseinanderlaufen — beide muessen dieselbe Funktion benutzen."""
    assert dispatch.normalisiere_empfaenger is nummern.normalisiere_empfaenger
    assert server.normalisiere_empfaenger is nummern.normalisiere_empfaenger


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

def test_claim_setzt_sichtbaren_zwischenzustand_und_ist_nur_einmal_moeglich():
    draft = _draft(_lead(), "+491701234567")
    geclaimt = dispatch.claim(draft)
    assert geclaimt is not None
    assert geclaimt["recipient"] == "+491701234567"
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"          # dokumentierter Zwischenzustand
    assert zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)
    assert dispatch.claim(draft) is None        # zweiter Versuch geht leer aus
    assert STUB.aufrufe == []                   # der Claim sendet nichts


def test_claim_ist_atomar_genau_einer_von_zwei_gewinnt():
    draft = _draft(_lead(), "+491701234567")
    ergebnisse = []
    sperre = threading.Lock()
    barriere = threading.Barrier(2)

    def versuch():
        barriere.wait(timeout=5)
        treffer = dispatch.claim(draft)
        with sperre:
            ergebnisse.append(treffer)

    faeden = [threading.Thread(target=versuch) for _ in range(2)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=10)
        assert not f.is_alive()

    assert len(ergebnisse) == 2
    assert len([e for e in ergebnisse if e is not None]) == 1


def test_claim_fasst_linkedin_nicht_an():
    draft = _draft(_lead(), "Max Testperson", kanal="linkedin")
    assert dispatch.claim(draft) is None
    assert _zeile(draft)["status"] == "approved"


# ---------------------------------------------------------------------------
# Versand: Erfolg
# ---------------------------------------------------------------------------

def test_erfolg_setzt_sent_und_loggt_aktivitaet():
    lead = _lead()
    draft = _draft(lead, "+49 170 1234567")

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "sent"
    assert zeile["sent_at"] is not None
    assert zeile["error"] is None

    assert len(STUB.aufrufe) == 1
    aufruf = STUB.aufrufe[0]
    assert aufruf["pfad"] == "/api/sessions/stub-session/messages/send-text"
    assert aufruf["api_key"] == "stub-key"
    assert aufruf["json"] == {"chatId": "491701234567@c.us",
                              "text": "Hallo Herr Testperson!"}

    akt = server._q("select payload from activities where lead_id = %s "
                    "and type = 'versand'", (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["draft_id"] == str(draft)
    assert akt[0]["payload"]["kanal"] == "whatsapp"
    assert akt[0]["payload"]["weg"] == "dispatcher"


def test_nur_approved_whatsapp_wird_verarbeitet():
    lead = _lead()
    pending = _draft(lead, "+491701234567", status="pending")
    rejected = _draft(lead, "+491701234567", status="rejected")
    gesendet = _draft(lead, "+491701234567", status="sent")
    email = _draft(lead, "max@example.com", kanal="email")

    dispatch.eine_runde()

    assert STUB.aufrufe == []
    assert _zeile(pending)["status"] == "pending"
    assert _zeile(rejected)["status"] == "rejected"
    assert _zeile(gesendet)["status"] == "sent"
    assert _zeile(email)["status"] == "approved"


def test_linkedin_draft_bleibt_unberuehrt():
    lead = _lead()
    linkedin = _draft(lead, "Max Testperson", kanal="linkedin")
    whatsapp = _draft(lead, "+491701234567")

    dispatch.eine_runde()

    assert _zeile(linkedin)["status"] == "approved"
    assert _zeile(linkedin)["error"] is None
    assert _zeile(whatsapp)["status"] == "sent"
    assert len(STUB.aufrufe) == 1


def test_stapel_ist_auf_fuenf_begrenzt():
    lead = _lead()
    for _ in range(7):
        _draft(lead, "+491701234567")

    dispatch.eine_runde()

    assert len(STUB.aufrufe) == 5
    offen = server._q("select count(*) as n from drafts where status = 'approved'")
    assert offen[0]["n"] == 2


# ---------------------------------------------------------------------------
# Versand: Fehlerpfade
# ---------------------------------------------------------------------------

def test_401_wird_zu_failed_mit_sprechendem_fehler():
    draft = _draft(_lead(), "+491701234567")
    STUB.status = 401
    STUB.rumpf = b'{"message":"Unauthorized"}'

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "401" in zeile["error"]
    assert zeile["sent_at"] is None
    assert not zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)


def test_500_wird_zu_failed_mit_sprechendem_fehler():
    draft = _draft(_lead(), "+491701234567")
    STUB.status = 500
    STUB.rumpf = b'{"message":"session not connected"}'

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "500" in zeile["error"]
    assert "session not connected" in zeile["error"]


def test_timeout_wird_zu_failed():
    draft = _draft(_lead(), "+491701234567")
    dispatch.HTTP_TIMEOUT_S = 0.5
    STUB.verzoegerung = 3.0

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "eitue" in zeile["error"]  # "Zeitueberschreitung", ohne Umlautfalle
    assert zeile["sent_at"] is None


def test_openwa_nicht_erreichbar_wird_zu_failed():
    draft = _draft(_lead(), "+491701234567")
    dispatch.OPENWA_URL = "http://127.0.0.1:1"  # niemand hoert hier zu

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "nicht erreichbar" in zeile["error"]


def test_name_als_empfaenger_wird_nie_gesendet():
    draft = _draft(_lead(), "Max Testperson")

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"] == "kein zustellbarer Empfaenger"
    assert STUB.aufrufe == []       # kein HTTP-Aufruf, kein Versuch
    akt = server._q("select count(*) as n from activities where type = 'versand'")
    assert akt[0]["n"] == 0


def test_fehlertext_wird_auf_300_zeichen_gekuerzt():
    draft = _draft(_lead(), "+491701234567")
    STUB.status = 500
    STUB.rumpf = b'{"message":"' + b"x" * 2000 + b'"}'

    dispatch.eine_runde()

    fehler = _zeile(draft)["error"]
    assert 0 < len(fehler) <= 300


def test_api_key_landet_nie_im_fehlertext():
    draft = _draft(_lead(), "+491701234567")
    STUB.status = 401
    STUB.rumpf = b'{"message":"invalid key"}'

    dispatch.eine_runde()

    assert "stub-key" not in _zeile(draft)["error"]


# --- T5a: Fehlerpfade, die den Prozess bisher haetten toeten koennen ------

def test_kaputte_openwa_url_wird_zur_fehlerbuchung_statt_zum_prozesstod():
    """Eine unbrauchbare OPENWA_URL liess `urllib.request.Request(...)` schon
    beim KONSTRUIEREN mit ValueError platzen — ausserhalb des try-Blocks.
    Ergebnis: der Dispatcher stirbt, und der Entwurf bleibt mit der
    Claim-Marke liegen, ohne dass irgendwo ein Grund steht."""
    draft = _draft(_lead(), "+491701234567")
    dispatch.OPENWA_URL = "keine-url"      # kein Schema, kein Host

    dispatch.eine_runde()                   # darf nicht werfen

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"]
    assert not zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)
    assert zeile["sent_at"] is None
    assert STUB.aufrufe == []


def test_kaputte_openwa_url_toetet_die_schleife_nicht():
    """Die Runde laeuft zu Ende und bilanziert — sie reisst nicht ab."""
    dispatch.OPENWA_URL = "keine-url"
    for _ in range(2):
        _draft(_lead(), "+491701234567")

    bilanz = dispatch.eine_runde()

    assert bilanz == {"fehler": 2}


def test_fehlerbuchung_ohne_wirkung_wird_laut_gemeldet():
    """`_als_fehler_buchen` schreibt nur, wenn die eigene Claim-Marke noch
    steht. Trifft es nichts, bleibt der Entwurf mit der Marke „in Zustellung"
    zurueck — und `entwurf_erneut_freigeben` verweigert dann dauerhaft die
    erneute Freigabe ohne `bestaetigt`. Das darf nicht stillschweigend
    passieren."""
    draft = _draft(_lead(), "+491701234567")
    geclaimt = dispatch.claim(draft)
    assert geclaimt is not None

    with _Mitschnitt() as mitschnitt:
        gebucht = dispatch._als_fehler_buchen(
            draft, "eine fremde Marke", "irgendein Fehler")

    assert gebucht is False
    kritisch = mitschnitt.texte(logging.CRITICAL)
    assert len(kritisch) == 1
    assert str(draft) in kritisch[0]
    assert "irgendein Fehler" in kritisch[0]
    # Der echte Claim steht unveraendert — es wurde nichts ueberschrieben.
    assert _zeile(draft)["error"] == geclaimt["marke"]


def test_fehlerbuchung_mit_eigener_marke_meldet_nichts():
    draft = _draft(_lead(), "+491701234567")
    geclaimt = dispatch.claim(draft)

    with _Mitschnitt() as mitschnitt:
        gebucht = dispatch._als_fehler_buchen(
            draft, geclaimt["marke"], "echter Fehler")

    assert gebucht is True
    assert mitschnitt.texte(logging.CRITICAL) == []
    assert _zeile(draft)["error"] == "echter Fehler"


# --- T5a: Sendepause -------------------------------------------------------

def test_zwischen_sendungen_liegt_eine_pause():
    """Ein Stapel von fuenf Nachrichten darf nicht in einem Rutsch bei
    WhatsApp einschlagen."""
    lead = _lead()
    for _ in range(3):
        _draft(lead, "+491701234567")
    dispatch.SENDE_PAUSE_S = 0.25

    start = time.monotonic()
    dispatch.eine_runde()
    gedauert = time.monotonic() - start

    assert len(STUB.aufrufe) == 3
    assert gedauert >= 0.5      # zwei Pausen zwischen drei Sendungen


def test_pause_im_betrieb_ist_eine_sekunde():
    """Der Vorgabewert steht im Modul, nicht in der Testfixture."""
    quelle = dispatch._SENDE_PAUSE_VORGABE
    assert quelle == 1.0


def test_keine_pause_hinter_einem_unzustellbaren_entwurf():
    """Pausiert wird gegenueber OpenWA, nicht gegenueber der Datenbank."""
    lead = _lead()
    for _ in range(3):
        _draft(lead, "Max Testperson")     # nie ein HTTP-Aufruf
    dispatch.SENDE_PAUSE_S = 5.0

    start = time.monotonic()
    dispatch.eine_runde()
    gedauert = time.monotonic() - start

    assert STUB.aufrufe == []
    assert gedauert < 2.0


def test_kein_retry_in_der_naechsten_runde():
    draft = _draft(_lead(), "+491701234567")
    STUB.status = 500

    dispatch.eine_runde()
    assert len(STUB.aufrufe) == 1
    assert _zeile(draft)["status"] == "failed"

    dispatch.eine_runde()
    assert len(STUB.aufrufe) == 1   # ein Mensch muss neu freigeben, nicht wir


# ---------------------------------------------------------------------------
# DISPATCH_ONCE
# ---------------------------------------------------------------------------

def test_dispatch_once_laeuft_eine_runde_und_endet(monkeypatch):
    draft = _draft(_lead(), "+491701234567")
    monkeypatch.setattr(dispatch, "DISPATCH_ONCE", True)

    assert dispatch.main() == 0
    assert _zeile(draft)["status"] == "sent"


def test_logging_geht_auf_stdout_und_nicht_doppelt():
    """`import server` zieht ueber mcp einen Root-Handler auf *stderr* hoch;
    logging.basicConfig() waere danach ein stiller No-op. Der Dispatcher muss
    trotzdem auf stdout schreiben, und jede Zeile genau einmal."""
    import sys as _sys

    dispatch.LOG.handlers.clear()          # frisch einrichten, sonst haengt der
    dispatch._logging_einrichten()         # Handler eines frueheren Tests dran
    handler = dispatch.LOG.handlers[0]
    assert handler.stream is _sys.stdout
    assert handler.stream is not _sys.stderr
    assert dispatch.LOG.propagate is False
    assert handler.formatter._fmt.startswith("%(asctime)s")


def test_main_bricht_ohne_konfiguration_ab(monkeypatch):
    monkeypatch.setattr(dispatch, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(dispatch, "DISPATCH_ONCE", True)
    draft = _draft(_lead(), "+491701234567")

    assert dispatch.main() != 0
    assert _zeile(draft)["status"] == "approved"   # nichts angefasst
    assert STUB.aufrufe == []


# ---------------------------------------------------------------------------
# F4 — Medien-Versand. Gemessen an der OpenWA-Quelle (siehe Kopf von
# medien.py): ein Aufruf je Entwurf, Nutzlast base64 + mimetype + filename,
# der Entwurfstext reist als `caption` mit.
#
# Der Medienordner ist auch hier ein tmp-Pfad, nie der echte Bind.
# ---------------------------------------------------------------------------

@pytest.fixture
def medienordner(tmp_path, monkeypatch):
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    (tmp_path / "checkliste.pdf").write_bytes(b"%PDF-1.4 Testinhalt")
    return tmp_path


def _medien_draft(lead_id, datei, recipient="+491701234567",
                  body="Die Checkliste vorab."):
    return server._q(
        "insert into drafts (lead_id, channel, recipient, body, media_ref, "
        "status, approved_by, approved_at) values (%s, 'whatsapp', %s, %s, %s, "
        "'approved', 'betreiber', now()) returning id",
        (lead_id, recipient, body, datei))[0]["id"]


def test_pdf_geht_als_dokument_mit_base64_nutzlast(medienordner):
    lead = _lead()
    draft = _medien_draft(lead, "checkliste.pdf")

    dispatch.eine_runde()

    assert len(STUB.aufrufe) == 1          # genau EIN Send je Entwurf
    aufruf = STUB.aufrufe[0]
    assert aufruf["pfad"] == "/api/sessions/stub-session/messages/send-document"
    assert aufruf["api_key"] == "stub-key"
    nutzlast = aufruf["json"]
    assert nutzlast["chatId"] == "491701234567@c.us"
    assert nutzlast["mimetype"] == "application/pdf"
    assert nutzlast["filename"] == "checkliste.pdf"
    assert nutzlast["caption"] == "Die Checkliste vorab."
    assert base64.b64decode(nutzlast["base64"]) == b"%PDF-1.4 Testinhalt"
    assert "url" not in nutzlast           # base64 statt URL, gemessen
    assert "text" not in nutzlast

    zeile = _zeile(draft)
    assert zeile["status"] == "sent"
    assert zeile["sent_at"] is not None
    assert zeile["error"] is None
    akt = server._q("select payload from activities where lead_id = %s "
                    "and type = 'versand'", (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["draft_id"] == str(draft)


@pytest.mark.parametrize("datei, endpunkt, mimetype", [
    ("checkliste.pdf", "send-document", "application/pdf"),
    ("foto.jpg", "send-image", "image/jpeg"),
    ("foto.jpeg", "send-image", "image/jpeg"),
    ("grafik.png", "send-image", "image/png"),
    ("ansage.mp3", "send-audio", "audio/mpeg"),
    ("ansage.ogg", "send-audio", "audio/ogg"),
])
def test_endpunkt_und_mimetype_folgen_der_endung(medienordner, datei,
                                                 endpunkt, mimetype):
    (medienordner / datei).write_bytes(b"inhalt")
    _medien_draft(_lead(), datei)

    dispatch.eine_runde()

    assert len(STUB.aufrufe) == 1
    assert STUB.aufrufe[0]["pfad"].endswith(f"/messages/{endpunkt}")
    assert STUB.aufrufe[0]["json"]["mimetype"] == mimetype


def test_audio_wird_nicht_als_sprachnachricht_gesendet(medienordner):
    """`ptt` bliebe die Mikrofon-Blase — ein Anhang ist eine Datei."""
    (medienordner / "ansage.mp3").write_bytes(b"inhalt")
    _medien_draft(_lead(), "ansage.mp3")

    dispatch.eine_runde()

    assert "ptt" not in STUB.aufrufe[0]["json"]


def test_geloeschte_datei_wird_failed_ohne_jeden_http_aufruf(medienordner):
    """Zwischen Freigabe und Zustellung kann die Datei verschwinden. Dann
    scheitert der Entwurf — und wird NICHT als reiner Text zugestellt."""
    lead = _lead()
    draft = _medien_draft(lead, "checkliste.pdf")
    (medienordner / "checkliste.pdf").unlink()

    dispatch.eine_runde()

    assert STUB.aufrufe == []               # kein Text-Ersatzversand
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["sent_at"] is None
    assert "checkliste.pdf" in zeile["error"]
    assert not zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)
    akt = server._q("select count(*) as n from activities where type = 'versand'")
    assert akt[0]["n"] == 0


def test_datei_ausserhalb_des_ordners_wird_nie_gelesen(medienordner, tmp_path):
    """Zweite Verteidigungslinie: selbst wenn eine Pfadangabe auf anderem Weg
    in `media_ref` geraet (Altbestand, direkter DB-Zugriff), liest der
    Dispatcher sie nicht — er bucht sie als Fehler."""
    fremd = tmp_path.parent / "geheim.pdf"
    fremd.write_bytes(b"%PDF-1.4 nicht fuer den Versand")
    draft = _medien_draft(_lead(), f"../{fremd.name}")

    dispatch.eine_runde()

    assert STUB.aufrufe == []
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["sent_at"] is None


def test_zu_grosse_datei_wird_vor_dem_senden_abgefangen(medienordner,
                                                        monkeypatch):
    monkeypatch.setattr(medien, "MAX_BYTES", 1024)
    (medienordner / "gross.pdf").write_bytes(b"x" * 2048)
    draft = _medien_draft(_lead(), "gross.pdf")

    dispatch.eine_runde()

    assert STUB.aufrufe == []
    assert _zeile(draft)["status"] == "failed"


def test_http_fehler_beim_medienversand_wird_sauber_gebucht(medienordner):
    draft = _medien_draft(_lead(), "checkliste.pdf")
    STUB.status = 413
    STUB.rumpf = b'{"message":"Payload Too Large"}'

    dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "413" in zeile["error"]
    assert zeile["sent_at"] is None


def test_textentwurf_ohne_medien_ref_geht_weiterhin_an_send_text(medienordner):
    """Regression: der Textweg bleibt exakt, wie er war."""
    draft = _draft(_lead(), "+491701234567")

    dispatch.eine_runde()

    assert len(STUB.aufrufe) == 1
    assert STUB.aufrufe[0]["pfad"] == \
        "/api/sessions/stub-session/messages/send-text"
    assert STUB.aufrufe[0]["json"] == {"chatId": "491701234567@c.us",
                                       "text": "Hallo Herr Testperson!"}
    assert _zeile(draft)["status"] == "sent"


def test_unzustellbare_nummer_schlaegt_vor_dem_dateizugriff_fehl(medienordner):
    """Die Empfaengerpruefung bleibt die erste Huerde — ein Medien-Entwurf an
    eine unzustellbare Nummer beruehrt weder Datei noch Netz."""
    draft = _medien_draft(_lead(phone="0664 1234567"), "checkliste.pdf",
                          recipient="0664 1234567")

    dispatch.eine_runde()

    assert STUB.aufrufe == []
    assert _zeile(draft)["error"] == nummern.FEHLER_NATIONALE_SCHREIBWEISE


def test_gemischter_stapel_trennt_text_und_medien(medienordner):
    lead = _lead()
    text_draft = _draft(lead, "+491701234567")
    medien_draft = _medien_draft(lead, "checkliste.pdf")

    dispatch.eine_runde()

    pfade = sorted(a["pfad"].rsplit("/", 1)[-1] for a in STUB.aufrufe)
    assert pfade == ["send-document", "send-text"]
    assert _zeile(text_draft)["status"] == "sent"
    assert _zeile(medien_draft)["status"] == "sent"
