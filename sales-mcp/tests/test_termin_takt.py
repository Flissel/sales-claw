"""Taktgeber sales-termine (Meeting-Mittelpunkt Task 11).

Vexa, Ollama und Telegram sind per Monkeypatch ersetzt; die Datenbank ist
sales_test. Die Akten werden direkt eingetragen (der Abgleich aus
termin_akte ist in test_termin_akte.py geprueft und hier ein No-op).
"""
import hashlib
import json
import logging
import os
import signal
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auswertung  # noqa: E402
import betreiber_hinweis  # noqa: E402
import briefing  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402
import termin_akte  # noqa: E402
import termin_takt  # noqa: E402
import vexa  # noqa: E402

JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
MEET = "https://meet.google.com/abc-defg-hij"
ADRESSE = "kunde@firma.de"
PASSCODE = "PASS4711"
SEGMENT_TEXT = "GEHEIMTEXT zum Budget"
SCHLUESSEL = "SCHLUESSEL-xyz-123"
TELEGRAM: list[str] = []
SEGMENTE = [{"sprecher": "Karla", "beginn": "2099-01-09T12:01:00Z",
             "text": SEGMENT_TEXT, "sprache": "de"}]


class FakeVexa:
    def __init__(self):
        self.aufrufe: list[tuple] = []
        self.meeting = {"status": "requested", "grund": "", "ende_grund": ""}
        self.segmente = list(SEGMENTE)
        self.bot_fehler: Exception | None = None
        self.lesen_fehler: Exception | None = None
        self.holen_fehler: list[Exception] = []
        self.loeschen_fehler: list[Exception] = []
        self.loeschen_hook = None

    def anzahl(self, name):
        return sum(1 for a in self.aufrufe if a[0] == name)

    def bot_schicken(self, url):
        self.aufrufe.append(("bot", url))
        if self.bot_fehler:
            raise self.bot_fehler
        return {"meeting_id": 11, "plattform": "google_meet",
                "native_id": "abc-defg-hij", "status": "requested"}

    def meeting_lesen(self, mid):
        self.aufrufe.append(("lesen", mid))
        if self.lesen_fehler:
            raise self.lesen_fehler
        return dict(self.meeting)

    def segmente_holen(self, mid):
        self.aufrufe.append(("holen", mid))
        if self.holen_fehler:
            raise self.holen_fehler.pop(0)
        return list(self.segmente)

    def meeting_loeschen(self, mid):
        self.aufrufe.append(("loeschen", mid))
        if self.loeschen_hook:
            self.loeschen_hook(mid)
        if self.loeschen_fehler:
            raise self.loeschen_fehler.pop(0)

    def bot_stoppen(self, plattform, native_id):
        self.aufrufe.append(("stoppen", plattform))


@pytest.fixture
def fake(monkeypatch):
    f = FakeVexa()
    monkeypatch.setattr(vexa, "konfiguriert", lambda: True)
    for name in ("bot_schicken", "meeting_lesen", "segmente_holen",
                 "meeting_loeschen", "bot_stoppen"):
        monkeypatch.setattr(vexa, name, getattr(f, name))
    return f


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    monkeypatch.setenv("UI_BASIS_URL", "https://ui.example.test")
    monkeypatch.setenv("VEXA_API_KEY", SCHLUESSEL)
    monkeypatch.setattr(termin_akte, "abgleichen", lambda jetzt: {})
    monkeypatch.setattr(ollama, "erreichbar", lambda: False)
    TELEGRAM.clear()
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: TELEGRAM.append(text) or True)
    monkeypatch.setattr(termin_takt, "_zustand", {})
    yield


