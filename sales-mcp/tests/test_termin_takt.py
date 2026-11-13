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
from zoneinfo import ZoneInfo  # noqa: E402

# Die echten Funktionen, bevor die Fixture sie ersetzt (Final-Review I3/I9).
ECHT_ABGLEICHEN = termin_akte.abgleichen
ECHT_ERREICHBAR = ollama.erreichbar
ECHT_SENDEN = betreiber_hinweis.senden

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
        self.bot_hook = None
        self.lesen_hook = None
        self.holen_hook = None

    def anzahl(self, name):
        return sum(1 for a in self.aufrufe if a[0] == name)

    def bot_schicken(self, url):
        self.aufrufe.append(("bot", url))
        if self.bot_fehler:
            raise self.bot_fehler
        if self.bot_hook:
            self.bot_hook()
        return {"meeting_id": 11, "plattform": "google_meet",
                "native_id": "abc-defg-hij", "status": "requested"}

    def meeting_lesen(self, mid):
        self.aufrufe.append(("lesen", mid))
        if self.lesen_fehler:
            raise self.lesen_fehler
        if self.lesen_hook:
            self.lesen_hook(mid)
        return dict(self.meeting)

    def segmente_holen(self, mid):
        self.aufrufe.append(("holen", mid))
        if self.holen_hook:
            self.holen_hook(mid)
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
        self.aufrufe.append(("stoppen", plattform, native_id))


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
    u2 = _zeile("u2")                                   # vorbei: kein Bot
    assert (u2["status"], u2["status_grund"]) == ("ohne_aufnahme", "Termin vorbei ohne Bot")


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
    assert fake.anzahl("loeschen") == 2                 # auch fehlgeschlagen (Ruling 8)
    assert _zeile("u1")["vexa_meeting_id"] is None
    assert _zeile("u1")["status"] == "ohne_aufnahme"
    assert _zeile("u2")["vexa_meeting_id"] is None
    assert _zeile("u2")["status"] == "fehlgeschlagen"


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

    def nie(segmente, bilder=None):
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
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis())
    termin_takt.runde(JETZT + timedelta(minutes=5))
    assert _mit()["auswertung_status"] == "fertig"
    zurueck = [r for r in caplog.records if r.name == "sales-termine"
               and r.getMessage().startswith("Ollama erreichbar")]
    assert len(zurueck) == 1


def test_auswertung_speichert_ergebnis_und_vorschlaege(fake, monkeypatch):
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    _akte("u2", status="fertig")
    _mitschrift("u2")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis(
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

    def kaputt(segmente, bilder=None):
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
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis())
    termin_takt.runde(JETZT + timedelta(hours=10))
    assert _mit()["auswertung_status"] == "fertig"


def test_zusammenfassung_nur_mit_schalter(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis(
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
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis())
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _mitschrift("u1")
    termin_takt.runde(JETZT)
    assert _mit()["auswertung_status"] == "fertig"
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    assert server._q("select count(*) as n from termin_vorschlaege")[0]["n"] == 0


def test_internes_gespraech_kein_entwurf_aber_vorschlaege(fake, monkeypatch):
    # art "intern": keine Zusammenfassung an einen Kunden, auch mit Schalter;
    # Ergebnis und Wiedervorlagen fuer Felix entstehen trotzdem.
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis(
        art="intern", zusagen_felix=[{"text": "Board zeigen", "datum": "2099-02-01",
                                      "segment": 3}]))
    lead = _lead()
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    termin_takt.runde(JETZT)
    m = _mit("u1")
    assert m["auswertung_status"] == "fertig" and m["entwurf_id"] is None
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    v = server._q("select art from termin_vorschlaege where mitschrift_id = %s order by art",
                  (m["id"],))
    assert [x["art"] for x in v] == ["termin_ergebnis", "wiedervorlage"]


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
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis(
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
    # I7a: solange ein Termin mit Bot ansteht/laeuft, wartet die Auswertung
    assert ergebnis["auswerten"] == 0 and _mit(uids[2])["auswertung_status"] == "offen"
    server._q("update termin_akten set abgesagt_am = now() where uid <> %s returning uid",
              (uids[2],))
    termin_takt.runde(JETZT + timedelta(seconds=30))
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


# ---------- Fix-Runde 1 ----------

def test_briefing_ki_wird_nachgeholt_ohne_zweiten_hinweis(fake, monkeypatch):
    lead = _lead()
    _akte("u1", beginn=JETZT + timedelta(minutes=20))
    _teilnehmer("u1", lead)
    termin_takt.runde(JETZT)                                  # Ollama aus
    assert _zeile("u1")["briefing_mit_ki"] is False and len(TELEGRAM) == 1
    aufrufe = []
    monkeypatch.setattr(ollama, "erreichbar", lambda: aufrufe.append(1) or True)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: "Kurzer KI-Text.")
    termin_takt.runde(JETZT + timedelta(seconds=30))          # I7b: noch Pause
    assert _zeile("u1")["briefing_mit_ki"] is False
    termin_takt.runde(JETZT + timedelta(minutes=6))
    assert _zeile("u1")["briefing_mit_ki"] is True
    assert "Kurzer KI-Text." in _zeile("u1")["briefing_md"]
    assert len(TELEGRAM) == 1
    termin_takt.runde(JETZT + timedelta(minutes=6, seconds=30))   # mit KI: nichts mehr
    assert len(TELEGRAM) == 1


