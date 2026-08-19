"""Vertragstests fuer `termin_bestaetigen`, die ICS und den CalDAV-Weg.

Drei Dinge sind hier festgenagelt:

1. **Die Datei ist RFC-5545-konform.** Sie laesst sich hier nicht in einem
   Kalenderprogramm oeffnen (Container, kein Desktop) — gemessen wird
   deshalb gegen die Norm: CRLF, VTIMEZONE zur TZID-Referenz, Faltung auf
   75 Oktette, maskierte TEXT-Werte, UID/DTSTAMP/DTSTART/DTEND.
2. **Der Kalender-Eintrag ist Beiwerk.** Ohne Konfiguration entsteht nur
   die Datei; scheitert der Eintrag, entsteht die Datei trotzdem, und das
   Passwort steht in keinem Fehlertext.
3. **Es wird nichts versendet.** Kein Entwurf entsteht, keiner aendert sich
   — das Freigabe-Gate bleibt unberuehrt (Gate-Invariante).

Der CalDAV-Server ist ein `http.server`-Thread auf einem vom Betriebssystem
vergebenen Port (Muster aus test_dispatch.py). Es geht in diesen Tests zu
keinem Zeitpunkt eine Anfrage an einen echten Kalender.
"""
import base64
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# HART, nicht setdefault: eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die truncate-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402
import medien  # noqa: E402
import recherche  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# CalDAV-Stub
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
def leer(tmp_path, monkeypatch):
    # Kein Test schreibt je in das echte /reports des Betriebs.
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))
    # Und keiner spricht mit einem echten Kalender: die drei Variablen
    # werden fuer JEDEN Test geleert, wer sie braucht, setzt sie selbst.
    for name in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT"):
        monkeypatch.delenv(name, raising=False)
    STUB.zuruecksetzen()
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


