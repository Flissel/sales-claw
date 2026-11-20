"""Schneller Pausenweg und Live-Transkript in sales-termine (Meeting-Steuerseite, Task 5).

Vexa und Telegram sind gefakt; die Datenbank ist sales_test. Die Zeit kommt als
`jetzt` in die Runden - Wiederholungen und die 10-s-Frist rechnen damit.
"""
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import betreiber_hinweis  # noqa: E402
import server  # noqa: E402
import termin_akte  # noqa: E402
import termin_pause  # noqa: E402
import termin_takt  # noqa: E402
import vexa  # noqa: E402

T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
MID = 41
NATIVE = "Raum-Karla@meet.ffmuc.net"
TITEL = "Geheimprojekt Karla Kunde"
HINWEISE: list[str] = []


def s(sek: float) -> timedelta:
    return timedelta(seconds=sek)


def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


class FakeVexa:
    def __init__(self):
        self.acts: list[tuple] = []
        self.zustand: dict[int, dict | None] = {}
        self.zustand_fehler: dict[int, Exception] = {}
        self.senden_fehler: list[Exception] = []
        self.stoppen_fehler: list[Exception] = []
        self.segmente: dict[int, list[dict]] = {}
        self.holen_fehler: dict[int, Exception] = {}
        self.lesungen = 0

    def pause_setzen(self, plattform, native_id, ab):
        self.acts.append(("pause" if ab is not None else "resume", plattform, native_id, ab))
        if self.senden_fehler:
            raise self.senden_fehler.pop(0)

    def pause_zustand(self, mid):
        self.lesungen += 1
        if mid in self.zustand_fehler:
            raise self.zustand_fehler[mid]
        return self.zustand.get(mid)

    def bot_stoppen(self, plattform, native_id):
        self.acts.append(("stoppen", plattform, native_id, None))
        if self.stoppen_fehler:
            raise self.stoppen_fehler.pop(0)

    def segmente_holen(self, mid):
        if mid in self.holen_fehler:
            raise self.holen_fehler[mid]
        return [dict(x) for x in self.segmente.get(mid, [])]

    def pausen_abs(self):
        return [a[3] for a in self.acts if a[0] == "pause"]


@pytest.fixture
def fake(monkeypatch):
    f = FakeVexa()
    for name in ("pause_setzen", "pause_zustand", "bot_stoppen", "segmente_holen"):
        monkeypatch.setattr(vexa, name, getattr(f, name))
    return f


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    server._q("truncate sales_test.termin_akten cascade")
    monkeypatch.setenv("VEXA_API_KEY", "SCHLUESSEL-test")
    monkeypatch.setenv("UI_BASIS_URL", "https://ui.example.test")
    HINWEISE.clear()
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: HINWEISE.append(text) or True)
    termin_pause._zuruecksetzen()
    yield
    termin_pause._zuruecksetzen()
    server._q("truncate sales_test.termin_akten cascade")


def _akte(uid="w1", status="laeuft", ids=True, mid=MID, ende=None):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, status, titel, "
        "vexa_meeting_id, vexa_plattform, vexa_native_id) "
        "values (%s, 'kalender', %s, %s, %s, %s, %s, %s, %s) returning uid",
        (uid, T0 - timedelta(minutes=5), ende or T0 + timedelta(hours=1), status, TITEL,
         mid if ids else None, "jitsi" if ids else None, NATIVE if ids else None))
    return uid


def _zeile(uid="w1"):
    return server._q("select * from termin_akten where uid = %s", (uid,))[0]


def _live(uid="w1"):
    return server._q("select segment_id, beginn, sprecher, text from termin_live_segmente "
                     "where uid = %s order by beginn, segment_id", (uid,))


def _live_einfuegen(uid, sid, beginn, text="x"):
    server._q("insert into termin_live_segmente (uid, segment_id, beginn, sprecher, text) "
              "values (%s, %s, %s, 'Karla', %s) returning uid", (uid, sid, beginn, text))


def _seg(sid, beginn, ende=None, text=None, sprecher="Karla"):
    return {"sprecher": sprecher, "beginn": iso(beginn) if beginn else "",
            "ende": iso(ende) if ende else "", "segment_id": sid,
            "text": text or f"Text {sid}", "sprache": "de"}


def _bestaetigt(f, von, mid=MID):
    f.zustand[mid] = {"pausiert": True, "seit_ms": ms(von)}


def _runde(jetzt):
    """Eine Wachrunde und danach ein Durchlauf des Hinweis-Arbeiters (in
    Produktion zwei getrennte Threads)."""
    n = termin_pause.wache_runde(jetzt)
    termin_pause.hinweise_senden(jetzt)
    return n


# ---------- Brief, Step 2 ----------