def test_bot_claim_verhindert_zweiten_bot(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    termin_takt._bot_starten("u1", MEET, JETZT)
    termin_takt._bot_starten("u1", MEET, JETZT)               # zweiter, "gleichzeitiger" Lauf
    termin_takt._bot(JETZT)
    assert fake.anzahl("bot") == 1
    assert _zeile("u1")["status"] == "wartet_auf_einlass"


def test_bot_gestartet_speichern_scheitert_raeumt_auf(fake, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    echt = termin_akte.status_wechseln

    def kaputt(uid, von, nach, grund="", **felder):
        if "vexa_meeting_id" in felder:
            raise RuntimeError(f"DB weg {ADRESSE}")
        return echt(uid, von, nach, grund, **felder)

    monkeypatch.setattr(termin_akte, "status_wechseln", kaputt)
    termin_takt._bot_starten("u1", MEET, JETZT)
    assert fake.anzahl("bot") == 1
    assert fake.anzahl("stoppen") == 1 and fake.anzahl("loeschen") == 1
    warn = [r for r in caplog.records if r.name == "sales-termine"
            and r.levelno == logging.WARNING]
    assert warn and "RuntimeError" in warn[0].getMessage()
    assert ADRESSE not in caplog.text
    assert _zeile("u1")["status"] == "wartet_auf_einlass"     # kein zweiter Bot
    termin_takt._bot(JETZT)
    assert fake.anzahl("bot") == 1


def test_nach_ende_ohne_bot_wird_ohne_aufnahme(fake, monkeypatch):
    vorbei = JETZT - timedelta(hours=2)
    _akte("u1", beginn=vorbei, kein_bot=True)
    _akte("u2", beginn=vorbei)
    monkeypatch.setattr(vexa, "konfiguriert", lambda: True)
    termin_takt.runde(JETZT)
    a = _zeile("u1")
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "kein Bot gewuenscht")
    a = _zeile("u2")                                          # Vexa da, trotzdem vorbei
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Termin vorbei ohne Bot")
    _akte("u3", beginn=vorbei)
    monkeypatch.setattr(vexa, "konfiguriert", lambda: False)
    termin_takt.runde(JETZT)
    a = _zeile("u3")
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Vexa nicht konfiguriert")
    assert fake.anzahl("bot") == 0


def test_ablegen_zweite_anweisung_scheitert_rollt_insert_zurueck(fake, monkeypatch):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    echt = server.pool.connection

    class Verbindung:
        def __init__(self, conn):
            self._c = conn

        def __getattr__(self, name):
            return getattr(self._c, name)

        def execute(self, sql, *a, **k):
            if sql.lstrip().startswith("update termin_akten"):
                raise RuntimeError("zweite Anweisung scheitert")
            return self._c.execute(sql, *a, **k)

    class Huelle:
        def __init__(self):
            self._cm = echt()

        def __enter__(self):
            return Verbindung(self._cm.__enter__())

        def __exit__(self, *a):
            return self._cm.__exit__(*a)

    with monkeypatch.context() as mp:
        mp.setattr(server.pool, "connection", lambda *a, **k: Huelle())
        termin_takt.runde(JETZT)
    assert fake.anzahl("holen") == 1 and fake.anzahl("loeschen") == 0
    assert _mit() is None                                     # Insert zurueckgerollt
    assert _zeile("u1")["status"] == "laeuft" and _zeile("u1")["vexa_meeting_id"] == 7


def test_ablegen_nur_aus_laeuft_oder_wartet(fake):
    _akte("u1", status="fehlgeschlagen")
    assert termin_takt._mitschrift_ablegen("u1", SEGMENTE) is False
    assert _mit() is None and _zeile("u1")["status"] == "fehlgeschlagen"


def test_vorschlaege_scheitern_einmal_fehler_kein_doppelter_entwurf(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: _ergebnis())
    lead = _lead()
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    echt = auswertung.vorschlaege
    folge = [True]

    def vorschlaege(a, ids, heute=None):
        if folge:
            folge.pop()
            return [{"art": "ungueltig", "lead_id": lead, "daten": {}}]   # verletzt check
        return echt(a, ids, heute)

    monkeypatch.setattr(auswertung, "vorschlaege", vorschlaege)
    termin_takt.runde(JETZT)
    m = _mit()
    assert m["auswertung_status"] == "fehler" and m["auswertung_versuche"] == 1
    assert m["auswertung_am"] == JETZT and m["auswertung_json"] is None
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    termin_takt.runde(JETZT + timedelta(minutes=30))          # Deckel: noch keine Stunde
    assert _mit()["auswertung_versuche"] == 1
    termin_takt.runde(JETZT + timedelta(minutes=61))
    assert _mit()["auswertung_status"] == "fertig"
    assert server._q("select count(*) as n from drafts")[0]["n"] == 1
    termin_takt.runde(JETZT + timedelta(hours=5))
    assert server._q("select count(*) as n from drafts")[0]["n"] == 1


def test_entwurf_scheitert_keine_neue_auswertung(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    zaehler = []
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: zaehler.append(1) or _ergebnis())

    def kaputt(*a, **k):
        raise RuntimeError("Entwurf kaputt")

    monkeypatch.setattr(server, "_entwurf_erstellen", kaputt)
    lead = _lead()
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    termin_takt.runde(JETZT)
    termin_takt.runde(JETZT + timedelta(hours=3))
    assert len(zaehler) == 1
    m = _mit()
    assert m["auswertung_status"] == "fertig" and m["entwurf_id"] is None


def test_gesperrt_ist_oeffentlich():
    assert briefing.gesperrt({"email": "", "phone": "", "enrichment": {}}) is False


# ---------- Final-Review C1/I2: nur der Taktgeber spricht mit Vexa ----------

VEXA_IDS = {"vexa_meeting_id": 11, "vexa_plattform": "google_meet",
            "vexa_native_id": "abc-defg-hij"}


def _ids(uid="u1"):
    a = _zeile(uid)
    return a["vexa_meeting_id"], a["vexa_plattform"], a["vexa_native_id"]


def _fake_einsetzen(monkeypatch) -> FakeVexa:
    f = FakeVexa()
    monkeypatch.setenv("VEXA_API_KEY", SCHLUESSEL)
    for name in ("bot_schicken", "meeting_lesen", "segmente_holen",
                 "meeting_loeschen", "bot_stoppen"):
        monkeypatch.setattr(vexa, name, getattr(f, name))
    return f


def _stopp_und_loeschen(f):
    return [a for a in f.aufrufe if a[0] in ("stoppen", "loeschen")]


def test_c1_ohne_aufnahme_ohne_vexa_schluessel_taktgeber_stoppt_bot(monkeypatch):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="laeuft", **VEXA_IDS)
    _mitschrift("u1")
    monkeypatch.delenv("VEXA_API_KEY")              # wie in sales-ui: kein Schluessel
    termin_akte.aufnahme_beenden("u1", "Kunde hat abgelehnt")
    assert _zeile()["status"] == "ohne_aufnahme" and _mit() is None
    assert _ids() == (11, "google_meet", "abc-defg-hij")
    f = _fake_einsetzen(monkeypatch)
    termin_takt.runde(JETZT)
    assert _stopp_und_loeschen(f) == [("stoppen", "google_meet", "abc-defg-hij"),
                                      ("loeschen", 11)]
    assert _ids() == (None, None, None) and _zeile()["status"] == "ohne_aufnahme"
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert f.anzahl("stoppen") == 1 and f.anzahl("loeschen") == 1


