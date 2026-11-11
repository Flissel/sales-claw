"""Vexa-Client gegen einen lokalen HTTP-Stub (Muster: meet_stub)."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import vexa

SCHLUESSEL = "streng-geheimer-vexa-schluessel"


class _VexaStub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _antwort(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        koerper = self.rfile.read(laenge).decode() if laenge else ""
        self.server.anfragen.append(
            (self.command, self.path, self.headers.get("X-API-Key"), koerper))
        status, daten = self.server.antworten.get(
            (self.command, self.path), (200, {}))
        roh = json.dumps(daten).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    do_GET = do_POST = do_DELETE = _antwort


@pytest.fixture(autouse=True)
def _zustand_frisch(monkeypatch):
    # I9: Warnungen nur beim Zustandswechsel - jeder Test beginnt frisch.
    monkeypatch.setattr(vexa, "_unerreichbar_gemeldet", False, raising=False)


@pytest.fixture
def stub(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _VexaStub)
    server.anfragen, server.antworten = [], {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("VEXA_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("VEXA_API_KEY", SCHLUESSEL)
    yield server
    server.shutdown()
    server.server_close()


def test_bot_body_exakt(stub):
    stub.antworten[("POST", "/bots")] = (201, {
        "id": 7, "platform": "jitsi", "native_meeting_id": "R1@meet.ffmuc.net",
        "status": "requested"})
    erg = vexa.bot_schicken("https://meet.ffmuc.net/R1")
    assert erg == {"meeting_id": 7, "plattform": "jitsi",
                   "native_id": "R1@meet.ffmuc.net", "status": "requested"}
    methode, pfad, key, koerper = stub.anfragen[0]
    assert (methode, pfad, key) == ("POST", "/bots", SCHLUESSEL)
    assert json.loads(koerper) == {
        "meeting_url": "https://meet.ffmuc.net/R1",
        "bot_name": "VibeMind Mitschrift", "language": "de",
        "recording_enabled": False,
        "automatic_leave": {"max_wait_for_admission": 1800000}}


def test_lobby_warten_aus_umgebung(stub, monkeypatch):
    monkeypatch.setenv("VEXA_LOBBY_WARTEN_MS", "60000")
    stub.antworten[("POST", "/bots")] = (201, {"id": 1})
    vexa.bot_schicken("https://x/y")
    assert json.loads(stub.anfragen[0][3])["automatic_leave"] == {
        "max_wait_for_admission": 60000}


def test_segmente_sortiert_und_abgebildet(stub):
    stub.antworten[("GET", "/transcripts/by-id/7")] = (200, {"segments": [
        {"speaker": "B", "absolute_start_time": "2026-11-11T10:00:05Z",
         "text": "zweitens", "language": "de", "start": 5.0},
        {"speaker": "C", "text": "ohne Zeit", "language": "de"},
        {"speaker": "A", "absolute_start_time": "2026-11-11T10:00:01Z",
         "text": "erstens", "language": "de", "start": 1.0},
    ]})
    segs = vexa.segmente_holen(7)
    assert [s["text"] for s in segs] == ["erstens", "zweitens", "ohne Zeit"]
    assert segs[0] == {"sprecher": "A", "beginn": "2026-11-11T10:00:01Z",
                       "text": "erstens", "sprache": "de"}
    assert segs[2]["beginn"] == ""


def test_stoppen_404_ok(stub):
    stub.antworten[("DELETE", "/bots/jitsi/R1")] = (404, {})
    assert vexa.bot_stoppen("jitsi", "R1") is None


def test_loeschen_404_ok(stub):
    stub.antworten[("DELETE", "/meetings/9")] = (404, {})
    assert vexa.meeting_loeschen(9) is None


def test_native_id_mit_at(stub):
    vexa.bot_stoppen("jitsi", "R1@meet.ffmuc.net")
    assert stub.anfragen[0][:2] == ("DELETE", "/bots/jitsi/R1@meet.ffmuc.net")


def test_meeting_lesen_filtert_liste(stub):
    stub.antworten[("GET", "/meetings")] = (200, {"meetings": [
        {"id": 1, "status": "active", "data": {}},
        {"id": 2, "status": "completed",
         "data": {"reason": "r", "completion_reason": "left_alone"}}]})
    assert vexa.meeting_lesen(2) == {
        "status": "completed", "grund": "r", "ende_grund": "left_alone"}
    assert vexa.meeting_lesen(1) == {
        "status": "active", "grund": "", "ende_grund": ""}


def test_meeting_lesen_unbekannt(stub):
    stub.antworten[("GET", "/meetings")] = (200, {"meetings": []})
    with pytest.raises(vexa.VexaNichtGefunden):
        vexa.meeting_lesen(5)


def test_meeting_lesen_ueberspringt_nicht_dicts(stub):
    stub.antworten[("GET", "/meetings")] = (200, {"meetings": [
        None, "x", {"id": 3, "status": "active"}]})
    assert vexa.meeting_lesen(3)["status"] == "active"


def test_segmente_404_nicht_gefunden(stub):
    stub.antworten[("GET", "/transcripts/by-id/4")] = (404, {})
    with pytest.raises(vexa.VexaNichtGefunden):
        vexa.segmente_holen(4)


def test_native_id_sonderzeichen(stub):
    vexa.bot_stoppen("jitsi", "a#b/c@h")
    assert stub.anfragen[0][:2] == ("DELETE", "/bots/jitsi/a%23b%2Fc@h")


def test_schluessel_mit_crlf_leckt_nicht(stub, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VEXA_API_KEY", "geheim123\r\n")
    stub.antworten[("GET", "/meetings")] = (200, {"meetings": [
        {"id": 1, "status": "active"}]})
    try:
        vexa.meeting_lesen(1)
    except vexa.VexaFehler as e:
        assert "geheim123" not in str(e) and "geheim123" not in repr(e)
    assert "geheim123" not in caplog.text
    assert stub.anfragen[0][2] == "geheim123"


def test_kaputter_header_wird_fester_fehler(stub, monkeypatch, caplog):
    """Auch ein Schluessel mit eingebettetem Zeilenumbruch (strip hilft nicht)."""
    monkeypatch.setenv("VEXA_API_KEY", "geheim123\nX-Evil: 1")
    with pytest.raises(vexa.VexaFehler) as e:
        vexa.meeting_lesen(1)
    assert "geheim123" not in str(e.value) and "geheim123" not in repr(e.value)
    assert "geheim123" not in caplog.text


def test_fehler_ohne_schluessel_im_text(stub, caplog):
    caplog.set_level(logging.DEBUG)
    stub.antworten[("POST", "/bots")] = (500, {"detail": "kaputt"})
    with pytest.raises(vexa.VexaFehler) as e:
        vexa.bot_schicken("https://meet.ffmuc.net/R1?pwd=passcode123")
    assert SCHLUESSEL not in str(e.value)
    assert "passcode123" not in str(e.value)
    assert "500" in str(e.value)
    assert SCHLUESSEL not in caplog.text
    assert "passcode123" not in caplog.text


def test_netzfehler_wird_vexafehler(monkeypatch):
    monkeypatch.setenv("VEXA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("VEXA_API_KEY", SCHLUESSEL)
    with pytest.raises(vexa.VexaFehler) as e:
        vexa.meeting_lesen(1)
    assert SCHLUESSEL not in str(e.value)


def test_ohne_schluessel(monkeypatch):
    monkeypatch.delenv("VEXA_API_KEY", raising=False)
    assert vexa.konfiguriert() is False
    with pytest.raises(vexa.VexaFehler, match="VEXA_API_KEY fehlt"):
        vexa.bot_schicken("https://x")
    with pytest.raises(vexa.VexaFehler, match="VEXA_API_KEY fehlt"):
        vexa.segmente_holen(1)
    monkeypatch.setenv("VEXA_API_KEY", "x")
    assert vexa.konfiguriert() is True


@pytest.mark.parametrize("vexa_status,erwartet", [
    ("requested", "wartet_auf_einlass"), ("joining", "wartet_auf_einlass"),
    ("awaiting_admission", "wartet_auf_einlass"), ("active", "laeuft"),
    ("completed", "fertig"), ("failed", "fehlgeschlagen"),
    ("seltsam", "wartet_auf_einlass"), ("", "wartet_auf_einlass"),
])
def test_abbilden(vexa_status, erwartet):
    assert vexa.abbilden(vexa_status) == erwartet


# --- Final-Review I9: "nicht erreichbar" nur beim Zustandswechsel -----------

def test_i9_nicht_erreichbar_einmal_je_wechsel(stub, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="vexa")
    port = stub.server_address[1]
    monkeypatch.setenv("VEXA_URL", "http://127.0.0.1:1")
    for _ in range(3):
        with pytest.raises(vexa.VexaNichtErreichbar):
            vexa.meeting_lesen(1)
        with pytest.raises(vexa.VexaFehler):
            vexa.bot_stoppen("google_meet", "abc")
    warn = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warn) == 1 and "nicht erreichbar" in warn[0].getMessage()
    # wieder da: eine Info, danach wieder eine Warnung beim naechsten Ausfall
    monkeypatch.setenv("VEXA_URL", f"http://127.0.0.1:{port}")
    stub.antworten[("GET", "/meetings")] = (200, {"meetings": [{"id": 1, "status": "active"}]})
    vexa.meeting_lesen(1)
    monkeypatch.setenv("VEXA_URL", "http://127.0.0.1:1")
    with pytest.raises(vexa.VexaFehler):
        vexa.meeting_lesen(1)
    warn = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warn) == 2
    assert SCHLUESSEL not in caplog.text
