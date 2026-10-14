"""Kalender-Sicht: Kunden-, eigene, Kollegen- und Handy-Termine in einem Zeitraum
und die Konfliktpruefung ueber alle vier Arten (Spec 2026-10-14)."""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import kalender  # noqa: E402
import kalenderquellen  # noqa: E402
import termine_eigen  # noqa: E402
import kalender_sicht  # noqa: E402

B = ZoneInfo("Europe/Berlin")
GEHEIM = "https://geheim.example/kollege-token.ics"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: ([], None))
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda nur_aktive=True: [])
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, z=7, v=60: ([], None))
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.eigene_termine, "
                     "sales_test.leads cascade")
    yield


def _lead(name="Ivan Kunde"):
    return str(server._q("insert into leads (name, source, consent_status) "
                         "values (%s, 'whatsapp', 'existing_customer') returning id",
                         (name,))[0]["id"])


def _kunde(lead, datum, uhrzeit="14:00", uid="k1", dauer=60, thema="Beratung", typ="termin"):
    server._q("insert into activities (lead_id, type, payload) values (%s,%s,%s::jsonb)",
              (lead, typ, json.dumps({"datum": datum, "uhrzeit": uhrzeit, "dauer_minuten": dauer,
                                      "thema": thema, "ort": "Büro", "uid": uid})))


def _eigen(beginn, dauer=30, titel="Steuer"):
    return termine_eigen.anlegen(titel, beginn, dauer)["termin"]


def _tag(n=1):
    return (datetime.now(B) + timedelta(days=n)).date()


def _um(n, h, m=0):
    d = _tag(n)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=B)


def _fenster(n=1):
    return _um(n, 0), _um(n, 0) + timedelta(days=1)


def _handy(uid, beginn, dauer=30, titel="Handy"):
    return {"uid": uid, "titel": titel, "ort": "", "beginn": beginn.astimezone(timezone.utc),
            "ende": (beginn + timedelta(minutes=dauer)).astimezone(timezone.utc)}


def _alle_vier(monkeypatch):
    lead = _lead()
    _kunde(lead, _tag().isoformat(), "09:00", uid="kunde-1")
    eig = _eigen(_um(1, 11), 30)
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: (
        [_handy(eig["uid"], _um(1, 11), 30), _handy("h-1", _um(1, 13), 30, "Zahnarzt")], None))
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda nur_aktive=True: [
        {"id": "q1", "anzeigename": "Ivan", "art": "kollege", "url": GEHEIM}])
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, z=7, v=60: (
        [_handy("c-1", _um(1, 15), 60, "Ivan Meeting")], None))
    return lead, eig


def test_vier_arten_mit_art_und_bearbeitbar(monkeypatch):
    lead, eig = _alle_vier(monkeypatch)
    erg = kalender_sicht.ereignisse(*_fenster())
    nach_art = {e["art"]: e for e in erg["ereignisse"]}
    assert set(nach_art) == {"kunde", "eigen", "kollege", "handy"}
    assert nach_art["kunde"]["bearbeitbar"] is True
    assert nach_art["kunde"]["titel"] == "Beratung – Ivan Kunde"
    assert nach_art["kunde"]["lead_id"] == lead
    assert nach_art["eigen"]["bearbeitbar"] is True
    assert nach_art["eigen"]["uid"] == eig["uid"]
    assert nach_art["kollege"]["bearbeitbar"] is False
    assert nach_art["kollege"]["quelle"] == "Ivan"
    assert nach_art["handy"]["bearbeitbar"] is False
    assert nach_art["handy"]["titel"] == "Zahnarzt"
    for e in erg["ereignisse"]:
        assert e["id"].startswith(e["art"] + ":")
        assert datetime.fromisoformat(e["beginn"]).utcoffset() is not None
        assert datetime.fromisoformat(e["ende"]).utcoffset() is not None
    assert erg["hinweise"] == []


def test_kollegen_adresse_wird_nie_ausgegeben(monkeypatch):
    _alle_vier(monkeypatch)
    erg = kalender_sicht.ereignisse(*_fenster())
    assert "kollege-token" not in json.dumps(erg, default=str)


def test_handy_mit_bekannter_uid_entfaellt(monkeypatch):
    _, eig = _alle_vier(monkeypatch)
    erg = kalender_sicht.ereignisse(*_fenster())
    handy = [e for e in erg["ereignisse"] if e["art"] == "handy"]
    assert [e["titel"] for e in handy] == ["Zahnarzt"]
    assert len([e for e in erg["ereignisse"] if e.get("uid") == eig["uid"]]) == 1


def test_handy_mit_uid_eines_kundentermins_entfaellt(monkeypatch):
    lead = _lead()
    _kunde(lead, _tag().isoformat(), "09:00", uid="kunde-1")
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: (
        [_handy("kunde-1", _um(1, 9), 60)], None))
    erg = kalender_sicht.ereignisse(*_fenster())
    assert [e["art"] for e in erg["ereignisse"]] == ["kunde"]