def test_wunsch_pause_sendet_act_mit_klickzeit(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    assert _runde(T0 + s(0.5)) == 1
    assert fake.acts == [("pause", "jitsi", NATIVE, T0)]
    # Doppelklick setzt aufnahme_wunsch_am neu - der Act behaelt die erste Klickzeit (R10)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0 + s(2))
    assert _zeile()["aufnahme_wunsch_am"] == T0 + s(2)
    _runde(T0 + s(1.5))     # unbestaetigt, aber noch zu frueh fuer erneut
    assert fake.pausen_abs() == [T0]
    _runde(T0 + s(4))       # unbestaetigt, Wiederholung faellig
    assert fake.pausen_abs() == [T0, T0]


def test_bestaetigung_setzt_pausiert_seit(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    assert _zeile()["aufnahme_pausiert_seit"] is None
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    z = _zeile()
    assert z["aufnahme_pausiert_seit"] == T0 and z["aufnahme_pause_fehler"] is None
    assert termin_akte.pausen("w1")[0]["bestaetigt_am"] == T0 + s(1.5)
    # R11c: nach der ERSTEN Bestaetigung genau ein zweiter pause-Aufruf, gleiche Klickzeit
    assert fake.pausen_abs() == [T0, T0]
    for t in (2.5, 5, 12, 30, 90):
        _runde(T0 + s(t))
    assert fake.pausen_abs() == [T0, T0]
    assert termin_akte.pausen("w1")[0]["bestaetigt_am"] == T0 + s(1.5)
    assert _zeile()["aufnahme_pause_fehler"] is None and HINWEISE == []


def test_r15_ohne_seit_ms_nicht_bestaetigt(fake):
    """R15: pausiert:true ohne seit_ms ist keine Bestaetigung - weiter senden."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand[MID] = {"pausiert": True, "seit_ms": None}
    _runde(T0 + s(0.5))
    _runde(T0 + s(4))
    assert _zeile()["aufnahme_pausiert_seit"] is None
    assert termin_akte.pausen("w1")[0]["bestaetigt_am"] is None
    assert fake.pausen_abs() == [T0, T0]                      # Wiederholung, kein Nachschuss
    for i in range(5, 12):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"


@pytest.mark.parametrize("abstand_ms,bestaetigt", [
    (-5000, False), (-1001, False), (-1000, True), (0, True), (2000, True), (2001, False)])
def test_r15_fenster_fuer_seit_ms(fake, abstand_ms, bestaetigt):
    """R15: nur von - 1 s <= seit_ms <= von + 2 s; aelter = Bestaetigung einer frueheren Pause."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand[MID] = {"pausiert": True, "seit_ms": ms(T0) + abstand_ms}
    _runde(T0 + s(0.5))
    _runde(T0 + s(4))
    z = _zeile()
    if bestaetigt:
        assert z["aufnahme_pausiert_seit"] == T0 + timedelta(milliseconds=abstand_ms)
    else:
        assert z["aufnahme_pausiert_seit"] is None
        assert fake.pausen_abs() == [T0, T0]                  # erneut gesendet


def test_bestaetigung_mit_seit_ms_vom_bot(fake):
    """Der Bot klemmt eine Klickzeit in der Zukunft auf seine Uhr: seit_ms zaehlt."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand[MID] = {"pausiert": True, "seit_ms": ms(T0) - 700}
    _runde(T0 + s(0.5))
    assert _zeile()["aufnahme_pausiert_seit"] == T0 - timedelta(milliseconds=700)


def test_alte_bestaetigung_einer_spaeteren_pause_zaehlt_nicht(fake):
    """seit_ms deutlich NACH der Klickzeit ist nicht diese Pause: erneut senden."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand[MID] = {"pausiert": True, "seit_ms": ms(T0 + s(60))}
    _runde(T0 + s(0.5))
    assert _zeile()["aufnahme_pausiert_seit"] is None


def test_ohne_bestaetigung_nach_10s_fehler_und_ein_hinweis(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    for i in range(1, 11):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None          # genau 10 s: noch nicht
    assert HINWEISE == []
    for i in range(11, 31):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    assert len(HINWEISE) == 1
    text = HINWEISE[0]
    assert "nicht bestätigt" in text
    assert "https://ui.example.test/termine/w1/live" in text
    assert TITEL not in text and "Karla" not in text and NATIVE not in text
    # Wiederholungen gedrosselt (nicht jede Sekunde), aber es wird weiter gesendet
    assert 2 <= len(fake.pausen_abs()) <= 11
    assert set(fake.pausen_abs()) == {T0}
    # Spaete Bestaetigung loescht den Fehler
    _bestaetigt(fake, T0)
    _runde(T0 + s(31))
    z = _zeile()
    assert z["aufnahme_pause_fehler"] is None and z["aufnahme_pausiert_seit"] == T0
    # Vexa vergisst die Pause wieder: Fehler ja, aber kein zweiter Hinweis je Pause
    fake.zustand[MID] = None
    for i in range(32, 50):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    assert len(HINWEISE) == 1


def test_hinweis_scheitert_wird_spaeter_wiederholt(fake, monkeypatch):
    versuche: list[str] = []
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: versuche.append(text) and False)
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    for i in range(1, 30):
        _runde(T0 + s(i))
    assert len(versuche) == 1                                 # nicht jede Sekunde
    _runde(T0 + s(11 + 61))
    assert len(versuche) == 2


def test_lobby_wunsch_wird_nach_aktivierung_gesendet(fake):
    _akte(status="wartet_auf_einlass", ids=False)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    assert _runde(T0 + s(0.5)) == 0
    assert fake.acts == [] and fake.lesungen == 0
    server._q("update termin_akten set vexa_meeting_id = %s, vexa_plattform = 'jitsi', "
              "vexa_native_id = %s where uid = 'w1' returning uid", (MID, NATIVE))
    assert _runde(T0 + s(1)) == 1
    assert fake.acts == [("pause", "jitsi", NATIVE, T0)]
    assert _zeile()["status"] == "wartet_auf_einlass"


def test_vexa_neustart_schickt_pause_erneut(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    assert fake.pausen_abs() == [T0, T0]
    # Vexa neu gestartet: Zustand pausiert:false
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    assert _runde(T0 + s(20)) == 1
    assert fake.pausen_abs() == [T0, T0, T0]
    assert _zeile()["aufnahme_pausiert_seit"] is None         # Seite zeigt "wird pausiert"
    # Zustand fehlt ganz (neues Meeting-Objekt): ebenfalls erneut
    fake.zustand[MID] = None
    _runde(T0 + s(24))
    assert fake.pausen_abs() == [T0] * 4
    # wieder bestaetigt: kein weiterer Nachschuss (nur nach der ERSTEN Bestaetigung)
    _bestaetigt(fake, T0)
    _runde(T0 + s(25))
    assert fake.pausen_abs() == [T0] * 4
    assert _zeile()["aufnahme_pausiert_seit"] == T0


def test_vexa_nicht_erreichbar_beim_lesen_sendet_trotzdem(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand_fehler[MID] = vexa.VexaNichtErreichbar("weg")
    assert _runde(T0 + s(0.5)) == 1
    assert fake.pausen_abs() == [T0]


def test_senden_scheitert_wird_wiederholt(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.senden_fehler.append(vexa.VexaFehler("503"))
    assert _runde(T0 + s(0.5)) == 0
    assert _runde(T0 + s(4)) == 1
    assert fake.pausen_abs() == [T0, T0]


def test_notbremse_stoppt_bot_sofort_und_behaelt_live_segmente(fake):
    _akte()
    _live_einfuegen("w1", "s1", T0 - s(30), "vor der Pause")
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    termin_akte.aufnahme_wuenschen("w1", "notbremse", "felix", T0 + s(5))
    fake.stoppen_fehler.append(vexa.VexaNichtErreichbar("kurz weg"))
    _runde(T0 + s(5.5))                    # scheitert: naechste Sekunde
    assert _runde(T0 + s(6.5)) == 1
    stopps = [a for a in fake.acts if a[0] == "stoppen"]
    assert stopps == [("stoppen", "jitsi", NATIVE, None)] * 2
    for t in (7.5, 8.5, 20):
        _runde(T0 + s(t))
    assert len([a for a in fake.acts if a[0] == "stoppen"]) == 2   # nicht wiederholt
    assert fake.pausen_abs() == [T0]                          # nach Notbremse keine Pause-Acts
    assert [z["segment_id"] for z in _live()] == ["s1"]       # Live-Ablage bleibt (R2)
    assert termin_akte.pausen("w1")[0]["bis"] is None         # offene Pause bleibt offen (R2)
    z = _zeile()
    assert z["status"] == "laeuft"                            # keine aufnahme_beenden-Wirkung
    assert HINWEISE == []                                     # keine 10-s-Frist nach Notbremse


def test_live_runde_laesst_pausensegmente_weg(fake):
    _akte()
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) "
              "values ('w1', %s, %s, 'felix') returning id", (T0 + s(60), T0 + s(120)))
    server._q("insert into termin_pausen (uid, von, angefordert_von) "
              "values ('w1', %s, 'felix') returning id", (T0 + s(300),))
    fake.segmente[MID] = [
        _seg("vor", T0 + s(10), T0 + s(15)),
        _seg("endet_bei_von", T0 + s(55), T0 + s(60)),     # endet genau bei von: bleibt
        _seg("ueber_von", T0 + s(58), T0 + s(61)),         # R4: ueberspannt von -> weg
        _seg("drin", T0 + s(70), T0 + s(75)),
        _seg("bei_bis", T0 + s(120), T0 + s(123)),         # bis exklusiv: bleibt
        _seg("nach", T0 + s(130), T0 + s(131)),
        _seg("offen", T0 + s(310), T0 + s(311)),           # offene Pause: weg
        _seg("ueber_offen", T0 + s(299), T0 + s(301)),     # R4 an der offenen Pause
        _seg("ohne_zeit", None),                           # nicht einzuordnen: weg
        {**_seg("ohne_ende", T0 + s(140)), "ende": ""},       # R16: Pause danach -> weg
    ]
    assert termin_pause.live_runde(T0 + s(400)) == 4
    assert [z["segment_id"] for z in _live()] == [
        "vor", "endet_bei_von", "bei_bis", "nach"]
    # Upsert: geaenderter Text, ein von Vexa zurueckgezogenes Segment verschwindet
    fake.segmente[MID] = [_seg("vor", T0 + s(10), T0 + s(15), text="neu"),
                          _seg("nach", T0 + s(130), T0 + s(131))]
    termin_pause.live_runde(T0 + s(405))
    z = _live()
    assert [(x["segment_id"], x["text"]) for x in z] == [("vor", "neu"), ("nach", "Text nach")]
    assert z[0]["beginn"] == T0 + s(10) and z[0]["sprecher"] == "Karla"


def test_live_runde_nur_laufende_akten(fake):
    _akte("w1", status="wartet_auf_einlass")
    _akte("w2", status="laeuft", mid=42)
    fake.segmente[MID] = [_seg("a", T0)]
    fake.segmente[42] = [_seg("b", T0)]
    termin_pause.live_runde(T0 + s(10))
    assert _live("w1") == [] and [z["segment_id"] for z in _live("w2")] == ["b"]


def test_live_runde_nach_fertig_traegt_nichts_mehr_ein(fake, monkeypatch):
    """Rennen: die Akte wird fertig, waehrend die Live-Runde bei Vexa holt."""
    _akte()
    fake.segmente[MID] = [_seg("a", T0)]
    echt = fake.segmente_holen

    def holen_und_fertig(mid):
        segs = echt(mid)
        assert termin_takt._mitschrift_ablegen("w1", segs) is True
        return segs

    monkeypatch.setattr(vexa, "segmente_holen", holen_und_fertig)
    assert termin_pause.live_runde(T0 + s(5)) == 0
    assert _live() == [] and _zeile()["status"] == "fertig"


def test_live_segment_ohne_id_bekommt_stabile_id(fake):
    _akte()
    fake.segmente[MID] = [{**_seg("", T0, T0 + s(2)), "text": "eins"}]
    termin_pause.live_runde(T0 + s(5))
    fake.segmente[MID] = [{**_seg("", T0, T0 + s(2)), "text": "eins zwei"}]
    termin_pause.live_runde(T0 + s(10))
    z = _live()
    assert len(z) == 1 and z[0]["text"] == "eins zwei" and z[0]["segment_id"]


def test_ende_waehrend_pause_schliesst_pause_und_mitschrift_ohne_fenster(fake):
    ende = T0 + timedelta(hours=1)
    _akte(ende=ende)
    von = T0 + timedelta(minutes=10)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", von)
    _live_einfuegen("w1", "s1", T0 + s(60))
    segmente = [
        _seg("vorher", T0 + s(60), T0 + s(64), text="vor der Pause"),
        _seg("ueber", von - s(2), von + s(1), text="ueber den Klick"),
        _seg("drin", von + s(30), von + s(33), text="GEHEIM in der Pause"),
        _seg("ohne_zeit", None, text="ohne Zeit"),
    ]
    ist_ende = T0 + timedelta(minutes=40)                    # frueher als geplant
    assert termin_takt._mitschrift_ablegen("w1", segmente, ende_am=ist_ende) is True
    m = server._q("select segmente from termin_mitschriften where uid = 'w1'")[0]["segmente"]
    assert [x["text"] for x in m] == ["vor der Pause"]
    assert set(m[0]) == {"sprecher", "beginn", "text", "sprache"}   # Schema unveraendert
    p = termin_akte.pausen("w1")
    assert len(p) == 1 and p[0]["von"] == von and p[0]["bis"] == ist_ende   # R12: echtes Ende
    assert _live() == []
    assert _zeile()["status"] == "fertig"


def test_r12_ueberzogen_waehrend_pause_bis_ist_tatsaechliches_ende(fake, monkeypatch):
    """R12: Meeting ueberzieht das geplante Ende in der Pause -> bis = Erkennung des Endes."""
    geplant = T0 + timedelta(hours=1)
    _akte(ende=geplant)
    von = geplant - timedelta(minutes=5)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", von)
    fake.segmente[MID] = [_seg("a", T0 + s(60), T0 + s(62)),
                          _seg("spaet", geplant + timedelta(minutes=10), text="GEHEIM")]
    monkeypatch.setattr(vexa, "meeting_lesen",
                        lambda mid: {"status": "completed", "grund": "", "ende_grund": ""})
    monkeypatch.setattr(vexa, "meeting_loeschen", lambda mid: None)
    erkannt = geplant + timedelta(minutes=20)
    z = server._q("select uid, status, ende, vexa_meeting_id, vexa_plattform, vexa_native_id "
                  "from termin_akten where uid = 'w1'")[0]
    assert termin_takt._verfolgen_eine(z, erkannt) == 1
    p = termin_akte.pausen("w1")[0]
    assert p["bis"] >= erkannt and p["bis"] > geplant
    m = server._q("select segmente from termin_mitschriften where uid = 'w1'")[0]["segmente"]
    assert "GEHEIM" not in json.dumps(m)


def test_r12_offene_pause_nie_vor_von(fake):
    _akte()
    von = T0 + timedelta(minutes=10)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", von)
    assert termin_takt._mitschrift_ablegen("w1", [], ende_am=von - s(30)) is True
    assert termin_akte.pausen("w1")[0]["bis"] == von


# ---------- R16: fehlendes Segment-Ende ----------

def test_r16_ohne_ende_vor_spaeterer_pause_weg():
    p = [{"von": T0 + s(60), "bis": T0 + s(120)}]
    assert termin_pause.beruehrt_pause(T0 + s(10), None, p) is True
    offen = [{"von": T0 + s(60), "bis": None}]
    assert termin_pause.beruehrt_pause(T0 + s(10), None, offen) is True


def test_r16_ohne_ende_nach_allen_geschlossenen_pausen_bleibt():
    p = [{"von": T0 + s(60), "bis": T0 + s(120)}, {"von": T0, "bis": T0 + s(5)}]
    assert termin_pause.beruehrt_pause(T0 + s(130), None, p) is False
    assert termin_pause.beruehrt_pause(T0 + s(120), None, p) is False   # bis exklusiv
    assert termin_pause.beruehrt_pause(T0 + s(90), None, p) is True     # in der Pause


def test_r16_ohne_ende_mit_offener_pause_weg():
    p = [{"von": T0 + s(60), "bis": T0 + s(120)}, {"von": T0 + s(300), "bis": None}]
    assert termin_pause.beruehrt_pause(T0 + s(130), None, p) is True    # offene Pause spaeter
    assert termin_pause.beruehrt_pause(T0 + s(400), None, p) is True    # in offener Pause


def test_r16_mitschrift_ohne_oder_kaputtes_ende(fake):
    _akte()
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) "
              "values ('w1', %s, %s, 'felix') returning id", (T0 + s(60), T0 + s(120)))
    segmente = [
        {**_seg("vor_ohne_ende", T0 + s(10), text="GEHEIM-A"), "ende": ""},
        {**_seg("vor_kaputt", T0 + s(20), text="GEHEIM-B"), "ende": "kaputt"},
        {**_seg("vor_mit_ende", T0 + s(30), T0 + s(31), text="eins")},
        {**_seg("nach_ohne_ende", T0 + s(200), text="zwei"), "ende": ""},
        {**_seg("ohne_beginn", None, text="GEHEIM-C")},   # fehlender Beginn: weiter weg
    ]
    assert termin_takt._mitschrift_ablegen("w1", segmente, ende_am=T0 + s(300)) is True
    m = json.dumps(server._q("select segmente from termin_mitschriften "
                             "where uid = 'w1'")[0]["segmente"])
    assert "GEHEIM" not in m and "eins" in m and "zwei" in m


def test_mitschrift_mit_geschlossener_pause_behaelt_danach(fake):
    _akte()
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) "
              "values ('w1', %s, %s, 'felix') returning id", (T0 + s(60), T0 + s(120)))
    segmente = [_seg("a", T0 + s(10), T0 + s(12), text="eins"),
                _seg("b", T0 + s(90), T0 + s(92), text="GEHEIM"),
                _seg("c", T0 + s(150), T0 + s(152), text="drei")]
    assert termin_takt._mitschrift_ablegen("w1", segmente) is True
    m = server._q("select segmente from termin_mitschriften where uid = 'w1'")[0]["segmente"]
    assert "GEHEIM" not in json.dumps(m)
    assert [x["text"] for x in m] in (["eins", "drei"], ["eins drei"])
    assert termin_akte.pausen("w1")[0]["bis"] == T0 + s(120)