def _akte(uid="u1", beginn=None, ende=None, **spalten):
    beginn = beginn or JETZT + timedelta(hours=5)
    werte = {"uid": uid, "herkunft": "sales-claw", "beginn": beginn,
             "ende": ende or beginn + timedelta(hours=1), "titel": "Beratung",
             "thema": "Beratung bAV", "link": MEET, "plattform": "google_meet",
             "status": "geplant", **spalten}
    namen = list(werte)
    server._q(f"insert into termin_akten ({', '.join(namen)}) values "
              f"({', '.join(['%s'] * len(namen))}) returning uid",
              [werte[n] for n in namen])
    return uid


def _zeile(uid="u1"):
    return server._q("select * from termin_akten where uid = %s", (uid,))[0]


def _lead(email=ADRESSE, name="Karla Kunde", firma="Firma GmbH"):
    return str(server._q(
        "insert into leads (name, email, company, source) values (%s, %s, %s, 'Messe') "
        "returning id", (name, email, firma))[0]["id"])


def _teilnehmer(uid, lead=None, adresse=ADRESSE, grund=None):
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id, grund) "
              "values (%s, %s, 'Karla Kunde', 'gast', %s, %s) returning uid",
              (uid, adresse, lead, grund))


def _mitschrift(uid="u1", status="offen", **spalten):
    werte = {"uid": uid, "segmente": json.dumps(SEGMENTE),
             "auswertung_status": status, **spalten}
    namen = list(werte)
    marken = ["%s::jsonb" if n == "segmente" else "%s" for n in namen]
    return str(server._q(
        f"insert into termin_mitschriften ({', '.join(namen)}) values ({', '.join(marken)}) "
        "returning id", [werte[n] for n in namen])[0]["id"])


def _mit(uid="u1"):
    z = server._q("select * from termin_mitschriften where uid = %s", (uid,))
    return z[0] if z else None


# ---------- Briefing ----------

def test_briefing_30_min_vorher_und_hinweis_einmal(fake):
    lead = _lead()
    _akte("u1", beginn=JETZT + timedelta(minutes=29))
    _teilnehmer("u1", lead)
    _akte("u2", beginn=JETZT + timedelta(minutes=31))
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert a["briefing_md"] and a["briefing_stand"] and a["briefing_am"] is not None
    assert a["briefing_mit_ki"] is False
    assert a["hinweis_gesendet_am"] is not None
    assert len(TELEGRAM) == 1
    assert "ui.example.test/termine/u1" in TELEGRAM[0]
    assert ADRESSE not in TELEGRAM[0]
    assert _zeile("u2")["briefing_md"] is None and _zeile("u2")["hinweis_gesendet_am"] is None
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert len(TELEGRAM) == 1


def test_briefing_neu_bei_aenderung_ohne_zweiten_hinweis(fake, monkeypatch):
    lead = _lead()
    _akte("u1", beginn=JETZT + timedelta(minutes=20))
    _teilnehmer("u1", lead)
    erstellt = []
    echt = briefing.erstellen
    monkeypatch.setattr(briefing, "erstellen", lambda uid: erstellt.append(uid) or echt(uid))
    termin_takt.runde(JETZT)
    stand1 = _zeile("u1")["briefing_stand"]
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert len(erstellt) == 1                       # unveraendert: kein neues Briefing
    server._q("update leads set company = 'Andere AG' where id = %s returning id", (lead,))
    termin_takt.runde(JETZT + timedelta(seconds=60))
    assert len(erstellt) == 2
    assert _zeile("u1")["briefing_stand"] != stand1
    assert "Andere AG" in _zeile("u1")["briefing_md"]
    assert len(TELEGRAM) == 1           # kein zweiter Hinweis
    # Die Akte wurde geaendert (Task 5 leert briefing_stand): neu erstellen.
    server._q("update termin_akten set briefing_stand = null where uid = 'u1' returning uid")
    termin_takt.runde(JETZT + timedelta(seconds=90))
    assert len(erstellt) == 3 and _zeile("u1")["briefing_stand"]
    assert len(TELEGRAM) == 1