def test_c1_loeschantrag_ohne_vexa_schluessel_taktgeber_stoppt_bot(monkeypatch):
    lead = _lead()
    _akte("u1", beginn=JETZT - timedelta(minutes=1), status="wartet_auf_einlass", **VEXA_IDS)
    _teilnehmer("u1", lead)
    monkeypatch.delenv("VEXA_API_KEY")              # wie in sales-mcp
    assert "fehler" not in json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    a = _zeile()
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Löschantrag eines Teilnehmers")
    assert _ids() == (11, "google_meet", "abc-defg-hij")
    f = _fake_einsetzen(monkeypatch)
    termin_takt.runde(JETZT)
    assert _stopp_und_loeschen(f) == [("stoppen", "google_meet", "abc-defg-hij"),
                                      ("loeschen", 11)]
    assert _ids() == (None, None, None)


def test_c1_stoppen_scheitert_ids_bleiben_und_neuversuch(fake, monkeypatch):
    _akte("u1", status="ohne_aufnahme", **VEXA_IDS)
    folge = [vexa.VexaFehler("500")]

    def stoppen(p, n):
        fake.aufrufe.append(("stoppen", p, n))
        if folge:
            raise folge.pop(0)

    monkeypatch.setattr(vexa, "bot_stoppen", stoppen)
    termin_takt._nachloeschen(JETZT)
    assert _ids() == (11, "google_meet", "abc-defg-hij") and fake.anzahl("loeschen") == 0
    termin_takt._nachloeschen(JETZT + timedelta(seconds=30))
    assert _ids() == (None, None, None)
    assert fake.anzahl("stoppen") == 2 and fake.anzahl("loeschen") == 1


