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
    # Ohne DTEND — Fix-Runde 1, WICHTIG 2: bisher hatten beide Testtermine
    # ein DTEND, der Rueckfall ende=beginn war nirgends festgenagelt.
    "BEGIN:VEVENT\r\n"
    "UID:dritter@google\r\n"
    "DTSTART;TZID=Europe/Berlin:20261003T080000\r\n"
    "SUMMARY:Dritter Termin\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n")


class _Stub:
    def __init__(self):
        self.status = 200
        self.rumpf = _ICS.encode("utf-8")
        self.typ = "text/calendar; charset=utf-8"
        self.kopfzeilen = []


@pytest.fixture
def server_stub(monkeypatch):
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
    # Fix-Runde 1, SSRF-Schluss: `hole()` weist 127.0.0.1 jetzt per Vorgabe ab
    # (siehe Modulkonstante unten). Der Stub braucht die ausdrueckliche
    # Freigabe — monkeypatch setzt sie zurueck, sobald der Test endet.
    monkeypatch.setattr(kalenderquellen, "PRIVATE_ZIELE_ERLAUBT", True)
    yield stub
    httpd.shutdown()


def test_termine_werden_gelesen_und_sortiert(server_stub):
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert [t["titel"] for t in termine] == [
        "Erster Termin", "Zweiter Termin", "Dritter Termin"]
    assert termine[0]["ort"] == "Büro"
    assert termine[0]["uid"] == "erster@google"


def test_ende_wird_gelesen(server_stub):
    """Ohne Endzeit ist keine Ueberlappung berechenbar. DTEND wurde im Baum
    bisher NUR geschrieben, nie gelesen."""
    termine, _ = kalenderquellen.hole(server_stub.url)
    dauer = termine[0]["ende"] - termine[0]["beginn"]
    assert dauer.total_seconds() == 3600, termine[0]


def test_ende_faellt_ohne_dtend_auf_beginn_zurueck(server_stub):
    """Fix-Runde 1, WICHTIG 2: der Rueckfall ende=beginn ohne DTEND war
    ungetestet — beide bisherigen Testtermine hatten ein DTEND. Eine
    erfundene Dauer erzeugte Kollisionen, die es nicht gibt (der eigentliche
    Grund fuer dieses Modul)."""
    termine, _ = kalenderquellen.hole(server_stub.url)
    dritter = next(t for t in termine if t["uid"] == "dritter@google")
    assert dritter["ende"] == dritter["beginn"], dritter


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


def test_kaputte_adresse_wirft_nicht():
    """Fix-Runde 1, KRITISCH 1: eine unbalancierte eckige Klammer laesst
    `urllib.parse.urlsplit` mit 'ValueError: Invalid IPv6 URL' werfen —
    ausserhalb eines Fangnetzes reisst das die aufrufende Seite ab statt
    eine Meldung zurueckzugeben. hole() wirft nie, auch hier nicht."""
    termine, fehler = kalenderquellen.hole("http://exa[mple.com/geheim.ics")
    assert termine == []
    assert fehler is not None


def test_die_adresse_steht_in_keinem_fehlertext(monkeypatch):
    """Spec §4: die Adresse ist ein Geheimnis mit der Berechtigung darin.
    Ein Fehlertext geht in die Datenbank und auf den Bildschirm.

    Fix-Runde 1, KRITISCH 2: eine `.invalid`-Adresse loest zwar garantiert
    nicht auf, fragt aber trotzdem den Namensdienst — in einem
    abgeschotteten CI-Netz ist das fragil, und seit dem SSRF-Schluss prueft
    `hole()` vor jedem Abruf ohnehin per `socket.getaddrinfo`. Beides wird
    hier umgangen: die Ziel-Pruefung wird auf 'erlaubt' gestellt und der
    Verbindungsaufbau selbst wirft direkt — kein Namensdienst, kein Netz."""
    url = "https://calendar.google.invalid/ical/GEHEIM123/basic.ics"
    monkeypatch.setattr(kalenderquellen, "_ziel_erlaubt", lambda u: (True, None))

    def _wirft(_url):
        raise TimeoutError("Zeitgrenze ueberschritten")

    monkeypatch.setattr(kalenderquellen, "_antwort_lesen", _wirft)
    _, fehler = kalenderquellen.hole(url)
    assert fehler is not None
    assert "GEHEIM123" not in fehler, fehler