def test_hinweis_nur_bei_erfolgreichem_senden(fake, monkeypatch):
    _akte("u1", beginn=JETZT + timedelta(minutes=10))
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: False)
    termin_takt.runde(JETZT)
    assert _zeile("u1")["hinweis_gesendet_am"] is None
    assert _zeile("u1")["briefing_md"]
    gesendet = []
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: gesendet.append(text) or True)
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert len(gesendet) == 1 and _zeile("u1")["hinweis_gesendet_am"] is not None


def test_abgesagt_kein_briefing_kein_bot(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30),
          abgesagt_am=JETZT - timedelta(hours=1))
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert a["briefing_md"] is None and not TELEGRAM
    assert fake.anzahl("bot") == 0 and a["status"] == "geplant"


# ---------- Bot ----------

def test_bot_eine_minute_vorher_mit_festen_parametern(monkeypatch):
    anfragen = []

    def anfrage(methode, pfad, body=None, ok404=False):
        anfragen.append((methode, pfad, body))
        if methode == "POST":
            return {"id": 7, "platform": "google_meet",
                    "native_meeting_id": "abc-defg-hij", "status": "requested"}
        return {"meetings": [{"id": 7, "status": "requested", "data": {}}]}

    monkeypatch.setattr(vexa, "_anfrage", anfrage)
    monkeypatch.setattr(vexa, "konfiguriert", lambda: True)
    _akte("u1", beginn=JETZT + timedelta(seconds=61))
    termin_takt.runde(JETZT)
    assert not [a for a in anfragen if a[0] == "POST"]
    assert _zeile("u1")["status"] == "geplant"
    termin_takt.runde(JETZT + timedelta(seconds=1))       # genau 60 s davor
    post = [a for a in anfragen if a[0] == "POST"]
    assert len(post) == 1 and post[0][1] == "/bots"
    body = post[0][2]
    assert body["meeting_url"] == MEET
    assert body["bot_name"] == "VibeMind Mitschrift" and body["language"] == "de"
    assert body["recording_enabled"] is False
    assert body["automatic_leave"]["max_wait_for_admission"] == 1800000
    a = _zeile("u1")
    assert a["status"] == "wartet_auf_einlass"
    assert (a["vexa_meeting_id"], a["vexa_plattform"], a["vexa_native_id"]) == (
        7, "google_meet", "abc-defg-hij")
    assert a["bot_geschickt_am"] is not None
    termin_takt.runde(JETZT + timedelta(seconds=31))
    assert len([x for x in anfragen if x[0] == "POST"]) == 1   # kein zweiter Bot


def test_kein_bot_schalter(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30), kein_bot=True)
    termin_takt.runde(JETZT)
    assert fake.anzahl("bot") == 0 and _zeile("u1")["status"] == "geplant"


def test_kein_bot_bei_gesperrtem(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    _teilnehmer("u1", None, "weg@firma.de", grund="gesperrt")
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert fake.anzahl("bot") == 0
    assert a["status"] == "ohne_aufnahme" and a["status_grund"] == "gesperrter Teilnehmer"


def test_kein_link_kein_bot(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30), link=None, plattform=None,
          status="kein_link")
    _akte("u2", beginn=JETZT + timedelta(seconds=30), link=None, plattform=None)
    termin_takt.runde(JETZT)
    assert fake.anzahl("bot") == 0
    assert _zeile("u1")["status"] == "kein_link"


def test_taktgeber_spaet_gestartet_schickt_noch_waehrend_termin(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=10), ende=JETZT + timedelta(minutes=50))
    _akte("u2", beginn=JETZT - timedelta(minutes=70), ende=JETZT - timedelta(minutes=10))
    termin_takt.runde(JETZT)
    assert [a for a in fake.aufrufe if a[0] == "bot"] == [("bot", MEET)]
    assert _zeile("u1")["status"] == "wartet_auf_einlass"
    assert _zeile("u2")["status"] == "geplant"          # vorbei: kein Bot


