"""Abonnierte Fremdkalender holen und zerlegen — ohne Netz."""
import threading
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import kalenderquellen


_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Berlin\r\n"
    "BEGIN:DAYLIGHT\r\n"
    "TZOFFSETFROM:+0100\r\n"
    "TZOFFSETTO:+0200\r\n"
    "TZNAME:CEST\r\n"
    "DTSTART:19700329T020000\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\n"
    "END:DAYLIGHT\r\n"
    "END:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:zweiter@google\r\n"
    "DTSTART;TZID=Europe/Berlin:20261002T140000\r\n"
    "DTEND;TZID=Europe/Berlin:20261002T153000\r\n"
    "SUMMARY:Zweiter Termin\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:erster@google\r\n"
    "DTSTART;TZID=Europe/Berlin:20261001T090000\r\n"
    "DTEND;TZID=Europe/Berlin:20261001T100000\r\n"
    "SUMMARY:Erster Termin\r\n"
    "LOCATION:Büro\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n")


class _Stub:
    def __init__(self):
        self.status = 200
        self.rumpf = _ICS.encode("utf-8")
        self.typ = "text/calendar; charset=utf-8"
        self.kopfzeilen = []


@pytest.fixture
def server_stub():
    stub = _Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            stub.kopfzeilen.append(dict(self.headers))
            self.send_response(stub.status)
            self.send_header("Content-Type", stub.typ)
            self.send_header("Content-Length", str(len(stub.rumpf)))
            self.end_headers()
            self.wfile.write(stub.rumpf)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}/privat.ics"
    yield stub
    httpd.shutdown()


def test_termine_werden_gelesen_und_sortiert(server_stub):
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert [t["titel"] for t in termine] == ["Erster Termin", "Zweiter Termin"]
    assert termine[0]["ort"] == "Büro"
    assert termine[0]["uid"] == "erster@google"


def test_ende_wird_gelesen(server_stub):
    """Ohne Endzeit ist keine Ueberlappung berechenbar. DTEND wurde im Baum
    bisher NUR geschrieben, nie gelesen."""
    termine, _ = kalenderquellen.hole(server_stub.url)
    dauer = termine[0]["ende"] - termine[0]["beginn"]
    assert dauer.total_seconds() == 3600, termine[0]


def test_zeiten_sind_zonenbewusst(server_stub):
    termine, _ = kalenderquellen.hole(server_stub.url)
    assert termine[0]["beginn"].tzinfo is not None
    assert termine[0]["beginn"].astimezone(timezone.utc).hour == 7


def test_eigener_user_agent_wird_gesetzt(server_stub):
    """Betriebsvoraussetzung, nicht Kosmetik: die WAF vor dav.privateemail.com
    weist die Vorgabe-Kennung von urllib mit 403 ab (kalender.py, Messreihe
    vom 19.08.2026). Ein fremder Anbieter kann dasselbe tun."""
    kalenderquellen.hole(server_stub.url)
    assert "urllib" not in server_stub.kopfzeilen[0]["User-Agent"].lower()


def test_webseite_statt_kalender_wird_benannt(server_stub):
    """Der haeufigste Bedienfehler: die oeffentliche Adresse oder ein Link
    auf eine Webseite. Der Text muss sagen, WAS ankam — sonst sucht der
    Kollege an der falschen Stelle."""
    server_stub.rumpf = b"<!doctype html><html><body>Anmelden</body></html>"
    server_stub.typ = "text/html; charset=utf-8"
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "Webseite" in fehler, fehler


def test_http_fehler_wird_gemeldet(server_stub):
    server_stub.status = 404
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "404" in fehler, fehler


def test_zu_grosse_antwort_wird_abgewiesen(server_stub):
    server_stub.rumpf = b"BEGIN:VCALENDAR\r\n" + b"X" * (
        kalenderquellen.MAX_BYTES + 1)
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "gross" in fehler.lower(), fehler


def test_nur_http_und_https():
    termine, fehler = kalenderquellen.hole("file:///etc/passwd")
    assert termine == []
    assert "http" in fehler.lower(), fehler


def test_die_adresse_steht_in_keinem_fehlertext():
    """Spec §4: die Adresse ist ein Geheimnis mit der Berechtigung darin.
    Ein Fehlertext geht in die Datenbank und auf den Bildschirm."""
    url = "https://calendar.google.invalid/ical/GEHEIM123/basic.ics"
    _, fehler = kalenderquellen.hole(url)
    assert fehler is not None
    assert "GEHEIM123" not in fehler, fehler


def test_ohne_adresse_filtert_auch_teile():
    url = "https://calendar.google.invalid/ical/GEHEIM123/basic.ics"
    text = f"Fehler beim Abruf von {url} (Zeitgrenze)"
    sauber = kalenderquellen.ohne_adresse(text, url)
    assert "GEHEIM123" not in sauber
    assert "Zeitgrenze" in sauber
