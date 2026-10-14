"""Eigene Termine des Betreibers (Tabelle eigene_termine, CalDAV-Abgleich)."""
import os
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import pytest

# HART setzen: nie gegen das echte Schema truncaten.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import termine_eigen  # noqa: E402

B = ZoneInfo("Europe/Berlin")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


# ---------------------------------------------------------------------------
# CalDAV-Stub (Muster aus test_termin.py, dazu DELETE)
# ---------------------------------------------------------------------------

class _Stub:
    def __init__(self):
        self.status = 201
        self.rumpf = b""
        self.aufrufe = []
        self.sperre = threading.Lock()

    def zuruecksetzen(self):
        self.status = 201
        self.rumpf = b""
        with self.sperre:
            self.aufrufe.clear()


STUB = _Stub()
STUB_URL = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_PUT(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        laenge = int(self.headers.get("Content-Length", "0"))
        roh = self.rfile.read(laenge) if laenge else b""
        with STUB.sperre:
            STUB.aufrufe.append({
                "pfad": self.path,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "if_none_match": self.headers.get("If-None-Match"),
                "user_agent": self.headers.get("User-Agent"),
                "rumpf": roh.decode("utf-8"),
            })
        self.send_response(STUB.status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(STUB.rumpf)))
        self.end_headers()
        if STUB.rumpf:
            self.wfile.write(STUB.rumpf)

    def do_REPORT(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        laenge = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(laenge) if laenge else b""
        with STUB.sperre:
            STUB.aufrufe.append({"pfad": self.path, "methode": "REPORT"})
        self.send_response(STUB.status)
        self.send_header("Content-Type", 'application/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(STUB.rumpf)))
        self.end_headers()
        if STUB.rumpf:
            self.wfile.write(STUB.rumpf)

    def do_DELETE(self):  # noqa: N802
        with STUB.sperre:
            STUB.aufrufe.append({"methode": "DELETE", "pfad": self.path})
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    global STUB_URL
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.daemon_threads = True
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    STUB_URL = f"http://127.0.0.1:{dienst.server_address[1]}/kalender/"
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    for name in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT"):
        monkeypatch.delenv(name, raising=False)
    STUB.zuruecksetzen()
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.eigene_termine")


@pytest.fixture
def kalender_konfiguriert(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", STUB_URL)
    monkeypatch.setenv("CALDAV_USER", "betreiber@example.org")
    monkeypatch.setenv("CALDAV_PASSWORT", "GEHEIMES-APP-PASSWORT")


def _morgen(h=10):
    d = datetime.now(B) + timedelta(days=1)
    return d.replace(hour=h, minute=0, second=0, microsecond=0)


def test_anlegen_speichert_und_traegt_ein(kalender_konfiguriert):
    r = termine_eigen.anlegen("Steuerberater", _morgen(), 45, ort="Büro")
    t = r["termin"]
    assert t["uid"].endswith("@sales-claw") and t["dauer_minuten"] == 45 and t["kalender_stand"] == "eingetragen"
    assert STUB.aufrufe[-1]["pfad"].endswith(t["uid"] + ".ics")


def test_caldav_aus_bleibt_gespeichert():
    t = termine_eigen.anlegen("Blocker", _morgen(), 30)["termin"]
    assert t["kalender_stand"] == "nicht_konfiguriert"
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23))[0]["uid"] == t["uid"]


def test_caldav_fehler_steht_im_stand(kalender_konfiguriert):
    STUB.status = 500
    t = termine_eigen.anlegen("X", _morgen(), 30)["termin"]
    assert t["kalender_stand"].startswith("fehlgeschlagen")


def test_aendern_loescht_und_traegt_neu_ein_gleiche_uid(kalender_konfiguriert):
    t = termine_eigen.anlegen("A", _morgen(9), 30)["termin"]
    r = termine_eigen.aendern(t["uid"], t["geaendert_am"], beginn=_morgen(11), titel="B")
    assert r["termin"]["uid"] == t["uid"] and r["termin"]["titel"] == "B"
    methoden = [a.get("methode", "PUT") for a in STUB.aufrufe]
    assert "DELETE" in methoden and methoden[-1] == "PUT"


def test_aendern_veraltet():
    t = termine_eigen.anlegen("A", _morgen(), 30)["termin"]
    termine_eigen.aendern(t["uid"], t["geaendert_am"], titel="B")
    assert termine_eigen.aendern(t["uid"], t["geaendert_am"], titel="C") == {"veraltet": True}


@pytest.mark.parametrize("dauer", [4, 1441])
def test_dauer_grenzen(dauer):
    assert "fehler" in termine_eigen.anlegen("A", _morgen(), dauer)


def test_vergangenheit_abgelehnt():
    assert "fehler" in termine_eigen.anlegen("A", datetime.now(B) - timedelta(hours=1), 30)


def test_sonderzeichen_bleiben(kalender_konfiguriert):
    titel = "Mo & Co; Treffen, „X“"
    termine_eigen.anlegen(titel, _morgen(), 30)
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23))[0]["titel"] == titel
    assert "Mo & Co\\; Treffen\\, „X“" in STUB.aufrufe[-1]["rumpf"]


def test_loeschen(kalender_konfiguriert):
    t = termine_eigen.anlegen("A", _morgen(), 30)["termin"]
    assert termine_eigen.loeschen(t["uid"]).get("geloescht") is True
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23)) == []