def test_mitschrift_ohne_pause_behaelt_segmente_ohne_zeit(fake):
    _akte()
    segmente = [{"sprecher": "A", "beginn": "", "text": "ohne Zeit", "sprache": "de"}]
    assert termin_takt._mitschrift_ablegen("w1", segmente) is True
    m = server._q("select segmente from termin_mitschriften where uid = 'w1'")[0]["segmente"]
    assert [x["text"] for x in m] == ["ohne Zeit"]


# ---------- Rulings R10/R11 ----------

def test_pause_weiter_pause_sendet_neues_von(fake):
    """Bindung aus Task 2: nach einem resume nie eine pause mit aelterem at_ms."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    t1 = T0 + s(60)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1)
    assert _runde(t1 + s(0.5)) == 1
    assert fake.acts[-1] == ("resume", "jitsi", NATIVE, None)
    assert _zeile()["aufnahme_pausiert_seit"] == T0           # "wird fortgesetzt"
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    _runde(t1 + s(1.5))
    assert _zeile()["aufnahme_pausiert_seit"] is None
    t2 = T0 + s(120)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", t2)
    for t in (0.5, 4, 8, 12):
        _runde(t2 + s(t))
    i = max(i for i, a in enumerate(fake.acts) if a[0] == "resume")
    nach = [a[3] for a in fake.acts[i + 1:] if a[0] == "pause"]
    assert nach and set(nach) == {t2}
    _bestaetigt(fake, t2)
    _runde(t2 + s(13))
    i = max(i for i, a in enumerate(fake.acts) if a[0] == "resume")
    assert set(a[3] for a in fake.acts[i + 1:] if a[0] == "pause") == {t2}
    assert _zeile()["aufnahme_pausiert_seit"] == t2


def test_weiter_vor_nachschuss_sendet_keine_alte_pause(fake, monkeypatch):
    """Scheitert der Nachschuss (R11c) und kommt dann Weiter, geht keine alte Pause mehr raus."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    fake.senden_fehler.append(vexa.VexaFehler("503"))
    _runde(T0 + s(1.5))                     # Nachschuss scheitert
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", T0 + s(2))
    for t in (2.5, 6, 10):
        _runde(T0 + s(t))
    i = min(i for i, a in enumerate(fake.acts) if a[0] == "resume")
    assert [a for a in fake.acts[i:] if a[0] == "pause"] == []


