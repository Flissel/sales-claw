"""Abonnierte Fremdkalender holen und zerlegen — ohne Netz."""
import threading
import time
from zoneinfo import ZoneInfo
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


def test_woechentliche_serie_wird_aufgeloest(server_stub):
    """Task 3: eine RRULE ergibt einzelne Vorkommen, je mit eigener UID
    (Serien-UID + '#' + Beginn) — und keinen Hinweis mehr."""
    start = _dt.now(_tz.utc).replace(microsecond=0) - _td(days=1)
    server_stub.rumpf = _ics(_vevent(
        "teamrunde@google", start.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (start + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Teamrunde\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert len(termine) == 3, termine
    uids = [t["uid"] for t in termine]
    assert len(set(uids)) == 3
    assert all(u.startswith("teamrunde@google#") for u in uids)
    assert {t["titel"] for t in termine} == {"Teamrunde"}


def test_ausnahme_exdate_fehlt(server_stub):
    start = _dt.now(_tz.utc).replace(microsecond=0) - _td(days=1)
    ausnahme = start + _td(days=7)
    server_stub.rumpf = _ics(_vevent(
        "serie@google", start.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (start + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\n"
        "EXDATE:" + ausnahme.strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "SUMMARY:Serie\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert len(termine) == 2
    assert ausnahme not in [t["beginn"] for t in termine]


def test_ganztaegig_value_date(server_stub):
    server_stub.rumpf = _ics(
        "BEGIN:VEVENT\r\nUID:tag@google\r\n"
        "DTSTART;VALUE=DATE:20261110\r\nDTEND;VALUE=DATE:20261111\r\n"
        "SUMMARY:Ganzer Tag\r\nEND:VEVENT\r\n")
    termine, fehler = kalenderquellen.hole(
        server_stub.url, tage_zurueck=3650, tage_voraus=3650)
    assert fehler is None, fehler
    assert len(termine) == 1
    t = termine[0]
    assert t["ganztaegig"] is True
    zone = kalenderquellen.kalender.ortszone() or _tz.utc
    assert t["beginn"].tzinfo is not None
    assert t["beginn"].astimezone(zone).replace(tzinfo=None) == _dt(2026, 11, 10)
    assert t["ende"].astimezone(zone).replace(tzinfo=None) == _dt(2026, 11, 11)


def test_gewoehnlicher_termin_ist_nicht_ganztaegig_und_nicht_frei(server_stub):
    server_stub.rumpf = _ics(_vevent(
        "normal@google", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (_BALD + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        + "\r\nSUMMARY:Normal\r\n"))
    termine, _ = kalenderquellen.hole(server_stub.url)
    assert termine[0]["ganztaegig"] is False
    assert termine[0]["frei"] is False
    assert "#" not in termine[0]["uid"]


def test_transparent_ist_frei(server_stub):
    server_stub.rumpf = _ics(_vevent(
        "geburtstag@google", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (_BALD + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        + "\r\nTRANSP:TRANSPARENT\r\nSUMMARY:Geburtstag\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert termine[0]["frei"] is True


def test_serie_neben_normalem_termin_behaelt_beide(server_stub):
    server_stub.rumpf = _ics(
        _vevent("normal@google", _BALD.strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (_BALD + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ")
               + "\r\nSUMMARY:Normaler Termin\r\n"),
        _vevent("serie@google",
               (_BALD + _td(days=1)).strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (_BALD + _td(days=1, hours=1)).strftime(
                   "%Y%m%dT%H%M%SZ") + "\r\nRRULE:FREQ=DAILY;COUNT=2\r\n"
               "SUMMARY:Serie\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert [t["titel"] for t in termine] == [
        "Normaler Termin", "Serie", "Serie"]


def test_kaputtes_ical_wirft_nicht_und_nennt_keine_adresse(server_stub):
    server_stub.rumpf = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
                         b"DTSTART:kaputt\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert fehler, "ein kaputter Kalender muss gemeldet werden"
    assert server_stub.url not in fehler


def test_unlesbares_vorkommen_wird_gemeldet_und_der_gute_bleibt(
        server_stub, monkeypatch):
    gut = _BALD
    schlecht = _BALD + _td(days=1)
    server_stub.rumpf = _ics(
        _vevent("gut@google", gut.strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (gut + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ")
               + "\r\nSUMMARY:Gut\r\n"),
        _vevent("schlecht@google", schlecht.strftime("%Y%m%dT%H%M%SZ"),
               "DTEND:" + (schlecht + _td(hours=1)).strftime(
                   "%Y%m%dT%H%M%SZ") + "\r\nSUMMARY:Geheimer Titel\r\n"))
    echt = kalenderquellen._ortszeit_utc

    def zickig(wert, zone):
        if wert.date() == schlecht.date():
            raise ValueError("kaputt")
        return echt(wert, zone)

    monkeypatch.setattr(kalenderquellen, "_ortszeit_utc", zickig)
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert [t["titel"] for t in termine] == ["Gut"]
    assert fehler and "1 Termin nicht lesbar" in fehler
    assert "Geheimer Titel" not in fehler and server_stub.url not in fehler


def test_obergrenze_fuer_vorkommen_kappt_und_meldet(server_stub, monkeypatch):
    monkeypatch.setattr(kalenderquellen, "MAX_VORKOMMEN", 5)
    start = _dt.now(_tz.utc).replace(microsecond=0) - _td(days=1)
    server_stub.rumpf = _ics(_vevent(
        "viele@google", start.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (start + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=DAILY;COUNT=20\r\nSUMMARY:Viele\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert len(termine) == 5
    assert fehler and "5" in fehler


def test_feindliche_sekundenserie_haelt_hole_nicht_auf(server_stub):
    start = _dt.now(_tz.utc).replace(microsecond=0)
    server_stub.rumpf = _ics(_vevent(
        "boese@google", start.strftime("%Y%m%dT%H%M%SZ"),
        "RRULE:FREQ=SECONDLY\r\nSUMMARY:Boese\r\n"))
    t0 = time.monotonic()
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert time.monotonic() - t0 < 30
    assert len(termine) == kalenderquellen.MAX_VORKOMMEN
    assert fehler


def test_tzid_beginn_wird_korrekt_nach_utc_umgerechnet(server_stub):
    tag = (_BALD + _td(days=1)).date()
    server_stub.rumpf = _ics(
        "BEGIN:VEVENT\r\nUID:berlin@google\r\n"
        f"DTSTART;TZID=Europe/Berlin:{tag:%Y%m%d}T140000\r\n"
        f"DTEND;TZID=Europe/Berlin:{tag:%Y%m%d}T150000\r\n"
        "SUMMARY:Berlin\r\nEND:VEVENT\r\n")
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    erwartet = _dt(tag.year, tag.month, tag.day, 14,
                   tzinfo=ZoneInfo("Europe/Berlin")).astimezone(_tz.utc)
    assert termine[0]["beginn"] == erwartet
    assert termine[0]["beginn"].utcoffset() == _td(0)


def test_ganztaegiger_geburtstag_ist_ganztaegig_und_frei(server_stub):
    tag = (_BALD + _td(days=1)).date()
    server_stub.rumpf = _ics(
        "BEGIN:VEVENT\r\nUID:geb@google\r\n"
        f"DTSTART;VALUE=DATE:{tag:%Y%m%d}\r\n"
        f"DTEND;VALUE=DATE:{(tag + _td(days=1)):%Y%m%d}\r\n"
        "TRANSP:TRANSPARENT\r\nSUMMARY:Geburtstag\r\nEND:VEVENT\r\n")
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert termine[0]["ganztaegig"] is True and termine[0]["frei"] is True


def test_serien_uid_ueber_120_zeichen_bleibt_je_vorkommen_eindeutig(
        server_stub):
    start = _dt.now(_tz.utc).replace(microsecond=0) - _td(days=1)
    lange_uid = "x" * 150 + "@google"
    server_stub.rumpf = _ics(_vevent(
        lange_uid, start.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + (start + _td(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
        "RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Lang\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    uids = [t["uid"] for t in termine]
    assert len(uids) == 3 and len(set(uids)) == 3
    assert all("#" in u for u in uids)


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


def test_wochen_duration_wird_gelesen(server_stub):
    """'P2W' war fuer den alten Handparser unlesbar; `icalendar` versteht
    es (Task 3: die Warnung zu unlesbarer Dauer entfaellt damit)."""
    server_stub.rumpf = _ics(_vevent(
        "wochen@irgendwer", _BALD.strftime("%Y%m%dT%H%M%SZ"),
        "DURATION:P2W\r\nSUMMARY:Zwei Wochen\r\n"))
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert len(termine) == 1
    assert termine[0]["ende"] - termine[0]["beginn"] == _td(weeks=2)


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
