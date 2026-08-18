"""Vertragstests des Dispatchers gegen sales_test + HTTP-Stub.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen. Der
OpenWA-Ersatz ist ein `http.server`-Thread auf einem vom Betriebssystem
vergebenen Port; `dispatch.OPENWA_URL/SESSION_ID/API_KEY` werden auf ihn
umgebogen. Es geht in diesen Tests zu keinem Zeitpunkt eine echte
WhatsApp-Nachricht raus.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("SALES_DB_SCHEMA", "sales_test")
import dispatch  # noqa: E402  — liest SALES_DB_SCHEMA ueber server beim Import
import server  # noqa: E402


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
    yield


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead(name="Max Testperson", phone="+491701234567"):
    return server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
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
    ("0170 1234567", "491701234567@c.us"),
    ("0170-123 4567", "491701234567@c.us"),
    ("+49 (0)170 1234567", "491701234567@c.us"),
    ("+1 202 555 0143", "12025550143@c.us"),
])
def test_normalisierung_gueltiger_nummern(roh, erwartet):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert fehler is None
    assert chat_id == erwartet


@pytest.mark.parametrize("roh", [
    "Max Testperson",
    "Herr Mueller 0170 1234567",   # Mischform: bewusst nicht geraten
    "max@example.com",
    "0170 123",                    # weniger als 8 Ziffern
    "1234567890123456789",         # laenger als E.164 erlaubt
    "",
    "   ",
    None,
])
def test_normalisierung_lehnt_unzustellbare_empfaenger_ab(roh):
    chat_id, fehler = dispatch.normalisiere_empfaenger(roh)
    assert chat_id is None
    assert fehler == "kein zustellbarer Empfaenger"


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