def test_ohne_adresse_filtert_auch_teile():
    """Fix-Runde 1, WICHTIG 1: der bisherige Text enthielt die VOLLSTAENDIGE
    Adresse — die entfernt schon die erste `.replace(url, ...)`-Zeile in
    `ohne_adresse`, die Pfad-/Abfrage-Filterung darunter blieb ungeprueft.
    Hier steht NUR der Pfad, nicht der Host — genau der Fall, fuer den die
    Pfadfilterung existiert (der Pfad allein genuegt einem Angreifer, der
    den Host kennt)."""
    url = "https://calendar.google.invalid/ical/GEHEIM123/basic.ics"
    text = "Fehler beim Abruf von /ical/GEHEIM123/basic.ics (Zeitgrenze)"
    sauber = kalenderquellen.ohne_adresse(text, url)
    assert "GEHEIM123" not in sauber
    assert "Zeitgrenze" in sauber


def test_private_ziele_sind_per_vorgabe_gesperrt():
    """Sicherheitskante mit Schalter: der Schalter muss im Code sichtbar
    UND per Vorgabe AUS sein. Nur die server_stub-Fixture setzt ihn (per
    monkeypatch, mit automatischem Zuruecksetzen) — produktiv darf er nie
    an sein."""
    assert kalenderquellen.PRIVATE_ZIELE_ERLAUBT is False


def test_loopback_ziel_wird_abgewiesen():
    """Ohne diese Kante waere `hole()` mit einer Adresse auf 127.0.0.1 ein
    Fenster in den eigenen Container — dort haengen Postgres und der
    MCP-Port im selben Netz (dieselbe SSRF-Klasse wie recherche._ziel_erlaubt,
    dort Review-Befund S1/S2)."""
    termine, fehler = kalenderquellen.hole("http://127.0.0.1:9/geheim.ics")
    assert termine == []
    assert fehler is not None
    assert "eigenen Netz" in fehler, fehler


def test_privates_ziel_wird_abgewiesen():
    """10.0.0.0/8 ist kein oeffentlich geroutetes Ziel — genau der Bereich,
    in dem VM-interne Dienste haengen koennten."""
    termine, fehler = kalenderquellen.hole("http://10.0.0.1/geheim.ics")
    assert termine == []
    assert fehler is not None
    assert "eigenen Netz" in fehler, fehler


# --- K4 (Schlusspruefung 13.09.2026): Serientermine und DURATION ----------
#
# Datumsangaben bewusst nahe an "heute" (nicht im Oktober-2026-Muster der
# uebrigen Fixture oben): seit K2/W1 filtert hole() ein Zeitfenster
# (Vorgabe 7 Tage zurueck, 60 Tage voraus) — ein Termin ausserhalb davon
# wuerde in diesen Tests fuer den falschen Grund fehlen.
from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402

_BALD = _dt.now(_tz.utc) + _td(days=5)
_ALT = _dt.now(_tz.utc) - _td(days=800)


def _ics(*vevents: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
           + "".join(vevents) + "END:VCALENDAR\r\n").encode("utf-8")


def _vevent(uid: str, dtstart: str, rumpf: str) -> str:
    return f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART:{dtstart}\r\n{rumpf}END:VEVENT\r\n"