def test_weiter_unbestaetigt_resume_wird_wiederholt(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", T0 + s(10))
    for t in (10.5, 11.5, 14):
        _runde(T0 + s(t))
    assert [a[0] for a in fake.acts].count("resume") == 2
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    _runde(T0 + s(15))
    for t in (20, 30):
        _runde(T0 + s(t))
    assert [a[0] for a in fake.acts].count("resume") == 2
    z = _zeile()
    assert z["aufnahme_pausiert_seit"] is None and z["aufnahme_pause_fehler"] is None


def test_weiter_raeumt_fehler_nach_bestaetigung(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    for i in range(1, 13):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", T0 + s(13))
    _runde(T0 + s(13.5))
    assert fake.acts[-1][0] == "resume"                       # unklar, ob pausiert: resume
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    _runde(T0 + s(14.5))
    assert _zeile()["aufnahme_pause_fehler"] is None


def test_bestaetigung_loescht_live_segmente_im_fenster(fake):
    """R11b: schon geholte Segmente, die das Fenster beruehren, verschwinden."""
    _akte()
    fake.segmente[MID] = [_seg("a", T0 - s(10), T0 - s(6)),
                          _seg("ueber", T0 - s(3), T0 + s(1))]   # Teilsegment, waechst noch
    termin_pause.live_runde(T0 - s(1))
    _live_einfuegen("w1", "drin", T0 + s(2))
    assert [z["segment_id"] for z in _live()] == ["a", "ueber", "drin"]
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    assert len(_live()) == 3                                  # erst bei Bestaetigung
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    assert [z["segment_id"] for z in _live()] == ["a"]


def test_r13_live_ende_gespeichert_und_loeschen_nach_neustart(fake):
    """R13: Ende steht in der Tabelle; die Loeschung bei Bestaetigung braucht keinen
    Prozess-Speicher (Neustart zwischen live_runde und Bestaetigung)."""
    _akte()
    fake.segmente[MID] = [_seg("a", T0 - s(10), T0 - s(6)),
                          _seg("ueber", T0 - s(3), T0 + s(1)),
                          _seg("bis_von", T0 - s(4), T0),         # endet genau bei von: bleibt
                          {**_seg("ohne_ende", T0 - s(2)), "ende": ""}]
    termin_pause.live_runde(T0 - s(1))
    enden = {z["segment_id"]: z["ende"] for z in server._q(
        "select segment_id, ende from termin_live_segmente where uid = 'w1'")}
    assert enden == {"a": T0 - s(6), "ueber": T0 + s(1), "bis_von": T0, "ohne_ende": None}
    termin_pause._zuruecksetzen()                              # "Neustart"
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _bestaetigt(fake, T0)
    _runde(T0 + s(0.5))
    # ohne Ende und vor von: R16 - koennte das Fenster beruehren -> weg
    assert sorted(z["segment_id"] for z in _live()) == ["a", "bis_von"]


def test_r13_live_upsert_aktualisiert_ende(fake):
    _akte()
    fake.segmente[MID] = [_seg("a", T0, T0 + s(1))]
    termin_pause.live_runde(T0 + s(2))
    fake.segmente[MID] = [_seg("a", T0, T0 + s(4))]
    termin_pause.live_runde(T0 + s(7))
    assert server._q("select ende from termin_live_segmente where uid = 'w1'")[0]["ende"] \
        == T0 + s(4)


# ---------- R14: unbestaetigtes Weiter ----------

def test_r14_weiter_ohne_bestaetigung_nach_10s_fehler_und_ein_hinweis(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    t1 = T0 + s(60)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1)
    # Doppelklick setzt aufnahme_wunsch_am neu - die Frist zaehlt ab dem ersten Klick (bis)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1 + s(5))
    for i in range(1, 11):
        _runde(t1 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None
    assert HINWEISE == []
    for i in range(11, 40):
        _runde(t1 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "weiter_nicht_bestaetigt"
    assert len(HINWEISE) == 1
    assert "Weiter" in HINWEISE[0] and "/termine/w1/live" in HINWEISE[0]
    assert TITEL not in HINWEISE[0] and NATIVE not in HINWEISE[0]
    assert [a[0] for a in fake.acts].count("resume") >= 3     # Wiederholungen
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    _runde(t1 + s(41))
    z = _zeile()
    assert z["aufnahme_pause_fehler"] is None and z["aufnahme_pausiert_seit"] is None
    for i in range(42, 60):
        _runde(t1 + s(i))
    assert len(HINWEISE) == 1


def test_r14_weiter_bestaetigt_rechtzeitig_kein_fehler(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    t1 = T0 + s(60)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1)
    _runde(t1 + s(0.5))
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    for i in range(1, 30):
        _runde(t1 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None and HINWEISE == []


def test_r14_neue_pause_ersetzt_weiter_fehler(fake):
    """Nach weiter_nicht_bestaetigt eine neue unbestaetigte Pause: Fehler wird nicht_bestaetigt."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    t1 = T0 + s(60)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1)
    for i in range(1, 13):
        _runde(t1 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "weiter_nicht_bestaetigt"
    t2 = t1 + s(20)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", t2)
    fake.zustand[MID] = None
    for i in range(1, 13):
        _runde(t2 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    assert len(HINWEISE) == 2                                  # je Ereignis einer


def test_aufraeumen_nach_ende_ausserhalb_der_mitschrift(fake):
    """Akte endet fehlgeschlagen/ohne Aufnahme waehrend einer Pause: Pause zu, Live leer."""
    ende = T0 + timedelta(hours=1)
    _akte(ende=ende)
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _live_einfuegen("w1", "s1", T0 - s(5))
    termin_akte.status_wechseln("w1", ("laeuft",), "fehlgeschlagen", "Bot ist gescheitert")
    termin_pause.live_runde(T0 + s(5))
    assert termin_akte.pausen("w1")[0]["bis"] == T0 + s(5)  # R12: Erkennung, nicht Plan
    assert _live() == []


def test_weiter_ohne_pause_fragt_vexa_nicht(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", T0)
    for t in (1, 2, 3):
        assert _runde(T0 + s(t)) == 0
    assert fake.lesungen == 0 and fake.acts == []


def test_ohne_vexa_schluessel_nichts(fake, monkeypatch):
    monkeypatch.delenv("VEXA_API_KEY")
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    assert _runde(T0 + s(1)) == 0
    assert fake.acts == []


def test_fehler_je_akte_ohne_inhalte_im_log(fake, caplog):
    caplog.set_level(logging.DEBUG)
    _akte("Karla-uid-1", mid=MID)
    _akte("w2", mid=42)
    termin_akte.aufnahme_wuenschen("Karla-uid-1", "pause", "felix", T0)
    termin_akte.aufnahme_wuenschen("w2", "pause", "felix", T0)
    fake.senden_fehler.append(RuntimeError(f"{TITEL} {NATIVE}"))
    assert _runde(T0 + s(0.5)) == 1          # die zweite Akte laeuft weiter
    fake.segmente[MID] = [_seg("x", T0 - s(30), text="GEHEIMTEXT")]
    fake.holen_fehler[42] = RuntimeError(f"{TITEL} GEHEIMTEXT")
    termin_pause.live_runde(T0 - s(1) + s(10))
    log = caplog.text
    assert "Karla" not in log and NATIVE not in log and "GEHEIMTEXT" not in log
    assert hashlib.sha256(b"Karla-uid-1").hexdigest()[:8] in log




# ---------- Review Important 2: Lesefehler != "Vexa meldet nicht pausiert" ----------

def _bestaetigte_pause(fake):
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    _runde(T0 + s(0.5))
    _bestaetigt(fake, T0)
    _runde(T0 + s(1.5))
    assert fake.pausen_abs() == [T0, T0]


def test_lesefehler_bei_bestaetigter_pause_aendert_nichts(fake):
    _bestaetigte_pause(fake)
    fake.zustand_fehler[MID] = vexa.VexaNichtErreichbar("Zeitlimit")
    for i in range(30, 60):
        _runde(T0 + s(i))
    z = _zeile()
    assert z["aufnahme_pausiert_seit"] == T0 and z["aufnahme_pause_fehler"] is None
    assert HINWEISE == []
    assert fake.pausen_abs() == [T0, T0]                      # nichts erneut gesendet
    del fake.zustand_fehler[MID]                              # wieder lesbar, weiter bestaetigt
    _runde(T0 + s(61))
    assert _zeile()["aufnahme_pausiert_seit"] == T0 and HINWEISE == []


def test_echtes_pausiert_false_bei_bestaetigter_pause_frische_frist(fake):
    _bestaetigte_pause(fake)
    verlust = T0 + s(60)
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}  # Bot neu gestartet
    assert _runde(verlust) == 1                               # sofort erneut, gleiche Klickzeit
    assert fake.pausen_abs() == [T0, T0, T0]
    assert _zeile()["aufnahme_pausiert_seit"] is None
    for i in range(1, 11):
        _runde(verlust + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None and HINWEISE == []   # Frist ab Verlust
    _runde(verlust + s(11))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    assert len(HINWEISE) == 1
    assert set(fake.pausen_abs()) == {T0}


def test_echtes_pausiert_false_nach_neustart_frische_frist(fake):
    """Ein Neustart von sales-termine zwischen Bestaetigung und Verlust: die Frist
    beginnt mit dem ersten Blick dieses Prozesses, nicht bei von."""
    _bestaetigte_pause(fake)
    termin_pause._zuruecksetzen()
    fake.zustand[MID] = None                                  # neues Meeting-Objekt, kein Zustand
    _runde(T0 + s(100))
    for i in range(101, 111):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None and HINWEISE == []
    _runde(T0 + s(111))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"


def test_lesefehler_bei_unbestaetigter_pause_frist_gilt(fake):
    """Ohne je eine Bestaetigung bleibt die Pause unbestaetigt - auch wenn Vexa nicht lesbar ist."""
    _akte()
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", T0)
    fake.zustand_fehler[MID] = vexa.VexaNichtErreichbar("weg")
    for i in range(1, 12):
        _runde(T0 + s(i))
    assert _zeile()["aufnahme_pause_fehler"] == "nicht_bestaetigt"
    assert len(HINWEISE) == 1


def _bestaetigtes_weiter(fake):
    _bestaetigte_pause(fake)
    t1 = T0 + s(60)
    termin_akte.aufnahme_wuenschen("w1", "an", "felix", t1)
    _runde(t1 + s(0.5))
    fake.zustand[MID] = {"pausiert": False, "seit_ms": None}
    _runde(t1 + s(1))
    z = _zeile()
    assert z["aufnahme_pausiert_seit"] is None and z["aufnahme_pause_fehler"] is None
    return t1


def test_lesefehler_nach_bestaetigtem_weiter_aendert_nichts(fake):
    t1 = _bestaetigtes_weiter(fake)
    resumes = [a[0] for a in fake.acts].count("resume")
    fake.zustand_fehler[MID] = vexa.VexaNichtErreichbar("Zeitlimit")
    for i in range(30, 60):
        _runde(t1 + s(i))
    z = _zeile()
    assert z["aufnahme_pause_fehler"] is None and HINWEISE == []
    assert [a[0] for a in fake.acts].count("resume") == resumes


def test_echtes_pausiert_true_nach_bestaetigtem_weiter_frische_frist(fake):
    t1 = _bestaetigtes_weiter(fake)
    verlust = t1 + s(60)
    _bestaetigt(fake, T0)                                     # alte Bestaetigung taucht wieder auf
    resumes = [a[0] for a in fake.acts].count("resume")
    assert _runde(verlust) == 1                               # resume sofort erneut
    assert [a[0] for a in fake.acts].count("resume") == resumes + 1
    for i in range(1, 11):
        _runde(verlust + s(i))
    assert _zeile()["aufnahme_pause_fehler"] is None and HINWEISE == []
    _runde(verlust + s(11))
    assert _zeile()["aufnahme_pause_fehler"] == "weiter_nicht_bestaetigt"
    assert len(HINWEISE) == 1


# ---------- Threads (Review Important 1: nichts Langsames im 1-s-Weg) ----------

def _warten(bedingung, sekunden=3.0):
    ende = time.monotonic() + sekunden
    while not bedingung() and time.monotonic() < ende:
        time.sleep(0.01)
    return bedingung()


def test_haengender_live_abruf_und_hinweis_verzoegern_keinen_act(fake, monkeypatch):
    monkeypatch.setattr(termin_pause, "WACHE_TAKT_S", 0.05)
    monkeypatch.setattr(termin_pause, "LIVE_TAKT_S", 0.05)
    monkeypatch.setattr(termin_pause, "HINWEIS_TAKT_S", 0.05)
    haengt = threading.Event()
    live_haengt, hinweis_haengt = threading.Event(), threading.Event()

    def holen(mid):
        live_haengt.set()
        haengt.wait(20)
        return []

    def senden(text, *, link_vorschau=False):
        hinweis_haengt.set()
        haengt.wait(20)
        return True

    monkeypatch.setattr(vexa, "segmente_holen", holen)
    monkeypatch.setattr(betreiber_hinweis, "senden", senden)
    _akte()
    jetzt = datetime.now(timezone.utc)
    # Frist laengst vorbei: die erste Wachrunde setzt den Fehler und reiht den Hinweis ein
    termin_akte.aufnahme_wuenschen("w1", "pause", "felix", jetzt - s(30))
    stopp = threading.Event()
    threads = termin_pause.starten(stopp)
    try:
        assert _warten(live_haengt.is_set) and _warten(hinweis_haengt.is_set)
        termin_akte.aufnahme_wuenschen("w1", "an", "felix", datetime.now(timezone.utc))
        start = time.monotonic()
        assert _warten(lambda: any(a[0] == "resume" for a in fake.acts), 2.0)
        assert time.monotonic() - start < 2.0
        termin_akte.aufnahme_wuenschen("w1", "notbremse", "felix", datetime.now(timezone.utc))
        assert _warten(lambda: any(a[0] == "stoppen" for a in fake.acts), 2.0)
    finally:
        stopp.set()
        haengt.set()
        for th in threads:
            th.join(timeout=5)
    assert not any(th.is_alive() for th in threads)
    assert {th.name for th in threads} == {"pausen-wache", "live-transkript", "betreiber-hinweise"}


def test_schleifen_sterben_nie(monkeypatch):
    aufrufe = {"wache": 0, "live": 0, "hinweis": 0}

    def zaehlen(name):
        def fn(jetzt):
            aufrufe[name] += 1
            if aufrufe[name] == 1:
                raise RuntimeError("einmal kaputt")
            return 0
        return fn

    monkeypatch.setattr(termin_pause, "wache_runde", zaehlen("wache"))
    monkeypatch.setattr(termin_pause, "live_runde", zaehlen("live"))
    monkeypatch.setattr(termin_pause, "hinweise_senden", zaehlen("hinweis"))
    for takt in ("WACHE_TAKT_S", "LIVE_TAKT_S", "HINWEIS_TAKT_S"):
        monkeypatch.setattr(termin_pause, takt, 0.01)
    stopp = threading.Event()
    threads = termin_pause.starten(stopp)
    assert _warten(lambda: min(aufrufe.values()) >= 5)
    stopp.set()
    for th in threads:
        th.join(timeout=2)
    assert not any(th.is_alive() for th in threads)


def test_takte_vorgaben():
    assert termin_pause.WACHE_TAKT_S == 1.0
    assert termin_pause.LIVE_TAKT_S == 5.0


def test_hinweis_arbeiter_wiederholt_gescheiterte(monkeypatch):
    versuche: list[str] = []
    ergebnis = [False]
    monkeypatch.setattr(betreiber_hinweis, "senden",
                        lambda text, *, link_vorschau=False: versuche.append(text) or ergebnis[0])
    termin_pause._hinweis_schlange.put("A")
    termin_pause.hinweise_senden(T0)
    termin_pause.hinweise_senden(T0 + s(30))
    assert versuche == ["A"]
    ergebnis[0] = True
    termin_pause.hinweise_senden(T0 + s(61))
    termin_pause.hinweise_senden(T0 + s(200))
    assert versuche == ["A", "A"]


def test_main_startet_schnellen_weg(monkeypatch):
    import signal
    stopp = threading.Event()
    monkeypatch.setattr(termin_takt, "_STOPP", stopp)
    monkeypatch.delenv("TERMIN_EINMAL", raising=False)
    gesehen: list = []
    monkeypatch.setattr(termin_pause, "starten", lambda ev: gesehen.append(ev) or [])
    monkeypatch.setattr(termin_takt, "runde", lambda jetzt: stopp.set() or {})
    alt = signal.getsignal(signal.SIGTERM)
    try:
        assert termin_takt.main() == 0
    finally:
        signal.signal(signal.SIGTERM, alt)
        termin_takt.LOG.handlers.clear()
        termin_takt.LOG.propagate = True
    assert gesehen == [stopp]