def test_bot_startet_nicht_fehlgeschlagen(fake):
    fake.bot_fehler = vexa.VexaFehler("Vexa nicht erreichbar")
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert a["status"] == "fehlgeschlagen" and a["status_grund"] == "Bot konnte nicht starten"
    assert a["vexa_meeting_id"] is None


def test_ohne_vexa_schluessel_wartet_die_akte(fake, monkeypatch):
    monkeypatch.setattr(vexa, "konfiguriert", lambda: False)
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    termin_takt.runde(JETZT)
    assert fake.anzahl("bot") == 0 and _zeile("u1")["status"] == "geplant"


# ---------- Verfolgen ----------

def test_nicht_eingelassen_fehlgeschlagen(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="wartet_auf_einlass",
          vexa_meeting_id=7)
    fake.meeting = {"status": "failed", "grund": "nicht eingelassen", "ende_grund": ""}
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert a["status"] == "fehlgeschlagen" and a["status_grund"] == "nicht eingelassen"
    assert fake.anzahl("holen") == 0 and _mit() is None


def test_vexa_weg_beim_start_fehlgeschlagen(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="wartet_auf_einlass",
          vexa_meeting_id=7)
    fake.lesen_fehler = vexa.VexaNichtGefunden("weg")
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert a["status"] == "fehlgeschlagen"
    assert a["status_grund"] == "Meeting bei Vexa nicht mehr vorhanden"


def test_vexa_fehler_beim_verfolgen_aendert_nichts(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="laeuft", vexa_meeting_id=7)
    fake.lesen_fehler = vexa.VexaFehler("nicht erreichbar")
    termin_takt.runde(JETZT)
    assert _zeile("u1")["status"] == "laeuft" and _zeile("u1")["vexa_meeting_id"] == 7


def test_aktiv_setzt_laeuft_und_wartet_sonst(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="wartet_auf_einlass",
          vexa_meeting_id=7)
    fake.meeting = {"status": "active", "grund": "", "ende_grund": ""}
    termin_takt.runde(JETZT)
    assert _zeile("u1")["status"] == "laeuft"
    assert fake.anzahl("holen") == 0 and fake.anzahl("loeschen") == 0