def test_i2_nein_waehrend_bot_schicken_bot_wird_gestoppt(fake):
    _akte("u1", beginn=JETZT + timedelta(seconds=30))
    fake.bot_hook = lambda: termin_akte.aufnahme_beenden("u1", "Kunde hat abgelehnt")
    termin_takt._bot(JETZT)
    a = _zeile()
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Kunde hat abgelehnt")
    assert _ids() == (11, "google_meet", "abc-defg-hij")      # Ids nie verlieren
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert _stopp_und_loeschen(fake) == [("stoppen", "google_meet", "abc-defg-hij"),
                                         ("loeschen", 11)]
    assert _ids() == (None, None, None) and _zeile()["status"] == "ohne_aufnahme"
    assert fake.anzahl("bot") == 1


def test_i2_verfolgen_nach_nein_aendert_status_nicht(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="wartet_auf_einlass", **VEXA_IDS)
    fake.meeting = {"status": "active", "grund": "", "ende_grund": ""}
    fake.lesen_hook = lambda mid: termin_akte.aufnahme_beenden("u1", "Kunde hat abgelehnt")
    termin_takt._verfolgen(JETZT)
    assert _zeile()["status"] == "ohne_aufnahme"


def test_i2_failed_nach_nein_aendert_status_nicht(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=5), status="laeuft", **VEXA_IDS)
    fake.meeting = {"status": "failed", "grund": "x", "ende_grund": ""}
    fake.lesen_hook = lambda mid: termin_akte.aufnahme_beenden("u1", "Kunde hat abgelehnt")
    termin_takt._verfolgen(JETZT)
    a = _zeile()
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Kunde hat abgelehnt")