def test_serientermin_wird_als_luecke_gemeldet_statt_einmalig_gezaehlt(
        server_stub):
    """Der Kernbefund K4: ein RRULE-VEVENT darf NICHT als einzelner Termin
    am ersten DTSTART durchrutschen (er kollidiert dann nie wieder) — er
    zaehlt stattdessen als Luecke, damit die Quelle nie `frei: true`
    ergibt."""
    server_stub.rumpf = _ics(_vevent(
        "teamrunde@google", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (_BALD + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO\r\n"
        "SUMMARY:Teamrunde\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == [], termine
    assert fehler is not None
    assert "Serientermin" in fehler and "RRULE" in fehler


def test_serie_neben_normalem_termin_behaelt_den_normalen(server_stub):
    """Eine Luecke darf gueltige Kollisionsdaten nicht mitreissen: ein
    gewoehnlicher VEVENT in derselben Antwort bleibt ein echter Termin."""
    server_stub.rumpf = _ics(
        _vevent("normal@google", _BALD.strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (_BALD + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ")
               + "\r\nSUMMARY:Normaler Termin\r\n"),
        _vevent("serie@google",
               (_BALD + _td(days=1)).strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (_BALD + _td(days=1, hours=1)).strftime(
                   "%Y%m%dT%H%M%SZ") + "\r\nRRULE:FREQ=WEEKLY\r\n"
               "SUMMARY:Serie\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert [t["titel"] for t in termine] == ["Normaler Termin"]
    assert fehler is not None and "Serientermin" in fehler


def test_duration_wird_als_ende_gelesen(server_stub):
    """RFC 5545 erlaubt DURATION statt DTEND (Apple, manche
    Outlook-Exporte) — ohne diese Lesung galt der Termin als punktuell und
    `_kollisionen` filtert punktuelle Eintraege ausdruecklich weg (K4)."""
    server_stub.rumpf = _ics(_vevent(
        "dauer@apple", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DURATION:PT1H30M\r\nSUMMARY:Mit Dauer\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert len(termine) == 1
    dauer = termine[0]["ende"] - termine[0]["beginn"]
    assert dauer.total_seconds() == 5400, termine[0]


def test_unlesbare_duration_wird_gezaehlt_und_gemeldet(server_stub):
    """Was die bescheidene Auswertung nicht versteht (hier: Wochen, 'P2W'),
    gilt wie ein fehlendes Ende — UND wird gemeldet (K4-Ruling), statt
    kommentarlos als still 'frei' durchzugehen."""
    server_stub.rumpf = _ics(_vevent(
        "seltsam@irgendwer", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DURATION:P2W\r\nSUMMARY:Komische Dauer\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert len(termine) == 1
    assert termine[0]["ende"] == termine[0]["beginn"]
    assert fehler is not None
    assert "unlesbar" in fehler.lower()


def test_laengst_beendete_serie_macht_die_quelle_nicht_fuer_immer_zur_luecke(
        server_stub):
    """Koordinator-Fix-Runde (13.09.2026): der Serien-Zaehler lief bisher
    VOR dem Zeitfenster — eine Serie, deren einziger bekannter Anhaltspunkt
    (Master-DTSTART/-DTEND) vor Jahren lag, machte die Quelle damit
    DAUERHAFT zur Luecke: termin_konflikte haette fuer sie nie wieder
    frei: true gemeldet. Jetzt zaehlt nur, was im Fenster liegt."""
    server_stub.rumpf = _ics(_vevent(
        "uralte-serie@google", _ALT.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (_ALT + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=WEEKLY;UNTIL=" + (_ALT + _td(days=30)).strftime(
            "%Y%m%dT%H%M%SZ") + "\r\nSUMMARY:Laengst vorbei\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert fehler is None, fehler


def test_laengst_veraltete_unlesbare_dauer_macht_die_quelle_nicht_fuer_immer_zur_luecke(
        server_stub):
    """Dieselbe Korrektur fuer unlesbare DURATION: ein Jahre alter Termin
    mit unlesbarer Dauer soll nicht auf ewig als Luecke gemeldet werden,
    wenn er laengst ausserhalb jedes Planungsfensters liegt."""
    server_stub.rumpf = _ics(_vevent(
        "uralt-seltsam@irgendwer", _ALT.strftime("%Y%m%dT%H%M%SZ"),
        "DURATION:P2W\r\nSUMMARY:Uralt und komisch\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert fehler is None, fehler