@pytest.fixture
def kalender_konfiguriert(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", STUB_URL)
    monkeypatch.setenv("CALDAV_USER", "betreiber@example.org")
    monkeypatch.setenv("CALDAV_PASSWORT", "GEHEIMES-APP-PASSWORT")


def _heute():
    """UTC, nicht date.today() — gleiche Begruendung wie in test_uebergabe."""
    return datetime.now(timezone.utc).date()


def _morgen():
    return (_heute() + timedelta(days=1)).isoformat()


def _lead(name="Max Bestand"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491701234567', 'whatsapp') returning id", (name,))[0]["id"])


# Sentinel statt None/"" als Vorgabe: sonst koennte der Helfer einen leeren
# Datums- oder Zeitstring gar nicht durchreichen — und genau der gehoert
# geprueft.
_VORGABE = object()


def _termin(lead=None, datum=_VORGABE, uhrzeit="14:30", **kw):
    return json.loads(server.termin_bestaetigen(
        lead or _lead(), _morgen() if datum is _VORGABE else datum,
        uhrzeit, **kw))


def _ics(antwort):
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Die Datei
# ---------------------------------------------------------------------------

def test_datei_entsteht_im_reportordner_mit_geslugtem_namen(tmp_path):
    antwort = _termin(_lead(name="Müller & Söhne ../../etc/passwd"))
    assert os.path.dirname(antwort["pfad"]) == os.path.realpath(str(tmp_path))
    assert re.fullmatch(r"termin-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.ics",
                        os.path.basename(antwort["pfad"]))
    assert "mueller" in os.path.basename(antwort["pfad"])


def test_ics_traegt_die_pflichtbestandteile_von_rfc_5545():
    antwort = _termin(uhrzeit="14:30", dauer_minuten=90, thema="Erstgespraech")
    text = _ics(antwort)
    tag = (_heute() + timedelta(days=1)).strftime("%Y%m%d")

    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in text
    assert "PRODID:-//sales-claw//Terminbestaetigung//DE\r\n" in text
    assert "BEGIN:VEVENT\r\n" in text and "END:VEVENT\r\n" in text
    assert re.search(r"\r\nUID:[0-9a-f-]{36}@sales-claw\r\n", text)
    assert re.search(r"\r\nDTSTAMP:\d{8}T\d{6}Z\r\n", text)
    assert f"\r\nDTSTART;TZID=Europe/Berlin:{tag}T143000\r\n" in text
    assert f"\r\nDTEND;TZID=Europe/Berlin:{tag}T160000\r\n" in text
    assert "\r\nSTATUS:CONFIRMED\r\n" in text


def test_ics_traegt_kein_method_sonst_lehnt_caldav_sie_ab():
    """RFC 4791 §4.1: ein Kalenderobjekt auf einem CalDAV-Server darf KEINE
    METHOD-Eigenschaft tragen. RFC 5545 wuerde `METHOD:PUBLISH` in einer
    veroeffentlichten Datei erlauben — SabreDAV (PrivateEmail) weist den
    PUT damit aber mit HTTP 415 zurueck („A calendar object on a CalDAV
    server MUST NOT have a METHOD property", live gemessen 19.08.2026).
    Ohne die Zeile ist EINE Fassung beides: anhaengbare Datei und
    Kalendereintrag."""
    text = _ics(_termin())
    assert "METHOD" not in text
    # Die uebrigen Kopfzeilen bleiben, damit das kein stiller Kahlschlag ist.
    assert "CALSCALE:GREGORIAN\r\n" in text
    assert f"PRODID:{kalender.PRODID}\r\n" in text


def test_ics_hat_ausschliesslich_crlf_zeilenenden():
    """LF allein ist kein gueltiges Zeilenende (RFC 5545 §3.1) — und der
    gehaertete Schreiber uebersetzt nichts (`newline='\\n'`), die CRLF
    muessen also woertlich im Text stehen."""
    text = _ics(_termin())
    assert "\n" in text
    assert re.search(r"[^\r]\n", text) is None


def test_vtimezone_liegt_bei_sonst_lehnen_outlook_varianten_die_tzid_ab():
    text = _ics(_termin())
    assert "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\n" in text
    assert "END:VTIMEZONE\r\n" in text
    # Beide Uebergaenge, sonst ist die Zone nur die halbe Wahrheit.
    assert "BEGIN:DAYLIGHT\r\n" in text and "BEGIN:STANDARD\r\n" in text
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU" in text
    assert "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU" in text
    assert "TZOFFSETTO:+0200" in text and "TZOFFSETTO:+0100" in text
    # Die TZID-Referenz zeigt auf genau diesen Block.
    assert text.count("TZID:Europe/Berlin") == 1


def test_summary_nennt_thema_und_kontakt_location_nur_wenn_gesetzt():
    ohne = _ics(_termin(_lead(name="Anna Beispiel"), thema="Erstgespraech"))
    assert "\r\nSUMMARY:Erstgespraech — Anna Beispiel\r\n" in ohne
    # Nicht blosses „LOCATION" — der VTIMEZONE-Block traegt X-LIC-LOCATION.
    assert "\r\nLOCATION:" not in ohne

    mit = _ics(_termin(_lead(name="Anna Beispiel"), ort="Buero Regensburg"))
    assert "\r\nLOCATION:Buero Regensburg\r\n" in mit


def test_description_traegt_keine_bedarfsdaten():
    """Die Datei wandert im Zweifel zum Kunden — in der DESCRIPTION steht
    deshalb ein neutraler Satz und nichts aus dem Gespraech."""
    lead = _lead()
    server.bedarf_speichern(lead, "netto", "3800 netto")
    server.profil_aktualisieren(lead, "beruf", "Schreinermeister")
    text = _ics(_termin(lead))
    assert "DESCRIPTION:Termin mit unserem Haus." in text
    assert "3800" not in text and "Schreinermeister" not in text


@pytest.mark.parametrize("roh, erwartet", [
    ("Beratung, Vorsorge", r"SUMMARY:Beratung\, Vorsorge"),
    ("Termin; kurz", r"SUMMARY:Termin\; kurz"),
    ("Pfad\\Weg", r"SUMMARY:Pfad\\Weg"),
])
def test_text_werte_werden_nach_3_3_11_maskiert(roh, erwartet):
    text = _ics(_termin(_lead(name="X"), thema=roh))
    assert erwartet in text


def test_zeilenumbruch_im_thema_wird_zu_escape_und_reisst_die_datei_nicht():
    """Ein roher Umbruch mitten in einer Content-Line waere eine kaputte
    Datei — und der Text kommt aus einem Sprachmodell."""
    text = _ics(_termin(_lead(name="X"), thema="Zeile1\nZeile2"))
    assert r"SUMMARY:Zeile1\nZeile2 — X" in text
    for zeile in text.split("\r\n"):
        assert not zeile.startswith("Zeile2")


def test_lange_zeilen_werden_auf_75_oktette_gefaltet():
    text = _ics(_termin(_lead(name="Ä" * 40), thema="T" * 100))
    zeilen = text.split("\r\n")
    for zeile in zeilen:
        assert len(zeile.encode("utf-8")) <= 75, zeile
    # Faltung heisst: Folgezeile mit fuehrendem Leerzeichen — nicht Abschnitt.
    assert any(z.startswith(" ") for z in zeilen)
    # Und das Ergebnis ist wieder zusammensetzbar (Entfaltung).
    entfaltet = text.replace("\r\n ", "")
    assert "T" * 100 in entfaltet


def test_zweiter_termin_am_selben_tag_meldet_das_ueberschreiben():
    lead = _lead()
    erste = _termin(lead)
    assert erste["ueberschrieben"] is False
    zweite = _termin(lead)
    assert zweite["ueberschrieben"] is True
    assert zweite["pfad"] == erste["pfad"]


def test_schreibfehler_kostet_den_termin_nicht(monkeypatch):
    """Fehlt der Bind ./reports:/reports, ist der Termin trotzdem vereinbart
    — und die Wiedervorlage daran haengt der eigentliche Wert."""
    def _kaputt(*_a, **_kw):
        raise OSError("Read-only file system")

    monkeypatch.setattr(recherche, "report_schreiben", _kaputt)
    antwort = _termin()
    assert antwort.get("pfad") is None
    assert "reports" in antwort["fehler"]
    assert antwort["wiedervorlage"]["aktivitaets_id"]
    assert antwort["bestaetigungstext"]


# ---------------------------------------------------------------------------
# Eingaben
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("datum", ["26.08.2026", "2026-13-01", "morgen", ""])
def test_ungueltiges_datum_wird_abgelehnt(datum):
    antwort = _termin(datum=datum)
    assert "fehler" in antwort
    assert "pfad" not in antwort


@pytest.mark.parametrize("uhrzeit", ["14 Uhr", "25:00", "14:70", "2:30 pm", ""])
def test_ungueltige_uhrzeit_wird_abgelehnt(uhrzeit):
    antwort = _termin(uhrzeit=uhrzeit)
    assert "fehler" in antwort


def test_termin_in_der_vergangenheit_wird_abgelehnt_und_legt_nichts_an():
    gestern = (_heute() - timedelta(days=1)).isoformat()
    antwort = _termin(datum=gestern)
    assert "fehler" in antwort
    assert "Vergangenheit" in antwort["fehler"]
    assert server._q("select count(*) as n from activities")[0]["n"] == 0


def test_heute_ist_erlaubt_und_die_erinnerung_faellt_auf_heute():
    heute = _heute()
    antwort = _termin(datum=heute.isoformat())
    assert "fehler" not in antwort
    assert antwort["wiedervorlage"]["faellig_am"] == heute.isoformat()


@pytest.mark.parametrize("roh, erwartet", [
    (5, 15), (15, 15), (60, 60), (480, 480), (9999, 480),
    ("abc", 60), (None, 60),
])
def test_dauer_wird_gekappt_statt_abgelehnt(roh, erwartet):
    assert server._termin_dauer(roh) == erwartet


def test_gekappte_dauer_steht_in_der_ics():
    antwort = _termin(uhrzeit="09:00", dauer_minuten=9999)
    tag = (_heute() + timedelta(days=1)).strftime("%Y%m%d")
    # 480 Minuten ab 09:00 -> 17:00
    assert f"DTEND;TZID=Europe/Berlin:{tag}T170000" in _ics(antwort)
    assert antwort["termin"]["dauer_minuten"] == 480


def test_unbekannter_kontakt_faellt_sauber():
    antwort = json.loads(server.termin_bestaetigen(
        "00000000-0000-0000-0000-000000000000", _morgen(), "14:30"))
    assert "fehler" in antwort


def test_langes_thema_und_langer_ort_werden_gekuerzt():
    antwort = _termin(thema="T" * 500, ort="O" * 500)
    assert len(antwort["termin"]["thema"]) == server.TERMIN_TEXT_MAXLAENGE
    assert len(antwort["termin"]["ort"]) == server.TERMIN_TEXT_MAXLAENGE


# ---------------------------------------------------------------------------
# Wiedervorlage, Protokoll, Bestaetigungstext
# ---------------------------------------------------------------------------

def test_wiedervorlage_entsteht_am_vortag_und_ist_auffindbar():
    lead = _lead()
    datum = (_heute() + timedelta(days=10)).isoformat()
    antwort = _termin(lead, datum=datum, thema="Erstgespraech")

    faellig = (_heute() + timedelta(days=9)).isoformat()
    assert antwort["wiedervorlage"]["faellig_am"] == faellig
    zeilen = server._q("select payload from activities where lead_id = %s "
                       "and type = 'wiedervorlage'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["faellig_am"] == faellig
    assert "Terminerinnerung" in zeilen[0]["payload"]["notiz"]
    assert datum in zeilen[0]["payload"]["notiz"]


def test_termin_wird_als_aktivitaet_protokolliert():
    lead = _lead()
    antwort = _termin(lead, uhrzeit="08:15", thema="bAV-Gespraech",
                      ort="Buero")
    zeilen = server._q("select payload from activities where lead_id = %s "
                       "and type = 'termin'", (lead,))
    assert len(zeilen) == 1
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["uhrzeit"] == "08:15"
    assert nutzlast["thema"] == "bAV-Gespraech"
    assert nutzlast["pfad"] == antwort["pfad"]
    assert nutzlast["kalender"] == "nicht konfiguriert"


def test_bestaetigungstext_nennt_wochentag_datum_uhrzeit_und_ort():
    # Der naechste Mittwoch, nie ein festes Datum: ein fest verdrahteter Tag
    # waere ab dem Tag danach „Vergangenheit" und der Test rot.
    heute = _heute()
    mittwoch = heute + timedelta(days=(2 - heute.weekday()) % 7 or 7)
    antwort = _termin(datum=mittwoch.isoformat(), uhrzeit="14:30",
                      ort="Buero Regensburg", thema="Erstgespraech",
                      dauer_minuten=45)
    text = antwort["bestaetigungstext"]
    assert "Mittwoch" in text
    assert f"{mittwoch:%d.%m.%Y}" in text and "14:30" in text
    assert "Buero Regensburg" in text
    assert "45 Minuten" in text
    assert "Sie" in text and "Du " not in text


def test_bestaetigungstext_ist_nur_text_und_erzeugt_keinen_entwurf():
    """Gate-Invariante: das Werkzeug versendet nichts und legt nichts in die
    Freigabe-Queue — daraus einen Entwurf zu machen ist ein eigener,
    ausdruecklicher Schritt des Betreibers."""
    lead = _lead()
    server._q("insert into drafts (lead_id, channel, recipient, body, status) "
              "values (%s,'whatsapp','+491701234567','x','pending')", (lead,))
    _termin(lead)
    zeilen = server._q("select status, count(*) as n from drafts "
                       "group by status")
    assert [(z["status"], z["n"]) for z in zeilen] == [("pending", 1)]


# ---------------------------------------------------------------------------
# CalDAV (G1b)
# ---------------------------------------------------------------------------

def test_ohne_konfiguration_entsteht_nur_die_datei():
    antwort = _termin()
    assert antwort["kalender"] == "nicht konfiguriert"
    assert os.path.isfile(antwort["pfad"])
    assert STUB.aufrufe == []
    assert "nicht konfiguriert" in antwort["hinweis"]


@pytest.mark.parametrize("fehlt", ["CALDAV_URL", "CALDAV_USER",
                                   "CALDAV_PASSWORT"])
def test_halbe_konfiguration_bleibt_inert(kalender_konfiguriert, monkeypatch,
                                          fehlt):
    monkeypatch.delenv(fehlt)
    antwort = _termin()
    assert antwort["kalender"] == "nicht konfiguriert"
    assert STUB.aufrufe == []


def test_eingetragen_bei_201_mit_korrektem_put(kalender_konfiguriert):
    antwort = _termin()
    assert antwort["kalender"] == "eingetragen"
    assert len(STUB.aufrufe) == 1
    aufruf = STUB.aufrufe[0]
    assert re.fullmatch(r"/kalender/[0-9a-f-]{36}@sales-claw\.ics",
                        aufruf["pfad"])
    assert aufruf["content_type"] == "text/calendar; charset=utf-8"
    # „Nur anlegen, nie ueberschreiben" — ein fremder Termin unter derselben
    # UID darf nicht still ersetzt werden.
    assert aufruf["if_none_match"] == "*"
    entschluesselt = base64.b64decode(
        aufruf["authorization"].split(" ", 1)[1]).decode("utf-8")
    assert entschluesselt == "betreiber@example.org:GEHEIMES-APP-PASSWORT"
    # Was hochgeht, ist zeichengleich mit dem, was in der Datei steht.
    assert aufruf["rumpf"] == _ics(antwort)


@pytest.mark.parametrize("status", [200, 204])
def test_weitere_erfolgsstatus_gelten_als_eingetragen(kalender_konfiguriert,
                                                      status):
    STUB.status = status
    assert _termin()["kalender"] == "eingetragen"


def test_put_traegt_eine_eigene_kennung_statt_der_urllib_vorgabe(
        kalender_konfiguriert):
    """Betriebsvoraussetzung, kein Schmuck: die WAF von
    dav.privateemail.com beantwortet Anfragen mit der Vorgabe-Kennung von
    urllib pauschal mit 403 — auch mit gueltigen Zugangsdaten (gemessen
    19.08.2026, Messreihe im Kopf von kalender.py). Faellt dieser Header
    weg, ist der Kalenderweg tot, und der Fehlertext deutet auf ein
    Zugangsproblem, das es nicht gibt."""
    _termin()
    kennung = STUB.aufrufe[0]["user_agent"]
    assert kennung == kalender.CALDAV_USER_AGENT
    # Genau das ist die gesperrte Kennung.
    assert "urllib" not in kennung.lower()
    # Und die Kennung sagt, wer da schreibt — statt ein fremdes Produkt
    # vorzutaeuschen (gemessen: jede eigene Kennung genuegt der WAF).
    assert "sales-claw" in kennung


def test_kennung_ist_ueber_die_umgebung_umstellbar(kalender_konfiguriert,
                                                   monkeypatch):
    """Ein anderer Anbieter kann etwas anderes verlangen — der Vorgabewert
    ist der gemessene, nicht der einzig moegliche."""
    monkeypatch.setattr(kalender, "CALDAV_USER_AGENT", "Anderer-Client/2.0")
    _termin()
    assert STUB.aufrufe[0]["user_agent"] == "Anderer-Client/2.0"


def test_401_wird_zum_sprechenden_fehler_und_die_datei_bleibt(
        kalender_konfiguriert):
    STUB.status = 401
    STUB.rumpf = b"Unauthorized"
    antwort = _termin()
    assert antwort["kalender"].startswith("fehlgeschlagen: ")
    assert "401" in antwort["kalender"]
    assert "App-Passwort" in antwort["kalender"]
    assert os.path.isfile(antwort["pfad"])       # die Datei entsteht trotzdem
    assert antwort["wiedervorlage"]["aktivitaets_id"]


def test_403_nennt_dieselbe_ursache(kalender_konfiguriert):
    """Der gemessene Stand bei PrivateEmail (2026-08-19): DAV antwortet auf
    alles mit 403, obwohl derselbe Zugang fuer SMTP funktioniert."""
    STUB.status = 403
    antwort = _termin()
    assert "403" in antwort["kalender"]
    assert "CALDAV_USER" in antwort["kalender"]


def test_412_sagt_dass_nichts_ueberschrieben_wurde(kalender_konfiguriert):
    STUB.status = 412
    antwort = _termin()
    assert "412" in antwort["kalender"]
    assert "ueberschrieben" in antwort["kalender"]


def test_500_wird_zum_fehlertext(kalender_konfiguriert):
    STUB.status = 500
    antwort = _termin()
    assert "500" in antwort["kalender"]
    assert "KOLLEKTION" in antwort["kalender"]


def test_passwort_landet_in_keinem_fehlertext(kalender_konfiguriert):
    """Fremde Fehlerrumpfe spiegeln Anfragen manchmal zurueck."""
    STUB.status = 401
    STUB.rumpf = b"login failed for GEHEIMES-APP-PASSWORT"
    antwort = _termin()
    assert "GEHEIMES-APP-PASSWORT" not in json.dumps(antwort)
    assert "***" in antwort["kalender"]
    protokoll = server._q("select payload from activities "
                          "where type = 'termin'")
    assert "GEHEIMES-APP-PASSWORT" not in json.dumps(protokoll[0]["payload"])


def test_kalender_nicht_erreichbar_wird_zum_fehlertext(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", "http://127.0.0.1:1/kalender/")
    monkeypatch.setenv("CALDAV_USER", "u")
    monkeypatch.setenv("CALDAV_PASSWORT", "p")
    antwort = _termin()
    assert "nicht erreichbar" in antwort["kalender"]
    assert os.path.isfile(antwort["pfad"])


def test_kaputte_caldav_url_toetet_das_werkzeug_nicht(monkeypatch):
    """Lehre aus dispatch.py (T5a): `Request(...)` wirft schon beim
    Konstruieren, wenn die URL kein brauchbares Schema hat — und die
    Meldung traegt die volle URL samt Zugangsdaten."""
    monkeypatch.setenv("CALDAV_URL", "keine-url")
    monkeypatch.setenv("CALDAV_USER", "u")
    monkeypatch.setenv("CALDAV_PASSWORT", "GEHEIM")
    antwort = _termin()
    assert antwort["kalender"].startswith("fehlgeschlagen: ")
    assert "GEHEIM" not in json.dumps(antwort)
    assert os.path.isfile(antwort["pfad"])


def test_datei_schema_wird_gar_nicht_erst_abgeschickt(monkeypatch, tmp_path):
    """Ein Tippfehler in der .env darf kein PUT ins Dateisystem werden."""
    monkeypatch.setenv("CALDAV_URL", f"file://{tmp_path}/")
    monkeypatch.setenv("CALDAV_USER", "u")
    monkeypatch.setenv("CALDAV_PASSWORT", "p")
    antwort = _termin()
    assert "http(s)" in antwort["kalender"]
    assert STUB.aufrufe == []


def test_kalender_ist_kein_egress_zum_kunden(kalender_konfiguriert):
    """Der Eintrag geht ausschliesslich an die konfigurierte CALDAV_URL —
    nie an eine Adresse aus Lead- oder Kundendaten."""
    _termin(_lead(name="Max mit https://boese.example/dav/ im Namen"))
    assert len(STUB.aufrufe) == 1
    assert STUB.aufrufe[0]["pfad"].startswith("/kalender/")


# ---------------------------------------------------------------------------
# Registrierung, Whitelist
# ---------------------------------------------------------------------------

def test_werkzeug_ist_registriert_und_die_signatur_ueberlebt_den_dekorator():
    import inspect
    assert server.termin_bestaetigen in server.WERKZEUGE
    parameter = inspect.signature(server.termin_bestaetigen).parameters
    assert list(parameter) == ["lead_id", "datum", "uhrzeit", "dauer_minuten",
                               "thema", "ort"]
    assert parameter["dauer_minuten"].default == 60
    assert parameter["thema"].default == "Erstgespraech"


def test_ics_ist_anhaengbar_und_geht_als_dokument(tmp_path, monkeypatch):
    """Die erzeugte Datei muss der Betreiber nach media\\ kopieren koennen —
    sonst waere der dokumentierte Weg nicht gangbar."""
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    (tmp_path / "termin-max-2026-08-26.ics").write_text(
        "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", encoding="utf-8")
    basis, fehler = medien.pruefe("termin-max-2026-08-26.ics")
    assert fehler is None
    assert basis == "termin-max-2026-08-26.ics"
    assert medien.endpunkt_und_typ(basis) == ("send-document", "text/calendar")