def test_i2_completed_nach_nein_keine_mitschrift(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", **VEXA_IDS)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    fake.holen_hook = lambda mid: termin_akte.aufnahme_beenden("u1", "Kunde hat abgelehnt")
    termin_takt._verfolgen(JETZT)
    assert _mit() is None
    assert _zeile()["status"] == "ohne_aufnahme" and _zeile()["vexa_meeting_id"] == 11
    termin_takt._nachloeschen(JETZT)
    assert fake.anzahl("loeschen") == 1 and _ids() == (None, None, None)
    assert server._q("select count(*) as n from termin_mitschriften")[0]["n"] == 0


def test_i2_ablegen_sperrt_die_akte(fake):
    _akte("u1", status="ohne_aufnahme")
    assert termin_takt._mitschrift_ablegen("u1", SEGMENTE) is False
    assert _mit() is None and _zeile()["status"] == "ohne_aufnahme"


def test_fertig_vergisst_die_bot_kennung(fake):
    _akte("u1", beginn=JETZT - timedelta(minutes=60), status="laeuft", **VEXA_IDS)
    fake.meeting = {"status": "completed", "grund": "", "ende_grund": ""}
    fake.loeschen_fehler = [vexa.VexaFehler("x"), vexa.VexaFehler("x")]
    termin_takt.runde(JETZT)
    a = _zeile()
    # Der Bot ist weg: keine Plattform-Kennung mehr (ein spaeterer Bot im selben
    # Raum wird nie gestoppt), nur die Meeting-Id zum Nachloeschen bleibt.
    assert a["status"] == "fertig" and _ids() == (11, None, None)
    assert fake.anzahl("stoppen") == 0


# ---------- Final-Review I3: verschobener Termin ----------

def _echter_abgleich(monkeypatch):
    monkeypatch.setattr(termin_akte, "abgleichen", ECHT_ABGLEICHEN)
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")


def _berlin(zeit):
    return zeit.astimezone(ZoneInfo("Europe/Berlin"))


def _sc_termin(lead, uid, beginn):
    b = _berlin(beginn)
    payload = {"datum": b.date().isoformat(), "uhrzeit": b.strftime("%H:%M"),
               "dauer_minuten": 60, "thema": "Beratung", "ort": MEET, "uid": uid}
    return str(server._q("insert into activities (lead_id, type, payload) "
                         "values (%s, 'termin', %s::jsonb) returning id",
                         (lead, json.dumps(payload)))[0]["id"])


def _sc_verschieben(aid, beginn):
    b = _berlin(beginn)
    server._q("update activities set payload = payload || %s::jsonb where id = %s returning id",
              (json.dumps({"datum": b.date().isoformat(), "uhrzeit": b.strftime("%H:%M")}),
               aid))


def test_i3_verschoben_neuer_hinweis_zur_neuen_zeit(fake, monkeypatch):
    _echter_abgleich(monkeypatch)
    aid = _sc_termin(_lead(), "v1", JETZT + timedelta(minutes=20))
    termin_takt.runde(JETZT)
    assert len(TELEGRAM) == 1 and _zeile("v1")["hinweis_gesendet_am"] is not None
    _sc_verschieben(aid, JETZT + timedelta(days=1, minutes=20))
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert _zeile("v1")["hinweis_gesendet_am"] is None and len(TELEGRAM) == 1
    termin_takt.runde(JETZT + timedelta(days=1))
    assert len(TELEGRAM) == 2 and _zeile("v1")["hinweis_gesendet_am"] is not None


def test_i3_fehlgeschlagen_neu_gebucht_bot_zur_neuen_zeit(fake, monkeypatch):
    _echter_abgleich(monkeypatch)
    aid = _sc_termin(_lead(), "v2", JETZT + timedelta(minutes=1))
    termin_takt.runde(JETZT)
    assert fake.anzahl("bot") == 1 and _zeile("v2")["status"] == "wartet_auf_einlass"
    fake.meeting = {"status": "failed", "grund": "nicht eingelassen", "ende_grund": ""}
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert _zeile("v2")["status"] == "fehlgeschlagen"
    _sc_verschieben(aid, JETZT + timedelta(days=1, minutes=1))
    termin_takt.runde(JETZT + timedelta(minutes=2))
    a = _zeile("v2")
    assert a["status"] == "geplant" and a["bot_geschickt_am"] is None
    assert _ids("v2") == (None, None, None)
    fake.meeting = {"status": "requested", "grund": "", "ende_grund": ""}
    termin_takt.runde(JETZT + timedelta(days=1))
    assert fake.anzahl("bot") == 2 and _zeile("v2")["status"] == "wartet_auf_einlass"


def test_i3_nein_bleibt_nach_verschieben(fake, monkeypatch):
    _echter_abgleich(monkeypatch)
    aid = _sc_termin(_lead(), "v3", JETZT + timedelta(hours=2))
    termin_takt.runde(JETZT)
    termin_akte.aufnahme_beenden("v3", "Kunde hat abgelehnt")
    _sc_verschieben(aid, JETZT + timedelta(days=1))
    termin_takt.runde(JETZT + timedelta(seconds=30))
    a = _zeile("v3")
    assert (a["status"], a["status_grund"]) == ("ohne_aufnahme", "Kunde hat abgelehnt")
    termin_takt.runde(JETZT + timedelta(days=1))
    assert fake.anzahl("bot") == 0


def test_i3_alte_bot_ids_erst_stoppen_dann_neuer_bot(fake):
    # Akte wurde zurueck auf 'geplant' gesetzt, die Ids des alten Bots stehen noch.
    _akte("u1", beginn=JETZT + timedelta(seconds=30), **VEXA_IDS)
    termin_takt._bot(JETZT)
    assert fake.anzahl("bot") == 0                       # erst aufraeumen
    termin_takt._nachloeschen(JETZT)
    assert _stopp_und_loeschen(fake) == [("stoppen", "google_meet", "abc-defg-hij"),
                                         ("loeschen", 11)]
    assert _ids() == (None, None, None) and _zeile()["status"] == "geplant"
    termin_takt._bot(JETZT + timedelta(seconds=5))
    assert fake.anzahl("bot") == 1


# ---------- Final-Review I7: Takt blockiert nicht ----------

def test_i7a_auswerten_pausiert_vor_einem_termin(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    aufrufe = []
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: aufrufe.append(1) or _ergebnis())
    _akte("alt", beginn=JETZT - timedelta(days=1), status="fertig")
    _mitschrift("alt")
    _akte("bald", beginn=JETZT + timedelta(minutes=14))
    assert termin_takt.runde(JETZT)["auswerten"] == 0 and aufrufe == []
    server._q("update termin_akten set kein_bot = true where uid = 'bald' returning uid")
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert aufrufe == [1]


def test_i7a_auswerten_pausiert_im_bot_fenster(fake, monkeypatch):
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    aufrufe = []
    monkeypatch.setattr(auswertung, "auswerten", lambda s, bilder=None: aufrufe.append(1) or _ergebnis())
    _akte("alt", beginn=JETZT - timedelta(days=1), status="fertig")
    _mitschrift("alt")
    _akte("lauf", beginn=JETZT - timedelta(minutes=10), status="laeuft", vexa_meeting_id=7)
    fake.meeting = {"status": "active", "grund": "", "ende_grund": ""}
    termin_takt.runde(JETZT)
    assert aufrufe == []
    server._q("update termin_akten set abgesagt_am = now() where uid = 'lauf' returning uid")
    termin_takt.runde(JETZT + timedelta(seconds=30))
    assert aufrufe == [1]


def test_i7b_briefing_ki_neuversuch_erst_nach_pause(fake, monkeypatch):
    lead = _lead()
    _akte("u1", beginn=JETZT + timedelta(minutes=25))
    _teilnehmer("u1", lead)

    def kaputt(*a, **k):
        raise ollama.OllamaFehler("weg")

    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", kaputt)
    erstellt = []
    echt = briefing.erstellen
    monkeypatch.setattr(briefing, "erstellen", lambda uid: erstellt.append(uid) or echt(uid))
    termin_takt.runde(JETZT)
    assert len(erstellt) == 1 and _zeile()["briefing_mit_ki"] is False
    termin_takt.runde(JETZT + timedelta(seconds=30))
    termin_takt.runde(JETZT + timedelta(minutes=4))
    assert len(erstellt) == 1
    termin_takt.runde(JETZT + timedelta(minutes=5, seconds=1))
    assert len(erstellt) == 2
    # geaenderte Fakten: sofort neu, ohne Pause
    server._q("update leads set company = 'Andere AG' where id = %s returning id", (lead,))
    termin_takt.runde(JETZT + timedelta(minutes=5, seconds=31))
    assert len(erstellt) == 3


# ---------- Final-Review I9: keine Warnungsflut ----------

def test_i9_dienste_weg_hoechstens_eine_warnung_je_dienst(monkeypatch, caplog):
    monkeypatch.setattr(ollama, "erreichbar", ECHT_ERREICHBAR)
    monkeypatch.setattr(betreiber_hinweis, "senden", ECHT_SENDEN)
    monkeypatch.setattr(vexa, "_unerreichbar_gemeldet", False, raising=False)
    monkeypatch.setattr(betreiber_hinweis, "_letzter_fehler", None, raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("VEXA_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    lead = _lead()
    _akte("brief", beginn=JETZT + timedelta(minutes=20))
    _teilnehmer("brief", lead)
    _akte("lauf", beginn=JETZT - timedelta(hours=2), ende=JETZT - timedelta(hours=1),
          status="laeuft", vexa_meeting_id=7)
    _akte("nein", beginn=JETZT - timedelta(hours=3), status="ohne_aufnahme", **VEXA_IDS)
    _akte("fertig", beginn=JETZT - timedelta(days=1), status="fertig")
    _mitschrift("fertig")
    caplog.set_level(logging.WARNING)
    for i in range(3):
        termin_takt.runde(JETZT + timedelta(seconds=30 * i))
    warn = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    for dienst in ("Vexa", "Telegram", "Ollama"):
        assert len([w for w in warn if dienst in w]) <= 1, (dienst, warn)
    assert len(warn) <= 3, warn
    for geheim in (SCHLUESSEL, ADRESSE, "Karla"):
        assert geheim not in caplog.text


# ---------- Re-Review: Rest-Punkte ----------

@pytest.mark.parametrize("weg", ["aufnahme_beenden", "mitschrift_entfernen"])
def test_mitschrift_waehrend_auswertung_verworfen_kein_entwurf(fake, monkeypatch, caplog, weg):
    caplog.set_level(logging.INFO)
    lead = _lead()
    _akte("u1", status="fertig", will_zusammenfassung=True)
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)

    def chat(system, nutzer, **k):
        # Felix sagt "Nein" bzw. verwirft, waehrend Ollama noch rechnet
        if weg == "aufnahme_beenden":
            termin_akte.aufnahme_beenden("u1", "nachträglich verworfen")
        else:
            termin_akte.mitschrift_entfernen("u1")
        return json.dumps({"kurzfassung": "Kurz.", "zusagen_felix": [
            {"text": "Angebot schicken", "datum": None}], "felder": {"company": "Neu AG"}})

    monkeypatch.setattr(ollama, "chat", chat)
    termin_takt.runde(JETZT)
    assert _mit() is None
    assert server._q("select count(*) as n from termin_vorschlaege")[0]["n"] == 0
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0
    eigene = [r.getMessage() for r in caplog.records if r.name == "sales-termine"]
    assert any("verworfen waehrend Auswertung" in m for m in eigene)
    assert "u1" not in "\n".join(m.replace(termin_takt._h("u1"), "") for m in eigene)


def test_bot_nur_einmal_stoppen_wenn_loeschen_haengt(fake):
    _akte("u1", status="ohne_aufnahme", **VEXA_IDS)
    fake.loeschen_fehler = [vexa.VexaFehler("x"), vexa.VexaFehler("x")]
    termin_takt._nachloeschen(JETZT)
    assert _ids() == (11, None, None)               # Bot ist weg, Meeting bleibt
    termin_takt._nachloeschen(JETZT + timedelta(seconds=30))
    termin_takt._nachloeschen(JETZT + timedelta(seconds=60))
    assert fake.anzahl("stoppen") == 1 and fake.anzahl("loeschen") == 3
    assert _ids() == (None, None, None)


# ---------- Abnahme 12.11.2026: Bot nach Terminende und Stille stoppen ----------
# Auf Jitsi merkte Vexa nicht, dass alle gegangen waren: der Bot sass allein im
# Raum, das Meeting blieb `active`, Mitschrift und Auswertung kamen nicht.

JITSI_IDS = {"vexa_meeting_id": 11, "vexa_plattform": "jitsi",
             "vexa_native_id": "RaumXYZ"}


def _laufend_nach_ende(fake, ende_vor_min=30, letztes_vor_min=None):
    beginn = JETZT - timedelta(minutes=ende_vor_min + 60)
    _akte("u1", beginn=beginn, status="laeuft", **JITSI_IDS)
    fake.meeting = {"status": "active", "grund": "", "ende_grund": ""}
    if letztes_vor_min is None:
        fake.segmente = []
    else:
        zeit = JETZT - timedelta(minutes=letztes_vor_min)
        fake.segmente = [{"sprecher": "Karla", "beginn": zeit.isoformat().replace("+00:00", "Z"),
                          "text": SEGMENT_TEXT, "sprache": "de"}]


def test_bot_nach_ende_und_stille_wird_einmal_gestoppt(fake):
    _laufend_nach_ende(fake, ende_vor_min=30, letztes_vor_min=25)
    termin_takt._verfolgen(JETZT)
    assert [a for a in fake.aufrufe if a[0] == "stoppen"] == [("stoppen", "jitsi", "RaumXYZ")]
    assert _zeile("u1")["status"] == "laeuft"          # fertig erst, wenn Vexa abschliesst
    termin_takt._verfolgen(JETZT + timedelta(seconds=30))
    assert fake.anzahl("stoppen") == 1


def test_bot_nach_ende_ohne_segmente_wird_gestoppt(fake):
    _laufend_nach_ende(fake, ende_vor_min=15, letztes_vor_min=None)
    termin_takt._verfolgen(JETZT)
    assert fake.anzahl("stoppen") == 1


def test_bot_nach_ende_bleibt_solange_noch_gesprochen_wird(fake):
    _laufend_nach_ende(fake, ende_vor_min=30, letztes_vor_min=2)
    termin_takt._verfolgen(JETZT)
    assert fake.anzahl("stoppen") == 0


def test_bot_vor_ende_plus_stille_bleibt_und_holt_nichts(fake):
    _laufend_nach_ende(fake, ende_vor_min=5, letztes_vor_min=None)
    termin_takt._verfolgen(JETZT)
    assert fake.anzahl("stoppen") == 0 and fake.anzahl("holen") == 0


def test_stille_aus_umgebung(fake, monkeypatch):
    monkeypatch.setenv("VEXA_STILLE_NACH_ENDE_MIN", "40")
    _laufend_nach_ende(fake, ende_vor_min=30, letztes_vor_min=None)
    termin_takt._verfolgen(JETZT)
    assert fake.anzahl("stoppen") == 0


def test_bot_stoppen_nach_ende_scheitert_naechste_runde_wieder(fake, monkeypatch):
    _laufend_nach_ende(fake, ende_vor_min=30, letztes_vor_min=None)
    folge = [vexa.VexaFehler("500")]

    def stoppen(p, n):
        fake.aufrufe.append(("stoppen", p, n))
        if folge:
            raise folge.pop(0)

    monkeypatch.setattr(vexa, "bot_stoppen", stoppen)
    termin_takt._verfolgen(JETZT)
    termin_takt._verfolgen(JETZT + timedelta(seconds=30))
    termin_takt._verfolgen(JETZT + timedelta(seconds=60))
    assert fake.anzahl("stoppen") == 2


def test_auswerten_eine_reicht_bilder_durch(fake, monkeypatch):
    import bildschirm
    _akte("u1", status="fertig")
    _mitschrift("u1")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(bildschirm, "bilder_zeilen",
                        lambda uid: [(JETZT, f"Folie fuer {uid}")])
    erhalten = []
    monkeypatch.setattr(auswertung, "auswerten",
                        lambda s, bilder=None: erhalten.append(bilder) or _ergebnis())
    termin_takt.runde(JETZT)
    assert erhalten == [[(JETZT, "Folie fuer u1")]]
    assert _mit("u1")["auswertung_status"] == "fertig"