def test_abgesagter_kundentermin_fehlt():
    lead = _lead()
    _kunde(lead, _tag().isoformat(), uid="weg")
    _kunde(lead, _tag().isoformat(), "16:00", uid="bleibt")
    _kunde(lead, _tag().isoformat(), uid="weg", typ="termin_abgesagt")
    erg = kalender_sicht.ereignisse(*_fenster())
    assert [e["uid"] for e in erg["ereignisse"]] == ["bleibt"]
    assert [k["uid"] for k in kalender_sicht.kundentermine(*_fenster())] == ["bleibt"]


def test_kundentermin_ohne_lead_oder_name():
    _kunde(None, _tag().isoformat(), "10:00", uid="a")
    ohne_name = _lead("")
    _kunde(ohne_name, _tag().isoformat(), "12:00", uid="b")
    k = kalender_sicht.kundentermine(*_fenster())
    assert {t["uid"]: t["kontakt"] for t in k} == {"a": "(ohne Kontakt)", "b": "(ohne Kontakt)"}
    assert all(t["bearbeitbar"] is False for t in k)


def test_kundentermin_ohne_uid_nicht_bearbeitbar():
    _kunde(_lead(), _tag().isoformat(), uid="")
    k = kalender_sicht.kundentermine(*_fenster())
    assert len(k) == 1 and k[0]["bearbeitbar"] is False


def test_kundentermine_nach_zeitraum_gefiltert():
    lead = _lead()
    _kunde(lead, _tag(1).isoformat(), uid="morgen")
    _kunde(lead, _tag(5).isoformat(), uid="spaeter")
    assert [t["uid"] for t in kalender_sicht.kundentermine(*_fenster(1))] == ["morgen"]


@pytest.mark.parametrize("art", ["kunde", "eigen", "kollege", "handy"])
def test_konflikt_mit_jeder_art(monkeypatch, art):
    _alle_vier(monkeypatch)
    stunde = {"kunde": 9, "eigen": 11, "handy": 13, "kollege": 15}[art]
    erg = kalender_sicht.konflikte(_um(1, stunde, 10), 20)
    assert erg["unvollstaendig"] is False
    assert [k["art"] for k in erg["konflikte"]] == [art]
    assert set(erg["konflikte"][0]) >= {"art", "titel", "beginn", "ende"}


def test_konflikt_halboffen(monkeypatch):
    _alle_vier(monkeypatch)
    assert kalender_sicht.konflikte(_um(1, 8, 30), 30)["konflikte"] == []   # endet 09:00
    assert kalender_sicht.konflikte(_um(1, 10), 60)["konflikte"] == []       # Eigen 11:00 beginnt nach 11:00? nein: Ende 11:00
    assert kalender_sicht.konflikte(_um(1, 10), 61)["konflikte"] != []


def test_ausser_uid_nimmt_termin_aus(monkeypatch):
    _, eig = _alle_vier(monkeypatch)
    assert kalender_sicht.konflikte(_um(1, 11), 30)["konflikte"] != []
    erg = kalender_sicht.konflikte(_um(1, 11), 30, ausser_uid=eig["uid"])
    assert erg["konflikte"] == []


def test_ausser_uid_gilt_auch_fuer_kundentermin(monkeypatch):
    _alle_vier(monkeypatch)
    assert kalender_sicht.konflikte(_um(1, 9), 30, ausser_uid="kunde-1")["konflikte"] == []


def test_caldav_fehler_hinweis_und_unvollstaendig(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: ([], "Kalender nicht erreichbar (X)."))
    erg = kalender_sicht.ereignisse(*_fenster())
    assert "Handy-Termine gerade nicht abrufbar" in erg["hinweise"]
    k = kalender_sicht.konflikte(_um(1, 9), 30)
    assert k["unvollstaendig"] is True and k["konflikte"] == []


def test_kollegenquelle_fehler_ist_unvollstaendig(monkeypatch):
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda nur_aktive=True: [
        {"id": "q1", "anzeigename": "Ivan", "art": "kollege", "url": GEHEIM}])
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, z=7, v=60: ([], "kaputt"))
    assert kalender_sicht.konflikte(_um(1, 9), 30)["unvollstaendig"] is True
    erg = kalender_sicht.ereignisse(*_fenster())
    assert any("Ivan" in h for h in erg["hinweise"])
    assert "kollege-token" not in json.dumps(erg)


def test_sommerzeit_umstellung_offset():
    lead = _lead()
    for tag in ("2026-10-24", "2026-10-25", "2026-10-26"):
        _kunde(lead, tag, "14:00", uid=f"u{tag}")
    k = kalender_sicht.kundentermine(datetime(2026, 10, 24, tzinfo=B), datetime(2026, 10, 27, tzinfo=B))
    stand = {t["uid"]: t["beginn"].isoformat() for t in k}
    assert stand["u2026-10-24"] == "2026-10-24T14:00:00+02:00"
    assert stand["u2026-10-25"] == "2026-10-25T14:00:00+01:00"
    assert stand["u2026-10-26"] == "2026-10-26T14:00:00+01:00"