def test_abholen_scheitert_bleibt_und_wiederholt(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    fake.holen_fehler = [vexa.VexaFehler("Vexa antwortet 500")]
    termin_takt.runde(JETZT)
    assert _mit() is None and fake.anzahl("loeschen") == 0
    a = _zeile("u1")
    assert a["status"] == "laeuft" and a["vexa_meeting_id"] == 7
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert _mit() is not None and _mit()["segmente"] == SEGMENTE
    assert fake.anzahl("loeschen") == 1
    a = _zeile("u1")
    assert a["status"] == "fertig" and a["vexa_meeting_id"] is None
    termin_takt.runde(JETZT + timedelta(seconds=60))
    assert fake.anzahl("loeschen") == 1                 # genau einmal


def test_loeschen_erst_nach_commit(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    reihenfolge = []

    def beim_loeschen(mid):
        # eigene Verbindung: sieht nur, was committet ist
        z = server._q("select a.status, (select count(*) from termin_mitschriften m "
                      "where m.uid = a.uid) as n from termin_akten a where a.uid = 'u1'")[0]
        reihenfolge.append((fake.aufrufe[-1][0], z["status"], z["n"]))

    fake.loeschen_hook = beim_loeschen
    termin_takt.runde(JETZT)
    assert reihenfolge == [("loeschen", "fertig", 1)]
    assert fake.aufrufe.index(("holen", 7)) < fake.aufrufe.index(("loeschen", 7))


def test_loeschen_scheitert_id_bleibt_und_naechste_runde_loescht_nach(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    fake.loeschen_fehler = [vexa.VexaFehler("x"), vexa.VexaFehler("x")]
    termin_takt.runde(JETZT)                 # Schritt 4 und Nachloeschen scheitern
    a = _zeile("u1")
    assert a["status"] == "fertig" and a["vexa_meeting_id"] == 7
    assert _mit() is not None and fake.anzahl("holen") == 1
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert _zeile("u1")["vexa_meeting_id"] is None
    assert fake.anzahl("holen") == 1         # nicht erneut abgeholt
    assert fake.anzahl("loeschen") == 3


def test_nachloeschen_bei_ohne_aufnahme(fake):
    _akte("u1", status="ohne_aufnahme", vexa_meeting_id=9)
    _akte("u2", status="fehlgeschlagen", vexa_meeting_id=10)
    termin_takt.runde(JETZT)
    assert fake.anzahl("loeschen") == 1
    assert _zeile("u1")["vexa_meeting_id"] is None
    assert _zeile("u1")["status"] == "ohne_aufnahme"


def test_null_segmente_leer(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    fake.segmente = []
    termin_takt.runde(JETZT)
    m = _mit()
    assert m["auswertung_status"] == "leer" and m["segmente"] == []
    assert _zeile("u1")["status"] == "fertig" and fake.anzahl("loeschen") == 1


# ---------- Auswerten ----------

def _ergebnis(**extra):
    a = auswertung._leer()
    a["kurzfassung"] = "Kurz und gut."
    a.update(extra)
    return a


def test_ollama_aus_auswertung_wartet(fake, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="sales-termine")
    _akte("u1", status="fertig")
    _mitschrift("u1")

    def nie(segmente):
        raise AssertionError("auswerten darf ohne Ollama nicht laufen")

    monkeypatch.setattr(auswertung, "auswerten", nie)
    for i in range(3):
        termin_takt.runde(JETZT + timedelta(seconds=30 * i))
    assert _mit()["auswertung_status"] == "offen"
    zeilen = [r for r in caplog.records if r.name == "sales-termine"
              and r.levelno <= logging.INFO and "Ollama" in r.getMessage()]
    assert len(zeilen) <= 1
    # Wechsel zurueck loggt wieder genau einmal
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis())
    termin_takt.runde(JETZT + timedelta(minutes=5))
    assert _mit()["auswertung_status"] == "fertig"


def test_auswertung_speichert_ergebnis_und_vorschlaege(fake, monkeypatch):
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    _akte("u2", status="fertig")
    _mitschrift("u2")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis(
        zusagen_felix=[{"text": "Angebot schicken", "datum": "2099-02-01"}]))
    termin_takt.runde(JETZT)
    m = _mit("u1")                       # aelteste zuerst, nur eine je Runde
    assert m["auswertung_status"] == "fertig" and m["auswertung_md"]
    assert m["auswertung_json"]["kurzfassung"] == "Kurz und gut."
    assert m["auswertung_am"] is not None and m["modell"]
    assert _mit("u2")["auswertung_status"] == "offen"
    v = server._q("select art, lead_id, daten from termin_vorschlaege "
                  "where mitschrift_id = %s order by art", (m["id"],))
    assert [x["art"] for x in v] == ["termin_ergebnis", "wiedervorlage"]
    assert all(str(x["lead_id"]) == lead for x in v)
    assert v[1]["daten"] == {"faellig_am": "2099-02-01", "notiz": "Angebot schicken"}


def test_auswertung_fehler_neuversuch_hoechstens_dreimal(fake, monkeypatch):
    _akte("u1", status="fertig")
    _mitschrift("u1")
    versuche = []

    def kaputt(segmente):
        versuche.append(1)
        raise ollama.OllamaFehler("kein JSON")

    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", kaputt)
    termin_takt.runde(JETZT)
    m = _mit()
    assert m["auswertung_status"] == "fehler" and m["auswertung_versuche"] == 1
    assert m["auswertung_am"] == JETZT
    termin_takt.runde(JETZT + timedelta(minutes=30))
    assert len(versuche) == 1                            # noch keine Stunde
    termin_takt.runde(JETZT + timedelta(minutes=61))
    assert len(versuche) == 2 and _mit()["auswertung_versuche"] == 2
    termin_takt.runde(JETZT + timedelta(hours=2, minutes=5))
    assert len(versuche) == 3 and _mit()["auswertung_versuche"] == 3
    termin_takt.runde(JETZT + timedelta(hours=9))
    assert len(versuche) == 3                            # Deckel
    assert _mit()["auswertung_status"] == "fehler"
    # Erfolg beim Neuversuch
    server._q("update termin_mitschriften set auswertung_versuche = 1 returning id")
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis())
    termin_takt.runde(JETZT + timedelta(hours=10))
    assert _mit()["auswertung_status"] == "fertig"


def test_zusammenfassung_nur_mit_schalter(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis(
        naechste_schritte=["Angebot senden"]))
    lead = _lead()
    _akte("u1", beginn=JETZT - timedelta(days=1), status="fertig")
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    termin_takt.runde(JETZT)
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    assert _mit("u1")["entwurf_id"] is None
    assert _mit("u1")["auswertung_status"] == "fertig"

    _akte("u2", beginn=datetime(2099, 1, 8, 9, 0, tzinfo=timezone.utc), status="fertig",
          will_zusammenfassung=True)
    _teilnehmer("u2", lead)
    _mitschrift("u2")
    termin_takt.runde(JETZT + timedelta(seconds=30))
    d = server._q("select id, status, channel, subject, body, thema, lead_id from drafts")
    assert len(d) == 1 and d[0]["status"] == "pending" and d[0]["channel"] == "email"
    assert d[0]["thema"] == "termin_zusammenfassung" and str(d[0]["lead_id"]) == lead
    assert d[0]["subject"] == "Zusammenfassung unseres Gesprächs vom 08.01.2099"
    assert d[0]["body"].startswith("Guten Tag Karla Kunde,")
    assert _mit("u2")["entwurf_id"] == d[0]["id"]


def test_zusammenfassung_ohne_verknuepften_kontakt_kein_draft(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis())
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _mitschrift("u1")
    termin_takt.runde(JETZT)
    assert _mit()["auswertung_status"] == "fertig"
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    assert server._q("select count(*) as n from termin_vorschlaege")[0]["n"] == 0


# ---------- Rundenverhalten und Log ----------

def test_schritt_fehler_stoppt_rest_nicht_und_loggt_keine_meldung(fake, monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def kaputt(jetzt):
        raise RuntimeError(f"Fehler mit {ADRESSE}")

    monkeypatch.setattr(termin_akte, "abgleichen", kaputt)
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    ergebnis = termin_takt.runde(JETZT)
    assert _zeile("u1")["status"] == "wartet_auf_einlass"
    assert ergebnis["abgleich"] == "fehler"
    assert ADRESSE not in caplog.text and "RuntimeError" in caplog.text


def test_fehler_einer_akte_stoppt_die_naechste_nicht(fake, monkeypatch):
    _akte("u1", beginn=JETZT + timedelta(seconds=10))
    _akte("u2", beginn=JETZT + timedelta(seconds=20))
    echt = termin_akte.hat_gesperrte

    def mal(uid):
        if uid == "u1":
            raise RuntimeError("kaputt")
        return echt(uid)

    monkeypatch.setattr(termin_akte, "hat_gesperrte", mal)
    termin_takt.runde(JETZT)
    assert _zeile("u2")["status"] == "wartet_auf_einlass"


def test_log_ohne_kundendaten(fake, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s: _ergebnis(
        kurzfassung=SEGMENT_TEXT, naechste_schritte=[SEGMENT_TEXT]))
    lead = _lead()
    link = f"{MEET}?pwd={PASSCODE}"
    uids = ["uid-geheim-1", "uid-geheim-2", "uid-geheim-3", "uid-geheim-4",
            "uid-geheim-5", "uid-geheim-6"]
    # Briefing + Hinweis
    _akte(uids[0], beginn=JETZT + timedelta(minutes=20), link=link, passcode=PASSCODE)
    _teilnehmer(uids[0], lead)
    # Bot
    _akte(uids[1], beginn=JETZT + timedelta(seconds=30), link=link, passcode=PASSCODE)
    # fertig melden + loeschen + auswerten + Zusammenfassung
    _akte(uids[2], beginn=JETZT - timedelta(hours=1), status="laeuft", vexa_meeting_id=7,
          link=link, passcode=PASSCODE, will_zusammenfassung=True)
    _teilnehmer(uids[2], lead)
    # nicht eingelassen
    _akte(uids[3], beginn=JETZT - timedelta(minutes=5), status="wartet_auf_einlass",
          vexa_meeting_id=8, link=link)
    # gesperrt
    _akte(uids[4], beginn=JETZT + timedelta(seconds=40), link=link)
    _teilnehmer(uids[4], None, ADRESSE, grund="gesperrt")
    # Vexa-Fehler im Start
    _akte(uids[5], beginn=JETZT + timedelta(seconds=50), link=link)
    orig = fake.bot_schicken
    folge = [None, vexa.VexaFehler(f"Vexa-Fehler {link}")]

    def bot(url):
        f = folge.pop(0) if folge else None
        if f:
            fake.aufrufe.append(("bot", url))
            raise f
        return orig(url)

    monkeypatch.setattr(vexa, "bot_schicken", bot)
    monkeypatch.setattr(vexa, "meeting_lesen", lambda mid: {
        7: {"status": "completed", "grund": "", "ende_grund": ""},
        8: {"status": "failed", "grund": "nicht eingelassen", "ende_grund": ""},
    }.get(mid, {"status": "active", "grund": "", "ende_grund": ""}))
    # Zweiter Bot (Nr. 5, gesperrt) schickt nie; Nr. 6 trifft den Fehler
    ergebnis = termin_takt.runde(JETZT)
    assert _zeile(uids[2])["status"] == "fertig"
    assert _mit(uids[2])["auswertung_status"] == "fertig"
    assert _zeile(uids[4])["status"] == "ohne_aufnahme"
    assert server._q("select count(*) as n from drafts")[0]["n"] == 1
    assert ergebnis
    text = caplog.text
    for verboten in (ADRESSE, "firma.de", PASSCODE, SEGMENT_TEXT, "GEHEIMTEXT",
                     SCHLUESSEL, "meet.google.com", "Karla"):
        assert verboten not in text, verboten
    eigene = "\n".join(r.getMessage() for r in caplog.records if r.name == "sales-termine")
    assert eigene
    for uid in uids:
        assert uid not in eigene
    assert hashlib.sha256(uids[2].encode()).hexdigest()[:8] in eigene


def test_main_einmal(monkeypatch):
    monkeypatch.setenv("TERMIN_EINMAL", "1")
    runden = []
    monkeypatch.setattr(termin_takt, "runde", lambda jetzt: runden.append(jetzt) or {})
    alt = signal.getsignal(signal.SIGTERM)
    try:
        assert termin_takt.main() == 0
    finally:
        signal.signal(signal.SIGTERM, alt)
        termin_takt.LOG.handlers.clear()
        termin_takt.LOG.propagate = True
    assert len(runden) == 1 and runden[0].tzinfo is not None


def test_takt_aus_umgebung(monkeypatch):
    monkeypatch.delenv("TERMIN_TAKT_S", raising=False)
    assert termin_takt._takt() == 30
    monkeypatch.setenv("TERMIN_TAKT_S", "7")
    assert termin_takt._takt() == 7
    for kaputt in ("0", "-3", "abc", "nan"):
        monkeypatch.setenv("TERMIN_TAKT_S", kaputt)
        assert termin_takt._takt() == 30
